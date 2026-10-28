"""曲目账本：今天评了哪几首、每首几分、留下了什么批注。

``TaskHistory`` 记的是"这一次任务成没成"（一次一条），回答不了"上周三我给
哪首歌打了四分、写了什么"。批注是要回看、要导出、要统计的东西，所以单独存
一份按曲目的明细，落地在同一目录的 ``track_log.json``。

为什么按天去重：同一天可能跑好几次（手动补跑、定时失败重试），但账本上
用户想看的是"这一天最终的结论"，不是同一首歌出现三遍。
"""
import json
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from app.app_config import _default_config_path

#: 保留多少天的明细（一年多一点，和打卡格子图对齐）
MAX_DAYS = 400

#: 曲目状态（与界面用词表一致，见 docs/DESIGN.md §6）
STATE_SUBMITTED = "submitted"
STATE_SKIPPED = "skipped"
STATE_FAILED = "failed"

STATE_LABEL = {
    STATE_SUBMITTED: "已提交",
    STATE_SKIPPED: "跳过",
    STATE_FAILED: "失败",
}


class TrackLog:
    """按天保存的曲目明细（同目录 ``track_log.json``）。"""

    def __init__(self, path: Optional[Path] = None) -> None:
        #: 允许注入路径：测试要写到临时文件，不能碰用户真实的账本
        self._path: Path = Path(path) if path is not None else (
            _default_config_path().parent / "track_log.json")

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def record(self, song: str, artist: str = "", score: str = "",
               note: str = "", state: str = STATE_SUBMITTED,
               day: Optional[str] = None) -> None:
        """记一首歌。同一天同名曲目**覆盖**，不追加。"""
        song = str(song or "").strip()
        if not song:
            return
        day = day or date.today().isoformat()
        now = datetime.now().isoformat(timespec="seconds")
        data = self._read()
        entries: List[dict] = data.setdefault(day, [])
        entry = {
            "song": song,
            "artist": str(artist or "").strip(),
            "score": str(score or "").strip(),
            "note": str(note or "").strip(),
            "state": state if state in STATE_LABEL else STATE_SUBMITTED,
            "ts": now,
        }
        for index, existing in enumerate(entries):
            if existing.get("song") == song:
                # 保留原有的批注：后一次没写批注不等于要抹掉前一次写的
                if not entry["note"]:
                    entry["note"] = str(existing.get("note") or "")
                entries[index] = entry
                break
        else:
            entries.append(entry)
        self._trim(data)
        self._write(data)

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    def day(self, day: Optional[str] = None) -> List[dict]:
        """某天的曲目；默认今天。"""
        day = day or date.today().isoformat()
        return list(self._read().get(day, []))

    def days(self) -> List[str]:
        """有记录的日子，倒序。"""
        return sorted(self._read().keys(), reverse=True)

    def recent(self, limit: int = 200) -> List[dict]:
        """最近的曲目明细，新的在前，每项带 ``day`` 字段。"""
        result: List[dict] = []
        data = self._read()
        for day in sorted(data.keys(), reverse=True):
            for entry in reversed(data[day]):
                item = dict(entry)
                item["day"] = day
                result.append(item)
                if len(result) >= limit:
                    return result
        return result

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------
    def stats(self) -> Dict[str, object]:
        """账本摘要：累计曲目、批注数、档位分布、按月档位中位数。"""
        data = self._read()
        total = 0
        notes = 0
        tiers: Dict[str, int] = {}
        monthly: Dict[str, List[int]] = {}
        for day, entries in data.items():
            month = day[:7]
            for entry in entries:
                total += 1
                if entry.get("note"):
                    notes += 1
                try:
                    value = int(str(entry.get("score") or "").strip())
                except (TypeError, ValueError):
                    continue
                tiers[str(value)] = tiers.get(str(value), 0) + 1
                monthly.setdefault(month, []).append(value)
        medians = {month: _median(values) for month, values in monthly.items()}
        return {
            "total": total,
            "notes": notes,
            "tiers": tiers,
            "medians": medians,
        }

    # ------------------------------------------------------------------
    # 导出
    # ------------------------------------------------------------------
    def export_markdown(self, day: Optional[str] = None) -> str:
        """把某天导出成一页 Markdown（"今日内页"）。

        这是"值班簿"这个比喻的兑现：跑完能产出一份可以贴出去的东西。
        """
        day = day or date.today().isoformat()
        entries = self.day(day)
        if not entries:
            return f"# {day}\n\n今天还没有评过曲子。\n"
        try:
            stamp = datetime.fromisoformat(day).strftime("%Y年%-m月%-d日")
        except ValueError:
            stamp = day
        lines = [f"# {stamp} · 音乐合伙人", ""]
        tiers = [e.get("score") for e in entries if e.get("score")]
        head = f"共 {len(entries)} 首"
        if tiers:
            head += f"，档位 {' / '.join(str(t) for t in tiers)}"
        lines.append(head)
        lines.append("")
        for index, entry in enumerate(entries, 1):
            score = entry.get("score") or "–"
            artist = entry.get("artist") or ""
            name = entry.get("song") or ""
            title = f"{index:02d}. {name}"
            if artist:
                title += f" — {artist}"
            lines.append(f"{title}　{score}⁄5")
            note = entry.get("note") or ""
            if note:
                lines.append(f"> {note}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _read(self) -> Dict[str, List[dict]]:
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def _write(self, data: Dict[str, List[dict]]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=1)
            tmp.replace(self._path)
        except Exception:
            pass

    @staticmethod
    def _trim(data: Dict[str, List[dict]]) -> None:
        """只保留最近的 MAX_DAYS 天，避免文件无限增长。"""
        if len(data) <= MAX_DAYS:
            return
        for day in sorted(data.keys())[: len(data) - MAX_DAYS]:
            data.pop(day, None)


def _median(values: List[int]) -> int:
    """整数中位数（向下取整，够画曲线了）。"""
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2
