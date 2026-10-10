from collections import Counter
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import or_, select

from .adjustments import require_operator
from .cancellations import cancel_score
from .db import lock_state, new_id, now_utc
from .feishu import FeishuError
from .models import Balance, Batch, Delivery, Ledger, LedgerCancellation, MessageRecall

RECALL_WINDOW = timedelta(hours=24)


def recall_deadline(delivery):
    return delivery.sent_at + RECALL_WINDOW if delivery.sent_at else None


def can_recall(delivery, recall=None, when=None):
    when = when or now_utc()
    deadline = recall_deadline(delivery)
    return bool(delivery.status == "sent" and delivery.message_id and deadline and when < deadline
                and (not recall or recall.status in {"failed", "review"} and recall.error_code != 230009))


def score_results(db, batch_id):
    rows = db.execute(select(Ledger, LedgerCancellation).outerjoin(LedgerCancellation).where(
        Ledger.batch_id == batch_id)).all()
    return [{"ledger_id": ledger.id, "person_id": ledger.employee_id,
             "original_total": ledger.final_total, "cancelled": cancellation is not None,
             "cancelled_at": cancellation.cancelled_at.isoformat() + "Z" if cancellation else None,
             "current_total": db.get(Balance, (ledger.employee_id, ledger.month)).total}
            for ledger, cancellation in rows]


def recall_summary(db, batch_id, when=None):
    when = when or now_utc()
    rows = db.execute(select(Delivery, MessageRecall).join(Ledger, Delivery.ledger_id == Ledger.id)
                      .outerjoin(MessageRecall, MessageRecall.delivery_id == Delivery.id)
                      .where(Ledger.batch_id == batch_id)).all()
    scores = score_results(db, batch_id)
    return {"statuses": dict(Counter(recall.status for _, recall in rows if recall)),
            "available": sum(can_recall(delivery, recall, when) for delivery, recall in rows),
            "cancelled_scores": sum(row["cancelled"] for row in scores), "scores": scores}


def enqueue_recall(db, delivery, user, when):
    recall = db.get(MessageRecall, delivery.id)
    if recall and recall.status in {"pending", "recalling", "recalled"}:
        return False  # Duplicate confirmation never resets an active/successful task.
    if not can_recall(delivery, recall, when):
        raise HTTPException(409, "只可撤回 24 小时内已发送且有消息 ID 的卡片；请刷新查看最新状态")
    if recall:
        recall.status = "pending"
        recall.attempts = 0
        recall.next_attempt_at = when
        recall.lease_until = recall.lease_token = None
        recall.last_error = None
        recall.error_code = None
    else:
        db.add(MessageRecall(delivery_id=delivery.id, actor_id=user.id, status="pending",
                             requested_at=when, next_attempt_at=when))
    return True


def cancel_if_fully_recalled(db, ledger, actor_id, when, *, source="recall"):
    rows = db.execute(select(Delivery.status, MessageRecall.status).outerjoin(MessageRecall).where(
        Delivery.ledger_id == ledger.id)).all()
    if not rows or any(sent != "sent" or recalled != "recalled" for sent, recalled in rows):
        return False
    return cancel_score(db, ledger, actor_id, when, source=source)


def request_recall(db, user_id, *, delivery_id=None, batch_id=None, when=None):
    when = when or now_utc()
    lock_state(db)
    user = require_operator(db, user_id)
    if delivery_id:
        delivery = db.get(Delivery, delivery_id)
        ledger = db.get(Ledger, delivery.ledger_id) if delivery else None
        batch = db.get(Batch, ledger.batch_id) if ledger else None
    else:
        batch = db.get(Batch, batch_id)
    if not batch or user.role != "admin" and batch.operator_id != user.id:
        raise HTTPException(404, "操作记录不存在")
    if delivery_id:
        accepted = int(enqueue_recall(db, delivery, user, when))
    else:
        rows = db.execute(select(Delivery, MessageRecall).join(Ledger, Delivery.ledger_id == Ledger.id)
                          .outerjoin(MessageRecall, MessageRecall.delivery_id == Delivery.id)
                          .where(Ledger.batch_id == batch.id)).all()
        accepted = sum(enqueue_recall(db, delivery, user, when) for delivery, recall in rows
                       if can_recall(delivery, recall, when))
        if not accepted and not any(recall and recall.status in {"pending", "recalling", "recalled"} for _, recall in rows):
            raise HTTPException(409, "本批次没有可撤回的已发送卡片")
    db.flush()
    return {"accepted": accepted, "batch_id": batch.id}


