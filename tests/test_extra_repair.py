"""额外评分补跑的自检（不联网，用内存里的假任务列表）。

跑法：``python -m unittest tests.test_extra_repair``
"""
import unittest

from core.tasks.extra import ExtraTask


class _Logger:
    def __init__(self) -> None:
        self.lines = []

    def info(self, msg): self.lines.append(("info", msg))
    def warning(self, msg): self.lines.append(("warning", msg))
    def error(self, msg): self.lines.append(("error", msg))
    def debug(self, msg): pass


class _Config:
    def __init__(self, full: bool) -> None:
        self.full = full

    def get(self, key, default=None):
        return self.full if key == "full_extra_tasks" else default

    def get_wait_time(self) -> float:
        return 0.0


class _FakeExtra(ExtraTask):
    """把网络调用换成脚本化的任务列表。"""

    def __init__(self, script, full: bool = True, fail_on=(12, 13, 14),
                 no_more: bool = False, skip_on=()) -> None:
        self.logger = _Logger()
        self.config = _Config(full)
        self.cancel_event = None
        self.progress = []
        self.on_progress = lambda done, total, song, score: self.progress.append(
            (done, total))
        self.script = script
        self.fetches = 0
        self.attempts = 0
        self.fail_on = set(fail_on)
        self.no_more = no_more
        #: 这些次序的尝试会被"服务端跳过"（如资源状态异常），应返回 False
        self.skip_on = set(skip_on)

    def _get_extra_tasks(self):
        pending, completed = self.script[min(self.fetches, len(self.script) - 1)]
        self.fetches += 1
        return ([{"work": {"name": f"w{i}", "id": i}} for i in range(pending)],
                completed)

    def _process_single_task(self, task, task_id, done_offset=0, total=None) -> bool:
        self.attempts += 1
        if self.no_more:
            raise RuntimeError("评分失败: 今日没有更多可评定歌曲啦 (响应码: 405)")
        if self.attempts in self.fail_on:
            raise RuntimeError("模拟单首失败")
        if self.attempts in self.skip_on:
            return False
        self.on_progress(done_offset + 1, total,
                         task["work"]["name"], "4")
        return True


class ExtraRepairTest(unittest.TestCase):
    def test_skipped_songs_are_retried_until_complete(self):
        # 首轮 15 条，末尾 3 条失败；补跑时服务端只剩这 3 条
        job = _FakeExtra([(15, 0), (3, 12)])
        job.process_extra_tasks("task")

        self.assertEqual(job.fetches, 2, "补跑前必须重新核对服务端")
        self.assertEqual(job.attempts, 18)
        # 进度只能前进，补跑不能把 done 拉回 0
        done = [d for d, _ in job.progress]
        self.assertEqual(done, sorted(done))
        self.assertTrue(all(t == 15 for _, t in job.progress))

    def test_limited_mode_stops_at_seven(self):
        job = _FakeExtra([(10, 0)], full=False, fail_on=())
        job.process_extra_tasks("task")

        self.assertEqual(job.attempts, 7)
        self.assertEqual(job.fetches, 1)

    def test_skipped_song_is_not_counted_as_success(self):
        """服务端跳过（资源状态异常）的一首不能算成功，否则本地比网易云多一首。"""
        job = _FakeExtra([(10, 0)], full=False, fail_on=(), skip_on={1})
        job.process_extra_tasks("task")

        messages = [m for _, m in job.logger.lines]
        self.assertEqual(job.attempts, 8, "跳过的那首要再评一首补足 7 个")
        self.assertTrue(any("成功完成第 7/7" in m for m in messages), messages)
        self.assertFalse(any("仍有" in m for m in messages), messages)

    def test_no_more_songs_is_completion_not_shortfall(self):
        # 405「今日没有更多可评定歌曲」= 今天已经评完，不能报"还有 15 个没完成"
        job = _FakeExtra([(15, 0)], fail_on=(), no_more=True)
        job.process_extra_tasks("task")

        messages = [m for _, m in job.logger.lines]
        self.assertEqual(job.fetches, 1, "没有更多时不应再补跑")
        self.assertTrue(any("额外任务今日已全部完成" in m for m in messages))
        self.assertFalse(any("仍有" in m for m in messages))


if __name__ == "__main__":
    unittest.main()
