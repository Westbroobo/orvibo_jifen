from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from . import auth
from .config import get_settings
from .db import get_db, lock_state
from .models import Department, Employee, PermissionAudit, Role
from .permissions import (BUILTINS, DEPENDENCIES, PERMISSIONS, audit, function_permissions,
                          grant_snapshot, owner_notice, require_manager)

router = APIRouter(prefix="/api/admin", tags=["authorization"])


class RoleDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    permissions: list[str] = Field(default_factory=list, max_length=7)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("角色名称不能为空")
        return value.strip()

    @field_validator("permissions")
    @classmethod
    def valid_permissions(cls, value):
        if any(p not in PERMISSIONS for p in value):
            raise ValueError("包含未知功能权限")
        if any(p in value and required not in value for p, required in DEPENDENCIES.items()):
            raise ValueError("撤回、重试需要查看发送记录，导出需要查看积分明细")
        return sorted(set(value))


class GrantRequest(BaseModel):
    role: str = Field(min_length=1, max_length=36)
    history_scope: Literal["own", "all"] = "own"
    ledger_scope: Literal["own", "departments", "all"] = "own"
    ledger_department_ids: list[str] = Field(default_factory=list, max_length=500)


def role_view(db, role):
    return {"id": role.id, "name": role.name, "description": role.description,
            "permissions": list(PERMISSIONS) if role.id == "owner" else role.permissions,
            "builtin": role.id in BUILTINS,
            "employee_count": db.scalar(select(func.count()).select_from(Employee).where(Employee.role == role.id))}


@router.get("/roles")
def roles(user=Depends(auth.admin), db=Depends(get_db)):
    order = {id: index for index, id in enumerate(BUILTINS)}
    rows = sorted(db.scalars(select(Role)), key=lambda r: (order.get(r.id, len(BUILTINS)), r.name))
    return {"items": [role_view(db, r) for r in rows],
            "permissions": [{"id": k, "name": v, "requires": DEPENDENCIES.get(k)} for k, v in PERMISSIONS.items()],
            "owner_notice": owner_notice(db, get_settings()),
            "departments": [{"id": d.id, "name": d.name if d.active else d.name + "（已停用）",
                "parent_id": d.parent_id, "path_ids": d.path_ids, "path_names": d.path_names, "active": d.active}
                for d in db.scalars(select(Department))]}


def save_role(db, actor, body, role=None):
    if role and role.id in {"owner", "none"}:
        raise HTTPException(403, "系统所有者和普通员工的权限定义固定")
    if role and role.id in BUILTINS and body.name != BUILTINS[role.id]:
        raise HTTPException(422, "内置角色名称不可修改")
    if not role and body.name in BUILTINS.values():
        raise HTTPException(409, "不能使用内置角色名称")
    duplicate = db.scalar(select(Role).where(Role.name == body.name))
    if duplicate and (not role or duplicate.id != role.id):
        raise HTTPException(409, "已有同名角色")
    before = role_view(db, role) if role else None
    if not role:
        role = Role(name=body.name, description=body.description, permissions=body.permissions)
        db.add(role)
        db.flush()
    else:
        role.name, role.description, role.permissions = body.name, body.description, body.permissions
    after = role_view(db, role)
    audit(db, actor, role.id, role.name, before, after, event="role")
    db.commit()
    return after


@router.post("/roles", status_code=201)
def create_role(body: RoleDefinition, user=Depends(auth.admin), db=Depends(get_db)):
    lock_state(db)
    return save_role(db, require_manager(db, user.id, owner=True), body)


@router.put("/roles/{role_id}")
def update_role(role_id: str, body: RoleDefinition, user=Depends(auth.admin), db=Depends(get_db)):
    lock_state(db)
    actor = require_manager(db, user.id, owner=True)
    role = db.get(Role, role_id, populate_existing=True)
    if not role:
        raise HTTPException(404, "角色不存在")
    return save_role(db, actor, body, role)


