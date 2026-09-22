from typing import Dict, Tuple
from ..signer import Signer
from .base import BaseTask
class DailyTask(BaseTask):
    def __init__(self, session, logger, config, on_progress=None, cancel_event=None):
        super().__init__(session, logger, config)
        self.on_progress = on_progress
        self.cancel_event = cancel_event
        self.api = {
            "task_data": "https://interface.music.163.com/api/music/partner/daily/task/get"
        }
    def execute(self) -> bool:
        try:
            complete, task_data = self._get_daily_tasks()
            if not complete:
                self._process_tasks(task_data)
            return True
        except Exception as e:
            self.logger.error(f"执行每日任务失败: {str(e)}")
            return False
    def _get_daily_tasks(self) -> Tuple[bool, Dict]:
        """获取每日任务"""
        response = self.session.get(url=self.api["task_data"]).json()
        task_data = response.get("data", {})

        count = task_data.get("count", 0)
        completed_count = task_data.get("completedCount", 0)
        today_task = f"[{completed_count}/{count}]"
        complete = count == completed_count

        self.logger.info(f'今日任务：{"已完成" if complete else "未完成"}{today_task}')
        return complete, task_data
    def _process_tasks(self, task_data: Dict) -> None:
        """处理未完成的任务"""
        self.logger.info("开始评分...")
        works = task_data.get("works", [])
        # 只统计待评分的作品，避免「已评分作品计入 total 但不会推进 done」导致进度条不动
        pending_works = [task for task in works if not task.get("completed", False)]
        total = len(pending_works)
        if total <= 0:
            self.logger.info("没有待评分作品")
            return
        signer = Signer(
            self.session, task_data["id"], self.logger, self.config,
            on_progress=self.on_progress,
            cancel_event=self.cancel_event,
            total=total,
        )
        self._emit_progress(0, total)

        for task in works:
            work = task["work"]
            if task.get("completed", False):
                self.logger.info(f'{work["name"]}「{work["authorName"]}」已有评分：{int(task["score"])}分')
            else:
                signer.sign(work)

    def _emit_progress(self, done: int, total: int,
                       song: str = "", score: str = "") -> None:
        """发出进度回调；回调异常不影响任务主流程。"""
        if not self.on_progress:
            return
        try:
            self.on_progress(done, total, song, score)
        except Exception as e:
            self.logger.debug(f"on_progress 回调异常: {e}")
