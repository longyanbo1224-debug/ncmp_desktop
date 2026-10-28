"""账本页 —— 这个账号在音乐合伙人里的"账"。

三件事：
1. 累计：连续多少天、评了多少首、留下多少条批注；
2. 口味曲线（D2）：**你自己**的评分分布，而不是完成率；
3. 最近的曲目与批注，可回看、可导出。

完成率那套数字首页已经有了，这里刻意不重复——用户来这里是想看"我评过什么"。
"""
from datetime import date, timedelta
from typing import List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from app.task_history import TaskHistory
from app.track_log import TrackLog
from app.ui import theme
from app.ui.widgets.streak_grid import StreakGrid
from app.ui.widgets.track_list import TrackList

#: 口味曲线里的档位，从高到低
_TIERS = ("5", "4", "3", "2", "1")

#: 最近曲目展示条数
_RECENT_LIMIT = 40


class LedgerPage(QWidget):
    """账本页。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.PAGE_MARGIN, theme.PAGE_MARGIN,
                                 theme.PAGE_MARGIN, theme.PAGE_MARGIN)
        outer.setSpacing(theme.SP_4)

        title = QLabel("记录")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        self._subtitle = QLabel("你在这个账号上评过的曲子与留下的话。")
        self._subtitle.setObjectName("subtitle")
        outer.addWidget(self._subtitle)

        # ---- 三个数 ----
        numbers = QHBoxLayout()
        numbers.setSpacing(theme.SP_4)
        self._stat_streak = self._stat_block("连续", "0 天")
        self._stat_tracks = self._stat_block("累计曲目", "0 首")
        self._stat_notes = self._stat_block("累计批注", "0 条")
        for block in (self._stat_streak, self._stat_tracks, self._stat_notes):
            numbers.addWidget(block)
        numbers.addStretch(1)
        outer.addLayout(numbers)

        # ---- 合伙人积分/等级（有数据才显示）----
        # 数字来自任务结束后缓存的那次查询；拿不到就整块隐藏，
        # 不填 0 假装有收益。
        self._points_title = QLabel("合伙人")
        self._points_title.setObjectName("sectionHeading")
        outer.addWidget(self._points_title)
        self._points_box = QWidget()
        self._points_lay = QVBoxLayout(self._points_box)
        self._points_lay.setContentsMargins(0, 0, 0, 0)
        self._points_lay.setSpacing(theme.SP_1 + 2)
        outer.addWidget(self._points_box)

        # ---- 口味曲线 ----
        curve_title = QLabel("口味曲线")
        curve_title.setObjectName("sectionHeading")
        outer.addWidget(curve_title)
        self._curve_hint = QLabel("每一档你给过多少首。")
        self._curve_hint.setObjectName("captionText")
        outer.addWidget(self._curve_hint)
        self._curve_box = QWidget()
        self._curve_lay = QVBoxLayout(self._curve_box)
        self._curve_lay.setContentsMargins(0, 0, 0, 0)
        self._curve_lay.setSpacing(theme.SP_1 + 2)
        outer.addWidget(self._curve_box)
        self._curve_empty = QLabel("还没有评分记录。跑一次之后，这里会长出你的口味曲线。")
        self._curve_empty.setObjectName("emptyState")
        outer.addWidget(self._curve_empty)

        # ---- 打卡格子 ----
        grid_title = QLabel("坚持")
        grid_title.setObjectName("sectionHeading")
        outer.addWidget(grid_title)
        self._grid = StreakGrid()
        # 不要给 StreakGrid 设最大/最小高度：它自带 setFixedSize，
        # 高度里已经算好了底部图例（成功/失败/没跑）的位置。
        # 之前这里加过 setMinimumHeight(120)，把固定高度压小，图例就被下面的
        # 「最近评过的曲子」标题盖住了。
        outer.addWidget(self._grid)

        # ---- 最近曲目 ----
        recent_title = QLabel("最近评过的曲子")
        recent_title.setObjectName("sectionHeading")
        outer.addWidget(recent_title)
        self._recent = TrackList()
        outer.addWidget(self._recent, 1)

    def _stat_block(self, label: str, value: str) -> QWidget:
        # 不做卡片：三个数直接坐在页面底色上（手机端记录页同样处理）
        block = QWidget()
        lay = QVBoxLayout(block)
        lay.setContentsMargins(0, 0, theme.SP_5, 0)
        lay.setSpacing(theme.SP_1)
        caption = QLabel(label)
        caption.setObjectName("captionText")
        number = QLabel(value)
        number.setObjectName("pageTitle")
        lay.addWidget(caption)
        lay.addWidget(number)
        block._value_label = number  # 供 refresh 更新
        block.setMinimumWidth(140)
        return block

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """从 TaskHistory + TrackLog 重新读一遍。"""
        days: List[Tuple[date, str]] = []
        try:
            days = TaskHistory().daily_summary(53 * 7)
        except Exception:
            days = []

        stats = {}
        try:
            stats = TrackLog().stats()
        except Exception:
            stats = {}

        total = int(stats.get("total", 0) or 0)
        notes = int(stats.get("notes", 0) or 0)
        streak = _streak_days(days)

        self._stat_streak._value_label.setText(f"{streak} 天")
        self._stat_tracks._value_label.setText(f"{total} 首")
        self._stat_notes._value_label.setText(f"{notes} 条")

        self._render_curve(stats.get("tiers") or {}, total)

        self._render_points()

        try:
            self._grid.set_days(days)
        except Exception:
            pass

        self._render_recent()

        if total:
            self._subtitle.setText(
                f"累计评过 {total} 首，其中 {notes} 首留下了批注。")
        else:
            self._subtitle.setText("你在这个账号上评过的曲子与留下的话。")

    def _render_curve(self, tiers: dict, total: int) -> None:
        while self._curve_lay.count():
            item = self._curve_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        has_data = any(int(tiers.get(tier, 0) or 0) > 0 for tier in _TIERS)
        self._curve_box.setVisible(has_data)
        self._curve_empty.setVisible(not has_data)
        if not has_data:
            return

        peak = max(int(tiers.get(tier, 0) or 0) for tier in _TIERS) or 1
        for tier in _TIERS:
            count = int(tiers.get(tier, 0) or 0)
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(theme.SP_3)

            name = QLabel(f"{tier} 分")
            name.setObjectName("dataTextMuted")
            name.setFixedWidth(38)
            lay.addWidget(name)

            bar = QFrame()
            bar.setFixedHeight(10)
            bar.setStyleSheet(
                f"background-color: {_tier_color(tier)}; border: none;")
            share = int(round(count / peak * 100)) if count else 0
            # 用拉伸比例画条：左边是条，右边是空，加起来永远 100
            lay.addWidget(bar, max(share, 1) if count else 0)
            lay.addStretch(100 - share if count else 100)

            percent = int(round(count / total * 100)) if total else 0
            value = QLabel(f"{count} 首 · {percent}%")
            value.setObjectName("dataTextMuted")
            value.setFixedWidth(88)
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lay.addWidget(value)

            self._curve_lay.addWidget(row)

    def _render_points(self) -> None:
        """合伙人积分/等级：有缓存才显示，没有就整块隐藏。"""
        while self._points_lay.count():
            item = self._points_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        try:
            from app import partner_points_store
            points = partner_points_store.load()
        except Exception:
            points = {}

        has_data = bool(points)
        self._points_title.setVisible(has_data)
        self._points_box.setVisible(has_data)
        if not has_data:
            return

        for label, value in points.items():
            self._points_lay.addWidget(self._points_row(label, value))

        # 称号：当前档 + 距下一档还差多少 + 完整阈值表（用户提供的一手规则）
        try:
            from core import partner_points
            info = partner_points.title_for(partner_points.score_of(points))
        except Exception:
            return
        if info.get("label"):
            self._points_lay.addWidget(self._points_row("当前称号", str(info["label"])))
        if info.get("next_label") and info.get("gap") is not None:
            self._points_lay.addWidget(self._points_row(
                "距下一档", f"{info['next_label']}（还差 {info['gap']} 分）"))
        for threshold, name in info.get("table") or ():
            self._points_lay.addWidget(self._points_row(f"{threshold} 分", name))

    def _points_row(self, label: str, value: str) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SP_3)
        name = QLabel(str(label))
        name.setObjectName("captionText")
        name.setFixedWidth(88)
        lay.addWidget(name)
        number = QLabel(str(value))
        number.setObjectName("dataText")
        lay.addWidget(number)
        lay.addStretch(1)
        return row

    def _render_recent(self) -> None:
        self._recent.clear()
        try:
            items = TrackLog().recent(_RECENT_LIMIT)
        except Exception:
            items = []
        for item in items:
            meta = " · ".join(part for part in (
                str(item.get("artist") or ""),
                _short_day(str(item.get("day") or "")),
            ) if part)
            self._recent.add(
                str(item.get("song") or ""),
                meta=meta,
                score=str(item.get("score") or ""),
                state="done",
                note=str(item.get("note") or ""),
            )


def _tier_color(tier: str) -> str:
    """档位 → 条的颜色。和曲目行的档位标同一条规则（设计文档 §4.1）。"""
    if tier in ("5", "4"):
        return theme.INK
    if tier == "3":
        return theme.MUTED
    return theme.FAILED


def _short_day(day: str) -> str:
    """2026-10-28 → 10-28。解析失败原样返回。"""
    try:
        return date.fromisoformat(day).strftime("%m-%d")
    except Exception:
        return day


def _streak_days(days: List[Tuple[date, str]]) -> int:
    """从今天往回数连续成功的天数。

    今天还没跑时从昨天开始数——否则每天凌晨打开账本都显示"连续 0 天"，
    而用户实际上一天没漏。
    """
    if not days:
        return 0
    mapping = {day: status for day, status in days}
    today = date.today()
    cursor = today
    if mapping.get(cursor) != "success":
        cursor = today - timedelta(days=1)
    streak = 0
    while mapping.get(cursor) == "success":
        streak += 1
        cursor -= timedelta(days=1)
    return streak
