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


class _NoQuotaState:
    """测试替身：默认表示「今日额外额度还没用完」。"""

    exhausted = False

    def __init__(self, *args, **kwargs):
        pass

    def exhausted_today(self, day=None):
        return self.exhausted


class _ExhaustedQuotaState(_NoQuotaState):
    """测试替身：今日额外额度已用完。"""

    exhausted = True


@unittest.skipUnless(_HAS_QT, "PySide6 不可用")
class TestTodayPage(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from app.ui import theme
        theme.apply_theme(cls.app, "light")

    def setUp(self):
        # 不读用户真实的「今日额外额度已用完」缓存，默认按未用完处理
        import app.ui.pages.task_page as task_page_module
        self._original_quota_state = task_page_module.QuotaState
        task_page_module.QuotaState = _NoQuotaState

    def tearDown(self):
        import app.ui.pages.task_page as task_page_module
        task_page_module.QuotaState = self._original_quota_state

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

    def test_skipped_extra_stays_skipped(self):
        """未轮到的额外曲目保持「跳过」，不能自动算成「已提交」。

        服务端返回「今日没有更多」只说明今天的额外额度用完了，不代表这首
        刚刚被评过。以前这里会统一改成「已提交」，界面会谎报 20/20。
        """
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
            finally:
                task_page_module.TrackLog = original

        self.assertEqual(page._track_list.done_count(), 0)
        self.assertEqual(len(page._track_list.rows_with_state("skipped")), 1)

    def test_blank_local_submitted_marks_done_from_history(self):
        """本机历史为 submitted 时（即使没有分数），重复执行也按「已完成」展示。"""
        from app.track_log import TrackLog
        import app.ui.pages.task_page as task_page_module

        with tempfile.TemporaryDirectory() as tmp:
            log = TrackLog(path=Path(tmp) / "track_log.json")
            log.record("无分歌", state="submitted")
            original = task_page_module.TrackLog
            task_page_module.TrackLog = lambda: log
            try:
                page = self._page()
                page._begin_run("执行中…", "running")
                page._on_works([{
                    "work": {"name": "无分歌", "authorName": "某"},
                    "completed": False,
                    "_group": "extra",
                }])
            finally:
                task_page_module.TrackLog = original

        self.assertEqual(page._track_list.done_count(), 1)

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

    def test_completed_extras_are_listed_before_pending(self):
        """同一天多次执行：早上评过的额外曲目由本机账本补回，必须排在待评前面。

        用户反馈的场景：今天已评 10 首（5 基础 + 5 额外），再点执行时服务端
        放出一批新的 15 首待评。以前补回的 5 首「已提交」追加在末尾（16-20），
        把本批次 5 首待评挤出了 20 行上限，页头「11/20、还剩 9 首」与列表对不上。
        """
        from app.track_log import STATE_SUBMITTED, TrackLog
        import app.ui.pages.task_page as task_page_module

        base = [
            {"work": {"name": f"基础{i}", "authorName": "某"},
             "completed": True, "score": 4, "_group": "base"}
            for i in range(5)
        ]
        extras = [
            {"work": {"name": f"额外{i}", "authorName": "某"},
             "completed": False, "score": 0, "_group": "extra"}
            for i in range(15)
        ]

        with tempfile.TemporaryDirectory() as tmp:
            log = TrackLog(path=Path(tmp) / "track_log.json")
            for i in range(5):
                log.record(f"早评{i}", artist="某", score="3",
                           state=STATE_SUBMITTED, group="extra")
            original = task_page_module.TrackLog
            task_page_module.TrackLog = lambda: log
            try:
                page = self._page()
                page._begin_run("执行中…", "running")
                page._on_works(base + extras)
            finally:
                task_page_module.TrackLog = original

        rows = list(page._track_list._rows.values())
        self.assertEqual(page._track_list.count(), 20)
        self.assertEqual(page._track_list.count_by_group("base"), 5)
        self.assertEqual(page._track_list.count_by_group("extra", state=None), 15)
        # 已提交的 5 首排在最前（紧跟基础行），后面才是待评
        self.assertEqual([row.state for row in rows[5:10]], ["done"] * 5)
        self.assertTrue(all(row.state != "done" for row in rows[10:]))
        # 数字与行对得上：10 已提交 / 20，剩 10 首待评
        self.assertEqual(page._track_list.done_count(), 10)

        # 再评一首：已提交 11、待评 9，仍是 20 行——页头与剩余任务一致
        page._on_progress(1, 10, "额外0", "4")
        rows = list(page._track_list._rows.values())
        self.assertEqual(page._track_list.count(), 20)
        self.assertEqual(page._track_list.done_count(), 11)
        self.assertEqual(
            sum(1 for row in rows if row.state == "pending"), 9)

    def test_extra_batch_after_base_reaches_twenty(self):
        """基础评完后服务端放出第二批次：曲目表从 15 行补到 20 行。

        用户反馈的场景：新的一天点执行先只有 15 首，基础 5 首评完后
        才放出剩下的 5 首额外曲目。第二次 on_works 必须合并而不是裁掉基础行。
        """
        from app.track_log import TrackLog
        import app.ui.pages.task_page as task_page_module

        base = [
            {"work": {"name": f"基础{i}", "authorName": "某"},
             "completed": i < 5, "score": 4 if i < 5 else "",
             "_group": "base"}
            for i in range(5)
        ]
        first_extra = [
            {"work": {"name": f"额外{i}", "authorName": "某"},
             "completed": False, "score": 0, "_group": "extra"}
            for i in range(10)
        ]
        second_extra = [
            {"work": {"name": f"额外{i}", "authorName": "某"},
             "completed": False, "score": 0, "_group": "extra"}
            for i in range(15)
        ]

        with tempfile.TemporaryDirectory() as tmp:
            log = TrackLog(path=Path(tmp) / "track_log.json")
            original = task_page_module.TrackLog
            task_page_module.TrackLog = lambda: log
            try:
                page = self._page()
                page._begin_run("执行中…", "running")
                page._on_works(base + first_extra)
                self.assertEqual(page._track_list.count(), 15)

                page._on_works(second_extra)
            finally:
                task_page_module.TrackLog = original

        self.assertEqual(page._track_list.count(), 20)
        self.assertEqual(page._track_list.count_by_group("base"), 5)
        self.assertEqual(page._track_list.count_by_group("extra", state=None), 15)

    def test_quota_exhausted_marks_extra_done_on_refresh(self):
        """本地已缓存「今日额外额度用完」时，刷新就把未完成的额外行显示为已完成。"""
        import app.ui.pages.task_page as task_page_module
        from app.track_log import TrackLog

        with tempfile.TemporaryDirectory() as tmp:
            log = TrackLog(path=Path(tmp) / "track_log.json")
            original_log = task_page_module.TrackLog
            task_page_module.TrackLog = lambda: log
            task_page_module.QuotaState = _ExhaustedQuotaState
            try:
                page = self._page()
                page._begin_run("执行中…", "running")
                page._on_works([{
                    "work": {"name": "额外歌", "authorName": "某"},
                    "completed": False,
                    "_group": "extra",
                }])
            finally:
                task_page_module.TrackLog = original_log
                task_page_module.QuotaState = _NoQuotaState

        self.assertEqual(page._track_list.done_count(), 1)

    def test_same_name_different_artist_are_separate_rows(self):
        """同名不同作品（不同歌手）要各占一行，不能被歌名去重裁成 19 首。"""
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
                    {"work": {"name": "同名歌", "authorName": "甲"},
                     "completed": False, "_group": "extra"},
                    {"work": {"name": "同名歌", "authorName": "乙"},
                     "completed": False, "_group": "extra"},
                ])
                self.assertEqual(page._track_list.count(), 2)

                page._on_progress(1, 2, "同名歌", "4")
                page._on_progress(2, 2, "同名歌", "3")
            finally:
                task_page_module.TrackLog = original

        self.assertEqual(page._track_list.done_count(), 2)

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

    def test_rated_extra_beyond_cap_does_not_grow_total(self):
        """被每日上限裁掉的额外曲目评完后，总行数不能越评越多。

        用户报过「15 首 → 评完一首变 1/16」：评分回调新建行时没带分组，
        这一行绕过了额外上限，于是每评一首就多一行。
        """
        from app.track_log import TrackLog
        import app.ui.pages.task_page as task_page_module

        works = [
            {"work": {"name": f"基础{i}", "authorName": "某"},
             "completed": False, "_group": "base"}
            for i in range(5)
        ]
        works += [
            {"work": {"name": f"额外{i}", "authorName": "某"},
             "completed": False, "_group": "extra"}
            for i in range(20)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            log = TrackLog(path=Path(tmp) / "track_log.json")
            original = task_page_module.TrackLog
            task_page_module.TrackLog = lambda: log
            try:
                page = self._page()
                page._begin_run("执行中…", "running")
                page._on_step("额外评分任务", "running", 0.0)
                page._on_works(works)
                self.assertEqual(page._track_list.count(), 20)
                # 额外18 在摆表时已被裁掉；评分回调又把它带回来
                page._on_progress(1, 15, "额外18", "4")
            finally:
                task_page_module.TrackLog = original

        # 新增的已提交行占掉一个额外名额，另一首待评行被裁掉：总数仍是 20
        self.assertEqual(page._track_list.count(), 20)
        self.assertEqual(page._track_list.done_count(), 1)
        self.assertEqual(page._track_list.count_by_group("extra", state=None), 15)

    def test_duplicate_base_rows_are_not_counted_as_extra(self):
        """额外清单里混入基础任务时，曲目表仍是 20 行（5 基础 + 15 额外）。"""
        from app.track_log import TrackLog
        import app.ui.pages.task_page as task_page_module

        base = [
            {"work": {"name": f"基础{i}", "authorName": "某"},
             "completed": False, "_group": "base"}
            for i in range(5)
        ]
        extras = [
            {"work": {"name": f"额外{i}", "authorName": "某"},
             "completed": False, "_group": "extra"}
            for i in range(15)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            log = TrackLog(path=Path(tmp) / "track_log.json")
            original = task_page_module.TrackLog
            task_page_module.TrackLog = lambda: log
            try:
                page = self._page()
                page._begin_run("执行中…", "running")
                # 额外清单把基础 5 首也列了进来
                page._on_works(base + extras + base)
            finally:
                task_page_module.TrackLog = original

        self.assertEqual(page._track_list.count(), 20)
        self.assertEqual(page._track_list.count_by_group("base", state=None), 5)
        self.assertEqual(page._track_list.count_by_group("extra", state=None), 15)

    def test_stale_refresh_does_not_wipe_running_list(self):
        """点执行前发起的同步晚到时，不能拿旧快照重建正在跑的曲目表。"""
        from app.track_log import TrackLog
        import app.ui.pages.task_page as task_page_module

        works = [
            {"work": {"name": f"歌{i}", "authorName": "某"},
             "completed": False,
             "_group": "base" if i < 5 else "extra"}
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
                page._refresh_started_at = 1.0
                page._run_started_at = 2.0
                page._on_refresh_works(works[:1])  # 执行前的旧快照
            finally:
                task_page_module.TrackLog = original

        self.assertEqual(page._track_list.count(), 20)


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
