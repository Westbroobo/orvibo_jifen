from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import or_, select

from .db import lock_state, new_id, now_utc
from .feishu import FeishuError
from .models import Batch, Delivery, Employee, Ledger


# A margin avoids retrying on the boundary of Feishu's one-hour UUID window.
DEDUPE_WINDOW = timedelta(minutes=50)


def claim_delivery(db, settings, when=None):
    when = when or now_utc()
    lock_state(db)
    delivery = db.scalar(select(Delivery).where(or_(
        (Delivery.status == "pending") & (Delivery.next_attempt_at <= when),
        (Delivery.status == "sending") & (Delivery.lease_until <= when),
    )).order_by(Delivery.next_attempt_at, Delivery.id).limit(1).with_for_update())
    if not delivery:
        return None
    if delivery.status == "sending":
        delivery.uncertain = True
    if delivery.uncertain and delivery.first_attempt_at and when - delivery.first_attempt_at >= DEDUPE_WINDOW:
        delivery.status = "review"
        delivery.last_error = "消息状态不确定且已超过安全去重窗口，须人工核实，不再自动重试"
        return None
    if delivery.attempts >= settings.max_send_attempts:
        delivery.status = "review" if delivery.uncertain else "failed"
        delivery.last_error = "已达到自动重试次数；" + (delivery.last_error or "请查看发送结果")
        return None
    recipient = db.get(Employee, delivery.recipient_id)
    if recipient.status != "active":
        delivery.status = "review" if delivery.uncertain else "failed"
        delivery.last_error = "通知对象当前不可用，未继续发送"
        return None
    delivery.status = "sending"
    delivery.first_attempt_at = delivery.first_attempt_at or when
    delivery.attempts += 1
    delivery.lease_until = when + timedelta(seconds=90)
    delivery.lease_token = new_id()
    ledger = db.get(Ledger, delivery.ledger_id)
    return {"id": delivery.id, "lease_token": delivery.lease_token,
            "recipient_open_id": delivery.recipient_open_id, "card": ledger.card, "uuid": delivery.uuid}


def complete_delivery(db, task, settings, *, message_id=None, error=None, when=None):
    when = when or now_utc()
    lock_state(db)
    delivery = db.get(Delivery, task["id"])
    if delivery.status != "sending" or delivery.lease_token != task["lease_token"]:
        return  # A stale worker must not overwrite another worker's claim.
    delivery.lease_until = None
    delivery.lease_token = None
    if message_id:
        delivery.status = "sent"
        delivery.message_id = message_id
        delivery.sent_at = when
        delivery.last_error = None
        delivery.uncertain = False
        return
    error = error or FeishuError("未知发送错误", uncertain=True, retryable=True)
    delivery.uncertain = delivery.uncertain or error.uncertain
    delivery.last_error = str(error)
    within_window = when - delivery.first_attempt_at < DEDUPE_WINDOW
    if (error.retryable or delivery.uncertain) and delivery.attempts < settings.max_send_attempts and within_window:
        delivery.status = "pending"
        delivery.next_attempt_at = when + timedelta(seconds=min(300, 2 ** delivery.attempts * 5))
    else:
        delivery.status = "review" if delivery.uncertain else "failed"


def retry_delivery(db, delivery_id, user, when=None):
    when = when or now_utc()
    lock_state(db)
    delivery = db.get(Delivery, delivery_id)
    if not delivery:
        raise HTTPException(404, "通知记录不存在")
    ledger = db.get(Ledger, delivery.ledger_id)
    batch = db.get(Batch, ledger.batch_id)
    if user.role != "admin" and batch.operator_id != user.id:
        raise HTTPException(404, "通知记录不存在")
    if delivery.status != "failed" or delivery.uncertain:
        raise HTTPException(409, "只允许重试明确失败的通知；成功或待核实通知不可重发")
    if db.get(Employee, delivery.recipient_id).status != "active":
        raise HTTPException(409, "通知对象当前不可用")
    delivery.status = "pending"
    delivery.attempts = 0
    delivery.first_attempt_at = None
    delivery.next_attempt_at = when
    delivery.last_error = None
