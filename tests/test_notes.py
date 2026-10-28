"""批注生成器的测试。

覆盖四件事：
1. 确定性——同歌同分永远同一句（预览与实际提交必须一致）；
2. 长度上限——超长时先丢收尾再截断，不会把句子切一半；
3. 开关——note_enabled 关闭时返回空串（回到旧版"只评分不写批注"）；
4. 永不抛异常——脏数据、LLM 未配置都退化成可用结果。
"""
import unittest

from core.notes import NoteGenerator, tier_for_score
from core.notes.llm import generate_with_llm


class _Cfg:
    """最小配置替身：只需 get(key, default)。"""

    def __init__(self, **kwargs):
        self._data = kwargs

    def get(self, key, default=None):
        return self._data.get(key, default)


_WORK = {"id": 19723756, "name": "夜航西飞", "authorName": "某乐队"}


class TestTierMapping(unittest.TestCase):
    def test_tiers(self):
        self.assertEqual(tier_for_score("5"), "high")
        self.assertEqual(tier_for_score("4"), "high")
        self.assertEqual(tier_for_score("3"), "mid")
        self.assertEqual(tier_for_score("2"), "low")
        self.assertEqual(tier_for_score("1"), "low")

    def test_bad_score_falls_back_to_mid(self):
        self.assertEqual(tier_for_score(""), "mid")
        self.assertEqual(tier_for_score(None), "mid")
        self.assertEqual(tier_for_score("abc"), "mid")


class TestDeterminism(unittest.TestCase):
    def test_same_work_same_note(self):
        cfg = _Cfg()
        first = NoteGenerator(cfg).generate(_WORK, "4")
        second = NoteGenerator(cfg).generate(_WORK, "4")
        self.assertTrue(first)
        self.assertEqual(first, second)

    def test_different_works_differ(self):
        gen = NoteGenerator(_Cfg())
        notes = {
            gen.generate({"id": i, "name": f"歌{i}", "authorName": "某"}, "4")
            for i in range(8)
        }
        # 8 首同档位的歌不应全部撞成同一句
        self.assertGreater(len(notes), 1)


class TestShape(unittest.TestCase):
    def test_three_part_shape(self):
        note = NoteGenerator(_Cfg()).generate(_WORK, "4")
        self.assertTrue(note.endswith("。"), note)
        # 开场以逗号收，判断与收尾之间有一个句号 → 至少两个句读
        self.assertIn("，", note)
        self.assertGreaterEqual(note.count("。"), 1)

    def test_max_chars_respected(self):
        note = NoteGenerator(_Cfg(note_max_chars=20)).generate(_WORK, "4")
        self.assertLessEqual(len(note), 20, note)
        self.assertTrue(note.endswith("。"))

    def test_no_emoji_or_tags(self):
        for score in ("1", "2", "3", "4", "5"):
            note = NoteGenerator(_Cfg()).generate(_WORK, score)
            self.assertNotIn("#", note)
            self.assertNotIn("！", note)
            self.assertNotIn("!", note)


class TestSwitches(unittest.TestCase):
    def test_disabled_returns_empty(self):
        self.assertEqual(NoteGenerator(_Cfg(note_enabled=False)).generate(_WORK, "4"), "")

    def test_enabled_by_default(self):
        self.assertTrue(NoteGenerator(_Cfg()).generate(_WORK, "4"))

    def test_llm_without_config_falls_back_to_template(self):
        cfg = _Cfg(note_source="llm")  # 没配 endpoint/model/key
        self.assertIsNone(generate_with_llm(_WORK, "4", cfg))
        self.assertTrue(NoteGenerator(cfg).generate(_WORK, "4"))


class TestRobustness(unittest.TestCase):
    def test_dirty_work_does_not_raise(self):
        gen = NoteGenerator(_Cfg())
        for work in ({}, {"name": None}, {"id": "x", "name": "歌", "authorName": ""}):
            self.assertIsInstance(gen.generate(work, "3"), str)

    def test_no_config_at_all(self):
        self.assertIsInstance(NoteGenerator(None).generate(_WORK, "4"), str)


if __name__ == "__main__":
    unittest.main()
