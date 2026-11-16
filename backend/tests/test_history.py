from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db import get_db
from app.main import app
from app.models import Batch, Employee
from test_adjustments import request, submit
from test_api import client, login


@pytest.fixture
def small_sort_buffer(client, factory, test_engine):
    def database():
        with test_engine.connect() as connection, factory(bind=connection) as db:
            previous = connection.exec_driver_sql("SELECT @@session.sort_buffer_size").scalar_one()
            connection.exec_driver_sql("SET SESSION sort_buffer_size = 32768")
            try:
                yield db
            finally:
                connection.exec_driver_sql(f"SET SESSION sort_buffer_size = {int(previous)}")

    app.dependency_overrides[get_db] = database


@pytest.mark.parametrize("employee_id,scope", [("admin", "all"), ("operator", "own"), ("operator", "all")])
def test_history_large_snapshots_paginate_with_small_sort_buffer(client, factory, settings, when, small_sort_buffer,
                                                               employee_id, scope):
    records = []
    for index in range(44):
        operator = "admin" if index % 2 == 0 else "operator"
        created_at = when + timedelta(seconds=index // 4)
        batch_id = submit(factory, settings, created_at, request(), user=operator)
        records.append((batch_id, created_at, operator))
    with factory.begin() as db:
        db.get(Employee, employee_id).history_scope = scope
        db.get(Employee, employee_id).avatar_url = "https://example.com/operator.png"
        db.get(Employee, "a").avatar_url = "https://example.com/person.png"
        for batch in db.scalars(select(Batch)):
            batch.snapshot = {**batch.snapshot, "padding": "x" * (128 * 1024)}

    visible = [row for row in records if scope == "all" or row[2] == employee_id]
    expected = [row[0] for row in sorted(visible, key=lambda row: (-row[1].timestamp(), row[0]))]
    login(client, factory, employee_id)
    actual = []
    for page in range(1, 4):
        response = client.get(f"/api/adjustments?page={page}")
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["total"] == len(expected) and result["page"] == page
        assert [item["id"] for item in result["items"]] == expected[(page - 1) * 20:page * 20]
        for item in result["items"]:
            assert item["names"] == ["张三"]
            assert item["people"][0]["avatar_url"] == "https://example.com/person.png"
            assert item["message_count"] == 1 and item["statuses"] == {"pending": 1}
            if next(row[2] for row in records if row[0] == item["id"]) == employee_id:
                assert item["operator_avatar_url"] == "https://example.com/operator.png"
        actual.extend(item["id"] for item in result["items"])
    assert actual == expected
