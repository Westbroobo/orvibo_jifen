from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from . import auth
from .permissions import require_system_access, is_manager
from .db import get_db, lock_state, now_utc
from .models import Preset
from .schemas import PresetRequest, Selection

router = APIRouter(prefix="/api/presets")


def preset_view(preset, user):
    return {"id": preset.id, "name": preset.name, "scope": preset.scope,
            "selection": Selection.model_validate(preset.selection).model_dump(),
            "can_edit": is_manager(user) if preset.scope == "public" else preset.owner_id == user.id}


@router.get("")
def presets(user=Depends(auth.system_user), db=Depends(get_db)):
    statement = select(Preset).where(or_(Preset.scope == "public",
        (Preset.scope == "personal") & (Preset.owner_id == user.id))).order_by(Preset.updated_at.desc(), Preset.id)
    return [preset_view(p, user) for p in db.scalars(statement)]


def writable_preset(db, user, preset_id):
    preset = db.get(Preset, preset_id)
    if not preset or preset.scope == "personal" and preset.owner_id != user.id:
        raise HTTPException(404, "名单不存在")
    if preset.scope == "public" and not is_manager(user):
        raise HTTPException(403, "仅管理员可维护公共名单")
    return preset


def save_preset(db, user, body, preset=None):
    if body.scope == "public" and not is_manager(user):
        raise HTTPException(403, "仅管理员可维护公共名单")
    if preset and body.scope != preset.scope:
        raise HTTPException(422, "已保存名单的可见范围不可修改，请新建名单")
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "名单名称不能为空")
    duplicates = select(Preset.id).where(Preset.scope == body.scope, Preset.name == name)
    if body.scope == "personal":
        duplicates = duplicates.where(Preset.owner_id == user.id)
    if preset:
        duplicates = duplicates.where(Preset.id != preset.id)
    # All preset and role writes share the system-state transaction lock.
    # Public names are checked across creators; personal names per owner.
    if db.scalar(duplicates):
        raise HTTPException(409, "已有同名公共名单" if body.scope == "public" else "已有同名个人名单")
    if preset is None:
        preset = Preset(owner_id=user.id, scope=body.scope, name=name, selection=body.selection.model_dump())
        db.add(preset)
    else:
        preset.name, preset.selection, preset.updated_at = name, body.selection.model_dump(), now_utc()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "已有同名名单") from exc
    return preset_view(preset, user)


@router.post("", status_code=201)
def new_preset(body: PresetRequest, user=Depends(auth.system_user), db=Depends(get_db)):
    lock_state(db)
    user = require_system_access(db, user.id)
    return save_preset(db, user, body)


@router.put("/{preset_id}")
def update_preset(preset_id: str, body: PresetRequest, user=Depends(auth.system_user), db=Depends(get_db)):
    lock_state(db)
    user = require_system_access(db, user.id)
    return save_preset(db, user, body, writable_preset(db, user, preset_id))


@router.delete("/{preset_id}")
def delete_preset(preset_id: str, user=Depends(auth.system_user), db=Depends(get_db)):
    lock_state(db)
    user = require_system_access(db, user.id)
    db.delete(writable_preset(db, user, preset_id))
    db.commit()
    return {"ok": True}
