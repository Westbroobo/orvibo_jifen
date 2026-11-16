from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_, select

from .permissions import require_permission, require_batch_operation
from .cancellations import cancel_score
from .db import lock_state, new_id, now_utc
from .feishu import FeishuError
from .models import Balance, Batch, Delivery, Ledger, LedgerCancellation, MessageRecall

RECALL_WINDOW = timedelta(hours=24)


def recall_deadline(delivery):
    return delivery.sent_at + RECALL_WINDOW if delivery and delivery.sent_at else None


def can_recall(delivery, recall=None, when=None):
    when = when or now_utc()
    deadline = recall_deadline(delivery)
    return bool(delivery and delivery.status == "sent" and delivery.message_id and deadline and when < deadline
                and (not recall or recall.status in {"failed", "review"} and recall.error_code != 230009))


def score_results(db, batch_id):
    # Read only score fields, not ledger card JSON, and fetch all balances together.
    rows = db.execute(select(Ledger.id, Ledger.employee_id, Ledger.final_total, Balance.total,
                             LedgerCancellation.ledger_id, LedgerCancellation.cancelled_at)
                      .select_from(Ledger)
                      .outerjoin(Balance, and_(Balance.employee_id == Ledger.employee_id, Balance.month == Ledger.month))
                      .outerjoin(LedgerCancellation, LedgerCancellation.ledger_id == Ledger.id)
                      .where(Ledger.batch_id == batch_id)).all()
    results = []
    for ledger_id, employee_id, original_total, current_total, cancelled_id, cancelled_at in rows:
        if current_total is None:
            raise HTTPException(409, "积分余额缺失，请核实这笔操作的记录")
        results.append({"ledger_id": ledger_id, "person_id": employee_id,
                        "original_total": original_total, "cancelled": cancelled_id is not None,
                        "cancelled_at": cancelled_at.isoformat() + "Z" if cancelled_at else None,
                        "current_total": current_total})
    return results


def batch_summaries(db, batch_ids, when=None):
    """Aggregate the visible batches without loading every delivery or score row."""
    result = {batch_id: {"delivery_statuses": {}, "statuses": {}, "available": 0, "cancelled_scores": 0}
              for batch_id in batch_ids}
    if not result:
        return result
    when = when or now_utc()
    # Keep this predicate equivalent to can_recall, including NULL retry error codes
    # and the strict 24-hour boundary. LENGTH also accepts nonempty whitespace IDs.
    available = and_(Delivery.status == "sent", func.length(Delivery.message_id) > 0,
                     Delivery.sent_at > when - RECALL_WINDOW,
                     or_(MessageRecall.delivery_id.is_(None),
                         and_(MessageRecall.status.in_(("failed", "review")),
                              or_(MessageRecall.error_code.is_(None), MessageRecall.error_code != 230009))))
    rows = db.execute(select(Ledger.batch_id, Delivery.status, MessageRecall.status, func.count(),
                             func.sum(case((available, 1), else_=0)))
                      .select_from(Ledger)
                      .join(Delivery, Delivery.ledger_id == Ledger.id)
                      .outerjoin(MessageRecall, MessageRecall.delivery_id == Delivery.id)
                      .where(Ledger.batch_id.in_(result))
                      .group_by(Ledger.batch_id, Delivery.status, MessageRecall.status))
    for batch_id, status, recall_status, count, recall_available in rows:
        summary = result[batch_id]
        summary["delivery_statuses"][status] = summary["delivery_statuses"].get(status, 0) + count
        if recall_status is not None:
            summary["statuses"][recall_status] = summary["statuses"].get(recall_status, 0) + count
        summary["available"] += int(recall_available)
    # Count ledgers separately so multiple recipients never multiply cancellations.
    cancellations = db.execute(select(Ledger.batch_id, func.count())
                               .join(LedgerCancellation, LedgerCancellation.ledger_id == Ledger.id)
                               .where(Ledger.batch_id.in_(result)).group_by(Ledger.batch_id))
    for batch_id, count in cancellations:
        result[batch_id]["cancelled_scores"] = count
    return result


def recall_summary(db, batch_id, when=None):
    return {**batch_summaries(db, [batch_id], when)[batch_id], "scores": score_results(db, batch_id)}


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
    rows = db.execute(select(Delivery.status, MessageRecall.status).outerjoin(MessageRecall, MessageRecall.delivery_id == Delivery.id).where(
        Delivery.ledger_id == ledger.id)).all()
    if not rows or any(sent != "sent" or recalled != "recalled" for sent, recalled in rows):
        return False
    return cancel_score(db, ledger, actor_id, when, source=source)


def request_recall(db, user_id, *, delivery_id=None, batch_id=None, when=None):
    when = when or now_utc()
    lock_state(db)
    user = require_permission(db, user_id, "history.recall")
    if delivery_id:
        delivery = db.get(Delivery, delivery_id)
        ledger = db.get(Ledger, delivery.ledger_id) if delivery else None
        batch = db.get(Batch, ledger.batch_id) if ledger else None
    else:
        batch = db.get(Batch, batch_id)
    user = require_batch_operation(db, user_id, batch, "history.recall")
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
    unfinished = select(Delivery.id).outerjoin(MessageRecall, MessageRecall.delivery_id == Delivery.id).where(
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
    delivery = db.get(Delivery, recall.delivery_id)
    ledger = db.get(Ledger, delivery.ledger_id) if delivery else None
    batch = db.get(Batch, ledger.batch_id) if ledger else None
    if not batch:
        recall.status = "review"
        recall.last_error = "关联消息、积分流水或操作批次缺失，请核实记录"
        return None
    if recall.status == "recalling":
        recall.uncertain = True
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
    if not recall or recall.status != "recalling" or recall.lease_token != task["lease_token"]:
        return
    recall.lease_until = recall.lease_token = None
    delivery = db.get(Delivery, recall.delivery_id)
    ledger = db.get(Ledger, delivery.ledger_id) if delivery else None
    if not ledger or not db.get(Batch, ledger.batch_id):
        recall.status = "review"
        recall.last_error = "撤回关联记录缺失，请核实消息及积分，暂不作废积分"
        recall.uncertain = True
        return
    if error is None:
        recall.status = "recalled"
        recall.recalled_at = when
        recall.last_error = None
        recall.error_code = None
        recall.uncertain = False
        db.flush()
        cancel_if_fully_recalled(db, ledger, recall.actor_id, when)
        return
    recall.last_error = str(error)
    recall.error_code = error.code
    recall.uncertain = recall.uncertain or error.uncertain
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
