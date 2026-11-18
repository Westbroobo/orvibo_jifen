import json

import httpx
import pytest

from app.models import Employee, Preset, SystemState
from app.table_sync.core import SourceError, check_source, diff_rows, read_source
from app.table_sync.remote import BitableClient
from app.feishu import FeishuError


MAPPING = {"user_id": "fldUser", "name": "fldName", "department": "fldDepartment"}
FIELDS = [
    {"field_id": "fldUser", "field_name": "user_id", "type": 1},
    {"field_id": "fldName", "field_name": "姓名", "type": 1},
    {"field_id": "fldDepartment", "field_name": "部门", "type": 1},
    {"field_id": "fldAuto", "field_name": "序号", "type": 1005},
]


def person(user_id="staffA", name="张三", department="平台", **extra):
    return {"user_id": user_id, "name": name, "department": department, **extra}


def source_config(**selection):
    return {"source_kind": "selection", "selection": {"match_mode": "union", **selection}}


def initialize_directory(factory, when):
    with factory.begin() as db:
        db.get(SystemState, 1).last_sync_at = when
        for employee_id in ("a", "b", "c", "gone", "admin", "operator"):
            db.get(Employee, employee_id).user_id = "staff" + employee_id


def remote_client(settings, handler, *, fields=None):
    settings.feishu_app_id, settings.feishu_app_secret = "test-app", "test-secret"
    requests = []

    def serve(request):
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "test-token", "expire": 7200})
        requests.append(request)
        if request.url.path.endswith("/fields"):
            return httpx.Response(200, json={"code": 0, "data": {"items": FIELDS if fields is None else fields,
                                                                     "has_more": False}})
        return handler(request)

    return BitableClient(settings, interval=0, transport=httpx.MockTransport(serve)), requests


def test_diff_preserves_correct_duplicate_and_reconciles_only_changes():
    wanted = [person(), person("staffB", "李四", "华东"), person("staffNew", "新人", "平台")]
    existing = [person(record_id="recZ"), person(name="旧姓名", record_id="recA"),
                person("staffB", "李四", "旧部门", record_id="recB"),
                person("staffGone", "离职员工", record_id="recGone"),
                person("", "空标识记录", record_id="recEmpty")]
    result = diff_rows(wanted, existing)
    assert result["unchanged"] == [person(record_id="recZ")]
    assert result["update"] == [person("staffB", "李四", "华东", record_id="recB")]
    assert result["create"] == [person("staffNew", "新人", "平台")]
    assert {(row["record_id"], row["reason"]) for row in result["delete"]} == {
        ("recA", "duplicate"), ("recGone", "not_in_source"), ("recEmpty", "empty_user_id")}
    assert result["summary"] == {"source": 3, "target": 5, "create": 1, "update": 1,
                                 "delete": 3, "duplicate": 1, "unchanged": 1}
    # Input dictionaries and unrelated fields are never mutated.
    assert existing[1]["name"] == "旧姓名"


def test_diff_empty_source_clears_dedicated_table_and_repeat_is_noop():
    assert diff_rows([], [person(record_id="recA")])["summary"]["delete"] == 1
    result = diff_rows([person()], [person(record_id="recA")])
    assert not result["create"] and not result["update"] and not result["delete"]
    assert result["unchanged"][0]["record_id"] == "recA"


@pytest.mark.parametrize("source, target", [
    ([person("")], []), ([person(), person()], []),
    ([person()], [person()]), ([person()], [person(record_id="recA"), person(record_id="recA")]),
    ([person()], [person(record_id="recA", name=123)]),
])
def test_diff_rejects_ambiguous_identity_or_non_text(source, target):
    with pytest.raises(SourceError):
        diff_rows(source, target)


def test_source_reuses_union_selection_and_leaf_department_names(factory, when):
    initialize_directory(factory, when)
    config = source_config(department_ids=["rd", "team"], person_ids=["b", "a", "c"])
    with factory() as db:
        result = read_source(db, config)
    assert result["rows"] == [person("staffa"), person("staffb", "李四", "华东"),
                              person("staffc", "多部门员工", "华东；平台")]
    assert result["source_name"] == "独立配置范围"
    assert len(result["source_signature"]) == 64


