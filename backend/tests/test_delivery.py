from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.delivery import claim_delivery, complete_delivery, retry_delivery
from app.feishu import FeishuError
from app.models import Balance, Delivery, Employee, Ledger
from test_adjustments import request, submit


def test_failed_notification_retry_does_not_score_again(factory, settings, when):
    submit(factory, settings, when, request())
    with factory.begin() as db:
        delivery = db.scalar(select(Delivery)); delivery.next_attempt_at = when
    with factory.begin() as db:
        task = claim_delivery(db, settings, when)
    with factory.begin() as db:
        complete_delivery(db, task, settings, error=FeishuError("recipient not available"), when=when)
    with factory.begin() as db:
        retry_delivery(db, task["id"], db.get(Employee, "admin"), when)
        retry = claim_delivery(db, settings, when)
        assert retry["uuid"] == task["uuid"]
    with factory.begin() as db:
        complete_delivery(db, retry, settings, message_id="om_success", when=when)
    with factory() as db:
        assert db.get(Delivery, task["id"]).message_id == "om_success"
        assert db.get(Balance, ("a", "2026-10")).total == 65
        assert db.scalar(select(func.count()).select_from(Ledger)) == 1
    with factory.begin() as db, pytest.raises(HTTPException):
        retry_delivery(db, task["id"], db.get(Employee, "admin"), when)


def test_restart_uncertain_window_and_stale_lease(factory, settings, when):
    submit(factory, settings, when, request())
    with factory.begin() as db:
        db.scalar(select(Delivery)).next_attempt_at = when
        task = claim_delivery(db, settings, when)
    with factory.begin() as db:
        recovered = claim_delivery(db, settings, when + timedelta(minutes=2))
        assert recovered["uuid"] == task["uuid"]
    with factory.begin() as db:
        complete_delivery(db, task, settings, message_id="stale", when=when)
        assert db.get(Delivery, task["id"]).message_id is None
        complete_delivery(db, recovered, settings, error=FeishuError("timeout", retryable=True, uncertain=True), when=when + timedelta(minutes=2))
    with factory.begin() as db:
        assert claim_delivery(db, settings, when + timedelta(hours=1)) is None
        assert db.get(Delivery, task["id"]).status == "review"
    with factory.begin() as db, pytest.raises(HTTPException):
        retry_delivery(db, task["id"], db.get(Employee, "admin"), when + timedelta(hours=1))
