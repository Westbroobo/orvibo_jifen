from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.db import now_utc
from app.feishu import FeishuClient, FeishuError
from app.models import Balance, Delivery, Employee, Ledger, LedgerCancellation, MessageRecall
from app.recall import can_recall, claim_recall, complete_recall, request_recall, run_recall_once
from test_adjustments import request, submit
from test_api import client, login


def sent_batch(factory, settings, when, recipients=None, **changes):
    batch_id = submit(factory, settings, when, request(recipients={"person_ids": recipients or ["operator"]}, **changes))
    with factory.begin() as db:
        deliveries = db.scalars(select(Delivery).join(Ledger).where(Ledger.batch_id == batch_id)).all()
        for delivery in deliveries:
            delivery.status = "sent"
            delivery.message_id = "om_" + delivery.id
            delivery.sent_at = when
        return batch_id, [delivery.id for delivery in deliveries]


def test_recall_idempotency_voids_score_once_and_preserves_snapshot(factory, settings, when):
    batch_id, (delivery_id,) = sent_batch(factory, settings, when)
    with factory.begin() as db:
        assert request_recall(db, "admin", batch_id=batch_id, when=when)["accepted"] == 1
        assert request_recall(db, "admin", delivery_id=delivery_id, when=when)["accepted"] == 0
        task = claim_recall(db, settings, when)
        complete_recall(db, task, settings, when=when)
        complete_recall(db, task, settings, when=when)
        assert request_recall(db, "admin", batch_id=batch_id, when=when)["accepted"] == 0
    with factory() as db:
        assert db.get(MessageRecall, delivery_id).status == "recalled"
        assert db.get(MessageRecall, delivery_id).actor_id == "admin"
        assert db.get(Delivery, delivery_id).status == "sent"
        assert db.get(Delivery, delivery_id).message_id == task["message_id"]
        assert db.get(Balance, ("a", "2026-10")).total == 60
        assert db.get(Balance, ("a", "2026-10")).version == 2
        ledger = db.scalar(select(Ledger))
        assert ledger.before_total == 60 and ledger.final_total == 65
        assert ledger.card["data"]["template_variable"]["total_score"] == "65"
        cancellation = db.get(LedgerCancellation, ledger.id)
        assert cancellation.before_balance == 65 and cancellation.after_balance == 60
        assert cancellation.actor_id == "admin" and cancellation.source == "recall"
        assert db.scalar(select(func.count()).select_from(Ledger)) == 1


def test_batch_skips_unsent_expired_and_already_recalled(factory, settings, when):
    batch_id, ids = sent_batch(factory, settings, when, ["admin", "operator", "a", "b"])
    with factory.begin() as db:
        db.get(Delivery, ids[0]).status = "pending"
        db.get(Delivery, ids[1]).sent_at = when - timedelta(hours=24)
        db.add(MessageRecall(delivery_id=ids[2], actor_id="admin", status="recalled", recalled_at=when))
    with factory.begin() as db:
        assert request_recall(db, "admin", batch_id=batch_id, when=when)["accepted"] == 1
    with factory() as db:
        assert not db.get(MessageRecall, ids[0]) and not db.get(MessageRecall, ids[1])
        assert db.get(MessageRecall, ids[3]).status == "pending"


@pytest.mark.parametrize("change,expected", [("unrelated", 404), ("revoked", 403), ("resigned", 403), ("expired", 409)])
def test_recall_enforces_owner_permissions_status_and_time(factory, settings, when, change, expected):
    _, (delivery_id,) = sent_batch(factory, settings, when)
    with factory.begin() as db:
        if change == "revoked":
            db.get(Employee, "admin").role = "none"
        if change == "resigned":
            db.get(Employee, "admin").status = "resigned"
        if change == "expired":
            db.get(Delivery, delivery_id).sent_at = when - timedelta(hours=24)
    with factory.begin() as db, pytest.raises(HTTPException) as error:
        request_recall(db, "operator" if change == "unrelated" else "admin", delivery_id=delivery_id, when=when)
    assert error.value.status_code == expected


def test_recall_timeout_restart_and_stale_lease(factory, settings, when):
    _, (delivery_id,) = sent_batch(factory, settings, when)
    with factory.begin() as db:
        request_recall(db, "admin", delivery_id=delivery_id, when=when)
        task = claim_recall(db, settings, when)
    with factory.begin() as db:
        restarted = claim_recall(db, settings, when + timedelta(minutes=2))
        assert restarted["message_id"] == task["message_id"]
        complete_recall(db, task, settings, when=when)
        assert db.get(MessageRecall, delivery_id).status == "recalling"
        complete_recall(db, restarted, settings, error=FeishuError("timeout", retryable=True, uncertain=True), when=when + timedelta(minutes=2))
    with factory.begin() as db:
        retry = claim_recall(db, settings, when + timedelta(minutes=5))
        complete_recall(db, retry, settings, when=when + timedelta(minutes=5))
        assert db.get(MessageRecall, delivery_id).status == "recalled"


