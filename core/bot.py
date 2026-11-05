import threading
import time
from typing import Callable, Optional
import requests
from core import CancelledError
from core.utils.config import Config
from core.utils.logger import Logger
from .tasks.daily import DailyTask
from .tasks.extra import ExtraTask
from .rating_ledger import RatingLedger
from .signer import RequestPacer
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
        #: 本地评分账本：同一任务重跑时不再提交已评过的歌
        self.ledger = RatingLedger()
        #: 整轮共享的请求节奏：第一次真实请求不等待
        self.pacer = RequestPacer()
        #: 当前账号 id（验证用户信息时拿到），账本按账号隔离
        self.account_id = ""
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
                ledger=self.ledger,
                account=self.account_id,
                pacer=self.pacer,
            )
            complete, task_data = daily_task._get_daily_tasks()
            self._remember_completed(task_data.get("id"),
                                     task_data.get("works") or [])
            self._step("拉取每日任务", "success")
            # 今日曲目清单（含服务端已记的分数）直接交给界面：
            # 今天已经评完时评分流程不会跑，界面否则一片空白。
            # 额外任务清单先预取，再和基础任务**合并成一次**交给界面：
            # 分两次上报会让曲目表先闪 5 首再跳到 15 首。
            extra_task = ExtraTask(
                self.session, self.logger, self.config,
                on_progress=self.on_progress,
                cancel_event=self.cancel_event,
                on_note=self.on_note,
                on_works=self.on_works,
                ledger=self.ledger,
                account=self.account_id,
                pacer=self.pacer,
            )
            base_works = list(task_data.get("works") or [])
            for item in base_works:
                item["_group"] = "base"
            # 额外清单接口会把等待评分的基础任务也列出来：先告诉 ExtraTask
            # 哪些是基础任务，取清单时剔除，避免 20 首被裁成 15 首、额度重复计算
            extra_task.set_base_works(base_works)
            extra_task.preload()
            self._remember_completed(
                task_data.get("id"), getattr(extra_task, "last_all", []) or [])
            try:
                extra_works = list(getattr(extra_task, "last_all", []) or [])
            except Exception:
                extra_works = []
            for item in extra_works:
                item["_group"] = "extra"
            self._emit_works(base_works + extra_works)

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

    def _emit_works(self, works) -> None:
        """把今日曲目清单交给界面（每项含 work / score / completed）。

        参数是**已合并好的列表**（基础 + 额外），不是原始响应 dict——
        早先这里按 ``task_data["works"]`` 取值，改成合并列表后直接抛
        ``'list' object has no attribute 'get'``，界面一行都收不到。
        """
        if not self.on_works:
            return
        try:
            self.on_works(list(works or []))
        except Exception as cb_err:
            self.logger.debug(f"on_works 回调异常: {cb_err}")

    def _remember_completed(self, task_id, tasks) -> None:
        """把服务端标成已完成的曲目记进账本（含另一台设备评的）。

        账本只用于"跳过重复提交"：下次同一任务里服务端标记滞后时，也不会再提交。
        """
        if not task_id:
            return
        for task in tasks or []:
            try:
                work = task.get("work") or {}
                score = str(task.get("score") or "").strip()
                # 有分数就说明已经评过，completed 标记可能滞后
                if work.get("id") is None or not score:
                    continue
                self.ledger.mark(self.account_id, task_id, work.get("id"), score)
            except Exception:
                continue

    def _verify_user(self) -> None:
        """验证用户信息"""
        try:
            self.logger.info("开始验证用户信息...")
            response = self.session.get(url=self.api["user_info"]).json()

            profile = response.get("profile")
            if profile:
                self.account_id = str(profile.get("userId") or "")
                self.logger.info(f'用户名: {profile["nickname"]}')
            else:
                raise RuntimeError("获取用户信息失败")

        except Exception as e:
            raise RuntimeError(f"验证用户信息失败: {str(e)}")
