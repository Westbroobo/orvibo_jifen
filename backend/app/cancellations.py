"""Void a scoring entry once and replay effective entries without changing snapshots."""

from fastapi import HTTPException
from sqlalchemy import select

from .models import Balance, Batch, Ledger, LedgerCancellation


def cancel_score(db, ledger, actor_id, when, *, source="recall"):
    # Caller holds the same system-state transaction lock as scoring writers.
    if db.get(LedgerCancellation, ledger.id):
        return False
    balance = db.get(Balance, (ledger.employee_id, ledger.month))
    if not balance:
        raise HTTPException(409, "积分余额缺失，请核实这笔操作的记录")
    entries = db.execute(select(Ledger, Batch).outerjoin(Batch, Ledger.batch_id == Batch.id).where(
        Ledger.employee_id == ledger.employee_id, Ledger.month == ledger.month)).all()
    if any(batch is None for _, batch in entries):
        raise HTTPException(409, "积分流水关联批次缺失，请核实本月记录")
    cancelled_ids = set(db.scalars(select(LedgerCancellation.ledger_id).join(
        Ledger, LedgerCancellation.ledger_id == Ledger.id).where(
        Ledger.employee_id == ledger.employee_id, Ledger.month == ledger.month)))
    cancelled_ids.add(ledger.id)

    def sequence(entry):
        item, batch = entry
        # Snapshot versions preserve commit order even when MySQL timestamps
        # round two or more commits to the same second.
        row = next(row for row in batch.snapshot["rows"] if row["person"]["id"] == item.employee_id)
        return row["balance_version"], batch.created_at, item.id

    total = 60
    for item, _ in sorted(entries, key=sequence):
        if item.id not in cancelled_ids:
            total = item.override_total if item.override_total is not None else total + item.delta
    if abs(total) > 2_000_000_000:
        raise HTTPException(409, "作废后总分超出整数存储范围，请先核实本月积分")
    db.add(LedgerCancellation(ledger_id=ledger.id, actor_id=actor_id, cancelled_at=when,
                              before_balance=balance.total, after_balance=total, source=source))
    balance.total = total
    balance.version += 1  # Old previews expire even when a later override keeps the same total.
    db.flush()
    return True
