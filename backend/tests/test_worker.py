import logging
import multiprocessing
import signal
import socket
import time
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call
from uuid import uuid4

import pytest
from pymysql.err import OperationalError as DriverError
from sqlalchemy import func, select
from sqlalchemy.exc import InterfaceError, OperationalError, ProgrammingError, TimeoutError

from app import delivery, directory, worker, worker_health
from app.db import database_error_label, make_engine, transient_database_error
from app.feishu import FeishuError
from app.models import Balance, Delivery, Employee, Ledger, SystemState
from app.worker_health import WorkerHealth, check_health
from test_adjustments import request, submit


def disconnected(code=2003):
    return OperationalError("SECRET SQL", {"secret": "SECRET VALUE"}, DriverError(code, "SECRET DRIVER MESSAGE"))


class StopAfterWaits:
    def __init__(self, count):
        self.count = count
        self.waits = []

    def is_set(self):
        return len(self.waits) >= self.count

    def wait(self, seconds):
        self.waits.append(seconds)
        return self.is_set()


@pytest.fixture
def loop_setup(monkeypatch, settings):
    settings.demo_mode = True  # No real Feishu calls or directory background threads.
    db = Mock()

    @contextmanager
    def begin():
        yield db

    monkeypatch.setattr(worker, "SessionLocal", SimpleNamespace(begin=begin))
    return Mock(), Mock(), db  # client, health, cleanup session


@pytest.mark.parametrize("stage", ["cleanup", "task"])
def test_loop_recovers_database_disconnect(stage, monkeypatch, settings, loop_setup, caplog):
    caplog.set_level(logging.INFO, logger="jifen.worker")
    client, health, db = loop_setup
    run_once = Mock(return_value=False)
    monkeypatch.setattr(worker, "run_once", run_once)
    if stage == "cleanup":
        db.execute.side_effect = [disconnected(), None, None, None]
    else:
        run_once.side_effect = [disconnected(), False]
    stopped = StopAfterWaits(2)
    worker.run_loop(client, settings, stopped, health)
    assert stopped.waits == [5, settings.worker_poll_seconds]
    assert health.record.call_args_list == [call(database_ok=False), call(database_ok=False), call(database_ok=True)]
    assert "已恢复" in caplog.text
    assert "SECRET" not in caplog.text
    client.close.assert_called_once()
    health.clear.assert_called_once()


def test_retry_delay_is_capped_and_resets_after_recovery(monkeypatch, settings, loop_setup):
    client, health, _ = loop_setup
    monkeypatch.setattr(worker, "run_once", Mock(side_effect=[disconnected()] * 6 + [False, disconnected(), False]))
    stopped = StopAfterWaits(9)
    worker.run_loop(client, settings, stopped, health)
    assert stopped.waits == [5, 10, 20, 40, 60, 60, settings.worker_poll_seconds, 5, settings.worker_poll_seconds]


def test_shutdown_interrupts_database_retry(monkeypatch, settings, loop_setup):
    client, health, _ = loop_setup
    run_once = Mock(side_effect=disconnected())
    monkeypatch.setattr(worker, "run_once", run_once)
    worker.run_loop(client, settings, StopAfterWaits(1), health)
    run_once.assert_called_once()
    client.close.assert_called_once()


def test_fatal_error_cleans_up_listener_and_client(monkeypatch, settings, loop_setup):
    client, health, _ = loop_setup
    settings.demo_mode = False
    settings.feishu_app_id = "test-app"
    context = Mock()
    process = context.Process.return_value
    monkeypatch.setattr(worker.multiprocessing, "get_context", Mock(return_value=context))
    thread = Mock()
    thread.is_alive.return_value = False
    monkeypatch.setattr(worker.threading, "Thread", Mock(return_value=thread))
    monkeypatch.setattr(worker, "run_once", Mock(side_effect=ValueError("fatal")))
    with pytest.raises(ValueError, match="fatal"):
        worker.run_loop(client, settings, StopAfterWaits(1), health)
    worker.multiprocessing.get_context.assert_called_once_with("spawn")
    process.start.assert_called_once()
    process.terminate.assert_called_once()
    process.kill.assert_called_once()  # This fake child ignores terminate.
    process.close.assert_called_once()
    client.close.assert_called_once()
    health.clear.assert_called_once()


def test_main_exits_nonzero_without_logging_credentials(monkeypatch, settings, caplog):
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker.signal, "signal", Mock())
    monkeypatch.setattr(worker, "FeishuClient", Mock())
    monkeypatch.setattr(worker, "run_loop", Mock(side_effect=disconnected(1045)))
    with pytest.raises(SystemExit) as error:
        worker.main()
    assert error.value.code == 1
    assert "OperationalError/1045" in caplog.text and "SECRET" not in caplog.text


