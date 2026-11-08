import json
import random
from typing import Dict, List, Tuple, Optional
from core import CancelledError
from core.scoring import clean_score
from ..signer import NoMoreWorksError, Signer


def _work_key(work: Dict) -> str:
    """本轮去重用的作品键：优先 work id，缺 id 时退到歌名。

    不能直接 ``str(work.get("id"))``：缺 id 的作品会共用 ``"None"`` 这个键，
    评上一首后其余缺 id 的歌都会被当成「已评上」跳过。歌名在同一天的歌单里
    不会重复（曲目表本身也按歌名去重）。
    """
    work_id = str(work.get("id") or "").strip()
    if work_id and work_id.lower() not in ("none", "null"):
        return work_id
    name = str(work.get("name") or "").strip()
    return f"name:{name}" if name else ""


class ExtraTask:
    def __init__(self, session, logger, config, on_progress=None, cancel_event=None,
                 on_note=None, on_works=None, ledger=None, account=""):
        self.session = session
        self.logger = logger
        self.config = config
        self.on_progress = on_progress
        self.cancel_event = cancel_event
        # callback(work, score, note)：批注提交后回调界面
        self.on_note = on_note
        # callback(tasks)：额外任务的曲目清单，交给界面预置"待评"行
        self.on_works = on_works
        # 本地评分账本与账号：重跑时跳过已确认收下的评分
        self.ledger = ledger
        self.account = account
        self.api = {
            "extra_list": "https://interface.music.163.com/api/music/partner/extra/wait/evaluate/work/list",
            "report_listen": "https://interface.music.163.com/weapi/partner/resource/interact/report"
        }
        self.signer = Signer(session, "", logger, config)  # task_id 为空字符串，因为上报听歌不需要
        #: 预取结果。界面要一开始就看到今天全部曲目，评分阶段复用这份，避免重复请求。
        self._prefetched = None
        #: 服务端明确返回「今日没有更多」：当天额度已用完，不是评分失败。
        self.quota_exhausted = False
        #: 当天基础任务的 work id / 歌名。额外清单接口会把等待评分的作品都列出来，
        #: 其中包括基础任务那 5 首——它们由基础阶段负责，不能再计入额外的 15 首额度。
        self.base_ids = set()
        self.base_names = set()
    #: 额外评分最多跑几轮：首轮 + 一次补跑。
    #: 单首失败只跳过不重试，跑完不重新核对就会"15 条只评了 12 首"却报成功。
    _MAX_PASSES = 2
    #: 每天额外任务上限（基础 5 + 额外 15 = 20 首）
    _DAILY_MAX = 15

    def set_base_works(self, works) -> None:
        """告诉额外阶段哪些作品属于当天的基础任务，取清单时要把它们剔除。

        不做这一步时，基础 5 首会被当成额外任务：曲目表被上限裁成 15 行
        （本该 20 行），评分阶段也会把基础曲目占掉的额度算进额外 15 首里。
        """
        ids, names = set(), set()
        for task in works or []:
            try:
                work = (task or {}).get("work") or {}
            except Exception:
                continue
            work_id = str(work.get("id") or "").strip()
            name = str(work.get("name") or "").strip()
            if work_id and work_id.lower() not in ("none", "null"):
                ids.add(work_id)
            if name:
                names.add(name)
        self.base_ids = ids
        self.base_names = names

    def _is_base_work(self, task) -> bool:
        try:
            work = (task or {}).get("work") or {}
        except Exception:
            return False
        work_id = str(work.get("id") or "").strip()
        name = str(work.get("name") or "").strip()
        if (work_id and work_id.lower() not in ("none", "null")
                and work_id in self.base_ids):
            return True
        return bool(name and name in self.base_names)

    def preload(self) -> None:
        """提前拉一次额外任务清单，让界面一开始就看到全部曲目。

        基础阶段评过之后 ``process_extra_tasks(refresh=True)`` 会重新拉一次
        （那时服务端才放出下一批）；这份结果留作重新拉取失败时的回退，
        也用于 ``daily.complete`` 已为真、没有基础阶段的场景。
        """
        try:
            self.last_all = []
            self._prefetched = self._get_extra_tasks(emit=False)
        except Exception as e:
            self._prefetched = None
            try:
                getattr(self.logger, "debug", self.logger.info)(
                    f"预取额外任务失败（评分阶段会重试）：{e}")
            except Exception:
                pass

    def process_extra_tasks(self, task_id: str, refresh: bool = False,
                            local_extra_done: int = 0) -> None:
        """处理额外的评分任务。

        每轮结束后重新拉一次任务列表：单首失败被跳过时，服务端仍把它标成
        未完成，补跑这一轮就能把漏掉的补上，用户不必再手动点一次执行。

        :param refresh: 忽略执行前预取的清单，重新拉一次。额外接口是分批
            返回的：基础任务评完后才会放出下一批，沿用旧预取会让一轮只评到
            15 首，用户还得再点一次执行才能到 20 首。
        """
        try:
            self.quota_exhausted = False
            # getattr：子类/测试替身可能不调用 super().__init__
            stale = getattr(self, "_prefetched", None)
            # 不管用不用，都清掉预取：它可能已经是基础任务评完之前的旧批次
            self._prefetched = None
            prefetched = None if refresh else stale
            if prefetched is not None:
                extra_tasks, completed_count = prefetched
            else:
                try:
                    extra_tasks, completed_count = self._get_extra_tasks()
                except Exception:
                    if stale is None:
                        raise
                    # 重新拉取失败时宁可沿用旧批次，也别让额外阶段整个失败
                    self.logger.warning("重新拉取额外任务失败，沿用执行前的清单")
                    extra_tasks, completed_count = stale
            self._remember_completed(task_id, getattr(self, "last_all", []) or [])
            full = bool(self.config.get('full_extra_tasks', False))
            limit = self._DAILY_MAX if full else 7
            # 今日已完成的额外曲目：服务端清单里的已评作品 + 本机账本里今天
            # 已提交的额外曲目，取较大者——服务端额外清单是分批的，早上评过的
            # 几首这次可能不再列出，只按清单算会把剩余额度多算，进度显示成 1/15
            # 而实际只剩 10 首，评到一半服务端才回「没有更多」。
            extra_before = max(completed_count, int(local_extra_done or 0))
            max_new = max(0, limit - extra_before)
            target = min(len(extra_tasks), max_new)

            if not extra_tasks:
                self.logger.info(f"额外评定完成数: {completed_count}")
                return

            # 如果已经完成任务，直接返回
            if target <= 0:
                self.logger.info(f"今日已完成 {extra_before} 个额外评分任务，已达到每日上限")
                return
            self.logger.info(
                f"发现 {len(extra_tasks)} 个待额外评定任务"
                f"（今日还可评 {target} 首）")

            # 跨轮累计的成功数：进度条只前进，补跑时不会倒回 0
            success_count = 0
            #: 本轮已评上的作品 id：补跑重新拉清单时服务端标记可能滞后，
            #: 同一首会原样返回；不剔除就会把它再算一次成功
            done_ids: set = set()
            #: 服务端拒绝（资源状态异常）而被跳过的歌名，最后要告诉用户缺哪首
            skipped: list = []
            #: 本轮已被服务端明确拒绝的作品 id：补跑轮别再请求同一首
            rejected: set = set()
            # 先给一个 0/total，进度条在等待第一首歌时就能显示任务总量
            if self.on_progress:
                try:
                    self.on_progress(0, target, "", "")
                except Exception as e:
                    self.logger.warning(f"on_progress 回调异常: {e}")

            no_more = False
            for attempt in range(self._MAX_PASSES):
                # 额度用完才停。这里不能用 target：首轮清单可能只有一批
                # （15 首里的 10 首），target 会等于这批的数量；按 max_new
                # 判断才能触发补跑，把服务端后来放出的批次评完。
                if success_count >= max_new:
                    break
                if attempt:
                    # 补跑前重新核对服务端状态，别拿旧列表硬跑
                    try:
                        extra_tasks, completed_count = self._get_extra_tasks()
                    except Exception as e:
                        self.logger.warning(f"补跑检查失败，结束额外评分: {e}")
                        break
                    self._remember_completed(
                        task_id, getattr(self, "last_all", []) or [])
                    # 本轮已经评上的不再算一遍
                    extra_tasks = [
                        task for task in extra_tasks
                        if _work_key(task.get("work") or {}) not in done_ids
                    ]
                    target = min(max_new, max(
                        target, success_count + len(extra_tasks)))
                    if not extra_tasks or success_count >= target:
                        self.logger.info("补跑检查：没有剩余额外任务")
                        break
                    self.logger.info(
                        f"补跑检查：还有 {target - success_count} 个额外任务未完成")

                for task in extra_tasks:
                    if success_count >= target:
                        break

                    work = task.get("work") or {}
                    work_key = _work_key(work)
                    if work_key and (work_key in rejected or work_key in done_ids):
                        # 上一轮已明确拒绝 / 已经评上的，重复执行也不会多评一首
                        continue

                    # 任务循环开始处响应取消
                    if self.cancel_event is not None and self.cancel_event.is_set():
                        self.logger.info("用户取消任务，停止额外评分")
                        raise CancelledError("用户取消任务，停止额外评分")

                    try:
                        rated = self._process_single_task(
                            task, task_id,
                            done_offset=success_count,
                            total=target,
                        )
                        if not rated:
                            # 服务端返回「资源状态异常」这类跳过：不能算成功，
                            # 否则本地计数会比网易云上实际评过的多一首。
                            if work_key:
                                rejected.add(work_key)
                            skipped.append(str(work.get("name") or ""))
                            self.logger.info("本首未计入成功，补跑轮次会再核对")
                            continue
                        success_count += 1
                        if work_key:
                            done_ids.add(work_key)
                        self.logger.info(f"成功完成第 {success_count}/{target} 个额外评分任务")

                    except CancelledError:
                        # 取消异常必须向上传递，不能按单首失败吞掉
                        raise
                    except Exception as e:
                        # 服务端说没有更多可评的歌了：这是完成信号，不是额度异常
                        if "没有更多" in str(e):
                            self.logger.info(
                                "今日已没有更多可评定歌曲，今日额外额度已用完")
                            no_more = True
                            self.quota_exhausted = True
                            break
                        self.logger.warning(
                            f"处理歌曲 {work.get('name') or '未知曲目'} 失败，"
                            f"尝试下一个: {str(e)}")
                        continue
                if no_more:
                    break

            if no_more:
                return
            if success_count < target:
                hint = ""
                if skipped:
                    hint = ("：" + "、".join(n for n in skipped if n)
                            + "（服务端拒绝的作品，重复执行也不会成功）")
                self.logger.warning(
                    f"检查后仍有 {target - success_count} 个额外评分任务未完成{hint}")
            else:
                self.logger.info(f"额外评分任务处理完成，成功评分 {success_count} 首")
        except CancelledError:
            raise
        except Exception as e:
            self.logger.error(f"处理额外评分任务时出错: {str(e)}")
            raise
    def _remember_completed(self, task_id, tasks) -> None:
        """把服务端标成已完成的额外曲目记进账本。

        这样即使下次运行服务端的完成标记滞后，同一任务里也不会再提交一遍。
        """
        ledger = getattr(self, "ledger", None)
        if ledger is None:
            return
        for task in tasks or []:
            try:
                work = task.get("work") or {}
                score = clean_score(task.get("score"))
                # 有合法分数就说明已经评过，completed 标记可能滞后
                if work.get("id") is None or not score:
                    continue
                ledger.mark(getattr(self, "account", ""), task_id,
                            work.get("id"), score)
            except Exception:
                continue

    def _emit_works(self, extra_tasks) -> None:
        """把额外任务的曲目清单交给界面，先摆成"待评"行。

        不给的话，用户点执行只会在曲目表里看到基础任务的 5 首，
        以为"今天只评了 5 首"，实际上额外任务还有一大批。
        """
        # 用 getattr：子类/测试替身可能不调用 super().__init__，没有这个属性
        callback = getattr(self, "on_works", None)
        if not callback:
            return
        try:
            for task in extra_tasks or []:
                task["_group"] = "extra"
            callback(list(extra_tasks or []))
        except Exception as e:
            # 测试替身的 logger 可能没有 debug，这里不能因为日志把任务打断
            try:
                getattr(self.logger, "debug", self.logger.info)(
                    f"on_works 回调异常: {e}")
            except Exception:
                pass

    def _get_extra_tasks(self, emit: bool = True) -> Tuple[List[Dict], int]:
        """获取额外评分任务列表"""
        try:
            response = self.session.get(
                url=self.api["extra_list"],
                headers={"Referer": "https://mp.music.163.com/"}
            ).json()
            if response["code"] != 200:
                raise RuntimeError(f"获取额外任务失败: {response.get('message', '未知错误')}")
            # 接口会把当天基础任务也列在待评清单里；基础阶段已经负责它们，
            # 这里剔除，确保「基础 5 + 额外 15 = 20」的额度和曲目表都不重复计数
            extra_tasks = [t for t in (response["data"] or [])
                           if isinstance(t, dict) and not self._is_base_work(t)]
            #: 最近一次拉到的整份清单，供上层与基础任务合并后一次性交给界面
            self.last_all = extra_tasks
            if emit:
                self._emit_works(extra_tasks)
            completed_tasks = [
                t for t in extra_tasks
                if t.get("completed") or clean_score(t.get("score"))
            ]
            uncompleted_tasks = [
                t for t in extra_tasks
                if not (t.get("completed") or clean_score(t.get("score")))
            ]

            # 获取所有未完成的任务，而不是只取前7个
            return uncompleted_tasks, len(completed_tasks)
        except Exception as e:
            self.logger.error(f"获取额外任务列表失败: {str(e)}")
            raise
    def _process_single_task(self, task: Dict, task_id: str,
                             done_offset: int = 0, total: Optional[int] = None) -> bool:
        """处理单个额外评分任务。返回服务端是否真的记下了这次评分。"""
        work = task['work']
        try:
            signer = Signer(
                self.session, task_id, self.logger, self.config,
                on_progress=self.on_progress,
                cancel_event=self.cancel_event,
                total=total,
                done_offset=done_offset,
                on_note=self.on_note,
                ledger=self.ledger,
                account=self.account,
            )

            # 本任务已确认收下的，连听歌上报都不用再发
            if signer.already_rated(work) is not None:
                return signer.sign(work, is_extra=True)

            # 1. 上报听歌记录
            self._report_listen(work)

            # 2. 评分
            return signer.sign(work, is_extra=True)
        except NoMoreWorksError:
            # 当天额度用完：正常的完成信号，不按「处理失败」打 ERROR
            raise
        except CancelledError:
            # 用户在评分入口处取消，直接透传，不按失败记录日志
            raise
        except Exception as e:
            self.logger.error(f"处理额外任务失败 - {work['name']}: {str(e)}")
            raise
    def _report_listen(self, work: Dict) -> None:
        """上报听歌记录"""
        try:
            csrf = self.session.cookies["__csrf"]

            # 准备加密数据
            data = {
                "workId": work['id'],
                "resourceId": work['resourceId'],
                "bizResourceId": "",
                "interactType": "PLAY_END",
                "csrf_token": csrf
            }

            # 使用相同的加密方式
            params = {
                "params": self.signer._get_params(data),
                "encSecKey": self.signer._get_enc_sec_key()
            }

            response = self.session.post(
                url=f"{self.api['report_listen']}?csrf_token={csrf}",
                data=params,
                headers={"Referer": "https://mp.music.163.com/"}
            ).json()
            if response["code"] != 200:
                raise RuntimeError(f"上报听歌记录失败: {response.get('message', '未知错误')}")
            else:
                self.logger.info(f"歌曲 {work['name']} 听歌记录上报成功")
        except Exception as e:
            self.logger.error(f"上报听歌记录失败: {str(e)}")
            raise
