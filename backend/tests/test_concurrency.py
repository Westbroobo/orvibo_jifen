from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.adjustments import commit_preview, create_preview
from app.models import Balance, Batch
from test_adjustments import request


@pytest.mark.parametrize("same_preview", [True, False])
def test_mysql_concurrent_commits(factory, settings, when, same_preview):
    with factory() as db:
        if db.bind.dialect.name != "mysql":
            pytest.skip("requires isolated MySQL integration instance")
    with factory.begin() as db:
        first = create_preview(db, "admin", request(), settings, when)
        second = first if same_preview else create_preview(db, "admin", request(), settings, when)
    barrier = Barrier(2)
    key = str(uuid4())

    def attempt(preview):
        barrier.wait()
        try:
            with factory.begin() as db:
                return commit_preview(db, "admin", preview["preview_token"], key if same_preview else str(uuid4()), settings, when).id
        except HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(attempt, [first, second]))
    if same_preview:
        assert results[0] == results[1]
    else:
        assert 409 in results and sum(isinstance(r, str) for r in results) == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Batch)) == 1
        assert db.get(Balance, ("a", "2026-10")).total == 65