def test_source_public_preset_is_dynamic_and_personal_preset_is_rejected(factory, when):
    initialize_directory(factory, when)
    with factory.begin() as db:
        db.add(Preset(id="public", owner_id="admin", scope="public", name="公开名单",
                      selection={"match_mode": "union", "person_ids": ["a"]}))
        db.add(Preset(id="private", owner_id="admin", scope="personal", name="私有名单",
                      selection={"match_mode": "union", "person_ids": ["b"]}))
    with factory() as db:
        assert read_source(db, {"source_kind": "preset", "preset_id": "public"})["rows"] == [person("staffa")]
        with pytest.raises(SourceError, match="公共名单"):
            read_source(db, {"source_kind": "preset", "preset_id": "private"})


def test_source_missing_id_or_uninitialized_directory_never_looks_like_empty(factory, when):
    config = source_config(person_ids=["a"])
    with factory() as db:
        with pytest.raises(SourceError, match="首次同步"):
            read_source(db, config)
    with factory.begin() as db:
        db.get(SystemState, 1).last_sync_at = when
    with factory() as db:
        with pytest.raises(SourceError, match="缺少 user_id"):
            read_source(db, config)


@pytest.mark.parametrize("config", [
    source_config(department_ids=["rd"]),
    source_config(person_ids=["a", "c", "gone"]),
    source_config(extra_ids=["a", "c", "gone"]),
    {"source_kind": "selection", "selection": {"levels": [["rd"], [], []], "mode": "all"}},
    {"source_kind": "selection", "selection": {"levels": [["rd"], [], []],
                                                "mode": "selected", "person_ids": ["a", "c"]}},
    {"source_kind": "preset", "preset_id": "public"},
])
def test_source_excludes_unknown_without_blocking_active_roster(factory, when, config):
    initialize_directory(factory, when)
    with factory.begin() as db:
        db.get(Employee, "a").status = "unknown"
        db.add(Preset(id="public", owner_id="admin", scope="public", name="公开名单",
                      selection={"match_mode": "union", "department_ids": ["rd"], "person_ids": ["a"]}))
    with factory() as db:
        assert read_source(db, config)["rows"] == [person("staffc", "多部门员工", "华东；平台")]
        result = read_source(db, source_config(person_ids=["b", "gone"]))
        assert result["rows"] == [person("staffb", "李四", "华东")]
        assert db.get(Employee, "a").status == "unknown"


def test_unknown_only_roster_is_empty_and_status_changes_invalidate_snapshot(factory, when):
    initialize_directory(factory, when)
    config = source_config(person_ids=["a"])
    with factory() as db:
        previous = read_source(db, config)
    with factory.begin() as db:
        db.get(Employee, "a").status = "unknown"
    with factory() as db:
        assert read_source(db, config)["rows"] == []
        with pytest.raises(SourceError, match="发生变化"):
            check_source(db, previous, config)


@pytest.mark.parametrize("config", [source_config(department_ids=["missing"]),
                                        source_config(person_ids=["missing"])])
def test_source_invalid_configuration_is_not_a_valid_empty_list(factory, when, config):
    initialize_directory(factory, when)
    with factory() as db:
        with pytest.raises(SourceError):
            read_source(db, config)


def test_source_empty_and_root_department_are_valid(factory, when):
    initialize_directory(factory, when)
    with factory() as db:
        assert read_source(db, source_config())["rows"] == []
        assert read_source(db, source_config(person_ids=["admin"]))["rows"] == [person("staffadmin", "管理员", "直属企业")]


def test_source_legacy_intersection_rejects_person_moved_out_of_range(factory, when):
    initialize_directory(factory, when)
    config = {"source_kind": "selection", "selection": {"levels": [["rd"], [], []],
                                                           "mode": "selected", "person_ids": ["b"]}}
    with factory() as db:
        with pytest.raises(SourceError, match="不符合"):
            read_source(db, config)


def test_source_revalidation_checks_content_as_well_as_directory_version(factory, when):
    initialize_directory(factory, when)
    config = source_config(person_ids=["a"])
    with factory() as db:
        snapshot = read_source(db, config)
        assert check_source(db, snapshot, config) is None
    with factory.begin() as db:
        db.get(Employee, "a").name = "新姓名"
    with factory() as db:
        with pytest.raises(SourceError, match="发生变化"):
            check_source(db, snapshot, config)


