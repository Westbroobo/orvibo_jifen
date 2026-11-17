import multiprocessing
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.db import lock_state
from app.models import TableSyncRun, TableSyncTask
from app.table_sync import health, service, worker


class ClockStop:
    def __init__(self, count):
        self.count = count
        self.tick = 0
        self.waits = []

    def is_set(self):
        return len(self.waits) >= self.count

    def wait(self, seconds):
        self.waits.append(seconds)
        self.tick += seconds
        return self.is_set()


class Child:
    def __init__(self, events, *, ignore_terminate=False, ignore_kill=False):
        self.events = events
        self.ignore_terminate = ignore_terminate
        self.ignore_kill = ignore_kill
        self.pid = None
        self.exitcode = None
        self.alive = False
        self.closed = False

    def start(self):
        self.events.append("start")
        self.pid, self.alive = 123, True

    def is_alive(self):
        if self.closed:
            raise ValueError("process closed")
        return self.alive

    def terminate(self):
        self.events.append("terminate")
        if not self.ignore_terminate:
            self.alive, self.exitcode = False, -15

    def join(self, timeout=0):
        self.events.append("join")

    def kill(self):
        self.events.append("kill")
        if not self.ignore_kill:
            self.alive, self.exitcode = False, -9

    def close(self):
        assert not self.alive
        self.events.append("close")
        self.closed = True


@pytest.fixture
def supervisor(monkeypatch):
    events = []
    claim = {"run_id": "run", "task_id": "task", "lease_token": "token"}
    child = Child(events, ignore_terminate=True)
    context = SimpleNamespace(Process=Mock(return_value=child))
    gate = Mock()
    gate.close.side_effect = lambda: events.append("gate_close")
    for name in ("schedule_due", "cleanup_history", "recover_interrupted"):
        monkeypatch.setattr(service, name, Mock())
    monkeypatch.setattr(service, "claim_run", Mock(side_effect=[claim] + [None] * 20))
    monkeypatch.setattr(service, "renew_run", Mock(return_value=True))
    monkeypatch.setattr(worker, "run_is_terminal", Mock(return_value=False))
    monkeypatch.setattr(worker, "wait_for_previous_runs", Mock(return_value=True))
    finish = Mock(side_effect=lambda *args, **kwargs: events.append("finish"))
    monkeypatch.setattr(service, "finish_run", finish)
    return SimpleNamespace(events=events, child=child, context=context, gate=gate, finish=finish,
                           factory=Mock(), health=Mock())


def loop(state, settings, stopped):
    return worker.run_loop(state.factory, settings, stopped, state.health, context=state.context,
                           gate=state.gate, clock=lambda: stopped.tick)


def test_shutdown_kills_and_joins_before_releasing_the_task(settings, supervisor):
    loop(supervisor, settings, ClockStop(1))
    events = supervisor.events
    assert events.index("kill") < events.index("close") < events.index("finish") < events.index("gate_close")
    assert supervisor.finish.call_args.args[3] == "interrupted"
    assert supervisor.context.Process.call_args.kwargs["daemon"] is True
    assert supervisor.context.Process.call_args.kwargs["target"] is worker.execute_child
    service.recover_interrupted.assert_called_once_with(supervisor.factory)


def test_timeout_stops_child_before_marking_failure(settings, supervisor, monkeypatch):
    monkeypatch.setattr(worker, "MAX_RUN_SECONDS", 2)
    loop(supervisor, settings, ClockStop(3))
    assert supervisor.events.index("close") < supervisor.events.index("finish")
    assert supervisor.finish.call_args.args[3] == "failed"
    assert "超过 2 秒" in supervisor.finish.call_args.kwargs["error"]
    supervisor.context.Process.assert_called_once()  # No replacement while an old child is alive.


@pytest.mark.parametrize("lost", ["gate", "lease"])
def test_lost_ownership_stops_execution_before_exit(lost, settings, supervisor, monkeypatch):
    monkeypatch.setattr(worker, "LEASE_REFRESH_SECONDS", 1)
    if lost == "gate":
        supervisor.gate.check.side_effect = [None, None, worker.SingletonLost("lost")]
        expected = worker.SingletonLost
    else:
        service.renew_run.return_value = False
        expected = worker.LeaseLost
    with pytest.raises(expected):
        loop(supervisor, settings, ClockStop(3))
    assert supervisor.child.closed
    assert supervisor.events.index("close") < supervisor.events.index("finish") < supervisor.events.index("gate_close")
    supervisor.health.clear.assert_called_once()


