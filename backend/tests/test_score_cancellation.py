from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from itertools import count
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app import db as db_module
from app.adjustments import commit_preview, create_preview
from app.feishu import FeishuError
from app.models import Balance, Batch, Delivery, Ledger, LedgerCancellation, MessageRecall
from app.recall import (claim_recall, complete_recall, reconcile_recalled_score,
                        request_recall, run_recall_once)
from test_adjustments import request, submit
from test_recall import sent_batch


def recall_one(factory, settings, when, delivery_id):
    with factory.begin() as db:
        request_recall(db, "admin", delivery_id=delivery_id, when=when)
        task = claim_recall(db, settings, when)
        assert task["delivery_id"] == delivery_id
        complete_recall(db, task, settings, when=when)


def test_only_last_notification_success_voids_score(factory, settings, when):
    _, ids = sent_batch(factory, settings, when, ["admin", "operator"])
    recall_one(factory, settings, when, ids[0])
    with factory() as db:
        assert db.get(Balance, ("a", "2026-10")).total == 65
        assert not db.scalar(select(LedgerCancellation))
    recall_one(factory, settings, when, ids[1])
    with factory() as db:
        assert db.get(Balance, ("a", "2026-10")).total == 60
        assert db.scalar(select(func.count()).select_from(LedgerCancellation)) == 1


@pytest.mark.parametrize("delivery_status,recall_status", [
    ("pending", None), ("sending", None), ("failed", None), ("review", None),
    ("sent", None), ("sent", "pending"), ("sent", "recalling"),
    ("sent", "failed"), ("sent", "review"), ("failed", "recalled"),
])
def test_any_incomplete_notification_keeps_score(factory, settings, when, delivery_status, recall_status):
    _, ids = sent_batch(factory, settings, when, ["admin", "operator"])
    recall_one(factory, settings, when, ids[0])
    with factory.begin() as db:
        db.get(Delivery, ids[1]).status = delivery_status
        if recall_status:
            db.add(MessageRecall(delivery_id=ids[1], actor_id="admin", status=recall_status))
    with factory.begin() as db:
        assert not reconcile_recalled_score(db, when)
    with factory() as db:
        assert db.get(Balance, ("a", "2026-10")).total == 65
        assert not db.scalar(select(LedgerCancellation))


def test_failed_recall_keeps_score_until_successful_retry(factory, settings, when):
    _, ids = sent_batch(factory, settings, when, ["admin", "operator"])
    recall_one(factory, settings, when, ids[0])
    with factory.begin() as db:
        request_recall(db, "admin", delivery_id=ids[1], when=when)
        task = claim_recall(db, settings, when)
        complete_recall(db, task, settings, error=FeishuError("permission denied", code=230027), when=when)
    with factory() as db:
        assert db.get(Balance, ("a", "2026-10")).total == 65
    recall_one(factory, settings, when, ids[1])
    with factory() as db:
        assert db.get(Balance, ("a", "2026-10")).total == 60
        assert db.scalar(select(func.count()).select_from(Ledger)) == 1
        assert all(d.status == "sent" for d in db.scalars(select(Delivery)))


def test_multi_person_cancels_independently(factory, settings, when):
    batch_id, ids = sent_batch(factory, settings, when, ["admin", "operator"],
                               person_ids=["a", "b"], overrides={"b": 85})
    with factory() as db:
        a_ids = list(db.scalars(select(Delivery.id).join(Ledger, Delivery.ledger_id == Ledger.id).where(
            Ledger.batch_id == batch_id, Ledger.employee_id == "a")))
    for delivery_id in a_ids:
        recall_one(factory, settings, when, delivery_id)
    with factory() as db:
        assert db.get(Balance, ("a", "2026-10")).total == 60
        assert db.get(Balance, ("b", "2026-10")).total == 85
        assert db.scalar(select(func.count()).select_from(LedgerCancellation)) == 1
    for delivery_id in set(ids) - set(a_ids):
        recall_one(factory, settings, when, delivery_id)
    with factory() as db:
        assert db.get(Balance, ("b", "2026-10")).total == 60


