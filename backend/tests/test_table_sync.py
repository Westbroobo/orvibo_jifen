from copy import deepcopy
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event, select

from app.db import now_utc
from app.feishu import FeishuError
from app.models import Balance, Batch, Employee, Ledger, Membership, Preset, SystemState, TableSyncLog, TableSyncRun, TableSyncTask
from app.table_sync import api, service
from app.table_sync.schedule import next_times, validate_cron
from test_api import client, login
from test_adjustments import request, submit


MAPPING = {"department": "fldDept", "name": "fldName", "user_id": "fldUser"}
INFO = {"base_token": "baseTest", "table_id": "tblTest", "table_name": "通知名单",
        "tables": [{"id": "tblTest", "name": "通知名单"}],
        "fields": [{"id": value, "name": key, "type": 1, "writable": True} for key, value in MAPPING.items()]}


@pytest.fixture
def prepared(factory, monkeypatch):
    with factory.begin() as db:
        db.get(SystemState, 1).last_sync_at = now_utc()
        for employee_id in ("a", "b", "c"):
            db.get(Employee, employee_id).user_id = "u_" + employee_id
    monkeypatch.setattr(api.BitableClient, "resolve_target", lambda *args, **kwargs: deepcopy(INFO))
    return factory


def body(**changes):
    return {"name": "战报名单", "source_kind": "selection", "preset_id": None,
            "selection": {"match_mode": "union", "person_ids": ["a"]},
            "target_url": "https://company.feishu.cn/base/baseTest?table=tblTest", "table_id": "tblTest",
            "field_mapping": MAPPING, "cron": "0 4 * * *", **changes}


def create(client, factory, **changes):
    headers = login(client, factory)
    response = client.post("/api/table-sync/tasks", json=body(**changes), headers=headers)
    assert response.status_code == 201, response.text
    return response.json(), headers


def start(factory, kind="sync"):
    with factory.begin() as db:
        task = db.scalar(select(TableSyncTask))
        run = service.enqueue(db, task, kind=kind, actor_id="admin", actor_name="管理员")
        run_id = run.id
    claim = service.claim_run(factory, "test-worker")
    assert claim["run_id"] == run_id
    return claim


class MemoryTable:
    def __init__(self, factory, rows=()):
        self.factory, self.rows, self.calls = factory, deepcopy(list(rows)), []

    def assert_released(self):
        assert self.factory.kw["bind"].pool.checkedout() == 0, "database connection spans external request"

    def validate_mapping(self, *args):
        self.assert_released()
        return MAPPING

    def read_rows(self, *args):
        self.assert_released()
        return deepcopy(self.rows)

    def create_rows(self, base, table, mapping, rows):
        self.assert_released()
        self.calls.append("create")
        for index, row in enumerate(rows):
            self.rows.append({"record_id": "recNew" + str(index), **row})
        return len(rows)

    def update_rows(self, base, table, mapping, rows):
        self.assert_released()
        self.calls.append("update")
        by_id = {row["record_id"]: row for row in rows}
        self.rows = [{**row, **by_id.get(row["record_id"], {})} for row in self.rows]
        return len(rows)

    def delete_rows(self, base, table, rows):
        self.assert_released()
        self.calls.append("delete")
        ids = {row["record_id"] for row in rows}
        self.rows = [row for row in self.rows if row["record_id"] not in ids]
        return len(rows)


def result(factory, claim):
    with factory() as db:
        run = db.get(TableSyncRun, claim["run_id"])
        return run.status, run.error, run.summary


def test_cron_is_five_field_beijing_and_future():
    assert validate_cron(" 0  4 * * * ") == "0 4 * * *"
    assert next_times("0 4 * * *", datetime(2026, 11, 17, 0), 2) == [datetime(2026, 11, 17, 20), datetime(2026, 11, 18, 20)]
    for expression in ("@daily", "0 0 4 * * *", "0 0 31 2 *", "bad"):
        with pytest.raises(ValueError):
            validate_cron(expression)


def test_all_sync_api_routes_are_admin_only_and_csrf_checked(client, prepared):
    assert client.get("/api/table-sync/tasks").status_code == 401
    headers = login(client, prepared, "operator")
    assert client.get("/api/table-sync/tasks").status_code == 403
    assert client.post("/api/table-sync/inspect", json={"url": body()["target_url"]}, headers=headers).status_code == 403
    headers = login(client, prepared)
    assert client.post("/api/table-sync/tasks", json=body()).status_code == 403
    assert client.post("/api/table-sync/cron", json={"cron": "* * * * * *"}, headers=headers).status_code == 422


