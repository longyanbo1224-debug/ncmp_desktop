"""bot 把曲目清单交给界面时的参数契约。

这里曾经把"合并后的列表"传进一个按 dict 取值的函数，异常被吞掉，
界面一行都没收到——用户看到的是"歌曲一首一首冒出来"。
"""
import unittest

from core.bot import MusicPartnerBot


class _Config:
    def get(self, key, default=None):
        return default


class _Logger:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class TestEmitWorks(unittest.TestCase):
    def test_accepts_merged_list(self):
        received = []
        bot = MusicPartnerBot(_Config(), _Logger(), None, on_works=received.extend)
        bot._emit_works([
            {"work": {"name": "基础一"}, "completed": False},
            {"work": {"name": "额外一"}, "completed": True, "score": 4},
        ])
        self.assertEqual(len(received), 2)
        self.assertEqual(received[1]["work"]["name"], "额外一")

    def test_empty_input_is_fine(self):
        received = []
        bot = MusicPartnerBot(_Config(), _Logger(), None, on_works=received.extend)
        bot._emit_works(None)
        self.assertEqual(received, [])


if __name__ == "__main__":
    unittest.main()
