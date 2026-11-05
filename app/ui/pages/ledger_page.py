"""账本页 —— 这个账号在音乐合伙人里的"账"。

三件事：
1. 累计：连续多少天、评了多少首、留下多少条批注；
2. 口味曲线（D2）：**你自己**的评分分布，而不是完成率；
3. 最近的曲目与批注，可回看、可导出。

完成率那套数字首页已经有了，这里刻意不重复——用户来这里是想看"我评过什么"。
"""
from datetime import date, datetime, timedelta
from typing import List, Tuple

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QToolButton,
    QVBoxLayout, QWidget,
)

from app.task_history import TaskHistory
from app.track_log import TrackLog
from app.ui import theme
from app.ui.widgets.track_list import TrackList


class _PointsWorker(QThread):
    """在后台查一次积分/等级。

    界面线程不能直接联网——查询慢的时候整页会卡住。
    """

    done = Signal(dict)

    def run(self) -> None:  # noqa: D401
        points = {}
        try:
            import requests

            from app.cookie_store import CookieStore
            from core.partner_points import fetch_points
            from core.utils.logger import Logger

            music_u, csrf, _ = CookieStore().load()
            if music_u and csrf:
                session = requests.Session()
                session.cookies.set("MUSIC_U", music_u)
                session.cookies.set("__csrf", csrf)
                points = fetch_points(session, Logger()) or {}
        except Exception:
            points = {}
        self.done.emit(points)

#: 口味曲线里的档位，从高到低
_TIERS = ("5", "4", "3", "2", "1")

#: 最近曲目展示条数（与手机端一致）
_RECENT_LIMIT = 30

#: 「执行情况」最多读多少条（与手机端的 800 条对齐）
_HISTORY_LIMIT = 800

_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


