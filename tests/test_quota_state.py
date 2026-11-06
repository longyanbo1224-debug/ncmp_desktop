"""本地「今日额外额度已用完」标记的边界。"""
import tempfile
import unittest
from pathlib import Path

from core.quota_state import QuotaState


class QuotaStateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "quota_exhausted.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_mark_and_match_same_day_task(self):
        state = QuotaState(self.path)
        state.mark("user", "task-a", day="2026-11-07")

        self.assertTrue(state.exhausted("user", "task-a", day="2026-11-07"))
        self.assertFalse(state.exhausted("user", "task-b", day="2026-11-07"))
        self.assertFalse(state.exhausted("other", "task-a", day="2026-11-07"))
        # 换天自动失效（同一天 taskId 也不同，双保险）
        self.assertFalse(state.exhausted("user", "task-a", day="2026-11-08"))

    def test_task_id_types_are_normalized(self):
        state = QuotaState(self.path)
        state.mark("user", 123, day="2026-11-07")
        self.assertTrue(state.exhausted("user", "123", day="2026-11-07"))

    def test_blank_task_is_never_marked(self):
        state = QuotaState(self.path)
        for bad in ("", "None", "null", None):
            state.mark("user", bad, day="2026-11-07")
        self.assertFalse(state.exhausted("user", "", day="2026-11-07"))
        self.assertFalse(self.path.exists())

    def test_corrupt_file_is_treated_as_empty(self):
        self.path.write_text("{not json", encoding="utf-8")
        state = QuotaState(self.path)
        self.assertFalse(state.exhausted("user", "task-a", day="2026-11-07"))

        state.mark("user", "task-a", day="2026-11-07")
        self.assertTrue(state.exhausted("user", "task-a", day="2026-11-07"))

    def test_old_day_entries_are_pruned(self):
        state = QuotaState(self.path)
        state.mark("user", "task-old", day="2026-11-06")
        state.mark("user", "task-new", day="2026-11-07")

        self.assertFalse(state.exhausted("user", "task-old", day="2026-11-06"))
        self.assertTrue(state.exhausted("user", "task-new", day="2026-11-07"))


if __name__ == "__main__":
    unittest.main()
