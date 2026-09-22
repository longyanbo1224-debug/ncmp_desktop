"""主窗口：QStackedWidget 切 4 页 + 左侧 QListWidget 导航 + 托盘 + 后台验证线程。

closeEvent 拦截：按 ``AppConfig.close_action`` 决定直接关或最小化到托盘
（None=每次弹确认框，"close"=直接关，"minimize"=最小化到托盘）。
持有 TrayIcon + ValidateWorker + TaskWorker + LoginWorker 实例并连接信号。

本地定时执行：QTimer 单次触发 + 60s 心跳校准。
- schedule_mode: local=本地任务，cloud=云端 Actions，both=两者都启动
- 到点前发托盘通知「定时任务已启动」，本地完成由 _on_task_finished_from_tray 通知，
  云端完成由 TaskPage.cloud_finished_sig → _on_schedule_cloud_finished 通知。
"""
from datetime import datetime, timedelta
from typing import Optional, Tuple

from PySide6.QtCore import QSize, QTimer, Qt
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from app.app_config import AppConfig
from app.cookie_store import CookieStore
from app.notify.desktop_notify import DesktopNotify
from app.ui.icons import create_app_icon, nav_icon
from app.ui.pages.about_page import AboutPage
from app.ui.pages.dashboard_page import DashboardPage
from app.ui.pages.login_page import LoginPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.pages.task_page import TaskPage
from app.ui.widgets.log_view import GuiLogHandler
from app.ui.widgets.tray_icon import TrayIcon
from app.workers.task_worker import TaskWorker
from app.workers.validate_worker import ValidateWorker


