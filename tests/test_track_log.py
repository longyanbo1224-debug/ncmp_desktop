"""曲目账本的分数口径：服务端的 "4.0" 必须按 4 分计入。

用户报过「口味曲线只显示今天的 20 首，昨天评的没累加」：昨天的记录是通过
服务端同步写进账本的，分数是浮点字符串（``4.0``），``int()`` 解析失败后被
当成「没有分数」，于是只有今天（本地评分回调写入整数）的记录进了曲线。
"""
import tempfile
import unittest
from pathlib import Path

from app.track_log import TrackLog, clean_score


class CleanScoreTest(unittest.TestCase):
    def test_integer_strings(self):
        for text in ("1", "3", "5", " 4 "):
            self.assertEqual(clean_score(text), text.strip())

    def test_float_strings_are_normalized(self):
        """服务端偶尔返回 4.0：按 4 分处理，而不是丢掉。"""
        self.assertEqual(clean_score("4.0"), "4")
        self.assertEqual(clean_score(3.0), "3")

    def test_invalid_values(self):
        for bad in ("", None, "null", "NULL", 0, "0", "4.5", "abc", "inf"):
            self.assertEqual(clean_score(bad), "", bad)


class TrackLogStatsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "track_log.json"
        self.log = TrackLog(path=self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_float_scores_count_into_tiers(self):
        self.log.record("浮点一", score="4.0")
        self.log.record("浮点二", score="3.0")

        stats = self.log.stats()
        self.assertEqual(stats["tiers"], {"4": 1, "3": 1})
        self.assertEqual(stats["unscored"], 0)

    def test_legacy_float_scores_in_file_are_counted(self):
        """旧账本里已经落盘的 "4.0" 也要算进曲线，不用用户重跑。"""
        self.path.write_text(
            '{"2026-11-06": [{"song": "旧歌", "score": "4.0", "state": "submitted"}]}',
            encoding="utf-8",
        )

        stats = self.log.stats()
        self.assertEqual(stats["tiers"], {"4": 1})
        self.assertEqual(stats["unscored"], 0)

    def test_recent_scores_are_clean(self):
        self.log.record("浮点", score="4.0", day="2026-11-06")
        self.assertEqual(self.log.recent(1)[0]["score"], "4")


if __name__ == "__main__":
    unittest.main()
