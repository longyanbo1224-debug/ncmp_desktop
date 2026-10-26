"""任务执行页 —— 一台仪器。

按钮组 + **分段电平表** + 步骤列表／日志分屏 + 状态行 + 最近任务摘要。

电平表（:class:`~app.ui.widgets.meter.LevelMeter`）是本页的主角，
也是全程序唯一的高光元素。它替掉了原来的 ``QProgressBar``。

支持两种执行模式：
    - 本地执行：TaskWorker 调 core.bot.MusicPartnerBot.run()，拿歌曲级进度
    - 云端执行：CloudWorker 触发 GitHub Actions workflow_dispatch 并轮询状态，
      无歌曲级进度（GitHub 不暴露 per-song），复用 StepList 的步骤行展示
      触发 / 等待 / 完成三阶段。

TaskWorker 实例由 MainWindow 注入，避免重复构造/重复连接。

**图标语言的划分**：步骤列表负责图标，状态行只负责颜色。
原来状态行里塞 ``✅ ⚠️ ❌`` emoji，和步骤树的图标是两套语言，属于噪音，已去掉。
"""
from typing import Optional, Tuple

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSplitter,
    QVBoxLayout, QWidget,
)

from app.cookie_store import CookieStore
from app.task_history import TaskHistory
from app.ui import theme
from app.ui.icons import ICON_RUN, op_icon, result_icon, step_icon
from app.ui.widgets.log_view import GuiLogHandler, LogView
from app.ui.widgets.meter import LevelMeter
from app.ui.widgets.step_list import StepList
from app.workers.cloud_worker import CloudWorker
from app.workers.task_worker import TaskWorker
from core.utils import errors

# keyring 服务名（与 CookieStore / Config 对齐，gh_token 同 service 不同 key）
_KEYRING_SERVICE = "ncmp desktop"

# 本地任务阶段 → 该阶段在总进度里占的区间 (起始%, 结束%)。
#
# 为什么用区间而不是单个锚点：阶段内的歌曲进度要在**本阶段区间内**插值。
# 早期版本把"本阶段第 N 首 / 本阶段共 M 首"直接当成全局 0-100%，
# 于是基础评分阶段刚跑完一半，进度条就已经顶到 100%。
#
# 两个评分阶段在 8~100 之间**按条目数分配**（见 _plan_scoring），
# 这里的值是"还没拿到条目数"时的兜底。兜底刻意偏保守：宁可在基础阶段
# 少报，也不要在额外任务开始时就已经跑到 65%——用户实际遇到的就是这个问题
# （基础 5 首、额外 15 条，额外是大头却只分到 35%）。
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


def _short_ts(ts: str) -> str:
    """2026-10-14T09:02:11 → 10-14 09:02。解析失败原样返回，不崩。"""
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(ts)).strftime("%m-%d %H:%M")
    except Exception:
        return str(ts)


