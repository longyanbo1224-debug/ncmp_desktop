"""Signer.sign 的返回值契约：只有服务端真的记下评分才返回 True。

这个契约决定"本地计数"和"网易云上看到的评分"是否一致：
把「资源状态异常」当成功，本地就会比线上多一首（用户报过 20 vs 19）。
"""
import unittest

from core.signer import RequestPacer, Signer

_WORK = {"id": 1, "name": "夜航西飞", "authorName": "某乐队"}


class _Resp:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class _Session:
    def __init__(self, payload, get_payload=None):
        self.payload = payload
        self.get_payload = get_payload or {"data": {"works": []}}
        self.cookies = {"__csrf": "csrf-token"}
        self.posts = 0
        self.gets = []

    def post(self, *args, **kwargs):
        self.posts += 1
        return _Resp(self.payload)

    def get(self, *args, **kwargs):
        self.gets.append((args, kwargs))
        return _Resp(self.get_payload)


class _Ledger:
    def __init__(self, scores=None):
        self.scores = dict(scores or {})
        self.marked = []

    def score(self, account, task_id, work_id):
        return self.scores.get(str(work_id))

    def mark(self, account, task_id, work_id, score):
        self.marked.append((account, task_id, str(work_id), score))


class _Config:
    def get(self, key, default=None):
        return {"score": 3, "note_enabled": False}.get(key, default)

    def get_wait_time(self):
        return 0.0


class _CountingConfig(_Config):
    def __init__(self):
        self.waits = 0

    def get_wait_time(self):
        self.waits += 1
        return 0.0


class _Logger:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def _signer(payload, session=None, ledger=None, config=None, pacer=None) -> Signer:
    return Signer(session or _Session(payload), "task", _Logger(), config or _Config(),
                  ledger=ledger, pacer=pacer)


class TestSignReturn(unittest.TestCase):
    def test_success_returns_true_and_counts(self):
        signer = _signer({"code": 200})
        self.assertTrue(signer.sign(_WORK))
        self.assertEqual(signer.done, 1)

    def test_resource_abnormal_returns_false_and_does_not_count(self):
        """「资源状态异常」= 服务端没评上，必须返回 False 且不推进计数。"""
        signer = _signer({"code": 405, "message": "资源状态异常"})
        self.assertFalse(signer.sign(_WORK))
        self.assertEqual(signer.done, 0)

    def test_other_error_raises(self):
        signer = _signer({"code": 500, "message": "服务器错误"})
        with self.assertRaises(RuntimeError):
            signer.sign(_WORK)

    def test_ledger_hit_skips_request(self):
        """本地账本已记过：不再发评分请求，但按已评推进计数。"""
        session = _Session({"code": 500, "message": "不该被调用"})
        ledger = _Ledger({"1": "4"})
        signer = _signer(None, session=session, ledger=ledger)

        self.assertTrue(signer.sign(_WORK))
        self.assertEqual(session.posts, 0)
        self.assertEqual(signer.done, 1)

    def test_success_is_written_to_ledger(self):
        ledger = _Ledger()
        signer = _signer({"code": 200}, ledger=ledger)

        self.assertTrue(signer.sign(_WORK))
        self.assertEqual(ledger.marked, [("", "task", "1", "3")])

    def test_rejected_work_is_not_written_to_ledger(self):
        ledger = _Ledger()
        signer = _signer({"code": 405, "message": "资源状态异常"}, ledger=ledger)

        self.assertFalse(signer.sign(_WORK))
        self.assertEqual(ledger.marked, [])

    def test_confirm_extra_checks_extra_endpoint(self):
        """额外曲目不在每日任务列表里，确认必须查额外清单。"""
        session = _Session(None, get_payload={
            "data": [{"work": {"id": 1}, "completed": True}]})
        signer = _signer(None, session=session)

        self.assertTrue(signer._confirm_rated(_WORK, is_extra=True))
        url = session.gets[0][1].get("url") or session.gets[0][0][0]
        self.assertIn("extra/wait/evaluate/work/list", url)

    def test_first_request_does_not_wait(self):
        """整轮第一次真实请求直接发；第二次起才等待。"""
        config = _CountingConfig()
        pacer = RequestPacer()
        signer = _signer({"code": 200}, config=config, pacer=pacer)
        second = {"id": 2, "name": "另一首", "authorName": "某乐队"}

        self.assertTrue(signer.sign(_WORK))
        self.assertEqual(config.waits, 0)
        self.assertTrue(signer.sign(second))
        self.assertEqual(config.waits, 1)


if __name__ == "__main__":
    unittest.main()
