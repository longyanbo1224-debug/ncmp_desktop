"""额外任务清单要去掉当天的基础任务。

服务端的额外清单接口会把等待评分的作品都列出来，其中包括每日基础任务
那 5 首。不去掉的话：曲目表把 20 首当成 20 首"额外"、按 15 首上限裁成
15 行；评分阶段也会少评基础曲目占掉的额度。
"""
import unittest

from core.tasks.extra import ExtraTask


class _Logger:
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass
    def debug(self, msg): pass


class _Response:
    def __init__(self, data):
        self._data = data

    def json(self):
        return {"code": 200, "message": "ok", "data": self._data}


class _Session:
    """按 URL 返回固定清单；额外清单里故意混入基础任务。"""

    def __init__(self, data):
        self.data = data

    def get(self, *args, **kwargs):
        return _Response(self.data)


def _work(work_id, name):
    return {"work": {"id": work_id, "name": name, "authorName": "某"},
            "completed": False, "score": None}


def _extra_task(data):
    """绕开 __init__：这轮只测清单过滤，不需要真正的 Signer。"""
    task = ExtraTask.__new__(ExtraTask)
    task.logger = _Logger()
    task.session = _Session(data)
    task.api = {"extra_list": "https://example.invalid/list"}
    task.on_works = None
    task.last_all = []
    task.base_ids = set()
    task.base_names = set()
    return task


class ExtraBaseFilterTest(unittest.TestCase):
    def test_base_works_are_removed_from_extra_list(self):
        base = [_work(i, f"基础{i}") for i in range(5)]
        extras = [_work(100 + i, f"额外{i}") for i in range(15)]
        # 服务端把基础任务也列进额外清单：不剔除时会变成 20 行"额外"
        data = list(extras) + list(base)
        task = _extra_task(data)
        task.set_base_works(base)

        pending, completed = task._get_extra_tasks(emit=False)

        self.assertEqual(len(pending), 15)
        self.assertEqual(completed, 0)
        self.assertEqual(len(task.last_all), 15)
        self.assertFalse(any("基础" in t["work"]["name"] for t in task.last_all))

    def test_filter_falls_back_to_name_when_id_missing(self):
        base = [{"work": {"name": "同名基础"}, "completed": False}]
        data = [{"work": {"name": "同名基础"}, "completed": False},
                _work(1, "额外一")]
        task = _extra_task(data)
        task.set_base_works(base)

        pending, _ = task._get_extra_tasks(emit=False)

        self.assertEqual([t["work"]["name"] for t in pending], ["额外一"])

    def test_duplicate_extra_entries_stay(self):
        """同名的额外行不是基础任务时不能被误删（过滤只按基础清单匹配）。"""
        base = [_work(1, "基础一")]
        data = [_work(2, "额外一"), _work(3, "额外一")]
        task = _extra_task(data)
        task.set_base_works(base)

        pending, _ = task._get_extra_tasks(emit=False)

        self.assertEqual(len(pending), 2)


if __name__ == "__main__":
    unittest.main()