def test_create_draft_target_exclusive_and_sources_not_presets(client, prepared):
    task, headers = create(client, prepared)
    assert not task["enabled"] and task["next_run_at"] is None
    assert client.get("/api/presets").json() == []
    assert client.post("/api/table-sync/tasks", json=body(), headers=headers).status_code == 409
    with prepared.begin() as db:
        db.add(Preset(owner_id="admin", name="私人", scope="personal", selection={}))
        db.add(Preset(owner_id="admin", name="公共", scope="public", selection={}))
    sources = client.get("/api/table-sync/sources").json()
    assert [item["name"] for item in sources["presets"]] == ["公共"]
    assert "totals" not in sources
    assert client.delete(f"/api/table-sync/tasks/{task['id']}", headers=headers).status_code == 200
    assert client.get("/api/table-sync/tasks").json()["total"] == 0
    assert client.post("/api/table-sync/tasks", json=body(), headers=headers).status_code == 201


def test_inspection_releases_authenticated_transaction(client, prepared, monkeypatch):
    from app.db import get_db
    from app.main import app
    sessions = []
    def database():
        with prepared() as db:
            sessions.append(db)
            yield db
    def inspect(*args, **kwargs):
        assert all(not db.in_transaction() for db in sessions)
        return deepcopy(INFO)
    app.dependency_overrides[get_db] = database
    monkeypatch.setattr(api.BitableClient, "resolve_target", inspect)
    headers = login(client, prepared)
    assert client.post("/api/table-sync/inspect", json={"url": body()["target_url"]}, headers=headers).status_code == 200
    assert client.post("/api/table-sync/tasks", json=body(), headers=headers).status_code == 201


def test_switch_only_controls_schedule_manual_does_not_shift_it(client, prepared):
    task, headers = create(client, prepared)
    url = f"/api/table-sync/tasks/{task['id']}"
    enabled = client.patch(url + "/enabled", json={"enabled": True}, headers=headers).json()
    scheduled = enabled["next_run_at"]
    run = client.post(url + "/run", headers=headers)
    assert run.status_code == 202 and run.json()["trigger"] == "manual"
    assert client.get(url).json()["next_run_at"] == scheduled
    assert client.post(url + "/run", headers=headers).status_code == 409
    assert client.put(url, json=body(), headers=headers).status_code == 409
    assert client.delete(url, headers=headers).status_code == 409
    assert client.patch(url + "/enabled", json={"enabled": False}, headers=headers).status_code == 200
    claim = service.claim_run(prepared, "test-worker")
    service.finish_run(prepared, claim["run_id"], claim["lease_token"], "interrupted", "测试结束")
    assert client.post(url + "/preview", headers=headers).status_code == 202


def test_valid_empty_preview_and_invalid_mapping(client, prepared, monkeypatch):
    headers = login(client, prepared)
    response = client.post("/api/table-sync/source-preview", json={"source_kind": "selection", "selection": {"match_mode": "union"}}, headers=headers)
    assert response.status_code == 200 and response.json()["source_count"] == 0
    info = deepcopy(INFO)
    info["fields"][0]["writable"] = False
    monkeypatch.setattr(api.BitableClient, "resolve_target", lambda *args, **kwargs: info)
    assert client.post("/api/table-sync/tasks", json=body(), headers=headers).status_code == 422


def test_preview_is_read_only_and_sync_converges_without_business_lock(client, prepared, monkeypatch, settings):
    task, headers = create(client, prepared)
    original = [{"record_id": "recOld", "user_id": "removed", "name": "旧人", "department": "旧部门"}]
    remote = MemoryTable(prepared, original)
    import app.data_integrity as integrity
    monkeypatch.setattr(integrity, "lock_state", lambda db: pytest.fail("sync uses original global lock"))
    claim = start(prepared, kind="preview")
    service.execute_run(prepared, claim["run_id"], claim["lease_token"], settings, remote)
    assert result(prepared, claim)[0] == "success"
    assert not remote.calls and remote.rows == original
    assert client.get(f"/api/table-sync/runs/{claim['run_id']}/rows").json()["total"] == 2
    claim = start(prepared)
    service.execute_run(prepared, claim["run_id"], claim["lease_token"], settings, remote)
    assert remote.calls == ["create", "delete"]
    assert result(prepared, claim)[0] == "success"
    assert remote.rows[0]["user_id"] == "u_a" and len(remote.rows) == 1
    assert client.get(f"/api/table-sync/runs/{claim['run_id']}/logs").json()["total"] >= 4
    claim = start(prepared)
    remote.calls.clear()
    service.execute_run(prepared, claim["run_id"], claim["lease_token"], settings, remote)
    assert result(prepared, claim)[0] == "unchanged" and not remote.calls


