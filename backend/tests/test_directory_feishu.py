import json

import httpx
import pytest
from sqlalchemy import select

from app.directory import apply_contact_event, apply_directory, resolve_selection
from app.feishu import FeishuClient, FeishuError
from app.models import Employee, EventReceipt, PermissionAudit, SystemState
from app.schemas import Selection


def test_directory_missing_is_unknown_and_events_survive_sync(factory, settings):
    with factory.begin() as db:
        apply_directory(db, [], [{"open_id": "ou_a", "name": "张三", "status": {"is_resigned": False}}], settings)
    with factory() as db:
        assert db.get(Employee, "b").status == "unknown"
        assert db.get(Employee, "gone").status == "resigned"
        before = db.get(SystemState, 1).directory_version
    with factory.begin() as db:
        apply_contact_event(db, "event1", "contact.user.deleted_v3", {"object": {"open_id": "ou_a"}})
        apply_contact_event(db, "event1", "contact.user.deleted_v3", {"object": {"open_id": "ou_a"}})
    with factory.begin() as db:
        assert not apply_directory(db, [], [{"open_id": "ou_a", "name": "张三", "status": {"is_resigned": False}}], settings, expected_version=before)
        assert db.get(Employee, "a").status == "resigned"


def test_preset_dynamic_membership(factory, settings):
    selection = Selection(mode="all", levels=[["rd"], [], []])
    with factory() as db:
        assert {p["id"] for p in resolve_selection(db, selection)["people"]} == {"a", "c"}
    departments = [{"open_department_id": "rd", "name": "研发", "parent_department_id": "0"}]
    users = [{"open_id": "ou_a", "name": "张三", "department_ids": ["rd"], "status": {"is_resigned": False}},
             {"open_id": "ou_new", "name": "新人", "department_ids": ["rd"], "status": {"is_resigned": False}}]
    with factory.begin() as db:
        apply_directory(db, departments, users, settings)
    with factory() as db:
        assert {p["name"] for p in resolve_selection(db, selection)["people"]} == {"张三", "新人"}


def test_bootstrap_admins_match_user_ids_and_only_initialize_once(factory, settings):
    settings.initial_admin_user_ids = " staff_a, staff_b, staff_a, "
    users = [
        {"open_id": "ou_a", "user_id": "staff_a", "name": "张三", "status": {"is_resigned": False}},
        {"open_id": "ou_b", "user_id": "staff_b", "name": "李四", "status": {"is_resigned": False}},
        {"open_id": "staff_a", "user_id": "other_staff", "name": "其他员工", "status": {"is_resigned": False}},
    ]
    with factory.begin() as db:
        apply_directory(db, [], users, settings)
    with factory.begin() as db:
        assert db.get(Employee, "a").user_id == "staff_a"
        assert db.get(Employee, "a").role == "admin"
        assert db.get(Employee, "b").role == "admin"
        other = db.scalar(select(Employee).where(Employee.open_id == "staff_a"))
        assert other.role == "none"
        assert db.get(SystemState, 1).bootstrap_done
        assert len(list(db.scalars(select(PermissionAudit)))) == 2
        # Later permission changes must not be undone by another directory sync.
        db.get(Employee, "b").role = "none"
    settings.initial_admin_user_ids = "staff_b,other_staff"
    with factory.begin() as db:
        apply_directory(db, [], users, settings)
    with factory() as db:
        assert db.get(Employee, "a").role == "admin"
        assert db.get(Employee, "b").role == "none"
        assert db.scalar(select(Employee).where(Employee.open_id == "staff_a")).role == "none"
        assert len(list(db.scalars(select(PermissionAudit)))) == 2