def reconcile_recalled_score(db, when=None):
    """Apply the new rule once to records whose cards were already recalled."""
    when = when or now_utc()
    lock_state(db)
    unfinished = select(Delivery.id).outerjoin(MessageRecall).where(
        Delivery.ledger_id == Ledger.id, or_(Delivery.status != "sent", MessageRecall.status.is_(None),
                                            MessageRecall.status != "recalled")).correlate(Ledger).exists()
    row = db.execute(select(Ledger, MessageRecall).join(Delivery, Delivery.ledger_id == Ledger.id).join(
        MessageRecall, MessageRecall.delivery_id == Delivery.id).outerjoin(
        LedgerCancellation, LedgerCancellation.ledger_id == Ledger.id).where(
        MessageRecall.status == "recalled", LedgerCancellation.ledger_id.is_(None), ~unfinished).order_by(
        MessageRecall.requested_at, MessageRecall.delivery_id).limit(1)).first()
    if not row:
        return False
    ledger, recall = row
    return cancel_if_fully_recalled(db, ledger, recall.actor_id, when, source="legacy_recall")


def claim_recall(db, settings, when=None):
    when = when or now_utc()
    lock_state(db)
    recall = db.scalar(select(MessageRecall).where(or_(
        (MessageRecall.status == "pending") & (MessageRecall.next_attempt_at <= when),
        (MessageRecall.status == "recalling") & (MessageRecall.lease_until <= when),
    )).order_by(MessageRecall.next_attempt_at, MessageRecall.delivery_id).limit(1).with_for_update())
    if not recall:
        return None
    if recall.status == "recalling":
        recall.uncertain = True
    delivery = db.get(Delivery, recall.delivery_id)
    if recall_deadline(delivery) is None or when >= recall_deadline(delivery):
        recall.status = "review" if recall.uncertain else "failed"
        recall.last_error = "已超过系统 24 小时撤回时限，请核实飞书中的消息状态"
        return None
    if recall.attempts >= settings.max_send_attempts:
        recall.status = "review" if recall.uncertain else "failed"
        recall.last_error = "已达到撤回自动重试次数；" + (recall.last_error or "请核实消息状态")
        return None
    recall.status = "recalling"
    recall.attempts += 1
    recall.lease_until = when + timedelta(seconds=90)
    recall.lease_token = new_id()
    return {"delivery_id": delivery.id, "message_id": delivery.message_id, "lease_token": recall.lease_token}


def complete_recall(db, task, settings, *, error=None, when=None):
    when = when or now_utc()
    lock_state(db)
    recall = db.get(MessageRecall, task["delivery_id"])
    if recall.status != "recalling" or recall.lease_token != task["lease_token"]:
        return
    recall.lease_until = recall.lease_token = None
    if error is None:
        recall.status = "recalled"
        recall.recalled_at = when
        recall.last_error = None
        recall.error_code = None
        recall.uncertain = False
        delivery = db.get(Delivery, recall.delivery_id)
        ledger = db.get(Ledger, delivery.ledger_id)
        db.flush()
        cancel_if_fully_recalled(db, ledger, recall.actor_id, when)
        return
    recall.last_error = str(error)
    recall.error_code = error.code
    recall.uncertain = recall.uncertain or error.uncertain
    delivery = db.get(Delivery, recall.delivery_id)
    if (error.retryable or error.uncertain) and recall.attempts < settings.max_send_attempts and when < recall_deadline(delivery):
        recall.status = "pending"
        recall.next_attempt_at = when + timedelta(seconds=min(300, 2 ** recall.attempts * 5))
    else:
        recall.status = "review" if recall.uncertain else "failed"


def run_recall_once(client, settings, factory):
    with factory.begin() as db:
        if reconcile_recalled_score(db):
            return True
        task = claim_recall(db, settings)
    if not task:
        return False
    error = None
    try:
        if not settings.demo_mode:
            client.recall_message(task["message_id"])
    except FeishuError as failure:
        error = failure
    except Exception:
        error = FeishuError("撤回结果不确定，请核实消息状态", retryable=True, uncertain=True)
    with factory.begin() as db:
        complete_recall(db, task, settings, error=error)
    return True
