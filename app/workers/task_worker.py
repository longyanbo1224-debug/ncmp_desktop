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
from core.utils import errors
from core.utils.config import Config
from core.utils.logger import Logger
from core.utils.notification import NotificationService


class TaskWorker(QThread):
    """任务执行工作线程。"""

    # name, status, elapsed（秒，float）
    step = Signal(str, str, float)
    # done, total, song_name, score
    progress = Signal(int, int, str, str)
    # song_name, score, note —— 批注提交成功后发出，供曲目表把"留下了什么话"落到行上
    note = Signal(str, str, str)
    # (ok, status, kind)，status ∈ {"success", "cancelled", "failed"}，
    # kind 是失败原因分类（见 core/utils/errors.py），成功时为空
    finished_sig = Signal(bool, str, str)

    #: 网络类失败自动重试前等待的秒数
    _RETRY_DELAY_SEC = 60

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
                self.finished_sig.emit(False, "failed", errors.COOKIE)
                self._send_email("failed", errors.COOKIE)
                return

            ok, kind = self._attempt(config, session)

            # 网络类失败自动重试一次。
            # 风控和 Cookie 类**绝不重试**：风控被拦之后立刻重试只会加重风控，
            # Cookie 失效重试一万次也没用。
            if (not ok and kind in errors.RETRYABLE
                    and not self.cancel_event.is_set()):
                self.step.emit("网络异常，稍后重试", "running", 0.0)
                if self._wait_cancelable(self._RETRY_DELAY_SEC):
                    ok, kind = self._attempt(config, session)

            if ok:
                status, kind = "success", ""
            elif self.cancel_event.is_set():
                status = "cancelled"
            else:
                status = "failed"

            if status == "failed" and kind:
                self._report_failure(kind)
            self.finished_sig.emit(ok, status, kind)
            self._send_email(status, kind)
        except Exception as e:
            # 兜底：保证 finished_sig 总会发出
            try:
                Logger().error(f"TaskWorker 异常: {e}")
            except Exception:
                pass
            kind = errors.classify(e)[0]
            self.finished_sig.emit(False, "failed", kind)
            self._send_email("failed", kind)

    def _attempt(self, config, session):
        """跑一次 bot，返回 ``(是否成功, 失败分类)``。"""
        bot = MusicPartnerBot(
            config=config,
            logger=Logger(),
            session=session,
            on_step=self._on_step,
            on_progress=self._on_progress,
            cancel_event=self.cancel_event,
            on_note=self._on_note,
        )
        try:
            ok = bot.run()
        except CancelledError:
            return False, ""
        except Exception as e:
            try:
                Logger().error(f"TaskWorker 执行异常: {e}")
            except Exception:
                pass
            return False, errors.classify(e)[0]
        if ok:
            return True, ""
        # bot.run() 吞了异常只返回 False，所以从 last_error 里取原因
        return False, errors.classify(bot.last_error)[0]

    def _wait_cancelable(self, seconds: int) -> bool:
        """分片等待，期间可被取消。返回 True 表示等完了、可以继续。"""
        for _ in range(max(0, int(seconds))):
            if self.cancel_event.is_set():
                return False
            QThread.msleep(1000)
        return not self.cancel_event.is_set()

    def _report_failure(self, kind: str) -> None:
        """把失败原因写进步骤视图——用户不用翻日志就能看到是哪一类问题。"""
        label = errors.LABELS.get(kind, errors.LABELS[errors.UNKNOWN])
        self.step.emit(f"失败原因：{label}", "failed", 0.0)

    # ------------------------------------------------------------------
    # 邮件通知
    # ------------------------------------------------------------------
    def _send_email(self, status: str, kind: str = "") -> None:
        """按 notify_context 对应开关发邮件通知；失败不影响主流程。

        :param kind: 失败原因分类（见 core/utils/errors.py），决定邮件里的
            「原因」和「下一步」。成功/取消时为空。
        """
        try:
            from datetime import datetime

            config = self._config or Config()
            flag_key = ("notify_on_schedule" if self._notify_context == "schedule"
                        else "notify_on_task_done")
            if not bool(config.get(flag_key, True)):
                return
            run_kind = ("定时执行" if self._notify_context == "schedule"
                        else "手动执行")
            facts = [("时间", datetime.now().strftime("%Y-%m-%d %H:%M")),
                     ("方式", run_kind)]

            if status == "success":
                level = "success"
                subject = "ncmp 任务完成"
                content = "音乐合伙人评分任务已执行完成。"
                action = ""
            elif status == "cancelled":
                level = "warning"
                subject = "ncmp 任务已取消"
                content = "任务被手动取消，本次执行未跑完。"
                action = ("下次定时时间到会自动重跑；也可以现在打开程序，"
                          "在「任务」页点「立即执行」补一次。")
            else:
                level = "failed"
                label = errors.LABELS.get(kind, errors.LABELS[errors.UNKNOWN])
                subject = f"ncmp 任务失败（{label}）"
                content = f"音乐合伙人评分任务未能完成：{label}。"
                action = errors.HINTS.get(kind, errors.HINTS[errors.UNKNOWN])
                facts.append(("原因", label))

            NotificationService(config, Logger()).send_notification(
                subject, content, level=level, facts=facts, action=action)
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

    def _on_note(self, work, score: str, note: str) -> None:
        """批注提交成功：转成信号发给界面（core 线程 → 主线程）。"""
        name = ""
        try:
            name = str(work.get("name", "") or "")
        except Exception:
            name = ""
        self.note.emit(name, str(score), str(note))

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
