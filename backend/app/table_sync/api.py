"""Administrator-only management APIs. Heavy previews and syncs are queued."""

import threading
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import load_only

from .. import auth
from ..config import get_settings
from ..db import get_db, new_id, now_utc
from ..directory import employee_views
from ..feishu import FeishuError
from ..models import Department, Preset, SystemState, TableSyncLog, TableSyncRun, TableSyncTask
from ..permissions import require_manager
from ..presets import preset_view
from ..schemas import Selection
from .core import SourceError, read_source
from .remote import BitableClient
from .schedule import next_times, validate_cron
from .service import enqueue, task_locked

router = APIRouter(prefix="/api/table-sync", tags=["名单同步"])
_inspection_slots = threading.BoundedSemaphore(2)
RUN_FIELDS = ("id", "task_id", "task_name", "kind", "trigger", "status", "actor_name", "scheduled_at",
              "created_at", "started_at", "finished_at", "summary", "error")


class SourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_kind: Literal["preset", "selection"]
    preset_id: str | None = Field(default=None, max_length=36)
    selection: Selection = Field(default_factory=Selection)

    @model_validator(mode="after")
    def source_valid(self):
        if self.source_kind == "preset" and not self.preset_id:
            raise ValueError("请选择公共名单")
        return self


class TaskRequest(SourceRequest):
    name: str = Field(min_length=1, max_length=200)
    target_url: str = Field(min_length=1, max_length=2048)
    table_id: str = Field(default="", max_length=100)
    field_mapping: dict[str, str]
    cron: str = Field(default="0 4 * * *", max_length=100)
    config_version: int | None = Field(default=None, ge=1)

    @field_validator("name", "target_url")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("名称和链接不能为空")
        return value.strip()

    @field_validator("cron")
    @classmethod
    def cron_valid(cls, value):
        return validate_cron(value)

    @field_validator("field_mapping")
    @classmethod
    def mapping_valid(cls, value):
        if (set(value) != {"department", "name", "user_id"} or len(set(value.values())) != 3
                or any(not item or len(item) > 100 for item in value.values())):
            raise ValueError("请为部门、姓名和 user_id 分别选择三个不同的文本字段")
        return value


class InspectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048)
    table_id: str | None = Field(default=None, max_length=100)


class CronRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cron: str = Field(min_length=1, max_length=100)


class EnabledRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


def iso(value):
    return value.isoformat() + "Z" if value is not None else None


def task_view(task):
    fields = ("id", "name", "source_kind", "preset_id", "selection", "target_url", "base_token", "table_id",
              "table_name", "field_mapping", "cron", "enabled", "active_run_id", "last_status", "last_summary", "config_version")
    result = {key: getattr(task, key) for key in fields}
    result.update({key: iso(getattr(task, key)) for key in ("next_run_at", "last_run_at", "created_at", "updated_at")})
    return result


def run_view(run):
    return {key: iso(getattr(run, key)) if key.endswith("_at") else getattr(run, key) for key in RUN_FIELDS}


def _get_task(db, task_id):
    task = db.get(TableSyncTask, task_id)
    if task is None or task.deleted:
        raise HTTPException(404, "同步任务不存在")
    return task


def _get_run(db, run_id):
    run = db.get(TableSyncRun, run_id)
    if run is None:
        raise HTTPException(404, "执行记录不存在")
    return run


def _inspect(url, table_id=None):
    if not _inspection_slots.acquire(blocking=False):
        raise HTTPException(429, "已有目标表检查正在进行，请稍后重试")
    client = BitableClient(get_settings(), interval=0)
    try:
        return client.resolve_target(url, table_id=table_id or None)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except FeishuError as error:
        raise HTTPException(502, str(error)) from error
    finally:
        client.close()
        _inspection_slots.release()


@router.get("/sources")
def sources(user=Depends(auth.admin), db=Depends(get_db)):
    state = db.get(SystemState, 1)
    return {"presets": [preset_view(p, user) for p in db.scalars(select(Preset).where(Preset.scope == "public").order_by(Preset.name, Preset.id))],
            "directory": {"people": employee_views(db),
                          "departments": [{"id": d.id, "name": d.name, "parent_id": d.parent_id,
                                           "path_ids": d.path_ids, "path_names": d.path_names}
                                          for d in db.scalars(select(Department).where(Department.active.is_(True)))],
                          "last_sync_at": iso(state.last_sync_at) if state else None,
                          "last_sync_error": state.last_sync_error if state else None,
                          "sync_requested": state.sync_requested if state else False}}


