"""桌面通知：优先用自绘的应用内气泡。

原来直接走 ``QSystemTrayIcon.showMessage``——那是**操作系统**画的气泡，
长什么样程序说了不算，用户反馈"不够好看"就是这个原因。

现在的顺序：
    1. 自绘气泡（右下角，配色/圆角/字号跟程序一致，见 widgets/toast.py）
    2. 系统托盘气泡（自绘失败时兜底）
    3. plyer
    4. print

注意：自绘气泡是顶层窗口，只能在 GUI 线程创建。非 GUI 线程调用时直接跳过它。
"""
from typing import Optional


def _on_gui_thread() -> bool:
    """当前是否在 GUI 线程。顶层窗口只能在 GUI 线程建。"""
    try:
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return False
        return QThread.currentThread() is app.thread()
    except Exception:
        return False


class DesktopNotify:
    """桌面通知封装。"""

    def __init__(self, tray=None) -> None:
        self.tray = tray

    def notify(self, title: str, body: str,
               ms_timeout: int = 5000) -> bool:
        """弹出通知，成功返回 True。"""
        # 1. 自绘气泡（首选：样式可控）
        if _on_gui_thread():
            try:
                from app.ui.widgets.toast import show as show_toast
                if show_toast(title, body):
                    return True
            except Exception:
                pass

        # 2. 系统托盘气泡（兜底）
        if self.tray is not None:
            try:
                from PySide6.QtWidgets import QSystemTrayIcon
            except Exception:
                QSystemTrayIcon = None  # type: ignore
            if QSystemTrayIcon is not None and self.tray.isVisible():
                try:
                    self.tray.showMessage(
                        title, body, QSystemTrayIcon.Information, ms_timeout)
                    return True
                except Exception:
                    pass

        # 3. plyer 降级
        try:
            from plyer import notification  # type: ignore
            notification.notify(
                title=title, message=body, timeout=ms_timeout // 1000)
            return True
        except Exception:
            pass

        # 4. 最终兜底
        print(f"[notify] {title}: {body}")
        return False