@pytest.mark.parametrize("operations,cancel_index,expected", [
    ([{}, {"points": 3}], 0, 63),
    ([{}, {"overrides": {"a": 85}}, {"points": 3}], 0, 88),
    ([{"overrides": {"a": 85}}, {"points": 3}], 0, 63),
    ([{}, {"overrides": {"a": 85}}, {"points": 3}], 1, 68),
    ([{"overrides": {"a": 0}}, {"operation": "minus", "points": 7}], 0, 53),
    ([{}, {"overrides": {"a": 0}}, {"points": 3}], 0, 3),
    ([{"operation": "minus", "points": 70}, {"points": 3}], 0, 63),
    ([{"overrides": {"a": -5}}, {"operation": "minus", "points": 3}], 0, 57),
])
def test_replay_effective_monthly_entries(factory, settings, when, operations, cancel_index, expected):
    ids = [sent_batch(factory, settings, when, **operation)[1][0] for operation in operations]
    recall_one(factory, settings, when, ids[cancel_index])
    with factory() as db:
        assert db.get(Balance, ("a", "2026-10")).total == expected
    submit(factory, settings, when, request(points=2))
    with factory() as db:
        assert db.get(Balance, ("a", "2026-10")).total == expected + 2


def test_same_second_replay_follows_balance_versions_not_uuid_order(factory, settings, when, monkeypatch):
    sequence = count(1000, -1)
    monkeypatch.setattr(db_module, "uuid4", lambda: UUID(int=next(sequence)))
    first, (delivery_id,) = sent_batch(factory, settings, when)
    second, _ = sent_batch(factory, settings, when, overrides={"a": 85})
    third, _ = sent_batch(factory, settings, when, points=3)
    assert first > second > third
    recall_one(factory, settings, when, delivery_id)
    with factory() as db:
        assert {batch.created_at for batch in db.scalars(select(Batch))} == {when}
        assert db.get(Balance, ("a", "2026-10")).total == 88


def test_multiple_cancellations_replay_without_restoring_old_cancelled_entries(factory, settings, when):
    ids = [sent_batch(factory, settings, when, **operation)[1][0]
           for operation in [{}, {"overrides": {"a": 85}}, {"points": 3}]]
    for index, expected in [(1, 68), (0, 63), (2, 60)]:
        recall_one(factory, settings, when, ids[index])
        with factory() as db:
            assert db.get(Balance, ("a", "2026-10")).total == expected
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(LedgerCancellation)) == 3


def test_cancellation_recalculates_original_month_only(factory, settings):
    before_midnight = datetime(2026, 10, 31, 15, 59)
    after_midnight = datetime(2026, 10, 31, 16, 1)
    _, (delivery_id,) = sent_batch(factory, settings, before_midnight)
    submit(factory, settings, after_midnight, request())
    recall_one(factory, settings, after_midnight, delivery_id)
    with factory() as db:
        assert db.get(Balance, ("a", "2026-10")).total == 60
        assert db.get(Balance, ("a", "2026-11")).total == 65


@pytest.mark.parametrize("later_override", [False, True])
def test_cancellation_invalidates_preview_even_if_total_unchanged(factory, settings, when, later_override):
    _, (delivery_id,) = sent_batch(factory, settings, when)
    if later_override:
        submit(factory, settings, when, request(overrides={"a": 85}))
    with factory.begin() as db:
        preview = create_preview(db, "admin", request(), settings, when)
    recall_one(factory, settings, when, delivery_id)
    with pytest.raises(HTTPException, match="已变化"):
        with factory.begin() as db:
            commit_preview(db, "admin", preview["preview_token"], str(uuid4()), settings, when)
    with factory() as db:
        assert db.get(Balance, ("a", "2026-10")).total == (85 if later_override else 60)


