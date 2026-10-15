import hashlib
import secrets
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select

from .cards import department_text, template_card
from .db import lock_state, now_utc
from .directory import employee_views, resolve_selection
from .models import Balance, Batch, Delivery, Ledger, Preview
from .schemas import AdjustmentRequest


def month_at(when):
    return when.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")


def require_operator(db, user_id):
    from .permissions import require_permission
    return require_permission(db, user_id, "adjustments.write")


def build_snapshot(db, user, request: AdjustmentRequest, settings, when):
    month = month_at(when)
    selected = resolve_selection(db, request.recipients)
    if selected["warnings"]:
        raise HTTPException(409, "；".join(selected["warnings"]))
    if not selected["people"]:
        raise HTTPException(422, "请至少选择一位通知对象")
    if len(selected["people"]) * len(request.person_ids) > 10000:
        raise HTTPException(422, "一次最多发送 10,000 条通知，请缩小范围后分批操作")
    people = {e["id"]: e for e in employee_views(db)}
    delta = request.points if request.operation == "plus" else -request.points
    time_text = when.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")
    rows = []
    for person_id in request.person_ids:
        person = people.get(person_id)
        if not person or person["status"] != "active":
            raise HTTPException(409, f"记分对象不可用：{person['name'] if person else person_id}")
        balance = db.get(Balance, (person_id, month))
        before = balance.total if balance else 60
        override = request.overrides.get(person_id)
        total = override if override is not None else before + delta
        if abs(total) > 2_000_000_000:
            raise HTTPException(422, "总分超出整数存储范围")
        context = {"person_name": person["name"], "person_open_id": person["open_id"],
                   "department": department_text(person),
                   "delta": delta, "points": request.points, "total": total, "reason": request.reason,
                   "operator_name": user.name, "operator_open_id": user.open_id, "month": month,
                   "time": time_text, "operation": "加分" if delta > 0 else "扣分"}
        rows.append({"person": person, "before_total": before, "final_total": total,
                     "override_total": override, "balance_version": balance.version if balance else 0,
                     "context": context, "card": template_card(context, request.operation)})
    return {"month": month, "delta": delta, "reason": request.reason, "operator_name": user.name,
            "rows": rows, "recipients": selected["people"], "message_count": len(rows) * len(selected["people"])}


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_preview(db, user_id, request, settings, when=None):
    lock_state(db)
    user = require_operator(db, user_id)
    when = when or now_utc()
    snapshot = build_snapshot(db, user, request, settings, when)
    token = secrets.token_urlsafe(32)
    preview = Preview(id=token_hash(token), owner_id=user.id, request=request.model_dump(),
                      snapshot=snapshot, created_at=when, expires_at=when + timedelta(minutes=10))
    db.add(preview)
    db.flush()
    return {"preview_token": token, "expires_at": preview.expires_at.isoformat() + "Z", **snapshot}


def commit_preview(db, user_id, token, idempotency_key, settings, when=None):
    lock_state(db)
    user = require_operator(db, user_id)
    when = when or now_utc()
    preview_id = token_hash(token)
    existing = db.scalar(select(Batch).where(Batch.operator_id == user.id, Batch.idempotency_key == idempotency_key))
    if existing:
        if existing.preview_id != preview_id:
            raise HTTPException(409, "幂等键已用于另一笔操作")
        return existing
    preview = db.get(Preview, preview_id)
    if not preview or preview.owner_id != user.id:
        raise HTTPException(404, "预览不存在")
    if preview.batch_id:
        batch = db.get(Batch, preview.batch_id)
        if not batch:
            raise HTTPException(409, "预览关联批次缺失，请核实操作记录")
        return batch
    if preview.expires_at <= when or month_at(when) != preview.snapshot["month"]:
        raise HTTPException(409, "预览已过期或月份变化，请重新预览")
    request = AdjustmentRequest.model_validate(preview.request)
    latest = build_snapshot(db, user, request, settings, preview.created_at)
    if latest != preview.snapshot:
        raise HTTPException(409, "人员、范围、模板或积分已变化，请重新预览")
    batch = Batch(operator_id=user.id, idempotency_key=idempotency_key, preview_id=preview_id,
                  month=latest["month"], delta=latest["delta"], reason=latest["reason"], snapshot=latest, created_at=when)
    db.add(batch)
    db.flush()
    for row in latest["rows"]:
        person_id = row["person"]["id"]
        balance = db.get(Balance, (person_id, latest["month"]))
        if not balance:
            balance = Balance(employee_id=person_id, month=latest["month"], total=60, version=0)
            db.add(balance)
        balance.total = row["final_total"]
        balance.version += 1
        ledger = Ledger(batch_id=batch.id, employee_id=person_id, month=latest["month"], delta=latest["delta"],
                        before_total=row["before_total"], final_total=row["final_total"],
                        override_total=row["override_total"], card=row["card"])
        db.add(ledger)
        db.flush()
        for recipient in latest["recipients"]:
            db.add(Delivery(ledger_id=ledger.id, recipient_id=recipient["id"],
                            recipient_open_id=recipient["open_id"], recipient_name=recipient["name"]))
    preview.batch_id = batch.id
    db.flush()
    return batch