def test_new_instance_does_not_recover_jobs_if_gate_is_busy(settings, supervisor):
    supervisor.gate.acquire.side_effect = worker.SingletonLost("already running")
    with pytest.raises(worker.SingletonLost):
        loop(supervisor, settings, ClockStop(1))
    service.recover_interrupted.assert_not_called()
    service.claim_run.assert_not_called()
    supervisor.context.Process.assert_not_called()


def test_shutdown_during_takeover_wait_does_not_recover_old_tasks(settings, supervisor):
    worker.wait_for_previous_runs.return_value = False
    loop(supervisor, settings, ClockStop(1))
    service.recover_interrupted.assert_not_called()
    service.claim_run.assert_not_called()
    supervisor.context.Process.assert_not_called()
    supervisor.gate.close.assert_called_once()


def test_completion_just_before_heartbeat_does_not_restart_the_supervisor(settings, supervisor, monkeypatch):
    monkeypatch.setattr(worker, "LEASE_REFRESH_SECONDS", 1)
    service.renew_run.return_value = False
    worker.run_is_terminal.return_value = True
    loop(supervisor, settings, ClockStop(2))
    assert supervisor.child.closed
    supervisor.finish.assert_not_called()  # The child's final status stays intact.
    assert service.claim_run.call_count == 2


def test_idle_polling_does_not_hit_database_every_second(settings, supervisor):
    service.claim_run.side_effect = None
    service.claim_run.return_value = None
    loop(supervisor, settings, ClockStop(3))
    assert service.schedule_due.call_count == 3
    assert service.claim_run.call_count == 3
    service.cleanup_history.assert_called_once()


def test_still_alive_child_cannot_release_the_run():
    events = []
    process = Child(events, ignore_terminate=True, ignore_kill=True)
    process.start()
    with pytest.raises(RuntimeError, match="禁止释放"):
        worker.stop_process(process)
    assert "close" not in events


def test_unstoppable_child_does_not_release_the_singleton_gate(settings, supervisor, monkeypatch):
    supervisor.child.ignore_kill = True
    monkeypatch.setattr(worker, "MAX_RUN_SECONDS", 1)
    with pytest.raises(RuntimeError, match="禁止释放"):
        loop(supervisor, settings, ClockStop(3))
    supervisor.finish.assert_not_called()
    supervisor.gate.close.assert_not_called()


def test_completion_database_failure_does_not_stop_a_closed_process_twice(settings, supervisor, monkeypatch):
    monkeypatch.setattr(worker, "MAX_RUN_SECONDS", 1)
    supervisor.finish.side_effect = RuntimeError("database down")
    with pytest.raises(RuntimeError, match="database down"):
        loop(supervisor, settings, ClockStop(3))
    assert supervisor.events.count("close") == 1


def test_child_builds_and_disposes_its_own_pool(settings, monkeypatch, caplog):
    factory = SimpleNamespace(kw={"bind": Mock()})
    create = Mock(return_value=factory)
    monkeypatch.setattr(worker, "make_session_factory", create)
    monkeypatch.setattr(worker, "bind_to_parent", lambda _: True)
    monkeypatch.setattr(worker.signal, "signal", Mock())
    monkeypatch.setattr(service, "execute_run", Mock(side_effect=RuntimeError("SECRET RESPONSE")))
    with pytest.raises(SystemExit) as error:
        worker.execute_child(settings.model_dump(), "run", "token", 1)
    assert error.value.code == 1
    create.assert_called_once_with(settings.database_url, pool_size=1)
    factory.kw["bind"].dispose.assert_called_once()
    assert "SECRET" not in caplog.text


def test_pool_size_is_bounded_and_does_not_change_the_shared_database_pool():
    factory = worker.make_session_factory("mysql+pymysql://test@127.0.0.1/jifen_test_worker")
    engine = factory.kw["bind"]
    try:
        assert engine.pool.size() == 2
        assert engine.pool._max_overflow == 0
    finally:
        engine.dispose()


def test_mysql_singleton_has_no_open_transaction_and_excludes_second_instance(factory):
    url = factory.kw["bind"].url.render_as_string(hide_password=False)
    isolated = worker.make_session_factory(url)
    first = worker.SingletonGate(isolated.kw["bind"])
    second = worker.SingletonGate(isolated.kw["bind"])
    try:
        first.acquire()
        assert not first.connection.in_transaction()
        first.check()
        assert not first.connection.in_transaction()
        with pytest.raises(worker.SingletonLost):
            second.acquire()
        first.check()
        first.close()
        second.acquire()
        second.check()
    finally:
        first.close()
        second.close()
        isolated.kw["bind"].dispose()