def test_listener_start_failure_can_be_cleaned_up():
    process = Mock(pid=None)
    worker.stop_event_listener(process)
    process.close.assert_called_once()
    process.join.assert_not_called()
    process.terminate.assert_not_called()


@pytest.fixture
def worker_file():
    # Use an ordinary workspace file: some Windows sandboxes cannot access the
    # restrictive ACL pytest applies to its temporary directories.
    cache = Path(__file__).resolve().parents[2] / ".cache"
    cache.mkdir(exist_ok=True)
    path = cache / f"worker-test-{uuid4().hex}.json"
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)
        path.with_suffix(".tmp").unlink(missing_ok=True)


def wait_for_parent(path):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    Path(path).write_text("ready", encoding="utf-8")
    while True:
        time.sleep(1)


def test_real_spawned_listener_is_stopped_even_if_it_ignores_sigterm(worker_file):
    context = multiprocessing.get_context("spawn")
    process = context.Process(target=wait_for_parent, args=(str(worker_file),), daemon=True)
    process.start()
    try:
        deadline = time.monotonic() + 15
        while not worker_file.exists() and process.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert worker_file.read_text(encoding="utf-8") == "ready"
        worker.stop_event_listener(process)
        assert process._closed  # close() is allowed only after the child has exited.
    finally:
        if not process._closed:
            process.kill()
            process.join(5)
            process.close()


@pytest.mark.parametrize("error,expected", [
    (disconnected(), True), (disconnected(2006), True), (disconnected(2013), True),
    (disconnected(1205), True), (disconnected(1213), True), (TimeoutError(), True),
    (InterfaceError(None, None, DriverError(0, "")), True),
    (disconnected(1045), False), (disconnected(1054), False),
    (ProgrammingError("SQL", {}, DriverError(1146, "missing table")), False),
    (ValueError("bad code"), False),
])
def test_only_transient_database_errors_are_retried(error, expected):
    assert transient_database_error(error) is expected
    assert "SECRET" not in database_error_label(error)


def test_mysql_network_waits_are_bounded():
    engine = make_engine("mysql+pymysql://test@127.0.0.1/jifen_test_worker")
    try:
        # Capture the actual driver call without opening a network connection.
        connect = Mock(side_effect=RuntimeError("captured"))
        engine.dialect.connect = connect
        with pytest.raises(RuntimeError, match="captured"):
            engine.connect()
        for name, seconds in {"connect_timeout": 10, "read_timeout": 30, "write_timeout": 30}.items():
            assert connect.call_args.kwargs[name] == seconds
    finally:
        engine.dispose()


def test_worker_health_tracks_main_loop_not_event_process(worker_file, monkeypatch):
    path = worker_file
    health = WorkerHealth(path)
    monkeypatch.setattr(worker_health.time, "time", lambda: 1000)
    assert check_health(path)
    health.record(database_ok=False)
    assert "数据库" in check_health(path)
    health.record(database_ok=True)
    assert check_health(path) is None
    monkeypatch.setattr(worker_health.time, "time", lambda: 1000 + worker_health.MAX_PROGRESS_AGE + 1)
    assert "未更新" in check_health(path)
    health.clear()
    assert check_health(path)
    path.write_text("broken", encoding="utf-8")
    assert check_health(path)


@pytest.mark.parametrize("delay", [timedelta(seconds=91), timedelta(hours=1)])
def test_sent_card_with_lost_database_commit_uses_existing_uuid(factory, settings, when, monkeypatch, delay):
    submit(factory, settings, when, request())
    with factory.begin() as db:
        db.scalar(select(Delivery)).next_attempt_at = when
    current = [when]
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(delivery, "now_utc", lambda: current[0])
    accepted = {}
    calls = []

    class Client:
        def send_card(self, recipient, card, uuid):
            calls.append(uuid)
            return accepted.setdefault(uuid, "om_one_message")

    original = worker.complete_delivery

    def lost_commit(*args, **kwargs):
        original(*args, **kwargs)
        raise disconnected(2013)  # Roll back the entire completion transaction.

    monkeypatch.setattr(worker, "complete_delivery", lost_commit)
    with pytest.raises(OperationalError):
        worker.run_once(Client(), settings)
    with factory() as db:
        row = db.scalar(select(Delivery))
        assert row.status == "sending" and row.message_id is None and row.attempts == 1
    monkeypatch.setattr(worker, "complete_delivery", original)
    assert not worker.run_once(Client(), settings)  # Lease has not expired.
    assert len(calls) == 1
    current[0] += delay
    worker.run_once(Client(), settings)
    assert not worker.run_once(Client(), settings)
    with factory() as db:
        row = db.scalar(select(Delivery))
        assert row.status == ("sent" if delay.total_seconds() < 3000 else "review")
        assert row.message_id == ("om_one_message" if row.status == "sent" else None)
        assert db.scalar(select(func.count()).select_from(Ledger)) == 1
        assert db.get(Balance, ("a", "2026-10")).total == 65
    assert len(accepted) == 1 and len(set(calls)) == 1
    assert len(calls) == (2 if delay.total_seconds() < 3000 else 1)


