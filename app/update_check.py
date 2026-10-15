"""启动时检查 GitHub Releases 有没有新版本。

**只检查、只提示、只打开下载页。不自动下载，更不自动替换。**

理由和功能好不好用无关：这个 exe 没有代码签名。自动替换等于给用户开了一条
"可执行文件可被中间人替换"的通道——更新包从哪来、有没有被篡改，
程序自己没法验证。签名之前，自动更新不能做。

频率限制：最多 24 小时查一次，时间戳记在 AppConfig 里，
避免每次启动都去打 GitHub 的接口。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import requests
from PySide6.QtCore import QThread, Signal

from app.version import API_LATEST_RELEASE, RELEASES_URL, is_newer

logger = logging.getLogger(__name__)

_TIMEOUT = 8
_MIN_INTERVAL = timedelta(hours=24)
_LAST_CHECK_KEY = "last_update_check"


def _should_check() -> bool:
    """距上次检查是否超过 24 小时。读不到配置就当该查。"""
    try:
        from app.app_config import AppConfig
        raw = str(AppConfig().get(_LAST_CHECK_KEY, "") or "")
        if not raw:
            return True
        last = datetime.fromisoformat(raw)
        return datetime.now() - last >= _MIN_INTERVAL
    except Exception:
        return True


def _mark_checked() -> None:
    """记下这次检查的时间。失败静默——不该因为记不上时间就报错。"""
    try:
        from app.app_config import AppConfig
        cfg = AppConfig()
        cfg.set(_LAST_CHECK_KEY, datetime.now().isoformat(timespec="seconds"))
        cfg.save()
    except Exception:
        pass


class UpdateChecker(QThread):
    """后台线程查最新 release。

    :signal checked: (是否有新版本, 远端版本号, 下载页 URL)
    """

    checked = Signal(bool, str, str)

    def __init__(self, parent=None, force: bool = False) -> None:
        super().__init__(parent)
        self._force = force

    def run(self) -> None:
        if not self._force and not _should_check():
            return
        try:
            resp = requests.get(
                API_LATEST_RELEASE,
                timeout=_TIMEOUT,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "ncmp-desktop",
                },
            )
            _mark_checked()
            if resp.status_code != 200:
                # 仓库没有 release、被限流、网络不通——都当作"没查到"，不打扰用户
                logger.debug("更新检查返回 %s", resp.status_code)
                return
            data = resp.json()
            tag = str(data.get("tag_name") or "").strip()
            url = str(data.get("html_url") or RELEASES_URL)
            if is_newer(tag):
                logger.info("发现新版本 %s", tag)
                self.checked.emit(True, tag, url)
            else:
                self.checked.emit(False, tag, url)
        except Exception as e:
            logger.debug("更新检查失败: %s", e)


def open_releases_page(url: str = RELEASES_URL) -> None:
    """用系统浏览器打开下载页。"""
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(url or RELEASES_URL))
    except Exception as e:
        logger.warning("打开下载页失败: %s", e)
