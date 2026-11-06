"""当天额外额度已用完的本地标记。

服务端返回 405「今日没有更多可评定歌曲」后，额外清单接口仍可能列出待评作品。
没有这个标记时，每次重跑都要先等 15–20 秒、再发一次评分请求才能确认额度已满。

标记按 ``(账号, 日期, taskId)`` 记录：
- 换天 / 换账号后 taskId 不同，旧标记自然失效；
- 同一天同一个 taskId 已经确认过额度用完，下次执行直接跳过额外阶段，
  不再等待、不再发评分请求。

文件损坏或写不进去都当成「没有标记」，不影响任务。
"""
import json
import os
from datetime import date
from pathlib import Path
from typing import Dict, Optional


def _default_path() -> Path:
    return Path(os.path.expanduser("~")) / ".ncmp_desktop" / "quota_exhausted.json"


class QuotaState:
    """本地记录「今天额外额度已用完」（同目录 ``quota_exhausted.json``）。"""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path is not None else _default_path()

    def exhausted(self, account: str, task_id, day: Optional[str] = None) -> bool:
        """这个账号 + 今天的这个任务是否已经确认过「额外额度用完」。"""
        task_key = str(task_id or "").strip()
        if not task_key or task_key.lower() in ("none", "null"):
            return False
        day = day or date.today().isoformat()
        item = self._read().get(str(account or ""))
        if not isinstance(item, dict):
            return False
        return (str(item.get("date") or "") == day
                and str(item.get("task_id") or "") == task_key)

    def exhausted_today(self, day: Optional[str] = None) -> bool:
        """今天是否有任意账号确认过「额外额度用完」。

        界面刷新时拿不到当前账号/taskId，用日期做一次宽松判断：
        只要今天已经确认过，就把服务端仍标待评的额外曲目显示为今日已完成。
        """
        day = day or date.today().isoformat()
        data = self._read()
        return any(isinstance(item, dict)
                   and str(item.get("date") or "") == day
                   for item in data.values())

    def mark(self, account: str, task_id, day: Optional[str] = None) -> None:
        """记下今天这个任务已经确认过额度用完。写失败静默忽略。"""
        task_key = str(task_id or "").strip()
        if not task_key or task_key.lower() in ("none", "null"):
            return
        day = day or date.today().isoformat()
        data = self._read()
        data[str(account or "")] = {"date": day, "task_id": task_key}
        # 只保留今天的条目，防止文件无限增长
        data = {key: value for key, value in data.items()
                if isinstance(value, dict) and str(value.get("date") or "") == day}
        self._write(data)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _read(self) -> Dict:
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def _write(self, data: Dict) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=1)
            tmp.replace(self._path)
        except Exception:
            pass
