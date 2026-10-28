"""评分不变式 + 日志脱敏 + 积分解析的边界测试。

评分那组是"不变量测试"：不管作品名长什么样、选哪个策略，
分数都必须落在该策略声明的区间内——以后加新策略时这条会立刻报警。
"""
import itertools
import unittest

from core import scoring
from core.partner_points import parse_points
from core.utils.logger import redact


class TestScoreInvariants(unittest.TestCase):
    def test_every_strategy_and_work_stays_in_range(self):
        names = ("夜航西飞", "Song A", "", "夜 Song", "123", "ＡＢＣ")
        artists = ("某乐队", "Band", "", "乐队 X")
        works = [{"name": n, "authorName": a}
                 for n, a in itertools.product(names, artists)]
        ranges = {1: (1, 2), 2: (2, 3), 3: (3, 4), 4: (4, 4)}
        for strategy, (low, high) in ranges.items():
            for work in works:
                score = int(scoring.score_for(work, strategy))
                self.assertGreaterEqual(score, low, f"策略{strategy} {work}")
                self.assertLessEqual(score, high, f"策略{strategy} {work}")

    def test_bad_strategy_falls_back_to_default(self):
        work = {"name": "夜航西飞", "authorName": "某乐队"}
        self.assertEqual(scoring.score_for(work, 99), "4")
        self.assertEqual(scoring.score_for(work, "abc"), "3")
        self.assertEqual(scoring.score_for(work, None), "3")

    def test_missing_fields_do_not_raise(self):
        self.assertIn(scoring.score_for({}, 3), ("3", "4"))
        self.assertIn(scoring.score_for({"name": None}, 3), ("3", "4"))


class TestRedact(unittest.TestCase):
    def test_masks_secrets(self):
        line = ("key sk-abcdef123456 cookie MUSIC_U=deadbeef; csrf=__csrf=abc123 "
                'Authorization: Bearer eyJhbGciOi')
        out = redact(line)
        self.assertNotIn("abcdef123456", out)
        self.assertNotIn("deadbeef", out)
        self.assertNotIn("abc123", out)
        self.assertNotIn("eyJhbGciOi", out)

    def test_truncates_long_lines(self):
        self.assertLessEqual(len(redact("x" * 1000)), 401)

    def test_normal_line_untouched(self):
        self.assertEqual(redact("评分完成：4分"), "评分完成：4分")


class TestParsePoints(unittest.TestCase):
    def test_picks_known_keys(self):
        payload = {"data": {"cloudBean": 12, "vipType": 3, "growthValue": 480}}
        self.assertEqual(
            parse_points(payload),
            {"云贝余额": "12", "VIP 等级": "3", "成长总值": "480"},
        )

    def test_zero_is_real_data_not_missing(self):
        self.assertEqual(parse_points({"data": {"cloudBean": 0}}), {"云贝余额": "0"})

    def test_empty_when_schema_unknown(self):
        self.assertEqual(parse_points({"data": {"foo": 1}}), {})


if __name__ == "__main__":
    unittest.main()
