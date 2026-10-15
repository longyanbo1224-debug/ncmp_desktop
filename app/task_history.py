"""任务执行历史持久化。

存储路径与 ``AppConfig`` 同目录（``task_history.json``），跨进程可见。

存两份数据，因为两个消费方要的东西不一样：

- ``records``：最近若干条**明细**，首页的记录表要显示具体时间和失败原因
- ``daily``：按**天**聚合的结论，连续打卡图要的是"那天到底跑没跑成"

早期版本只存 20 条明细，而且是一天跑三次就占三条——既画不出一年格子图，
也没法回答"这个月坚持得怎么样"。
"""
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List

from app.app_config import _default_config_path

#: 保留多少条明细（给记录表用）
MAX_RECORDS = 50

#: 保留多少天的按天结论（一年多一点，够画 53 周格子图）
MAX_DAYS = 400

#: 按天结论的取值
DAY_SUCCESS = "success"
DAY_FAILED = "failed"
DAY_NONE = "none"


class TaskHistory:
    """任务历史记录（与 AppConfig 同目录的 task_history.json）。"""

    #: 兼容旧名字：早期版本叫 MAX_RECORDS，语义是"总条数上限"
    MAX_RECORDS = MAX_RECORDS

    def __init__(self) -> None:
        self._path: Path = _default_config_path().parent / "task_history.json"

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def record(self, success: bool, summary: str, detail: str = "") -> None:
        """追加一条记录，并更新当天的结论。"""
        now = datetime.now()
        entry = {
            "ts": now.isoformat(timespec="seconds"),
            "success": bool(success),
            "summary": summary,
            "detail": detail or "",
        }
        data = self._read_all()
        records: List[dict] = data["records"]
        records.append(entry)
        if len(records) > MAX_RECORDS:
            records = records[-MAX_RECORDS:]

        daily: Dict[str, str] = data["daily"]
        self._merge_day(daily, now.date().isoformat(), bool(success))
        daily = self._trim_days(daily)

        self._write_all({"records": records, "daily": daily})

    @staticmethod
    def _merge_day(daily: Dict[str, str], day: str, success: bool) -> None:
        """把一次执行并进当天的结论。

        一天可能跑多次（手动补跑、定时失败后重试）。**成功优先**：
        这一天只要成功跑成过一次，就算这天是绿的——用户关心的是
        "今天任务做完了没有"，而不是"第一次有没有失败"。
        """
        prev = daily.get(day, DAY_NONE)
        if success:
            daily[day] = DAY_SUCCESS
        elif prev != DAY_SUCCESS:
            daily[day] = DAY_FAILED

    @staticmethod
    def _trim_days(daily: Dict[str, str]) -> Dict[str, str]:
        """只保留最近 MAX_DAYS 天，避免文件无限增长。"""
        if len(daily) <= MAX_DAYS:
            return daily
        keep = sorted(daily.keys())[-MAX_DAYS:]
        return {k: daily[k] for k in keep}

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    def load_recent(self, n: int = 5) -> List[dict]:
        """读最近 n 条明细，新在前。"""
        if n <= 0:
            return []
        records = self._read_all()["records"]
        recent = records[-n:]
        recent.reverse()
        return recent

    def daily_summary(self, days: int = 371) -> List[tuple]:
        """读最近 ``days`` 天的按天结论。

        :returns: ``[(date 对象, "success"/"failed"/"none"), ...]``，从旧到新，
            含没有记录的日子（结论为 ``none``）。
        """
        if days <= 0:
            return []
        daily = self._read_all()["daily"]
        today = date.today()
        out = []
        for offset in range(days - 1, -1, -1):
            day = today - timedelta(days=offset)
            out.append((day, daily.get(day.isoformat(), DAY_NONE)))
        return out

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _read_all(self) -> Dict:
        """读整份数据；兼容早期的"纯列表"格式。"""
        empty = {"records": [], "daily": {}}
        if not self._path.exists():
            return empty
        try:
            with self._path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return empty

        # 旧格式：整个文件就是一个记录列表
        if isinstance(data, list):
            records = [r for r in data if isinstance(r, dict)]
            return {"records": records, "daily": self._rebuild_daily(records)}

        if not isinstance(data, dict):
            return empty
        records = [r for r in data.get("records", []) if isinstance(r, dict)]
        daily = data.get("daily")
        if not isinstance(daily, dict):
            daily = self._rebuild_daily(records)
        return {"records": records,
                "daily": {str(k): str(v) for k, v in daily.items()}}

    @staticmethod
    def _rebuild_daily(records: List[dict]) -> Dict[str, str]:
        """从明细重建按天结论（旧格式迁移用）。"""
        daily: Dict[str, str] = {}
        for entry in records:
            ts = str(entry.get("ts", "") or "")
            try:
                day = datetime.fromisoformat(ts).date().isoformat()
            except Exception:
                continue
            TaskHistory._merge_day(daily, day, bool(entry.get("success")))
        return daily

    def _write_all(self, data: Dict) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