@router.post("/source-preview")
def source_preview(body: SourceRequest, user=Depends(auth.admin), db=Depends(get_db)):
    try:
        snapshot = read_source(db, body.model_dump())
    except SourceError as error:
        raise HTTPException(422, str(error)) from error
    return {"source_name": snapshot["source_name"], "source_count": len(snapshot["rows"]),
            "rows": snapshot["rows"][:20], "directory_version": snapshot["directory_version"]}


@router.post("/inspect")
def inspect_target(body: InspectRequest, user=Depends(auth.admin), db=Depends(get_db)):
    # Authentication itself opens a transaction: explicitly release it before HTTP.
    db.rollback()
    return _inspect(body.url, body.table_id)


@router.post("/cron")
def cron_preview(body: CronRequest, user=Depends(auth.admin)):
    try:
        expression = validate_cron(body.cron)
        return {"cron": expression, "timezone": "Asia/Shanghai", "next_runs": [iso(t) for t in next_times(expression)]}
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get("/tasks")
def tasks(page: int = Query(1, ge=1), user=Depends(auth.admin), db=Depends(get_db)):
    where = TableSyncTask.deleted.is_(False)
    total = db.scalar(select(func.count()).select_from(TableSyncTask).where(where))
    page = min(page, max(1, (total + 19) // 20))
    # Sort only IDs; large custom selection JSON must not enter MySQL's sort buffer.
    ids = list(db.scalars(select(TableSyncTask.id).where(where).order_by(TableSyncTask.created_at.desc(), TableSyncTask.id)
                         .offset((page - 1) * 20).limit(20)))
    rows = {row.id: task_view(row) for row in db.scalars(select(TableSyncTask).where(TableSyncTask.id.in_(ids)))} if ids else {}
    return {"items": [rows[i] for i in ids], "total": total, "page": page}


@router.get("/tasks/{task_id}")
def task_detail(task_id: str, user=Depends(auth.admin), db=Depends(get_db)):
    return task_view(_get_task(db, task_id))


def _save_task(body, user, db, task_id=None):
    actor_id = user.id
    expected_version = None
    if task_id:
        current = _get_task(db, task_id)
        if current.active_run_id:
            raise HTTPException(409, "任务正在排队或运行，请完成后修改配置")
        expected_version = current.config_version
        if body.config_version is not None and body.config_version != expected_version:
            raise HTTPException(409, "任务已被其他管理员修改，请刷新后重试")
    db.rollback()
    info = _inspect(body.target_url, body.table_id)
    if not info["table_id"]:
        raise HTTPException(422, "请先选择链接内要同步的数据表")
    fields = {item["id"]: item for item in info["fields"]}
    if any(field_id not in fields or not fields[field_id]["writable"] for field_id in body.field_mapping.values()):
        raise HTTPException(422, "映射字段必须是目标数据表内真实存在的可写文本字段")
    require_manager(db, actor_id)
    if body.source_kind == "preset":
        preset = db.get(Preset, body.preset_id)
        if not preset or preset.scope != "public":
            raise HTTPException(422, "只能引用现有公共名单；任务专用范围请使用任务专属名单")
    task = task_locked(db, task_id) if task_id else TableSyncTask(id=new_id(), created_by=actor_id)
    if task_id and (task.active_run_id or task.config_version != expected_version):
        raise HTTPException(409, "任务已开始执行或配置发生变化，请刷新后重试")
    if not task_id:
        db.add(task)
        task.enabled, task.deleted, task.config_version = False, False, 1
    else:
        task.config_version += 1
    for key in ("name", "source_kind", "target_url", "field_mapping", "cron"):
        setattr(task, key, getattr(body, key))
    task.preset_id = body.preset_id if body.source_kind == "preset" else None
    task.selection = body.selection.model_dump() if body.source_kind == "selection" else {}
    task.base_token, task.table_id, task.table_name = info["base_token"], info["table_id"], info["table_name"]
    if len(task.base_token) > 100 or len(task.table_id) > 100:
        raise HTTPException(422, "目标表标识过长")
    task.target_key = task.base_token + ":" + task.table_id
    task.updated_by, task.updated_at = actor_id, now_utc()
    task.next_run_at = next_times(task.cron, count=1)[0] if task.enabled else None
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409, "该目标数据表已有同步任务，请编辑原任务或选择其他数据表") from error
    return task_view(task)


@router.post("/tasks", status_code=201)
def create_task(body: TaskRequest, user=Depends(auth.admin), db=Depends(get_db)):
    return _save_task(body, user, db)


@router.put("/tasks/{task_id}")
def update_task(task_id: str, body: TaskRequest, user=Depends(auth.admin), db=Depends(get_db)):
    return _save_task(body, user, db, task_id)


@router.patch("/tasks/{task_id}/enabled")
def enable_task(task_id: str, body: EnabledRequest, user=Depends(auth.admin), db=Depends(get_db)):
    task = task_locked(db, task_id)
    task.enabled = body.enabled
    task.next_run_at = next_times(task.cron, count=1)[0] if task.enabled else None
    task.updated_by, task.updated_at = user.id, now_utc()
    db.commit()
    return task_view(task)


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str, user=Depends(auth.admin), db=Depends(get_db)):
    task = task_locked(db, task_id)
    if task.active_run_id:
        raise HTTPException(409, "任务正在排队或运行，请完成后删除")
    task.deleted, task.enabled, task.target_key, task.next_run_at = True, False, None, None
    task.updated_by, task.updated_at = user.id, now_utc()
    db.commit()
    return {"ok": True}


