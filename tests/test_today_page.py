"""今日页的冒烟测试：曲目表能不能被真实数据喂起来。

不测像素，只测"数据进得去、状态出得来"——Qt 控件在 offscreen 平台下可以
正常构造，所以这里直接建真控件，避免手写 mock。
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
class TestTodayPage(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from app.ui import theme
        theme.apply_theme(cls.app, "light")

    def _page(self):
        from app.ui.pages.task_page import TaskPage
        return TaskPage()

    def test_track_rows_follow_progress(self):
        page = self._page()
        page._begin_run("执行中…", "running")
        page._on_progress(0, 5, "", "")
        page._on_progress(1, 5, "夜航西飞", "4")
        page._on_progress(2, 5, "另一首", "3")
        self.assertEqual(page._track_list.count(), 2)
        self.assertIn("2/5", page._today_label.text())

    def test_note_lands_on_track_row(self):
        page = self._page()
        page._begin_run("执行中…", "running")
        page._on_progress(1, 5, "夜航西飞", "4")
        page._on_note("夜航西飞", "4", "通勤路上点开的，结构完整。先放进歌单。")
        self.assertEqual(page._track_list.note_count(), 1)
        self.assertIn("批注", page._rail_notes.text())

    def test_note_for_unknown_song_creates_row(self):
        """批注回调可能先于进度回调到达，不能丢。"""
        page = self._page()
        page._begin_run("执行中…", "running")
        page._on_note("未登记的歌", "5", "第一句。")
        self.assertEqual(page._track_list.count(), 1)
        self.assertEqual(page._track_list.note_count(), 1)

    def test_detail_collapsed_by_default(self):
        """默认收起：用 isHidden 判断（isVisible 还取决于父窗口是否显示）。"""
        page = self._page()
        self.assertTrue(page._detail.isHidden())

    def test_toggle_detail(self):
        page = self._page()
        page.toggle_detail()
        self.assertFalse(page._detail.isHidden())
        page.toggle_detail()
        self.assertTrue(page._detail.isHidden())

    def test_loads_today_from_track_log(self):
        """今天已经评过、再打开程序时，曲目表必须是今天评过的那些。

        这是用户报过的问题：账本里有数据，今日页却显示"今天还没有排到曲子"。
        """
        from app.track_log import TrackLog
        import app.ui.pages.task_page as task_page_module

        with tempfile.TemporaryDirectory() as tmp:
            log = TrackLog(path=Path(tmp) / "track_log.json")
            log.record("夜航西飞", artist="某乐队", score="4", note="第一句。")
            original = task_page_module.TrackLog
            task_page_module.TrackLog = lambda: log
            try:
                page = self._page()
            finally:
                task_page_module.TrackLog = original
        self.assertEqual(page._track_list.count(), 1)
        self.assertEqual(page._track_list.note_count(), 1)


@unittest.skipUnless(_HAS_QT, "PySide6 不可用")
class TestThemeModes(unittest.TestCase):
    """明暗两套主题都要能生成样式表，且色值真的换掉了。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        from app.ui import theme
        theme.set_mode("light")

    def test_dark_and_light_differ(self):
        from app.ui import theme
        theme.set_mode("light")
        light_qss = theme.build_qss()
        light_ground = theme.GROUND
        theme.set_mode("dark")
        dark_qss = theme.build_qss()
        self.assertNotEqual(light_ground, theme.GROUND)
        self.assertNotEqual(light_qss, dark_qss)
        self.assertIn(theme.GROUND, dark_qss)

    def test_state_colors_follow_mode(self):
        from app.ui import theme
        theme.set_mode("light")
        light_success = theme.state_text("success")
        theme.set_mode("dark")
        self.assertNotEqual(light_success, theme.state_text("success"))


if __name__ == "__main__":
    unittest.main()
