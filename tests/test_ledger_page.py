"""记录页口味曲线的数据口径。

用户报过「今天评了 20 首，曲线只有 10 首（4 分 3 首 + 3 分 7 首）」：
另外 10 首是服务端只给了 `completed`、没给 `score` 的曲目（例如另一台设备
评过），既不能归进档位，也不能让它们悄悄消失。
"""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
    _HAS_QT = True
except Exception:  # pragma: no cover - 无 Qt 环境时跳过
    _HAS_QT = False


@unittest.skipUnless(_HAS_QT, "PySide6 不可用")
class TestLedgerCurve(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from app.ui import theme
        theme.apply_theme(cls.app, "light")

    def _page_with(self, entries):
        from app.track_log import TrackLog
        import app.ui.pages.ledger_page as ledger_module

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        log = TrackLog(path=Path(tmp.name) / "track_log.json")
        for song, score in entries:
            log.record(song, score=score)
        original = ledger_module.TrackLog
        ledger_module.TrackLog = lambda: log
        try:
            return ledger_module.LedgerPage()
        finally:
            ledger_module.TrackLog = original

    def test_unscored_submissions_are_explained(self):
        """20 首提交、其中 10 首没有分数：曲线画有分数的 10 首，并写明另外 10 首。"""
        entries = [(f"有分{i}", "4" if i < 3 else "3") for i in range(10)]
        entries += [(f"无分{i}", "") for i in range(10)]
        page = self._page_with(entries)

        self.assertFalse(page._curve_box.isHidden())
        self.assertTrue(page._curve_empty.isHidden())
        self.assertEqual(page._curve_lay.count(), 5)
        self.assertIn("10 首", page._curve_hint.text())
        self.assertIn("没有分数", page._curve_hint.text())

    def test_all_unscored_does_not_claim_no_records(self):
        """有提交记录但一个分数都没有时，不能显示「还没有评分记录」。"""
        page = self._page_with([("无分一", ""), ("无分二", "")])

        self.assertTrue(page._curve_box.isHidden())
        self.assertFalse(page._curve_empty.isHidden())
        self.assertIn("2 首", page._curve_empty.text())
        self.assertNotIn("还没有评分记录", page._curve_empty.text())


if __name__ == "__main__":
    unittest.main()
