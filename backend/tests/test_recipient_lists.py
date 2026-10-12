from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.adjustments import commit_preview, create_preview
from app.db import lock_state
from app.directory import resolve_selection
from app.models import Balance, Department, Employee, Membership, Preset
from app.presets import save_preset
from app.schemas import AdjustmentRequest, PresetRequest, Selection
from test_api import client, login  # Reuse the isolated API fixture.


def ids(result):
    return {p["id"] for p in result["people"]}


def test_union_combines_layers_descendants_and_explicit_people(factory):
    selection = Selection(match_mode="union", department_ids=["rd", "east", "team", "rd"],
                          person_ids=["a", "admin", "c"], extra_ids=["admin", "b"])
    with factory() as db:
        result = resolve_selection(db, selection)
        assert ids(result) == {"a", "b", "c", "admin"}
        assert len(result["people"]) == 4
        assert result["warnings"] == []


def test_union_empty_invalid_and_unavailable_never_widen(factory):
    with factory() as db:
        assert resolve_selection(db, Selection(match_mode="union", mode="all"))["people"] == []
        result = resolve_selection(db, Selection(match_mode="union", department_ids=["missing"],
                                                person_ids=["gone", "unknown"], extra_ids=["a"]))
        assert ids(result) == {"a"}
        assert len(result["warnings"]) == 3


def test_union_re_resolves_joiners_moves_resignations_and_inactive_departments(factory):
    selection = Selection(match_mode="union", department_ids=["sw"])
    with factory() as db:
        assert ids(resolve_selection(db, selection)) == {"a", "c"}
    with factory.begin() as db:
        db.add(Employee(id="new", open_id="ou_new", name="新人", status="active"))
        db.add(Membership(employee_id="new", department_id="team"))
        db.delete(db.get(Membership, ("a", "team")))
        db.add(Membership(employee_id="a", department_id="east"))
        db.get(Employee, "c").status = "resigned"
    with factory() as db:
        assert ids(resolve_selection(db, selection)) == {"new"}
    with factory.begin() as db:
        db.get(Department, "sw").active = False
    with factory() as db:
        result = resolve_selection(db, selection)
        assert result["people"] == []
        assert result["warnings"]


def test_legacy_selection_stays_intersection(factory):
    old_json = {"levels": [["rd"], ["east"], []], "mode": "all", "person_ids": [], "extra_ids": []}
    with factory() as db:
        assert ids(resolve_selection(db, Selection.model_validate(old_json))) == set()
        assert ids(resolve_selection(db, Selection(match_mode="union", department_ids=["rd", "east"]))) == {"a", "b", "c"}


@pytest.mark.parametrize("selection", [
    {"match_mode": "union", "levels": [["rd"], [], []]},
    {"department_ids": ["rd"]},
    {"match_mode": "unexpected"},
])
def test_ambiguous_matching_is_rejected(client, factory, selection):
    headers = login(client, factory)
    assert client.post("/api/ranges/resolve", json=selection, headers=headers).status_code == 422


def test_public_lists_visible_to_operators_but_admin_only_writable(client, factory):
    headers = login(client, factory)
    body = {"name": "研发通知", "scope": "public", "selection": {"match_mode": "union", "department_ids": ["rd"]}}
    saved = client.post("/api/presets", json=body, headers=headers)
    assert saved.status_code == 201
    public_id = saved.json()["id"]
    private = client.post("/api/presets", json=body | {"scope": "personal"}, headers=headers)
    assert private.status_code == 201
    headers = login(client, factory, "operator")
    visible = client.get("/api/presets").json()
    assert len(visible) == 1 and visible[0]["id"] == public_id and not visible[0]["can_edit"]
    assert client.post("/api/presets", json=body, headers=headers).status_code == 403
    assert client.put(f"/api/presets/{public_id}", json=body, headers=headers).status_code == 403
    assert client.delete(f"/api/presets/{public_id}", headers=headers).status_code == 403
    assert client.post("/api/presets", json=body | {"scope": "personal"}, headers=headers).status_code == 201


