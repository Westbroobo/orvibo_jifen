"""Worker progress check, independent of the API and Feishu event subprocess."""

import json
import os
import tempfile
import time
from pathlib import Path

HEALTH_FILE = Path(tempfile.gettempdir()) / "orvibo-jifen-worker-health.json"
MAX_PROGRESS_AGE = 180


class WorkerHealth:
    def __init__(self, path=HEALTH_FILE):
        self.path = path

    def record(self, *, database_ok):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"pid": os.getpid(), "updated_at": time.time(),
                                         "database_ok": database_ok}), encoding="utf-8")
        temporary.replace(self.path)

    def clear(self):
        self.path.unlink(missing_ok=True)


def check_health(path=HEALTH_FILE):
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - state["updated_at"]
        if not 0 <= age <= MAX_PROGRESS_AGE:
            return "worker 任务循环长时间未更新"
        if state["database_ok"] is not True:
            return "worker 数据库连接异常，正在重试"
    except (OSError, ValueError, KeyError, TypeError):
        return "worker 尚未就绪或已停止"
    return None


if __name__ == "__main__":
    error = check_health()
    if error:
        print(error)
        raise SystemExit(1)
    print("worker 正常")
