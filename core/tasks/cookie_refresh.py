import os
from typing import Callable, Optional
from core.utils.auth import AuthService
from core.utils.logger import Logger
from core.utils.notification import NotificationService
class CookieRefreshTask:
    def __init__(self, logger: Logger,
                 notifier: Optional[NotificationService] = None,
                 on_cookie_refreshed: Optional[Callable[[str, str], None]] = None):
        """
        Cookie 刷新任务（桌面版改造：去除远端回写）。

        :param on_cookie_refreshed: 刷新成功后的回调，签名为 (music_u, csrf)。
            由上层（如 app/cookie_store.CookieStore）负责把新 Cookie 写入本地存储，
            core/ 层不依赖 app/ 层的具体实现。
        """
        self.logger = logger
        self.notifier = notifier
        self.on_cookie_refreshed = on_cookie_refreshed
        self.auth_service = AuthService(logger)

    def execute(self) -> bool:
        """执行Cookie刷新任务"""
        try:
            self.logger.info("开始执行Cookie刷新任务")

            # 获取登录凭据
            phone = os.environ.get("NETEASE_PHONE")
            password = os.environ.get("NETEASE_PASSWORD")
            md5_password = os.environ.get("NETEASE_MD5_PASSWORD")

            if not phone:
                self.logger.error("未设置手机号，无法执行自动登录")
                if self.notifier:
                    self.notifier.send_notification(
                        "网易云音乐合伙人 - 自动登录失败",
                        "未设置手机号，请检查NETEASE_PHONE环境变量"
                    )
                return False

            if not md5_password and not password:
                self.logger.error("未设置密码，无法执行自动登录")
                if self.notifier:
                    self.notifier.send_notification(
                        "网易云音乐合伙人 - 自动登录失败",
                        "未设置密码，请检查NETEASE_MD5_PASSWORD或NETEASE_PASSWORD环境变量"
                    )
                return False

            # 执行登录，优先使用MD5密码，如果使用明文密码，则自动转换为MD5
            success, cookies = self.auth_service.login(
                phone=phone,
                password=password if not md5_password else None,
                md5_password=md5_password
            )

            if not success or not cookies:
                self.logger.error("登录失败，无法获取新的Cookie")
                if self.notifier:
                    self.notifier.send_notification(
                        "网易云音乐合伙人 - 自动登录失败",
                        "登录过程失败，请检查登录凭据是否正确"
                    )
                return False

            music_u = cookies.get("Cookie_MUSIC_U", "")
            csrf = cookies.get("Cookie___csrf", "")

            # 通过回调把新 Cookie 交给上层持久化（替代原远端回写逻辑）
            if self.on_cookie_refreshed:
                try:
                    self.on_cookie_refreshed(music_u, csrf)
                    self.logger.info("新 Cookie 已通过回调持久化")
                except Exception as cb_err:
                    self.logger.error(f"Cookie 回调持久化失败: {str(cb_err)}")

            self.logger.info("Cookie 刷新成功")
            if self.notifier:
                self.notifier.send_notification(
                    "网易云音乐合伙人 - Cookie更新成功",
                    "已成功获取新的Cookie"
                )
            return True

        except Exception as e:
            error_message = f"Cookie刷新任务执行异常: {str(e)}"
            self.logger.error(error_message)

            if self.notifier:
                self.notifier.send_notification(
                    "网易云音乐合伙人 - Cookie刷新异常",
                    error_message
                )

            return False
