"""Short database transactions and the isolated sync execution pipeline.

None of these tables participate in SystemState's business-wide writer lock.
The standalone worker owns scheduling/execution; API requests only enqueue.
"""

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import delete, select

from ..db import database_error_label, new_id, now_utc
from ..feishu import FeishuError
from ..models import TableSyncLog, TableSyncRun, TableSyncTask
from .core import SourceError, check_source, diff_rows, read_source
from .remote import BitableClient
from .schedule import next_times

LEASE_SECONDS = 90
TERMINAL = {"success", "unchanged", "failed", "interrupted"}
CONFIG_FIELDS = ("name", "source_kind", "preset_id", "selection", "base_token", "table_id",
                 "table_name", "target_url", "field_mapping", "cron", "config_version")


def task_config(task):
    return {key: getattr(task, key) for key in CONFIG_FIELDS}


def task_locked(db, task_id):
    task = db.scalar(select(TableSyncTask).where(TableSyncTask.id == task_id).with_for_update())
    if not task or task.deleted:
        raise HTTPException(404, "同步任务不存在")
    return task


def enqueue(db, task, *, kind="sync", trigger="manual", actor_id=None, actor_name=None, scheduled_at=None):
    if task.active_run_id:
        raise HTTPException(409, "该任务已在排队或运行，请等待完成")
    run = TableSyncRun(id=new_id(), task_id=task.id, task_name=task.name, kind=kind, trigger=trigger,
                       status="queued", config=task_config(task), actor_id=actor_id, actor_name=actor_name,
                       scheduled_at=scheduled_at)
    db.add(run)
    task.active_run_id = run.id
    db.add(TableSyncLog(run_id=run.id, stage="queued", message="只读预览已入队" if kind == "preview" else "同步任务已入队"))
    return run


def schedule_due(factory, when=None):
    when = when or now_utc()
    enqueued = 0
    with factory.begin() as db:
        tasks = list(db.scalars(select(TableSyncTask).where(
            TableSyncTask.deleted.is_(False), TableSyncTask.enabled.is_(True),
            TableSyncTask.next_run_at <= when).order_by(TableSyncTask.next_run_at, TableSyncTask.id)
            .limit(100).with_for_update(skip_locked=True)))
        for task in tasks:
            scheduled_at = task.next_run_at
            task.next_run_at = next_times(task.cron, when, 1)[0]
            if task.active_run_id:
                db.add(TableSyncLog(run_id=task.active_run_id, stage="schedule", message="到点已有排队或运行记录，跳过本次定时触发",
                                    details={"scheduled_at": scheduled_at.isoformat() + "Z"}))
                continue
            enqueue(db, task, trigger="scheduled", scheduled_at=scheduled_at)
            enqueued += 1
    return enqueued


def claim_run(factory, worker_id, when=None):
    when = when or now_utc()
    # Single worker is enforced by its advisory lock. The CAS remains defensive.
    with factory() as db:
        candidates = list(db.scalars(select(TableSyncRun.id).where(TableSyncRun.status == "queued")
                                    .order_by(TableSyncRun.created_at, TableSyncRun.id).limit(100)))
    for run_id in candidates:
        with factory.begin() as db:
            task_id = db.scalar(select(TableSyncRun.task_id).where(TableSyncRun.id == run_id))
            task = db.scalar(select(TableSyncTask).where(TableSyncTask.id == task_id).with_for_update())
            run = db.scalar(select(TableSyncRun).where(TableSyncRun.id == run_id).with_for_update())
            if not task or task.deleted or not run or run.status != "queued" or task.active_run_id != run.id:
                continue
            token = new_id()
            run.status, run.started_at, run.progress_at = "running", when, when
            run.lease_token, run.lease_until, run.worker_id = token, when + timedelta(seconds=LEASE_SECONDS), worker_id
            db.add(TableSyncLog(run_id=run.id, stage="started", message="开始只读预览" if run.kind == "preview" else "开始核对同步数据"))
            return {"run_id": run.id, "task_id": task.id, "lease_token": token}
    return None


def renew_run(factory, run_id, lease_token, when=None):
    when = when or now_utc()
    with factory.begin() as db:
        run = db.scalar(select(TableSyncRun).where(TableSyncRun.id == run_id).with_for_update())
        if not run or run.status != "running" or run.lease_token != lease_token:
            return False
        run.progress_at, run.lease_until = when, when + timedelta(seconds=LEASE_SECONDS)
    return True


def finish_run(factory, run_id, lease_token, status, error=None, summary=None):
    if status not in TERMINAL:
        raise ValueError("Invalid terminal sync status")
    with factory.begin() as db:
        task_id = db.scalar(select(TableSyncRun.task_id).where(TableSyncRun.id == run_id))
        task = db.scalar(select(TableSyncTask).where(TableSyncTask.id == task_id).with_for_update())
        run = db.scalar(select(TableSyncRun).where(TableSyncRun.id == run_id).with_for_update())
        if not run or run.status != "running" or run.lease_token != lease_token:
            return False
        run.status, run.finished_at, run.error = status, now_utc(), error
        run.lease_until = None
        if summary is not None:
            run.summary = summary
        if task and task.active_run_id == run.id:
            task.active_run_id = None
            task.last_status, task.last_summary, task.last_run_at = status, run.summary, run.finished_at
        message = error or ("核对完成，无变化" if status == "unchanged" else "只读预览完成" if run.kind == "preview" else "同步完成，最终核验一致")
        db.add(TableSyncLog(run_id=run.id, level="error" if status in {"failed", "interrupted"} else "info",
                            stage=status, message=message[:2000], details=run.summary))
    return True


