"""Cookie 本地存储（替代 ncmp 原 github.py 的远端回写）。

Windows 上 keyring 默认走 Credential Manager（DPAPI 加密），比明文 setting.json 安全得多。
keyring 未安装时降级为内存字典（仅当前进程可用，仅供测试/无依赖环境）。
"""
from datetime import datetime
from typing import Optional, Tuple


try:
    import keyring
    _KEYRING_AVAILABLE = True
except ImportError:
    keyring = None  # type: ignore
    _KEYRING_AVAILABLE = False


# keyring 不可用时的内存降级后端（仅用于无依赖环境的兜底）
_FALLBACK_STORE = {"MUSIC_U": "", "__csrf": "", "updated_at": ""}


class CookieStore:
    """Cookie 本地持久化。

    对应 ncmp setting.json 中的 ``Cookie_MUSIC_U`` 与 ``Cookie___csrf``。
    SERVICE 字符串与 ``core/utils/config.py`` 的 ``KEYRING_SERVICE`` 保持一致，
    以便核心层在加载配置时可直接读到此处写入的 Cookie。
    """

    SERVICE = "ncmp-desktop"

    def __init__(self) -> None:
        self._available = _KEYRING_AVAILABLE

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------
    def save(self, music_u: str, csrf: str) -> None:
        """保存 Cookie，并记录写入时间。"""
        if not music_u or not csrf:
            raise ValueError("保存 Cookie 失败：MUSIC_U/__csrf 不能为空")
        timestamp = datetime.now().isoformat(timespec="seconds")
        if self._available:
            try:
                keyring.set_password(self.SERVICE, "MUSIC_U", music_u)
                keyring.set_password(self.SERVICE, "__csrf", csrf)
                keyring.set_password(self.SERVICE, "updated_at", timestamp)
                return
            except Exception:
                # keyring 后端不可用时降级到内存
                self._available = False
        _FALLBACK_STORE["MUSIC_U"] = music_u
        _FALLBACK_STORE["__csrf"] = csrf
        _FALLBACK_STORE["updated_at"] = timestamp

    def load(self) -> Tuple[str, str, Optional[str]]:
        """读取 Cookie，返回 (MUSIC_U, __csrf, updated_at)。

        没有记录时返回 ("", "", None)。
        """
        if self._available:
            try:
                music_u = keyring.get_password(self.SERVICE, "MUSIC_U") or ""
                csrf = keyring.get_password(self.SERVICE, "__csrf") or ""
                updated_at = keyring.get_password(self.SERVICE, "updated_at")
                if music_u or csrf:
                    return music_u, csrf, updated_at
            except Exception:
                self._available = False
        music_u = _FALLBACK_STORE.get("MUSIC_U", "")
        csrf = _FALLBACK_STORE.get("__csrf", "")
        updated_at = _FALLBACK_STORE.get("updated_at") or None
        return music_u, csrf, updated_at

    def clear(self) -> None:
        """清空 Cookie 与更新时间。"""
        if self._available:
            for key in ("MUSIC_U", "__csrf", "updated_at"):
                try:
                    keyring.delete_password(self.SERVICE, key)
                except Exception:
                    pass
        for key in ("MUSIC_U", "__csrf", "updated_at"):
            _FALLBACK_STORE[key] = ""

    @property
    def available(self) -> bool:
        """keyring 后端是否可用。"""
        return self._available
