"""扫码登录（pyncm 1.8.1 LoginQrcodeUnikey / LoginQrcodeCheck / GetLoginQRCodeUrl）。

pyncm 未安装时 ``PYNCM_AVAILABLE`` 为 False，``generate``/``poll`` 抛 RuntimeError
由调用方决定 UI 上如何提示降级。
"""
import io
from typing import Dict, Tuple

try:
    from pyncm.apis.login import LoginQrcodeUnikey, LoginQrcodeCheck, GetLoginQRCodeUrl
    from pyncm import Session
    PYNCM_AVAILABLE = True
except ImportError:
    LoginQrcodeUnikey = None  # type: ignore
    LoginQrcodeCheck = None  # type: ignore
    GetLoginQRCodeUrl = None  # type: ignore
    Session = None  # type: ignore
    PYNCM_AVAILABLE = False


try:
    import qrcode
    _QRCODE_AVAILABLE = True
except ImportError:
    qrcode = None  # type: ignore
    _QRCODE_AVAILABLE = False


try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    Image = None  # type: ignore
    _PIL_AVAILABLE = False


class QrLogin:
    """网易云音乐扫码登录封装（适配 pyncm 1.8.1 API）。"""

    def __init__(self) -> None:
        self._available = PYNCM_AVAILABLE
        # pyncm 1.8.1 移除 GetCurrentSession，需显式创建 Session 复用
        self._session = Session() if PYNCM_AVAILABLE else None

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------
    def generate(self) -> Tuple[str, bytes]:
        """生成二维码，返回 (unikey, png_bytes)。

        :raises RuntimeError: pyncm/qrcode/Pillow 任一缺失。
        """
        if not self._available or self._session is None:
            raise RuntimeError("pyncm 未安装，扫码登录不可用。请参考 README 安装 pyncm。")
        if not _QRCODE_AVAILABLE or not _PIL_AVAILABLE:
            raise RuntimeError("qrcode / Pillow 未安装，无法渲染二维码图片。")
        # 1. 申请扫码令牌
        data = LoginQrcodeUnikey(session=self._session) or {}
        unikey = data.get("unikey") or ""
        if not unikey:
            raise RuntimeError(f"pyncm 未返回 unikey: {data}")
        # 2. 拼接含 chainId 的二维码 URL（新版风控需要 chainId）
        qr_url = GetLoginQRCodeUrl(unikey, session=self._session) or ""
        if not qr_url:
            raise RuntimeError(f"pyncm 未返回二维码 URL: unikey={unikey}")
        img_bytes = self._render_png(qr_url)
        return unikey, img_bytes

    def poll(self, unikey: str) -> Tuple[int, Dict[str, str]]:
        """轮询扫码状态，返回 (code, cookies)。

        code 取值：
            800: 二维码过期
            801: 等待扫描
            802: 已扫描待确认
            803: 登录成功
        code == 803 时 cookies 包含 ``Cookie_MUSIC_U`` / ``Cookie___csrf``。
        """
        if not self._available or self._session is None:
            raise RuntimeError("pyncm 未安装，扫码登录不可用。请参考 README 安装 pyncm。")
        state = LoginQrcodeCheck(unikey, session=self._session) or {}
        # 兼容：某些版本把真实数据塞在 data 字段里
        if "code" not in state and isinstance(state.get("data"), dict):
            state = state["data"]
        code = int(state.get("code", 0))
        cookies: Dict[str, str] = {}
        if code == 803:
            music_u = ""
            csrf = ""
            try:
                music_u = self._session.cookies.get("MUSIC_U") or ""
            except Exception:
                pass
            try:
                csrf = self._session.cookies.get("__csrf") or ""
            except Exception:
                pass
            if music_u:
                cookies["Cookie_MUSIC_U"] = music_u
            if csrf:
                cookies["Cookie___csrf"] = csrf
        return code, cookies

    @property
    def available(self) -> bool:
        return self._available

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _render_png(self, qr_url: str) -> bytes:
        """用 qrcode + Pillow 渲染 PNG 字节流。"""
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2,
        )
        qr.add_data(qr_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
