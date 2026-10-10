from datetime import datetime, timedelta

from .db import now_utc

BEIJING_OFFSET = timedelta(hours=8)
SYNC_LEASE = timedelta(seconds=90)


def sync_is_running(state, when: datetime) -> bool:
    return bool(state.sync_started_at and state.sync_lease_token and state.sync_lease_until and state.sync_lease_until > when)


def release_sync_claim(state):
    state.sync_started_at = None
    state.sync_lease_token = None
    state.sync_lease_until = None


def first_sync_at(when: datetime, clock: str, interval_days: int) -> datetime:
    """Anchor a new plan to today's Beijing date, then advance if already due."""
    hour, minute = map(int, clock.split(":"))
    candidate = (when + BEIJING_OFFSET).replace(hour=hour, minute=minute, second=0, microsecond=0) - BEIJING_OFFSET
    return candidate if candidate > when else candidate + timedelta(days=interval_days)


def advance_sync_at(scheduled_at: datetime, when: datetime, interval_days: int) -> datetime:
    """After downtime run once, skipping missed slots without shifting the plan."""
    interval = timedelta(days=interval_days)
    return scheduled_at + (max(0, (when - scheduled_at) // interval) + 1) * interval


def schedule_view(state, when=None):
    when = when or now_utc()
    next_at = (state.next_sync_at or first_sync_at(when, state.sync_time, state.sync_interval_days)) if state.sync_enabled else None

    def iso(value):
        return value.isoformat() + "Z" if value else None

    return {
        "enabled": state.sync_enabled,
        "interval_days": state.sync_interval_days,
        "time": state.sync_time,
        "next_sync_at": iso(next_at),
        "last_sync_at": iso(state.last_sync_at),
        "last_sync_error": state.last_sync_error,
        "sync_requested": state.sync_requested,
        "sync_started_at": iso(state.sync_started_at),
        "retry_at": iso(state.sync_retry_at),
        "directory_version": state.directory_version,
        "status": "running" if sync_is_running(state, when) else
                  "recovering" if state.sync_started_at else
                  "retry" if state.sync_retry_at and state.sync_requested else
                  "queued" if state.sync_requested or not state.last_sync_at else "idle",
    }
