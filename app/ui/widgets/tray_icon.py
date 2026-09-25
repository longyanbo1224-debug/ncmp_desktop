"""系统托盘图标。

提供 4 项右键菜单：显示主窗口 / 立即执行任务 / 检查/刷新 Cookie / 退出。
图标优先用 qtawesome 生成（fa5s.music 着主色），替代 app.png 与 SP_ComputerIcon 回退。
菜单项也带图标。
"""
from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from app.ui.icons import (
    ICON_ABOUT, create_app_icon, ICON_EYE, ICON_QUIT, ICON_REFRESH, ICON_RUN,
    ICON_SHOW_MAIN, COLOR_PRIMARY, op_icon,
)


class TrayIcon(QSystemTrayIcon):
    """托盘图标。"""

    show_main = Signal()
    run_task = Signal()
    refresh_cookie = Signal()
    about = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(self._make_icon(), parent)
        self.setToolTip("ncmp desktop")
        self._build_menu()
        self._connect_internal()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    @staticmethod
    def _make_icon() -> QIcon:
        """优先用品牌 create_app_icon（圆角蓝底 + 白色 music）。"""
        try:
            return create_app_icon()
        except Exception:
            app = QApplication.instance() or QApplication([])
            style = app.style()
            from PySide6.QtWidgets import QStyle
            return style.standardIcon(QStyle.SP_ComputerIcon)

    def _build_menu(self) -> None:
        menu = QMenu()
        act_show = QAction(op_icon(ICON_SHOW_MAIN), "显示主窗口", menu)
        act_show.triggered.connect(self._on_show_main)
        menu.addAction(act_show)

        act_run = QAction(op_icon(ICON_RUN, COLOR_PRIMARY), "立即执行任务", menu)
        act_run.triggered.connect(self._on_run_task)
        menu.addAction(act_run)

        act_refresh = QAction(op_icon(ICON_REFRESH), "检查/刷新 Cookie", menu)
        act_refresh.triggered.connect(self._on_refresh_cookie)
        menu.addAction(act_refresh)

        act_about = QAction(op_icon(ICON_ABOUT), "关于", menu)
        act_about.triggered.connect(self._on_about)
        menu.addAction(act_about)

        menu.addSeparator()

        act_quit = QAction(op_icon(ICON_QUIT), "退出", menu)
        act_quit.triggered.connect(self._on_quit)
        menu.addAction(act_quit)

        self.setContextMenu(menu)

    def _connect_internal(self) -> None:
        # 双击托盘时也显示主窗口
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_main.emit()

    def _on_show_main(self) -> None:
        self.show_main.emit()

    def _on_run_task(self) -> None:
        self.run_task.emit()

    def _on_refresh_cookie(self) -> None:
        self.refresh_cookie.emit()

    def _on_about(self) -> None:
        self.about.emit()

    def _on_quit(self) -> None:
        self.quit_requested.emit()
