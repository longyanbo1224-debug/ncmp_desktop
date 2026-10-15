"""一次性 Cookie 验证（放后台线程，不冻界面）。

设置页的「验证 Cookie」要发一次网络请求。原来直接写在按钮槽里，
请求期间整个界面是卡住的——用户点完没反应，还以为是程序死了。

:signal done: ``(是否有效, 说明文字)``
"""
from PySide6.QtCore import QThread, Signal


class CookieCheckWorker(QThread):
    """跑一次 Cookie 验证，把结果发回来。"""

    done = Signal(bool, str)

    def run(self) -> None:  # noqa: D401
        try:
            from app.cookie_store import CookieStore
            music_u, csrf, _ = CookieStore().load()
        except Exception as e:
            self.done.emit(False, f"读取 Cookie 失败：{e}")
            return

        if not (music_u and csrf):
            self.done.emit(False, "未配置 Cookie，请先登录。")
            return

        try:
            import requests
            from core.utils.logger import Logger
            from core.validators.cookie import CookieValidator

            session = requests.Session()
            session.cookies.set("MUSIC_U", music_u)
            session.cookies.set("__csrf", csrf)
            ok, msg = CookieValidator(session, Logger()).validate()
            self.done.emit(bool(ok), str(msg))
        except Exception as e:
            self.done.emit(False, f"验证失败：{e}")
