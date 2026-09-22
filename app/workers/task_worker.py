"""任务执行工作线程：调用 core.bot.MusicPartnerBot.run()。

通过 Qt 信号把 bot 的 step / progress 回调转发到主线程 UI。
``cancel()`` 设置 ``cancel_event``，core 层在每个步骤、每次 sleep 前检查。

任务结束后按 ``notify_context`` 读取对应邮件开关发通知：
    - "task"     → notify_on_task_done（手动执行）
    - "schedule" → notify_on_schedule（定时执行）
状态：success/cancelled/failed，对应不同主题与文案。
"""
import threading
from typing import Optional

import requests
from PySide6.QtCore import QThread, Signal

from app.cookie_store import CookieStore
from core import CancelledError
from core.bot import MusicPartnerBot
from core.utils.config import Config
from core.utils.logger import Logger
from core.utils.notification import NotificationService


class TaskWorker(QThread):
    """任务执行工作线程。"""

    # name, status, elapsed（秒，float）
    step = Signal(str, str, float)
    # done, total, song_name, score
    progress = Signal(int, int, str, str)
    # (ok, status)，status ∈ {"success", "cancelled", "failed"}
    finished_sig = Signal(bool, str)

    def __init__(self, config: Optional[Config] = None,
                 session: Optional[requests.Session] = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._session = session
        self.cancel_event = threading.Event()
        # "task"=手动执行用 notify_on_task_done；"schedule"=定时执行用 notify_on_schedule
        self._notify_context: str = "task"

    # ------------------------------------------------------------------
    # 启动接口
    # ------------------------------------------------------------------
    def start_task(self, config: Optional[Config] = None,
                   session: Optional[requests.Session] = None,
                   notify_context: str = "task") -> None:
        """启动任务。可在外部传入 config/session，也可在 run() 内现取现造。

        :param notify_context: "task"=手动执行（读 notify_on_task_done），
                               "schedule"=定时执行（读 notify_on_schedule）。
        """
        if config is not None:
            self._config = config
        if session is not None:
            self._session = session
        self._notify_context = notify_context if notify_context in ("task", "schedule") else "task"
        self.cancel_event.clear()
        if not self.isRunning():
            self.start()

    def cancel(self) -> None:
        """请求取消任务。core 层会在下次取消点响应。"""
        self.cancel_event.set()

    # ------------------------------------------------------------------
    # QThread.run
    # ------------------------------------------------------------------
    def run(self) -> None:  # noqa: D401
        try:
            config = self._config or Config()
            session = self._session or self._build_session_from_store()
            if session is None:
                # Cookie 完全没配置
                self.step.emit("初始化", "failed", 0.0)
                self.finished_sig.emit(False, "failed")
                self._send_email("failed")
                return
            bot = MusicPartnerBot(
                config=config,
                logger=Logger(),
                session=session,
                on_step=self._on_step,
                on_progress=self._on_progress,
                cancel_event=self.cancel_event,
            )
            try:
                ok = bot.run()
                status = "success" if ok else "failed"
            except CancelledError:
                ok, status = False, "cancelled"
            except Exception as e:
                try:
                    Logger().error(f"TaskWorker 执行异常: {e}")
                except Exception:
                    pass
                ok, status = False, "failed"
            self.finished_sig.emit(ok, status)
            self._send_email(status)
        except Exception as e:
            # 兜底：保证 finished_sig 总会发出
            try:
                Logger().error(f"TaskWorker 异常: {e}")
            except Exception:
                pass
            self.finished_sig.emit(False, "failed")
            self._send_email("failed")

    # ------------------------------------------------------------------
    # 邮件通知
    # ------------------------------------------------------------------
    def _send_email(self, status: str) -> None:
        """按 notify_context 对应开关发邮件通知；失败不影响主流程。"""
        try:
            config = self._config or Config()
            flag_key = ("notify_on_schedule" if self._notify_context == "schedule"
                        else "notify_on_task_done")
            if not bool(config.get(flag_key, True)):
                return
            if status == "success":
                subject, content = "ncmp 任务完成", "评分任务已成功完成"
            elif status == "cancelled":
                subject, content = "ncmp 任务已取消", "用户手动取消任务"
            else:
                subject, content = "ncmp 任务失败", "评分任务失败，请查看日志"
            NotificationService(config, Logger()).send_notification(subject, content)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _on_step(self, name: str, status: str, elapsed: float) -> None:
        # Signal.emit 是线程安全的，Qt 会自动跨线程派发到主线程槽
        self.step.emit(name, status, float(elapsed))

    def _on_progress(self, done: int, total, song_name: str, score: str) -> None:
        # total 可能为 None
        self.progress.emit(int(done), int(total) if total is not None else 0,
                           str(song_name), str(score))

    def _build_session_from_store(self) -> Optional[requests.Session]:
        """从 CookieStore 构造 requests.Session。"""
        try:
            store = CookieStore()
            music_u, csrf, _ = store.load()
        except Exception:
            return None
        if not music_u or not csrf:
            return None
        session = requests.Session()
        session.cookies.set("MUSIC_U", music_u)
        session.cookies.set("__csrf", csrf)
        return session
