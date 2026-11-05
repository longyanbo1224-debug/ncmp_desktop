"""后台同步今日曲目清单（基础 + 额外）。

今日页打开或切回时用它把服务端的已完成状态拉回来：另一台设备评过的歌，
本机也能立刻显示成「已提交」，不用先跑一次任务。失败静默，不打扰主流程。
"""
import requests
from PySide6.QtCore import QThread, Signal

from app.cookie_store import CookieStore

_DAILY_URL = "https://interface.music.163.com/api/music/partner/daily/task/get"
_EXTRA_URL = "https://interface.music.163.com/api/music/partner/extra/wait/evaluate/work/list"


class WorksRefreshWorker(QThread):
    """拉取今日清单；成功时发出与 bot 相同结构的列表。"""

    works = Signal(list)

    def run(self) -> None:  # noqa: D401
        try:
            music_u, csrf, _ = CookieStore().load()
            if not (music_u and csrf):
                return
            session = requests.Session()
            session.cookies.set("MUSIC_U", music_u)
            session.cookies.set("__csrf", csrf)

            daily = session.get(_DAILY_URL, timeout=15).json()
            base = ((daily.get("data") or {}).get("works") or [])
            for item in base:
                item["_group"] = "base"

            extra = []
            try:
                response = session.get(
                    _EXTRA_URL, timeout=15,
                    headers={"Referer": "https://mp.music.163.com/"}).json()
                if response.get("code") == 200:
                    extra = response.get("data") or []
                    for item in extra:
                        item["_group"] = "extra"
            except Exception:
                extra = []

            self.works.emit(list(base) + list(extra))
        except Exception:
            return
