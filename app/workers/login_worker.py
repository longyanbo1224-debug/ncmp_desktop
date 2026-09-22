"""登录工作线程：支持扫码模式与密码模式。

扫码模式：
    1. ``generate`` → 发 ``qr_ready`` 信号把二维码 PNG 字节推到 UI
    2. 每 2 秒 ``poll`` → 发 ``qr_status`` 信号更新状态文字
    3. 收到 code==803 → ``CookieStore.save`` + 发 ``login_result`` 信号
密码模式：
    ``PwdLogin.login`` → ``CookieStore.save`` → 发 ``login_result`` 信号

所有跨线程数据通过 Qt 信号传递，主线程槽里更新 UI。
"""
import threading
import time
from typing import Any, Optional

from PySide6.QtCore import QThread, Signal

from app.cookie_store import CookieStore
from app.login.pwd_login import PwdLogin
from app.login.qr_login import QrLogin


class LoginWorker(QThread):
    """登录工作线程。

    使用方式：
        worker = LoginWorker()
        worker.qr_ready.connect(...)         # bytes: 二维码 PNG
        worker.qr_status.connect(...)        # str: 状态文字
        worker.login_result.connect(...)     # (bool, str): 成功与否 + 消息
        worker.start_qr()        # 扫码模式
        worker.start_pwd(phone, pwd, use_md5=False)  # 密码模式
        worker.cancel()          # 取消（停止轮询）
    """

    qr_ready = Signal(bytes)
    qr_status = Signal(str)
    login_result = Signal(bool, str)

    POLL_INTERVAL = 2.0  # 扫码轮询间隔，单位秒
    QR_EXPIRE_HINT = "二维码已过期，请重新生成"

    # 网易云密码登录风控判定：
    #   - code 命中风控集合（502/503 等）→ 风控
    #   - msg 含「频繁|风险|验证|异常」关键词 → 风控
    #   - 501/-501（密码错误）、506（参数错误）等保持普通失败文案
    _RISK_CODES = {502, 503}
    _RISK_KEYWORDS = ("频繁", "风险", "验证", "异常")
    _RISK_HINT = "密码登录触发风控，建议改用扫码登录（账号页「扫码登录」Tab）。"
    _PLAIN_FAIL = "登录失败，请检查手机号/密码。"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._mode: Optional[str] = None  # 'qr' 或 'pwd'
        self._phone = ""
        self._password = ""
        self._use_md5 = False
        self._cancel_event = threading.Event()
        self._store = CookieStore()
        self._qr = QrLogin()
        self._pwd = PwdLogin()

    # ------------------------------------------------------------------
    # 启动接口
    # ------------------------------------------------------------------
    def start_qr(self) -> None:
        """以扫码模式启动。"""
        self._mode = "qr"
        self._cancel_event.clear()
        if not self.isRunning():
            self.start()

    def start_pwd(self, phone: str, password: str,
                  use_md5: bool = False) -> None:
        """以密码模式启动。"""
        self._mode = "pwd"
        self._phone = phone
        self._password = password
        self._use_md5 = use_md5
        self._cancel_event.clear()
        if not self.isRunning():
            self.start()

    def cancel(self) -> None:
        """停止轮询/取消当前操作。"""
        self._cancel_event.set()

    # ------------------------------------------------------------------
    # QThread.run
    # ------------------------------------------------------------------
    def run(self) -> None:  # noqa: D401 - QThread 入口
        if self._mode == "qr":
            self._run_qr()
        elif self._mode == "pwd":
            self._run_pwd()
        # mode 为 None 时不做任何事（避免误启动）

    # ------------------------------------------------------------------
    # 扫码模式
    # ------------------------------------------------------------------
    def _run_qr(self) -> None:
        if not self._qr.available:
            self.login_result.emit(
                False, "pyncm 未安装，扫码登录不可用。请先 pip install pyncm。")
            return
        # 1. 生成二维码
        try:
            unikey, img_bytes = self._qr.generate()
        except Exception as e:
            self.login_result.emit(False, f"生成二维码失败：{e}")
            return
        if self._cancel_event.is_set():
            return
        self.qr_ready.emit(img_bytes)
        self.qr_status.emit("请使用网易云音乐 APP 扫码")
        # 2. 轮询
        while not self._cancel_event.is_set():
            try:
                code, cookies = self._qr.poll(unikey)
            except Exception as e:
                self.qr_status.emit(f"轮询出错：{e}")
                # 出错后稍等再继续，避免狂打接口
                self._sleep_interruptible(2.0)
                continue
            if code == 800:
                self.qr_status.emit(self.QR_EXPIRE_HINT)
                self.login_result.emit(False, self.QR_EXPIRE_HINT)
                return
            if code == 801:
                self.qr_status.emit("等待扫描…")
            elif code == 802:
                self.qr_status.emit("已扫描，请在手机确认登录")
            elif code == 803:
                music_u = cookies.get("Cookie_MUSIC_U", "")
                csrf = cookies.get("Cookie___csrf", "")
                if music_u and csrf:
                    try:
                        self._store.save(music_u, csrf)
                    except Exception as e:
                        self.login_result.emit(False, f"保存 Cookie 失败：{e}")
                        return
                    self.qr_status.emit("登录成功")
                    self.login_result.emit(True, "登录成功")
                else:
                    self.login_result.emit(False, "登录成功但未拿到 Cookie")
                return
            else:
                self.qr_status.emit(f"未知状态：{code}")
            self._sleep_interruptible(self.POLL_INTERVAL)
        # 主动取消
        self.qr_status.emit("已取消")

    # ------------------------------------------------------------------
    # 密码模式
    # ------------------------------------------------------------------
    def _run_pwd(self) -> None:
        if not self._pwd.available:
            self.login_result.emit(
                False, "pyncm 未安装，密码登录不可用。请先 pip install pyncm。")
            return
        if self._cancel_event.is_set():
            return
        try:
            ok, info = self._pwd.login(
                self._phone, self._password, use_md5=self._use_md5)
        except Exception as e:
            self.login_result.emit(False, f"登录过程异常：{e}")
            return
        if not ok:
            # info: None（pyncm 不可用）或 {"code":..., "msg":...}
            if info is None:
                self.login_result.emit(
                    False, "pyncm 未安装，密码登录不可用。请先 pip install pyncm。")
                return
            code = info.get("code")
            msg = (info.get("msg") or "").strip()
            if self._is_risk_control(code, msg):
                self.login_result.emit(False, self._RISK_HINT)
            else:
                self.login_result.emit(False, self._PLAIN_FAIL)
            return
        if not info:
            self.login_result.emit(False, "登录成功但未拿到 Cookie")
            return
        music_u = info.get("Cookie_MUSIC_U", "")
        csrf = info.get("Cookie___csrf", "")
        if not (music_u and csrf):
            self.login_result.emit(False, "登录成功但未拿到 Cookie")
            return
        try:
            self._store.save(music_u, csrf)
        except Exception as e:
            self.login_result.emit(False, f"保存 Cookie 失败：{e}")
            return
        self.login_result.emit(True, "登录成功")

    # ------------------------------------------------------------------
    # 风控判定
    # ------------------------------------------------------------------
    @classmethod
    def _is_risk_control(cls, code: Any, msg: str) -> bool:
        """判断密码登录失败是否为风控。

        - code 命中风控集合（502/503 等）→ True
        - msg 含「频繁|风险|验证|异常」任一关键词 → True
        - 其余（501/-501 密码错误、506 参数错误等）→ False
        """
        if code is not None:
            try:
                if int(code) in cls._RISK_CODES:
                    return True
            except (TypeError, ValueError):
                pass
        return any(kw in msg for kw in cls._RISK_KEYWORDS)

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    def _sleep_interruptible(self, seconds: float) -> None:
        """可被 cancel() 中断的 sleep。"""
        end = time.time() + seconds
        while True:
            if self._cancel_event.is_set():
                return
            remaining = end - time.time()
            if remaining <= 0:
                return
            self._cancel_event.wait(min(0.5, remaining))
