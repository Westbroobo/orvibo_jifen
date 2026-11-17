"""Five-field cron in Beijing time; independent of directory schedules."""

from datetime import timezone
from zoneinfo import ZoneInfo

from croniter import croniter

from ..db import now_utc

BEIJING = ZoneInfo("Asia/Shanghai")


def validate_cron(expression):
    expression = " ".join(expression.strip().split())
    if len(expression.split()) != 5 or len(expression) > 100 or not croniter.is_valid(expression):
        raise ValueError("请输入有效的五字段 Cron：分 时 日 月 星期")
    # Reject impossible dates as well as syntactically invalid expressions.
    next_times(expression, count=1)
    return expression


def next_times(expression, when=None, count=3):
    when = when or now_utc()
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    try:
        iterator = croniter(expression, when.astimezone(BEIJING), max_years_between_matches=8)
        return [iterator.get_next(type(when)).astimezone(timezone.utc).replace(tzinfo=None) for _ in range(count)]
    except (ValueError, OverflowError, KeyError) as error:
        raise ValueError("Cron 无法计算有效的下次执行时间") from error