def test_other_admin_can_manage_public_but_not_private_lists(client, factory):
    headers = login(client, factory)
    body = {"name": "通知", "scope": "public", "selection": {"match_mode": "union", "person_ids": ["a"]}}
    public_id = client.post("/api/presets", json=body, headers=headers).json()["id"]
    private_id = client.post("/api/presets", json=body | {"scope": "personal"}, headers=headers).json()["id"]
    with factory.begin() as db:
        db.get(Employee, "operator").role = "admin"
    headers = login(client, factory, "operator")
    assert client.get("/api/presets").json()[0]["can_edit"]
    assert client.post("/api/presets", json=body, headers=headers).status_code == 409
    assert client.put(f"/api/presets/{private_id}", json=body | {"scope": "personal"}, headers=headers).status_code == 404
    assert client.delete(f"/api/presets/{private_id}", headers=headers).status_code == 404
    assert client.put(f"/api/presets/{public_id}", json=body | {"scope": "personal"}, headers=headers).status_code == 422
    assert client.put(f"/api/presets/{public_id}", json=body | {"name": "新版通知"}, headers=headers).status_code == 200
    assert client.delete(f"/api/presets/{public_id}", headers=headers).status_code == 200


def test_personal_name_normalization_uniqueness_and_csrf(client, factory):
    headers = login(client, factory)
    body = {"name": "  我的名单  ", "selection": {"match_mode": "union", "person_ids": ["a"]}}
    assert client.post("/api/presets", json=body).status_code == 403
    saved = client.post("/api/presets", json=body, headers=headers).json()
    assert saved["name"] == "我的名单"
    assert saved["scope"] == "personal" and saved["can_edit"]
    assert client.post("/api/presets", json=body | {"name": "我的名单"}, headers=headers).status_code == 409
    assert client.put(f"/api/presets/{saved['id']}", json=body, headers=headers).status_code == 200
    assert client.post("/api/presets", json=body | {"name": "  "}, headers=headers).status_code == 422


@pytest.mark.parametrize("status,role", [("active", "none"), ("resigned", "admin"), ("unknown", "operator")])
def test_revoked_or_unavailable_users_cannot_maintain_lists(client, factory, status, role):
    headers = login(client, factory)
    body = {"name": "通知", "selection": {"person_ids": ["a"]}}
    preset_id = client.post("/api/presets", json=body, headers=headers).json()["id"]
    with factory.begin() as db:
        user = db.get(Employee, "admin")
        user.status, user.role = status, role
    assert client.get("/api/presets").status_code == 403
    assert client.post("/api/presets", json=body, headers=headers).status_code == 403
    assert client.put(f"/api/presets/{preset_id}", json=body, headers=headers).status_code == 403
    assert client.delete(f"/api/presets/{preset_id}", headers=headers).status_code == 403


def test_concurrent_public_names_are_unique_across_admins(factory):
    with factory.begin() as db:
        db.get(Employee, "operator").role = "admin"

    def create(user_id):
        with factory() as db:
            lock_state(db)
            try:
                save_preset(db, db.get(Employee, user_id), PresetRequest(name="公共名单", scope="public", selection=Selection()))
                return 201
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create, ["admin", "operator"])) == [201, 409]
    with factory() as db:
        assert len(list(db.scalars(select(Preset)))) == 1


def test_union_preview_commit_deduplicates_and_detects_directory_changes(factory, settings, when):
    request = AdjustmentRequest(person_ids=["a", "b"], operation="plus", points=5, reason="协作",
        recipients=Selection(match_mode="union", department_ids=["rd", "east"], person_ids=["a", "c"]))
    with factory.begin() as db:
        preview = create_preview(db, "admin", request, settings, when)
        assert len(preview["recipients"]) == 3 and preview["message_count"] == 6
    with factory.begin() as db:
        batch = commit_preview(db, "admin", preview["preview_token"], "union-batch-idempotency-key", settings, when)
        assert batch.snapshot["recipients"] == preview["recipients"]
        assert db.get(Balance, ("a", "2026-10")).total == 65
    with factory.begin() as db:
        preview = create_preview(db, "admin", request, settings, when)
    with factory.begin() as db:
        db.get(Employee, "c").status = "resigned"
    with factory() as db:
        with pytest.raises(HTTPException) as exc:
            commit_preview(db, "admin", preview["preview_token"], "changed-union-idempotency-key", settings, when)
        assert exc.value.status_code == 409
