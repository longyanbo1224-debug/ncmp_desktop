"""Signer.sign 的返回值契约：只有服务端真的记下评分才返回 True。

这个契约决定"本地计数"和"网易云上看到的评分"是否一致：
把「资源状态异常」当成功，本地就会比线上多一首（用户报过 20 vs 19）。
"""
import unittest

from core.signer import Signer

_WORK = {"id": 1, "name": "夜航西飞", "authorName": "某乐队"}


class _Resp:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class _Session:
    def __init__(self, payload):
        self.payload = payload
        self.cookies = {"__csrf": "csrf-token"}

    def post(self, *args, **kwargs):
        return _Resp(self.payload)

    def get(self, *args, **kwargs):
        return _Resp({"data": {"works": []}})


class _Config:
    def get(self, key, default=None):
        return {"score": 3, "note_enabled": False}.get(key, default)

    def get_wait_time(self):
        return 0.0


class _Logger:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def _signer(payload) -> Signer:
    return Signer(_Session(payload), "task", _Logger(), _Config())


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


if __name__ == "__main__":
    unittest.main()
