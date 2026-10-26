"""失败处理策略的自检：限流重试上限 + 基础阶段额度用完不判失败。

跑法：``python -m unittest tests.test_failure_policy``
"""
import unittest

import core.tasks.daily as daily_mod
from core.signer import Signer
from core.tasks.daily import DailyTask


class _Logger:
    def __init__(self) -> None:
        self.lines = []

    def info(self, msg): self.lines.append(("info", msg))
    def warning(self, msg): self.lines.append(("warning", msg))
    def error(self, msg): self.lines.append(("error", msg))
    def debug(self, msg): pass


class _Config:
    def get(self, key, default=None):
        return 4 if key == "score" else default

    def get_wait_time(self) -> float:
        return 0.0


class _Response:
    def __init__(self, payload) -> None:
        self.payload = payload

    def json(self):
        return self.payload


class _Session:
    def __init__(self, responses) -> None:
        self.cookies = {"__csrf": "test"}
        self._responses = list(responses)
        self.posts = 0

    def post(self, url, data):
        self.posts += 1
        return _Response(self._responses.pop(0))


class SignerRetryTest(unittest.TestCase):
    def test_rate_limit_gives_up_after_three_attempts(self):
        session = _Session([{"code": 400, "message": "操作频繁"}] * 5)
        signer = Signer(session, "task", _Logger(), _Config())

        with self.assertRaises(RuntimeError):
            signer.sign({"name": "a", "authorName": "b", "id": 1})

        self.assertEqual(session.posts, 3)


class DailyQuotaTest(unittest.TestCase):
    def test_quota_exhausted_stops_base_phase_without_raising(self):
        calls = []

        class _FakeSigner:
            def __init__(self, *args, **kwargs): pass

            def sign(self, work):
                calls.append(work["name"])
                if work["name"] == "b":
                    raise RuntimeError("评分过程出错: 评分失败: 没有更多可评定歌曲")

        original = daily_mod.Signer
        daily_mod.Signer = _FakeSigner
        try:
            task = DailyTask(session=None, logger=_Logger(), config=_Config())
            task._process_tasks({
                "id": "task",
                "works": [
                    {"work": {"name": n, "authorName": ""}, "completed": False}
                    for n in ("a", "b", "c")
                ],
            })
        finally:
            daily_mod.Signer = original

        # b 额度用完就停，c 不该再发请求；整个过程不抛异常（不算失败）
        self.assertEqual(calls, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
