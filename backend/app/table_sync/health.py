"""Health of the isolated table-sync supervisor, separate from message delivery."""

import json
import os
import tempfile
import time
from pathlib import Path


HEALTH_FILE = Path(tempfile.gettempdir()) / "orvibo-jifen-table-sync-health.json"
MAX_PROGRESS_AGE = 90


class TableSyncHealth:
    def __init__(self, path=HEALTH_FILE):
        self.path = Path(path)

    def record(self, *, database_ok, run_id=None):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"pid": os.getpid(), "updated_at": time.time(),
                                         "database_ok": database_ok, "run_id": run_id}), encoding="utf-8")
        temporary.replace(self.path)

    def clear(self):
        self.path.unlink(missing_ok=True)
        self.path.with_suffix(".tmp").unlink(missing_ok=True)


def check_health(path=HEALTH_FILE):
    try:
        state = json.loads(Path(path).read_text(encoding="utf-8"))
        age = time.time() - state["updated_at"]
        if not 0 <= age <= MAX_PROGRESS_AGE:
            return "名单同步任务循环长时间未更新"
        if state["database_ok"] is not True:
            return "名单同步数据库连接异常"
    except (OSError, ValueError, KeyError, TypeError):
        return "名单同步服务尚未就绪或已停止"
    return None


if __name__ == "__main__":
    error = check_health()
    if error:
        print(error)
        raise SystemExit(1)
    print("名单同步服务正常")
