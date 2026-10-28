"""合伙人积分/等级的本地缓存。

存在设置文件同目录的 ``partner_points.json``：查询发生在任务线程里，
记录页只读这个文件，界面线程不联网。文件不存在/内容坏掉都当成"没有数据"。
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Dict

from app.app_config import _default_config_path


def _path() -> Path:
    return _default_config_path().parent / "partner_points.json"


def save(points: Dict[str, str], path=None) -> None:
    if not points:
        return
    target = Path(path) if path is not None else _path()
    payload = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "points": points,
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
        tmp.replace(target)
    except Exception:
        pass


def load(path=None) -> Dict[str, str]:
    target = Path(path) if path is not None else _path()
    try:
        with open(target, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        points = data.get("points")
        if isinstance(points, dict):
            return {str(k): str(v) for k, v in points.items()}
    except Exception:
        pass
    return {}
