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
    def test_ends_with_period_and_fills_placeholder(self):
        for score in ("1", "2", "3", "4", "5"):
            note = NoteGenerator(_Cfg()).generate(_WORK, score)
            self.assertTrue(note.endswith("。"), note)
            self.assertNotIn("{name}", note)

    def test_formats_vary(self):
        """四种排法要真的用上：既要有两句的，也要有只有一句的。"""
        gen = NoteGenerator(_Cfg())
        works = [{"id": i, "name": f"歌{i}", "authorName": "某"} for i in range(40)]
        notes = [gen.generate(work, "4") for work in works]
        doubles = [n for n in notes if n.count("。") >= 2]
        singles = [n for n in notes if n.count("。") == 1]
        self.assertTrue(doubles, "没有出现两句的批注")
        self.assertTrue(singles, "没有出现一句的批注")

    def test_corpus_is_varied(self):
        """语料扩容后，40 首同档位的歌不应该大面积重复。"""
        gen = NoteGenerator(_Cfg())
        works = [{"id": i, "name": f"歌{i}", "authorName": "某"} for i in range(40)]
        notes = {gen.generate(work, "4") for work in works}
        self.assertGreaterEqual(len(notes), 20)

    def test_no_double_period(self):
        """简短语气的判断句自带句号，拼接时不能再补一个。"""
        works = [{"id": i, "name": f"歌{i}", "authorName": "某"} for i in range(12)]
        for voice in ("restrained", "warm", "brief"):
            gen = NoteGenerator(_Cfg(note_voice=voice))
            for work in works:
                note = gen.generate(work, "4")
                self.assertNotIn("。。", note, f"{voice}: {note}")

    def test_brief_stays_short(self):
        """简短语气就是一句，不带开场也不带收尾。"""
        works = [{"id": i, "name": f"歌{i}", "authorName": "某"} for i in range(12)]
        gen = NoteGenerator(_Cfg(note_voice="brief"))
        for work in works:
            note = gen.generate(work, "4")
            self.assertEqual(note.count("。"), 1, note)
            self.assertLessEqual(len(note), 16, note)

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


class TestLengthTiers(unittest.TestCase):
    """三档长度必须真的不同：简短 < 标准 < 详细，且各自不超过上限。"""

    _WORKS = [{"id": i, "name": f"歌{i}", "authorName": "某"} for i in range(8)]

    def _note(self, work, length):
        return NoteGenerator(_Cfg(note_length=length)).generate(work, "4")

    def test_monotonic(self):
        for work in self._WORKS:
            brief = self._note(work, "brief")
            standard = self._note(work, "standard")
            detailed = self._note(work, "detailed")
            self.assertLess(len(brief), len(standard), (work, brief, standard))
            self.assertLess(len(standard), len(detailed), (work, standard, detailed))

    def test_caps(self):
        for work in self._WORKS:
            self.assertLessEqual(len(self._note(work, "brief")), 40)
            self.assertLessEqual(len(self._note(work, "standard")), 80)
            self.assertLessEqual(len(self._note(work, "detailed")), 120)

    def test_legacy_max_chars_still_works(self):
        self.assertEqual(NoteGenerator(_Cfg(note_max_chars=30)).length, "brief")
        self.assertEqual(NoteGenerator(_Cfg(note_max_chars=80)).length, "standard")
        self.assertEqual(NoteGenerator(_Cfg(note_max_chars=120)).length, "detailed")


if __name__ == "__main__":
    unittest.main()
