from collections import Counter
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from . import auth
from .adjustments import commit_preview, create_preview, month_at, require_operator
from .config import get_settings
from .db import get_db, lock_state, now_utc
from .delivery import retry_delivery
from .directory import employee_views, in_selection_path, resolve_selection
from .models import Balance, Batch, Delivery, Employee, Ledger, MessageRecall, PermissionAudit, Preset, SystemState
from .recall import can_recall, recall_deadline, recall_summary, request_recall
from .schemas import AdjustmentRequest, CommitRequest, PresetRequest, RoleRequest, Selection

settings = get_settings()


@asynccontextmanager
async def lifespan(app):
    settings.validate_runtime()
    yield


app = FastAPI(title="ORVIBO_员工积分系统", version="1.0.0", lifespan=lifespan)
app.include_router(auth.router)


@app.middleware("http")
async def headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/api/health")
def health(db=Depends(get_db)):
    if not db.get(SystemState, 1):
        raise HTTPException(503, "数据库尚未初始化，请手动执行 database/schema.sql")
    return {"ok": True}


@app.get("/api/public-config")
def public_config():
    return {"demo_mode": settings.demo_mode, "configured": bool(settings.feishu_app_id)}


@app.get("/api/directory")
def directory(user=Depends(auth.operator), db=Depends(get_db)):
    from .models import Department
    state = db.get(SystemState, 1)
    return {"people": employee_views(db),
            "departments": [{"id": d.id, "name": d.name, "parent_id": d.parent_id,
                             "path_ids": d.path_ids, "path_names": d.path_names}
                            for d in db.scalars(select(Department).where(Department.active.is_(True)))],
            "last_sync_at": state.last_sync_at.isoformat() + "Z" if state.last_sync_at else None,
            "last_sync_error": state.last_sync_error, "sync_requested": state.sync_requested,
            "events_connected_at": state.events_connected_at.isoformat() + "Z" if state.events_connected_at else None}


@app.get("/api/people")
def people(q: str = "", include_unavailable: bool = False, user=Depends(auth.operator), db=Depends(get_db)):
    return [p for p in employee_views(db) if q.strip().casefold() in p["name"].casefold()
            and (include_unavailable and user.role == "admin" or p["status"] == "active")]


@app.post("/api/ranges/resolve")
def resolve(selection: Selection, user=Depends(auth.operator), db=Depends(get_db)):
    return resolve_selection(db, selection)


@app.get("/api/balances")
def balances(user=Depends(auth.operator), db=Depends(get_db)):
    month = month_at(now_utc())
    rows = db.scalars(select(Balance).where(Balance.month == month)).all()
    return {"month": month, "totals": {b.employee_id: b.total for b in rows},
            "versions": {b.employee_id: b.version for b in rows}}


@app.get("/api/presets")
def presets(user=Depends(auth.operator), db=Depends(get_db)):
    return [{"id": p.id, "name": p.name, "selection": p.selection}
            for p in db.scalars(select(Preset).where(Preset.owner_id == user.id).order_by(Preset.updated_at.desc()))]


def save_preset(db, user, body, preset=None):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "配置名称不能为空")
    if not preset:
        preset = Preset(owner_id=user.id, name=name, selection=body.selection.model_dump())
        db.add(preset)
    else:
        preset.name, preset.selection, preset.updated_at = name, body.selection.model_dump(), now_utc()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "已有同名个人配置") from exc
    return {"id": preset.id, "name": preset.name, "selection": preset.selection}


@app.post("/api/presets", status_code=201)
def new_preset(body: PresetRequest, user=Depends(auth.operator), db=Depends(get_db)):
    return save_preset(db, user, body)


def owned_preset(db, user, preset_id):
    preset = db.get(Preset, preset_id)
    if not preset or preset.owner_id != user.id:
        raise HTTPException(404, "配置不存在")
    return preset


@app.put("/api/presets/{preset_id}")
def update_preset(preset_id: str, body: PresetRequest, user=Depends(auth.operator), db=Depends(get_db)):
    return save_preset(db, user, body, owned_preset(db, user, preset_id))


@app.delete("/api/presets/{preset_id}")
def delete_preset(preset_id: str, user=Depends(auth.operator), db=Depends(get_db)):
    db.delete(owned_preset(db, user, preset_id))
    db.commit()
    return {"ok": True}


@app.post("/api/adjustments/preview")
def preview(body: AdjustmentRequest, user=Depends(auth.operator), db=Depends(get_db)):
    result = create_preview(db, user.id, body, settings)
    db.commit()
    return result


@app.post("/api/adjustments", status_code=201)
def confirm(body: CommitRequest, user=Depends(auth.operator), db=Depends(get_db)):
    batch = commit_preview(db, user.id, body.preview_token, body.idempotency_key, settings)
    db.commit()
    return {"id": batch.id, "message_count": batch.snapshot["message_count"]}


def accessible_batch(db, batch_id, user):
    batch = db.get(Batch, batch_id)
    if not batch or user.role != "admin" and batch.operator_id != user.id:
        raise HTTPException(404, "操作记录不存在")
    return batch


