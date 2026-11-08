import threading
import time
from typing import Callable, Optional
import requests
from core import CancelledError
from core import scoring
from core.utils.config import Config
from core.utils.logger import Logger
from .tasks.daily import DailyTask
from .tasks.extra import ExtraTask
from .rating_ledger import RatingLedger
from .quota_state import QuotaState
class MusicPartnerBot:
    def __init__(self, config: Config, logger: Logger, session: requests.Session,
                 on_step: Optional[Callable[[str, str, float], None]] = None,
                 on_progress: Optional[Callable[[int, Optional[int], str, str], None]] = None,
                 cancel_event: Optional[threading.Event] = None,
                 on_note: Optional[Callable[[dict, str, str], None]] = None,
                 on_works: Optional[Callable[[list], None]] = None,
                 quota_state: Optional[QuotaState] = None,
                 local_submitted_count: int = 0,
                 local_extra_done: int = 0):
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
        #: 当天额外额度已用完的本地标记：命中就直接跳过额外阶段
        self.quota_state = quota_state if quota_state is not None else QuotaState()
        #: 本机今日曲目记录里已提交的条数（由界面层传入）：达到 基础+额外上限
        #: 时同样直接跳过额外阶段，不再请求服务端。
        self.local_submitted_count = int(local_submitted_count or 0)
        #: 本机今日记录里已提交的「额外」曲目数（由界面层传入）：
        #: 服务端额外清单是分批的，早上评过的可能不再列出，剩余额度得靠它补足。
        self.local_extra_done = int(local_extra_done or 0)
        #: 当前账号 id（验证用户信息时拿到），账本按账号隔离
        self.account_id = ""
        #: 服务端明确返回「今日没有更多」：当天额外额度已用完。
        #: 界面用它决定未轮到的额外曲目是否按今日完成计。
        self.extra_all_done = False
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
            )
            base_works = list(task_data.get("works") or [])
            for item in base_works:
                item["_group"] = "base"

            # 先查本地，再决定额外评分要不要请求服务端：
            # 1) 已缓存「今天这个任务额度用完」；
            # 2) 本地账本已经确认收下「基础 + 额外上限」这么多首；
            # 3) 本机今日曲目记录已经这么多首 submitted。
            # 命中时只跳过**评分**，仍拉一次只读的额外清单用于显示完整曲目
            # （不发评分请求、不等待）。
            full = bool(self.config.get("full_extra_tasks", False))
            extra_limit = 15 if full else 7
            base_count = max(1, int(task_data.get("count") or 0))
            ledger_done = self.ledger.count(self.account_id, task_data.get("id"))
            local_complete = ledger_done >= base_count + extra_limit
            history_complete = self.local_submitted_count >= base_count + extra_limit
            quota_done = self.quota_state.exhausted(self.account_id, task_data.get("id"))
            skip_extra = quota_done or local_complete or history_complete

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
            if skip_extra:
                # 本地命中：不再等待、不再发评分请求
                if quota_done:
                    self.logger.info("本机记录显示今日额外额度已用完，跳过额外评分")
                elif local_complete:
                    self.logger.info(
                        f"本地评分账本显示今日已评满（{ledger_done} 首），跳过额外评分")
                else:
                    self.logger.info(
                        f"本地曲目记录显示今日已评满（{self.local_submitted_count} 首），"
                        f"跳过额外评分")
                self.extra_all_done = True
            else:
                # 基础任务评完后额外清单才会放出下一批：基础阶段跑过时重新拉一次，
                # 否则一轮只评到第一批（例如 15 首），用户还得再点一次执行才到 20 首
                # 服务端额外清单是分批的，早上评过的额外曲目这次可能不再列出；
                # 本地记录的额外已评数要和清单里的已完成数取较大者，否则会把
                # 剩余额度多算（进度 1/15、实际只剩 10 首）。
                base_done = sum(1 for item in base_works if item.get("completed"))
                local_extra_done = max(
                    self.local_extra_done,
                    max(0, self.local_submitted_count - base_done),
                )
                extra_task.process_extra_tasks(
                    task_data["id"], refresh=not complete,
                    local_extra_done=local_extra_done)
                self.extra_all_done = bool(getattr(extra_task, "quota_exhausted", False))
                if self.extra_all_done:
                    # 记住「今天这个任务额度已用完」，下次重跑直接跳过
                    self.quota_state.mark(self.account_id, task_data.get("id"))
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
                # 用 clean_score：服务端可能给 4.0 / 0.0 / "null"，只有 1–5
                # 的整档才算「已评过」，否则会把待评歌写进账本
                score = scoring.clean_score(task.get("score"))
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
