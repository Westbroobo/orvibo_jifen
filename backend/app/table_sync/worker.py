"""Single-instance supervisor for table sync; delivery workers are independent."""

import ctypes
import logging
import multiprocessing
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from ..config import Settings, get_settings
from ..db import AppSession, database_error_label, now_utc
from ..models import TableSyncRun
from . import service
from .health import TableSyncHealth


logger = logging.getLogger("jifen.table_sync.worker")
POLL_SECONDS = 15
LEASE_REFRESH_SECONDS = 15
MAX_RUN_SECONDS = 900
STOP_GRACE_SECONDS = 5
CLEANUP_SECONDS = 300
TAKEOVER_GRACE_SECONDS = 90
LOCK_NAME = "orvibo_jifen_table_sync_worker"
_local_gate = threading.Lock()


class SingletonLost(RuntimeError):
    pass


class LeaseLost(RuntimeError):
    pass


def make_session_factory(database_url, *, pool_size=2):
    """One gate connection and one short-transaction connection in the parent."""
    address = make_url(database_url)
    options = {"pool_pre_ping": True}
    if address.get_backend_name() == "sqlite":
        options["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        options.update(pool_size=pool_size, max_overflow=0, pool_timeout=5,
                       pool_recycle=1800, isolation_level="READ COMMITTED",
                       connect_args={"connect_timeout": 10, "read_timeout": 30, "write_timeout": 30})
    engine = create_engine(database_url, **options)
    return sessionmaker(engine, class_=AppSession, expire_on_commit=False)


class SingletonGate:
    """A session advisory lock; no row lock or transaction spans a job."""
    def __init__(self, engine):
        self.engine = engine
        self.connection = None
        self.local = False

    def acquire(self):
        if self.engine.dialect.name == "sqlite":
            if not _local_gate.acquire(blocking=False):
                raise SingletonLost("名单同步服务已经运行")
            self.local = True
            return
        self.connection = self.engine.connect()
        try:
            acquired = self.connection.scalar(text("SELECT GET_LOCK(:name, 0)"), {"name": LOCK_NAME})
            self.connection.commit()
            if acquired != 1:
                raise SingletonLost("名单同步服务已经运行，拒绝启动第二个执行者")
        except BaseException:
            self.close()
            raise

    def check(self):
        if self.local:
            return
        if self.connection is None or self.connection.closed or self.connection.invalidated:
            raise SingletonLost("名单同步独占连接已经失效")
        owned = self.connection.scalar(
            text("SELECT IS_USED_LOCK(:name) = CONNECTION_ID()"), {"name": LOCK_NAME})
        self.connection.commit()
        if owned != 1:
            raise SingletonLost("名单同步服务已失去独占执行权")

    def close(self):
        if self.local:
            self.local = False
            _local_gate.release()
        connection, self.connection = self.connection, None
        if connection is None:
            return
        try:
            if not connection.closed and not connection.invalidated:
                connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": LOCK_NAME})
                connection.commit()
        except Exception:
            logger.warning("名单同步独占连接关闭时已不可用")
        finally:
            connection.close()


def bind_to_parent(parent_pid):
    """An orphan must never continue a write after the supervisor is killed."""
    if sys.platform.startswith("linux"):
        library = ctypes.CDLL(None, use_errno=True)
        if library.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
            raise RuntimeError("无法绑定名单同步子进程生命周期")
        if os.getppid() != parent_pid:
            return False
    parent = multiprocessing.parent_process()
    return parent is None or parent.is_alive()


def execute_child(settings_values, run_id, lease_token, parent_pid):
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if not bind_to_parent(parent_pid):
        return
    settings = Settings(_env_file=None, **settings_values)
    factory = make_session_factory(settings.database_url, pool_size=1)
    try:
        service.execute_run(factory, run_id, lease_token, settings)
    except Exception as error:
        logger.error("名单同步执行进程异常退出（%s）", database_error_label(error))
        raise SystemExit(1) from None
    finally:
        factory.kw["bind"].dispose()


def stop_process(process):
    """Return only after the child cannot make another external request."""
    if process.pid is None:
        process.close()
        return
    if process.is_alive():
        process.terminate()
        process.join(timeout=STOP_GRACE_SECONDS)
        if process.is_alive():
            process.kill()
            process.join(timeout=STOP_GRACE_SECONDS)
    else:
        process.join(timeout=0)
    if process.is_alive():
        raise RuntimeError("名单同步执行进程未终止，禁止释放运行任务")
    process.close()


@dataclass
class ActiveRun:
    claim: dict
    process: object
    started: float
    renewed: float


def finish_active(factory, active, status, error):
    service.finish_run(factory, active.claim["run_id"], active.claim["lease_token"], status, error=error)


def run_is_terminal(factory, run_id):
    with factory() as db:
        return db.scalar(select(TableSyncRun.status).where(TableSyncRun.id == run_id)) in service.TERMINAL


def previous_run_deadline(factory):
    with factory() as db:
        return db.scalar(select(func.max(func.coalesce(TableSyncRun.lease_until, TableSyncRun.progress_at,
                             TableSyncRun.started_at, TableSyncRun.created_at)))
                         .where(TableSyncRun.status == "running"))


