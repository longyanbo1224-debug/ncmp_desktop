"""桌面端一轮任务的端到端流程（假服务端，不联网、不写真实账本）。

覆盖用户反馈的核心流程：首次点「开始评分」时服务端只放出 15 首
（基础 5 + 额外 10），基础 5 首评完后额外清单才会放出剩下的 5 首。
以前评完第一批（15 首）就结束，用户要再点一次才能到 20 首；现在同一次
执行会重新拉清单并补满 20 首。
"""
import tempfile
import unittest
from pathlib import Path

import core.bot as bot_mod
from core.bot import MusicPartnerBot
from core.quota_state import QuotaState
from core.rating_ledger import RatingLedger

_DAILY_URL = "https://interface.music.163.com/api/music/partner/daily/task/get"
_EXTRA_URL = "https://interface.music.163.com/api/music/partner/extra/wait/evaluate/work/list"
_USER_URL = "https://music.163.com/api/nuser/account/get"
_SIGN_URL = "https://interface.music.163.com/weapi/music/partner/work/evaluate"
_LISTEN_URL = "https://interface.music.163.com/weapi/partner/resource/interact/report"


class _Resp:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class _FakeServer:
    """模拟每日 5 首基础 + 15 首额外，额外接口每次最多返回 15 条。"""

    def __init__(self, no_more: bool = False):
        self.base_ids = list(range(1, 6))
        self.extra_ids = list(range(101, 116))
        self.rated = {}
        self.evaluated = []
        #: true 时：基础评完后的第一次额外评分返回 405「今日没有更多」
        self.no_more = no_more
        self.listens = 0
        # 按本次执行的真实顺序：基础 5 首 → 额外 15 首
        self.submit_order = list(self.base_ids) + list(self.extra_ids)
        self.daily_gets = 0
        self.extra_gets = 0

    # -- 服务端状态 ----------------------------------------------------
    @staticmethod
    def _work(work_id):
        return {
            "id": work_id,
            "name": f"歌{work_id}",
            "authorName": "某乐队",
            "resourceId": work_id + 1000,
        }

    def _item(self, work_id):
        score = self.rated.get(work_id)
        return {
            "work": self._work(work_id),
            "completed": score is not None,
            "score": score if score is not None else 0,
        }

    def _waiting(self):
        """待评作品：未评的基础任务也会出现在额外清单里，接口给满 15 条。"""
        ids = [i for i in self.base_ids if i not in self.rated]
        ids += [i for i in self.extra_ids if i not in self.rated]
        return ids[:15]

    # -- 伪造 session --------------------------------------------------
    @property
    def cookies(self):
        return {"__csrf": "csrf-token"}

    def get(self, url=None, *args, **kwargs):
        url = url or kwargs.get("url") or ""
        if url == _USER_URL:
            return _Resp({"profile": {"nickname": "测试用户", "userId": 1}})
        if url == _DAILY_URL:
            self.daily_gets += 1
            done = sum(1 for i in self.base_ids if i in self.rated)
            return _Resp({"code": 200, "data": {
                "id": "task-1",
                "count": len(self.base_ids),
                "completedCount": done,
                "works": [self._item(i) for i in self.base_ids],
            }})
        if url == _EXTRA_URL:
            self.extra_gets += 1
            return _Resp({"code": 200, "data": [self._item(i) for i in self._waiting()]})
        return _Resp({"code": 200, "data": {}})

    def post(self, url=None, *args, **kwargs):
        url = url or kwargs.get("url") or ""
        if url.startswith(_LISTEN_URL):
            self.listens += 1
            return _Resp({"code": 200})
        if url.startswith(_SIGN_URL):
            # 基础 5 首评完后再评额外：服务端说今天已经没有额外额度
            if self.no_more and len(self.evaluated) >= len(self.base_ids):
                return _Resp({"code": 405, "message": "今日没有更多可评定歌曲啦"})
            if not self.submit_order:
                return _Resp({"code": 500, "message": "评多了"})
            work_id = self.submit_order.pop(0)
            if work_id in self.rated:
                return _Resp({"code": 500, "message": "重复评分"})
            self.rated[work_id] = "4"
            self.evaluated.append(work_id)
            return _Resp({"code": 200})
        return _Resp({"code": 200})


class _Config:
    def get(self, key, default=None):
        return {
            "score": 3,
            "note_enabled": False,
            "note_source": "template",
            "note_voice": "restrained",
            "note_length": "standard",
            "note_max_chars": 80,
            "full_extra_tasks": True,
        }.get(key, default)

    def get_wait_time(self):
        return 0.0


