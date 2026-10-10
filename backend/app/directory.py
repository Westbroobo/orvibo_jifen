from sqlalchemy import delete, select

from .config import get_settings
from .db import lock_state, now_utc
from .models import Department, Employee, EventReceipt, Membership, PermissionAudit
from .schemas import Selection
from .sync_schedule import release_sync_claim


def employee_views(db):
    departments = {d.id: d for d in db.scalars(select(Department))}
    paths = {}
    for membership in db.scalars(select(Membership)):
        department = departments.get(membership.department_id)
        if department and department.active:
            paths.setdefault(membership.employee_id, []).append({"ids": department.path_ids, "names": department.path_names})
    return [
        {"id": e.id, "open_id": e.open_id, "name": e.name, "avatar_url": e.avatar_url,
         "status": e.status, "role": e.role,
         "paths": sorted(paths.get(e.id, []), key=lambda p: "/".join(p["ids"]))}
        for e in db.scalars(select(Employee).order_by(Employee.name, Employee.id))
    ]


def in_selection_path(person, levels):
    # All selected levels must match one and the same membership path.
    if not any(levels):
        return True
    return any(all(not ids or (len(path["ids"]) > i and path["ids"][i] in ids)
                   for i, ids in enumerate(levels)) for path in person["paths"])


def resolve_selection(db, selection: Selection):
    warnings = []
    active_departments = {d.id: d for d in db.scalars(select(Department).where(Department.active.is_(True)))}
    for level, ids in enumerate(selection.levels):
        for department_id in ids:
            department = active_departments.get(department_id)
            if not department or len(department.path_ids) != level + 1:
                warnings.append(f"第 {level + 1} 级部门已失效或层级变化：{department_id}")
    people = employee_views(db)
    by_id = {p["id"]: p for p in people}
    matches = {p["id"] for p in people if p["status"] == "active" and in_selection_path(p, selection.levels)}
    if selection.mode == "all":
        # Explicit department selection is required. Empty filters never mean company-wide.
        chosen = matches if any(selection.levels) else set()
    else:
        chosen = matches & set(selection.person_ids)
    for person_id in set(selection.person_ids if selection.mode == "selected" else []) | set(selection.extra_ids):
        person = by_id.get(person_id)
        if not person or person["status"] != "active":
            warnings.append(f"人员不可用：{person['name'] if person else person_id}")
        elif person_id in selection.person_ids and person_id not in matches and person_id not in selection.extra_ids:
            warnings.append(f"人员已不符合部门范围：{person['name']}")
    chosen |= {i for i in selection.extra_ids if i in by_id and by_id[i]["status"] == "active"}
    return {"people": [by_id[i] for i in sorted(chosen)], "warnings": sorted(set(warnings))}


def feishu_status(data):
    status = data.get("status", {})
    if status.get("is_resigned"):
        return "resigned"
    if status.get("is_exited") or status.get("is_frozen"):
        return "inactive"
    # Missing employee-status scope must not turn unknown people into active ones.
    if "is_resigned" not in status:
        return "unknown"
    return "active"


def apply_directory(db, departments, users, settings=None, expected_version=None, expected_sync_token=None):
    settings = settings or get_settings()
    state = lock_state(db)
    if expected_sync_token is not None and state.sync_lease_token != expected_sync_token:
        return False
    if expected_version is not None and state.directory_version != expected_version:
        # A real-time event landed while full sync was fetching. Do not overwrite it.
        state.sync_requested = True
        release_sync_claim(state)
        state.last_sync_error = "同步期间收到人员变更，等待重新同步"
        return False
    department_map = {d["open_department_id"]: d for d in departments}
    memo = {"0": ([], [])}

    def path_for(department_id, visiting=None):
        if department_id in memo:
            return memo[department_id]
        visiting = set() if visiting is None else visiting
        if department_id in visiting or department_id not in department_map:
            raise ValueError("部门树包含循环或缺失父部门，同步未应用")
        data = department_map[department_id]
        ids, names = path_for(data.get("parent_department_id") or "0", visiting | {department_id})
        memo[department_id] = (ids + [department_id], names + [data["name"]])
        return memo[department_id]

    for department_id in department_map:
        path_for(department_id)
    existing_departments = {d.id: d for d in db.scalars(select(Department))}
    for department in existing_departments.values():
        department.active = department.id in department_map
    for department_id, data in department_map.items():
        department = existing_departments.get(department_id)
        if not department:
            department = Department(id=department_id, name=data["name"])
            db.add(department)
        department.name = data["name"]
        department.parent_id = data.get("parent_department_id") or "0"
        department.path_ids, department.path_names = memo[department_id]
        department.active = True
    existing = {e.open_id: e for e in db.scalars(select(Employee))}
    seen = set()
    for data in users:
        open_id = data["open_id"]
        seen.add(open_id)
        employee = existing.get(open_id)
        if not employee:
            employee = Employee(open_id=open_id, name=data["name"])
            db.add(employee)
            db.flush()
            existing[open_id] = employee
        employee.user_id = data.get("user_id") or None
        employee.name = data["name"]
        employee.avatar_url = data.get("avatar", {}).get("avatar_72", "")
        employee.feishu_status = data.get("status", {})
        employee.status = feishu_status(data)
        employee.updated_at = now_utc()
        db.execute(delete(Membership).where(Membership.employee_id == employee.id))
        for department_id in set(data.get("department_ids", [])):
            if department_id in department_map:
                db.add(Membership(employee_id=employee.id, department_id=department_id))
    for open_id, employee in existing.items():
        if open_id not in seen and employee.status != "resigned":
            employee.status = "unknown"
    if not state.bootstrap_done:
        by_user_id = {e.user_id: e for e in existing.values() if e.user_id}
        for user_id in settings.bootstrap_admins:
            employee = by_user_id.get(user_id)
            if employee and employee.status == "active" and employee.role != "admin":
                db.add(PermissionAudit(employee_id=employee.id, old_role=employee.role, new_role="admin"))
                employee.role = "admin"
        state.bootstrap_done = bool(settings.bootstrap_admins) and all(
            i in by_user_id and by_user_id[i].status == "active" for i in settings.bootstrap_admins
        )
    state.directory_version += 1
    state.last_sync_at = now_utc()
    state.last_sync_error = None
    release_sync_claim(state)
    state.sync_retry_at = None
    return True


def apply_contact_event(db, event_id, event_type, data):
    state = lock_state(db)
    if db.get(EventReceipt, event_id):
        return
    db.add(EventReceipt(id=event_id))
    state.sync_requested = True
    state.directory_version += 1
    if event_type == "contact.user.deleted_v3":
        user = data.get("object", data)
        open_id = user.get("open_id")
        if not open_id and isinstance(user.get("user_id"), dict):
            open_id = user["user_id"].get("open_id")
        if not open_id:
            raise ValueError("离职事件缺少 open_id")
        employee = db.scalar(select(Employee).where(Employee.open_id == open_id))
        if employee:
            employee.status = "resigned"
            employee.updated_at = now_utc()
    elif event_type == "contact.user.updated_v3":
        user = data.get("object", data)
        open_id = user.get("open_id")
        employee = db.scalar(select(Employee).where(Employee.open_id == open_id)) if open_id else None
        if employee:
            employee.status = "unknown"  # Block changes until full authoritative refresh.
