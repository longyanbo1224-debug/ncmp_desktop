"""持久化日志：按天滚动，保留 7 天。

在此之前日志只存在内存里，关掉程序就没了——用户遇到问题时
没法提供任何可排查的信息，"报障"这件事从不可能变成可能。

日志目录与配置文件同级（``%LOCALAPPDATA%\\ncmp desktop\\logs\\``），
设置页有「打开日志文件夹」按钮。
"""
from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

# 保留天数（含当天）
KEEP_DAYS = 7

_FILENAME = "ncmp.log"
_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"


def log_dir() -> Path:
    """日志目录。与应用配置同级的 ``logs/``，不存在就建。"""
    from app.app_config import _default_config_path
    directory = Path(_default_config_path()).parent / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def install_file_logging(level: int = logging.DEBUG) -> Optional[str]:
    """装一个按天滚动的文件日志。

    必须在 ``QApplication`` 构造之后调用——目录解析走
    ``QStandardPaths``，没有 QApplication 时会落到错误的路径。

    :returns: 日志目录路径；失败返回 None（不抛异常，日志写不了不该拦住程序启动）。
    """
    try:
        directory = log_dir()
        handler = TimedRotatingFileHandler(
            str(directory / _FILENAME),
            when="midnight",
            backupCount=KEEP_DAYS,
            encoding="utf-8",
            delay=True,
        )
        handler.suffix = "%Y-%m-%d"
        handler.setFormatter(logging.Formatter(_FORMAT))
        handler.setLevel(level)

        root = logging.getLogger()
        root.addHandler(handler)
        # 只在 root 还没设过级别时设，别把调用方（GuiLogHandler.install）的选择覆盖掉
        if root.level in (logging.NOTSET, logging.WARNING):
            root.setLevel(level)
        return str(directory)
    except Exception:
        return None


def open_log_dir() -> bool:
    """用系统文件管理器打开日志目录。"""
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        return bool(QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(log_dir()))))
    except Exception:
        return False
