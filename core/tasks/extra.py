import json
import random
import time
from typing import Dict, List, Tuple, Optional
from core import CancelledError
from ..signer import Signer
class ExtraTask:
    def __init__(self, session, logger, config, on_progress=None, cancel_event=None):
        self.session = session
        self.logger = logger
        self.config = config
        self.on_progress = on_progress
        self.cancel_event = cancel_event
        self.api = {
            "extra_list": "https://interface.music.163.com/api/music/partner/extra/wait/evaluate/work/list",
            "report_listen": "https://interface.music.163.com/weapi/partner/resource/interact/report"
        }
        self.signer = Signer(session, "", logger, config)  # task_id 为空字符串，因为上报听歌不需要
    #: 额外评分最多跑几轮：首轮 + 一次补跑。
    #: 单首失败只跳过不重试，跑完不重新核对就会"15 条只评了 12 首"却报成功。
    _MAX_PASSES = 2

    def process_extra_tasks(self, task_id: str) -> None:
        """处理额外的评分任务。

        每轮结束后重新拉一次任务列表：单首失败被跳过时，服务端仍把它标成
        未完成，补跑这一轮就能把漏掉的补上，用户不必再手动点一次执行。
        """
        try:
            extra_tasks, completed_count = self._get_extra_tasks()
            full = bool(self.config.get('full_extra_tasks', False))
            target = len(extra_tasks) if full else 7 - completed_count

            # 如果已经完成任务，直接返回
            if target <= 0:
                self.logger.info(f"今日已完成 {completed_count} 个额外评分任务，已达到每日上限")
                return

            if not extra_tasks:
                self.logger.info(f"额外评定完成数: {completed_count}")
                return
            self.logger.info(f"发现 {len(extra_tasks)} 个待额外评定任务")

            # 跨轮累计的成功数：进度条只前进，补跑时不会倒回 0
            success_count = 0
            # 先给一个 0/total，进度条在等待第一首歌时就能显示任务总量
            if self.on_progress:
                try:
                    self.on_progress(0, target, "", "")
                except Exception as e:
                    self.logger.warning(f"on_progress 回调异常: {e}")

            for attempt in range(self._MAX_PASSES):
                if success_count >= target:
                    break
                if attempt:
                    # 补跑前重新核对服务端状态，别拿旧列表硬跑
                    try:
                        extra_tasks, completed_count = self._get_extra_tasks()
                    except Exception as e:
                        self.logger.warning(f"补跑检查失败，结束额外评分: {e}")
                        break
                    if full:
                        target = max(target, success_count + len(extra_tasks))
                    else:
                        target = max(target, 7 - completed_count)
                    if not extra_tasks or success_count >= target:
                        self.logger.info("补跑检查：没有剩余额外任务")
                        break
                    self.logger.info(
                        f"补跑检查：还有 {target - success_count} 个额外任务未完成")

                quota_exhausted = False
                for task in extra_tasks:
                    if success_count >= target:
                        break

                    # 任务循环开始处响应取消
                    if self.cancel_event is not None and self.cancel_event.is_set():
                        self.logger.info("用户取消任务，停止额外评分")
                        raise CancelledError("用户取消任务，停止额外评分")

                    try:
                        self._process_single_task(
                            task, task_id,
                            done_offset=success_count,
                            total=target,
                        )
                        # 只有在没有抛出异常时才增加成功计数
                        success_count += 1
                        self.logger.info(f"成功完成第 {success_count}/{target} 个额外评分任务")

                        # 添加随机等待时间
                        if success_count < target:  # 最后一个任务不需要等待
                            delay = self.config.get_wait_time()
                            self.logger.info(f"等待 {delay:.1f} 秒后继续...")
                            time.sleep(delay)

                    except CancelledError:
                        # 取消异常必须向上传递，不能按单首失败吞掉
                        raise
                    except Exception as e:
                        # 额度用完时后面每一首都会失败，立刻停，别空转
                        if "没有更多" in str(e):
                            self.logger.info("今日额外评分额度已用完，停止")
                            quota_exhausted = True
                            break
                        self.logger.warning(f"处理歌曲 {task['work']['name']} 失败，尝试下一个: {str(e)}")
                        continue
                if quota_exhausted:
                    break

            if success_count < target:
                self.logger.warning(
                    f"检查后仍有 {target - success_count} 个额外评分任务未完成")
            else:
                self.logger.info(f"额外评分任务处理完成，成功评分 {success_count} 首")
        except CancelledError:
            raise
        except Exception as e:
            self.logger.error(f"处理额外评分任务时出错: {str(e)}")
            raise
    def _get_extra_tasks(self) -> Tuple[List[Dict], int]:
        """获取额外评分任务列表"""
        try:
            response = self.session.get(
                url=self.api["extra_list"],
                headers={"Referer": "https://mp.music.163.com/"}
            ).json()
            if response["code"] != 200:
                raise RuntimeError(f"获取额外任务失败: {response.get('message', '未知错误')}")
            extra_tasks = response["data"]
            completed_tasks = [t for t in extra_tasks if t['completed']]
            uncompleted_tasks = [t for t in extra_tasks if not t['completed']]

            # 获取所有未完成的任务，而不是只取前7个
            return uncompleted_tasks, len(completed_tasks)
        except Exception as e:
            self.logger.error(f"获取额外任务列表失败: {str(e)}")
            raise
    def _process_single_task(self, task: Dict, task_id: str,
                             done_offset: int = 0, total: Optional[int] = None) -> None:
        """处理单个额外评分任务"""
        work = task['work']
        try:
            # 1. 上报听歌记录
            self._report_listen(work)

            # 2. 评分
            signer = Signer(
                self.session, task_id, self.logger, self.config,
                on_progress=self.on_progress,
                cancel_event=self.cancel_event,
                total=total,
                done_offset=done_offset,
            )
            signer.sign(work, is_extra=True)
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
