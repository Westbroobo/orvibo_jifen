from datetime import datetime, timedelta
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.adjustments import commit_preview, create_preview
from app import cards
from app.directory import resolve_selection
from app.models import Balance, Batch, Delivery, Employee, Ledger
from app.schemas import AdjustmentRequest, Selection


def request(**changes):
    return AdjustmentRequest.model_validate({"person_ids": ["a"], "operation": "plus", "points": 5,
        "reason": "提前完成项目", "recipients": {"person_ids": ["operator"]}, **changes})


def submit(factory, settings, when, body, user="admin"):
    with factory.begin() as db:
        preview = create_preview(db, user, body, settings, when)
    with factory.begin() as db:
        batch = commit_preview(db, user, preview["preview_token"], str(uuid4()), settings, when)
        return batch.id


def test_override_zero_and_continuing_month(factory, settings, when):
    submit(factory, settings, when, request())
    submit(factory, settings, when, request(overrides={"a": 85}))
    submit(factory, settings, when, request(points=3))
    with factory() as db:
        assert db.get(Balance, ("a", "2026-10")).total == 88
    submit(factory, settings, when, request(overrides={"a": 0}))
    submit(factory, settings, when, request(operation="minus", points=7))
    with factory() as db:
        assert db.get(Balance, ("a", "2026-10")).total == -7
    submit(factory, settings, datetime(2026, 10, 31, 16, 1), request())
    with factory() as db:
        assert db.get(Balance, ("a", "2026-11")).total == 65


def test_multi_person_independent_overrides_and_cartesian_messages(factory, settings, when):
    submit(factory, settings, when, request(person_ids=["a", "b", "a"], overrides={"b": 101},
                                         recipients={"person_ids": ["admin", "operator", "admin"]}))
    with factory() as db:
        assert db.get(Balance, ("a", "2026-10")).total == 65
        assert db.get(Balance, ("b", "2026-10")).total == 101
        assert db.scalar(select(func.count()).select_from(Ledger)) == 2
        assert db.scalar(select(func.count()).select_from(Delivery)) == 4


def test_idempotent_and_stale_preview(factory, settings, when):
    with factory.begin() as db:
        first = create_preview(db, "admin", request(), settings, when)
        second = create_preview(db, "admin", request(), settings, when)
    key = str(uuid4())
    with factory.begin() as db:
        batch = commit_preview(db, "admin", first["preview_token"], key, settings, when)
        batch_id = batch.id
    with factory.begin() as db:
        assert commit_preview(db, "admin", first["preview_token"], key, settings, when).id == batch_id
        assert commit_preview(db, "admin", first["preview_token"], str(uuid4()), settings, when).id == batch_id
    with factory.begin() as db, pytest.raises(HTTPException, match="已变化"):
        commit_preview(db, "admin", second["preview_token"], str(uuid4()), settings, when)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Batch)) == 1


@pytest.mark.parametrize("kind", ["expired", "month", "target", "recipient", "permission", "template"])
def test_preview_revalidates(factory, settings, when, kind, monkeypatch):
    with factory.begin() as db:
        preview = create_preview(db, "admin", request(), settings, when)
    later = when
    with factory.begin() as db:
        if kind == "expired": later += timedelta(minutes=11)
        if kind == "month": later = datetime(2026, 10, 31, 16, 0)
        if kind == "target": db.get(Employee, "a").status = "resigned"
        if kind == "recipient": db.get(Employee, "operator").status = "unknown"
        if kind == "permission": db.get(Employee, "admin").role = "none"
        if kind == "template": monkeypatch.setitem(cards.TEMPLATES, "plus", replace(cards.TEMPLATES["plus"], version="2.0.0"))
    with factory.begin() as db, pytest.raises(HTTPException):
        commit_preview(db, "admin", preview["preview_token"], str(uuid4()), settings, later)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Ledger)) == 0


def test_department_intersection_on_same_path_and_safe_empty(factory):
    with factory() as db:
        assert resolve_selection(db, Selection(mode="all"))["people"] == []
        selected = resolve_selection(db, Selection(mode="all", levels=[["rd"], ["sw"], []], extra_ids=["b", "a"]))
        assert {p["id"] for p in selected["people"]} == {"a", "b", "c"}
        assert resolve_selection(db, Selection(mode="all", levels=[["rd"], ["east"], []]))["people"] == []
        invalid = resolve_selection(db, Selection(mode="all", levels=[["deleted"], [], []]))
        assert invalid["warnings"] and not invalid["people"]


def test_atomic_rollback(factory, settings, when):
    with factory.begin() as db:
        preview = create_preview(db, "admin", request(), settings, when)
    with pytest.raises(RuntimeError):
        with factory.begin() as db:
            commit_preview(db, "admin", preview["preview_token"], str(uuid4()), settings, when)
            raise RuntimeError("simulate database failure before commit")
    with factory() as db:
        assert db.get(Balance, ("a", "2026-10")) is None
        assert db.scalar(select(func.count()).select_from(Delivery)) == 0


@pytest.mark.parametrize("changes", [{"points": 0}, {"points": 1.5}, {"reason": "   "}, {"overrides": {"b": 10}}])
def test_invalid_inputs(changes):
    with pytest.raises(ValueError):
        request(**changes)
