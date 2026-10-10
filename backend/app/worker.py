import json
import logging
import multiprocessing
import signal
import threading
import time
from datetime import timedelta

from sqlalchemy import delete

from .config import get_settings
from .db import SessionLocal, lock_state, now_utc
from .delivery import claim_delivery, complete_delivery
from .directory import apply_contact_event, apply_directory
from .feishu import FeishuClient, FeishuError
from .models import LoginState, Preview, Session
from .recall import run_recall_once

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


def sync_if_due(client, settings):
    when = now_utc()
    with SessionLocal.begin() as db:
        state = lock_state(db)
        due = state.sync_requested or not state.last_sync_at or when - state.last_sync_at >= timedelta(seconds=settings.sync_interval_seconds)
        if not due or state.sync_started_at and when - state.sync_started_at < timedelta(minutes=30):
            return
        state.sync_requested = False
        state.sync_started_at = when
        version = state.directory_version
    try:
        departments, users = client.fetch_directory()
        with SessionLocal.begin() as db:
            apply_directory(db, departments, users, settings, expected_version=version)
        logger.info("组织架构同步完成")
    except Exception as error:
        detail = str(error) if isinstance(error, (FeishuError, ValueError)) else "同步异常，未应用不完整数据"
        logger.error("组织同步失败：%s", detail)
        with SessionLocal.begin() as db:
            state = lock_state(db)
            state.last_sync_error = detail
            # Keep claim for one minute to avoid hammering a failing service.
            state.sync_started_at = when - timedelta(minutes=29)
            state.sync_requested = True


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