class LedgerPage(QWidget):
    """账本页。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._expanded_days = set()
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # 整页放进滚动区：最近曲目展开后内容会比窗口高，
        # 不滚的话会去挤上面的打卡格子图（图例被压没）。
        page = QVBoxLayout(self)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        scroll.setWidget(content)
        page.addWidget(scroll)
        #: 供「查看全部」跳转后滚到执行情况
        self._scroll = scroll

        outer = QVBoxLayout(content)
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
        # 标题行常显：即使还没数据，也能手动点「刷新」去查一次。
        self._points_header = QWidget()
        head = QHBoxLayout(self._points_header)
        head.setContentsMargins(0, 0, 0, 0)
        self._points_title = QLabel("合伙人")
        self._points_title.setObjectName("sectionHeading")
        head.addWidget(self._points_title)
        head.addStretch(1)
        self._points_refresh = QPushButton("刷新")
        self._points_refresh.setObjectName("textButton")
        self._points_refresh.clicked.connect(self.refresh_points)
        head.addWidget(self._points_refresh)
        outer.addWidget(self._points_header)

        self._points_empty = QLabel("点「刷新」获取积分与称号")
        self._points_empty.setObjectName("captionText")
        outer.addWidget(self._points_empty)

        self._points_box = QWidget()
        self._points_lay = QVBoxLayout(self._points_box)
        self._points_lay.setContentsMargins(0, 0, 0, 0)
        self._points_lay.setSpacing(theme.SP_1 + 2)
        outer.addWidget(self._points_box)
        self._points_worker = None

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

        # 打卡格子只在首页出现；记录页不再重复一张

        # ---- 最近曲目 ----
        # 最近曲目可能几十条，默认收起（与手机端一致），点标题右侧的按钮展开
        self._recent_expanded = False
        self._recent_header = QWidget()
        recent_head = QHBoxLayout(self._recent_header)
        recent_head.setContentsMargins(0, 0, 0, 0)
        self._recent_title = QLabel("最近评过的曲子")
        self._recent_title.setObjectName("sectionHeading")
        recent_head.addWidget(self._recent_title)
        recent_head.addStretch(1)
        self._recent_toggle = QToolButton()
        self._recent_toggle.setObjectName("textButton")
        self._recent_toggle.setText("展开 ▸")
        self._recent_toggle.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._recent_toggle.setCursor(Qt.PointingHandCursor)
        self._recent_toggle.clicked.connect(self.toggle_recent)
        recent_head.addWidget(self._recent_toggle)
        outer.addWidget(self._recent_header)

        self._recent = TrackList()
        self._recent.setVisible(False)
        # 展开时给一块能看的高度（约 5~6 行），不再和上面的内容抢空间
        self._recent.setMinimumHeight(300)
        outer.addWidget(self._recent)

        # ---- 执行情况（与手机端同构：一天一条，可展开）----
        self._history_section = QWidget()
        section_lay = QVBoxLayout(self._history_section)
        section_lay.setContentsMargins(0, 0, 0, 0)
        section_lay.setSpacing(theme.SP_1)
        history_title = QLabel("执行情况")
        history_title.setObjectName("sectionHeading")
        section_lay.addWidget(history_title)
        history_hint = QLabel("一天一条；同一天多次执行合并在这里，点开看明细")
        history_hint.setObjectName("captionText")
        section_lay.addWidget(history_hint)
        self._history_box = QWidget()
        self._history_lay = QVBoxLayout(self._history_box)
        self._history_lay.setContentsMargins(0, 0, 0, 0)
        self._history_lay.setSpacing(0)
        section_lay.addWidget(self._history_box)
        outer.addWidget(self._history_section)

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

        self._render_recent()
        self._render_history()

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

        scored = sum(int(tiers.get(tier, 0) or 0) for tier in _TIERS)
        unscored = max(0, int(total or 0) - scored)
        has_data = scored > 0
        self._curve_box.setVisible(has_data)
        self._curve_empty.setVisible(not has_data)
        # 档位百分比的分母只算「有分数」的曲目，否则会出现「3 分 7 首 · 35%」这种
        # 加起来不到 100% 的读数
        self._curve_hint.setText(
            f"每一档你给过多少首。另有 {unscored} 首已提交但没有分数记录"
            f"（跨设备评分或服务端未返回分数），未计入档位。"
            if unscored else "每一档你给过多少首。")
        if not has_data:
            # 有提交记录但一条分数都没有：别显示「还没有评分记录」，那句话是错的
            self._curve_empty.setText(
                f"有 {total} 首已提交记录，但服务端没有返回分数，暂时画不出档位分布。"
                if total else "还没有评分记录。跑一次之后，这里会长出你的口味曲线。")
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

            percent = int(round(count / scored * 100)) if scored else 0
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
        self._points_box.setVisible(has_data)
        self._points_empty.setVisible(not has_data)
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

    def refresh_points(self) -> None:
        """手动查一次积分/等级。

        查询走后台线程（界面线程不联网，慢的时候整页会卡住）；
        查到就写进缓存，再重绘这一块。
        """
        if self._points_worker is not None and self._points_worker.isRunning():
            return
        self._points_refresh.setEnabled(False)
        self._points_refresh.setText("刷新中…")
        self._points_worker = _PointsWorker(self)
        self._points_worker.done.connect(self._on_points_fetched)
        self._points_worker.start()

    def _on_points_fetched(self, points: dict) -> None:
        self._points_refresh.setEnabled(True)
        self._points_refresh.setText("刷新")
        if points:
            try:
                from app import partner_points_store
                partner_points_store.save(points)
            except Exception:
                pass
        self._render_points()

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

    def toggle_recent(self) -> None:
        """展开/收起「最近评过的曲子」。"""
        self._recent_expanded = not self._recent_expanded
        self._recent.setVisible(self._recent_expanded)
        self._recent_toggle.setText("收起 ▾" if self._recent_expanded else "展开 ▸")

    def _render_recent(self) -> None:
        self._recent.clear()
        try:
            items = TrackLog().recent(_RECENT_LIMIT)
        except Exception:
            items = []
        self._recent_title.setText(
            f"最近评过的曲子 {len(items)}" if items else "最近评过的曲子")
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

    # ------------------------------------------------------------------
    # 执行情况（与手机端同构：一天一条，可展开）
    # ------------------------------------------------------------------
    def scroll_to_history(self) -> None:
        """「查看全部」跳过来时，直接落到执行情况那一块。"""
        QTimer.singleShot(
            0, lambda: self._scroll.ensureWidgetVisible(self._history_section))

    def _render_history(self) -> None:
        while self._history_lay.count():
            item = self._history_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        try:
            records = TaskHistory().load_recent(_HISTORY_LIMIT)
        except Exception:
            records = []

        groups = {}
        for entry in records:
            ts = str(entry.get("ts") or "")
            try:
                moment = datetime.fromisoformat(ts)
            except ValueError:
                continue
            groups.setdefault(moment.date().isoformat(), []).append((moment, entry))

        if not groups:
            empty = QLabel("还没有执行记录，点「今日」页的「立即执行」跑第一次。")
            empty.setObjectName("captionText")
            empty.setWordWrap(True)
            self._history_lay.addWidget(empty)
            return

        for day in sorted(groups, reverse=True):
            runs = sorted(groups[day], key=lambda pair: pair[0], reverse=True)
            self._history_lay.addWidget(self._history_day(day, runs))
            rule = QFrame()
            rule.setObjectName("rule")
            self._history_lay.addWidget(rule)

    def _history_day(self, day: str, runs) -> QWidget:
        statuses = [_run_status(entry) for _, entry in runs]
        if "success" in statuses:
            day_status = "success"
        elif "fail" in statuses:
            day_status = "fail"
        else:
            day_status = "cancel"
        marker, name = _STATUS_VIEW[day_status]

        wrapper = QWidget()
        lay = QVBoxLayout(wrapper)
        lay.setContentsMargins(0, 10, 0, 10)
        lay.setSpacing(3)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(theme.SP_2)
        title = QLabel(_day_title(day))
        title.setObjectName("trackName")
        head.addWidget(title, 0, Qt.AlignBaseline)
        weekday = QLabel(_weekday(day))
        weekday.setObjectName("trackMeta")
        head.addWidget(weekday, 0, Qt.AlignBaseline)
        head.addStretch(1)
        status = QLabel(marker)
        status.setObjectName(name)
        head.addWidget(status, 0, Qt.AlignBaseline)
        toggle = QToolButton()
        toggle.setObjectName("textButton")
        toggle.setToolButtonStyle(Qt.ToolButtonTextOnly)
        toggle.setCursor(Qt.PointingHandCursor)
        head.addWidget(toggle)
        lay.addLayout(head)

        latest_time, latest_entry = runs[0]
        summary = (str(latest_entry.get("summary") or "")
                   if len(runs) == 1 else
                   f"执行 {len(runs)} 次，最近 "
                   f"{latest_time.strftime('%H:%M')} {_STATUS_VIEW[_run_status(latest_entry)][0]}")
        summary_label = QLabel(summary)
        summary_label.setObjectName("captionText")
        summary_label.setWordWrap(True)
        lay.addWidget(summary_label)

        panel = self._history_runs_panel()
        show = day in self._expanded_days
        if show:
            self._fill_runs_panel(panel, runs)
        panel.setVisible(show)
        toggle.setText("收起 ▾" if show else "展开 ▸")
        toggle.clicked.connect(
            lambda _=False, d=day, p=panel, b=toggle, r=runs:
            self._toggle_day(d, p, b, r))
        lay.addWidget(panel)
        return wrapper

    def _history_runs_panel(self) -> QWidget:
        """先建空面板；展开时才填内容，避免几百天一次性建控件。"""
        panel = QFrame()
        panel.setObjectName("card")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(theme.SP_3, theme.SP_2, theme.SP_3, theme.SP_2)
        lay.setSpacing(theme.SP_1)
        panel.setProperty("filled", False)
        return panel

    def _fill_runs_panel(self, panel: QWidget, runs) -> None:
        if panel.property("filled"):
            return
        panel.setProperty("filled", True)
        lay = panel.layout()
        for index, (moment, entry) in enumerate(runs):
            if index:
                rule = QFrame()
                rule.setObjectName("rule")
                lay.addWidget(rule)
            row = QWidget()
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(theme.SP_2)

            stamp = QLabel(moment.strftime("%H:%M"))
            stamp.setObjectName("dataTextMuted")
            stamp.setFixedWidth(48)
            row_lay.addWidget(stamp, 0, Qt.AlignTop)

            marker, name = _STATUS_VIEW[_run_status(entry)]
            status = QLabel(marker)
            status.setObjectName(name)
            status.setFixedWidth(40)
            row_lay.addWidget(status, 0, Qt.AlignTop)

            text = QWidget()
            text_lay = QVBoxLayout(text)
            text_lay.setContentsMargins(0, 0, 0, 0)
            text_lay.setSpacing(2)
            message = QLabel(str(entry.get("summary") or ""))
            message.setObjectName("subtitle")
            message.setWordWrap(True)
            text_lay.addWidget(message)
            detail = str(entry.get("detail") or "")
            if detail:
                detail_label = QLabel(detail)
                detail_label.setObjectName("captionText")
                detail_label.setWordWrap(True)
                text_lay.addWidget(detail_label)
            row_lay.addWidget(text, 1)
            lay.addWidget(row)

    def _toggle_day(self, day: str, panel: QWidget, button: QToolButton,
                    runs) -> None:
        show = panel.isHidden()
        if show:
            self._fill_runs_panel(panel, runs)
        panel.setVisible(show)
        button.setText("收起 ▾" if show else "展开 ▸")
        if show:
            self._expanded_days.add(day)
        else:
            self._expanded_days.discard(day)


_STATUS_VIEW = {
    "success": ("成功", "successText"),
    "fail": ("失败", "dangerText"),
    "cancel": ("取消", "warningText"),
}


def _run_status(entry: dict) -> str:
    if entry.get("success"):
        return "success"
    return "cancel" if "取消" in str(entry.get("summary") or "") else "fail"


def _day_title(day: str) -> str:
    try:
        moment = date.fromisoformat(day)
        return f"{moment.month}月{moment.day}日"
    except Exception:
        return day


def _weekday(day: str) -> str:
    try:
        return _WEEKDAYS[date.fromisoformat(day).weekday()]
    except Exception:
        return ""


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