def test_cancellation_success_and_audit_are_atomic(factory, settings, when):
    _, (delivery_id,) = sent_batch(factory, settings, when)
    with factory.begin() as db:
        request_recall(db, "admin", delivery_id=delivery_id, when=when)
        task = claim_recall(db, settings, when)
    with pytest.raises(RuntimeError):
        with factory.begin() as db:
            complete_recall(db, task, settings, when=when)
            raise RuntimeError("transaction failed")
    with factory() as db:
        assert db.get(MessageRecall, delivery_id).status == "recalling"
        assert db.get(Balance, ("a", "2026-10")).total == 65
        assert not db.scalar(select(LedgerCancellation))
    with factory.begin() as db:
        complete_recall(db, task, settings, when=when)
    with factory() as db:
        assert db.get(Balance, ("a", "2026-10")).total == 60


def test_concurrent_last_notifications_cancel_once(factory, settings, when):
    batch_id, _ = sent_batch(factory, settings, when, ["admin", "operator"])
    with factory.begin() as db:
        request_recall(db, "admin", batch_id=batch_id, when=when)
        tasks = [claim_recall(db, settings, when), claim_recall(db, settings, when)]
    barrier = Barrier(2)
    def complete(task):
        barrier.wait()
        with factory.begin() as db:
            complete_recall(db, task, settings, when=when)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(complete, tasks))
    with factory() as db:
        assert db.get(Balance, ("a", "2026-10")).total == 60
        assert db.get(Balance, ("a", "2026-10")).version == 2
        assert db.scalar(select(func.count()).select_from(LedgerCancellation)) == 1
        assert all(r.status == "recalled" for r in db.scalars(select(MessageRecall)))


def test_legacy_partial_recall_does_not_block_fully_recalled_entry(factory, settings, when):
    _, partial_ids = sent_batch(factory, settings, when, ["admin", "operator"])
    _, complete_ids = sent_batch(factory, settings, when, ["admin", "operator"])
    with factory.begin() as db:
        for delivery_id in [partial_ids[0], *complete_ids]:
            db.add(MessageRecall(delivery_id=delivery_id, actor_id="admin", status="recalled",
                                 requested_at=when, recalled_at=when))
    class NoNetwork:
        def recall_message(self, *_):
            pytest.fail("Historical recalls must not call Feishu again")
    assert run_recall_once(NoNetwork(), settings, factory)
    assert not run_recall_once(NoNetwork(), settings, factory)
    with factory() as db:
        assert db.get(Balance, ("a", "2026-10")).total == 65
        cancellation = db.scalar(select(LedgerCancellation))
        assert cancellation.source == "legacy_recall"
        assert cancellation.before_balance == 70 and cancellation.after_balance == 65
        assert cancellation.ledger_id == db.get(Delivery, complete_ids[0]).ledger_id


def test_reconfirming_cancelled_batch_never_restores_score(factory, settings, when):
    with factory.begin() as db:
        preview = create_preview(db, "admin", request(), settings, when)
    key = str(uuid4())
    with factory.begin() as db:
        batch = commit_preview(db, "admin", preview["preview_token"], key, settings, when)
        batch_id = batch.id
        delivery = db.scalar(select(Delivery))
        delivery_id = delivery.id
        delivery.status, delivery.message_id, delivery.sent_at = "sent", "om_original", when
    recall_one(factory, settings, when, delivery_id)
    for new_key in [key, str(uuid4())]:
        with factory.begin() as db:
            assert commit_preview(db, "admin", preview["preview_token"], new_key, settings, when).id == batch_id
    with factory() as db:
        assert db.get(Balance, ("a", "2026-10")).total == 60
        assert db.scalar(select(func.count()).select_from(Ledger)) == 1
        assert db.scalar(select(func.count()).select_from(Delivery)) == 1
