"""Read-only directory snapshots and deterministic table reconciliation."""

import hashlib
import json
from collections import defaultdict

from pydantic import ValidationError
from sqlalchemy import select

from ..directory import in_selection_path, resolve_selection
from ..models import Department, Employee, Membership, Preset, SystemState
from ..schemas import Selection


class SourceError(ValueError):
    pass


def _signature(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _selection(db, config):
    kind = config.get("source_kind")
    if kind == "preset":
        preset = db.get(Preset, config.get("preset_id"), populate_existing=True)
        if preset is None or preset.scope != "public":
            raise SourceError("所选公共名单已不存在，请重新选择名单")
        raw, name = preset.selection, preset.name
    elif kind == "selection":
        raw, name = config.get("selection"), "独立配置范围"
    else:
        raise SourceError("名单来源无效")
    try:
        return Selection.model_validate(raw), name
    except (ValidationError, TypeError, ValueError) as error:
        raise SourceError("名单范围配置无效，请检查部门和人员选择") from error


def _validate_selection(db, selection):
    departments = {d.id: d for d in db.scalars(select(Department))}
    if selection.match_mode == "union":
        chosen = selection.department_ids
        invalid = [i for i in chosen if i not in departments or not departments[i].active]
    else:
        invalid = [i for level, ids in enumerate(selection.levels) for i in ids
                   if i not in departments or not departments[i].active
                   or len(departments[i].path_ids) != level + 1]
    if invalid:
        raise SourceError("名单包含失效或层级变化的部门，请先修正名单")

    explicit = set(selection.extra_ids)
    if selection.match_mode == "union" or selection.mode == "selected":
        explicit.update(selection.person_ids)
    explicit_people = dict(db.execute(select(Employee.id, Employee.status)
                                     .where(Employee.id.in_(explicit))).all()) if explicit else {}
    if explicit - explicit_people.keys():
        raise SourceError("名单包含已不存在的指定人员，请先修正名单")
    if any(status == "unknown" for status in explicit_people.values()):
        raise SourceError("名单中有人员状态待核实，请等待通讯录同步完成")

    # Contact events temporarily mark users unknown. Do not interpret that as
    # a departure and remove their remote row while directory refresh is pending.
    if selection.match_mode == "union":
        has_department_range = bool(selection.department_ids)
    else:
        has_department_range = selection.mode == "all" and any(selection.levels)
    if has_department_range:
        unknown_paths = db.execute(select(Employee.id, Department.path_ids)
                                  .join(Membership, Membership.employee_id == Employee.id)
                                  .join(Department, Department.id == Membership.department_id)
                                  .where(Employee.status == "unknown", Department.active.is_(True)))
        for _, path_ids in unknown_paths:
            if selection.match_mode == "union":
                relevant = bool(set(selection.department_ids).intersection(path_ids))
            else:
                relevant = in_selection_path({"paths": [{"ids": path_ids}]}, selection.levels)
            if relevant:
                raise SourceError("所选部门有人员状态待核实，请等待通讯录同步完成")


def read_source(db, config):
    """Resolve the same public/custom selection used by the console, without writes."""
    before = db.execute(select(SystemState.directory_version, SystemState.last_sync_at)
                        .where(SystemState.id == 1)).one_or_none()
    if before is None or before.last_sync_at is None:
        raise SourceError("通讯录尚未完成首次同步，不能执行名单同步")
    selection, source_name = _selection(db, config)
    _validate_selection(db, selection)
    resolved = resolve_selection(db, selection)
    if any(warning.startswith("人员已不符合部门范围：") for warning in resolved["warnings"]):
        raise SourceError("指定人员已不符合名单的部门范围，请先修正名单")
    people = resolved["people"]
    identifiers = dict(db.execute(select(Employee.id, Employee.user_id)
                                 .where(Employee.id.in_([p["id"] for p in people]))).all()) if people else {}
    rows = []
    seen = set()
    for person in people:
        user_id = identifiers.get(person["id"])
        if not isinstance(user_id, str) or not user_id.strip():
            raise SourceError(f"人员“{person['name']}”缺少 user_id，请先完善通讯录数据")
        if user_id in seen:
            raise SourceError("来源名单存在重复 user_id，请先检查通讯录数据")
        seen.add(user_id)
        names = sorted({p["names"][-1] for p in person["paths"] if p["names"]})
        rows.append({"user_id": user_id, "name": person["name"],
                     "department": "；".join(names) or "直属企业"})
    rows.sort(key=lambda row: row["user_id"])
    after = db.scalar(select(SystemState.directory_version).where(SystemState.id == 1))
    # Re-read the public rule too: editing a preset need not increment directory_version.
    current_selection, current_name = _selection(db, config)
    if after != before.directory_version or current_selection != selection or current_name != source_name:
        raise SourceError("读取期间通讯录或名单发生变化，请稍后重新执行")
    return {"rows": rows, "directory_version": after, "source_name": source_name,
            "source_signature": _signature({"selection": selection.model_dump(), "rows": rows,
                                             "source_name": source_name})}


def check_source(db, snapshot, config):
    current = read_source(db, config)
    if (current["directory_version"] != snapshot["directory_version"]
            or current["source_signature"] != snapshot["source_signature"]):
        raise SourceError("执行期间通讯录或名单发生变化，本次停止后续写入，请重新执行")


def _row(row):
    return {key: row.get(key, "") for key in ("user_id", "name", "department")}


def diff_rows(source_rows, remote_rows):
    """Keep one stable row per source ID and remove all other dedicated-table rows."""
    source = {}
    for item in source_rows:
        row = _row(item)
        user_id = row["user_id"]
        if (not all(isinstance(value, str) for value in row.values())
                or not user_id.strip() or user_id in source):
            raise SourceError("来源名单的 user_id 为空或重复，不能计算同步差异")
        source[user_id] = row
    by_id = defaultdict(list)
    record_ids = set()
    for item in remote_rows:
        record_id = item.get("record_id")
        if not isinstance(record_id, str) or not record_id or record_id in record_ids:
            raise SourceError("目标记录 ID 缺失或重复，未取得完整目标数据")
        record_ids.add(record_id)
        row = {"record_id": record_id, **_row(item)}
        if not all(isinstance(value, str) for value in row.values()):
            raise SourceError("目标表字段不是文本，不能计算同步差异")
        by_id[row["user_id"]].append(row)
    result = {"create": [], "update": [], "delete": [], "unchanged": []}
    duplicates = 0
    for user_id in sorted(source):
        desired = source[user_id]
        matches = by_id.pop(user_id, [])
        if not matches:
            result["create"].append(desired.copy())
            continue
        # Prefer an already-correct record, then a stable ID. Unchanged records
        # retain both their record ID and all columns outside this mapping.
        matches.sort(key=lambda row: (_row(row) != desired, row["record_id"]))
        keep, *extras = matches
        key = "unchanged" if _row(keep) == desired else "update"
        result[key].append({"record_id": keep["record_id"], **desired})
        duplicates += len(extras)
        result["delete"].extend({**row, "reason": "duplicate"} for row in extras)
    for user_id in sorted(by_id):
        extras = by_id[user_id]
        duplicates += max(0, len(extras) - 1) if user_id.strip() else 0
        result["delete"].extend({**row, "reason": "not_in_source" if user_id.strip() else "empty_user_id"}
                                for row in extras)
    result["delete"].sort(key=lambda row: row["record_id"])
    result["summary"] = {"source": len(source_rows), "target": len(remote_rows),
                         "create": len(result["create"]), "update": len(result["update"]),
                         "delete": len(result["delete"]), "duplicate": duplicates,
                         "unchanged": len(result["unchanged"])}
    return result
