"""按记账快照查询逐人流水；MySQL 8 在数据库内筛选及分页。"""
import json
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from . import auth
from .adjustments import month_at
from .db import get_db, now_utc

router = APIRouter(prefix="/api/score-ledgers", tags=["score-ledgers"])
PAGE_SIZE = 20

# JSON_TABLE 将一批快照按记分员工展开，与唯一的 batch_id/employee_id 流水对应。
BASE = """
SELECT l.id, l.batch_id, l.employee_id, l.month, l.delta,
       l.before_total, l.final_total, l.override_total,
       p.person_name, p.avatar_url,
       JSON_EXTRACT(b.snapshot, CONCAT('$.rows[', p.row_index - 1, '].person.paths')) AS paths,
       JSON_UNQUOTE(JSON_EXTRACT(b.snapshot, '$.reason')) AS reason,
       JSON_UNQUOTE(JSON_EXTRACT(b.snapshot, '$.operator_name')) AS operator_name,
       b.created_at, c.cancelled_at
FROM orvibo_jifen_batches b
JOIN JSON_TABLE(b.snapshot, '$.rows[*]' COLUMNS (
    row_index FOR ORDINALITY,
    person_id VARCHAR(36) PATH '$.person.id',
    person_name VARCHAR(200) PATH '$.person.name',
    avatar_url TEXT PATH '$.person.avatar_url'
)) AS p ON TRUE
JOIN orvibo_jifen_ledger l ON l.batch_id = b.id
    AND l.employee_id = p.person_id COLLATE utf8mb4_unicode_ci
LEFT JOIN orvibo_jifen_ledger_cancellations c ON c.ledger_id = l.id
WHERE b.month = :month AND (:is_admin = 1 OR b.operator_id = :operator_id)
"""


def decode_paths(value):
    return json.loads(value) if isinstance(value, str) else value or []


def query_ledgers(db, user, month, q="", department_id="", operation="all", status="all", page=1):
    params = {"month": month, "is_admin": int(user.role == "admin"), "operator_id": user.id,
              "q": q.strip(), "department_id": department_id}
    conditions = ["LOCATE(LOWER(:q), LOWER(person_name)) > 0"]
    if department_id:
        conditions.append("JSON_CONTAINS(JSON_EXTRACT(paths, '$[*].ids[*]'), JSON_QUOTE(:department_id))")
    if operation != "all":
        conditions.append("delta > 0" if operation == "plus" else "delta < 0")
    if status != "all":
        conditions.append("cancelled_at IS NULL" if status == "valid" else "cancelled_at IS NOT NULL")
    filtered = f"WITH scoped AS ({BASE}), filtered AS (SELECT * FROM scoped WHERE {' AND '.join(conditions)})"
    summary = db.execute(text(filtered + """
        SELECT COUNT(*) AS total,
               COALESCE(SUM(CASE WHEN cancelled_at IS NULL AND delta > 0 THEN delta ELSE 0 END), 0) AS plus_total,
               COALESCE(SUM(CASE WHEN cancelled_at IS NULL AND delta < 0 THEN delta ELSE 0 END), 0) AS minus_total
        FROM filtered
    """), params).mappings().one()
    total = int(summary["total"])
    page = min(page, max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE))
    records = db.execute(text(filtered + """
        SELECT * FROM filtered ORDER BY created_at DESC, id ASC LIMIT :limit OFFSET :offset
    """), {**params, "limit": PAGE_SIZE, "offset": (page - 1) * PAGE_SIZE}).mappings()
    items = []
    for record in records:
        row = dict(record)
        row["paths"] = decode_paths(row["paths"])
        row["cancelled"] = row["cancelled_at"] is not None
        for field in ("created_at", "cancelled_at"):
            row[field] = row[field].isoformat() + "Z" if row[field] else None
        items.append(row)

    # 只取去重后的历史路径，不把整个月的人员流水加载到应用内。
    historical_paths = db.execute(text(f"""WITH scoped AS ({BASE})
        SELECT CAST(paths AS CHAR) AS paths, MAX(created_at) AS latest
        FROM scoped GROUP BY CAST(paths AS CHAR) ORDER BY latest DESC, paths
    """), params).mappings()
    departments = {}
    for record in historical_paths:
        for path in decode_paths(record["paths"]):
            ids, names = path["ids"], path["names"]
            for index, department in enumerate(ids):
                departments.setdefault(department, {
                    "id": department, "name": names[index], "parent_id": ids[index - 1] if index else "0",
                    "path_ids": ids[:index + 1], "path_names": names[:index + 1],
                })
    return {"items": items, "total": total, "page": page, "page_size": PAGE_SIZE, "month": month,
            "summary": {"plus_total": int(summary["plus_total"]), "minus_total": int(summary["minus_total"])},
            "departments": list(departments.values())}


@router.get("")
def score_ledgers(month: str | None = Query(None, pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$"),
                  q: str = Query("", max_length=200), department_id: str = Query("", max_length=100),
                  operation: Literal["all", "plus", "minus"] = "all",
                  status: Literal["all", "valid", "cancelled"] = "all",
                  page: int = Query(1, ge=1), user=Depends(auth.operator), db=Depends(get_db)):
    return query_ledgers(db, user, month or month_at(now_utc()), q, department_id, operation, status, page)