def test_resolve_base_and_wiki_validate_selected_table(settings):
    def serve(request):
        if request.url.path == "/open-apis/wiki/v2/spaces/get_node":
            assert request.url.params["token"] == "wikiToken"
            return httpx.Response(200, json={"code": 0, "data": {"node": {"obj_type": "bitable", "obj_token": "baseToken"}}})
        assert request.url.path == "/open-apis/bitable/v1/apps/baseToken/tables"
        return httpx.Response(200, json={"code": 0, "data": {"items": [{"table_id": "tblPeople", "name": "名单"},
                                                                             {"table_id": "tblOther", "name": "其他表"}], "has_more": False}})

    client, _ = remote_client(settings, serve)
    try:
        resolved = client.resolve_target("https://example.feishu.cn/base/baseToken?table=tblPeople")
        assert resolved["table_id"] == "tblPeople" and resolved["table_name"] == "名单"
        assert resolved["fields"][-1]["writable"] is False
        assert client.resolve_target("https://example.feishu.cn/base/baseToken")["table_id"] is None
        assert client.resolve_target("https://example.feishu.cn/wiki/wikiToken", "tblPeople")["base_token"] == "baseToken"
        with pytest.raises(ValueError, match="不是可同步"):
            client.resolve_target("https://example.feishu.cn/base/baseToken?table=dshDashboard")
    finally:
        client.close()


@pytest.mark.parametrize("url", ["http://example.feishu.cn/base/baseToken", "https://evil.example/base/baseToken",
                                "https://example.feishu.cn.evil.example/base/baseToken",
                                "https://example.feishu.cn/base/../secret", "https://user:pass@example.feishu.cn/base/baseToken"])
def test_resolve_rejects_non_base_or_unsafe_urls_without_requests(settings, url):
    client, requests = remote_client(settings, lambda request: pytest.fail("unexpected network request"))
    try:
        with pytest.raises(ValueError):
            client.resolve_target(url)
        assert requests == []
    finally:
        client.close()


def test_read_records_follows_all_pages_and_normalizes_text_without_view_filter(settings):
    def serve(request):
        assert request.method == "GET" and request.url.path.endswith("/records")
        assert "view_id" not in request.url.params and "filter" not in request.url.params
        if "page_token" not in request.url.params:
            data = {"items": [{"record_id": "recA", "fields": {"user_id": "staffA", "姓名": [{"type": "text", "text": "张三"}], "部门": "平台"}}],
                    "has_more": True, "page_token": "page2"}
        else:
            assert request.url.params["page_token"] == "page2"
            data = {"items": [{"record_id": "recB", "fields": {"user_id": "staffB", "姓名": "李四"}}], "has_more": False}
        return httpx.Response(200, json={"code": 0, "data": data})

    client, _ = remote_client(settings, serve)
    try:
        assert client.read_rows("baseToken", "tblPeople", MAPPING) == [person(record_id="recA"), person("staffB", "李四", "", record_id="recB")]
    finally:
        client.close()


@pytest.mark.parametrize("data", [
    {"items": [], "has_more": True},
    {"items": []},
    {"items": [{"record_id": "recA", "fields": {}}]},
    {"items": [], "has_more": 0},
    {"items": [], "has_more": "false"},
    {"items": [{"record_id": "recA", "fields": {}}], "has_more": True, "page_token": "same"},
    {"has_more": False},
    {"items": [{"fields": {}}], "has_more": False},
])
def test_read_rejects_incomplete_pagination_or_identity(settings, data):
    client, _ = remote_client(settings, lambda request: httpx.Response(200, json={"code": 0, "data": data}))
    try:
        with pytest.raises(FeishuError):
            client.read_rows("baseToken", "tblPeople", MAPPING)
    finally:
        client.close()


def test_resolve_rejects_repeated_table_ids_across_pages(settings):
    def serve(request):
        if "page_token" not in request.url.params:
            data = {"items": [{"table_id": "tblPeople", "name": "名单"}],
                    "has_more": True, "page_token": "page2"}
        else:
            data = {"items": [{"table_id": "tblPeople", "name": "重复目录"}], "has_more": False}
        return httpx.Response(200, json={"code": 0, "data": data})

    client, _ = remote_client(settings, serve)
    try:
        with pytest.raises(FeishuError, match="目录不完整"):
            client.resolve_target("https://example.feishu.cn/base/baseToken?table=tblPeople")
    finally:
        client.close()


