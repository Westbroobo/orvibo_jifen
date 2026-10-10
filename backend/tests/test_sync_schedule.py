from datetime import datetime, timedelta
from threading import Event, Thread

import pytest
from pydantic import ValidationError

from app import worker
from app.directory import apply_contact_event
from app.feishu import FeishuError
from app.models import Employee, SystemState
from app.schemas import SyncScheduleRequest
from app.sync_schedule import SYNC_LEASE, advance_sync_at, first_sync_at, schedule_view


@pytest.mark.parametrize("when,clock,days,expected", [
    ("2026-10-09T17:00", "02:00", 1, "2026-10-09T18:00"),
    ("2026-10-09T18:00", "02:00", 1, "2026-10-10T18:00"),
    ("2026-10-09T18:01", "02:00", 7, "2026-10-16T18:00"),
    ("2026-12-31T16:00", "00:00", 1, "2027-01-01T16:00"),
    ("2028-02-28T18:01", "02:00", 1, "2028-02-29T18:00"),
])
def test_beijing_schedule_boundaries(when, clock, days, expected):
    assert first_sync_at(datetime.fromisoformat(when), clock, days) == datetime.fromisoformat(expected)


def test_advance_skips_missed_runs_without_drifting():
    original = datetime(2026, 10, 1, 18)
    assert advance_sync_at(original, original, 7) == datetime(2026, 10, 8, 18)
    assert advance_sync_at(original, datetime(2026, 10, 20, 20), 7) == datetime(2026, 10, 22, 18)


@pytest.mark.parametrize("patch", [
    {"interval_days": 0}, {"interval_days": 366}, {"interval_days": 1.5},
    {"interval_days": True}, {"enabled": "true"}, {"time": "24:00"},
    {"time": "02:60"}, {"time": "2:00"}, {"time": "02:00:00"}, {"extra": 1},
])
def test_invalid_schedule_rejected(patch):
    with pytest.raises(ValidationError):
        SyncScheduleRequest(**({"enabled": True, "interval_days": 1, "time": "02:00"} | patch))


class DirectoryClient:
    def __init__(self):
        self.calls = 0

    def fetch_directory(self):
        self.calls += 1
        return [], [{"open_id": "ou_a", "name": "张三", "status": {"is_resigned": False}}]


@pytest.fixture
def sync_clock(factory, monkeypatch):
    current = [datetime(2026, 10, 9, 17)]  # 北京时间 10 月 10 日 01:00
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "now_utc", lambda: current[0])
    from app import directory
    monkeypatch.setattr(directory, "now_utc", lambda: current[0])
    with factory.begin() as db:
        state = db.get(SystemState, 1)
        state.last_sync_at = current[0] - timedelta(days=1)
        state.sync_requested = False
    return current


def test_scheduled_sync_survives_restart_and_manual_does_not_shift(factory, settings, sync_clock):
    client = DirectoryClient()
    worker.sync_if_due(client, settings)
    assert client.calls == 0
    with factory.begin() as db:
        state = db.get(SystemState, 1)
        assert state.next_sync_at == datetime(2026, 10, 9, 18)
        state.sync_requested = True
    worker.sync_if_due(client, settings)
    assert client.calls == 1
    with factory() as db:
        assert db.get(SystemState, 1).next_sync_at == datetime(2026, 10, 9, 18)
    sync_clock[0] = datetime(2026, 10, 9, 18)
    worker.sync_if_due(client, settings)
    assert client.calls == 2
    restarted = DirectoryClient()
    worker.sync_if_due(restarted, settings)
    assert restarted.calls == 0
    with factory() as db:
        assert db.get(SystemState, 1).next_sync_at == datetime(2026, 10, 10, 18)