def wait_for_previous_runs(factory, stopped, health, gate, *, utc_clock=None):
    """Allow old requests to settle after a lost MySQL gate session.

    Losing GET_LOCK does not instantly stop the previous child. Wait until its
    last lease and an additional request grace have passed, re-reading renewals
    before recovering it. This bounds ordinary connection-loss handoff; it is
    not a remote API fencing mechanism against indefinitely paused processes.
    """
    utc_clock = utc_clock or now_utc
    while not stopped.is_set():
        gate.check()
        deadline = previous_run_deadline(factory)  # Session closes before wait.
        if deadline is None:
            return True
        remaining = (deadline - utc_clock()).total_seconds() + TAKEOVER_GRACE_SECONDS
        if remaining <= 0:
            return True
        health.record(database_ok=True)
        stopped.wait(min(POLL_SECONDS, remaining))
    return False


def run_loop(factory, settings, stopped, health, *, context=None, gate=None, clock=None):
    context = context or multiprocessing.get_context("spawn")
    clock = clock or time.monotonic
    gate = gate or SingletonGate(factory.kw["bind"])
    worker_id = str(uuid4())
    active = None
    acquired = False
    next_schedule = next_claim = next_gate = next_health = next_cleanup = 0
    try:
        gate.acquire()
        acquired = True
        health.record(database_ok=False)
        # The gate is held, and spawn children die with the previous Linux parent.
        # Never reclaim a live execution based only on a lease timestamp.
        if not wait_for_previous_runs(factory, stopped, health, gate):
            return
        service.recover_interrupted(factory)
        while not stopped.is_set():
            tick = clock()
            if tick >= next_gate:
                gate.check()
                next_gate = tick + LEASE_REFRESH_SECONDS
            if active:
                if not active.process.is_alive():
                    exitcode = active.process.exitcode
                    stop_process(active.process)
                    active.process = None
                    finish_active(factory, active, "failed", "执行进程异常退出" if exitcode else "执行结束但未保存完成状态")
                    active = None
                    next_claim = tick
                elif tick - active.started >= MAX_RUN_SECONDS:
                    stop_process(active.process)
                    active.process = None
                    finish_active(factory, active, "failed", f"任务执行超过 {MAX_RUN_SECONDS} 秒，已终止执行")
                    active = None
                    next_claim = tick
                elif tick - active.renewed >= LEASE_REFRESH_SECONDS:
                    if not service.renew_run(factory, active.claim["run_id"], active.claim["lease_token"]):
                        # A child can commit success just before its process exits.
                        # Stop first, then distinguish completion from lost ownership.
                        stop_process(active.process)
                        active.process = None
                        if not run_is_terminal(factory, active.claim["run_id"]):
                            raise LeaseLost("名单同步执行租约已失效")
                        active = None
                        next_claim = tick
                    else:
                        active.renewed = tick
            if tick >= next_schedule:
                service.schedule_due(factory)
                next_schedule = tick + POLL_SECONDS
            if active is None and tick >= next_cleanup:
                service.cleanup_history(factory)
                next_cleanup = tick + CLEANUP_SECONDS
            if active is None and tick >= next_claim:
                claim = service.claim_run(factory, worker_id)
                next_claim = tick + POLL_SECONDS
                if claim:
                    process = context.Process(target=execute_child,
                        args=(settings.model_dump(), claim["run_id"], claim["lease_token"], os.getpid()), daemon=True)
                    active = ActiveRun(claim, process, tick, tick)
                    # The gate can be lost during scheduling/claim database work.
                    # Never start a fresh child based only on the earlier probe.
                    gate.check()
                    process.start()
            if tick >= next_health:
                health.record(database_ok=True, run_id=active.claim["run_id"] if active else None)
                next_health = tick + POLL_SECONDS
            stopped.wait(1 if active else POLL_SECONDS)
    except BaseException:
        if acquired:
            health.record(database_ok=False)
        raise
    finally:
        safely_stopped = active is None or active.process is None
        try:
            if active:
                if active.process is not None:
                    stop_process(active.process)
                    active.process = None
                safely_stopped = True
                try:
                    finish_active(factory, active, "interrupted", "名单同步服务停止，执行已中断；下次运行重新核对目标")
                except Exception as error:
                    logger.warning("名单同步中断状态暂未保存（%s）", database_error_label(error))
        finally:
            try:
                # If SIGKILL could not stop a child, keep the gate until process
                # exit; PDEATHSIG then binds child death to supervisor death.
                if acquired and safely_stopped:
                    gate.close()
            finally:
                if acquired:
                    health.clear()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    settings.validate_runtime()
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    factory = make_session_factory(settings.database_url)
    try:
        run_loop(factory, settings, stopped, TableSyncHealth())
    except Exception as error:
        logger.error("名单同步服务异常退出（%s），容器将按重启策略恢复", database_error_label(error))
        raise SystemExit(1) from None
    finally:
        factory.kw["bind"].dispose()


if __name__ == "__main__":
    main()
