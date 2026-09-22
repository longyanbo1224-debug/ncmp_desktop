"""桌面系统通知：优先用托盘气泡，否则降级 plyer / print。"""
from typing import Optional


class DesktopNotify:
    """桌面通知封装。

    - 若传入托盘图标实例，优先使用 ``QSystemTrayIcon.showMessage``（跨平台原生通知）
    - 否则尝试用 ``plyer`` 库（需额外安装）
    - 都不可用时退化为 print，确保功能不致中断
    """

    def __init__(self, tray=None) -> None:
        self.tray = tray

    def notify(self, title: str, body: str,
               ms_timeout: int = 5000) -> bool:
        """弹出通知，成功返回 True。"""
        # 1. 优先托盘气泡
        if self.tray is not None:
            try:
                from PySide6.QtWidgets import QSystemTrayIcon
            except Exception:
                QSystemTrayIcon = None  # type: ignore
            if QSystemTrayIcon is not None and self.tray.isVisible():
                try:
                    self.tray.showMessage(title, body, QSystemTrayIcon.Information, ms_timeout)
                    return True
                except Exception:
                    pass
        # 2. plyer 降级
        try:
            from plyer import notification  # type: ignore
            notification.notify(title=title, message=body, timeout=ms_timeout // 1000)
            return True
        except Exception:
            pass
        # 3. 最终兜底
        print(f"[notify] {title}: {body}")
        return False