def test_timeout_state_is_saved_without_touching_original_global_lock(factory, settings, monkeypatch):
    task = TableSyncTask(id="task", name="worker test", source_kind="selection", selection={},
                         target_url="https://example.feishu.cn/base/base?table=table", base_token="base", table_id="table",
                         field_mapping={}, created_by="admin", updated_by="admin")
    with factory.begin() as db:
        db.add(task)
        db.flush()
        run_id = service.enqueue(db, task).id
    events = []
    process = Child(events)
    context = SimpleNamespace(Process=Mock(return_value=process))
    stopped = ClockStop(2)
    monkeypatch.setattr(worker, "MAX_RUN_SECONDS", 1)
    engine = factory.kw["bind"]

    def forbid_global_lock(conn, cursor, statement, parameters, context, executemany):
        assert "orvibo_jifen_system_state" not in statement

    with factory.begin() as db:
        lock_state(db)
        event.listen(engine, "before_cursor_execute", forbid_global_lock)
        try:
            worker.run_loop(factory, settings, stopped, Mock(), context=context, gate=Mock(), clock=lambda: stopped.tick)
        finally:
            event.remove(engine, "before_cursor_execute", forbid_global_lock)
    with factory() as db:
        run = db.get(TableSyncRun, run_id)
        assert run.status == "failed" and "超过 1 秒" in run.error
        assert db.get(TableSyncTask, "task").active_run_id is None


def test_takeover_waits_for_latest_lease_and_request_grace_without_busy_polling(monkeypatch):
    when = datetime(2026, 11, 17)
    stopped = ClockStop(20)
    gate, check = Mock(), Mock()
    seen = []

    def deadline(_):
        seen.append(stopped.tick)
        # A lease renewal observed during handoff must extend the wait.
        return when + timedelta(seconds=30 if stopped.tick < 30 else 60)

    monkeypatch.setattr(worker, "previous_run_deadline", deadline)
    assert worker.wait_for_previous_runs(Mock(), stopped, check, gate,
                                        utc_clock=lambda: when + timedelta(seconds=stopped.tick))
    assert stopped.tick == 60 + worker.TAKEOVER_GRACE_SECONDS
    assert all(0 < delay <= worker.POLL_SECONDS for delay in stopped.waits)
    assert gate.check.call_count == len(seen)
    assert all(call.kwargs == {"database_ok": True} for call in check.record.call_args_list)


def test_takeover_aborts_on_stop_or_lost_gate_without_recovering(monkeypatch):
    when = datetime(2026, 11, 17)
    monkeypatch.setattr(worker, "previous_run_deadline", lambda _: when)
    stopped, gate = ClockStop(1), Mock()
    assert not worker.wait_for_previous_runs(Mock(), stopped, Mock(), gate, utc_clock=lambda: when)
    stopped = ClockStop(3)
    gate.check.side_effect = worker.SingletonLost("gate lost")
    with pytest.raises(worker.SingletonLost):
        worker.wait_for_previous_runs(Mock(), stopped, Mock(), gate, utc_clock=lambda: when)
    assert not stopped.waits


def test_takeover_without_running_rows_returns_immediately(monkeypatch):
    monkeypatch.setattr(worker, "previous_run_deadline", lambda _: None)
    stopped = ClockStop(1)
    assert worker.wait_for_previous_runs(Mock(), stopped, Mock(), Mock())
    assert not stopped.waits


@pytest.fixture
def health_path():
    cache = Path(__file__).resolve().parents[2] / ".cache"
    cache.mkdir(exist_ok=True)
    path = cache / f"table-sync-worker-test-{uuid4().hex}.json"
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)
        path.with_suffix(".tmp").unlink(missing_ok=True)


def test_health_is_separate_and_reports_stale_or_failed_supervisor(health_path, monkeypatch):
    assert health.HEALTH_FILE.name != "orvibo-jifen-worker-health.json"
    check = health.TableSyncHealth(health_path)
    monkeypatch.setattr(health.time, "time", lambda: 1000)
    assert health.check_health(health_path)
    check.record(database_ok=False)
    assert "数据库" in health.check_health(health_path)
    check.record(database_ok=True, run_id="run")
    assert health.check_health(health_path) is None
    monkeypatch.setattr(health.time, "time", lambda: 1000 + health.MAX_PROGRESS_AGE + 1)
    assert "未更新" in health.check_health(health_path)
    check.clear()
    assert health.check_health(health_path)


def test_actual_spawned_child_is_stopped_before_releasing_process_handle():
    # A standard-library target avoids importing this whole test module in a
    # fresh Windows interpreter. Terminate-ignoring children are covered above.
    process = multiprocessing.get_context("spawn").Process(target=time.sleep, args=(60,))
    process.start()
    try:
        assert process.pid is not None and process.is_alive()
        worker.stop_process(process)
        assert process._closed
    finally:
        if not process._closed:
            process.kill()
            process.join(5)
            process.close()
