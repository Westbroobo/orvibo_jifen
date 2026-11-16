import pytest
from sqlalchemy import select

from app.models import Delivery, Employee, Ledger
from test_adjustments import request, submit
from test_api import client, login


@pytest.fixture
def batch_with_many_deliveries(factory, settings, when):
    recipient_ids = [f"recipient-{index:03}" for index in range(220)]
    with factory.begin() as db:
        db.add_all([Employee(id=id, open_id="ou_" + id, name=f"通知对象 {index:03}", status="active")
                    for index, id in enumerate(recipient_ids)])
    batch_id = submit(factory, settings, when, request(recipients={"person_ids": recipient_ids}))
    with factory.begin() as db:
        deliveries = db.scalars(select(Delivery).join(Ledger, Delivery.ledger_id == Ledger.id).where(
            Ledger.batch_id == batch_id).order_by(Delivery.recipient_name, Delivery.id)).all()
        for index, delivery in enumerate(deliveries):
            delivery.status = "failed" if index >= 115 else "sent"
            if delivery.status == "sent":
                delivery.message_id = "om_" + delivery.id
                delivery.sent_at = when
            else:
                delivery.last_error = "模拟发送失败"
        return batch_id, [delivery.id for delivery in deliveries]


def test_delivery_filter_searches_the_entire_batch_before_paginating(client, factory, batch_with_many_deliveries):
    batch_id, ids = batch_with_many_deliveries
    login(client, factory)
    endpoint = f"/api/adjustments/{batch_id}"
    unfiltered = client.get(endpoint).json()
    assert unfiltered["delivery_status"] == "all" and unfiltered["total"] == 220
    assert [row["id"] for row in unfiltered["deliveries"]] == ids[:100]
    assert all(row["status"] == "sent" for row in unfiltered["deliveries"])

    first = client.get(endpoint + "?delivery_status=failed").json()
    second = client.get(endpoint + "?delivery_status=failed&page=2").json()
    assert first["total"] == second["total"] == 105
    assert first["delivery_status"] == second["delivery_status"] == "failed"
    assert first["page"] == 1 and second["page"] == 2
    assert [row["id"] for row in first["deliveries"] + second["deliveries"]] == ids[115:]
    assert all(row["status"] == "failed" and row["last_error"] == "模拟发送失败"
               for row in first["deliveries"] + second["deliveries"])
    assert first["statuses"] == unfiltered["statuses"] == {"sent": 115, "failed": 105}
    for field in ["snapshot", "scores", "recall_statuses", "recall_available", "cancelled_scores", "can_recall", "can_retry"]:
        assert first[field] == unfiltered[field]


def test_delivery_filter_empty_and_shrinking_results_use_a_valid_page(client, factory, batch_with_many_deliveries):
    batch_id, ids = batch_with_many_deliveries
    headers = login(client, factory)
    endpoint = f"/api/adjustments/{batch_id}"
    empty = client.get(endpoint + "?delivery_status=review&page=8").json()
    assert empty["deliveries"] == [] and empty["total"] == 0 and empty["page"] == 1
    for id in ids[-5:]:
        assert client.post(f"/api/deliveries/{id}/retry", headers=headers).status_code == 200
    refreshed = client.get(endpoint + "?delivery_status=failed&page=2").json()
    assert refreshed["delivery_status"] == "failed" and refreshed["page"] == 1
    assert refreshed["total"] == 100 and len(refreshed["deliveries"]) == 100
    assert refreshed["statuses"] == {"sent": 115, "failed": 100, "pending": 5}
    pending = client.get(endpoint + "?delivery_status=pending").json()
    assert pending["total"] == 5 and {row["id"] for row in pending["deliveries"]} == set(ids[-5:])


@pytest.mark.parametrize("status", ["all", "failed", "review", "pending", "sending", "sent"])
def test_delivery_filters_preserve_batch_visibility(client, factory, settings, when, status):
    batch_id = submit(factory, settings, when, request())
    login(client, factory, "operator")
    assert client.get(f"/api/adjustments/{batch_id}?delivery_status={status}").status_code == 404


def test_invalid_delivery_filter_is_rejected(client, factory, settings, when):
    batch_id = submit(factory, settings, when, request())
    login(client, factory)
    assert client.get(f"/api/adjustments/{batch_id}?delivery_status=unknown").status_code == 422
