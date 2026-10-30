"""启动冒烟：所有页面能不能构造出来，账本能不能读能写。

比逐个函数测更值：页面构造会一次性暴露导入错误、QSS objectName 写错、
布局参数不合法这类"一打开就崩"的问题。
"""
import json
import os
import tempfile
import unittest
from datetime import date, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
    _HAS_QT = True
except Exception:  # pragma: no cover
    _HAS_QT = False


@unittest.skipUnless(_HAS_QT, "PySide6 不可用")
class TestPagesConstruct(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from app.ui import theme
        theme.apply_theme(cls.app, "light")

    def test_all_pages_construct(self):
        from app.ui.pages.about_page import AboutPage
        from app.ui.pages.dashboard_page import DashboardPage
        from app.ui.pages.ledger_page import LedgerPage
        from app.ui.pages.login_page import LoginPage
        from app.ui.pages.settings_page import SettingsPage
        from app.ui.pages.task_page import TaskPage

        for factory in (DashboardPage, LoginPage, TaskPage, LedgerPage,
                        SettingsPage, AboutPage):
            page = factory()
            self.assertIsNotNone(page)

    def test_settings_has_note_controls(self):
        from app.ui.pages.settings_page import SettingsPage
        page = SettingsPage()
        for key in ("note_enabled", "note_voice", "note_max_chars"):
            self.assertIn(key, page._controls, f"设置页缺 {key} 控件")

    def test_settings_roundtrip_note_voice(self):
        """语气下拉走 userData：设进去再取出来必须还是同一个值。"""
        from app.ui.pages.settings_page import SettingsPage
        page = SettingsPage()
        page._set_control("note_voice", "brief")
        self.assertEqual(page._controls["note_voice"].currentData(), "brief")
        self.assertEqual(page._collect_form()["note_voice"], "brief")

    def test_toast_paints_opaque_background(self):
        """通知气泡必须真的画出面板（曾因半透明窗口导致"透明、像没加载完"）。"""
        from app.ui.widgets.toast import Toast

        toast = Toast("任务完成", "今天评完了 20 首")
        pixmap = toast.grab()
        self.assertFalse(pixmap.isNull())
        self.assertGreater(pixmap.width(), 0)
        # 中心像素应是面板色（不透出背景）
        image = pixmap.toImage()
        center = image.pixelColor(image.width() // 2, image.height() // 2)
        self.assertEqual(center.alpha(), 255, f"中心像素透明: {center.name()}")


class TestTrackLog(unittest.TestCase):
    def _log(self):
        from app.track_log import TrackLog
        log = TrackLog()
        handle, path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        os.unlink(path)
        log._path = type(log._path)(path)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        return log

    def test_record_and_read_back(self):
        log = self._log()
        day = date.today().isoformat()
        log.record("夜航西飞", artist="某乐队", score="4", note="第一句。")
        rows = log.day(day)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["note"], "第一句。")

    def test_same_song_same_day_overwrites(self):
        log = self._log()
        log.record("夜航西飞", score="4")
        log.record("夜航西飞", score="5", note="改过的批注。")
        rows = log.day()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["score"], "5")
        self.assertEqual(rows[0]["note"], "改过的批注。")

    def test_later_record_without_note_keeps_old_note(self):
        """重跑时没写批注，不该把上一次写的抹掉。"""
        log = self._log()
        log.record("夜航西飞", score="4", note="先前的批注。")
        log.record("夜航西飞", score="4")
        self.assertEqual(log.day()[0]["note"], "先前的批注。")

    def test_stats_and_export(self):
        log = self._log()
        log.record("甲", score="4", note="一。")
        log.record("乙", score="4")
        log.record("丙", score="3", note="二。")
        stats = log.stats()
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["notes"], 2)
        self.assertEqual(stats["tiers"], {"4": 2, "3": 1})
        markdown = log.export_markdown()
        self.assertIn("甲", markdown)
        self.assertIn("> 一。", markdown)

    def test_empty_export_is_graceful(self):
        log = self._log()
        self.assertIn("今天还没有评过曲子", log.export_markdown())

    def test_recent_is_newest_first(self):
        log = self._log()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        log.record("旧歌", score="3", day=yesterday)
        log.record("新歌", score="4")
        recent = log.recent(10)
        self.assertEqual(recent[0]["song"], "新歌")
        self.assertEqual(recent[0]["day"], date.today().isoformat())


class TestScoringPreview(unittest.TestCase):
    """D1 的判定：四种策略必须给出可区分的结果。"""

    def test_compare_covers_all_strategies(self):
        from core import scoring
        works = [{"name": "Song A", "authorName": "X"},
                 {"name": "夜航西飞", "authorName": "某乐队"}]
        result = scoring.compare(works)
        self.assertEqual(set(result), {1, 2, 3, 4})
        # 含拉丁字母的那首在 3-4 档拿 4 分，纯中文那首拿 3 分
        self.assertEqual(result[3], {"4": 1, "3": 1})
        self.assertEqual(result[4], {"4": 2})

    def test_describe_is_human_readable(self):
        from core import scoring
        text = scoring.describe({"4": 2, "3": 3})
        self.assertIn("2 首 4 分", text)
        self.assertIn("3 首 3 分", text)


if __name__ == "__main__":
    unittest.main()