def _enqueue_api(task_id, kind, user, db):
    task = task_locked(db, task_id)
    run = enqueue(db, task, kind=kind, actor_id=user.id, actor_name=user.name)
    db.commit()
    return run_view(run)


@router.post("/tasks/{task_id}/preview", status_code=202)
def preview_task(task_id: str, user=Depends(auth.admin), db=Depends(get_db)):
    return _enqueue_api(task_id, "preview", user, db)


@router.post("/tasks/{task_id}/run", status_code=202)
def run_task(task_id: str, user=Depends(auth.admin), db=Depends(get_db)):
    return _enqueue_api(task_id, "sync", user, db)


@router.get("/runs")
def runs(task_id: str | None = None, status: Literal["all", "queued", "running", "success", "unchanged", "failed", "interrupted"] = "all",
         kind: Literal["all", "preview", "sync"] = "all", page: int = Query(1, ge=1), user=Depends(auth.admin), db=Depends(get_db)):
    filters = []
    if task_id:
        filters.append(TableSyncRun.task_id == task_id)
    if status != "all":
        filters.append(TableSyncRun.status == status)
    if kind != "all":
        filters.append(TableSyncRun.kind == kind)
    total = db.scalar(select(func.count()).select_from(TableSyncRun).where(*filters))
    page = min(page, max(1, (total + 19) // 20))
    ids = list(db.scalars(select(TableSyncRun.id).where(*filters).order_by(TableSyncRun.created_at.desc(), TableSyncRun.id.desc())
                         .offset((page - 1) * 20).limit(20)))
    items = {run.id: run_view(run) for run in db.scalars(select(TableSyncRun).where(TableSyncRun.id.in_(ids))
                .options(load_only(*(getattr(TableSyncRun, key) for key in RUN_FIELDS))))} if ids else {}
    return {"items": [items[i] for i in ids], "total": total, "page": page}


@router.get("/runs/{run_id}")
def run_detail(run_id: str, user=Depends(auth.admin), db=Depends(get_db)):
    run = db.scalar(select(TableSyncRun).where(TableSyncRun.id == run_id)
                    .options(load_only(*(getattr(TableSyncRun, key) for key in RUN_FIELDS))))
    if not run:
        raise HTTPException(404, "执行记录不存在")
    return run_view(run)


@router.get("/runs/{run_id}/rows")
def run_rows(run_id: str, action: Literal["all", "create", "update", "delete", "unchanged"] = "all",
             page: int = Query(1, ge=1), user=Depends(auth.admin), db=Depends(get_db)):
    record = db.execute(select(TableSyncRun.details).where(TableSyncRun.id == run_id)).one_or_none()
    if record is None:
        raise HTTPException(404, "执行记录不存在")
    details = record.details or {}
    items = [{**row, "action": key} for key in ("create", "update", "delete", "unchanged")
             if action in {"all", key} for row in details.get(key, [])]
    total = len(items)
    page = min(page, max(1, (total + 99) // 100))
    return {"items": items[(page - 1) * 100:page * 100], "total": total, "page": page}


@router.get("/runs/{run_id}/logs")
def run_logs(run_id: str, page: int = Query(1, ge=1), user=Depends(auth.admin), db=Depends(get_db)):
    if not db.scalar(select(TableSyncRun.id).where(TableSyncRun.id == run_id)):
        raise HTTPException(404, "执行记录不存在")
    total = db.scalar(select(func.count()).select_from(TableSyncLog).where(TableSyncLog.run_id == run_id))
    page = min(page, max(1, (total + 99) // 100))
    rows = db.scalars(select(TableSyncLog).where(TableSyncLog.run_id == run_id).order_by(TableSyncLog.id)
                      .offset((page - 1) * 100).limit(100))
    return {"items": [{"id": row.id, "level": row.level, "stage": row.stage, "message": row.message,
                        "created_at": iso(row.created_at), "details": row.details} for row in rows], "total": total, "page": page}