def test_unknown_create_stops_delete_and_next_run_repairs(client, prepared, settings):
    create(client, prepared)
    remote = MemoryTable(prepared, [{"record_id": "recOld", "user_id": "old", "name": "旧人", "department": "旧"}])
    original_create = remote.create_rows
    def uncertain(*args):
        original_create(*args)
        raise FeishuError("飞书网络请求失败", uncertain=True)
    remote.create_rows = uncertain
    claim = start(prepared)
    service.execute_run(prepared, claim["run_id"], claim["lease_token"], settings, remote)
    assert result(prepared, claim)[0] == "failed" and remote.calls == ["create"]
    remote.create_rows = original_create
    claim = start(prepared)
    service.execute_run(prepared, claim["run_id"], claim["lease_token"], settings, remote)
    assert result(prepared, claim)[0] == "success" and remote.calls == ["create", "delete"]
    assert [row["user_id"] for row in remote.rows] == ["u_a"]


def test_unknown_people_leave_remote_roster_but_keep_employee_and_score_history(client, prepared, settings, when):
    batch_id = submit(prepared, settings, when, request())
    with prepared.begin() as db:
        db.get(Employee, "a").status = "unknown"
    create(client, prepared, selection={"match_mode": "union", "department_ids": ["rd"], "person_ids": ["a"]})
    original = [{"record_id": "recA", "user_id": "u_a", "name": "张三", "department": "平台"},
                {"record_id": "recC", "user_id": "u_c", "name": "多部门员工", "department": "华东；平台"}]
    remote = MemoryTable(prepared, original)
    preview = start(prepared, kind="preview")
    service.execute_run(prepared, preview["run_id"], preview["lease_token"], settings, remote)
    status, error, summary = result(prepared, preview)
    assert status == "success" and error is None
    assert summary["source"] == 1 and summary["delete"] == 1 and not remote.calls
    assert remote.rows == original
    rows = client.get(f"/api/table-sync/runs/{preview['run_id']}/rows?action=delete").json()["items"]
    assert len(rows) == 1 and rows[0]["user_id"] == "u_a" and rows[0]["reason"] == "not_in_source"

    claim = start(prepared)
    service.execute_run(prepared, claim["run_id"], claim["lease_token"], settings, remote)
    assert result(prepared, claim)[0] == "success" and remote.calls == ["delete"]
    assert remote.rows == [original[1]]
    with prepared() as db:
        assert db.get(Employee, "a").status == "unknown"
        assert db.get(Membership, ("a", "team")) is not None
        ledger = db.scalar(select(Ledger).where(Ledger.batch_id == batch_id))
        assert ledger.employee_id == "a" and ledger.final_total == 65
        assert db.get(Balance, ("a", "2026-10")).total == 65
        assert db.get(Batch, batch_id).snapshot["rows"][0]["person"]["name"] == "张三"
    history = client.get("/api/score-ledgers?month=2026-10").json()
    assert history["total"] == 1 and history["items"][0]["person_name"] == "张三"


def test_source_change_during_write_prevents_cleanup(client, prepared, settings):
    create(client, prepared)
    remote = MemoryTable(prepared, [{"record_id": "recOld", "user_id": "old", "name": "旧人", "department": "旧"}])
    original_create = remote.create_rows
    def change_source(*args):
        count = original_create(*args)
        with prepared.begin() as db:
            db.get(SystemState, 1).directory_version += 1
        return count
    remote.create_rows = change_source
    claim = start(prepared)
    service.execute_run(prepared, claim["run_id"], claim["lease_token"], settings, remote)
    assert result(prepared, claim)[0] == "failed" and remote.calls == ["create"]


