"""统一功能权限、管理身份和记录可见范围；写操作在系统事务锁内复核。"""
from fastapi import HTTPException
from sqlalchemy import func, select

from .models import Employee, PermissionAudit, Role, SystemState

PERMISSIONS = {
    "adjustments.write": "积分操作",
    "history.read": "查看发送记录",
    "history.recall": "整批撤回",
    "history.retry": "重试通知",
    "history.others": "操作他人记录",
    "ledgers.read": "查看积分明细",
    "ledgers.export": "导出积分明细",
}
DEPENDENCIES = {"history.recall": "history.read", "history.retry": "history.read", "ledgers.export": "ledgers.read"}
BUILTINS = {"owner": "系统所有者", "admin": "管理员", "operator": "操作员", "none": "普通员工"}


def require_active(db, user_id):
    user = db.get(Employee, user_id, populate_existing=True)
    if not user or user.status != "active":
        raise HTTPException(403, "人员状态不可用，请联系管理员同步通讯录")
    return user


def function_permissions(db, user):
    if user.status != "active":
        return []
    if user.role == "owner":
        return list(PERMISSIONS)
    role = db.get(Role, user.role, populate_existing=True)
    return [p for p in (role.permissions if role else []) if p in PERMISSIONS]


def has_permission(db, user, permission):
    granted = function_permissions(db, user)
    return permission in granted and (permission not in DEPENDENCIES or DEPENDENCIES[permission] in granted)


def require_permission(db, user_id, permission):
    user = require_active(db, user_id)
    if not has_permission(db, user, permission):
        raise HTTPException(403, f"当前账号没有“{PERMISSIONS[permission]}”权限，请刷新页面")
    return user


def is_manager(user):
    return user.status == "active" and user.role in {"owner", "admin"}


def can_access_system(db, user):
    return is_manager(user) or bool(set(function_permissions(db, user)) & {
        "adjustments.write", "history.read", "ledgers.read"})


def require_system_access(db, user_id):
    user = require_active(db, user_id)
    if not can_access_system(db, user):
        raise HTTPException(403, "当前账号暂无系统使用权限，请联系数据支持组开通相关权限")
    return user


def require_manager(db, user_id, *, owner=False):
    user = require_active(db, user_id)
    if not is_manager(user) or owner and user.role != "owner":
        raise HTTPException(403, "仅系统所有者可操作" if owner else "仅管理员或系统所有者可操作")
    return user


def history_visible(user, batch):
    return user.role == "owner" or user.history_scope == "all" or batch.operator_id == user.id


def can_operate_batch(db, user, batch, permission):
    granted = set(function_permissions(db, user))
    return (history_visible(user, batch) and "history.read" in granted and permission in granted
            and (batch.operator_id == user.id or "history.others" in granted))


def require_batch_operation(db, user_id, batch, permission):
    user = require_permission(db, user_id, permission)
    if not batch or not history_visible(user, batch):
        raise HTTPException(404, "操作记录不存在")
    if not can_operate_batch(db, user, batch, permission):
        raise HTTPException(403, "当前账号不能操作他人记录")
    return user


def grant_snapshot(db, user):
    role = db.get(Role, user.role)
    return {"role": user.role, "role_name": role.name if role else user.role,
            "history_scope": user.history_scope, "ledger_scope": user.ledger_scope,
            "ledger_department_ids": user.ledger_department_ids or []}


def audit(db, actor, target_id, target_name, before, after, *, event="employee", employee_id=None):
    db.add(PermissionAudit(actor_id=actor.id if actor else None, actor_name=actor.name if actor else None,
        employee_id=employee_id, event=event, target_id=target_id, target_name=target_name,
        old_role=before.get("role") if before else None, new_role=after.get("role") if after else None,
        before=before, after=after))


def bootstrap_owners(db, settings, state=None):
    # 调用者持有 lock_state；单独记录每个账号，部分匹配也不会反复恢复已取消的授权。
    state = state or db.get(SystemState, 1)
    if state.owner_bootstrap_done or not settings.bootstrap_admins:
        return
    handled = set(state.owner_bootstrap_ids or [])
    for user_id in settings.bootstrap_admins:
        if user_id in handled:
            continue
        user = db.scalar(select(Employee).where(Employee.user_id == user_id, Employee.status == "active"))
        if user:
            before = grant_snapshot(db, user)
            user.role = "owner"
            audit(db, None, user.id, user.name, before, grant_snapshot(db, user), event="owner_init", employee_id=user.id)
            handled.add(user_id)
    state.owner_bootstrap_ids = sorted(handled)
    state.owner_bootstrap_done = set(settings.bootstrap_admins).issubset(handled)


def owner_notice(db, settings):
    if db.scalar(select(func.count()).select_from(Employee).where(Employee.role == "owner", Employee.status == "active")):
        return ""
    if not settings.bootstrap_admins:
        return "尚无有效系统所有者，请配置 INITIAL_ADMIN_USER_IDS 后同步人员。"
    state = db.get(SystemState, 1)
    if not state.owner_bootstrap_done:
        return "初始所有者尚未匹配到在职员工，请核对 INITIAL_ADMIN_USER_IDS 并同步人员。"
    return "系统所有者当前均不可用，请核实人员状态并同步通讯录。"


def user_capabilities(db, user):
    role = db.get(Role, user.role)
    return {**grant_snapshot(db, user), "role_name": role.name if role else "角色已失效",
            "permissions": function_permissions(db, user), "can_manage": is_manager(user),
            "can_access_system": can_access_system(db, user),
            "can_configure_roles": user.status == "active" and user.role == "owner"}
