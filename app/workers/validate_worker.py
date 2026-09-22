"""后台 Cookie 验证线程：周期性校验当前 Cookie 是否仍有效。

失效时通过 ``expired`` 信号通知 UI（弹托盘通知 + 跳转登录页），
仍然有效时通过 ``status`` 信号把最新状态推给 UI。
``stop()`` 把 ``_running`` 置 False，下一轮 sleep 醒来后退出。

失效时还会按 ``notify_on_cookie_expired`` 开关发邮件通知
（``ncmp Cookie 失效`` / ``Cookie 已失效，请重新登录获取``）；
邮件失败不影响 expired 信号 emit。
"""
from typing import Optional

import requests
from PySide6.QtCore import QThread, Signal

from app.cookie_store import CookieStore
from core.utils.config import Config
from core.utils.logger import Logger
from core.utils.notification import NotificationService
from core.validators.cookie import CookieValidator


class ValidateWorker(QThread):
    """后台 Cookie 验证线程。"""

    expired = Signal(str)           # 失效原因
    status = Signal(bool, str)      # (是否有效, 状态描述)

    def __init__(self, interval_sec: int = 6 * 3600, parent=None) -> None:
        super().__init__(parent)
        self.interval = int(interval_sec)
        self._running = True
        self._store = CookieStore()
        self._logger = Logger()

    def stop(self) -> None:
        """请求停止，下一轮循环退出。"""
        self._running = False

    def run(self) -> None:  # noqa: D401
        # 启动后立即跑一次，便于 UI 初始化时就能拿到状态
        while self._running:
            self._validate_once()
            if not self._running:
                break
            # 拆分 sleep 以便尽快响应 stop()
            self._msleep_interruptible(self.interval * 1000)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _validate_once(self) -> None:
        try:
            music_u, csrf, _ = self._store.load()
        except Exception as e:
            self._notify_expired(f"读取本地 Cookie 失败: {e}")
            return
        if not music_u or not csrf:
            self._notify_expired("未配置 Cookie")
            return
        session = requests.Session()
        session.cookies.set("MUSIC_U", music_u)
        session.cookies.set("__csrf", csrf)
        try:
            ok, msg = CookieValidator(session, self._logger).validate()
        except Exception as e:
            ok, msg = False, f"Cookie验证失败: {e}"
        if ok:
            self.status.emit(True, msg)
        else:
            self._notify_expired(msg)

    def _notify_expired(self, reason: str) -> None:
        """发邮件（如启用）后 emit expired 信号；邮件失败不影响主流程。"""
        try:
            config = Config()
            if bool(config.get("notify_on_cookie_expired", True)):
                NotificationService(config, self._logger).send_notification(
                    "ncmp Cookie 失效", "Cookie 已失效，请重新登录获取")
        except Exception:
            pass
        self.expired.emit(reason)

    def _msleep_interruptible(self, ms: int) -> None:
        """分片 msleep，便于及时响应 stop()。"""
        step_ms = 500
        remaining = ms
        while remaining > 0 and self._running:
            self.msleep(min(step_ms, remaining))
            remaining -= step_ms
