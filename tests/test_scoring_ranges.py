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

    def test_real_payload_fields(self):
        """真实返回（2026-10-29）：integral / currentWeekIntegral。"""
        payload = {"data": {
            "period": 73, "week": 3, "title": "CHIEF", "days": 1023,
            "integral": 454, "currentWeekIntegral": 92,
        }}
        self.assertEqual(
            parse_points(payload),
            {"本期积分": "454", "本周积分": "92"},
        )

    def test_zero_is_real_data_not_missing(self):
        self.assertEqual(parse_points({"data": {"cloudBean": 0}}), {"云贝余额": "0"})

    def test_empty_when_schema_unknown(self):
        self.assertEqual(parse_points({"data": {"foo": 1}}), {})


class TestPartnerTitles(unittest.TestCase):
    """称号换算：320 高级 / 400 资深 / 480 首席（用户提供的一手规则）。"""

    def test_thresholds(self):
        from core.partner_points import title_for
        self.assertEqual(title_for(300)["label"], "未达保级线")
        self.assertEqual(title_for(320)["label"], "高级音乐合伙人")
        self.assertEqual(title_for(399)["label"], "高级音乐合伙人")
        self.assertEqual(title_for(400)["label"], "资深音乐合伙人")
        self.assertEqual(title_for(454)["label"], "资深音乐合伙人")
        self.assertEqual(title_for(480)["label"], "首席音乐合伙人")
        self.assertEqual(title_for(500)["label"], "首席音乐合伙人")

    def test_next_and_gap(self):
        from core.partner_points import title_for
        info = title_for(454)
        self.assertEqual(info["next_label"], "首席音乐合伙人")
        self.assertEqual(info["gap"], 26)
        # 已到最高档：没有下一档
        self.assertIsNone(title_for(480)["next_label"])
        self.assertIsNone(title_for(480)["gap"])

    def test_unknown_score(self):
        from core.partner_points import title_for
        self.assertEqual(title_for(None)["label"], "")
        self.assertEqual(len(title_for(None)["table"]), 3)

    def test_score_of_prefers_period_points(self):
        from core.partner_points import score_of
        self.assertEqual(score_of({"本期积分": "454", "云贝余额": "999"}), 454)
        self.assertEqual(score_of({"本周积分": "12"}), 12)
        self.assertIsNone(score_of({"云贝余额": "999"}))
        self.assertIsNone(score_of({}))


if __name__ == "__main__":
    unittest.main()