def test_source_change_between_delete_batches_stops_second_batch(client, prepared, settings):
    create(client, prepared, selection={"match_mode": "union"})
    remote = MemoryTable(prepared, [{"record_id": f"recOld{index}", "user_id": f"old{index}", "name": "旧人", "department": "旧"}
                                    for index in range(201)])
    original_delete = remote.delete_rows
    def change_source(*args):
        count = original_delete(*args)
        with prepared.begin() as db:
            db.get(SystemState, 1).directory_version += 1
        return count
    remote.delete_rows = change_source
    claim = start(prepared)
    service.execute_run(prepared, claim["run_id"], claim["lease_token"], settings, remote)
    assert result(prepared, claim)[0] == "failed" and remote.calls == ["delete"]
    assert len(remote.rows) == 1


def test_legal_empty_clears_but_source_failure_never_does(client, prepared, settings):
    create(client, prepared, selection={"match_mode": "union"})
    remote = MemoryTable(prepared, [{"record_id": "recOld", "user_id": "old", "name": "旧", "department": "旧"}])
    claim = start(prepared)
    service.execute_run(prepared, claim["run_id"], claim["lease_token"], settings, remote)
    assert result(prepared, claim)[0] == "success" and remote.rows == []
    with prepared.begin() as db:
        db.get(SystemState, 1).last_sync_at = None
    remote = MemoryTable(prepared, [{"record_id": "recOld", "user_id": "old", "name": "旧", "department": "旧"}])
    claim = start(prepared)
    service.execute_run(prepared, claim["run_id"], claim["lease_token"], settings, remote)
    assert result(prepared, claim)[0] == "failed" and not remote.calls and remote.rows


def test_schedule_catchup_coalesces_and_active_is_skipped(client, prepared):
    task, headers = create(client, prepared)
    when = now_utc()
    with prepared.begin() as db:
        row = db.get(TableSyncTask, task["id"])
        row.enabled, row.next_run_at = True, when - timedelta(days=3)
    assert service.schedule_due(prepared, when) == 1
    assert service.schedule_due(prepared, when) == 0
    with prepared.begin() as db:
        row = db.get(TableSyncTask, task["id"])
        row.next_run_at = when - timedelta(seconds=1)
    assert service.schedule_due(prepared, when) == 0
    with prepared() as db:
        assert len(list(db.scalars(select(TableSyncRun)))) == 1
        assert db.get(TableSyncTask, task["id"]).next_run_at > when


def test_concurrent_claim_has_one_winner_and_recovery_retains_queue(client, prepared):
    create(client, prepared)
    with prepared.begin() as db:
        service.enqueue(db, db.scalar(select(TableSyncTask)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        winners = list(pool.map(lambda worker: service.claim_run(prepared, worker), ["worker1", "worker2"]))
    assert sum(item is not None for item in winners) == 1
    assert service.recover_interrupted(prepared) == 1
    winner = next(item for item in winners if item)
    assert result(prepared, winner)[0] == "interrupted"
    with prepared.begin() as db:
        service.enqueue(db, db.scalar(select(TableSyncTask)))
    assert service.recover_interrupted(prepared) == 0
    assert service.claim_run(prepared, "new-worker")


def test_history_filters_retained_after_task_delete_and_summary_query(client, prepared):
    task, headers = create(client, prepared)
    claim = start(prepared)
    assert service.finish_run(prepared, claim["run_id"], claim["lease_token"], "failed", "测试错误")
    assert not service.finish_run(prepared, claim["run_id"], claim["lease_token"], "success")
    assert client.delete(f"/api/table-sync/tasks/{task['id']}", headers=headers).status_code == 200
    statements = []
    engine = prepared.kw["bind"]
    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())
    event.listen(engine, "before_cursor_execute", record)
    try:
        records = client.get("/api/table-sync/runs?status=failed").json()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert records["total"] == 1 and records["items"][0]["task_name"] == task["name"]
    assert client.get("/api/table-sync/runs?status=success").json()["total"] == 0
    for statement in statements:
        if "from orvibo_jifen_table_sync_runs" in statement:
            assert "source_snapshot" not in statement and "details" not in statement


def test_retention_only_cleans_completed_sync_history(client, prepared):
    create(client, prepared)
    claim = start(prepared)
    service.finish_run(prepared, claim["run_id"], claim["lease_token"], "failed", "旧记录")
    with prepared.begin() as db:
        db.get(TableSyncRun, claim["run_id"]).finished_at = now_utc() - timedelta(days=91)
    assert service.cleanup_history(prepared) == 1
    with prepared() as db:
        assert db.get(TableSyncRun, claim["run_id"]) is None
        assert not list(db.scalars(select(TableSyncLog)))
        assert db.get(Employee, "a") and db.scalar(select(TableSyncTask))
