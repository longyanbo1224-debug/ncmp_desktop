"""本地评分账本的边界：按账号 + 任务隔离，坏文件当空账本。"""
import json
import tempfile
import unittest
from pathlib import Path

from core.rating_ledger import RatingLedger


class RatingLedgerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "rated_works.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_marked_score_is_returned_for_same_task(self):
        ledger = RatingLedger(self.path)
        ledger.mark("user", "task-a", 101, "4")

        self.assertEqual(ledger.score("user", "task-a", 101), "4")
        self.assertIsNone(ledger.score("user", "task-a", 102))

    def test_other_task_or_account_does_not_match(self):
        ledger = RatingLedger(self.path)
        ledger.mark("user", "task-a", 101, "4")

        self.assertIsNone(ledger.score("user", "task-b", 101))
        self.assertIsNone(ledger.score("other", "task-a", 101))

    def test_corrupt_file_is_treated_as_empty(self):
        self.path.write_text("{not json", encoding="utf-8")
        ledger = RatingLedger(self.path)

        self.assertIsNone(ledger.score("user", "task", 1))
        ledger.mark("user", "task", 1, "3")
        self.assertEqual(ledger.score("user", "task", 1), "3")

    def test_mark_overwrites_same_work(self):
        ledger = RatingLedger(self.path)
        ledger.mark("user", "task", 1, "3")
        ledger.mark("user", "task", 1, "4")

        self.assertEqual(ledger.score("user", "task", 1), "4")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(len(data["user"]["task"]), 1)

    def test_invalid_scores_are_ignored(self):
        """空 / "null" / 0 不是分数，不能写进账本去跳过评分。"""
        ledger = RatingLedger(self.path)
        for bad in ("", "null", "NULL", "0", "  "):
            ledger.mark("user", "task", 1, bad)
        self.assertIsNone(ledger.score("user", "task", 1))
        self.assertFalse(self.path.exists())

    def test_legacy_null_score_entry_is_not_matched(self):
        """旧版本可能把服务端的 null 写成 "null"：这种历史条目不能再跳过评分。"""
        self.path.write_text(json.dumps({
            "user": {"task": {
                "1": {"score": "null", "ts": "2026-11-06T09:00:00"},
                "2": {"score": "4", "ts": "2026-11-06T09:00:00"},
            }}
        }), encoding="utf-8")
        ledger = RatingLedger(self.path)

        self.assertIsNone(ledger.score("user", "task", 1))
        self.assertEqual(ledger.score("user", "task", 2), "4")

    def test_float_score_is_normalized(self):
        """服务端把档位返回成 4.0 时，仍要记成 4 并在重跑时命中。"""
        ledger = RatingLedger(self.path)
        ledger.mark("user", "task", 1, "4.0")

        self.assertEqual(ledger.score("user", "task", 1), "4")

    def test_count_returns_entries_for_task(self):
        ledger = RatingLedger(self.path)
        ledger.mark("user", "task", 1, "4")
        ledger.mark("user", "task", 2, "3")
        ledger.mark("user", "other", 3, "4")

        self.assertEqual(ledger.count("user", "task"), 2)
        self.assertEqual(ledger.count("user", "other"), 1)
        self.assertEqual(ledger.count("other", "task"), 0)

    def test_blank_work_id_is_never_marked(self):
        """缺 id 的作品共用一个空键，会让所有歌都被误判成已评过。"""
        ledger = RatingLedger(self.path)
        ledger.mark("user", "task", "", "4")
        ledger.mark("user", "task", "None", "4")

        self.assertIsNone(ledger.score("user", "task", ""))
        self.assertIsNone(ledger.score("user", "task", "None"))


if __name__ == "__main__":
    unittest.main()