class _Logger:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class OneRunReachesTwentyTest(unittest.TestCase):
    def test_single_run_rates_all_twenty(self):
        server = _FakeServer()
        works_emitted = []
        progress = []

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        original_ledger = bot_mod.RatingLedger
        bot_mod.RatingLedger = lambda: RatingLedger(
            Path(tmp.name) / "rated_works.json")
        try:
            bot = MusicPartnerBot(
                _Config(), _Logger(), server,
                on_works=works_emitted.append,
                on_progress=lambda done, total, song, score: progress.append(
                    (done, total)),
                quota_state=QuotaState(Path(tmp.name) / "quota.json"),
            )
            ok = bot.run()
        finally:
            bot_mod.RatingLedger = original_ledger

        self.assertTrue(ok, getattr(bot, "last_error", None))
        # 一次执行评完基础 5 + 额外 15
        self.assertEqual(sorted(server.evaluated), sorted(server.base_ids + server.extra_ids))
        self.assertEqual(len(server.evaluated), 20)
        # 基础评完后重新拉过额外清单（第二次 GET）
        self.assertEqual(server.extra_gets, 2)
        # 界面拿到的第一份清单是 15 行，第二份是补出来的 15 首额外
        self.assertEqual(len(works_emitted[0]), 15)
        last = works_emitted[-1]
        self.assertEqual(len(last), 15)
        self.assertTrue(all(t.get("_group") == "extra" for t in last))
        # 额外阶段进度评满 15/15
        self.assertEqual(progress[-1], (15, 15))


    def test_no_more_marks_extra_quota_exhausted(self):
        """基础评完、第一次额外评分就收到「今日没有更多」：按额度用尽处理。"""
        server = _FakeServer(no_more=True)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        original_ledger = bot_mod.RatingLedger
        bot_mod.RatingLedger = lambda: RatingLedger(
            Path(tmp.name) / "rated_works.json")
        try:
            quota = QuotaState(Path(tmp.name) / "quota.json")
            bot = MusicPartnerBot(_Config(), _Logger(), server, quota_state=quota)
            ok = bot.run()
        finally:
            bot_mod.RatingLedger = original_ledger

        self.assertTrue(ok, getattr(bot, "last_error", None))
        self.assertTrue(bot.extra_all_done)
        # 只评了基础 5 首；额外第一首收到 405 后没有再发请求
        self.assertEqual(server.evaluated, server.base_ids)
        self.assertTrue(quota.exhausted("1", "task-1"))

    def test_second_run_skips_extra_from_quota_cache(self):
        """同一天同一 taskId 已确认额度用完：第二次执行直接跳过额外阶段。"""
        server = _FakeServer(no_more=True)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        original_ledger = bot_mod.RatingLedger
        bot_mod.RatingLedger = lambda: RatingLedger(
            Path(tmp.name) / "rated_works.json")
        quota = QuotaState(Path(tmp.name) / "quota.json")
        try:
            first = MusicPartnerBot(_Config(), _Logger(), server, quota_state=quota)
            self.assertTrue(first.run(), getattr(first, "last_error", None))

            # 第二次：服务端这次若真能评，就会发请求；缓存命中应完全跳过
            server.no_more = False
            evaluated_before = list(server.evaluated)
            listens_before = server.listens
            extra_gets_before = server.extra_gets
            second = MusicPartnerBot(_Config(), _Logger(), server, quota_state=quota)
            self.assertTrue(second.run(), getattr(second, "last_error", None))
        finally:
            bot_mod.RatingLedger = original_ledger

        self.assertTrue(second.extra_all_done)
        self.assertEqual(server.evaluated, evaluated_before)
        self.assertEqual(server.listens, listens_before)
        # 本地命中后不再评分：只保留一次只读的额外清单拉取用于显示
        self.assertEqual(server.extra_gets, extra_gets_before + 1)


    def test_local_ledger_complete_skips_extra(self):
        """本地账本已达到基础 + 额外上限：不再发评分请求，直接按已评满处理。"""
        server = _FakeServer()
        # 服务端这边基础已完成；额外清单仍返回 15 条待评（模拟标记滞后）
        server.rated = {i: "4" for i in server.base_ids}

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ledger = RatingLedger(Path(tmp.name) / "rated_works.json")
        for work_id in server.base_ids + server.extra_ids:
            ledger.mark("1", "task-1", work_id, "4")

        bot = MusicPartnerBot(
            _Config(), _Logger(), server,
            quota_state=QuotaState(Path(tmp.name) / "quota.json"),
        )
        bot.ledger = ledger
        self.assertTrue(bot.run(), getattr(bot, "last_error", None))

        self.assertTrue(bot.extra_all_done)
        self.assertEqual(server.evaluated, [])
        self.assertEqual(server.listens, 0)
        self.assertEqual(server.extra_gets, 1)


    def test_local_history_complete_skips_extra(self):
        """本机今日曲目记录已经 20 首 submitted：直接按已评满处理，不再发评分请求。"""
        server = _FakeServer()
        server.rated = {i: "4" for i in server.base_ids}

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bot = MusicPartnerBot(
            _Config(), _Logger(), server,
            quota_state=QuotaState(Path(tmp.name) / "quota.json"),
            local_submitted_count=20,
        )
        # 不写用户真实的评分账本
        bot.ledger = RatingLedger(Path(tmp.name) / "rated_works.json")
        self.assertTrue(bot.run(), getattr(bot, "last_error", None))

        self.assertTrue(bot.extra_all_done)
        self.assertEqual(server.evaluated, [])
        self.assertEqual(server.listens, 0)
        self.assertEqual(server.extra_gets, 1)


if __name__ == "__main__":
    unittest.main()