@router.delete("/roles/{role_id}")
def delete_role(role_id: str, user=Depends(auth.admin), db=Depends(get_db)):
    lock_state(db)
    actor = require_manager(db, user.id, owner=True)
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(404, "角色不存在")
    if role.id in BUILTINS:
        raise HTTPException(409, "内置角色不可删除")
    if db.scalar(select(Employee.id).where(Employee.role == role.id).limit(1)):
        raise HTTPException(409, "有员工使用此角色，不能删除")
    audit(db, actor, role.id, role.name, role_view(db, role), None, event="role")
    db.delete(role)
    db.commit()
    return {"ok": True}


@router.get("/people/{person_id}/authorization")
def get_grant(person_id: str, user=Depends(auth.admin), db=Depends(get_db)):
    person = db.get(Employee, person_id)
    if not person:
        raise HTTPException(404, "人员不存在")
    return {"id": person.id, "name": person.name, **grant_snapshot(db, person),
            "permissions": function_permissions(db, person)}


@router.put("/people/{person_id}/authorization")
def update_grant(person_id: str, body: GrantRequest, user=Depends(auth.admin), db=Depends(get_db)):
    lock_state(db)
    actor = require_manager(db, user.id)
    target = db.get(Employee, person_id, populate_existing=True)
    if not target:
        raise HTTPException(404, "人员不存在")
    role = db.get(Role, body.role)
    if not role:
        raise HTTPException(422, "角色不存在，请刷新页面")
    # MySQL ID 比较忽略大小写，始终使用库内规范 ID 执行管理身份检查。
    role_id = role.id
    if actor.role != "owner" and (target.role == "owner" or role_id == "owner"):
        raise HTTPException(403, "管理员不能调整系统所有者")
    if role_id != "none" and target.status != "active":
        raise HTTPException(409, "只可为在职人员授权；不可用人员可取消角色")
    if target.role == "owner" and target.status == "active" and role_id != "owner":
        owners = db.scalar(select(func.count()).select_from(Employee).where(Employee.role == "owner", Employee.status == "active"))
        if owners <= 1:
            raise HTTPException(409, "不能移除最后一名有效系统所有者")
    departments = sorted(set(body.ledger_department_ids)) if body.ledger_scope == "departments" else []
    if body.ledger_scope == "departments":
        if not departments:
            raise HTTPException(422, "至少选择一个积分明细授权部门")
        # 已停用或删除的历史授权允许原样保留，新选择必须存在且有效。
        retained = set(target.ledger_department_ids or [])
        for dept_id in departments:
            dept = db.get(Department, dept_id)
            if dept_id not in retained and (not dept or not dept.active):
                raise HTTPException(422, "新授权部门不存在或已停用，请重新选择")
    before = grant_snapshot(db, target)
    target.role, target.history_scope, target.ledger_scope = role_id, body.history_scope, body.ledger_scope
    target.ledger_department_ids = departments
    after = grant_snapshot(db, target)
    if before != after:
        audit(db, actor, target.id, target.name, before, after, employee_id=target.id)
    db.commit()
    return {"ok": True}


@router.get("/permission-audits")
def audits(page: int = Query(1, ge=1), user=Depends(auth.admin), db=Depends(get_db)):
    total = db.scalar(select(func.count()).select_from(PermissionAudit))
    items = []
    for row in db.scalars(select(PermissionAudit).order_by(PermissionAudit.created_at.desc(), PermissionAudit.id).offset((page - 1) * 20).limit(20)):
        employee = db.get(Employee, row.employee_id) if row.employee_id else None
        actor = db.get(Employee, row.actor_id) if row.actor_id else None
        legacy = row.before is None and row.after is None
        items.append({"id": row.id, "event": row.event, "target_id": row.target_id or row.employee_id,
            "target_name": row.target_name or (employee.name if employee else "历史对象"),
            "actor_name": row.actor_name or (actor.name if actor else "系统初始化"),
            "before": {"role": row.old_role} if legacy else row.before,
            "after": {"role": row.new_role} if legacy else row.after,
            "created_at": row.created_at.isoformat() + "Z"})
    return {"items": items, "total": total, "page": page}
