"""应用自身的配置（与 ncmp 业务配置分离）。

存储与桌面程序自身行为相关的项：Cookie 验证间隔、是否最小化到托盘、主题。
持久化到用户主目录下的 ``~/.ncmp_desktop/config.json``。
"""
import json
import os
from pathlib import Path
from typing import Any, Dict


def _default_config_path() -> Path:
    """返回应用配置文件路径。"""
    try:
        from PySide6.QtCore import QStandardPaths, QDir
        # Qt 推荐路径（AppConfigLocation）
        qt_paths = QStandardPaths.standardLocations(QStandardPaths.AppConfigLocation)
        if qt_paths:
            base = Path(qt_paths[0])
        else:
            base = Path(QDir.homePath()) / ".ncmp_desktop"
    except Exception:
        # PySide6 不可用或未构造 QCoreApplication 时降级到 pathlib
        base = Path.home() / ".ncmp_desktop"
    base.mkdir(parents=True, exist_ok=True)
    return base / "config.json"


class AppConfig:
    """桌面应用配置（不包含 ncmp 业务字段）。"""

    DEFAULTS: Dict[str, Any] = {
        "validate_interval_sec": 6 * 3600,
        "minimize_to_tray": True,
        "theme": "light",
        # close_action: None=每次问, "close"=直接关, "minimize"=最小化到托盘
        "close_action": None,
        # 定时执行：是否启用、触发时间(HH:MM)、模式(local/cloud/both)
        "schedule_enabled": False,
        "schedule_time": "09:00",
        "schedule_mode": "local",
        # 邮件通知开关（默认勾选；与 core.utils.config._apply_defaults 对齐）
        "notify_on_task_done": True,
        "notify_on_cookie_expired": True,
        "notify_on_schedule": True,
    }

    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path) if path else _default_config_path()
        self.data: Dict[str, Any] = dict(self.DEFAULTS)
        self.load()

    def load(self) -> None:
        """从磁盘加载配置；文件不存在或解析失败时使用默认值。"""
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # 仅覆盖已知的 key，避免污染
                for k, v in data.items():
                    if k in self.DEFAULTS:
                        self.data[k] = v
        except Exception:
            pass

    def save(self) -> bool:
        """写入磁盘。成功返回 True。"""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, self.DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        if key in self.DEFAULTS:
            self.data[key] = value

    @property
    def validate_interval_sec(self) -> int:
        return int(self.data.get("validate_interval_sec", self.DEFAULTS["validate_interval_sec"]))

    @property
    def minimize_to_tray(self) -> bool:
        return bool(self.data.get("minimize_to_tray", self.DEFAULTS["minimize_to_tray"]))

    @property
    def theme(self) -> str:
        return str(self.data.get("theme", self.DEFAULTS["theme"]))

    @property
    def close_action(self) -> str | None:
        """关闭行为：None=每次问，"close"=直接关，"minimize"=最小化到托盘。"""
        val = self.data.get("close_action", self.DEFAULTS["close_action"])
        if val is None:
            return None
        return str(val)

    @property
    def schedule_enabled(self) -> bool:
        """是否启用本地定时执行。"""
        return bool(self.data.get("schedule_enabled", self.DEFAULTS["schedule_enabled"]))

    @property
    def schedule_time(self) -> str:
        """定时触发时间，格式 "HH:MM"（24 小时制，默认 "09:00"）。"""
        val = str(self.data.get("schedule_time", self.DEFAULTS["schedule_time"]))
        # 简单校验：HH:MM
        parts = val.split(":")
        if len(parts) != 2:
            return self.DEFAULTS["schedule_time"]
        try:
            h, m = int(parts[0]), int(parts[1])
        except ValueError:
            return self.DEFAULTS["schedule_time"]
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return self.DEFAULTS["schedule_time"]
        return f"{h:02d}:{m:02d}"

    @property
    def schedule_mode(self) -> str:
        """定时模式：local=仅本地任务，cloud=仅云端触发，both=两者都启动。"""
        val = str(self.data.get("schedule_mode", self.DEFAULTS["schedule_mode"]))
        if val not in ("local", "cloud", "both"):
            return self.DEFAULTS["schedule_mode"]
        return val