def test_real_connection_refusal_recovers_on_next_loop(factory, settings, monkeypatch, caplog):
    settings.demo_mode = True
    health, client = Mock(), Mock()
    calls = 0
    # Reserve a local TCP port without listening: connecting to it must be refused.
    with socket.socket() as endpoint:
        endpoint.bind(("127.0.0.1", 0))
        offline = make_engine(f"mysql+pymysql://test@127.0.0.1:{endpoint.getsockname()[1]}/jifen_test_offline")

        @contextmanager
        def begin():
            nonlocal calls
            calls += 1
            if calls == 1:
                with offline.connect():
                    pytest.fail("The reserved port must refuse connections")
            with factory.begin() as db:
                yield db

        monkeypatch.setattr(worker, "SessionLocal", SimpleNamespace(begin=begin))
        stopped = StopAfterWaits(2)
        try:
            worker.run_loop(client, settings, stopped, health)
        finally:
            offline.dispose()
    assert stopped.waits == [5, settings.worker_poll_seconds]
    assert health.record.call_args_list[-1] == call(database_ok=True)
    assert "OperationalError/2003" in caplog.text
    client.send_card.assert_not_called()


def test_169_stopped_notifications_are_never_sent_and_keep_scores(factory, settings, when, monkeypatch):
    recipient_ids = [f"recipient-{index}" for index in range(169)]
    with factory.begin() as db:
        db.add_all(Employee(id=id, open_id="ou_" + id, name=id, status="active") for id in recipient_ids)
    submit(factory, settings, when, request(recipients={"person_ids": recipient_ids}))
    reason = "操作人要求停止通知，保留积分及全部操作记录"
    with factory.begin() as db:
        for row in db.scalars(select(Delivery)):
            row.status = "review"
            row.last_error = reason
    monkeypatch.setattr(worker, "SessionLocal", factory)
    client = Mock()
    for _ in range(3):
        assert not worker.run_once(client, settings)
    client.send_card.assert_not_called()
    with factory() as db:
        rows = db.scalars(select(Delivery)).all()
        assert len(rows) == 169
        assert all(row.status == "review" and row.attempts == 0 and row.message_id is None
                   and row.first_attempt_at is None and row.last_error == reason for row in rows)
        assert db.scalar(select(func.count()).select_from(Ledger)) == 1
        assert db.get(Balance, ("a", "2026-10")).total == 65


@pytest.mark.parametrize("failure_at", [1, 2])
def test_sync_recovers_when_claim_or_failure_record_cannot_reach_database(factory, settings, when, monkeypatch, failure_at, caplog):
    calls = 0
    current = [when]

    @contextmanager
    def unstable_begin():
        nonlocal calls
        calls += 1
        if calls == failure_at:
            raise disconnected()
        with factory.begin() as db:
            yield db

    monkeypatch.setattr(worker, "SessionLocal", SimpleNamespace(begin=unstable_begin))
    monkeypatch.setattr(worker, "now_utc", lambda: current[0])
    monkeypatch.setattr(directory, "now_utc", lambda: current[0])
    failed = Mock()
    failed.fetch_directory.side_effect = FeishuError("暂不可用")
    worker.sync_if_due(failed, settings)
    current[0] += timedelta(seconds=91)  # Recover a claim whose error could not be recorded.
    recovered = Mock()
    recovered.fetch_directory.return_value = ([], [{"open_id": "ou_a", "name": "张三", "status": {"is_resigned": False}}])
    worker.sync_if_due(recovered, settings)
    recovered.fetch_directory.assert_called_once()
    with factory() as db:
        state = db.get(SystemState, 1)
        assert state.last_sync_at == current[0]
        assert state.sync_lease_token is None and state.sync_started_at is None
    assert "数据库暂不可用" in caplog.text and "SECRET" not in caplog.text
