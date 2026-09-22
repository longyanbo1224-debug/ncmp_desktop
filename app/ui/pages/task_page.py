"""任务执行页：StepList + LogView + 执行/取消按钮 + QProgressBar。

支持两种执行模式：
    - 本地执行：TaskWorker 调 core.bot.MusicPartnerBot.run()，拿歌曲级进度
    - 云端执行：CloudWorker 触发 GitHub Actions workflow_dispatch 并轮询状态，
      无歌曲级进度（GitHub 不暴露 per-song），复用 StepList 的步骤行展示
      触发 / 等待 / 完成三阶段。

TaskWorker 实例由 MainWindow 注入，避免重复构造/重复连接。
连接 ``TaskWorker`` 信号：
    step    -> StepList.updateStep
    progress-> StepList.addProgress + ProgressBar 更新
    finished_sig -> 按钮/进度条状态收尾
"""
from typing import Optional, Tuple

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)

from app.cookie_store import CookieStore
from app.task_history import TaskHistory
from app.ui.icons import (
    COLOR_DANGER, COLOR_PENDING, COLOR_SUCCESS, ICON_EMPTY_HISTORY, ICON_RUN,
    op_icon,
)
from app.ui.widgets.log_view import GuiLogHandler, LogView
from app.ui.widgets.step_list import StepList
from app.workers.cloud_worker import CloudWorker
from app.workers.task_worker import TaskWorker

# keyring 服务名（与 CookieStore / Config 对齐，gh_token 同 service 不同 key）
_KEYRING_SERVICE = "ncmp-desktop"