def test_disabled_schedule_still_allows_manual_and_first_sync(factory, settings, sync_clock):
    with factory.begin() as db:
        db.get(SystemState, 1).sync_enabled = False
    client = DirectoryClient()
    worker.sync_if_due(client, settings)
    assert client.calls == 0
    with factory.begin() as db:
        db.get(SystemState, 1).sync_requested = True
    worker.sync_if_due(client, settings)
    assert client.calls == 1
    with factory.begin() as db:
        state = db.get(SystemState, 1)
        assert state.next_sync_at is None
        state.last_sync_at = None
    worker.sync_if_due(client, settings)
    assert client.calls == 2


def test_downtime_runs_once_then_returns_to_original_plan(factory, settings, sync_clock):
    with factory.begin() as db:
        state = db.get(SystemState, 1)
        state.sync_interval_days = 7
        state.next_sync_at = datetime(2026, 10, 1, 18)
    sync_clock[0] = datetime(2026, 10, 20, 20)
    client = DirectoryClient()
    worker.sync_if_due(client, settings)
    worker.sync_if_due(client, settings)
    assert client.calls == 1
    with factory() as db:
        assert db.get(SystemState, 1).next_sync_at == datetime(2026, 10, 22, 18)


def test_worker_crash_recovers_expired_claim_without_waiting_for_next_day(factory, settings, sync_clock):
    original = datetime(2026, 10, 11, 18)
    with factory.begin() as db:
        state = db.get(SystemState, 1)
        state.next_sync_at = original
        state.sync_started_at = sync_clock[0]
        state.sync_lease_token = "crashed-task"
        state.sync_lease_until = sync_clock[0] + SYNC_LEASE
    client = DirectoryClient()
    worker.sync_if_due(client, settings)
    assert client.calls == 0
    sync_clock[0] += SYNC_LEASE
    worker.sync_if_due(client, settings)
    assert client.calls == 1
    with factory() as db:
        state = db.get(SystemState, 1)
        assert state.next_sync_at == original and state.sync_started_at is None
        assert state.sync_lease_token is None and state.sync_lease_until is None


def test_legacy_claim_from_previous_worker_is_recovered_immediately(factory, settings, sync_clock):
    with factory.begin() as db:
        state = db.get(SystemState, 1)
        state.sync_started_at = sync_clock[0] - timedelta(seconds=20)
        assert schedule_view(state, sync_clock[0])["status"] == "recovering"
    client = DirectoryClient()
    worker.sync_if_due(client, settings)
    assert client.calls == 1
    with factory() as db:
        assert schedule_view(db.get(SystemState, 1), sync_clock[0])["status"] == "idle"


def test_heartbeat_prevents_other_workers_from_taking_over(factory, settings, sync_clock):
    with factory.begin() as db:
        state = db.get(SystemState, 1)
        state.sync_started_at = sync_clock[0]
        state.sync_lease_token = "live-task"
        state.sync_lease_until = sync_clock[0] + SYNC_LEASE
    sync_clock[0] += timedelta(seconds=60)
    assert worker.renew_sync_lease("live-task")
    sync_clock[0] += timedelta(seconds=60)
    client = DirectoryClient()
    worker.sync_if_due(client, settings)
    assert client.calls == 0
    with factory() as db:
        assert schedule_view(db.get(SystemState, 1), sync_clock[0])["status"] == "running"
    assert not worker.renew_sync_lease("wrong-task")
    sync_clock[0] += timedelta(seconds=30)
    assert not worker.renew_sync_lease("live-task")


@pytest.mark.parametrize("fails", [False, True])
def test_expired_task_cannot_overwrite_newer_task(factory, settings, sync_clock, fails):
    class Superseded(DirectoryClient):
        def fetch_directory(self):
            with factory.begin() as db:
                state = db.get(SystemState, 1)
                state.sync_lease_token = "new-task"
                state.sync_lease_until = sync_clock[0] + SYNC_LEASE
                state.last_sync_error = "new-task-error"
            if fails:
                raise FeishuError("old-task-error")
            return super().fetch_directory()
    with factory.begin() as db:
        db.get(SystemState, 1).sync_requested = True
    worker.sync_if_due(Superseded(), settings)
    with factory() as db:
        state = db.get(SystemState, 1)
        assert state.sync_lease_token == "new-task"
        assert state.last_sync_error == "new-task-error"
        assert state.directory_version == 0