def recover_interrupted(factory):
    """Called only after acquiring worker singleton lock; old child must be dead."""
    with factory() as db:
        runs = list(db.execute(select(TableSyncRun.id, TableSyncRun.lease_token).where(TableSyncRun.status == "running")))
    count = 0
    for run_id, token in runs:
        count += bool(finish_run(factory, run_id, token, "interrupted", "独立执行服务重启，本次已中断；下次执行将重新核对目标数据"))
    return count


def _owned(db, run_id, token):
    run = db.get(TableSyncRun, run_id, populate_existing=True)
    if not run or run.status != "running" or run.lease_token != token or not run.lease_until or run.lease_until <= now_utc():
        raise SourceError("本次执行归属已失效，停止继续写入")
    return run


def _record(factory, run_id, token, stage, message, log_details=None, **values):
    with factory.begin() as db:
        run = _owned(db, run_id, token)
        for key, value in values.items():
            setattr(run, key, value)
        db.add(TableSyncLog(run_id=run_id, stage=stage, message=message, details=log_details))


def execute_run(factory, run_id, lease_token, settings, client=None):
    """Executed in a supervised child. No Session survives an external call."""
    owned_client = client is None
    summary = None
    try:
        with factory() as db:
            run = _owned(db, run_id, lease_token)
            config, kind = run.config, run.kind
            source = read_source(db, config)
        _record(factory, run_id, lease_token, "source", f"来源校验完成，共 {len(source['rows'])} 人", source_snapshot=source)
        if client is None:
            client = BitableClient(settings, interval=1)
        base, table, mapping = config["base_token"], config["table_id"], config["field_mapping"]
        client.validate_mapping(base, table, mapping)
        remote = client.read_rows(base, table, mapping)
        plan = diff_rows(source["rows"], remote)
        summary = dict(plan["summary"])
        summary.update(completed_create=0, completed_update=0, completed_delete=0)
        _record(factory, run_id, lease_token, "compared", "已完整读取目标并计算差异", summary,
                summary=summary, details=plan)
        if kind == "preview":
            finish_run(factory, run_id, lease_token, "success", summary=summary)
            return
        with factory() as db:
            _owned(db, run_id, lease_token)
            check_source(db, source, config)
        for action in ("create", "update", "delete"):
            rows = plan[action]
            for start in range(0, len(rows), 200):
                with factory() as db:
                    _owned(db, run_id, lease_token)
                    if action == "delete":
                        # Recheck before every destructive batch, not only the first.
                        check_source(db, source, config)
                if action == "delete":
                    client.validate_mapping(base, table, mapping)
                batch = rows[start:start + 200]
                if action == "delete":
                    confirmed = client.delete_rows(base, table, batch)
                else:
                    confirmed = getattr(client, action + "_rows")(base, table, mapping, batch)
                if confirmed != len(batch):
                    raise SourceError("飞书批次返回不完整，部分结果可能已写入；停止后续清理，下次重新核对")
                summary = {**summary, "completed_" + action: summary["completed_" + action] + confirmed}
                _record(factory, run_id, lease_token, action, f"本批已确认 {confirmed} 条", summary, summary=summary)
        changed = any(plan[action] for action in ("create", "update", "delete"))
        if changed:
            remote = client.read_rows(base, table, mapping)
            verified = diff_rows(source["rows"], remote)
            if any(verified[action] for action in ("create", "update", "delete")):
                raise SourceError("写入后核验仍有差异，本次未完成；下次执行将重新核对")
        with factory() as db:
            _owned(db, run_id, lease_token)
            check_source(db, source, config)
        finish_run(factory, run_id, lease_token, "success" if changed else "unchanged", summary=summary)
    except Exception as error:
        if isinstance(error, (ValueError, FeishuError)):
            detail = str(error)
            if isinstance(error, FeishuError) and error.uncertain:
                detail += "；部分结果可能已写入，已停止后续删除，下次执行重新核对"
        else:
            detail = "执行异常（" + database_error_label(error) + "），已停止；请查看独立服务日志或重试"
        if isinstance(error, FeishuError):
            try:
                _record(factory, run_id, lease_token, "upstream_error", detail[:2000],
                        {"code": error.code, "request_log_id": getattr(client, "last_log_id", None),
                         "uncertain": error.uncertain})
            except SourceError:
                pass  # Lost ownership must not append more progress records.
        finish_run(factory, run_id, lease_token, "failed", detail[:2000], summary)
    finally:
        if owned_client and client is not None:
            client.close()


def cleanup_history(factory, when=None):
    """Bounded retention work; never scans or deletes any original business table."""
    cutoff = (when or now_utc()) - timedelta(days=90)
    with factory.begin() as db:
        ids = list(db.scalars(select(TableSyncRun.id).where(TableSyncRun.finished_at < cutoff,
                    TableSyncRun.status.in_(TERMINAL)).order_by(TableSyncRun.finished_at).limit(100)))
        if not ids:
            return 0
        # Small chunks also bound log deletion for high-frequency cron schedules.
        log_ids = list(db.scalars(select(TableSyncLog.id).where(TableSyncLog.run_id.in_(ids)).limit(500)))
        if log_ids:
            db.execute(delete(TableSyncLog).where(TableSyncLog.id.in_(log_ids)))
        pending = set(db.scalars(select(TableSyncLog.run_id).where(TableSyncLog.run_id.in_(ids)).distinct()))
        removable = set(ids) - pending
        if removable:
            db.execute(delete(TableSyncRun).where(TableSyncRun.id.in_(removable)))
        return len(removable)
