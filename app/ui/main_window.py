"""主窗口：QStackedWidget 切 4 页 + 左侧 QListWidget 导航 + 托盘 + 后台验证线程。

closeEvent 拦截：按 ``AppConfig.close_action`` 决定直接关或最小化到托盘
（None=每次弹确认框，"close"=直接关，"minimize"=最小化到托盘）。
持有 TrayIcon + ValidateWorker + TaskWorker + LoginWorker 实例并连接信号。

本地定时执行：QTimer 单次触发 + 60s 心跳校准。
- schedule_mode: local=本地任务，cloud=云端 Actions，both=两者都启动
- 到点前发托盘通知「定时任务已启动」，本地完成由 _on_task_finished_from_tray 通知，
  云端完成由 TaskPage.cloud_finished_sig → _on_schedule_cloud_finished 通知。
"""
import math
import random
import sys
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
from app.ui import theme
from app.ui.icons import create_app_icon, nav_icon
from app.update_check import UpdateChecker
from app.ui.pages.about_page import AboutPage
from app.ui.pages.dashboard_page import DashboardPage
from app.ui.pages.login_page import LoginPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.pages.ledger_page import LedgerPage
from app.ui.pages.task_page import TaskPage
from app.ui.widgets.log_view import GuiLogHandler
from app.ui.widgets.tray_icon import TrayIcon
from app.ui.widgets.wheel_guard import WheelGuard
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
        self.resize(*theme.WINDOW_DEFAULT)
        self.setMinimumSize(*theme.WINDOW_MINIMUM)
        self._center_on_screen()

        self._log_handler: Optional[GuiLogHandler] = None
        # 是否已排定一次延迟启动的定时任务。补跑要靠它判断
        # "延迟窗口里已经有任务在排队了，别再触发一次"。
        self._pending_run = False
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
        # 心跳同时兼作错过补跑的检查点：每分钟看一次"今天该跑还没跑"
        self._schedule_heartbeat_timer.timeout.connect(self._maybe_catch_up)
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
        self._nav.setFixedWidth(theme.NAV_WIDTH)
        self._nav.setIconSize(QSize(theme.NAV_ICON, theme.NAV_ICON))
        self._nav.setSpacing(2)
        self._nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for text, key in (("首页", "home"), ("账号", "account"),
                          ("今日", "task"), ("记录", "ledger"),
                          ("设置", "settings"), ("关于", "about")):
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
        self._ledger = LedgerPage()
        self._settings = SettingsPage()
        self._about = AboutPage()
        self._stack.addWidget(self._dashboard)
        self._stack.addWidget(self._login)
        self._stack.addWidget(self._task)
        self._stack.addWidget(self._ledger)
        self._stack.addWidget(self._settings)
        self._stack.addWidget(self._about)
        self._stack.setCurrentIndex(0)
        layout.addWidget(self._stack, 1)

        self.setCentralWidget(central)

    # ------------------------------------------------------------------
    # 子组件
    # ------------------------------------------------------------------
    def _init_workers(self) -> None:
        # 滚轮保护：设置页的下拉框／数字框不该被滚轮误改数值
        app = QApplication.instance()
        self._wheel_guard = WheelGuard(app if app is not None else self)
        if app is not None:
            app.installEventFilter(self._wheel_guard)
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
        self._dashboard.goto_settings.connect(lambda: self._goto_page(4))
        self._dashboard.refresh_cookie.connect(self._refresh_cookie_status)

        # 登录成功 → 刷新 Cookie 卡片 + 跳回首页
        self._login.login_succeeded.connect(self._on_login_succeeded)

        # 任务页 Cookie 预检失败 → 跳登录页
        self._task.goto_login.connect(lambda: self._goto_page(1))
        self._task.goto_settings.connect(lambda: self._goto_page(4))
        # 云端 worker 完成 → 托盘通知（定时 + 手动都走这条）
        self._task.cloud_finished_sig.connect(self._on_schedule_cloud_finished)

        # 设置页定时配置保存 → 重排定时器
        self._settings.schedule_config_changed.connect(self._on_schedule_config_changed)
        self._settings.close_action_changed.connect(self._on_close_action_changed)

        # 托盘
        self._tray.show_main.connect(self._show_and_raise)
        self._tray.run_task.connect(self._goto_task_and_run)
        self._tray.refresh_cookie.connect(self._refresh_cookie_status)
        self._tray.about.connect(self._goto_about)
        self._tray.quit_requested.connect(self.quit_app)
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
        """启动后台线程：Cookie 定期验证 + 托盘显示 + 更新检查。"""
        try:
            self._tray.show()
        except Exception:
            pass
        try:
            if not self._validate_worker.isRunning():
                self._validate_worker.start()
        except Exception:
            pass
        # 更新检查：后台跑，最多 24 小时查一次（见 app/update_check.py），
        # 查不到就安静退出，不打扰用户
        try:
            self._update_checker = UpdateChecker(self)
            self._update_checker.checked.connect(self._on_update_checked)
            self._update_checker.start()
        except Exception:
            pass
        # 错过补跑：等界面立起来再查，免得启动瞬间弹通知吓人
        QTimer.singleShot(3000, self._maybe_catch_up)

    # ------------------------------------------------------------------
    # 槽
    # ------------------------------------------------------------------
    def _on_nav_changed(self, row: int) -> None:
        if 0 <= row < self._stack.count():
            self._stack.setCurrentIndex(row)
            if row == 1:
                # 进入登录页时启动扫码
                self._login.start()
            elif row == 3:
                # 进入账本页时重读本地记录（曲目/批注可能刚被别处写入）
                self._ledger.refresh()
            elif row == 4:
                # 进入设置页时从磁盘重读 AppConfig（close_action 可能被关闭弹窗修改）
                self._settings.refresh_app_config()

    def _goto_page(self, index: int) -> None:
        self._nav.setCurrentRow(index)

    def _goto_task_and_run(self) -> None:
        self._show_and_raise()
        self._nav.setCurrentRow(2)
        self._task.execute()

    def _goto_about(self) -> None:
        """托盘「关于」入口：显示主窗口并跳关于页。"""
        self._show_and_raise()
        self._nav.setCurrentRow(5)

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

    def show_from_second_instance(self) -> None:
        """用户又点了桌面图标：把已有窗口（可能最小化/收进托盘）拉到前台。"""
        self._show_and_raise()

    def _center_on_screen(self) -> None:
        """把窗口放到主屏可用区域的正中。

        Windows 不做这件事：不给位置就落在左上角。尺寸按 DPI 缩放后也不要
        超出可用区域，否则高 DPI 的笔记本上一个 1100×760 的窗口会顶出屏幕。
        """
        try:
            screen = QApplication.primaryScreen()
            if screen is None:
                return
            area = screen.availableGeometry()
            width = min(self.width(), area.width())
            height = min(self.height(), area.height())
            self.resize(width, height)
            self.move(area.x() + (area.width() - width) // 2,
                      area.y() + (area.height() - height) // 2)
        except Exception:
            pass

    def _show_and_raise(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        # Windows 的前台窗口锁会无视 activateWindow，再直接抢一次
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.user32.SetForegroundWindow(int(self.winId()))
            except Exception:
                pass

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

    def _on_task_finished_from_tray(self, ok: bool, status: str,
                                    kind: str = "") -> None:
        """共享 TaskWorker 完成时的托盘通知 + 首页摘要。

        :param ok: 成功与否（cancelled/failed 均为 False）。
        :param status: "success" / "cancelled" / "failed"。
        :param kind: 失败原因分类，决定通知里说什么。
        """
        if status == "cancelled":
            msg = "用户手动取消任务"
        elif status == "success":
            msg = "任务执行完成"
        else:
            from core.utils import errors
            label = errors.LABELS.get(kind, "")
            msg = f"任务执行失败：{label}" if label else "任务执行失败"
        self._notify.notify("ncmp 任务", msg)
        self._dashboard.set_last_task_summary(msg)
        # 成功一次就记下日期，错过补跑靠它判断"今天跑过没有"
        if status == "success":
            self._mark_success_today()

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

    def _on_close_action_changed(self) -> None:
        """设置页改了关闭按钮行为 → 重读 AppConfig。"""
        try:
            self.app_config.load()
        except Exception:
            pass

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
        """到下一次 (HH:MM) 壁钟时刻（今天已过则取明天）的秒数。

        使用向上取整，避免「距离目标不足 1 秒」被截断为 0，
        导致 QTimer 立即触发并在整点前重复执行定时任务。
        """
        try:
            h_str, m_str = (hhmm or "09:00").split(":")
            h, m = int(h_str), int(m_str)
        except Exception:
            h, m = 9, 0
        now = datetime.now()
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target = target + timedelta(days=1)
        return max(0, math.ceil((target - now).total_seconds()))

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
            self._start_local_after_delay()
        if mode in ("cloud", "both"):
            try:
                self._task.execute_cloud()
            except Exception as e:
                self._notify.notify("ncmp 定时任务", f"云端任务启动失败：{e}")
        # 重排下一天的定时（心跳也会兜底）
        self._setup_schedule()

    def _start_local_after_delay(self) -> None:
        """本地定时任务：按配置的随机延迟启动。

        固定整点发起请求本身就是个风控特征，所以给一个 0~N 分钟的随机窗口。
        延迟窗口内如果用户手动跑了任务，到点那次会被 TaskPage 的
        「已有任务在执行」挡掉，不会重复执行。
        """
        try:
            span = int(self.app_config.get("local_delay_minutes", 0) or 0)
        except Exception:
            span = 0
        if span <= 0:
            self._run_local_scheduled()
            return
        delay_min = random.randint(0, span)
        if delay_min <= 0:
            self._run_local_scheduled()
            return
        # 标记"已有一次延迟启动在排队"：这段窗口里补跑不能再触发，
        # 否则延迟到点时会和补跑撞成两次执行
        self._pending_run = True
        self._notify.notify(
            "ncmp 定时任务", f"本地任务将在约 {delay_min} 分钟后启动")
        QTimer.singleShot(delay_min * 60 * 1000, self._run_local_scheduled)

    def _run_local_scheduled(self) -> None:
        """真正启动本地定时任务。"""
        self._pending_run = False
        if self._task_running():
            # 已经有一次在跑（比如补跑刚触发），别叠加
            return
        try:
            # 定时执行走 notify_on_schedule 开关（而非 notify_on_task_done）
            self._task.execute(notify_context="schedule")
        except Exception as e:
            self._notify.notify("ncmp 定时任务", f"本地任务启动失败：{e}")

    # ------------------------------------------------------------------
    # 错过补跑
    # ------------------------------------------------------------------
    def _mark_success_today(self) -> None:
        """记下"今天已经成功跑过"，补跑靠它判断。"""
        try:
            self.app_config.set("last_success_date", datetime.now().date().isoformat())
            self.app_config.save()
        except Exception:
            pass

    @staticmethod
    def _parse_hhmm(text: str, default: tuple) -> tuple:
        """把 "HH:MM" 解析成 (时, 分)；解析失败用默认值。"""
        try:
            hh, mm = str(text or "").split(":")
            h, m = int(hh), int(mm)
            if 0 <= h <= 23 and 0 <= m <= 59:
                return h, m
        except Exception:
            pass
        return default

    def _schedule_target_today(self) -> datetime:
        """今天该跑的时刻（已经过了也是今天这个时刻）。"""
        h, m = self._parse_hhmm(self.app_config.schedule_time, (9, 0))
        return datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)

    def _catchup_deadline(self) -> datetime:
        """补跑截止时刻。"""
        h, m = self._parse_hhmm(
            self.app_config.get("catchup_deadline", "23:00"), (23, 0))
        return datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)

    def _task_running(self) -> bool:
        try:
            return bool(self._task_worker is not None
                        and self._task_worker.isRunning())
        except Exception:
            return False

    @staticmethod
    def _has_cookie() -> bool:
        try:
            music_u, csrf, _ = CookieStore().load()
            return bool(music_u and csrf)
        except Exception:
            return False

    def _maybe_catch_up(self) -> None:
        """错过补跑：定时时间已过、今天还没跑、且没到截止时间 → 补一次。

        场景：定时设了 09:00，但电脑 09:30 才开机（或者程序没启动）。
        原来 ``_seconds_until_next`` 会直接算到**明天** 09:00，
        今天就这么无声无息地没了，用户不会收到任何提示。

        几个刻意的限制：
        - **只补当天**，不追溯更早。音乐合伙人是当天有效的任务，
          补三天前那次网易也不认；连续补跑几次还是明显的风控特征。
        - **每天最多补一次**。补跑失败也记一笔，否则 60 秒心跳会每分钟
          重试一次直到截止时间——那就是重试风暴，正是最重的风控特征。
        - **有截止时间**（默认 23:00）。如果 23:50 才开机就别跑了——
          离第二天 09:00 只剩 10 分钟，跑完紧接着又跑一次，同样触发风控。
        - **云端模式不补**。GitHub Actions 自己按 cron 跑，与本机开不开机无关。
        - **延迟窗口里不判定**。本地随机延迟会把启动推后 0~30 分钟，
          那段窗口里"今天还没跑"是正常的，不该触发补跑，
          否则延迟到点时会和补跑撞成两次执行。
        """
        try:
            if not self.app_config.schedule_enabled:
                return
            if not bool(self.app_config.get("catchup_enabled", True)):
                return
            if self.app_config.schedule_mode not in ("local", "both"):
                return
            if self._task_running():
                return
            if self._pending_run:
                return                      # 已有延迟启动在排队，别撞成两次
            now = datetime.now()
            today = now.date().isoformat()
            if str(self.app_config.get("last_success_date", "") or "") == today:
                return                      # 今天已经成功跑过
            if str(self.app_config.get("last_catchup_date", "") or "") == today:
                return                      # 今天已经补过一次了，不管成没成
            if now < self._schedule_target_today():
                return                      # 还没到今天的定时时间，等定时器
            if now > self._catchup_deadline():
                return                      # 过了截止时间，不补
            if not self._has_cookie():
                return                      # 没配 Cookie，补了也是白失败一次

            # 先记账再触发：即使这次补跑立刻失败，今天也不会再试第二次
            self.app_config.set("last_catchup_date", today)
            self.app_config.save()
            self._notify.notify(
                "ncmp 定时任务",
                f"检测到今天的任务还没跑（定时 {self.app_config.schedule_time}），正在补跑")
            self._run_local_scheduled()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 更新检查
    # ------------------------------------------------------------------
    def _on_update_checked(self, has_update: bool, version: str, url: str) -> None:
        """后台查到新版本：托盘提示 + 关于页留一条常驻入口。

        只提示、不下载、不替换——这个 exe 没有代码签名，
        自动替换等于开了一条"可执行文件可被中间人替换"的通道。
        """
        if not has_update:
            return
        self._notify.notify(
            "ncmp desktop", f"发现新版本 {version}，在「关于」页可打开下载页")
        try:
            self._about.set_update_available(version, url)
        except Exception:
            pass

    def _on_schedule_cloud_finished(self, ok: bool, msg: str) -> None:
        """云端 worker 完成 → 托盘通知（定时 + 手动都走这条）。"""
        if ok:
            text = "云端任务完成：成功"
        elif msg.startswith("已取消"):
            text = "云端任务已取消"
        elif msg.startswith("取消远端失败"):
            text = f"云端任务取消失败（{msg}）"
        else:
            text = f"云端任务完成：失败（{msg}）"
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
            self.quit_app()
            event.accept()
        else:  # "minimize"
            event.ignore()
            self.hide()
            self._notify.notify(
                "ncmp desktop",
                "已最小化到托盘，定时任务仍会在后台按时执行。双击托盘图标恢复窗口。")

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
        root.setSpacing(theme.SP_3)
        root.setContentsMargins(theme.SP_5, theme.SP_5, theme.SP_5, theme.SP_4)

        caption = QLabel(
            "要直接关闭程序，还是最小化到系统托盘后台运行？", dlg)
        caption.setObjectName("captionText")
        caption.setWordWrap(True)
        root.addWidget(caption)

        remember_box = QCheckBox("不再显示此提示", dlg)
        root.addWidget(remember_box)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(theme.SP_2)
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
        try:
            self._task_worker.cancel()
            if self._task_worker.isRunning():
                self._task_worker.wait(2000)
        except Exception:
            pass

    def quit_app(self) -> None:
        """彻底退出：停掉后台线程、移除托盘图标并退出应用。"""
        self._shutdown_workers()
        try:
            self._tray.hide()
        except Exception:
            pass
        QApplication.quit()
