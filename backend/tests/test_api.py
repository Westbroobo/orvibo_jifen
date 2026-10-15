from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth
from app.db import get_db, now_utc
from app.feishu import FeishuClient
from app.main import app
from app.models import Employee, LoginState, Preset, Session, SystemState


@pytest.fixture
def client(factory):
    def database():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def login(client, factory, employee_id="admin"):
    token = "test-token-" + employee_id
    with factory.begin() as db:
        db.add(Session(id=auth.digest(token), employee_id=employee_id, csrf_token="csrf-" + employee_id,
                       expires_at=now_utc() + timedelta(hours=1)))
    client.cookies.set("jifen_session", token)
    return {"X-CSRF-Token": "csrf-" + employee_id}


def test_csrf_permissions_and_retired_role_endpoint(client, factory):
    assert client.get("/api/directory").status_code == 401
    headers = login(client, factory)
    assert client.get("/api/directory").status_code == 200
    assert client.put("/api/admin/people/a/role", json={"role": "operator"}).status_code == 403
    assert client.put("/api/admin/people/admin/role", json={"role": "none"}, headers=headers).status_code == 410
    assert client.put("/api/admin/people/a/authorization", json={"role": "operator"}, headers=headers).status_code == 200
    with factory.begin() as db:
        db.get(Employee, "admin").role = "none"
    assert client.get("/api/directory").status_code == 403
    assert client.get("/api/balances").status_code == 403
    assert client.get("/api/auth/me").json()["role"] == "none"


def test_presets_are_owner_only_and_inaccessible_history(client, factory):
    headers = login(client, factory)
    response = client.post("/api/presets", json={"name": "周知", "selection": {"person_ids": ["a"]}}, headers=headers)
    assert response.status_code == 201
    preset_id = response.json()["id"]
    headers = login(client, factory, "operator")
    assert client.get("/api/presets").json() == []
    assert client.put(f"/api/presets/{preset_id}", json={"name": "更改", "selection": {}}, headers=headers).status_code == 404
    assert client.delete(f"/api/presets/{preset_id}", headers=headers).status_code == 404


def test_oauth_state_once_and_tenant_enforced(client, factory, monkeypatch):
    monkeypatch.setattr(auth.settings, "feishu_tenant_key", "our-tenant")
    monkeypatch.setattr(FeishuClient, "oauth_user", lambda *args: {"open_id": "ou_a", "name": "张三", "tenant_key": "other-tenant"})
    state = "state"
    with factory.begin() as db:
        db.add(LoginState(id=auth.digest(state), verifier="verifier", expires_at=now_utc() + timedelta(minutes=5)))
    client.cookies.set("jifen_oauth", state)
    assert client.get("/api/auth/callback?state=wrong&code=test").status_code == 400
    assert client.get("/api/auth/callback?state=state&code=test").status_code == 403
    assert client.get("/api/auth/callback?state=state&code=test").status_code == 400


def test_oauth_login_does_not_grant_role(client, factory, monkeypatch):
    monkeypatch.setattr(auth.settings, "feishu_tenant_key", "our-tenant")
    monkeypatch.setattr(FeishuClient, "oauth_user", lambda *args: {"open_id": "ou_a", "name": "张三", "tenant_key": "our-tenant"})
    with factory.begin() as db:
        db.add(LoginState(id=auth.digest("state"), verifier="verifier", expires_at=now_utc() + timedelta(minutes=5)))
    client.cookies.set("jifen_oauth", "state")
    response = client.get("/api/auth/callback?state=state&code=test", follow_redirects=False)
    assert response.status_code == 303
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "token=" not in response.headers["location"]
    assert client.get("/api/auth/me").json()["role"] == "none"
    assert not client.get("/api/auth/me").json()["can_access_system"]
    assert client.get("/api/directory").status_code == 403
    assert client.get("/api/adjustments").status_code == 403


def test_sync_schedule_admin_only_and_csrf(client, factory):
    endpoint = "/api/admin/directory/schedule"
    body = {"enabled": True, "interval_days": 7, "time": "03:30"}
    assert client.get(endpoint).status_code == 401
    headers = login(client, factory, "operator")
    assert client.get(endpoint).status_code == 403
    assert client.put(endpoint, json=body, headers=headers).status_code == 403
    headers = login(client, factory)
    assert client.put(endpoint, json=body).status_code == 403
    assert client.put(endpoint, json=body, headers=headers | {"Origin": "https://untrusted.example"}).status_code == 403
    response = client.put(endpoint, json=body, headers=headers)
    assert response.status_code == 200
    assert response.json()["interval_days"] == 7
    assert response.json()["time"] == "03:30"
    assert response.json()["next_sync_at"]
    # Re-saving identical settings must not shift an existing plan.
    assert client.put(endpoint, json=body, headers=headers).json()["next_sync_at"] == response.json()["next_sync_at"]
    with factory.begin() as db:
        db.get(Employee, "admin").role = "none"
    assert client.get(endpoint).status_code == 403
    assert client.put(endpoint, json=body, headers=headers).status_code == 403


def test_disable_schedule_preserves_manual_sync_and_clears_retry(client, factory):
    headers = login(client, factory)
    with factory.begin() as db:
        state = db.get(SystemState, 1)
        state.sync_requested = False
        state.last_sync_at = now_utc()
        state.sync_retry_at = now_utc() + timedelta(minutes=5)
    response = client.put("/api/admin/directory/schedule", json={"enabled": False, "interval_days": 1, "time": "02:00"}, headers=headers)
    assert response.status_code == 200 and response.json()["next_sync_at"] is None
    assert client.post("/api/admin/directory/sync", headers=headers).status_code == 200
    state = client.get("/api/admin/directory/schedule").json()
    assert state["sync_requested"] and state["retry_at"] is None
    assert not state["enabled"] and state["next_sync_at"] is None


@pytest.mark.parametrize("field,value", [("interval_days", 0), ("interval_days", 366), ("time", "25:00"), ("time", "00:60")])
def test_sync_schedule_invalid_values_do_not_change_saved_settings(client, factory, field, value):
    headers = login(client, factory)
    endpoint = "/api/admin/directory/schedule"
    previous = client.get(endpoint).json()
    body = {"enabled": True, "interval_days": 1, "time": "02:00", field: value}
    assert client.put(endpoint, json=body, headers=headers).status_code == 422
    assert client.get(endpoint).json() == previous
