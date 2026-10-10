import json
import logging
import multiprocessing
import signal
import threading
import time
from datetime import timedelta

from sqlalchemy import delete

from .config import get_settings
from .db import SessionLocal, lock_state, new_id, now_utc
from .delivery import claim_delivery, complete_delivery
from .directory import apply_contact_event, apply_directory
from .feishu import FeishuClient, FeishuError
from .models import LoginState, Preview, Session
from .recall import run_recall_once
from .sync_schedule import SYNC_LEASE, advance_sync_at, first_sync_at, release_sync_claim, sync_is_running

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("jifen.worker")


def event_listener():
    # Run SDK's blocking event loop in its own process, not an asyncio thread.
    import lark_oapi as lark
    settings = get_settings()

    def receive(event):
        payload = json.loads(lark.JSON.marshal(event))
        header = payload["header"]
        if header.get("tenant_key") != settings.feishu_tenant_key:
            raise ValueError("忽略其他企业事件")
        with SessionLocal.begin() as db:
            apply_contact_event(db, header["event_id"], header["event_type"], payload["event"])

    builder = lark.EventDispatcherHandler.builder("", "")
    builder.register_p2_contact_user_created_v3(receive)
    builder.register_p2_contact_user_updated_v3(receive)
    builder.register_p2_contact_user_deleted_v3(receive)
    builder.register_p2_contact_department_created_v3(receive)
    builder.register_p2_contact_department_updated_v3(receive)
    builder.register_p2_contact_department_deleted_v3(receive)
    client = lark.ws.Client(settings.feishu_app_id, settings.feishu_app_secret,
                            event_handler=builder.build(), log_level=lark.LogLevel.ERROR)

    def reconnected():
        with SessionLocal.begin() as db:
            state = lock_state(db)
            state.events_connected_at = now_utc()
            state.sync_requested = True

    def disconnected():
        with SessionLocal.begin() as db:
            lock_state(db).events_connected_at = None

    client.on_reconnected = reconnected
    client.on_reconnecting = disconnected
    # Initial connection is not covered by the reconnect hook; write the
    # attempt timestamp rather than representing it as a verified connection.
    client.start()


def renew_sync_lease(token):
    with SessionLocal.begin() as db:
        state = lock_state(db)
        when = now_utc()
        if state.sync_lease_token != token or not sync_is_running(state, when):
            return False
        state.sync_lease_until = when + SYNC_LEASE
    return True


def sync_heartbeat(token, stopped):
    while not stopped.wait(20):
        try:
            if not renew_sync_lease(token):
                return
        except Exception:
            logger.warning("同步任务续期失败，将在下次心跳重试")


def sync_if_due(client, settings):
    when = now_utc()
    with SessionLocal.begin() as db:
        state = lock_state(db)
        if state.sync_enabled and not state.next_sync_at:
            state.next_sync_at = first_sync_at(when, state.sync_time, state.sync_interval_days)
        elif not state.sync_enabled:
            state.next_sync_at = None
        scheduled_due = state.sync_enabled and state.next_sync_at <= when
        running = sync_is_running(state, when)
        stale_claim = state.sync_started_at and not running
        due = state.sync_requested or not state.last_sync_at or scheduled_due or stale_claim
        if not due or running:
            return
        if state.sync_retry_at and when < state.sync_retry_at:
            return
        if scheduled_due:
            state.next_sync_at = advance_sync_at(state.next_sync_at, when, state.sync_interval_days)
        state.sync_requested = False
        state.sync_started_at = when
        state.sync_retry_at = None
        token = state.sync_lease_token = new_id()
        state.sync_lease_until = when + SYNC_LEASE
        version = state.directory_version
    stopped = threading.Event()
    heartbeat = threading.Thread(target=sync_heartbeat, args=(token, stopped), daemon=True)
    heartbeat.start()
    try:
        departments, users = client.fetch_directory()
        with SessionLocal.begin() as db:
            applied = apply_directory(db, departments, users, settings, expected_version=version, expected_sync_token=token)
        logger.info("组织架构同步完成" if applied else "同步结果已过期，交由当前任务处理")
    except Exception as error:
        detail = str(error) if isinstance(error, (FeishuError, ValueError)) else "同步异常，未应用不完整数据"
        logger.error("组织同步失败：%s", detail)
        with SessionLocal.begin() as db:
            state = lock_state(db)
            if state.sync_lease_token != token:
                return
            state.last_sync_error = detail
            release_sync_claim(state)
            state.sync_retry_at = now_utc() + timedelta(minutes=5)
            state.sync_requested = True
    finally:
        stopped.set()
        heartbeat.join(timeout=5)


def run_once(client, settings):
    if run_recall_once(client, settings, SessionLocal):
        return True
    with SessionLocal.begin() as db:
        task = claim_delivery(db, settings)
    if not task:
        return False
    message_id, failure = None, None
    try:
        message_id = "demo_" + task["uuid"] if settings.demo_mode else client.send_card(task["recipient_open_id"], task["card"], task["uuid"])
    except FeishuError as error:
        failure = error
    except Exception:
        failure = FeishuError("发送结果不确定", uncertain=True, retryable=True)
    with SessionLocal.begin() as db:
        complete_delivery(db, task, settings, message_id=message_id, error=failure)
    return True


def main():
    settings = get_settings()
    settings.validate_runtime()
    client = FeishuClient(settings)
    running = True
    process = None
    sync_thread = None
    next_sync = next_cleanup = next_events = 0

    def shutdown(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        while running:
            tick = time.monotonic()
            if tick >= next_events and settings.feishu_event_enabled and not settings.demo_mode and settings.feishu_app_id:
                if not process or not process.is_alive():
                    if process:
                        process.join()
                        time.sleep(5)
                    process = multiprocessing.Process(target=event_listener, daemon=True)
                    process.start()
                    next_events = tick + 60
            if tick >= next_sync and not settings.demo_mode:
                if not sync_thread or not sync_thread.is_alive():
                    sync_thread = threading.Thread(target=sync_if_due, args=(client, settings), daemon=True)
                    sync_thread.start()
                next_sync = tick + 15
            if tick >= next_cleanup:
                with SessionLocal.begin() as db:
                    db.execute(delete(LoginState).where(LoginState.expires_at < now_utc()))
                    db.execute(delete(Session).where(Session.expires_at < now_utc()))
                    db.execute(delete(Preview).where(Preview.expires_at < now_utc() - timedelta(days=7)))
                next_cleanup = tick + 3600
            sent = run_once(client, settings)
            time.sleep(settings.send_interval_seconds if sent else settings.worker_poll_seconds)
    finally:
        if process and process.is_alive():
            process.terminate()
            process.join(timeout=5)
        if sync_thread and sync_thread.is_alive():
            sync_thread.join(timeout=20)
        if not sync_thread or not sync_thread.is_alive():
            client.close()


if __name__ == "__main__":
    main()
