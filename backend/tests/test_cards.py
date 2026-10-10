import json
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.adjustments import commit_preview, create_preview
from app.cards import department_text
from app.delivery import claim_delivery, complete_delivery
from app.feishu import FeishuClient, FeishuError
from app.models import Delivery, Ledger
from test_adjustments import request


@pytest.mark.parametrize("operation,total,expected_score,template_id,version", [
    ("plus", 65, "5", "AAqzjRLLF2LbI", "1.0.4"),
    ("minus", 55, "-5", "AAqzj4Y1vmkf7", "1.0.3"),
    ("plus", 0, "5", "AAqzjRLLF2LbI", "1.0.4"),
    ("minus", -8, "-5", "AAqzj4Y1vmkf7", "1.0.3"),
])
def test_published_card_variables_and_delivery_snapshot(factory, settings, when, operation, total, expected_score, template_id, version):
    overrides = {} if total == (65 if operation == "plus" else 55) else {"a": total}
    reason = '完成「专项」\n说明包含 "引号" 和反斜杠 \\。'
    with factory.begin() as db:
        preview = create_preview(db, "admin", request(operation=operation, reason=reason, overrides=overrides), settings, when)
    row = preview["rows"][0]
    assert row["context"]["department"] == "研发 / 软件 / 平台"
    assert row["card"] == {"type": "template", "data": {
        "template_id": template_id, "template_version_name": version,
        "template_variable": {"department": "研发 / 软件 / 平台", "user_name": "张三",
                              "reason": reason, "score": expected_score, "total_score": str(total)},
    }}
    with factory.begin() as db:
        commit_preview(db, "admin", preview["preview_token"], str(uuid4()), settings, when)
    with factory() as db:
        ledger = db.scalar(select(Ledger))
        assert ledger.card == row["card"]
    with factory.begin() as db:
        db.scalar(select(Delivery)).next_attempt_at = when
    with factory.begin() as db:
        task = claim_delivery(db, settings, when)
    requests = []
    def handle(upstream):
        if "tenant_access_token" in str(upstream.url):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "test-token", "expire": 7200})
        requests.append(upstream)
        assert upstream.method == "POST"
        assert str(upstream.url) == "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"
        assert upstream.headers["Content-Type"] == "application/json; charset=utf-8"
        assert upstream.headers["Authorization"] == "Bearer test-token"
        body = json.loads(upstream.content)
        assert body["receive_id"] == "ou_operator"
        assert body["msg_type"] == "interactive"
        assert body["uuid"] == task["uuid"]
        assert isinstance(body["content"], str)
        assert json.loads(body["content"]) == row["card"]
        return httpx.Response(200, json={"code": 0, "data": {"message_id": "om_test"}})
    settings.feishu_app_id, settings.feishu_app_secret = "test-app", "test-secret"
    client = FeishuClient(settings, transport=httpx.MockTransport(handle))
    try:
        message_id = client.send_card(task["recipient_open_id"], task["card"], task["uuid"])
    finally:
        client.close()
    with factory.begin() as db:
        complete_delivery(db, task, settings, message_id=message_id, when=when)
    with factory() as db:
        delivery = db.get(Delivery, task["id"])
        assert delivery.status == "sent" and delivery.message_id == "om_test"
    assert len(requests) == 1


def test_department_text_preserves_multiple_paths_and_root():
    assert department_text({"paths": []}) == "直属企业"
    assert department_text({"paths": [
        {"names": ["研发", "软件", "平台"]}, {"names": ["销售", "华东"]},
        {"names": ["研发", "软件", "平台"]},
    ]}) == "研发 / 软件 / 平台；销售 / 华东"


def test_upstream_still_sending_is_uncertain(settings):
    def handle(upstream):
        if "tenant_access_token" in str(upstream.url):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "test-token", "expire": 7200})
        return httpx.Response(400, json={"code": 230049, "msg": "The message is being sent."})
    settings.feishu_app_id, settings.feishu_app_secret = "test-app", "test-secret"
    client = FeishuClient(settings, transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(FeishuError) as error:
            client.send_card("ou_operator", {}, "stable-uuid")
        assert error.value.retryable and error.value.uncertain
    finally:
        client.close()
