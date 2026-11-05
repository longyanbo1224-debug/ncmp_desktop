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
        # 页头分母是曲目表行数（不是阶段目标 5），所以两首评完就是 2/2
        self.assertEqual(page._track_list.done_count(), 2)
        self.assertIn("2/2", page._today_label.text())

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

    def test_server_pending_does_not_downgrade_local_submitted(self):
        """服务端标记滞后时，本机已提交的曲目不能被降回「待评」。"""
        from app.track_log import TrackLog
        import app.ui.pages.task_page as task_page_module

        with tempfile.TemporaryDirectory() as tmp:
            log = TrackLog(path=Path(tmp) / "track_log.json")
            log.record("夜航西飞", artist="某乐队", score="4")
            original = task_page_module.TrackLog
            task_page_module.TrackLog = lambda: log
            try:
                page = self._page()
                page._on_works([{
                    "work": {"name": "夜航西飞", "authorName": "某乐队"},
                    "completed": False,
                }])
            finally:
                task_page_module.TrackLog = original

        self.assertEqual(page._track_list.done_count(), 1)

    def test_local_submitted_song_survives_shrunk_server_list(self):
        """已经评上的额外曲目，即使服务端待评清单缩水也要保留。"""
        from app.track_log import TrackLog
        import app.ui.pages.task_page as task_page_module

        with tempfile.TemporaryDirectory() as tmp:
            log = TrackLog(path=Path(tmp) / "track_log.json")
            log.record("额外已评歌", artist="某乐队", score="4")
            original = task_page_module.TrackLog
            task_page_module.TrackLog = lambda: log
            try:
                page = self._page()
                page._begin_run("执行中…", "running")  # 模拟新一次执行清空列表
                page._on_works([{
                    "work": {"name": "基础一", "authorName": "某乐队"},
                    "completed": False,
                }])
            finally:
                task_page_module.TrackLog = original

        self.assertTrue(page._track_list.contains("额外已评歌"))
        self.assertEqual(page._track_list.done_count(), 1)

    def test_local_skipped_song_not_in_server_list_is_dropped(self):
        """旧的跳过行不属于当前任务清单时不再补回来，否则会越堆越多。"""
        from app.track_log import TrackLog
        import app.ui.pages.task_page as task_page_module

        with tempfile.TemporaryDirectory() as tmp:
            log = TrackLog(path=Path(tmp) / "track_log.json")
            log.record("旧跳过歌", artist="某乐队", state="skipped")
            original = task_page_module.TrackLog
            task_page_module.TrackLog = lambda: log
            try:
                page = self._page()
                page._begin_run("执行中…", "running")
                page._on_works([{
                    "work": {"name": "基础一", "authorName": "某乐队"},
                    "completed": False,
                }])
            finally:
                task_page_module.TrackLog = original

        self.assertFalse(page._track_list.contains("旧跳过歌"))
        self.assertEqual(page._track_list.count(), 1)

    def test_server_pending_without_local_record_stays_pending(self):
        """服务端说待评、本机也没记录时，不能误标成已提交（否则恒 20/20）。"""
        from app.track_log import TrackLog
        import app.ui.pages.task_page as task_page_module

        with tempfile.TemporaryDirectory() as tmp:
            log = TrackLog(path=Path(tmp) / "track_log.json")
            original = task_page_module.TrackLog
            task_page_module.TrackLog = lambda: log
            try:
                page = self._page()
                page._begin_run("执行中…", "running")
                page._on_works([{
                    "work": {"name": "今天新歌", "authorName": "某"},
                    "completed": False,
                }])
            finally:
                task_page_module.TrackLog = original

        self.assertEqual(page._track_list.done_count(), 0)
        self.assertEqual(
            [row.song for row in page._track_list.rows_with_state("pending")],
            ["今天新歌"],
        )

    def test_base_and_extra_are_counted_separately(self):
        """完成总结要能分出基础/额外；_group 从清单带进曲目行。"""
        from app.track_log import TrackLog
        import app.ui.pages.task_page as task_page_module

        with tempfile.TemporaryDirectory() as tmp:
            log = TrackLog(path=Path(tmp) / "track_log.json")
            original = task_page_module.TrackLog
            task_page_module.TrackLog = lambda: log
            try:
                page = self._page()
                page._begin_run("执行中…", "running")
                page._on_works([
                    {"work": {"name": "基础一", "authorName": "某"},
                     "completed": True, "score": 4, "_group": "base"},
                    {"work": {"name": "额外一", "authorName": "某"},
                     "completed": True, "score": 4, "_group": "extra"},
                ])
            finally:
                task_page_module.TrackLog = original

        self.assertEqual(page._track_list.done_count(), 2)
        self.assertEqual(page._track_list.count_by_group("base"), 1)
        self.assertEqual(page._track_list.count_by_group("extra"), 1)

    def test_score_means_rated_even_when_completed_flag_lags(self):
        """服务端 completed=false 但已经有分数：按已评处理。"""
        from app.track_log import TrackLog
        import app.ui.pages.task_page as task_page_module

        with tempfile.TemporaryDirectory() as tmp:
            log = TrackLog(path=Path(tmp) / "track_log.json")
            original = task_page_module.TrackLog
            task_page_module.TrackLog = lambda: log
            try:
                page = self._page()
                page._begin_run("执行中…", "running")
                page._on_works([{
                    "work": {"name": "已评歌", "authorName": "某"},
                    "completed": False,
                    "score": 4,
                }])
            finally:
                task_page_module.TrackLog = original

        self.assertEqual(page._track_list.done_count(), 1)
        self.assertEqual(page._track_list.rows_with_state("pending"), [])

    def test_skipped_extra_counts_as_done_on_success(self):
        """额外曲目「已评过所以跳过」算进今日完成数，不再只算基础 5 首。"""
        from app.track_log import TrackLog
        import app.ui.pages.task_page as task_page_module

        with tempfile.TemporaryDirectory() as tmp:
            log = TrackLog(path=Path(tmp) / "track_log.json")
            original = task_page_module.TrackLog
            task_page_module.TrackLog = lambda: log
            try:
                page = self._page()
                page._begin_run("执行中…", "running")
                page._on_works([{
                    "work": {"name": "额外歌", "authorName": "某"},
                    "completed": False,
                    "_group": "extra",
                }])
                page._track_list.settle_pending()
                page._track_list.mark_extra_skipped_done()
            finally:
                task_page_module.TrackLog = original

        self.assertEqual(page._track_list.done_count(), 1)
        self.assertEqual(page._track_list.rows_with_state("skipped"), [])

    def test_extra_rows_are_capped_at_daily_limit(self):
        """基础 5 + 额外最多 15：多出来的旧批次行不展示，优先保留已提交。"""
        from app.track_log import TrackLog
        import app.ui.pages.task_page as task_page_module

        works = [
            {"work": {"name": f"基础{i}", "authorName": "某"},
             "completed": True, "score": 4, "_group": "base"}
            for i in range(5)
        ]
        works += [
            {"work": {"name": f"额外{i}", "authorName": "某"},
             "completed": i < 15, "score": 4 if i < 15 else "",
             "_group": "extra"}
            for i in range(20)
        ]

        with tempfile.TemporaryDirectory() as tmp:
            log = TrackLog(path=Path(tmp) / "track_log.json")
            original = task_page_module.TrackLog
            task_page_module.TrackLog = lambda: log
            try:
                page = self._page()
                page._begin_run("执行中…", "running")
                page._on_works(works)
            finally:
                task_page_module.TrackLog = original

        self.assertEqual(page._track_list.count(), 20)
        self.assertEqual(page._track_list.done_count(), 20)
        self.assertEqual(page._track_list.count_by_group("base"), 5)
        self.assertEqual(page._track_list.count_by_group("extra"), 15)

    def test_new_day_clears_previous_tracks(self):
        """跨天后第一次同步要把昨天的行清掉，不能两天堆在一起。"""
        from datetime import date as real_date
        from app.track_log import TrackLog
        import app.track_log as track_log_module
        import app.ui.pages.task_page as task_page_module

        class _Tomorrow:
            @classmethod
            def today(cls):
                return real_date(2099, 1, 1)

        with tempfile.TemporaryDirectory() as tmp:
            log = TrackLog(path=Path(tmp) / "track_log.json")
            original_log = task_page_module.TrackLog
            original_date = task_page_module.date
            original_log_date = track_log_module.date
            task_page_module.TrackLog = lambda: log
            try:
                page = self._page()
                page._on_works([{
                    "work": {"name": "昨天的歌", "authorName": "某乐队"},
                    "completed": True,
                    "score": 4,
                }])
                self.assertEqual(page._track_list.count(), 1)

                task_page_module.date = _Tomorrow
                track_log_module.date = _Tomorrow
                page._on_works([{
                    "work": {"name": "今天的歌", "authorName": "某乐队"},
                    "completed": False,
                }])
            finally:
                task_page_module.TrackLog = original_log
                task_page_module.date = original_date
                track_log_module.date = original_log_date

        self.assertFalse(page._track_list.contains("昨天的歌"))
        self.assertTrue(page._track_list.contains("今天的歌"))


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
