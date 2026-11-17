"""Bitable adapter, separate from the existing notification client behavior."""

import json
import re
import threading
import time
from urllib.parse import parse_qs, unquote, urlparse

from ..feishu import FeishuClient, FeishuError


KEYS = ("user_id", "name", "department")
IDENTIFIER = re.compile(r"[A-Za-z0-9]{1,150}\Z")
TABLE_ID = re.compile(r"tbl[A-Za-z0-9]{1,147}\Z")


class BitableClient(FeishuClient):
    def __init__(self, settings, interval=1, transport=None):
        super().__init__(settings, transport=transport)
        self.interval = max(0, interval)
        self._request_lock = threading.Lock()
        self._next_request = 0
        self.last_log_id = None
        self.http.event_hooks["response"].append(self._capture_log_id)

    def _capture_log_id(self, response):
        value = response.headers.get("x-tt-logid", "")
        self.last_log_id = value if re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value) else None

    def api(self, method, path, **kwargs):
        with self._request_lock:
            delay = self._next_request - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            try:
                data = super().api(method, path, **kwargs)
                if not isinstance(data, dict):
                    raise FeishuError("飞书返回的数据结构不完整", uncertain=kwargs.get("sending", False))
                return data
            except FeishuError as error:
                if error.code in {91403, 1254302, 1254303, 99991672, 99991679}:
                    raise FeishuError("飞书应用无权访问目标多维表或缺少权限，请检查应用授权和表格协作者设置",
                                      code=error.code, uncertain=error.uncertain) from error
                raise
            finally:
                self._next_request = time.monotonic() + self.interval

    @staticmethod
    def _path(base_token, table_id=None):
        if not isinstance(base_token, str) or not IDENTIFIER.fullmatch(base_token):
            raise ValueError("多维表标识无效")
        if table_id is not None and (not isinstance(table_id, str) or not TABLE_ID.fullmatch(table_id)):
            raise ValueError("数据表标识无效")
        path = f"/bitable/v1/apps/{base_token}/tables"
        return f"{path}/{table_id}" if table_id is not None else path

    def _pages(self, path, *, page_size=100, params=None):
        cursor = None
        seen = set()
        while True:
            data = self.api("GET", path, params={"page_size": page_size, **(params or {}),
                                                   **({"page_token": cursor} if cursor else {})})
            items = data.get("items")
            if (not isinstance(items, list) or not all(isinstance(item, dict) for item in items)
                    or not isinstance(data.get("has_more"), bool)):
                raise FeishuError("飞书返回的数据页不完整，本次停止同步")
            yield from items
            if not data["has_more"]:
                return
            cursor = data.get("page_token")
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise FeishuError("飞书分页游标异常，未取得完整目标数据")
            seen.add(cursor)

    def _fields(self, base_token, table_id):
        result, seen = [], set()
        for field in self._pages(self._path(base_token, table_id) + "/fields"):
            field_id, name, kind = field.get("field_id"), field.get("field_name"), field.get("type")
            if (not isinstance(field_id, str) or field_id in seen
                    or not isinstance(name, str) or not isinstance(kind, int)):
                raise FeishuError("目标表字段结构不完整")
            seen.add(field_id)
            result.append({"id": field_id, "name": name, "type": kind, "writable": kind == 1})
        return result

    def resolve_target(self, url, table_id=None):
        if not isinstance(url, str):
            raise ValueError("请填写飞书多维表链接")
        parsed = urlparse(url.strip())
        hostname = (parsed.hostname or "").lower()
        allowed = any(hostname == suffix or hostname.endswith("." + suffix)
                      for suffix in ("feishu.cn", "larksuite.com"))
        if parsed.scheme != "https" or not allowed or parsed.username or parsed.password or parsed.port not in {None, 443}:
            raise ValueError("请填写有效的飞书多维表或知识库 HTTPS 链接")
        parts = unquote(parsed.path).strip("/").split("/")
        if len(parts) != 2 or parts[0] not in {"base", "wiki"} or not IDENTIFIER.fullmatch(parts[1]):
            raise ValueError("链接须指向飞书多维表或知识库中的多维表")
        token = parts[1]
        if parts[0] == "wiki":
            data = self.api("GET", "/wiki/v2/spaces/get_node", params={"token": token})
            node = data.get("node", {})
            if node.get("obj_type") != "bitable" or not isinstance(node.get("obj_token"), str):
                raise ValueError("该知识库链接指向的不是多维表")
            token = node["obj_token"]
        query = parse_qs(parsed.query)
        selected = table_id or query.get("table", [None])[0]
        tables, table_ids = [], set()
        for table in self._pages(self._path(token)):
            current_id, name = table.get("table_id"), table.get("name")
            if (not isinstance(current_id, str) or not TABLE_ID.fullmatch(current_id)
                    or current_id in table_ids or not isinstance(name, str)):
                raise FeishuError("多维表的数据表目录不完整")
            table_ids.add(current_id)
            tables.append({"id": current_id, "name": name})
        if selected is None and len(tables) == 1:
            selected = tables[0]["id"]
        matches = [table for table in tables if table["id"] == selected]
        if selected is not None and not matches:
            raise ValueError("链接选中的不是可同步的数据表，请选择正确的数据表")
        return {"base_token": token, "table_id": selected,
                "table_name": matches[0]["name"] if matches else None, "tables": tables,
                "fields": self._fields(token, selected) if selected else []}

    def validate_mapping(self, base_token, table_id, mapping):
        if (not isinstance(mapping, dict) or set(mapping) != set(KEYS)
                or not all(isinstance(value, str) and value for value in mapping.values())
                or len(set(mapping.values())) != len(KEYS)):
            raise ValueError("请为 user_id、姓名、部门分别选择三个不同的文本字段")
        fields = {field["id"]: field for field in self._fields(base_token, table_id)}
        names = {}
        for key in KEYS:
            field = fields.get(mapping[key])
            if field is None:
                raise ValueError("映射字段已被删除，请重新检查字段映射")
            if not field["writable"]:
                raise ValueError(f"字段“{field['name']}”不是可写文本字段，请调整映射")
            names[key] = field["name"]
        return names

    @staticmethod
    def _text(value):
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list) and all(isinstance(part, dict) and isinstance(part.get("text"), str)
                                           and part.get("type", "text") == "text" for part in value):
            return "".join(part["text"] for part in value)
        raise FeishuError("目标映射字段返回了非文本值，请检查字段类型")

    def read_rows(self, base_token, table_id, mapping):
        names = self.validate_mapping(base_token, table_id, mapping)
        rows, seen = [], set()
        for item in self._pages(self._path(base_token, table_id) + "/records", page_size=500,
                                params={"field_names": json.dumps(list(names.values()), ensure_ascii=False)}):
            record_id, fields = item.get("record_id"), item.get("fields")
            if not isinstance(record_id, str) or not record_id or record_id in seen or not isinstance(fields, dict):
                raise FeishuError("目标记录 ID 缺失或重复，未取得完整目标数据")
            seen.add(record_id)
            rows.append({"record_id": record_id,
                         **{key: self._text(fields.get(name)) for key, name in names.items()}})
        return rows

    @staticmethod
    def _batch(rows):
        if len(rows) > 200:
            raise ValueError("每批最多处理 200 条记录")

    def _write_rows(self, base_token, table_id, mapping, rows, *, updating):
        self._batch(rows)
        if not rows:
            return 0
        names = self.validate_mapping(base_token, table_id, mapping)
        records = []
        for row in rows:
            if any(not isinstance(row.get(key), str) for key in KEYS):
                raise ValueError("待同步字段必须为文本")
            record = {"fields": {names[key]: row[key] for key in KEYS}}
            if updating:
                if not isinstance(row.get("record_id"), str) or not IDENTIFIER.fullmatch(row["record_id"]):
                    raise ValueError("待更新记录的 ID 无效")
                record["record_id"] = row["record_id"]
            records.append(record)
        action = "batch_update" if updating else "batch_create"
        data = self.api("POST", self._path(base_token, table_id) + f"/records/{action}",
                        json={"records": records}, sending=True)
        returned = data.get("records")
        if (not isinstance(returned, list) or len(returned) != len(records)
                or any(not isinstance(item, dict) or not isinstance(item.get("record_id"), str)
                       or not IDENTIFIER.fullmatch(item["record_id"]) for item in returned)
                or len({item["record_id"] for item in returned}) != len(returned)
                or updating and {item["record_id"] for item in returned} != {row["record_id"] for row in rows}):
            raise FeishuError("飞书写入响应不完整，结果待核实，请重新核对目标表", uncertain=True)
        return len(returned)

    def create_rows(self, base_token, table_id, mapping, rows):
        return self._write_rows(base_token, table_id, mapping, rows, updating=False)

    def update_rows(self, base_token, table_id, mapping, rows):
        return self._write_rows(base_token, table_id, mapping, rows, updating=True)

    def delete_rows(self, base_token, table_id, rows):
        self._batch(rows)
        if not rows:
            return 0
        identifiers = [row.get("record_id") if isinstance(row, dict) else row for row in rows]
        if (any(not isinstance(value, str) or not IDENTIFIER.fullmatch(value) for value in identifiers)
                or len(set(identifiers)) != len(identifiers)):
            raise ValueError("待删除记录的 ID 无效或重复")
        data = self.api("POST", self._path(base_token, table_id) + "/records/batch_delete",
                        json={"records": identifiers}, sending=True)
        returned = data.get("records")
        if (not isinstance(returned, list) or len(returned) != len(identifiers)
                or any(not isinstance(item, dict) or item.get("deleted") is not True
                       or not isinstance(item.get("record_id"), str) for item in returned)
                or {item.get("record_id") for item in returned} != set(identifiers)):
            raise FeishuError("飞书删除响应不完整，结果待核实，请重新核对目标表", uncertain=True)
        return len(returned)
