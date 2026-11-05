"""本地评分账本：记下服务端确认收下的评分，避免同一任务重复提交。

服务端的 ``completed`` 仍是"评过没有"的主依据；这个账本只用来补一个漏：
任务列表偶尔仍把刚评过的歌标成未完成（标记滞后 / 同任务重跑）。命中账本
只跳过重复提交，绝不反过来判定"没评过"。

按 ``(账号, taskId)`` 分组：换天、换账号后 taskId 不同，旧记录自然不命中；
写入时顺手裁掉 48 小时前的条目。文件损坏或写不进去都当成空账本，不影响任务。
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

#: 旧条目保留时长。taskId 已经做了分组，这里只是防止文件无限增长。
_MAX_AGE = timedelta(hours=48)


def _default_path() -> Path:
    return Path(os.path.expanduser("~")) / ".ncmp_desktop" / "rated_works.json"


class RatingLedger:
    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path is not None else _default_path()

    def score(self, account: str, task_id: str, work_id) -> Optional[str]:
        """这本作品在本任务里是否已评过；评过返回当时的分数，否则 None。"""
        works = self._task_entries(self._read(), account, task_id)
        item = works.get(str(work_id))
        if not isinstance(item, dict):
            return None
        score = str(item.get("score") or "").strip()
        return score or None

    def mark(self, account: str, task_id: str, work_id, score: str) -> None:
        """记一次服务端确认收下的评分。写失败静默忽略。"""
        data = self._read()
        account_key = str(account or "")
        tasks = data.get(account_key)
        if not isinstance(tasks, dict):
            tasks = {}
            data[account_key] = tasks
        task_key = str(task_id)
        works = tasks.get(task_key)
        if not isinstance(works, dict):
            works = {}
            tasks[task_key] = works
        works[str(work_id)] = {
            "score": str(score or ""),
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
        self._prune(tasks)
        self._write(data)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    @staticmethod
    def _task_entries(data: Dict, account: str, task_id: str) -> Dict:
        tasks = data.get(str(account or ""))
        if not isinstance(tasks, dict):
            return {}
        works = tasks.get(str(task_id))
        return works if isinstance(works, dict) else {}

    @staticmethod
    def _prune(tasks: Dict) -> None:
        """删掉 48 小时前的条目；空掉的任务分组一起清理。"""
        cutoff = datetime.now() - _MAX_AGE
        for task_id in list(tasks):
            works = tasks.get(task_id)
            if not isinstance(works, dict):
                tasks.pop(task_id, None)
                continue
            for work_id in list(works):
                item = works.get(work_id)
                ts = ""
                if isinstance(item, dict):
                    ts = str(item.get("ts") or "")
                try:
                    fresh = datetime.fromisoformat(ts) >= cutoff
                except ValueError:
                    fresh = False
                if not fresh:
                    works.pop(work_id, None)
            if not works:
                tasks.pop(task_id, None)

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
