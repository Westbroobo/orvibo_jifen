import base64
import hashlib
import hmac
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy import delete, select

from .config import get_settings
from .db import get_db, lock_state, now_utc
from .feishu import FeishuClient, FeishuError
from .models import Employee, LoginState, Session, SystemState
from .permissions import require_active, require_system_access, require_permission, require_manager, user_capabilities, bootstrap_owners, owner_notice

router = APIRouter(prefix="/api/auth")
settings = get_settings()


def digest(value):
    return hmac.new(settings.session_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def current_user(request: Request, db=Depends(get_db)):
    token = request.cookies.get("jifen_session")
    session = db.get(Session, digest(token)) if token else None
    if not session or session.expires_at <= now_utc():
        raise HTTPException(401, "请先登录")
    user = db.get(Employee, session.employee_id)
    if not user or user.status in {"resigned", "inactive"}:
        raise HTTPException(403, "人员状态不可用")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf = request.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(csrf, session.csrf_token):
            raise HTTPException(403, "请求校验失败，请刷新页面")
        origin = request.headers.get("Origin")
        if origin and origin != settings.public_url.rstrip("/"):
            raise HTTPException(403, "请求来源无效")
    request.state.session = session
    return user


def active(user=Depends(current_user), db=Depends(get_db)):
    return require_active(db, user.id)


def system_user(user=Depends(current_user), db=Depends(get_db)):
    return require_system_access(db, user.id)


def permission(name):
    def check(user=Depends(current_user), db=Depends(get_db)):
        return require_permission(db, user.id, name)
    return check


operator = permission("adjustments.write")


def admin(user=Depends(current_user), db=Depends(get_db)):
    return require_manager(db, user.id)


def session_response(db, user, response=None):
    token = secrets.token_urlsafe(32)
    session = Session(id=digest(token), employee_id=user.id, csrf_token=secrets.token_urlsafe(32),
                      expires_at=now_utc() + timedelta(hours=settings.session_hours))
    db.add(session)
    db.commit()
    response = response or RedirectResponse(settings.public_url, status_code=303)
    response.set_cookie("jifen_session", token, httponly=True, secure=settings.cookie_secure,
                        samesite="lax", max_age=settings.session_hours * 3600, path="/")
    response.delete_cookie("jifen_oauth", path="/api/auth")
    return response


@router.get("/login")
def login(db=Depends(get_db)):
    if not settings.feishu_app_id or not settings.feishu_tenant_key:
        raise HTTPException(503, "请先配置飞书应用 ID 和企业标识")
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    db.add(LoginState(id=digest(state), verifier=verifier, expires_at=now_utc() + timedelta(minutes=5)))
    db.commit()
    params = {"client_id": settings.feishu_app_id, "response_type": "code", "redirect_uri": settings.feishu_redirect_uri,
              "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
    response = RedirectResponse("https://accounts.feishu.cn/open-apis/authen/v1/authorize?" + urlencode(params))
    response.set_cookie("jifen_oauth", state, httponly=True, secure=settings.cookie_secure,
                        samesite="lax", max_age=300, path="/api/auth")
    return response


@router.get("/callback")
def callback(request: Request, state: str = "", code: str = "", error: str = "", db=Depends(get_db)):
    cookie = request.cookies.get("jifen_oauth", "")
    if not state or not cookie or not hmac.compare_digest(state, cookie):
        raise HTTPException(400, "授权状态校验失败，请重新登录")
    lock_state(db)
    record = db.get(LoginState, digest(state))
    if not record or record.expires_at <= now_utc():
        raise HTTPException(400, "授权已过期或已使用，请重新登录")
    verifier = record.verifier
    db.delete(record)
    db.commit()  # Consume once before any upstream request.
    if error or not code:
        return RedirectResponse(settings.public_url + "?login_error=denied", status_code=303)
    client = FeishuClient(settings)
    try:
        profile = client.oauth_user(code, verifier)
        if profile.get("tenant_key") != settings.feishu_tenant_key:
            raise HTTPException(403, "仅允许本企业员工登录")
    except FeishuError as exc:
        raise HTTPException(502, str(exc)) from exc
    finally:
        client.close()
    lock_state(db)
    user = db.scalar(select(Employee).where(Employee.open_id == profile["open_id"]))
    if not user:
        user = Employee(open_id=profile["open_id"], name=profile["name"], status="unknown", role="none")
        db.add(user)
        db.flush()
    # Login does not grant directory status or authorization.
    if user.status in {"resigned", "inactive"}:
        raise HTTPException(403, "人员状态不可用")
    return session_response(db, user)


@router.get("/me")
def me(request: Request, user=Depends(current_user), db=Depends(get_db)):
    state = db.get(SystemState, 1)
    if state and not state.owner_bootstrap_done and settings.bootstrap_admins:
        state = lock_state(db)
        db.refresh(state)
        bootstrap_owners(db, settings, state)
        db.commit()
        db.refresh(user)
    return {"id": user.id, "name": user.name, "role": user.role, "status": user.status,
            "avatar_url": user.avatar_url, "csrf_token": request.state.session.csrf_token,
            "demo_mode": settings.demo_mode, **user_capabilities(db, user),
            "owner_notice": owner_notice(db, settings) if user.role in {"owner", "admin"} else ""}


@router.post("/logout")
def logout(request: Request, user=Depends(current_user), db=Depends(get_db)):
    db.delete(request.state.session)
    db.commit()
    response = JSONResponse({"ok": True})
    response.delete_cookie("jifen_session", path="/")
    return response


@router.post("/demo")
def demo_login(request: Request, db=Depends(get_db)):
    if not settings.demo_mode or settings.app_env != "development":
        raise HTTPException(404, "不存在")
    # Explicitly local-only: forwarded headers are not trusted here.
    if request.client and request.client.host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(403, "演示登录仅限本机")
    user = db.scalar(select(Employee).where(Employee.open_id == "demo_admin"))
    if not user:
        raise HTTPException(503, "演示人员尚未配置")
    return session_response(db, user, JSONResponse({"ok": True}))
