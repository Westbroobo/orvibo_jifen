"""在无外键 MySQL 上验证应用层完整性和历史保护。"""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, inspect, select, update

from app.db import Base
from app.delivery import claim_delivery
from app.models import (Balance, Batch, Delivery, Department, Employee, Ledger,
                        Membership, MessageRecall, PermissionAudit, Preset,
                        Preview, Session)
from app.recall import claim_recall
from test_adjustments import request, submit
from test_recall import sent_batch


def test_schema_has_no_foreign_keys(factory):
    with factory() as db:
        inspector = inspect(db.bind)
        assert all(not inspector.get_foreign_keys(name) for name in Base.metadata.tables)
        assert all(not table.foreign_keys for table in Base.metadata.tables.values())


def test_required_indexes_are_covered(factory):
    required = {Membership: [("department_id",)], Balance: [("month",)],
                Employee: [("role", "status")], Batch: [("operator_id", "created_at")],
                Delivery: [("status", "next_attempt_at"), ("status", "lease_until")],
                MessageRecall: [("status", "next_attempt_at"), ("status", "lease_until"),
                                ("status", "requested_at")]}
    with factory() as db:
        inspector = inspect(db.bind)
        for model, prefixes in required.items():
            indexes = [tuple(index["column_names"]) for index in inspector.get_indexes(model.__tablename__)]
            for prefix in prefixes:
                assert any(columns[:len(prefix)] == prefix for columns in indexes)


@pytest.mark.parametrize("record", [
    lambda: Membership(employee_id="missing", department_id="rd"),
    lambda: Membership(employee_id="a", department_id="missing"),
    lambda: Balance(employee_id="missing", month="2026-10", total=60),
    lambda: Preset(owner_id="missing", name="范围", selection={}),
    lambda: Session(employee_id="missing", id="session", csrf_token="csrf"),
    lambda: Preview(id="preview", owner_id="missing", request={}, snapshot={}),
    lambda: PermissionAudit(employee_id="missing", old_role="none", new_role="admin"),
    lambda: PermissionAudit(employee_id="a", actor_id="missing", old_role="none", new_role="admin"),
])
def test_missing_parents_are_rejected_before_writing(factory, record):
    with pytest.raises(HTTPException) as error:
        with factory.begin() as db:
            db.add(record())
    assert error.value.status_code == 409
    with factory() as db:
        assert not db.scalar(select(Preset))
        assert not db.get(Balance, ("missing", "2026-10"))


def test_changed_reference_is_checked_and_same_transaction_parents_work(factory):
    with factory.begin() as db:
        db.add(Employee(id="new", open_id="ou_new", name="新员工"))
        db.add(Department(id="newdept", name="新部门"))
        db.add(Membership(employee_id="new", department_id="newdept"))
        db.add(PermissionAudit(employee_id="new", actor_id=None, old_role="none", new_role="admin"))
    with pytest.raises(HTTPException):
        with factory.begin() as db:
            db.get(Membership, ("new", "newdept")).department_id = "missing"
    with factory() as db:
        assert db.get(Membership, ("new", "newdept"))


@pytest.mark.parametrize("bulk", [True, False])
def test_historical_parent_cannot_be_deleted(factory, settings, when, bulk):
    batch_id = submit(factory, settings, when, request())
    with pytest.raises(HTTPException):
        with factory.begin() as db:
            if bulk:
                db.execute(delete(Employee).where(Employee.id == "a"))
            else:
                db.delete(db.get(Batch, batch_id))
    with factory() as db:
        assert db.get(Batch, batch_id) and db.get(Employee, "a")


def test_primary_key_change_and_bulk_reference_update_are_blocked(factory):
    with pytest.raises(HTTPException):
        with factory.begin() as db:
            db.get(Employee, "a").id = "renamed"
    with pytest.raises(HTTPException):
        with factory.begin() as db:
            db.execute(update(Membership).values(employee_id="missing"))
    with factory() as db:
        assert db.get(Employee, "a")


def test_corrupt_delivery_is_quarantined_without_sending(factory, settings, when):
    submit(factory, settings, when, request())
    with factory.begin() as db:
        delivery = db.scalar(select(Delivery))
        delivery.next_attempt_at = when
        delivery_id = delivery.id
    # 模拟数据库工具绕过应用校验，工作进程应停止这条任务，不误发卡片。
    with factory.kw["bind"].begin() as connection:
        connection.execute(update(Delivery).where(Delivery.id == delivery_id).values(ledger_id="missing"))
    with factory.begin() as db:
        assert claim_delivery(db, settings, when) is None
        assert db.get(Delivery, delivery_id).status == "review"


def test_corrupt_recall_is_quarantined_without_voiding_scores(factory, settings, when):
    _, (delivery_id,) = sent_batch(factory, settings, when)
    with factory.begin() as db:
        db.add(MessageRecall(delivery_id=delivery_id, actor_id="admin", next_attempt_at=when))
    with factory.kw["bind"].begin() as connection:
        connection.execute(update(Delivery).where(Delivery.id == delivery_id).values(ledger_id="missing"))
    with factory.begin() as db:
        assert claim_recall(db, settings, when) is None
        assert db.get(MessageRecall, delivery_id).status == "review"
        assert db.get(Balance, ("a", "2026-10")).total == 65


def test_ledger_and_message_references_are_validated(factory, settings, when):
    submit(factory, settings, when, request())
    with factory() as db:
        delivery_id = db.scalar(select(Delivery.id))
        ledger_id = db.scalar(select(Ledger.id))
    for model, key, field in [(Delivery, delivery_id, "ledger_id"),
                              (Delivery, delivery_id, "recipient_id"),
                              (Ledger, ledger_id, "batch_id")]:
        with pytest.raises(HTTPException):
            with factory.begin() as db:
                setattr(db.get(model, key), field, str(uuid4()))
