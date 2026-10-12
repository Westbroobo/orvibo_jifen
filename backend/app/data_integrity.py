"""应用层关联校验；仅允许状态变更，保留人员和业务历史。"""

from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import inspect, select

from .db import lock_state
from .models import (Balance, Batch, Delivery, Department, Employee, Ledger,
                     LedgerCancellation, Membership, MessageRecall, PermissionAudit,
                     Preset, Preview, Session, SystemState)


# 关联字段使用普通索引/主键查询。预览可过期清理，批次保存完整快照。
REFERENCES = {
    Membership: {"employee_id": Employee, "department_id": Department},
    Preset: {"owner_id": Employee},
    Balance: {"employee_id": Employee},
    Preview: {"owner_id": Employee, "batch_id": Batch},
    Batch: {"operator_id": Employee},
    Ledger: {"batch_id": Batch, "employee_id": Employee},
    Delivery: {"ledger_id": Ledger, "recipient_id": Employee},
    LedgerCancellation: {"ledger_id": Ledger, "actor_id": Employee},
    MessageRecall: {"delivery_id": Delivery, "actor_id": Employee},
    Session: {"employee_id": Employee},
    PermissionAudit: {"actor_id": Employee, "employee_id": Employee},
}
RETAINED = {Employee, Department, Balance, Batch, Ledger, Delivery,
            LedgerCancellation, MessageRecall, PermissionAudit}
PARENT_LABELS = {Employee: "员工", Department: "部门", Batch: "操作批次",
                 Ledger: "积分流水", Delivery: "消息记录"}


def validate_changes(db):
    for row in db.deleted:
        if type(row) in RETAINED:
            raise HTTPException(409, "人员、部门和业务历史不可删除，请使用状态变更或撤回")
    required = defaultdict(set)
    for row in set(db.new) | set(db.dirty):
        state = inspect(row)
        if state.persistent and any(state.attrs[column.key].history.has_changes()
                                    for column in state.mapper.primary_key):
            raise HTTPException(409, "已保存记录的 ID 不可修改")
        for field, parent in REFERENCES.get(type(row), {}).items():
            if row in db.new or state.attrs[field].history.has_changes():
                value = getattr(row, field)
                if value is not None:
                    required[parent].add(value)
    if not required:
        return
    # 和记账、同步、授权共用事务锁，校验至提交期间不允许并发改动关联。
    if not any(isinstance(row, SystemState) and row.id == 1 for row in db.new):
        if lock_state(db) is None:
            raise HTTPException(503, "数据库尚未初始化，请手动执行 database/schema.sql")
    for parent, ids in required.items():
        pending = {row.id for row in db.new if isinstance(row, parent) and row.id is not None}
        missing = sorted(ids - pending)
        for start in range(0, len(missing), 500):
            chunk = missing[start:start + 500]
            found = set(db.scalars(select(parent.id).where(parent.id.in_(chunk))))
            if set(chunk) - found:
                raise HTTPException(409, f"关联{PARENT_LABELS[parent]}不存在，请刷新页面并核实记录")


def guard_bulk_write(execution):
    if not (execution.is_delete or execution.is_update or execution.is_insert):
        return
    table = getattr(execution.statement, "table", None)
    table_name = getattr(table, "name", None)
    if execution.is_delete:
        if table_name in {model.__tablename__ for model in RETAINED}:
            raise HTTPException(409, "人员、部门和业务历史不可删除，请使用状态变更或撤回")
    elif table_name in {model.__tablename__ for model in REFERENCES} | {Employee.__tablename__, Department.__tablename__}:
        raise HTTPException(409, "关联记录须逐条通过业务会话保存，不能绕过关联校验批量写入")
