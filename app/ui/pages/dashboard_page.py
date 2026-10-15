"""首页 —— 一份记录表。

主角是**一句话**，不是一张卡片：40px 宋体直说今天的状况
（还没有登录 / Cookie 失效了 / 今天还没跑 / 今天已跑）。
下面是一张真实的打卡记录，读 ``TaskHistory``。

设计意图：用户每天打开程序只想知道一件事——今天跑了吗。
所以这句话是页面上唯一的展示级元素，其余全部安静。
"""
from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from app.app_config import AppConfig
from app.cookie_store import CookieStore
from app.task_history import TaskHistory
from app.ui import theme
from app.ui.icons import ICON_LOGIN, ICON_RUN, op_icon, result_icon, step_icon
from app.ui.widgets.streak_grid import StreakGrid

# 三态常量（UNCONFIGURED 无 Cookie / VALID 有效 / EXPIRED 失效）
_UNCONFIGURED = "unconfigured"
_VALID = "valid"
_EXPIRED = "expired"

# 记录表显示多少行（一年格子图负责"坚持得怎么样"，表只负责"上次怎么回事"，
# 所以行数从 7 缩到 5，把纵向空间让给图）
_LEDGER_ROWS = 5

# 格子图要多少天：53 周
_GRID_DAYS = 371

_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _parse_ts(ts: str) -> Optional[datetime]:
    """解析历史记录里的 ISO 时间戳；失败返回 None。"""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        try:
            return datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            return None


def _fmt_day(dt: datetime) -> str:
    """10月15日"""
    return f"{dt.month}月{dt.day}日"


def _fmt_clock(dt: datetime) -> str:
    """09:02"""
    return dt.strftime("%H:%M")