class TaskPage(QWidget):
    """任务执行页。"""

    goto_login = Signal()  # Cookie 预检失败时通知主窗口跳登录页
    goto_settings = Signal()  # 云端预检失败时通知主窗口跳设置页
    # 云端 worker 完成（ok, msg）；定时器 + 手动按钮都走这条通知主窗口
    cloud_finished_sig = Signal(bool, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._log_handler: Optional[GuiLogHandler] = None
        self._worker: Optional[TaskWorker] = None
        self._cloud_worker: Optional[CloudWorker] = None
        self._current_phase: str = ""   # 当前阶段名，供歌曲进度在阶段区间内插值
        # 阶段区间。开局是兜底值，拿到条目数后由 _plan_scoring 重算。
        self._phase_span: dict = dict(_PHASE_SPAN)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.PAGE_MARGIN, theme.PAGE_MARGIN,
                                 theme.PAGE_MARGIN, theme.PAGE_MARGIN)
        outer.setSpacing(theme.SP_4)

        # ---- 顶部按钮组 ----
        actions = QHBoxLayout()
        actions.setSpacing(theme.SP_2)

        self._run_btn = QPushButton("立即执行")
        self._run_btn.setObjectName("primaryButton")
        self._run_btn.setIcon(op_icon(ICON_RUN, theme.PANEL))
        self._run_btn.setIconSize(QSize(15, 15))
        self._run_btn.clicked.connect(self.execute)

        self._cloud_btn = QPushButton("云端执行")
        self._cloud_btn.setObjectName("secondaryButton")
        self._cloud_btn.setIcon(op_icon(ICON_RUN, theme.INK))
        self._cloud_btn.setIconSize(QSize(15, 15))
        self._cloud_btn.clicked.connect(self.execute_cloud)

        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.setObjectName("secondaryButton")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self.cancel)

        actions.addWidget(self._run_btn)
        actions.addWidget(self._cloud_btn)
        actions.addWidget(self._cancel_btn)
        actions.addStretch(1)
        outer.addLayout(actions)

        # ---- 电平表 + 百分比读数 ----
        meter_row = QHBoxLayout()
        meter_row.setSpacing(theme.SP_3)
        self._meter = LevelMeter()
        meter_row.addWidget(self._meter, 1)
        # 百分比是**读数**不是主角，所以用等宽小字放右边，不做成大数字
        self._percent_label = QLabel("0%")
        self._percent_label.setObjectName("dataTextMuted")
        self._percent_label.setFixedWidth(40)
        self._percent_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        meter_row.addWidget(self._percent_label)
        outer.addLayout(meter_row)

        outer.addSpacing(theme.SP_2)

        # ---- 步骤列表 / 日志 分屏 ----
        splitter = QSplitter(Qt.Vertical)
        self._step_list = StepList()
        self._log_view = LogView()
        # 日志也带一个标题，和上面的「任务步骤」对称
        log_pane = QWidget()
        log_lay = QVBoxLayout(log_pane)
        log_lay.setContentsMargins(0, 0, 0, 0)
        log_lay.setSpacing(theme.SP_2)
        log_title = QLabel("日志")
        log_title.setObjectName("sectionHeading")
        log_lay.addWidget(log_title)
        log_lay.addWidget(self._log_view, 1)
        splitter.addWidget(self._step_list)
        splitter.addWidget(log_pane)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setChildrenCollapsible(False)
        outer.addWidget(splitter, 1)

        # ---- 状态行 ----
        self._status_label = QLabel("待执行")
        self._status_label.setObjectName("captionText")
        outer.addWidget(self._status_label)

        # ---- 失败提示：只在失败时出现，直接告诉用户下一步做什么 ----
        self._hint_label = QLabel("")
        self._hint_label.setObjectName("captionText")
        self._hint_label.setWordWrap(True)
        self._hint_label.setVisible(False)
        outer.addWidget(self._hint_label)

        # ---- 最近任务摘要（空状态：无历史时给引导而非空白）----
        self._summary_icon = QLabel()
        self._summary_icon.setFixedSize(15, 15)
        self._summary_text = QLabel("")
        self._summary_text.setObjectName("captionText")
        summary_row = QHBoxLayout()
        summary_row.setSpacing(theme.SP_2)
        summary_row.setContentsMargins(0, 0, 0, 0)
        summary_row.addWidget(self._summary_icon)
        summary_row.addWidget(self._summary_text, 1)
        outer.addLayout(summary_row)

        self._refresh_history_summary()

    # ------------------------------------------------------------------
    # 对外
    # ------------------------------------------------------------------
    def set_worker(self, worker: TaskWorker) -> None:
        """注入 TaskWorker 实例并连接信号。"""
        if self._worker is not None:
            try:
                self._worker.step.disconnect()
                self._worker.progress.disconnect()
                self._worker.finished_sig.disconnect()
            except Exception:
                pass
        self._worker = worker
        self._worker.step.connect(self._on_step)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_sig.connect(self._on_finished)

    def install_log_handler(self, handler: GuiLogHandler) -> None:
        """供 MainWindow 把共享的 GuiLogHandler 挂进来。"""
        if handler is None:
            return
        # 首次连接即可；PySide6 对未连接的 signal 调 disconnect 只打 RuntimeWarning
        # （try 捕获不到），用标志位避免重复 connect。
        if getattr(self, '_log_handler', None) is None:
            handler.log_signal.connect(self._log_view.appendLog)
        self._log_handler = handler

    def execute(self, notify_context: str = "task") -> None:
        """启动本地任务。

        :param notify_context: "task"=手动执行（默认，读 notify_on_task_done），
                                "schedule"=定时执行（读 notify_on_schedule）。
        """
        if self._worker is None:
            self._status_label.setText("未注入 TaskWorker")
            return
        # Cookie 预检：未配置则不启动 worker，提示并引导登录
        try:
            music_u, csrf, _ = CookieStore().load()
        except Exception:
            music_u, csrf = "", ""
        if not (music_u and csrf):
            self._status_label.setText("未配置 Cookie，请先登录")
            self.goto_login.emit()
            return
        if self._is_any_worker_running():
            self._status_label.setText("已有任务在执行")
            return

        self._begin_run("执行中…", "running")
        # 由 MainWindow 注入 config/session；若未注入则 worker 内部现取现造
        # notify_context 决定走 notify_on_task_done 还是 notify_on_schedule
        self._worker.start_task(notify_context=notify_context)

    def execute_cloud(self) -> None:
        """启动云端任务：触发 GitHub Actions workflow_dispatch。"""
        if self._is_any_worker_running():
            self._status_label.setText("已有任务在执行")
            return
        # 前置检查：读 gh_token (keyring) + gh_repo/workflow_name/branch (Config)
        token, repo, workflow, branch, missing = self._load_cloud_config()
        if missing:
            self._status_label.setText(
                f"未配置 GitHub Actions（缺 {missing}），请先到设置页填写")
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
            self._status_label.setText("正在取消…")
            self._worker.cancel()
            return
        if self._cloud_worker is not None and self._cloud_worker.isRunning():
            self._status_label.setText("正在取消云端任务…")
            self._cloud_worker.cancel()

    # ------------------------------------------------------------------
    # 运行态辅助
    # ------------------------------------------------------------------
    def _begin_run(self, status_text: str, meter_state: str) -> None:
        """一次执行开始时的统一收尾：清空视图、归零电平表、锁按钮。"""
        self._step_list.clear()
        self._meter.reset()
        self._meter.set_state(meter_state)
        self._percent_label.setText("0%")
        self._current_phase = ""
        self._phase_span = dict(_PHASE_SPAN)
        self._show_hint("")
        self._set_status(status_text, "captionText")
        self._set_run_buttons_enabled(False)

    def _set_status(self, text: str, obj_name: str) -> None:
        """改状态行文案 + 语义色。

        状态行的颜色由 objectName 决定（见 theme.py 的 ``*Text`` 规则），
        objectName 变了必须重新 polish 才会套上新样式。
        """
        self._status_label.setText(text)
        self._status_label.setObjectName(obj_name)
        try:
            self._status_label.style().polish(self._status_label)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 云端辅助
    # ------------------------------------------------------------------
    def _load_cloud_config(self) -> Tuple[str, str, str, str, str]:
        """读取 GitHub Actions 配置。

        gh_token 走 keyring（与 CookieStore 同 service，key="gh_token"），
        其余走 Config（setting.json / env）。任一缺失返回 missing 字段名。
        """
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

    def _refresh_history_summary(self) -> None:
        """读 TaskHistory 最近一条；无历史时显示空状态引导。"""
        try:
            recent = TaskHistory().load_recent(1)
        except Exception:
            recent = []
        if not recent:
            self._summary_icon.clear()
            self._summary_text.setText("暂无任务记录，点上方执行开始第一次任务")
            return
        item = recent[0]
        ts = _short_ts(item.get("ts", ""))
        summary = item.get("summary", "")
        ok = bool(item.get("success", False))
        # 图标和状态词必须同色：取消用琥珀"禁止"，别用红叉（那是失败）
        cancelled = "取消" in str(summary)
        if ok:
            marker, icon_pm = "成功", result_icon(True)
        elif cancelled:
            marker, icon_pm = "取消", step_icon("cancelled")
        else:
            marker, icon_pm = "失败", result_icon(False)
        self._summary_icon.setPixmap(icon_pm.pixmap(QSize(16, 16)))
        self._summary_text.setText(f"最近任务：{marker}　{summary}（{ts}）")

    # ------------------------------------------------------------------
    # 槽
    # ------------------------------------------------------------------
    def _plan_scoring(self, base_total: int) -> None:
        """按条目数把 8~100 分给两个评分阶段。

        基础任务的条目数在它开始时就知道（``on_progress(0, total, ...)``），
        额外任务的要等它自己开始时才知道，所以这里用一个估计值：
        ``full_extra_tasks`` 关闭时额外固定 7 条，可以算准；
        打开时条目数不定，按"额外通常是基础的数倍"给额外阶段大头。

        估计偏保守是刻意的——宁可在基础阶段少报一点，
        也不要在额外任务开始时进度条已经跑到高位（这正是用户反馈的问题）。
        """
        if base_total <= 0:
            return
        try:
            from core.utils.config import Config
            full = bool(Config().get("full_extra_tasks", False))
        except Exception:
            full = False
        extra_est = (_EXTRA_WHEN_LIMITED if not full
                     else base_total * _EXTRA_WHEN_FULL_RATIO)
        if extra_est <= 0:
            return
        span = _SCORING_HI - _SCORING_LO
        base_hi = _SCORING_LO + int(round(span * base_total / (base_total + extra_est)))
        # 夹住，别让基础阶段把整个区间吃光或退化成 0
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
            # 进入新阶段：进度跳到该阶段起点，并记下当前阶段供歌曲进度插值
            self._current_phase = name
            self._update_progress(lo)
        elif status in ("success", "failed"):
            # 阶段结束：推到该阶段终点。failed 也算结束，不该把进度条卡住。
            self._update_progress(hi)
            if self._current_phase == name:
                self._current_phase = ""

    def _on_progress(self, done: int, total: int, song: str, score: str) -> None:
        # 初始进度（song/score 为空）只刷新进度条，不在步骤树里挂空行
        if song or score:
            self._step_list.addProgress(done, total, song, score)
        if not total or total <= 0:
            return
        # 基础阶段开局会先报一次 0/total，正好用来拿到条目数重排两个评分阶段的区间
        if done == 0 and self._current_phase == "评分基础任务":
            self._plan_scoring(int(total))
        # 关键：在本阶段区间内插值，而不是映射到全局 0-100%
        lo, hi = self._phase_span.get(self._current_phase, (0, 100))
        frac = max(0.0, min(1.0, float(done) / float(total)))
        self._update_progress(int(round(lo + (hi - lo) * frac)))

    def _on_cloud_progress(self, pct: int) -> None:
        """云端阶段进度（0-100）。"""
        self._update_progress(pct)

    def _update_progress(self, pct: int) -> None:
        """单调推进，避免阶段粗粒度进度回退覆盖更精确的歌曲进度。"""
        applied = self._meter.set_progress(max(0, min(100, int(pct))))
        self._percent_label.setText(f"{applied}%")

    def _on_finished(self, ok: bool, status: str, kind: str = "") -> None:
        """本地 worker 完成：按 status 显示 success/cancelled/failed。

        :param ok: 成功与否（cancelled/failed 均为 False）。
        :param status: "success" / "cancelled" / "failed"。
        :param kind: 失败原因分类（见 core/utils/errors.py），成功时为空。
        """
        self._set_run_buttons_enabled(True)

        if status == "success":
            summary = "任务执行完成"
            self._set_status("任务执行完成", "successText")
            self._meter.set_state("success")
            self._meter.set_progress(100)
            self._percent_label.setText("100%")
            self._show_hint("")
        elif status == "cancelled":
            summary = "用户手动取消任务"
            self._set_status("用户手动取消任务", "warningText")
            self._meter.set_state("cancelled")
            self._show_hint("")
        else:
            summary = "任务执行失败"
            label = errors.LABELS.get(kind, "")
            self._set_status(f"任务执行失败：{label}" if label else "任务执行失败",
                             "dangerText")
            self._meter.set_state("failed")
            # 分类的意义就在这一行：告诉非技术用户现在该干什么
            self._show_hint(errors.HINTS.get(kind, ""))

        # 在步骤视图追加一行任务结果
        try:
            self._step_list.addStep("任务结果", status, 0.0)
        except Exception:
            pass
        # 持久化任务结果，供首页记录表展示
        try:
            TaskHistory().record(ok, summary)
        except Exception:
            pass
        self._refresh_history_summary()

    def _show_hint(self, text: str) -> None:
        """显示/隐藏失败提示。"""
        self._hint_label.setText(text)
        self._hint_label.setVisible(bool(text))

    def _on_cloud_log(self, line: str) -> None:
        """云端 worker 的单行日志直接追加到 LogView。"""
        self._log_view.appendLog(line)

    def _on_cloud_finished(self, ok: bool, msg: str) -> None:
        """云端 worker 完成（ok 由 conclusion=='success' 决定）。

        :param msg: 成功时为 html_url；失败时为错误描述/conclusion。
        """
        self._set_run_buttons_enabled(True)

        if ok:
            summary = "云端执行成功"
            self._set_status("云端执行成功", "successText")
            self._meter.set_state("success")
            self._meter.set_progress(100)
            self._percent_label.setText("100%")
            if msg:
                # 追加 html_url（QPlainTextEdit 不渲染可点链接，但可复制）
                self._log_view.appendLog(f"Run 详情（可复制）：{msg}")
        elif msg.startswith("已取消"):
            summary = "云端任务已取消"
            self._set_status("已取消云端任务", "warningText")
            self._meter.set_state("cancelled")
        elif msg.startswith("取消远端失败"):
            summary = f"云端任务取消失败（{msg}）"
            self._set_status(msg, "warningText")
            self._meter.set_state("cancelled")
        else:
            summary = f"云端执行未完成（{msg}）"
            self._set_status(summary, "dangerText")
            self._meter.set_state("failed")

        try:
            TaskHistory().record(ok, "云端执行 " + (msg if not ok else "success"))
        except Exception:
            pass
        self._refresh_history_summary()
        # 通知主窗口（托盘通知 + 首页摘要）
        self.cloud_finished_sig.emit(ok, msg)
