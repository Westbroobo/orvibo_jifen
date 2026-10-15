from datetime import datetime, timedelta
from io import BytesIO

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select

from app.cancellations import cancel_score
from app.models import Department, Delivery, Employee, Ledger, Membership
from app.score_ledgers import query_ledgers
from test_adjustments import request, submit
from test_api import client, login


def read(factory, user="admin", **filters):
    with factory() as db:
        return query_ledgers(db, db.get(Employee, user), filters.pop("month", "2026-10"), **filters)


def test_person_rows_summaries_overrides_and_cancel(factory, settings, when):
    batch_id = submit(factory, settings, when, request(person_ids=["a", "b", "c"],
                      overrides={"b": 0}, recipients={"person_ids": ["admin", "operator", "a"]}))
    result = read(factory)
    assert result["total"] == 3  # 九条消息仍然只有三笔流水。
    assert result["summary"] == {"plus_total": 15, "minus_total": 0}
    rows = {row["employee_id"]: row for row in result["items"]}
    assert rows["b"]["final_total"] == rows["b"]["override_total"] == 0
    assert rows["a"]["before_total"] == 60 and rows["a"]["final_total"] == 65
    assert rows["a"]["override_total"] is None
    assert [row["id"] for row in result["items"]] == sorted(row["id"] for row in result["items"])
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Delivery)) == 9
    # 消息仍待发送，已记账的流水仍计入合计。
    with factory.begin() as db:
        ledger = db.scalar(select(Ledger).where(Ledger.batch_id == batch_id, Ledger.employee_id == "a"))
        cancel_score(db, ledger, "admin", when + timedelta(minutes=1))
    submit(factory, settings, when + timedelta(minutes=2), request(person_ids=["b"], operation="minus", points=3))
    result = read(factory)
    assert result["total"] == 4
    assert result["summary"] == {"plus_total": 10, "minus_total": -3}
    assert result["items"][0]["before_total"] == 0
    assert result["items"][0]["final_total"] == -3
    cancelled = read(factory, status="cancelled")
    assert cancelled["total"] == 1 and cancelled["items"][0]["cancelled"]
    assert cancelled["items"][0]["final_total"] == 65
    assert cancelled["summary"] == {"plus_total": 0, "minus_total": 0}
    assert read(factory, status="valid")["total"] == 3
    assert read(factory, operation="minus")["summary"] == {"plus_total": 0, "minus_total": -3}


def test_snapshot_departments_names_and_owner_scope(factory, settings, when):
    with factory.begin() as db:
        db.add(Membership(employee_id="c", department_id="sw"))
    submit(factory, settings, when, request(person_ids=["a", "c"]), user="operator")
    submit(factory, settings, when, request(person_ids=["b"]))
    with factory.begin() as db:
        db.get(Employee, "a").name = "新姓名"
        db.get(Employee, "a").status = "resigned"
        db.get(Employee, "operator").name = "新的操作员姓名"
        db.get(Department, "team").name = "新部门名"
        db.get(Department, "team").active = False
    result = read(factory, user="operator", q="张三", department_id="rd", status="valid", operation="plus")
    assert result["total"] == 1
    assert result["items"][0]["person_name"] == "张三"
    assert result["items"][0]["operator_name"] == "操作员"
    assert result["items"][0]["reason"] == request().reason
    assert result["items"][0]["paths"][0]["names"] == ["研发", "软件", "平台"]
    assert next(d for d in result["departments"] if d["id"] == "team")["name"] == "平台"
    assert read(factory, q="新姓名")["total"] == 0
    assert read(factory, user="operator", department_id="sales")["total"] == 1
    assert read(factory, user="operator")["total"] == 2
    assert read(factory, user="operator", department_id="rd")["total"] == 2
    assert read(factory, user="operator", department_id="missing")["total"] == 0
    # 筛选不影响同月部门选项，但选项不能越过操作员的数据权限。
    submit(factory, settings, datetime(2026, 11, 1), request(person_ids=["b"]))
    hidden = read(factory, user="operator", month="2026-11")
    assert hidden["items"] == hidden["departments"] == []


def test_month_pagination_and_aggregate_across_pages(factory, settings, when):
    for i in range(22):
        submit(factory, settings, when + timedelta(seconds=i), request(points=2))
    submit(factory, settings, datetime(2026, 10, 31, 16, 1), request(points=9))
    first, second = read(factory), read(factory, page=2)
    assert first["total"] == second["total"] == 22
    assert first["summary"]["plus_total"] == second["summary"]["plus_total"] == 44
    assert len(first["items"]) == 20 and len(second["items"]) == 2
    assert not ({r["id"] for r in first["items"]} & {r["id"] for r in second["items"]})
    assert first["items"][0]["created_at"] > second["items"][0]["created_at"]
    assert read(factory, page=99)["page"] == 2
    assert read(factory, month="2026-11")["summary"]["plus_total"] == 9
    assert read(factory, q="%_")["total"] == 0


