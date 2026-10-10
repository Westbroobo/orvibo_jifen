import json
import re
import threading
import time

import httpx


class FeishuError(Exception):
    def __init__(self, message, *, retryable=False, uncertain=False, code=None):
        super().__init__(message)
        self.retryable = retryable
        self.uncertain = uncertain
        self.code = code


class FeishuClient:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.http = httpx.Client(timeout=httpx.Timeout(25, connect=10), transport=transport)
        self._token = None
        self._expires = 0
        self._token_lock = threading.Lock()

    def close(self):
        self.http.close()

    def _json(self, method, url, *, sending=False, **kwargs):
        try:
            response = self.http.request(method, url, **kwargs)
        except httpx.RequestError as error:
            raise FeishuError("飞书网络请求失败", retryable=True, uncertain=sending) from error
        try:
            data = response.json()
        except ValueError as error:
            raise FeishuError("飞书返回了无法解析的响应", retryable=True, uncertain=sending) from error
        if response.status_code >= 500:
            raise FeishuError("飞书服务暂时不可用", retryable=True, uncertain=sending)
        if response.status_code == 429:
            raise FeishuError("飞书接口限流", retryable=True)
        code = data.get("code", 0)
        if response.is_error or code != 0 or data.get("error"):
            # Do not echo response bodies: OAuth responses can contain credentials.
            detail = f"飞书接口拒绝请求（HTTP {response.status_code}，code {code}）"
            if response.request.url.path.startswith("/open-apis/contact/"):
                hints = {
                    40004: "无部门权限，请将应用的通讯录数据权限范围设为全部成员，并发布生效",
                    40014: "无父部门权限，请检查通讯录组织架构可见范围",
                    40011: "分页大小无效，请检查 page_size",
                    40012: "分页游标无效，请重新同步",
                    42008: "租户身份无效，请检查当前应用所属企业",
                    43010: "超大部门不允许递归查询",
                    99991672: "缺少通讯录 API 权限，请在飞书后台开通应用身份权限，并发布生效",
                    99991679: "缺少通讯录 API 权限，请在飞书后台开通应用身份权限，并发布生效",
                }
                if code in hints:
                    detail += "：" + hints[code]
                # Scope identifiers are safe diagnostics; never print upstream
                # message text or the full body, which may echo credentials.
                error = data.get("error")
                violations = error.get("permission_violations", []) if isinstance(error, dict) else []
                scopes = sorted({item["subject"] for item in violations if isinstance(item, dict)
                                 and isinstance(item.get("subject"), str)
                                 and re.fullmatch(r"contact:[a-z0-9_.:-]{1,150}", item["subject"])})
                if scopes:
                    detail += "；所需权限（按接口要求开通）：" + "、".join(scopes)
            if method == "DELETE" and response.request.url.path.startswith("/open-apis/im/v1/messages/"):
                hint = {
                    230009: "消息已超出企业设置的撤回时限",
                    230013: "接收人不在当前机器人的可用范围内或已离职",
                    230026: "当前机器人只能撤回自己发送的消息，请确认发送时使用的飞书应用",
                    230027: "当前应用缺少消息撤回权限，请在飞书后台开通并发布",
                    230050: "当前应用无法访问该消息，请确认发送时使用的飞书应用",
                    230006: "请开启当前应用的机器人能力并发布",
                }.get(code)
                if hint:
                    detail += "：" + hint
            raise FeishuError(detail, code=code,
                              retryable=code in {99991400, 99991403, 230020, 230049},
                              uncertain=sending and code == 230049)
        return data

    def tenant_token(self):
        with self._token_lock:
            if self._token and time.monotonic() < self._expires:
                return self._token
            if not self.settings.feishu_app_id or not self.settings.feishu_app_secret:
                raise FeishuError("尚未配置飞书应用凭据")
            data = self._json("POST", "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                              json={"app_id": self.settings.feishu_app_id, "app_secret": self.settings.feishu_app_secret})
            self._token = data["tenant_access_token"]
            self._expires = time.monotonic() + max(1, data.get("expire", 7200) - 120)
            return self._token

    def api(self, method, path, **kwargs):
        return self._json(method, "https://open.feishu.cn/open-apis" + path,
                          headers={"Authorization": f"Bearer {self.tenant_token()}",
                                   "Content-Type": "application/json; charset=utf-8"}, **kwargs).get("data", {})

    def oauth_user(self, code, verifier):
        # v2 is the documented endpoint supporting PKCE S256.
        token = self._json("POST", "https://open.feishu.cn/open-apis/authen/v2/oauth/token", json={
            "grant_type": "authorization_code", "client_id": self.settings.feishu_app_id,
            "client_secret": self.settings.feishu_app_secret, "code": code,
            "redirect_uri": self.settings.feishu_redirect_uri, "code_verifier": verifier,
        })
        return self._json("GET", "https://open.feishu.cn/open-apis/authen/v1/user_info",
                          headers={"Authorization": f"Bearer {token['access_token']}"})["data"]

    def pages(self, path, params):
        token = None
        seen = set()
        while True:
            data = self.api("GET", path, params={**params, **({"page_token": token} if token else {})})
            yield from data.get("items", [])
            if not data.get("has_more"):
                return
            token = data.get("page_token")
            if not token or token in seen:
                raise FeishuError("飞书分页游标异常，未应用不完整的同步数据")
            seen.add(token)

    def fetch_directory(self):
        # Traverse immediate children to avoid recursive-list caps.
        departments = []
        queue = ["0"]
        visited = set()
        while queue:
            parent = queue.pop(0)
            if parent in visited:
                raise FeishuError("部门树存在重复或循环")
            visited.add(parent)
            children = list(self.pages(f"/contact/v3/departments/{parent}/children", {
                "department_id_type": "open_department_id", "fetch_child": "false", "page_size": 50,
            }))
            departments.extend(children)
            queue.extend(d["open_department_id"] for d in children)
        users = {}
        for department_id in ["0"] + [d["open_department_id"] for d in departments]:
            for user in self.pages("/contact/v3/users/find_by_department", {
                "department_id": department_id, "department_id_type": "open_department_id",
                "user_id_type": "open_id", "page_size": 50,
            }):
                users[user["open_id"]] = user
        return departments, list(users.values())

    def send_card(self, recipient_open_id, card, message_uuid):
        data = self.api("POST", "/im/v1/messages", sending=True,
                        params={"receive_id_type": "open_id"},
                        json={"receive_id": recipient_open_id, "msg_type": "interactive",
                              "content": json.dumps(card, ensure_ascii=False), "uuid": message_uuid})
        if not data.get("message_id"):
            raise FeishuError("发送响应缺少 message_id，消息状态待核实", retryable=True, uncertain=True)
        return data["message_id"]

    def recall_message(self, message_id):
        try:
            self.api("DELETE", "/im/v1/messages/" + message_id, sending=True)
        except FeishuError as error:
            # Repeating DELETE is safe after a lost response or worker restart.
            # The documented already-deleted response confirms the desired state.
            if error.code != 230110:
                raise
