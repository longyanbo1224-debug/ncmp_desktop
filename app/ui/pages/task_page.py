"""今日页 —— 一本每天自动填一页的值班簿。

v1.2 起本页的主视角是**曲目表**（:class:`~app.ui.widgets.track_list.TrackList`）：
今天评了哪几首、每首几分、留下了什么批注，一屏读完。
旧的"步骤树 + 日志"没有丢，但降级成默认收起的「运行详情」，只在失败时自动展开。
设计依据见 ``docs/DESIGN.md`` §4、§5。

两种执行模式不变：
    - 本地执行：TaskWorker 调 core.bot.MusicPartnerBot.run()，拿歌曲级进度
    - 云端执行：CloudWorker 触发 GitHub Actions workflow_dispatch 并轮询状态，
      无歌曲级进度（GitHub 不暴露 per-song），复用步骤行展示触发/等待/完成。
"""
from datetime import date, datetime
import re
import time
from typing import Optional, Tuple

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QSplitter, QToolButton, QVBoxLayout, QWidget,
)

from app.cookie_store import CookieStore
from app.task_history import TaskHistory
from app.track_log import (
    STATE_FAILED, STATE_SKIPPED, STATE_SUBMITTED, TrackLog,
)
from app.ui import theme
from app.ui.icons import ICON_RUN, op_icon
from app.ui.widgets.log_view import GuiLogHandler, LogView
from app.ui.widgets.meter import LevelMeter
from app.ui.widgets.step_list import StepList
from app.ui.widgets.track_list import TrackList
from app.workers.cloud_worker import CloudWorker
from app.workers.task_worker import TaskWorker
from app.workers.works_worker import WorksRefreshWorker
from core import scoring
from core.utils import errors

# keyring 服务名（与 CookieStore / Config 对齐，gh_token 同 service 不同 key）
_KEYRING_SERVICE = "ncmp desktop"

# 本地任务阶段 → 该阶段在总进度里占的区间 (起始%, 结束%)。
#
# 为什么用区间而不是单个锚点：阶段内的歌曲进度要在**本阶段区间内**插值。
# 早期版本把"本阶段第 N 首 / 本阶段共 M 首"直接当成全局 0-100%，
# 于是基础评分阶段刚跑完一半，进度条就已经顶到 100%。
_PHASE_SPAN = {
    "验证用户信息": (0, 2),
    "拉取每日任务": (2, 8),
    "评分基础任务": (8, 30),
    "额外评分任务": (30, 100),
}

# 两个评分阶段合起来占的区间
_SCORING_LO, _SCORING_HI = 8, 100

# full_extra_tasks 关闭时，额外任务固定 7 条（见 core/tasks/extra.py），可以算准。
# 打开时条目数不定，按"额外通常是基础的数倍"给一个大头估计。
_EXTRA_WHEN_LIMITED = 7
_EXTRA_WHEN_FULL_RATIO = 3

#: 右栏宽度（账本摘要）。设计文档 §5：240px
_RAIL_WIDTH = 240

_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _short_ts(ts: str) -> str:
    """2026-10-14T09:02:11 → 10-14 09:02。解析失败原样返回，不崩。"""
    try:
        return datetime.fromisoformat(str(ts)).strftime("%m-%d %H:%M")
    except Exception:
        return str(ts)


def _date_line() -> str:
    """页头的日期：10月28日 周二。"""
    now = datetime.now()
    return f"{now.month}月{now.day}日 {_WEEKDAYS[now.weekday()]}"


