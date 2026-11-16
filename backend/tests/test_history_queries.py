from collections import Counter
from contextlib import contextmanager
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, event, select

from app.cancellations import cancel_score
from app.models import Balance, Batch, Delivery, Employee, Ledger, MessageRecall
from app.recall import batch_summaries, can_recall, score_results
from test_adjustments import request, submit
from test_api import client, login


@contextmanager
def select_statements(engine):
    statements = []

    def record(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


def test_history_query_count_does_not_grow_with_batches_or_scored_people(client, factory, settings, when, test_engine):
    submit(factory, settings, when, request())
    login(client, factory)
    with select_statements(test_engine) as first_queries:
        first = client.get("/api/adjustments")
    assert first.status_code == 200 and first.json()["total"] == 1

    for index in range(19):
        submit(factory, settings, when + timedelta(seconds=index + 1), request(person_ids=["a", "b", "c"]))
    with select_statements(test_engine) as page_queries:
        response = client.get("/api/adjustments")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["total"] == len(result["items"]) == 20
    assert len(page_queries) == len(first_queries)
    assert not any(Balance.__tablename__ in sql for sql in page_queries)
    assert all(item["statuses"] == {"pending": item["message_count"]} for item in result["items"])


def test_score_results_fetches_balances_together_and_preserves_values(factory, settings, when, test_engine):
    first_id = submit(factory, settings, when, request())
    with select_statements(test_engine) as first_queries, factory() as db:
        first = score_results(db, first_id)
    assert len(first) == 1 and len(first_queries) == 1

    batch_id = submit(factory, settings, when + timedelta(seconds=1), request(person_ids=["a", "b", "c"]))
    with factory.begin() as db:
        ledger = db.scalar(select(Ledger).where(Ledger.batch_id == batch_id, Ledger.employee_id == "a"))
        assert cancel_score(db, ledger, "admin", when + timedelta(seconds=2))
    with select_statements(test_engine) as queries, factory() as db:
        scores = {row["person_id"]: row for row in score_results(db, batch_id)}
    assert len(queries) == len(first_queries)
    assert set(scores) == {"a", "b", "c"}
    assert scores["a"]["original_total"] == 70 and scores["a"]["current_total"] == 65
    assert scores["a"]["cancelled"] and scores["a"]["cancelled_at"]
    assert all(scores[id]["original_total"] == scores[id]["current_total"] == 65 for id in ["b", "c"])
    assert all(not scores[id]["cancelled"] and scores[id]["cancelled_at"] is None for id in ["b", "c"])
    # Large card snapshots have no role in a score-only read.
    assert ".card" not in queries[0]


def test_score_results_retains_missing_balance_conflict(factory, settings, when, test_engine):
    batch_id = submit(factory, settings, when, request())
    # Simulate inconsistent historical data outside the guarded business session.
    with test_engine.begin() as connection:
        connection.execute(delete(Balance).where(Balance.employee_id == "a", Balance.month == "2026-10"))
    with factory() as db, pytest.raises(HTTPException) as error:
        score_results(db, batch_id)
    assert error.value.status_code == 409 and "余额缺失" in error.value.detail


def test_grouped_summary_matches_recall_rules_and_counts_each_score_once(factory, settings, when):
    cases = [
        {},
        {"recall": "failed", "code": None},
        {"recall": "review", "code": None},
        {"recall": "failed", "code": 230009},
        {"recall": "review", "code": 230009},
        {"recall": "failed", "code": 230027},
        {"recall": "pending"},
        {"recall": "recalling"},
        {"recall": "recalled"},
        {"sent_at": when - timedelta(hours=24, seconds=1)},
        {"sent_at": when - timedelta(hours=24)},
        {"sent_at": when - timedelta(hours=24) + timedelta(seconds=1)},
        {"message_id": None},
        {"message_id": ""},
        {"sent_at": None},
        {"status": "failed"},
        {"message_id": " "},
    ]
    recipients = [f"summary-recipient-{index}" for index in range(len(cases))]
    with factory.begin() as db:
        db.add_all([Employee(id=id, open_id="ou_" + id, name=id, status="active") for id in recipients])
    batch_id = submit(factory, settings, when, request(person_ids=["a", "b"], recipients={"person_ids": recipients}))
    excluded_id = submit(factory, settings, when, request())
    with factory.begin() as db:
        ledger = db.scalar(select(Ledger).where(Ledger.batch_id == batch_id, Ledger.employee_id == "a"))
        deliveries = {row.recipient_id: row for row in db.scalars(select(Delivery).where(Delivery.ledger_id == ledger.id))}
        for recipient, changes in zip(recipients, cases):
            delivery = deliveries[recipient]
            delivery.status = changes.get("status", "sent")
            delivery.message_id = changes.get("message_id", "om_" + delivery.id)
            delivery.sent_at = changes.get("sent_at", when)
            if "recall" in changes:
                db.add(MessageRecall(delivery_id=delivery.id, actor_id="admin", status=changes["recall"],
                                     error_code=changes.get("code"), requested_at=when))
        assert cancel_score(db, ledger, "admin", when)
        empty = Batch(operator_id="admin", idempotency_key="empty-summary", preview_id="empty-summary",
                      month="2026-10", delta=5, reason="测试空批次", snapshot={}, created_at=when)
        db.add(empty)
        db.flush()
        empty_id = empty.id
    with factory() as db:
        rows = db.execute(select(Delivery, MessageRecall).join(Ledger, Delivery.ledger_id == Ledger.id).outerjoin(
            MessageRecall, MessageRecall.delivery_id == Delivery.id).where(Ledger.batch_id == batch_id)).all()
        expected_available = sum(can_recall(delivery, recall, when) for delivery, recall in rows)
        assert expected_available == 6
        summary = batch_summaries(db, [batch_id, empty_id], when)
    assert set(summary) == {batch_id, empty_id} and excluded_id not in summary
    assert summary[batch_id] == {
        "delivery_statuses": dict(Counter(delivery.status for delivery, _ in rows)),
        "statuses": dict(Counter(recall.status for _, recall in rows if recall)),
        "available": expected_available,
        "cancelled_scores": 1,
    }
    assert summary[empty_id] == {"delivery_statuses": {}, "statuses": {}, "available": 0, "cancelled_scores": 0}


def test_empty_summary_selection_never_queries():
    class NoDatabase:
        def execute(self, *_args, **_kwargs):
            pytest.fail("Empty selections must not query or scan other batches")

    assert batch_summaries(NoDatabase(), []) == {}