@pytest.mark.parametrize("configured_id,user_id,status", [
    ("staff_a", None, {"is_resigned": False}),
    ("ou_a", "staff_a", {"is_resigned": False}),
    ("staff_a", "staff_a", {"is_resigned": True}),
    ("staff_a", "staff_a", {"is_resigned": False, "is_frozen": True}),
    ("staff_a", "staff_a", {}),
])
def test_bootstrap_waits_for_matching_active_user_id(factory, settings, configured_id, user_id, status):
    settings.initial_admin_user_ids = configured_id
    user = {"open_id": "ou_a", "user_id": user_id, "name": "张三", "status": status}
    with factory.begin() as db:
        apply_directory(db, [], [user], settings)
    with factory() as db:
        assert db.get(Employee, "a").role == "none"
        assert not db.get(SystemState, 1).bootstrap_done
        assert not list(db.scalars(select(PermissionAudit)))
    # Once the configured person is available and active, initialization can finish.
    user.update(user_id=configured_id, status={"is_resigned": False})
    with factory.begin() as db:
        apply_directory(db, [], [user], settings)
    with factory() as db:
        assert db.get(Employee, "a").role == "admin"
        assert db.get(SystemState, 1).bootstrap_done


def test_feishu_template_and_uuid_contract(settings):
    requests = []
    def handle(request):
        requests.append(request)
        if "tenant_access_token" in str(request.url):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "secret", "expire": 7200})
        return httpx.Response(200, json={"code": 0, "data": {"message_id": "om_123"}})
    settings.feishu_app_id, settings.feishu_app_secret = "app", "secret"
    client = FeishuClient(settings, transport=httpx.MockTransport(handle))
    card = {"type": "template", "data": {"template_id": "plus", "template_version_name": "1.0.0", "template_variable": {"total": 65}}}
    assert client.send_card("ou_a", card, "stable-uuid") == "om_123"
    assert client.send_card("ou_a", card, "stable-uuid") == "om_123"
    assert len(requests) == 3  # Tenant token is cached.
    body = json.loads(requests[1].content)
    assert body["uuid"] == "stable-uuid" and body["receive_id"] == "ou_a"
    assert json.loads(body["content"]) == card
    client.close()


def test_send_timeout_is_uncertain(settings):
    def handle(request):
        if "tenant_access_token" in str(request.url):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "secret", "expire": 7200})
        raise httpx.ReadTimeout("timeout", request=request)
    settings.feishu_app_id, settings.feishu_app_secret = "app", "secret"
    client = FeishuClient(settings, transport=httpx.MockTransport(handle))
    with pytest.raises(FeishuError) as result:
        client.send_card("ou_a", {}, "stable")
    assert result.value.uncertain and result.value.retryable
    client.close()


@pytest.mark.parametrize("code,hint", [(40004, "全部成员"), (40014, "父部门权限"), (99991672, "API 权限")])
def test_contact_errors_explain_permissions_without_echoing_response(settings, code, hint):
    def handle(request):
        if "tenant_access_token" in str(request.url):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "private-token", "expire": 7200})
        return httpx.Response(400, json={
            "code": code, "msg": "do not echo private-token or personal-data",
            "error": {"permission_violations": [
                {"subject": "contact:department.organize:readonly"},
                {"subject": "private-token"},
            ]},
        })
    settings.feishu_app_id, settings.feishu_app_secret = "app", "app-secret"
    client = FeishuClient(settings, transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(FeishuError) as error:
            client.fetch_directory()
        detail = str(error.value)
        assert f"code {code}" in detail and hint in detail
        assert "contact:department.organize:readonly" in detail
        assert "private-token" not in detail and "personal-data" not in detail
    finally:
        client.close()


def test_oauth_error_never_echoes_upstream_body(settings):
    def handle(request):
        return httpx.Response(400, json={"code": 40004, "msg": "private-access-token", "access_token": "private-access-token"})
    client = FeishuClient(settings, transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(FeishuError) as error:
            client.oauth_user("authorization-code", "verifier")
        assert "private-access-token" not in str(error.value)
    finally:
        client.close()


def test_sync_failure_logs_actionable_error_and_preserves_directory(factory, settings, monkeypatch, caplog):
    from app import worker

    class UnavailableDirectory:
        def fetch_directory(self):
            raise FeishuError("飞书接口拒绝请求（HTTP 400，code 40004）：请将通讯录权限范围设为全部成员")

    monkeypatch.setattr(worker, "SessionLocal", factory)
    worker.sync_if_due(UnavailableDirectory(), settings)
    assert "code 40004" in caplog.text and "全部成员" in caplog.text
    with factory() as db:
        assert db.get(Employee, "a").status == "active"
        state = db.get(SystemState, 1)
        assert "code 40004" in state.last_sync_error and state.sync_requested
