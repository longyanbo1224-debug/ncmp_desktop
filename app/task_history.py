"""任务执行历史持久化：记录最近 N 条任务结果，供首页摘要展示。

存储路径与 ``AppConfig`` 同目录（``task_history.json``），跨进程可见。
仅记录最近 20 条，避免无限增长。
"""
import json
from datetime import datetime
from pathlib import Path
from typing import List

from app.app_config import _default_config_path


class TaskHistory:
    """任务历史记录（与 AppConfig 同目录的 task_history.json）。"""

    MAX_RECORDS = 20

    def __init__(self) -> None:
        self._path: Path = _default_config_path().parent / "task_history.json"

    # ------------------------------------------------------------------
    # 对外
    # ------------------------------------------------------------------
    def record(self, success: bool, summary: str, detail: str = "") -> None:
        """追加一条记录；保留最近 MAX_RECORDS 条。"""
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "success": bool(success),
            "summary": summary,
            "detail": detail or "",
        }
        records = self._read_all()
        records.append(entry)
        if len(records) > self.MAX_RECORDS:
            records = records[-self.MAX_RECORDS:]
        self._write_all(records)

    def load_recent(self, n: int = 5) -> List[dict]:
        """读最近 n 条，新在前。"""
        if n <= 0:
            return []
        records = self._read_all()
        recent = records[-n:]
        recent.reverse()
        return recent

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _read_all(self) -> List[dict]:
        if not self._path.exists():
            return []
        try:
            with self._path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return [r for r in data if isinstance(r, dict)]
        except Exception:
            pass
        return []

    def _write_all(self, records: List[dict]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