class DashboardPage(QWidget):
    """首页：一句话状态 + 打卡记录。"""

    run_task = Signal()
    goto_login = Signal()
    goto_settings = Signal()  # 保留：主窗口仍连着，供将来复用
    refresh_cookie = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._state = _UNCONFIGURED
        self._expired_msg = ""
        self._build_ui()
        self.refresh_cookie_card()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.PAGE_MARGIN, theme.PAGE_MARGIN,
                                 theme.PAGE_MARGIN, theme.PAGE_MARGIN)
        outer.setSpacing(0)

        # 今天是几号——这句话定义了下面"今天"的含义，所以它值得占一行
        self._today_label = QLabel("")
        self._today_label.setObjectName("captionText")
        outer.addWidget(self._today_label)

        outer.addSpacing(theme.SP_5)

        # 顶部提示条（默认隐藏）
        self._toast = QLabel("")
        self._toast.setObjectName("toast")
        self._toast.setVisible(False)
        outer.addWidget(self._toast)

        # ---- 主角：一句话 ----
        self._statement = QLabel("")
        self._statement.setObjectName("displayStatement")
        self._statement.setWordWrap(True)
        outer.addWidget(self._statement)

        outer.addSpacing(theme.SP_2)

        self._detail = QLabel("")
        self._detail.setObjectName("captionText")
        self._detail.setWordWrap(True)
        outer.addWidget(self._detail)

        outer.addSpacing(theme.SP_5)

        # ---- 动作行：主按钮在左，定时信息在右 ----
        action_row = QHBoxLayout()
        action_row.setSpacing(theme.SP_4)

        self._action_btn = QPushButton("")
        self._action_btn.setObjectName("primaryButton")
        self._action_btn.setIconSize(QSize(15, 15))
        self._action_btn.setMinimumWidth(132)
        self._action_btn.clicked.connect(self._on_action_clicked)
        action_row.addWidget(self._action_btn)

        action_row.addStretch(1)

        self._schedule_label = QLabel("")
        self._schedule_label.setObjectName("captionText")
        action_row.addWidget(self._schedule_label)

        outer.addLayout(action_row)

        outer.addSpacing(theme.SP_6)

        # ---- 分隔线 ----
        rule = QFrame()
        rule.setObjectName("rule")
        outer.addWidget(rule)

        outer.addSpacing(theme.SP_5)

        # ---- 打卡记录：一年格子图 ----
        # 图回答"我坚持得怎么样"，表回答"上次到底怎么回事"，两者职责不同
        grid_heading = QLabel("打卡记录")
        grid_heading.setObjectName("sectionHeading")
        outer.addWidget(grid_heading)

        outer.addSpacing(theme.SP_3)

        self._grid = StreakGrid()
        outer.addWidget(self._grid, 0, Qt.AlignLeft)

        outer.addSpacing(theme.SP_5)

        # ---- 最近几次：明细表 ----
        ledger_heading = QLabel("最近几次")
        ledger_heading.setObjectName("sectionHeading")
        outer.addWidget(ledger_heading)

        outer.addSpacing(theme.SP_3)

        self._ledger = QVBoxLayout()
        self._ledger.setSpacing(0)
        outer.addLayout(self._ledger)

        outer.addStretch(1)

    # ------------------------------------------------------------------
    # 记录表
    # ------------------------------------------------------------------
    def _clear_ledger(self) -> None:
        while self._ledger.count():
            item = self._ledger.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _refresh_ledger(self) -> None:
        """读历史，重建一年格子图和最近几次的明细表。"""
        self._refresh_grid()
        self._clear_ledger()
        try:
            recent = TaskHistory().load_recent(_LEDGER_ROWS)
        except Exception:
            recent = []

        if not recent:
            empty = QLabel("还没有执行记录，点上面的按钮跑第一次")
            empty.setObjectName("emptyState")
            self._ledger.addWidget(empty)
            return

        for entry in recent:
            self._ledger.addWidget(self._make_ledger_row(entry))

    def _refresh_grid(self) -> None:
        """重建一年格子图。数据源是按天聚合的结论，不是明细。"""
        try:
            days = TaskHistory().daily_summary(_GRID_DAYS)
        except Exception:
            days = []
        self._grid.set_days(days)

    def _make_ledger_row(self, entry: dict) -> QWidget:
        """一行记录：日期 / 星期 / 状态（失败时带原因）/ 时间。"""
        ok = bool(entry.get("success", False))
        summary = str(entry.get("summary", "") or "")
        dt = _parse_ts(str(entry.get("ts", "") or ""))

        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 7, 0, 7)
        lay.setSpacing(theme.SP_3)

        # 日期（等宽，保证列对齐）
        date_label = QLabel(dt.strftime("%m-%d") if dt else "--")
        date_label.setObjectName("dataTextMuted")
        date_label.setFixedWidth(46)
        lay.addWidget(date_label)

        # 星期
        week_label = QLabel(_WEEKDAYS[dt.weekday()] if dt else "")
        week_label.setObjectName("captionText")
        week_label.setFixedWidth(34)
        lay.addWidget(week_label)

        # 状态：图标 + 词。取消不算失败也不算成功，单独一色。
        # 图标必须和状态词同色——取消用琥珀的"禁止"，不能用红色叉（那是失败）
        if "取消" in summary:
            status_word, status_obj, icon_pm = "取消", "warningText", step_icon("cancelled")
        elif ok:
            status_word, status_obj, icon_pm = "成功", "successText", result_icon(True)
        else:
            status_word, status_obj, icon_pm = "失败", "dangerText", result_icon(False)

        icon = QLabel()
        icon.setFixedSize(16, 16)
        icon.setPixmap(icon_pm.pixmap(QSize(16, 16)))
        lay.addWidget(icon)

        status_label = QLabel(status_word)
        status_label.setObjectName(status_obj)
        status_label.setFixedWidth(34)
        lay.addWidget(status_label)

        # 只有失败／取消才展开原因——成功的记录都长一个样，展开只是噪音
        if not ok:
            reason = QLabel(summary)
            reason.setObjectName("captionText")
            reason.setToolTip(summary)
            lay.addWidget(reason, 1)
        else:
            lay.addStretch(1)

        # 时间
        clock_label = QLabel(_fmt_clock(dt) if dt else "")
        clock_label.setObjectName("dataTextMuted")
        lay.addWidget(clock_label)

        row.setToolTip(f"{summary}\n{entry.get('ts', '')}".strip())
        return row

    # ------------------------------------------------------------------
    # 状态渲染
    # ------------------------------------------------------------------
    def _today_record(self) -> Optional[dict]:
        """今天的最近一条记录；今天没跑过返回 None。"""
        try:
            recent = TaskHistory().load_recent(_LEDGER_ROWS)
        except Exception:
            return None
        today = datetime.now().date()
        for entry in recent:
            dt = _parse_ts(str(entry.get("ts", "") or ""))
            if dt and dt.date() == today:
                return entry
            if dt and dt.date() < today:
                break
        return None

    def _last_record(self) -> Optional[dict]:
        try:
            recent = TaskHistory().load_recent(1)
        except Exception:
            return None
        return recent[0] if recent else None

    def _render(self) -> None:
        now = datetime.now()
        self._today_label.setText(
            f"{now.year}年{now.month}月{now.day}日 {_WEEKDAYS[now.weekday()]}")

        if self._state == _UNCONFIGURED:
            self._statement.setText("还没有登录")
            self._set_statement_color(theme.INK)
            self._detail.setText("登录后即可执行音乐合伙人每日任务")
            self._action_btn.setText("立即登录")
            self._action_btn.setIcon(op_icon(ICON_LOGIN, theme.PANEL))

        elif self._state == _EXPIRED:
            self._statement.setText("Cookie 失效了")
            self._set_statement_color(theme.FAILED)
            self._detail.setText(self._expired_msg or "需要重新登录才能继续执行任务")
            self._action_btn.setText("重新登录")
            self._action_btn.setIcon(op_icon(ICON_LOGIN, theme.PANEL))

        else:  # _VALID
            today = self._today_record()
            if today is None:
                last = self._last_record()
                self._statement.setText("今天还没跑")
                self._set_statement_color(theme.INK)
                if last is not None:
                    dt = _parse_ts(str(last.get("ts", "") or ""))
                    word = "成功" if last.get("success") else "失败"
                    if dt:
                        self._detail.setText(
                            f"上次{word} {_fmt_day(dt)} {_fmt_clock(dt)}")
                    else:
                        self._detail.setText(f"上次{word}")
                else:
                    self._detail.setText("还没有执行记录")
            else:
                summary = str(today.get("summary", "") or "")
                dt = _parse_ts(str(today.get("ts", "") or ""))
                clock = f" {_fmt_clock(dt)}" if dt else ""
                if "取消" in summary:
                    self._statement.setText("今天手动取消了")
                    self._set_statement_color(theme.RUNNING_TEXT)
                elif today.get("success"):
                    self._statement.setText("今天已跑")
                    self._set_statement_color(theme.SUCCESS)
                else:
                    self._statement.setText("今天跑失败了")
                    self._set_statement_color(theme.FAILED)
                self._detail.setText(f"{summary}{clock}".strip())

            self._action_btn.setText("立即执行")
            self._action_btn.setIcon(op_icon(ICON_RUN, theme.PANEL))

        self._render_schedule()
        self._refresh_ledger()

    def _set_statement_color(self, color: str) -> None:
        """改那句话的颜色。

        用内联样式而不是 objectName：这句话的颜色由**状态**决定，
        而状态是运行时算出来的，套 objectName 再 repolish 反而更绕。
        """
        self._statement.setStyleSheet(f"color: {color};")

    def _render_schedule(self) -> None:
        """右下角的定时信息。没开就直说没开，别留空让人猜。"""
        try:
            cfg = AppConfig()
            enabled = bool(cfg.schedule_enabled)
            hhmm = str(cfg.schedule_time or "09:00")
            mode = str(cfg.schedule_mode or "local")
        except Exception:
            enabled, hhmm, mode = False, "09:00", "local"

        if not enabled:
            self._schedule_label.setText("未开启定时")
            return
        mode_text = {"local": "本地", "cloud": "云端", "both": "本地＋云端"}.get(
            mode, "本地")
        self._schedule_label.setText(f"下次自动 {hhmm}（{mode_text}）")

    def _on_action_clicked(self) -> None:
        if self._state == _VALID:
            self.run_task.emit()
        else:
            self.goto_login.emit()

    # ------------------------------------------------------------------
    # 对外
    # ------------------------------------------------------------------
    def refresh_cookie_card(self) -> None:
        """从 CookieStore 判断存在性：无 Cookie → UNCONFIGURED；有 → VALID。"""
        try:
            music_u, csrf, _ = CookieStore().load()
        except Exception:
            music_u, csrf = "", ""
        self._state = _VALID if (music_u and csrf) else _UNCONFIGURED
        self._expired_msg = ""
        self._render()

    def set_cookie_status(self, ok: bool, msg: str = "") -> None:
        """后台验证结果驱动：ok=True → VALID；ok=False → EXPIRED。"""
        if ok:
            self._state = _VALID
            self._expired_msg = ""
        else:
            self._state = _EXPIRED
            self._expired_msg = msg
        self._render()

    def set_last_task_summary(self, msg: str = "") -> None:
        """刷新最近任务摘要（重新读 TaskHistory 并重绘记录表）。"""
        self._render()

    def show_toast(self, msg: str) -> None:
        """顶部短暂提示，2.5 秒后自动隐藏。"""
        self._toast.setText(msg)
        self._toast.show()
        QTimer.singleShot(2500, self._hide_toast)

    def _hide_toast(self) -> None:
        self._toast.hide()