def test_endpoint_auth_and_validation(client, factory, settings, when):
    endpoint = "/api/score-ledgers"
    assert client.get(endpoint).status_code == 401
    login(client, factory, "operator")
    submit(factory, settings, when, request(person_ids=["b"]))
    result = client.get(endpoint, params={"month": "2026-10"}).json()
    assert result["total"] == 0 and result["departments"] == []
    for params in ({"month": "2026-13"}, {"page": 0}, {"status": "bad"}, {"operation": "bad"}):
        assert client.get(endpoint, params=params).status_code == 422
    with factory.begin() as db:
        db.get(Employee, "operator").role = "none"
    assert client.get(endpoint).status_code == 403


@pytest.mark.parametrize("state", ["resigned", "inactive", "unknown"])
def test_unavailable_operator_cannot_read(client, factory, state):
    login(client, factory, "operator")
    with factory.begin() as db:
        db.get(Employee, "operator").status = state
    assert client.get("/api/score-ledgers").status_code in (401, 403)
    assert client.get("/api/score-ledgers/export").status_code in (401, 403)


def exported(client, **params):
    response = client.get("/api/score-ledgers/export", params={"month": "2026-10", **params})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    workbook = load_workbook(BytesIO(response.content))
    return workbook, list(workbook["积分明细"].values)


def test_export_all_pages_snapshot_and_numeric_zero(client, factory, settings, when):
    login(client, factory)
    for i in range(22):
        submit(factory, settings, when + timedelta(seconds=i), request(points=2))
    submit(factory, settings, when + timedelta(minutes=1), request(overrides={"a": 0}))
    with factory.begin() as db:
        db.get(Employee, "a").name = "调岗后新姓名"
        db.get(Department, "team").name = "调岗后新部门"
    workbook, rows = exported(client)
    assert len(rows) == 24  # 表头 + 23 条，超过页面的 20 条。
    assert rows[1][2:4] == ("张三", "研发 / 软件 / 平台")
    assert rows[1][4:8] == (5, 104, 0, "手动覆盖")
    assert rows[1][9] == "2026-10-06 14:01:00"
    assert rows[1][10:12] == ("管理员", "有效")
    assert [row[0] for row in rows[1:]] == list(range(1, 24))
    assert workbook["积分明细"].freeze_panes == "A2"
    assert workbook["积分明细"].auto_filter.ref == "A1:M24"
    workbook.close()


def test_export_filters_cancellation_and_operator_scope(client, factory, settings, when):
    batch = submit(factory, settings, when, request(person_ids=["a", "b", "c"],
                   operation="minus", points=3, recipients={"person_ids": ["admin", "operator"]}), user="operator")
    submit(factory, settings, when, request(person_ids=["b"]))
    submit(factory, settings, datetime(2026, 11, 1), request(person_ids=["a"]), user="operator")
    with factory.begin() as db:
        ledger = db.scalar(select(Ledger).where(Ledger.batch_id == batch, Ledger.employee_id == "a"))
        cancel_score(db, ledger, "operator", when + timedelta(minutes=1))
    login(client, factory, "operator")
    workbook, rows = exported(client)
    assert len(rows) == 4  # 多通知对象不扩展导出行数，管理员的批次也不导出。
    assert sorted(row[2] for row in rows[1:]) == sorted(["张三", "李四", "多部门员工"])
    workbook.close()
    workbook, rows = exported(client, department_id="rd", operation="minus", status="cancelled", q="张")
    assert len(rows) == 2
    assert rows[1][2] == "张三" and rows[1][11:13] == ("已作废", "2026-10-06 14:01:00")
    workbook.close()
    workbook, rows = exported(client, department_id="rd", operation="minus", status="valid")
    assert len(rows) == 2 and rows[1][2] == "多部门员工"
    assert rows[1][3] == "研发 / 软件 / 平台；销售 / 华东"
    workbook.close()
    workbook, rows = exported(client, month="2026-11")
    assert len(rows) == 2
    workbook.close()


def test_export_text_is_not_excel_formula(client, factory, settings, when):
    with factory.begin() as db:
        db.get(Employee, "a").name = '=HYPERLINK("https://example.com","姓名")'
    submit(factory, settings, when, request(reason='=1+1\n完整原因，逗号,引号"保持原样\t制表符\x01'))
    login(client, factory)
    workbook, rows = exported(client)
    sheet = workbook["积分明细"]
    assert sheet["C2"].data_type == sheet["I2"].data_type == "s"
    assert sheet["I2"].value == '=1+1\n完整原因，逗号,引号"保持原样\t制表符'
    assert sheet["E2"].data_type == "n" and sheet["E2"].value == 5
    workbook.close()


def test_export_auth_validation_and_empty_results(client, factory):
    assert client.get("/api/score-ledgers/export").status_code == 401
    login(client, factory, "operator")
    for params in ({"month": "2026-13"}, {"status": "bad"}, {"operation": "bad"}):
        assert client.get("/api/score-ledgers/export", params=params).status_code == 422
    workbook, rows = exported(client)
    assert len(rows) == 1  # 无匹配记录时仍可返回合法的空表。
    workbook.close()
    with factory.begin() as db:
        db.get(Employee, "operator").role = "none"
    assert client.get("/api/score-ledgers/export").status_code == 403