class TaskPage(QWidget):
    """今日页。"""

    goto_login = Signal()  # Cookie 预检失败时通知主窗口跳登录页
    goto_settings = Signal()  # 云端预检失败时通知主窗口跳设置页
    goto_ledger = Signal()  # 右栏「查看全部」跳到记录页的完整执行情况
    # 云端 worker 完成（ok, msg）；定时器 + 手动按钮都走这条通知主窗口
    cloud_finished_sig = Signal(bool, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._log_handler: Optional[GuiLogHandler] = None
        self._worker: Optional[TaskWorker] = None
        self._cloud_worker: Optional[CloudWorker] = None
        self._refresh_worker: Optional[WorksRefreshWorker] = None
        self._last_sync = 0.0
        #: 本次执行 / 本次同步的起始时刻：同步比执行早发起的，结果一律作废
        self._run_started_at = 0.0
        self._refresh_started_at = 0.0
        self._history_records = None
        self._track_day = date.today().isoformat()
        #: 歌名 → base/extra。曲目被每日上限裁掉后仍保留，
        #: 评分回调才能把新出现的一行归回额外组、继续受上限约束。
        self._track_groups: dict = {}
        self._current_phase: str = ""   # 当前阶段名，供歌曲进度在阶段区间内插值
        # 阶段区间。开局是兜底值，拿到条目数后由 _plan_scoring 重算。
        self._phase_span: dict = dict(_PHASE_SPAN)
        self._build_ui()
        # 打开程序时把今天已经评过的曲目从账本读回来：
        # 今天跑过之后再开程序，曲目表不该显示"还没排到曲子"。
        self._load_today_from_log()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.PAGE_MARGIN, theme.PAGE_MARGIN,
                                 theme.PAGE_MARGIN, theme.PAGE_MARGIN)
        outer.setSpacing(theme.SP_3)

        # ---- 页头：日期 + 今日计数 ----
        header = QHBoxLayout()
        header.setSpacing(theme.SP_3)
        self._date_label = QLabel(_date_line())
        self._date_label.setObjectName("pageTitle")
        header.addWidget(self._date_label)
        header.addStretch(1)
        self._today_label = QLabel("今日 0/0")
        self._today_label.setObjectName("dataTextMuted")
        header.addWidget(self._today_label)
        outer.addLayout(header)

        # ---- 一句状态陈述：这一行是页面的"话"，其余都是它的注脚 ----
        self._status_label = QLabel("待执行")
        self._status_label.setObjectName("subtitle")
        self._status_label.setWordWrap(True)
        outer.addWidget(self._status_label)

        # ---- 电平表：保留，但收成一条细带，不再是主角 ----
        meter_row = QHBoxLayout()
        meter_row.setSpacing(theme.SP_3)
        self._meter = LevelMeter()
        meter_row.addWidget(self._meter, 1)
        self._percent_label = QLabel("0%")
        self._percent_label.setObjectName("dataTextMuted")
        self._percent_label.setFixedWidth(40)
        self._percent_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        meter_row.addWidget(self._percent_label)
        outer.addLayout(meter_row)

        # ---- 工具条：执行按钮在右，详情开关在左 ----
        actions = QHBoxLayout()
        actions.setSpacing(theme.SP_2)

        self._detail_btn = QToolButton()
        self._detail_btn.setObjectName("textButton")
        self._detail_btn.setText("运行详情 ▸")
        self._detail_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._detail_btn.setCursor(Qt.PointingHandCursor)
        self._detail_btn.clicked.connect(self.toggle_detail)
        actions.addWidget(self._detail_btn)

        # 策略预演（D1）：不联网提交，先用今天的真实歌单算出四种策略的结果
        self._preview_btn = QPushButton("预演今日策略")
        self._preview_btn.setObjectName("textButton")
        self._preview_btn.clicked.connect(self.preview_strategies)
        actions.addWidget(self._preview_btn)

        # 导出今日内页（D4）：从右栏挪到工具条，右栏留给执行历史
        self._export_btn = QPushButton("导出今日内页")
        self._export_btn.setObjectName("textButton")
        self._export_btn.clicked.connect(self.export_today)
        actions.addWidget(self._export_btn)
        actions.addStretch(1)

        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.setObjectName("secondaryButton")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self.cancel)

        self._cloud_btn = QPushButton("云端执行")
        self._cloud_btn.setObjectName("secondaryButton")
        self._cloud_btn.setIcon(op_icon(ICON_RUN, theme.INK))
        self._cloud_btn.setIconSize(QSize(15, 15))
        self._cloud_btn.clicked.connect(self.execute_cloud)

        self._run_btn = QPushButton("立即执行")
        self._run_btn.setObjectName("primaryButton")
        self._run_btn.setIcon(op_icon(ICON_RUN, theme.PANEL))
        self._run_btn.setIconSize(QSize(15, 15))
        self._run_btn.clicked.connect(self.execute)

        actions.addWidget(self._cancel_btn)
        actions.addWidget(self._cloud_btn)
        actions.addWidget(self._run_btn)
        outer.addLayout(actions)

        # ---- 主体：曲目表 + 右栏账本摘要 ----
        body = QHBoxLayout()
        body.setSpacing(theme.SP_4)
        self._track_list = TrackList()
        body.addWidget(self._track_list, 1)
        body.addWidget(self._build_rail())
        outer.addLayout(body, 1)

        # ---- 运行详情：默认收起，失败时自动展开 ----
        self._detail = self._build_detail()
        self._detail.setVisible(False)
        outer.addWidget(self._detail, 0)

        # ---- 失败提示：只在失败时出现，直接告诉用户下一步做什么 ----
        self._hint_label = QLabel("")
        self._hint_label.setObjectName("subtitle")
        self._hint_label.setWordWrap(True)
        self._hint_label.setVisible(False)
        outer.addWidget(self._hint_label)

        self._refresh_rail()

    def _build_rail(self) -> QWidget:
        """右栏账本摘要：今日进度、批注数、最近一次运行。"""
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(_RAIL_WIDTH)
        lay = QVBoxLayout(rail)
        lay.setContentsMargins(theme.SP_4, theme.SP_4, theme.SP_4, theme.SP_4)
        lay.setSpacing(theme.SP_2)

        self._rail_today = QLabel("今日")
        self._rail_today.setObjectName("sectionHeading")
        lay.addWidget(self._rail_today)

        self._rail_done = QLabel("已完成 0 首")
        self._rail_done.setObjectName("dataTextMuted")
        lay.addWidget(self._rail_done)

        self._rail_notes = QLabel("已提交 0 条批注")
        self._rail_notes.setObjectName("dataTextMuted")
        self._rail_notes.setWordWrap(True)
        lay.addWidget(self._rail_notes)

        rule = QFrame()
        rule.setObjectName("rule")
        lay.addWidget(rule)

        history_head = QHBoxLayout()
        history_head.setContentsMargins(0, 0, 0, 0)
        history_head.setSpacing(theme.SP_2)
        history_title = QLabel("最近执行")
        history_title.setObjectName("sectionHeading")
        history_head.addWidget(history_title)
        history_head.addStretch(1)
        self._history_all = QToolButton()
        self._history_all.setObjectName("textButton")
        self._history_all.setText("查看全部 ▸")
        self._history_all.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._history_all.setCursor(Qt.PointingHandCursor)
        self._history_all.clicked.connect(self.goto_ledger.emit)
        history_head.addWidget(self._history_all)
        lay.addLayout(history_head)

        self._history_box = QWidget()
        self._history_lay = QVBoxLayout(self._history_box)
        self._history_lay.setContentsMargins(0, 0, 0, 0)
        self._history_lay.setSpacing(0)
        # 窗口变矮时让列表自己滚动，不要把最后一条挤出可视区
        self._history_scroll = QScrollArea()
        self._history_scroll.setWidgetResizable(True)
        self._history_scroll.setFrameShape(QFrame.NoFrame)
        self._history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._history_scroll.setWidget(self._history_box)
        self._history_scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self._history_scroll.viewport().setStyleSheet("background: transparent;")
        lay.addWidget(self._history_scroll, 1)

        # 等待倒计时（D6）：把 15–20 秒的随机等待变成可见的节奏，
        # 用户理解了为什么要等，就不会以为程序卡死了。
        self._wait_label = QLabel("")
        self._wait_label.setObjectName("dataTextMuted")
        self._wait_label.setWordWrap(True)
        self._wait_label.setVisible(False)
        lay.addWidget(self._wait_label)
        self._wait_timer = QTimer(self)
        self._wait_timer.setInterval(1000)
        self._wait_timer.timeout.connect(self._tick_wait)
        self._wait_left = 0

        return rail

    def _build_detail(self) -> QWidget:
        """运行详情：步骤树 + 日志（原来的主视角，现在是兜底）。"""
        wrapper = QWidget()
        lay = QVBoxLayout(wrapper)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SP_2)

        splitter = QSplitter(Qt.Vertical)
        self._step_list = StepList()
        self._log_view = LogView()
        log_pane = QWidget()
        log_lay = QVBoxLayout(log_pane)
        log_lay.setContentsMargins(0, 0, 0, 0)
        log_lay.setSpacing(theme.SP_1)
        log_title = QLabel("日志")
        log_title.setObjectName("sectionHeading")
        log_lay.addWidget(log_title)
        log_lay.addWidget(self._log_view, 1)
        splitter.addWidget(self._step_list)
        splitter.addWidget(log_pane)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setChildrenCollapsible(False)
        splitter.setFixedHeight(260)
        lay.addWidget(splitter)
        return wrapper

    # ------------------------------------------------------------------
    # 对外
    # ------------------------------------------------------------------
    def toggle_detail(self) -> None:
        """展开/收起运行详情。

        用 ``isHidden`` 而不是 ``isVisible``：后者还取决于整页是否已经显示，
        页面还没挂到窗口上时会把"收起的"当成"显示的"，开关就会失灵。
        """
        self._set_detail_visible(self._detail.isHidden())

    def _set_detail_visible(self, visible: bool) -> None:
        self._detail.setVisible(visible)
        self._detail_btn.setText("运行详情 ▾" if visible else "运行详情 ▸")

    def set_worker(self, worker: TaskWorker) -> None:
        """注入 TaskWorker 实例并连接信号。"""
        if self._worker is not None:
            try:
                self._worker.step.disconnect()
                self._worker.progress.disconnect()
                self._worker.note.disconnect()
                self._worker.works.disconnect()
                self._worker.finished_sig.disconnect()
            except Exception:
                pass
        self._worker = worker
        self._worker.step.connect(self._on_step)
        self._worker.progress.connect(self._on_progress)
        self._worker.note.connect(self._on_note)
        self._worker.works.connect(self._on_works)
        self._worker.finished_sig.connect(self._on_finished)

    def refresh_today(self, force: bool = False) -> None:
        """后台拉一次今日清单，把另一台设备评过的歌补进曲目表。

        打开程序或切回「今日」时触发；30 秒内不重复请求。失败静默，
        不影响页面现有内容。
        """
        if self._is_any_worker_running():
            return
        if (self._refresh_worker is not None
                and self._refresh_worker.isRunning()):
            return
        if not force and time.monotonic() - self._last_sync < 30:
            return
        try:
            music_u, csrf, _ = CookieStore().load()
        except Exception:
            music_u, csrf = "", ""
        if not (music_u and csrf):
            return
        self._last_sync = time.monotonic()
        self._refresh_started_at = self._last_sync
        self._refresh_worker = WorksRefreshWorker(self)
        self._refresh_worker.works.connect(self._on_refresh_works)
        self._refresh_worker.finished.connect(self._on_refresh_finished)
        self._refresh_worker.start()

    def _on_refresh_works(self, works) -> None:
        """打开 / 切回页面时的服务端同步结果。

        同步请求可能在用户点「立即执行」之后才返回：这时它手里是启动那一刻
        的旧快照，拿它重建曲目表会把本次执行刚摆好的行（和随后评完的行）冲掉，
        用户就会看到「先 15 首、评一首多一行」。执行中一律以 worker 的清单为准。
        """
        if self._is_any_worker_running():
            return
        # 同步请求比这次执行发起得还早 → 它拿的是执行前的旧快照，作废
        if self._refresh_started_at <= self._run_started_at:
            return
        self._on_works(works, replace=True)

    def _on_refresh_finished(self) -> None:
        worker = self.sender()
        if worker is not None:
            worker.deleteLater()
        self._refresh_worker = None

    def install_log_handler(self, handler: GuiLogHandler) -> None:
        """供 MainWindow 把共享的 GuiLogHandler 挂进来。"""
        if handler is None:
            return
        if getattr(self, '_log_handler', None) is None:
            handler.log_signal.connect(self._on_log_line)
        self._log_handler = handler

    # ------------------------------------------------------------------
    # D6：等待倒计时
    # ------------------------------------------------------------------
    #: 日志里"等待 17.0 秒后继续..."是 core 在真正 sleep 之前打的，
    #: 所以从这里起算倒计时与真实节奏一致，不需要给 core 再加回调。
    _WAIT_RE = re.compile(r"等待 ([\d.]+) 秒后继续")

    def _on_log_line(self, line: str) -> None:
        self._log_view.appendLog(line)
        self._detect_wait(line)

    def _detect_wait(self, line: str) -> None:
        match = self._WAIT_RE.search(str(line))
        if not match:
            return
        try:
            seconds = int(round(float(match.group(1))))
        except (TypeError, ValueError):
            return
        if seconds <= 0:
            self._stop_wait()
            return
        self._wait_left = seconds
        self._show_wait()
        self._wait_timer.start()

    def _tick_wait(self) -> None:
        self._wait_left -= 1
        if self._wait_left <= 0:
            self._stop_wait()
            return
        self._show_wait()

    def _show_wait(self) -> None:
        self._wait_label.setText(f"再等 {self._wait_left} 秒，避免触发风控。")
        self._wait_label.setVisible(True)

    def _stop_wait(self) -> None:
        try:
            self._wait_timer.stop()
        except Exception:
            pass
        self._wait_left = 0
        self._wait_label.setVisible(False)

    # ------------------------------------------------------------------
    # D1：策略预演
    # ------------------------------------------------------------------
    def preview_strategies(self) -> None:
        """用今天真实的待评歌单，算出四种策略各会给出什么（不提交、不改配置）。"""
        try:
            music_u, csrf, _ = CookieStore().load()
        except Exception:
            music_u, csrf = "", ""
        if not (music_u and csrf):
            self._set_status("未配置 Cookie，请先登录", "dangerText")
            self.goto_login.emit()
            return

        works = []
        try:
            import requests
            session = requests.Session()
            session.cookies.set("MUSIC_U", music_u)
            session.cookies.set("__csrf", csrf)
            response = session.get(
                "https://interface.music.163.com/api/music/partner/daily/task/get",
                timeout=15).json()
            tasks = (response.get("data") or {}).get("works") or []
            all_works = [task.get("work") or {} for task in tasks]
            pending = [task.get("work") or {} for task in tasks
                       if not task.get("completed")]
            # 今天已经评完时 pending 是空的，但"策略会给出什么"照样能算——
            # 用今天这份完整歌单演算，否则按钮会变成"没内容可预演"。
            works = pending or all_works
            all_done = not pending and bool(all_works)
        except Exception as error:
            QMessageBox.warning(self, "策略预演", f"拉取今日歌单失败：{error}")
            return

        if not works:
            QMessageBox.information(
                self, "策略预演", "今天没有可评的曲子，暂时没有可预演的内容。")
            return

        try:
            from core.utils.config import Config
            current = int(Config().get("score", scoring.DEFAULT_STRATEGY))
        except Exception:
            current = scoring.DEFAULT_STRATEGY

        lines = [f"今天待评 {len(works)} 首。四种策略分别会给出：", ""] if not all_done else [
            f"今天这 {len(works)} 首已经评完了。若换策略，同样这 {len(works)} 首会是：", ""]
        for strategy, counts in scoring.compare(works).items():
            label = scoring.STRATEGIES.get(strategy, str(strategy))
            mark = "　← 当前" if strategy == current else ""
            lines.append(f"· {label}：{scoring.describe(counts)}{mark}")
        lines.append("")
        lines.append("只是预演，没有提交任何东西。要改策略请到设置页。")
        QMessageBox.information(self, "策略预演", "\n".join(lines))

    # ------------------------------------------------------------------
    # D4：导出今日内页
    # ------------------------------------------------------------------
    def export_today(self) -> None:
        """把今天的曲目与批注导出成一页 Markdown。"""
        log = TrackLog()
        text = log.export_markdown()
        default_name = f"音乐合伙人-{datetime.now().strftime('%Y%m%d')}.md"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出今日内页", default_name, "Markdown (*.md);;文本 (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
        except Exception as error:
            self._show_hint(f"导出失败：{error}")
            return
        self._show_hint(f"已导出到 {path}")

    def execute(self, notify_context: str = "task") -> None:
        """启动本地任务。

        :param notify_context: "task"=手动执行（默认，读 notify_on_task_done），
                                "schedule"=定时执行（读 notify_on_schedule）。
        """
        if self._worker is None:
            self._set_status("未注入 TaskWorker", "captionText")
            return
        # Cookie 预检：未配置则不启动 worker，提示并引导登录
        try:
            music_u, csrf, _ = CookieStore().load()
        except Exception:
            music_u, csrf = "", ""
        if not (music_u and csrf):
            self._set_status("未配置 Cookie，请先登录", "dangerText")
            self.goto_login.emit()
            return
        if self._is_any_worker_running():
            self._set_status("已有任务在执行", "captionText")
            return

        self._begin_run("执行中…", "running")
        self._worker.start_task(notify_context=notify_context)

    def execute_cloud(self) -> None:
        """启动云端任务：触发 GitHub Actions workflow_dispatch。"""
        if self._is_any_worker_running():
            self._set_status("已有任务在执行", "captionText")
            return
        token, repo, workflow, branch, missing = self._load_cloud_config()
        if missing:
            self._set_status(
                f"未配置 GitHub Actions（缺 {missing}），请先到设置页填写", "dangerText")
            self.goto_settings.emit()
            return

        if self._cloud_worker is not None:
            try:
                self._cloud_worker.step.disconnect()
                self._cloud_worker.log.disconnect()
                self._cloud_worker.progress.disconnect()
                self._cloud_worker.finished_sig.disconnect()
            except Exception:
                pass
        self._cloud_worker = CloudWorker(
            token=token, repo=repo, workflow=workflow, branch=branch,
            parent=self,
        )
        self._cloud_worker.step.connect(self._on_step)
        self._cloud_worker.log.connect(self._on_cloud_log)
        self._cloud_worker.progress.connect(self._on_cloud_progress)
        self._cloud_worker.finished_sig.connect(self._on_cloud_finished)

        self._begin_run("云端执行中…", "running")
        self._cloud_worker.start()

    def cancel(self) -> None:
        """取消当前正在运行的 worker（本地或云端）。"""
        if self._worker is not None and self._worker.isRunning():
            self._set_status("正在取消…", "captionText")
            self._worker.cancel()
            return
        if self._cloud_worker is not None and self._cloud_worker.isRunning():
            self._set_status("正在取消云端任务…", "captionText")
            self._cloud_worker.cancel()

    # ------------------------------------------------------------------
    # 运行态辅助
    # ------------------------------------------------------------------
    def _begin_run(self, status_text: str, meter_state: str) -> None:
        """一次执行开始时的统一收尾：清空曲目表、归零电平表、锁按钮。"""
        self._track_day = date.today().isoformat()
        self._track_list.clear()
        self._track_groups.clear()
        self._run_started_at = time.monotonic()
        self._meter.reset()
        self._meter.set_state(meter_state)
        self._percent_label.setText("0%")
        self._current_phase = ""
        self._phase_span = dict(_PHASE_SPAN)
        self._stop_wait()
        self._show_hint("")
        # 跑起来就把「运行详情」展开：日志要能一边跑一边看，
        # 结束后（成功时）再收起来（失败/取消保持展开，方便回看原因）。
        self._set_detail_visible(True)
        self._set_status(status_text, "captionText")
        self._set_run_buttons_enabled(False)
        self._refresh_rail()

    def _set_status(self, text: str, obj_name: str) -> None:
        """改状态陈述的文案 + 语义色（objectName 变了要重新 polish）。"""
        self._status_label.setText(text)
        self._status_label.setObjectName(obj_name)
        try:
            self._status_label.style().polish(self._status_label)
        except Exception:
            pass

    def _load_today_from_log(self) -> None:
        """把今天账本里的曲目读回曲目表。

        今天已经跑过一轮之后再打开程序，曲目表必须是"今天评了什么"，
        而不是空状态引导——这正是"值班簿"的意义：它记着今天。
        """
        try:
            entries = TrackLog().day()
        except Exception:
            return
        if not entries:
            return
        for entry in entries:
            if entry.get("state") == STATE_SUBMITTED:
                state = "done"
            elif entry.get("state") == STATE_FAILED:
                state = "failed"
            else:
                state = "skipped"
            self._track_list.add(
                str(entry.get("song") or ""),
                meta=str(entry.get("artist") or ""),
                score=str(entry.get("score") or ""),
                state=state,
                note=str(entry.get("note") or ""),
                group=str(entry.get("group") or ""),
            )
        self._refresh_rail()

    def _refresh_rail(self) -> None:
        """刷新右栏：今日完成数、批注数、最近几次执行。

        分母用**曲目表行数**（基础 + 额外，含待评），不是当前阶段的进度目标——
        否则基础阶段显示 0/5、额外阶段又跳到 x/15，和列表里的行数对不上。
        """
        total = self._track_list.count()
        done = self._track_list.done_count()
        self._rail_done.setText(f"已完成 {done}/{total} 首" if total else "已完成 0 首")
        notes = self._track_list.note_count()
        self._rail_notes.setText(
            f"已提交 {notes} 条批注" if notes else "本次还没有提交批注")
        self._today_label.setText(f"今日 {done}/{total}" if total else "今日 0")
        self._render_history()

    # ------------------------------------------------------------------
    # 云端辅助
    # ------------------------------------------------------------------
    def _load_cloud_config(self) -> Tuple[str, str, str, str, str]:
        """读取 GitHub Actions 配置（gh_token 走 keyring，其余走 Config）。"""
        token = ""
        try:
            import keyring
            if keyring is not None:
                token = keyring.get_password(_KEYRING_SERVICE, "gh_token") or ""
        except Exception:
            token = ""
        repo = workflow = branch = ""
        try:
            from core.utils.config import Config
            cfg = Config()
            repo = str(cfg.get("gh_repo", "") or "")
            workflow = str(cfg.get("workflow_name", "") or "")
            branch = str(cfg.get("workflow_branch", "") or "")
        except Exception:
            pass
        if not token:
            return "", "", "", "", "gh_token"
        if not repo:
            return "", "", "", "", "gh_repo"
        if not workflow:
            return "", "", "", "", "workflow_name"
        if not branch:
            return "", "", "", "", "workflow_branch"
        return token, repo, workflow, branch, ""

    def _is_any_worker_running(self) -> bool:
        """本地或云端任一 worker 在跑即返回 True。"""
        local = self._worker is not None and self._worker.isRunning()
        cloud = self._cloud_worker is not None and self._cloud_worker.isRunning()
        return local or cloud

    def _set_run_buttons_enabled(self, enabled: bool) -> None:
        """运行/取消按钮联动。运行中禁用所有运行按钮，启用取消。"""
        self._run_btn.setEnabled(enabled)
        self._cloud_btn.setEnabled(enabled)
        self._cancel_btn.setEnabled(not enabled)

    def _render_history(self) -> None:
        """右栏「执行情况」：最近几次执行的时间、结果和摘要。

        只在历史真的变化时重建：进度回调每秒都会刷新右栏，重建控件会闪、
        旧控件在 deleteLater 生效前还会和新控件叠在一起。
        """
        try:
            records = TaskHistory().load_recent(4)
        except Exception:
            records = []
        if records == self._history_records:
            return
        self._history_records = records

        while self._history_lay.count():
            item = self._history_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # 先从布局和父容器里摘掉，再延迟销毁；否则旧控件会残留一帧
                widget.setParent(None)
                widget.deleteLater()

        if not records:
            empty = QLabel("还没有执行记录。点「立即执行」跑第一次。")
            empty.setObjectName("captionText")
            empty.setWordWrap(True)
            self._history_lay.addWidget(empty)
            return
        for index, entry in enumerate(records):
            if index:
                rule = QFrame()
                rule.setObjectName("rule")
                self._history_lay.addWidget(rule)

            summary = str(entry.get("summary") or "")
            ok = bool(entry.get("success", False))
            if ok:
                marker, name = "成功", "successText"
            elif "取消" in summary:
                marker, name = "取消", "warningText"
            else:
                marker, name = "失败", "dangerText"

            box = QWidget()
            box_lay = QVBoxLayout(box)
            box_lay.setContentsMargins(0, 5, 0, 5)
            box_lay.setSpacing(3)

            head = QHBoxLayout()
            head.setContentsMargins(0, 0, 0, 0)
            head.setSpacing(theme.SP_2)
            status = QLabel(marker)
            status.setObjectName(name)
            head.addWidget(status, 0, Qt.AlignBaseline)
            head.addStretch(1)
            stamp = QLabel(_short_ts(str(entry.get("ts") or "")))
            stamp.setObjectName("dataTextMuted")
            head.addWidget(stamp, 0, Qt.AlignBaseline)
            box_lay.addLayout(head)

            if summary:
                body = QLabel(summary)
                body.setObjectName("captionText")
                body.setWordWrap(True)
                box_lay.addWidget(body)
            self._history_lay.addWidget(box)

    # ------------------------------------------------------------------
    # 槽
    # ------------------------------------------------------------------
    def _plan_scoring(self, base_total: int) -> None:
        """按条目数把 8~100 分给两个评分阶段（详见旧版注释，逻辑未变）。"""
        if base_total <= 0:
            return
        try:
            from core.utils.config import Config
            full = bool(Config().get("full_extra_tasks", True))
        except Exception:
            full = True
        extra_est = (_EXTRA_WHEN_LIMITED if not full
                     else base_total * _EXTRA_WHEN_FULL_RATIO)
        if extra_est <= 0:
            return
        span = _SCORING_HI - _SCORING_LO
        base_hi = _SCORING_LO + int(round(span * base_total / (base_total + extra_est)))
        base_hi = max(_SCORING_LO + 1, min(_SCORING_HI - 1, base_hi))
        self._phase_span["评分基础任务"] = (_SCORING_LO, base_hi)
        self._phase_span["额外评分任务"] = (base_hi, _SCORING_HI)

    def _on_step(self, name: str, status: str, elapsed: float) -> None:
        self._step_list.updateStep(name, status, elapsed)
        span = self._phase_span.get(name)
        if span is None:
            return
        lo, hi = span
        if status == "running":
            self._current_phase = name
            self._update_progress(lo)
        elif status in ("success", "failed"):
            self._update_progress(hi)
            if self._current_phase == name:
                self._current_phase = ""

    def _on_progress(self, done: int, total: int, song: str, score: str) -> None:
        # 一首歌评完：在曲目表里落下这一行。
        # 必须带上分组：被每日上限裁掉的额外曲目重新出现时，还要继续受上限约束，
        # 否则每评一首就多一行（15 → 16 → …），计数越跑越大。
        if song and score:
            self._track_list.add(song, score=str(score), state="done",
                                 group=self._group_for(song))
            self._cap_tracks()
            # 同时写进账本（AppConfig 同目录的 track_log.json）
            try:
                TrackLog().record(song, score=str(score),
                                  group=self._group_for(song))
            except Exception:
                pass
        if not total or total <= 0:
            self._refresh_rail()
            return
        if done == 0 and self._current_phase == "评分基础任务":
            self._plan_scoring(int(total))
        lo, hi = self._phase_span.get(self._current_phase, (0, 100))
        frac = max(0.0, min(1.0, float(done) / float(total)))
        self._update_progress(int(round(lo + (hi - lo) * frac)))
        self._refresh_rail()

    def _group_for(self, song: str) -> str:
        """某首歌的 base/extra 分组；清单里没摆过的按当前评分阶段补。

        评分回调只带歌名，不带分组。正常路径下曲目表早已摆好、映射也有；
        万一某首歌没出现在预置清单里（服务端分批、同步竞态），按「正在跑哪个
        阶段」也能归对组，避免它绕过额外的每日上限、每评一首多一行。
        """
        group = self._track_groups.get(song, "")
        if group:
            return group
        if self._current_phase == "评分基础任务":
            group = "base"
        elif self._current_phase == "额外评分任务":
            group = "extra"
        if group:
            self._track_groups[song] = group
        return group

    def _cap_tracks(self) -> None:
        """额外任务每天最多 15 首（基础 5 + 额外 15 = 20），多出来的不展示。"""
        try:
            from core.utils.config import Config
            full = bool(Config().get("full_extra_tasks", True))
        except Exception:
            full = True
        self._track_list.cap_extra(15 if full else 7)

    def _on_works(self, works, replace: bool = False) -> None:
        """服务端返回的今日曲目清单：已评过的落进曲目表，批注从账本补。

        这是"今天已经评过、再点执行也没歌可评"时曲目表还能有内容的关键——
        分数在服务端，批注在本地账本，两边拼起来才是完整的一行。
        跨设备时服务端标记可能滞后：本机账本里已提交的，不能被降级成"待评"。
        """
        # 跨天后的第一次刷新：先清掉昨天的行，别让两天的曲目堆在一起
        today = date.today().isoformat()
        if today != self._track_day:
            self._track_list.clear()
            self._track_groups.clear()
            self._track_day = today
        elif replace:
            # 同一页重复同步时重建，避免旧批次/旧运行的行越堆越多
            self._track_list.clear()
        entries = {}
        try:
            for entry in TrackLog().day():
                name = str(entry.get("song") or "")
                if name:
                    entries[name] = entry
        except Exception:
            entries = {}
        server_names = set()
        for task in works or []:
            try:
                server_names.add(str((task.get("work") or {}).get("name") or ""))
            except Exception:
                pass
        # 基础曲目的歌名：用来给没有显式分组的行补分组
        base_names = {
            str((task.get("work") or {}).get("name") or "")
            for task in (works or [])
            if task.get("_group") == "base"
        }
        grouped = any(task.get("_group") for task in (works or []))

        def group_for(name: str) -> str:
            """分组优先取服务端标记；整份清单都没标记时按基础处理（不误裁）。"""
            known = self._track_groups.get(name, "")
            if known:
                return known
            return "base" if (not grouped or name in base_names) else "extra"

        # 先把**整份清单**（含稍后被上限裁掉的）的分组记下来：
        # 评分回调晚到的那一行还要按 extra 继续受每日上限约束。
        for task in works or []:
            try:
                work = task.get("work") or {}
                name = str(work.get("name") or "")
            except Exception:
                continue
            if not name:
                continue
            group = str(task.get("_group") or "") or group_for(name)
            # 基础任务即使也被额外清单列出来，也必须留在 base 组：
            # 否则会被算进额外 15 首上限，曲目表从 20 行被裁成 15 行
            if name in base_names:
                group = "base"
            self._track_groups[name] = group
        notes = {name: str(entry.get("note") or "")
                 for name, entry in entries.items()}
        added = 0
        for task in works or []:
            try:
                work = task.get("work") or {}
                name = str(work.get("name") or "")
            except Exception:
                continue
            if not name:
                continue
            local = entries.get(name) or {}
            # 没有本机记录时 local_state 必须是空，不能默认成 submitted，
            # 否则服务端说「待评」的歌会被误标成「已提交」（桌面端恒 20/20 的根因）
            local_state = (str(local.get("state") or STATE_SUBMITTED)
                           if local else "")
            task_score = str(task.get("score") or "").strip()
            # 有分数就说明已经评过，completed 标记偶尔滞后
            server_done = bool(task.get("completed")) or bool(task_score)
            if server_done or local_state == STATE_SUBMITTED:
                state = "done"
            elif local_state in ("skipped", "failed"):
                state = local_state
            else:
                state = "pending"
            done = state == "done"
            score = str(task.get("score") or "")
            if not server_done:
                score = str(local.get("score") or "")
            self._track_list.add(
                name,
                meta=str(work.get("authorName") or ""),
                score=score if done else "",
                state=state,
                note=notes.get(name, ""),
                group=self._track_groups.get(name) or group_for(name),
            )
            added += 1
            if server_done:
                # 今天在手机端评过的歌，本机账本里没有；这里补记一条，
                # 否则「记录」页的"最近评过的曲子"会是空的。拿不到批注就留空。
                try:
                    TrackLog().record(
                        name,
                        artist=str(work.get("authorName") or ""),
                        score=str(task.get("score") or ""),
                        note=notes.get(name, ""),
                        group=self._track_groups.get(name, ""),
                    )
                except Exception:
                    pass
        # 服务端待评清单会随着评分缩水；本机账本里的今日曲目要补回来，
        # 否则额外任务评完/跳过后再打开，曲目表就只剩基础那几首。
        for name, entry in entries.items():
            if self._track_list.contains(name):
                continue
            state = str(entry.get("state") or STATE_SUBMITTED)
            if state == STATE_SUBMITTED:
                state = "done"
            elif state not in ("skipped", "failed"):
                state = "pending"
            # 只有已提交的可以脱离服务端清单保留；旧的跳过行不再补回来，
            # 否则清单换批次后越堆越多（手机端出现 20/41 的来源）
            if state != "done" and name not in server_names:
                continue
            # 本机记录里的分组优先（跨会话保留），其次用本次清单的分组
            group = (str(entry.get("group") or "")
                     or self._track_groups.get(name) or group_for(name))
            if name in base_names:
                group = "base"
            self._track_groups[name] = group
            self._track_list.add(
                name,
                meta=str(entry.get("artist") or ""),
                score=str(entry.get("score") or "") if state == "done" else "",
                state=state,
                note=str(entry.get("note") or ""),
                group=group,
            )
            added += 1
        # 基础 5 + 额外最多 15：服务端多返回的旧批次行不展示
        self._cap_tracks()
        if added:
            # 不在执行中时（启动 / 切回今日页的同步），状态陈述也跟着服务端刷新
            if not self._is_any_worker_running():
                total = self._track_list.count()
                done = self._track_list.done_count()
                if done:
                    self._set_status(f"今天已完成 {done}/{total} 首。", "successText")
                else:
                    self._set_status(f"今天还有 {total} 首待评。", "subtitle")
            self._refresh_rail()

    def _on_note(self, song: str, score: str, note: str) -> None:
        """批注提交成功：填到对应曲目行上、写进账本、更新右栏计数。"""
        if not note:
            return
        self._track_list.add(song, score=str(score), state="done",
                             note=note, group=self._group_for(song))
        self._cap_tracks()
        try:
            TrackLog().record(song, score=str(score), note=note,
                              group=self._group_for(song))
        except Exception:
            pass
        self._refresh_rail()

    def _on_cloud_progress(self, pct: int) -> None:
        """云端阶段进度（0-100）。"""
        self._update_progress(pct)

    def _update_progress(self, pct: int) -> None:
        """单调推进，避免阶段粗粒度进度回退覆盖更精确的歌曲进度。"""
        applied = self._meter.set_progress(max(0, min(100, int(pct))))
        self._percent_label.setText(f"{applied}%")

    def _on_finished(self, ok: bool, status: str, kind: str = "") -> None:
        """本地 worker 完成：按 status 显示 success/cancelled/failed。"""
        self._set_run_buttons_enabled(True)
        # 没轮到的行不能一直挂着"待评"（今天额度用完时最明显）
        self._track_list.settle_pending()
        if status == "success":
            # 额外任务通常是「已评过所以跳过」：算进今日完成数，而不是只算基础 5 首
            self._track_list.mark_extra_skipped_done()
            try:
                for row in self._track_list.rows_with_state("done"):
                    if row.group == "extra" and not row.score:
                        TrackLog().record(
                            row.song, artist=row.meta, note=row.note,
                            group=row.group)
            except Exception:
                pass
        # 跳过的歌也记进今日账本：下次再打开时，额外任务即使不在服务端待评清单里，
        # 曲目表也能把它们以「跳过」显示出来，而不是只剩基础那 5 首。
        # 取消/失败时不记：那些歌还没真正轮过，下次仍该显示为待评。
        if status == "success":
            try:
                for row in self._track_list.rows_with_state("skipped"):
                    TrackLog().record(
                        row.song, artist=row.meta, score=row.score,
                        note=row.note, state=STATE_SKIPPED, group=row.group)
            except Exception:
                pass

        if status == "success":
            notes = self._track_list.note_count()
            skipped = len(self._track_list.rows_with_state("skipped"))
            done = self._track_list.done_count()
            # 分组缺失的行（极少见）按基础算，保证分项加起来等于总数
            base_done = (self._track_list.count_by_group("base")
                         + self._track_list.count_by_group(""))
            extra_done = self._track_list.count_by_group("extra")
            has_extra = self._track_list.count_by_group("extra", state=None) > 0

            head = f"今日已完成 {done} 首"
            if has_extra:
                head += f"（基础 {base_done} 首、额外 {extra_done} 首）"
            if skipped:
                head += f"，跳过 {skipped} 首"
            if notes:
                head += f"，留下 {notes} 条批注"
            summary = "成功，" + head
            self._set_status(head + "。", "successText")
            self._meter.set_state("success")
            self._meter.set_progress(100)
            self._percent_label.setText("100%")
            self._show_hint("")
        elif status == "cancelled":
            summary = "用户手动取消任务"
            self._set_status("这次被你取消了，已经评完的曲目都还在。", "warningText")
            self._meter.set_state("cancelled")
            self._show_hint("")
        else:
            summary = "任务执行失败"
            label = errors.LABELS.get(kind, "")
            self._set_status(f"这次没跑完：{label}。" if label else "这次没跑完。",
                             "dangerText")
            self._meter.set_state("failed")
            self._show_hint(errors.HINTS.get(kind, ""))
            # 失败时把运行详情自动展开——这是"过程可见"的兜底
            self._set_detail_visible(True)

        try:
            self._step_list.addStep("任务结果", status, 0.0)
        except Exception:
            pass
        try:
            TaskHistory().record(ok, summary)
        except Exception:
            pass
        # 今天已经评完（这次没评到任何一首）时，曲目表要回落到账本里的记录，
        # 不能因为"本次运行清空了列表"就显示成空状态。
        if self._track_list.count() == 0:
            self._load_today_from_log()
        self._refresh_rail()

    def _show_hint(self, text: str) -> None:
        self._hint_label.setText(text)
        self._hint_label.setVisible(bool(text))

    def _on_cloud_log(self, line: str) -> None:
        self._log_view.appendLog(line)

    def _on_cloud_finished(self, ok: bool, msg: str) -> None:
        """云端 worker 完成（ok 由 conclusion=='success' 决定）。"""
        self._set_run_buttons_enabled(True)

        if ok:
            summary = "云端执行成功"
            self._set_status("云端跑完了。曲目与批注请在「记录」里回看。", "successText")
            self._meter.set_state("success")
            self._meter.set_progress(100)
            self._percent_label.setText("100%")
            if msg:
                self._log_view.appendLog(f"Run 详情（可复制）：{msg}")
        elif msg.startswith("已取消"):
            summary = "云端任务已取消"
            self._set_status("已取消云端任务。", "warningText")
            self._meter.set_state("cancelled")
        elif msg.startswith("取消远端失败"):
            summary = f"云端任务取消失败（{msg}）"
            self._set_status(msg, "warningText")
            self._meter.set_state("cancelled")
        else:
            summary = f"云端执行未完成（{msg}）"
            self._set_status(f"云端没跑完：{msg}", "dangerText")
            self._meter.set_state("failed")
            self._set_detail_visible(True)

        try:
            TaskHistory().record(ok, "云端执行 " + (msg if not ok else "success"))
        except Exception:
            pass
        self._refresh_rail()
        self.cloud_finished_sig.emit(ok, msg)