@app.get("/api/adjustments")
def history(page: int = Query(1, ge=1), user=Depends(auth.operator), db=Depends(get_db)):
    statement = select(Batch)
    if user.role != "admin":
        statement = statement.where(Batch.operator_id == user.id)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    result = []
    when = now_utc()
    for batch in db.scalars(statement.order_by(Batch.created_at.desc(), Batch.id).offset((page - 1) * 20).limit(20)):
        statuses = db.scalars(select(Delivery.status).join(Ledger).where(Ledger.batch_id == batch.id)).all()
        summary = recall_summary(db, batch.id, when)
        result.append({"id": batch.id, "month": batch.month, "delta": batch.delta, "reason": batch.reason,
                       "created_at": batch.created_at.isoformat() + "Z", "operator_name": batch.snapshot["operator_name"],
                       "names": [r["person"]["name"] for r in batch.snapshot["rows"]],
                       "message_count": batch.snapshot["message_count"], "statuses": dict(Counter(statuses)),
                       "recall_statuses": summary["statuses"], "recall_available": summary["available"],
                       "cancelled_scores": summary["cancelled_scores"]})
    return {"items": result, "total": total, "page": page}


@app.get("/api/adjustments/{batch_id}")
def batch_detail(batch_id: str, page: int = Query(1, ge=1), user=Depends(auth.operator), db=Depends(get_db)):
    batch = accessible_batch(db, batch_id, user)
    base = select(Delivery, Ledger.employee_id, MessageRecall).join(Ledger, Delivery.ledger_id == Ledger.id).outerjoin(
        MessageRecall, MessageRecall.delivery_id == Delivery.id).where(Ledger.batch_id == batch.id)
    statuses = db.scalars(select(Delivery.status).join(Ledger).where(Ledger.batch_id == batch.id)).all()
    rows = []
    when = now_utc()
    summary = recall_summary(db, batch.id, when)
    for delivery, person_id, recall in db.execute(base.order_by(Delivery.recipient_name, Delivery.id).offset((page - 1) * 100).limit(100)):
        rows.append({"id": delivery.id, "person_id": person_id, "recipient_name": delivery.recipient_name,
                     "status": delivery.status, "attempts": delivery.attempts, "message_id": delivery.message_id,
                     "sent_at": delivery.sent_at.isoformat() + "Z" if delivery.sent_at else None,
                     "last_error": delivery.last_error,
                     "recall_status": recall.status if recall else None,
                     "recall_error": recall.last_error if recall else None,
                     "recalled_at": recall.recalled_at.isoformat() + "Z" if recall and recall.recalled_at else None,
                     "recall_deadline": recall_deadline(delivery).isoformat() + "Z" if recall_deadline(delivery) else None,
                     "can_recall": can_recall(delivery, recall, when)})
    return {"id": batch.id, "snapshot": batch.snapshot, "created_at": batch.created_at.isoformat() + "Z",
            "deliveries": rows, "statuses": dict(Counter(statuses)), "total": len(statuses), "page": page,
            "recall_statuses": summary["statuses"], "recall_available": summary["available"],
            "cancelled_scores": summary["cancelled_scores"], "scores": summary["scores"]}


@app.post("/api/adjustments/{batch_id}/recall", status_code=202)
def recall_batch(batch_id: str, user=Depends(auth.operator), db=Depends(get_db)):
    result = request_recall(db, user.id, batch_id=batch_id)
    db.commit()
    return result


@app.post("/api/deliveries/{delivery_id}/recall", status_code=202)
def recall_delivery(delivery_id: str, user=Depends(auth.operator), db=Depends(get_db)):
    result = request_recall(db, user.id, delivery_id=delivery_id)
    db.commit()
    return result


@app.post("/api/deliveries/{delivery_id}/retry")
def retry(delivery_id: str, user=Depends(auth.operator), db=Depends(get_db)):
    lock_state(db)
    user = require_operator(db, user.id)
    retry_delivery(db, delivery_id, user)
    db.commit()
    return {"ok": True}


@app.put("/api/admin/people/{person_id}/role")
def update_role(person_id: str, body: RoleRequest, user=Depends(auth.admin), db=Depends(get_db)):
    lock_state(db)
    actor = require_operator(db, user.id)
    if actor.role != "admin":
        raise HTTPException(403, "仅管理员可操作")
    target = db.get(Employee, person_id)
    if not target:
        raise HTTPException(404, "人员不存在")
    if body.role != "none" and target.status != "active":
        raise HTTPException(409, "只可为在职可用人员授权")
    if target.role == "admin" and target.status == "active" and body.role != "admin":
        count = db.scalar(select(func.count()).select_from(Employee).where(Employee.role == "admin", Employee.status == "active"))
        if count <= 1:
            raise HTTPException(409, "不能移除最后一名有效管理员")
    if target.role != body.role:
        db.add(PermissionAudit(actor_id=actor.id, employee_id=target.id, old_role=target.role, new_role=body.role))
        target.role = body.role
    db.commit()
    return {"ok": True}


@app.post("/api/admin/directory/sync")
def request_sync(user=Depends(auth.admin), db=Depends(get_db)):
    state = lock_state(db)
    if require_operator(db, user.id).role != "admin":
        raise HTTPException(403, "仅管理员可操作")
    state.sync_requested = True
    db.commit()
    return {"ok": True}
