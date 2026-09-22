"""密码登录：直接走 pyncm 提取 code/msg，便于上层区分风控。

约束：不改 ``core/``。原 ``core.utils.auth.AuthService`` 在失败时只返回
``(False, None)``，丢失了 pyncm 返回的 ``code``/``message``，无法区分风控。
故本封装直接调用 pyncm ``LoginViaCellphone``，自行解析结果。

返回值统一为 ``(ok, info)``：
    - 成功：``info`` 为 cookies dict ``{"Cookie_MUSIC_U": ..., "Cookie___csrf": ...}``
    - 失败：``info`` 为错误 dict ``{"code": <int|None>, "msg": <str>}``（或 None
      当 pyncm 未安装时）
"""
import hashlib
from typing import Any, Dict, Optional, Tuple

from core.utils.auth import PYNCM_AVAILABLE
from core.utils.logger import Logger


class PwdLogin:
    """密码登录封装（直接走 pyncm，便于拿到 code/msg）。"""

    def __init__(self) -> None:
        self.logger = Logger()

    @property
    def available(self) -> bool:
        return PYNCM_AVAILABLE

    def login(self, phone: str, password: str,
              use_md5: bool = False) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """手机号 + 密码登录。

        :param phone: 手机号
        :param password: 明文密码（use_md5=False）或 MD5 密码（use_md5=True）
        :param use_md5: True 时把 password 视作 MD5
        :return: ``(success, info)``。``info`` 在成功时为 cookies dict，失败时为
            ``{"code": ..., "msg": ...}``（或 pyncm 不可用时为 None）。
        """
        if not self.available:
            return False, None
        try:
            from pyncm.apis.login import LoginViaCellphone
            from pyncm import Session
        except ImportError:
            return False, None

        try:
            if use_md5:
                password_hash = password
                self.logger.debug("使用提供的MD5密码登录")
            else:
                password_hash = hashlib.md5(password.encode()).hexdigest()
                self.logger.debug("使用明文密码（转换为MD5）登录")

            self.logger.info(
                f"尝试使用 pyncm 登录账号: {phone[:3]}****{phone[-4:]}")

            # pyncm 1.8.1 起必须传 session= 关键字参数
            session = Session()
            result = LoginViaCellphone(
                phone=phone,
                passwordHash=password_hash,
                ctcode=86,
                remeberLogin=True,
                session=session,
            )

            code = result.get("code")
            msg = (result.get("message") or result.get("msg") or "").strip()

            if code != 200:
                self.logger.error(f"登录失败: code={code} msg={msg}")
                return False, {"code": code, "msg": msg}

            music_u = session.cookies.get("MUSIC_U")
            csrf = session.cookies.get("__csrf")
            if not music_u or not csrf:
                self.logger.error("未能从会话中获取 MUSIC_U/__csrf cookie")
                return False, {"code": code, "msg": "未获取到 Cookie"}

            self.logger.info("登录成功并获取Cookie")
            return True, {
                "Cookie_MUSIC_U": music_u,
                "Cookie___csrf": csrf,
            }
        except Exception as e:
            self.logger.error(f"pyncm 登录过程发生异常: {str(e)}")
            return False, {"code": None, "msg": str(e)}
