import threading
import time
from typing import Callable, Optional
import requests
from core import CancelledError
from core.utils.config import Config
from core.utils.logger import Logger
from .tasks.daily import DailyTask
from .tasks.extra import ExtraTask
class MusicPartnerBot:
    def __init__(self, config: Config, logger: Logger, session: requests.Session,
                 on_step: Optional[Callable[[str, str, float], None]] = None,
                 on_progress: Optional[Callable[[int, Optional[int], str, str], None]] = None,
                 cancel_event: Optional[threading.Event] = None,
                 on_note: Optional[Callable[[dict, str, str], None]] = None,
                 on_works: Optional[Callable[[list], None]] = None):
        self.config = config
        self.logger = logger
        self.session = session
        # 桌面版新增的回调与取消支持
        self.on_step = on_step            # callback(name, status, elapsed)
        self.on_progress = on_progress    # callback(done, total, song_name, score)
        self.on_note = on_note            # callback(work, score, note)
        self.on_works = on_works          # callback(tasks)：今日曲目清单（含服务端分数）
        self.cancel_event = cancel_event  # threading.Event
        self.t0 = 0.0
        self._current_step = ""
        #: 失败时的原始异常。run() 会把异常吞掉只返回 False，
        #: 但调用方（TaskWorker）需要异常本身来做失败原因分类。
        self.last_error: Optional[BaseException] = None
        self.api = {
            "user_info": "https://music.163.com/api/nuser/account/get",
        }

    def _step(self, name: str, status: str) -> None:
        """推进结构化步骤视图状态：status ∈ running/success/failed/cancelled。"""
        self._current_step = name
        if self.on_step:
            try:
                self.on_step(name, status, time.time() - self.t0)
            except Exception as cb_err:
                self.logger.debug(f"on_step 回调异常: {cb_err}")

    def _check_cancel(self) -> None:
        """在每个阶段开始处响应取消。"""
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise CancelledError("用户取消任务")

    def run(self) -> bool:
        self.t0 = time.time()
        try:
            self._check_cancel()
            self._step("验证用户信息", "running")
            self._verify_user()
            self._step("验证用户信息", "success")

            self._check_cancel()
            self._step("拉取每日任务", "running")
            daily_task = DailyTask(
                self.session, self.logger, self.config,
                on_progress=self.on_progress,
                cancel_event=self.cancel_event,
                on_note=self.on_note,
            )
            complete, task_data = daily_task._get_daily_tasks()
            self._step("拉取每日任务", "success")
            # 今日曲目清单（含服务端已记的分数）直接交给界面：
            # 今天已经评完时评分流程不会跑，界面否则一片空白。
            self._emit_works(task_data)

            # 额外任务清单提前拉一次：界面从第一秒就能看到今天全部曲目，
            # 而不是先显示 5 首、等基础任务跑完才冒出额外的 15 首。
            extra_task = ExtraTask(
                self.session, self.logger, self.config,
                on_progress=self.on_progress,
                cancel_event=self.cancel_event,
                on_note=self.on_note,
                on_works=self.on_works,
            )
            extra_task.preload()

            if not complete:
                self._check_cancel()
                self._step("评分基础任务", "running")
                daily_task._process_tasks(task_data)
                self._step("评分基础任务", "success")

            self._check_cancel()
            self._step("额外评分任务", "running")
            extra_task.process_extra_tasks(task_data["id"])
            self._step("额外评分任务", "success")
            return True

        except CancelledError:
            self._step(self._current_step, "cancelled")
            self.logger.info("任务已取消")
            # 重新抛出让 TaskWorker 区分取消/失败
            raise
        except Exception as e:
            self.logger.error(f"执行失败: {str(e)}")
            # 留给 TaskWorker 做失败原因分类（网络/风控/Cookie/接口/未知）
            self.last_error = e
            self._step(self._current_step, "failed")
            return False

    def _emit_works(self, task_data: dict) -> None:
        """把今日曲目清单交给界面（work / 服务端分数 / 是否已评）。

        今天已经评完时不会走评分流程，"今天评了哪几首、各几分"就只在这份
        响应里（``works[].work`` + ``works[].score`` + ``works[].completed``），
        不交出去，界面就只能显示空状态。
        """
        if not self.on_works:
            return
        try:
            self.on_works(list(task_data.get("works") or []))
        except Exception as cb_err:
            self.logger.debug(f"on_works 回调异常: {cb_err}")

    def _verify_user(self) -> None:
        """验证用户信息"""
        try:
            self.logger.info("开始验证用户信息...")
            response = self.session.get(url=self.api["user_info"]).json()

            profile = response.get("profile")
            if profile:
                self.logger.info(f'用户名: {profile["nickname"]}')
            else:
                raise RuntimeError("获取用户信息失败")

        except Exception as e:
            raise RuntimeError(f"验证用户信息失败: {str(e)}")