def test_event_during_fetch_releases_lease_and_queues_resync(factory, settings, sync_clock):
    class Changed(DirectoryClient):
        def fetch_directory(self):
            with factory.begin() as db:
                apply_contact_event(db, "left-during-sync", "contact.user.deleted_v3", {"object": {"open_id": "ou_a"}})
            return super().fetch_directory()
    with factory.begin() as db:
        db.get(SystemState, 1).sync_requested = True
    worker.sync_if_due(Changed(), settings)
    with factory() as db:
        state = db.get(SystemState, 1)
        assert state.sync_lease_token is None and state.sync_lease_until is None
        assert state.sync_started_at is None and state.sync_requested
        assert db.get(Employee, "a").status == "resigned"


def test_failure_waits_five_minutes_and_preserves_people(factory, settings, sync_clock):
    class Unavailable(DirectoryClient):
        def fetch_directory(self):
            self.calls += 1
            raise FeishuError("通讯录不可用")
    with factory.begin() as db:
        db.get(SystemState, 1).sync_requested = True
    client = Unavailable()
    worker.sync_if_due(client, settings)
    with factory() as db:
        state = db.get(SystemState, 1)
        assert state.sync_started_at is None
        assert state.sync_retry_at == sync_clock[0] + timedelta(minutes=5)
        assert db.get(Employee, "a").status == "active"
    sync_clock[0] += timedelta(minutes=4)
    worker.sync_if_due(client, settings)
    assert client.calls == 1
    sync_clock[0] += timedelta(minutes=1)
    recovered = DirectoryClient()
    worker.sync_if_due(recovered, settings)
    assert recovered.calls == 1
    with factory() as db:
        assert db.get(SystemState, 1).sync_retry_at is None


def test_event_sync_does_not_shift_schedule(factory, settings, sync_clock):
    original = datetime(2026, 10, 11, 18)
    with factory.begin() as db:
        db.get(SystemState, 1).next_sync_at = original
        apply_contact_event(db, "new-employee", "contact.user.created_v3", {})
    client = DirectoryClient()
    worker.sync_if_due(client, settings)
    assert client.calls == 1
    with factory() as db:
        assert db.get(SystemState, 1).next_sync_at == original


def test_settings_changed_during_fetch_are_preserved(factory, settings, sync_clock):
    changed = datetime(2026, 10, 12, 19)
    class Changing(DirectoryClient):
        def fetch_directory(self):
            with factory.begin() as db:
                state = db.get(SystemState, 1)
                state.sync_interval_days = 3
                state.sync_time = "03:00"
                state.next_sync_at = changed
            return super().fetch_directory()
    with factory.begin() as db:
        db.get(SystemState, 1).sync_requested = True
    worker.sync_if_due(Changing(), settings)
    with factory() as db:
        state = db.get(SystemState, 1)
        assert (state.sync_interval_days, state.sync_time, state.next_sync_at) == (3, "03:00", changed)


def test_concurrent_workers_only_fetch_once(factory, settings, sync_clock):
    entered, release = Event(), Event()
    class Blocking(DirectoryClient):
        def fetch_directory(self):
            entered.set()
            assert release.wait(10)
            return super().fetch_directory()
    with factory.begin() as db:
        db.get(SystemState, 1).sync_requested = True
    first, second = Blocking(), DirectoryClient()
    thread = Thread(target=worker.sync_if_due, args=(first, settings))
    thread.start()
    try:
        assert entered.wait(10)
        worker.sync_if_due(second, settings)
        assert second.calls == 0
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive() and first.calls == 1