# 本地任务阶段 → 粗粒度进度百分比（歌曲级 on_progress 会在阶段内继续细化）
_LOCAL_STEP_PROGRESS = {
    "验证用户信息": 5,
    "拉取每日任务": 15,
    "评分基础任务": 35,
    "额外评分任务": 75,
}


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
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        # 顶部按钮组
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._run_btn = QPushButton("立即执行(本地)")
        self._run_btn.setObjectName("primaryButton")
        self._run_btn.setIcon(op_icon(ICON_RUN))
        self._run_btn.setIconSize(QSize(16, 16))
        self._run_btn.clicked.connect(self.execute)
        self._cloud_btn = QPushButton("云端执行")
        self._cloud_btn.setObjectName("secondaryButton")
        self._cloud_btn.setIcon(op_icon(ICON_RUN))
        self._cloud_btn.setIconSize(QSize(16, 16))
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

        # 进度条
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        outer.addWidget(self._progress)

        # 中间：StepList 与 LogView 用 splitter 分屏
        splitter = QSplitter(Qt.Vertical)
        self._step_list = StepList()
        self._log_view = LogView()
        splitter.addWidget(self._step_list)
        splitter.addWidget(self._log_view)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter, 1)

        # 状态行
        self._status_label = QLabel("待执行")
        self._status_label.setObjectName("captionText")
        outer.addWidget(self._status_label)

        # 最近任务摘要（空状态：无历史时给引导而非空白）
        self._summary_icon = QLabel()
        self._summary_icon.setFixedSize(16, 16)
        self._summary_text = QLabel("")
        self._summary_text.setObjectName("captionText")
        summary_row = QHBoxLayout()
        summary_row.setSpacing(8)
        summary_row.setContentsMargins(0, 0, 0, 0)
        summary_row.addWidget(self._summary_icon)
        summary_row.addWidget(self._summary_text, 1)
        summary_row.addStretch(0)
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
        self._step_list.clear()
        self._progress.setValue(0)
        self._status_label.setText("执行中…")
        self._status_label.setObjectName("captionText")
        try:
            self._status_label.style().polish(self._status_label)
        except Exception:
            pass
        self._set_run_buttons_enabled(False)
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
        # 构造 CloudWorker，连接信号，启动
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
        self._step_list.clear()
        self._progress.setValue(0)
        self._status_label.setText("云端执行中…")
        self._set_run_buttons_enabled(False)
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
    # 云端辅助
    # ------------------------------------------------------------------
    def _load_cloud_config(self) -> Tuple[str, str, str, str, str]:
        """读取 GitHub Actions 配置。

        gh_token 走 keyring（与 CookieStore 同 service，key="gh_token"），
        其余走 Config（setting.json / env）。任一缺失返回 missing 字段名。
        """
        # gh_token
        token = ""
        try:
            import keyring
            if keyring is not None:
                token = keyring.get_password(_KEYRING_SERVICE, "gh_token") or ""
        except Exception:
            token = ""
        # gh_repo / workflow_name / workflow_branch 从 Config 读
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
            self._summary_icon.setPixmap(
                op_icon(ICON_EMPTY_HISTORY, COLOR_PENDING).pixmap(QSize(16, 16)))
            self._summary_text.setText("暂无任务记录，点上方执行开始第一次任务")
            return
        item = recent[0]
        ts = item.get("ts", "")
        summary = item.get("summary", "")
        success = item.get("success", False)
        color = COLOR_SUCCESS if success else COLOR_DANGER
        icon_name = "fa5s.check-circle" if success else "fa5s.times-circle"
        self._summary_icon.setPixmap(op_icon(icon_name, color).pixmap(QSize(16, 16)))
        marker = "成功" if success else "失败"
        self._summary_text.setText(f"最近任务：{marker} {summary}（{ts}）")

    # ------------------------------------------------------------------
    # 槽
    # ------------------------------------------------------------------
    def _on_step(self, name: str, status: str, elapsed: float) -> None:
        self._step_list.updateStep(name, status, elapsed)
        base = _LOCAL_STEP_PROGRESS.get(name)
        if base is not None and status in ("running", "success"):
            self._update_progress(base)

    def _on_progress(self, done: int, total: int, song: str, score: str) -> None:
        # 初始进度（song/score 为空）只刷新进度条，不在步骤树里挂空行
        if song or score:
            self._step_list.addProgress(done, total, song, score)
        if total and total > 0:
            pct = int(done * 100 / total)
            self._update_progress(pct)

    def _on_cloud_progress(self, pct: int) -> None:
        """云端阶段进度（0-100）。"""
        self._update_progress(pct)

    def _update_progress(self, pct: int) -> None:
        """单调推进进度条，避免阶段粗粒度进度回退覆盖更精确的歌曲进度。"""
        pct = max(0, min(100, int(pct)))
        if pct >= self._progress.value():
            self._progress.setValue(pct)

    def _on_finished(self, ok: bool, status: str) -> None:
        """本地 worker 完成：按 status 显示 success/cancelled/failed 文案。

        :param ok: 成功与否（cancelled/failed 均为 False）。
        :param status: "success" / "cancelled" / "failed"。
        """
        self._set_run_buttons_enabled(True)
        if status == "success":
            summary = "任务执行完成"
            text = "✅ 任务执行完成"
            obj_name = "successText"
            self._progress.setValue(100)
        elif status == "cancelled":
            summary = "用户手动取消任务"
            text = "⚠️ 用户手动取消任务"
            obj_name = "warningText"
        else:
            summary = "任务执行失败"
            text = "❌ 任务执行失败"
            obj_name = "dangerText"
        self._status_label.setText(text)
        self._status_label.setObjectName(obj_name)
        # objectName 改变后需重新 polish 才能套上新样式
        try:
            self._status_label.style().polish(self._status_label)
        except Exception:
            pass
        # 在步骤视图追加一行任务结果（按 status 显示对应图标）
        try:
            self._step_list.addStep("任务结果", status, 0.0)
        except Exception:
            pass
        # 持久化任务结果，供首页摘要展示
        try:
            TaskHistory().record(ok, summary)
        except Exception:
            pass
        # 刷新本页最近任务摘要
        self._refresh_history_summary()

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
            self._status_label.setText("云端执行成功")
            self._progress.setValue(100)
            if msg:
                # 追加 html_url（QPlainTextEdit 不渲染可点链接，但可复制）
                self._log_view.appendLog(f"Run 详情（可复制）：{msg}")
        elif msg.startswith("已取消"):
            summary = "云端任务已取消"
            self._status_label.setText("⚠️ 已取消云端任务")
            self._status_label.setObjectName("warningText")
            try:
                self._status_label.style().polish(self._status_label)
            except Exception:
                pass
        elif msg.startswith("取消远端失败"):
            summary = f"云端任务取消失败（{msg}）"
            self._status_label.setText(f"⚠️ {msg}")
            self._status_label.setObjectName("warningText")
            try:
                self._status_label.style().polish(self._status_label)
            except Exception:
                pass
        else:
            summary = f"云端执行未完成（{msg}）"
            self._status_label.setText(summary)
        try:
            TaskHistory().record(ok, "云端执行 " + (msg if not ok else "success"))
        except Exception:
            pass
        self._refresh_history_summary()
        # 通知主窗口（托盘通知 + 首页摘要）
        self.cloud_finished_sig.emit(ok, msg)