class MainWindow(QMainWindow):
    """主窗口。"""

    def __init__(self, app_config: Optional[AppConfig] = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.app_config = app_config or AppConfig()
        self.setWindowTitle("ncmp desktop")
        self.setWindowIcon(create_app_icon())
        self.resize(960, 640)
        self.setMinimumSize(820, 540)

        self._log_handler: Optional[GuiLogHandler] = None
        self._build_ui()
        self._init_workers()
        self._connect_signals()
        # 本地定时器：到点触发；心跳每 60s 校准防漂移
        self._schedule_timer = QTimer(self)
        self._schedule_timer.setSingleShot(True)
        self._schedule_timer.timeout.connect(self._on_schedule_tick)
        self._schedule_heartbeat_timer = QTimer(self)
        self._schedule_heartbeat_timer.setSingleShot(False)
        self._schedule_heartbeat_timer.timeout.connect(self._setup_schedule)
        self._setup_schedule()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 左侧导航
        self._nav = QListWidget()
        self._nav.setObjectName("navList")
        self._nav.setFixedWidth(140)
        self._nav.setIconSize(QSize(18, 18))
        for text, key in (("首页", "home"), ("账号", "account"),
                          ("任务", "task"), ("设置", "settings"),
                          ("关于", "about")):
            item = QListWidgetItem(nav_icon(key), text)
            self._nav.addItem(item)
        self._nav.setCurrentRow(0)
        self._nav.currentRowChanged.connect(self._on_nav_changed)
        layout.addWidget(self._nav)

        # 右侧内容
        self._stack = QStackedWidget()
        self._dashboard = DashboardPage()
        self._login = LoginPage()
        self._task = TaskPage()
        self._settings = SettingsPage()
        self._about = AboutPage()
        self._stack.addWidget(self._dashboard)
        self._stack.addWidget(self._login)
        self._stack.addWidget(self._task)
        self._stack.addWidget(self._settings)
        self._stack.addWidget(self._about)
        self._stack.setCurrentIndex(0)
        layout.addWidget(self._stack, 1)

        self.setCentralWidget(central)

    # ------------------------------------------------------------------
    # 子组件
    # ------------------------------------------------------------------
    def _init_workers(self) -> None:
        # 托盘
        self._tray = TrayIcon(self)
        self._notify = DesktopNotify(self._tray)
        # 后台 Cookie 验证线程
        self._validate_worker = ValidateWorker(
            interval_sec=self.app_config.validate_interval_sec, parent=self)
        # 任务执行线程（MainWindow 持有，注入到 TaskPage 共享）
        self._task_worker = TaskWorker(parent=self)
        self._task.set_worker(self._task_worker)

    def _connect_signals(self) -> None:
        # Dashboard 快捷按钮
        self._dashboard.run_task.connect(self._goto_task_and_run)
        self._dashboard.goto_login.connect(lambda: self._goto_page(1))
        self._dashboard.goto_settings.connect(lambda: self._goto_page(3))
        self._dashboard.refresh_cookie.connect(self._refresh_cookie_status)

        # 登录成功 → 刷新 Cookie 卡片 + 跳回首页
        self._login.login_succeeded.connect(self._on_login_succeeded)

        # 任务页 Cookie 预检失败 → 跳登录页
        self._task.goto_login.connect(lambda: self._goto_page(1))
        self._task.goto_settings.connect(lambda: self._goto_page(3))
        # 云端 worker 完成 → 托盘通知（定时 + 手动都走这条）
        self._task.cloud_finished_sig.connect(self._on_schedule_cloud_finished)

        # 设置页定时配置保存 → 重排定时器
        self._settings.schedule_config_changed.connect(self._on_schedule_config_changed)

        # 托盘
        self._tray.show_main.connect(self._show_and_raise)
        self._tray.run_task.connect(self._goto_task_and_run)
        self._tray.refresh_cookie.connect(self._refresh_cookie_status)
        self._tray.about.connect(self._goto_about)
        self._tray.activated.connect(self._on_tray_activated)

        # 后台验证
        self._validate_worker.expired.connect(self._on_cookie_expired)
        self._validate_worker.status.connect(self._on_cookie_status)

        # 任务执行（共享 worker；finished 时给托盘通知）
        self._task_worker.finished_sig.connect(self._on_task_finished_from_tray)

    # ------------------------------------------------------------------
    # 对外
    # ------------------------------------------------------------------
    def install_log_handler(self, handler: GuiLogHandler) -> None:
        """把共享的 GuiLogHandler 挂到任务页的 LogView。"""
        self._log_handler = handler
        self._task.install_log_handler(handler)

    def start_background_workers(self) -> None:
        """启动后台线程：Cookie 定期验证 + 托盘显示。"""
        try:
            self._tray.show()
        except Exception:
            pass
        try:
            if not self._validate_worker.isRunning():
                self._validate_worker.start()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 槽
    # ------------------------------------------------------------------
    def _on_nav_changed(self, row: int) -> None:
        if 0 <= row < self._stack.count():
            self._stack.setCurrentIndex(row)
            if row == 1:
                # 进入登录页时启动扫码
                self._login.start()

    def _goto_page(self, index: int) -> None:
        self._nav.setCurrentRow(index)

    def _goto_task_and_run(self) -> None:
        self._show_and_raise()
        self._nav.setCurrentRow(2)
        self._task.execute()

    def _goto_about(self) -> None:
        """托盘「关于」入口：显示主窗口并跳关于页。"""
        self._show_and_raise()
        self._nav.setCurrentRow(4)

    def _refresh_cookie_status(self) -> None:
        self._dashboard.refresh_cookie_card()
        # 立即触发一次验证（如果 worker 在跑，先停再启会过于繁琐；这里仅在已停止时启动）
        if not self._validate_worker.isRunning():
            self._validate_worker.start()

    def _on_login_succeeded(self) -> None:
        """登录成功后：刷新 Cookie 卡片、提示 toast、跳回首页。"""
        self._dashboard.refresh_cookie_card()
        self._dashboard.show_toast("Cookie 已就绪，可立即执行任务")
        self._nav.setCurrentRow(0)

    def _show_and_raise(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_and_raise()

    def _on_cookie_expired(self, reason: str) -> None:
        self._notify.notify("ncmp Cookie 失效", reason)
        # 先把首页状态切到 EXPIRED，再跳登录页
        self._dashboard.set_cookie_status(False, reason)
        try:
            app = QApplication.instance()
            if app is not None:
                app.alert(self)
        except Exception:
            pass
        self._show_and_raise()
        self._nav.setCurrentRow(1)

    def _on_cookie_status(self, ok: bool, msg: str) -> None:
        # 不弹通知，仅把后台验证结果推给 Dashboard
        self._dashboard.set_cookie_status(ok, msg)

    def _on_task_finished_from_tray(self, ok: bool, status: str) -> None:
        """共享 TaskWorker 完成时的托盘通知 + 首页摘要。

        :param ok: 成功与否（cancelled/failed 均为 False）。
        :param status: "success" / "cancelled" / "failed"。
        """
        if status == "cancelled":
            msg = "用户手动取消任务"
        elif status == "success":
            msg = "任务执行完成"
        else:
            msg = "任务执行失败"
        self._notify.notify("ncmp 任务", msg)
        self._dashboard.set_last_task_summary(msg)

    # ------------------------------------------------------------------
    # 本地定时执行
    # ------------------------------------------------------------------
    def _on_schedule_config_changed(self) -> None:
        """设置页保存了定时配置 → 重读 AppConfig 并重排定时器。"""
        try:
            self.app_config.load()
        except Exception:
            pass
        self._setup_schedule()

    def _setup_schedule(self) -> None:
        """根据 AppConfig 重排定时器。幂等：重复调用不会改变目标触发时刻。

        - schedule_enabled=False：停掉定时器与心跳，直接返回
        - 计算到下一次 (HH:MM) 壁钟时刻的秒数，启动单次 QTimer
        - 启动 60s 心跳，每分钟重新调用本方法（防系统休眠/时钟漂移后失准）
        """
        try:
            enabled = self.app_config.schedule_enabled
            hhmm = self.app_config.schedule_time
        except Exception:
            enabled = False
            hhmm = "09:00"
        if not enabled:
            self._schedule_timer.stop()
            self._schedule_heartbeat_timer.stop()
            return
        secs = self._seconds_until_next(hhmm)
        # secs 可能为 0（恰好到点）→ 立刻触发
        ms = max(0, secs) * 1000
        # QTimer 在 32 位平台对超长 ms 溢出上限约 24 天；24h 内安全
        self._schedule_timer.start(ms)
        if not self._schedule_heartbeat_timer.isActive():
            self._schedule_heartbeat_timer.start(60 * 1000)

    @staticmethod
    def _seconds_until_next(hhmm: str) -> int:
        """到下一次 (HH:MM) 壁钟时刻（今天已过则取明天）的秒数。"""
        try:
            h_str, m_str = (hhmm or "09:00").split(":")
            h, m = int(h_str), int(m_str)
        except Exception:
            h, m = 9, 0
        now = datetime.now()
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target = target + timedelta(days=1)
        return max(0, int((target - now).total_seconds()))

    def _on_schedule_tick(self) -> None:
        """到点触发：按 schedule_mode 启动 local/cloud/both 任务。

        触发后由 _setup_schedule 在下次心跳中重排（目标已过 → 取明天）。
        本地完成由 _on_task_finished_from_tray 通知；云端由
        _on_schedule_cloud_finished 通知。
        """
        try:
            mode = self.app_config.schedule_mode
        except Exception:
            mode = "local"
        self._notify.notify("ncmp 定时任务", "定时任务已启动")
        if mode in ("local", "both"):
            try:
                # 定时执行走 notify_on_schedule 开关（而非 notify_on_task_done）
                self._task.execute(notify_context="schedule")
            except Exception as e:
                self._notify.notify("ncmp 定时任务", f"本地任务启动失败：{e}")
        if mode in ("cloud", "both"):
            try:
                self._task.execute_cloud()
            except Exception as e:
                self._notify.notify("ncmp 定时任务", f"云端任务启动失败：{e}")
        # 重排下一天的定时（心跳也会兜底）
        self._setup_schedule()

    def _on_schedule_cloud_finished(self, ok: bool, msg: str) -> None:
        """云端 worker 完成 → 托盘通知（定时 + 手动都走这条）。"""
        text = "云端任务完成：成功" if ok else f"云端任务完成：失败（{msg}）"
        self._notify.notify("ncmp 定时任务", text)
        self._dashboard.set_last_task_summary(text)

    # ------------------------------------------------------------------
    # 关闭事件
    # ------------------------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        action = self.app_config.close_action
        if action is None:
            choice, remember = self._ask_close_action()
            if choice is None:
                # 用户关闭对话框（Esc / X）→ 取消本次关闭
                event.ignore()
                return
            if remember:
                self.app_config.set("close_action", choice)
                self.app_config.save()
            action = choice

        if action == "close":
            self._shutdown_workers()
            super().closeEvent(event)
        else:  # "minimize"
            event.ignore()
            self.hide()
            self._notify.notify(
                "ncmp desktop", "已最小化到托盘，双击图标恢复")

    def _ask_close_action(self) -> Tuple[Optional[str], bool]:
        """弹出关闭确认对话框，返回 (所选动作, 是否勾选不再提示)。

        返回值：
          - ("close" | "minimize", remember_bool)：用户点了某个按钮
          - (None, remember_bool)：用户取消（Esc/关闭窗口）
        """
        dlg = QDialog(self)
        dlg.setObjectName("closeConfirm")
        dlg.setWindowTitle("关闭确认")
        dlg.setModal(True)

        root = QVBoxLayout(dlg)
        root.setSpacing(12)
        root.setContentsMargins(20, 20, 20, 16)

        caption = QLabel(
            "要直接关闭程序，还是最小化到系统托盘后台运行？", dlg)
        caption.setObjectName("captionText")
        caption.setWordWrap(True)
        root.addWidget(caption)

        remember_box = QCheckBox("不再显示此提示", dlg)
        root.addWidget(remember_box)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_minimize = QPushButton("最小化到托盘", dlg)
        btn_minimize.setObjectName("secondaryButton")
        btn_close = QPushButton("直接关闭", dlg)
        btn_close.setObjectName("primaryButton")
        btn_row.addWidget(btn_minimize)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

        result = {"action": None}

        def _choose(action: str) -> None:
            result["action"] = action
            dlg.accept()

        btn_close.clicked.connect(lambda: _choose("close"))
        btn_minimize.clicked.connect(lambda: _choose("minimize"))

        # 居中到父窗口
        dlg.adjustSize()
        center = self.geometry().center()
        dlg.move(center.x() - dlg.width() // 2,
                 center.y() - dlg.height() // 2)

        dlg.exec()
        return result["action"], remember_box.isChecked()

    def _shutdown_workers(self) -> None:
        """真正退出前停掉后台线程。"""
        try:
            self._schedule_timer.stop()
            self._schedule_heartbeat_timer.stop()
        except Exception:
            pass
        try:
            self._validate_worker.stop()
            if self._validate_worker.isRunning():
                self._validate_worker.wait(2000)
        except Exception:
            pass