def test_mapping_rejects_repeated_field_ids_across_pages(settings):
    settings.feishu_app_id, settings.feishu_app_secret = "test-app", "test-secret"

    def serve(request):
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "test-token", "expire": 7200})
        assert request.url.path.endswith("/fields")
        if "page_token" not in request.url.params:
            data = {"items": FIELDS, "has_more": True, "page_token": "page2"}
        else:
            data = {"items": [dict(FIELDS[0], field_name="重复映射")], "has_more": False}
        return httpx.Response(200, json={"code": 0, "data": data})

    client = BitableClient(settings, interval=0, transport=httpx.MockTransport(serve))
    try:
        with pytest.raises(FeishuError, match="字段结构不完整"):
            client.validate_mapping("baseToken", "tblPeople", MAPPING)
    finally:
        client.close()


def test_mapping_uses_stable_id_and_current_name_and_rejects_readonly_fields(settings):
    renamed = [dict(field, field_name="新姓名" if field["field_id"] == "fldName" else field["field_name"]) for field in FIELDS]
    client, _ = remote_client(settings, lambda request: pytest.fail("unexpected write"), fields=renamed)
    try:
        assert client.validate_mapping("baseToken", "tblPeople", MAPPING)["name"] == "新姓名"
        for mapping in (MAPPING | {"name": "fldAuto"}, MAPPING | {"name": "deletedField"}, MAPPING | {"name": "fldUser"}):
            with pytest.raises(ValueError):
                client.validate_mapping("baseToken", "tblPeople", mapping)
    finally:
        client.close()


def test_batch_write_only_maps_three_columns_and_checks_exact_confirmation(settings):
    def serve(request):
        body = json.loads(request.content)
        if request.url.path.endswith("/batch_delete"):
            assert body == {"records": ["recA"]}
            data = {"records": [{"record_id": "recA", "deleted": True}]}
        else:
            expected = {"fields": {"user_id": "staffA", "姓名": "张三", "部门": "平台"}}
            if request.url.path.endswith("/batch_update"):
                expected["record_id"] = "recA"
            assert body == {"records": [expected]}
            data = {"records": [{"record_id": "recA"}]}
        return httpx.Response(200, json={"code": 0, "data": data})

    client, requests = remote_client(settings, serve)
    try:
        assert client.create_rows("baseToken", "tblPeople", MAPPING, [person()]) == 1
        assert client.update_rows("baseToken", "tblPeople", MAPPING, [person(record_id="recA", unrelated="保留")]) == 1
        assert client.delete_rows("baseToken", "tblPeople", [{"record_id": "recA"}]) == 1
        count = len(requests)
        assert client.create_rows("baseToken", "tblPeople", MAPPING, []) == 0
        assert client.delete_rows("baseToken", "tblPeople", []) == 0
        assert len(requests) == count
        with pytest.raises(ValueError, match="200"):
            client.create_rows("baseToken", "tblPeople", MAPPING, [person()] * 201)
    finally:
        client.close()


def test_uncertain_create_is_not_blindly_retried_and_diagnostics_hide_body(settings):
    def serve(request):
        raise httpx.ReadTimeout("upstream includes a secret", request=request)

    client, requests = remote_client(settings, serve)
    try:
        with pytest.raises(FeishuError) as caught:
            client.create_rows("baseToken", "tblPeople", MAPPING, [person()])
        assert caught.value.uncertain is True
        assert "secret" not in str(caught.value)
        assert len([request for request in requests if request.method == "POST"]) == 1
    finally:
        client.close()


@pytest.mark.parametrize("action", ["create", "update", "delete"])
def test_incomplete_write_confirmation_is_uncertain_failure(settings, action):
    client, _ = remote_client(settings, lambda request: httpx.Response(200, json={"code": 0, "data": {"records": []}}))
    try:
        with pytest.raises(FeishuError) as caught:
            if action == "delete":
                client.delete_rows("baseToken", "tblPeople", [person(record_id="recA")])
            else:
                getattr(client, action + "_rows")("baseToken", "tblPeople", MAPPING, [person(record_id="recA")])
        assert caught.value.uncertain is True
    finally:
        client.close()