def test_recall_uncertain_expiry_requires_review(factory, settings, when):
    _, (delivery_id,) = sent_batch(factory, settings, when)
    with factory.begin() as db:
        request_recall(db, "admin", delivery_id=delivery_id, when=when)
        task = claim_recall(db, settings, when)
        complete_recall(db, task, settings, error=FeishuError("timeout", uncertain=True, retryable=True), when=when)
    with factory.begin() as db:
        assert claim_recall(db, settings, when + timedelta(hours=24)) is None
        assert db.get(MessageRecall, delivery_id).status == "review"


def test_expired_by_enterprise_cannot_retry_but_permission_failure_can(factory, settings, when):
    _, ids = sent_batch(factory, settings, when, ["admin", "operator"])
    for delivery_id, code in zip(ids, [230009, 230027]):
        with factory.begin() as db:
            request_recall(db, "admin", delivery_id=delivery_id, when=when)
            task = claim_recall(db, settings, when)
            complete_recall(db, task, settings, error=FeishuError("rejected", code=code), when=when)
            recall = db.get(MessageRecall, delivery_id)
            assert recall.status == "failed"
            assert can_recall(db.get(Delivery, delivery_id), recall, when) == (code != 230009)
    with factory.begin() as db:
        assert request_recall(db, "admin", delivery_id=ids[1], when=when)["accepted"] == 1


@pytest.mark.parametrize("result_code", [0, 230110])
def test_feishu_recall_delete_and_already_deleted_contract(settings, result_code):
    requests = []
    def handle(request):
        requests.append(request)
        if "tenant_access_token" in str(request.url):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token", "expire": 7200})
        return httpx.Response(200 if result_code == 0 else 400, json={"code": result_code, "data": {}})
    settings.feishu_app_id, settings.feishu_app_secret = "app", "secret"
    client = FeishuClient(settings, transport=httpx.MockTransport(handle))
    try:
        client.recall_message("om_existing")
    finally:
        client.close()
    assert requests[-1].method == "DELETE"
    assert requests[-1].url.path == "/open-apis/im/v1/messages/om_existing"


def test_worker_only_retries_recall_and_never_sends_card(factory, settings):
    # MySQL DATETIME may round to the next second; the task must already be due.
    when = now_utc() - timedelta(seconds=1)
    _, (delivery_id,) = sent_batch(factory, settings, when)
    with factory.begin() as db:
        request_recall(db, "admin", delivery_id=delivery_id, when=when)
    class Client:
        def recall_message(self, message_id):
            assert message_id == "om_" + delivery_id
        def send_card(self, *_):
            pytest.fail("Recall must never re-send the card")
    assert run_recall_once(Client(), settings, factory)
    assert not run_recall_once(Client(), settings, factory)
    with factory() as db:
        assert db.get(MessageRecall, delivery_id).status == "recalled"


def test_recall_api_csrf_owner_and_result_counts(client, factory, settings):
    when = now_utc()
    batch_id, (delivery_id,) = sent_batch(factory, settings, when)
    headers = login(client, factory)
    assert client.post(f"/api/adjustments/{batch_id}/recall").status_code == 403
    detail = client.get(f"/api/adjustments/{batch_id}").json()
    assert detail["recall_available"] == 1 and detail["deliveries"][0]["can_recall"]
    assert client.post(f"/api/adjustments/{batch_id}/recall", headers=headers).json()["accepted"] == 1
    assert client.post(f"/api/deliveries/{delivery_id}/recall", headers=headers).json()["accepted"] == 0
    assert client.get("/api/adjustments").json()["items"][0]["recall_statuses"] == {"pending": 1}
    with factory.begin() as db:
        worker_when = now_utc() + timedelta(seconds=1)  # MySQL DATETIME rounds fractional seconds.
        task = claim_recall(db, settings, worker_when)
        complete_recall(db, task, settings, when=worker_when)
    detail = client.get(f"/api/adjustments/{batch_id}").json()
    assert detail["deliveries"][0]["recall_status"] == "recalled"
    assert detail["cancelled_scores"] == 1
    assert detail["scores"][0]["cancelled"] and detail["scores"][0]["cancelled_at"]
    assert detail["scores"][0]["original_total"] == 65 and detail["scores"][0]["current_total"] == 60
    assert client.get("/api/adjustments").json()["items"][0]["cancelled_scores"] == 1
    balances = client.get("/api/balances").json()
    assert balances["totals"]["a"] == 60 and balances["versions"]["a"] == 2
    headers = login(client, factory, "operator")
    assert client.post(f"/api/deliveries/{delivery_id}/recall", headers=headers).status_code == 404


def test_mysql_concurrent_recall_creates_one_task(factory, settings, when):
    with factory() as db:
        if db.bind.dialect.name != "mysql":
            pytest.skip("requires isolated MySQL")
    _, (delivery_id,) = sent_batch(factory, settings, when)
    barrier = Barrier(2)
    def attempt(_):
        barrier.wait()
        with factory.begin() as db:
            return request_recall(db, "admin", delivery_id=delivery_id, when=when)["accepted"]
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(attempt, [1, 2])) == [0, 1]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(MessageRecall)) == 1
