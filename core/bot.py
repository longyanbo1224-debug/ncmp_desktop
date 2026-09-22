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
                 cancel_event: Optional[threading.Event] = None):
        self.config = config
        self.logger = logger
        self.session = session
        # 桌面版新增的回调与取消支持
        self.on_step = on_step            # callback(name, status, elapsed)
        self.on_progress = on_progress    # callback(done, total, song_name, score)
        self.cancel_event = cancel_event  # threading.Event
        self.t0 = 0.0
        self._current_step = ""
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
            )
            complete, task_data = daily_task._get_daily_tasks()
            self._step("拉取每日任务", "success")

            if not complete:
                self._check_cancel()
                self._step("评分基础任务", "running")
                daily_task._process_tasks(task_data)
                self._step("评分基础任务", "success")

            self._check_cancel()
            self._step("额外评分任务", "running")
            extra_task = ExtraTask(
                self.session, self.logger, self.config,
                on_progress=self.on_progress,
                cancel_event=self.cancel_event,
            )
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
            self._step(self._current_step, "failed")
            return False

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
