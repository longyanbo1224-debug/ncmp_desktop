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


if __name__ == "__main__":
    unittest.main()
