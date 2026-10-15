"""连续打卡图。

53 周 × 7 天的格子，像 GitHub 贡献图那样一眼看出坚持得怎么样。

**配色不用 GitHub 那种单色深浅，而是复用程序的状态色：**
绿=当天成功、红=当天失败、灰=当天没跑。这样格子和界面其他地方
说的是同一种语言，而且能一眼看出哪几天翻车了——单色深浅做不到这点。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from app.ui import theme

_CELL = 11
_GAP = 3
_WEEKS = 53
_LEFT = 20          # 左侧星期标签宽度
_TOP = 17           # 顶部月份标签高度
_LEGEND_H = 22      # 底部图例高度

_WEEKDAY_ROWS = {0: "一", 2: "三", 4: "五"}

_STATUS_TEXT = {
    "success": "成功",
    "failed": "失败",
    "none": "没跑",
}


class StreakGrid(QWidget):
    """连续打卡格子图。

    调用 :meth:`set_days` 传入 ``[(date, "success"/"failed"/"none"), ...]``。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cells: Dict[Tuple[int, int], Tuple[date, str]] = {}
        self._months: List[Tuple[int, str]] = []
        self._streak = 0
        self._total = 0

        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedSize(
            _LEFT + _WEEKS * _CELL + (_WEEKS - 1) * _GAP,
            _TOP + 7 * _CELL + 6 * _GAP + _LEGEND_H)
        self.setMouseTracking(True)
        self.setAccessibleName("连续打卡图")

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------
    def set_days(self, days: List[Tuple[date, str]]) -> None:
        """铺数据。``days`` 从旧到新，最后一项应当是今天。"""
        self._cells, self._months = self._layout(days)
        self._streak = self._compute_streak(days)
        self._total = sum(1 for _, s in days if s == "success")
        self.update()

    def _layout(self, days):
        """把日期铺进 53×7 的格子。最后一列是本周，列从周一开始。"""
        if not days:
            return {}, []
        today = days[-1][0]
        end_monday = today - timedelta(days=today.weekday())
        start_monday = end_monday - timedelta(days=(_WEEKS - 1) * 7)

        cells: Dict[Tuple[int, int], Tuple[date, str]] = {}
        for day, status in days:
            if day < start_monday or day > today:
                continue
            col, row = divmod((day - start_monday).days, 7)
            if 0 <= col < _WEEKS:
                cells[(col, row)] = (day, status)

        # 月份标签：某列的首日进入新月份时，在那一列上方标出来
        months: List[Tuple[int, str]] = []
        last_month = None
        for col in range(_WEEKS):
            for row in range(7):
                cell = cells.get((col, row))
                if cell is None:
                    continue
                month = cell[0].month
                if month != last_month:
                    # 第一列不标，避免和左边挤在一起
                    if col > 0:
                        months.append((col, f"{month}月"))
                    last_month = month
                break
        return cells, months

    @staticmethod
    def _compute_streak(days: List[Tuple[date, str]]) -> int:
        """从今天往回数，连续成功多少天。今天还没跑不算断。"""
        if not days:
            return 0
        streak = 0
        # 倒着走：今天没跑不算断（可能还没到点），从昨天开始数
        items = list(days)
        idx = len(items) - 1
        if idx >= 0 and items[idx][1] != "success":
            idx -= 1
        while idx >= 0 and items[idx][1] == "success":
            streak += 1
            idx -= 1
        return streak

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    @staticmethod
    def _color(status: str) -> QColor:
        if status == "success":
            return QColor(theme.SUCCESS)
        if status == "failed":
            return QColor(theme.FAILED)
        return QColor(theme.METER_TRACK)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            font = QFont(self.font())
            font.setPixelSize(theme.FS_CAPTION - 1)
            painter.setFont(font)
            painter.setPen(QColor(theme.MUTED))

            # 月份标签
            for col, text in self._months:
                x = _LEFT + col * (_CELL + _GAP)
                painter.drawText(x, 0, 30, _TOP - 4,
                                 Qt.AlignLeft | Qt.AlignVCenter, text)

            # 星期标签
            for row, text in _WEEKDAY_ROWS.items():
                y = _TOP + row * (_CELL + _GAP)
                painter.drawText(0, y, _LEFT - 5, _CELL,
                                 Qt.AlignRight | Qt.AlignVCenter, text)

            # 格子
            painter.setPen(Qt.NoPen)
            for (col, row), (_day, status) in self._cells.items():
                painter.setBrush(self._color(status))
                painter.drawRect(QRect(
                    _LEFT + col * (_CELL + _GAP),
                    _TOP + row * (_CELL + _GAP),
                    _CELL, _CELL))

            self._paint_legend(painter)
        finally:
            painter.end()

    def _paint_legend(self, painter: QPainter) -> None:
        """底部图例：三个色块 + 文字，外加连续天数和累计天数。"""
        y = _TOP + 7 * _CELL + 6 * _GAP + 5
        x = 0
        painter.setPen(Qt.NoPen)
        for status, label in (("success", "成功"), ("failed", "失败"),
                              ("none", "没跑")):
            painter.setBrush(self._color(status))
            painter.drawRect(QRect(x, y, _CELL, _CELL))
            x += _CELL + 4
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(x, y - 3, 40, _CELL + 6,
                             Qt.AlignLeft | Qt.AlignVCenter, label)
            x += 30

        # 右侧：连续 / 累计。只统计有记录的天数，别把没跑的日子算进去。
        if self._total or self._streak:
            painter.setPen(QColor(theme.MUTED))
            text = f"连续 {self._streak} 天　累计 {self._total} 天"
            painter.drawText(x + 8, y - 3, self.width() - x - 8, _CELL + 6,
                             Qt.AlignRight | Qt.AlignVCenter, text)

    # ------------------------------------------------------------------
    # 悬停提示
    # ------------------------------------------------------------------
    def _cell_at(self, pos) -> Optional[Tuple[date, str]]:
        col = (pos.x() - _LEFT) // (_CELL + _GAP)
        row = (pos.y() - _TOP) // (_CELL + _GAP)
        if col < 0 or row < 0:
            return None
        return self._cells.get((int(col), int(row)))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        cell = self._cell_at(event.position().toPoint())
        if cell is None:
            QToolTip.hideText()
            return
        day, status = cell
        QToolTip.showText(
            event.globalPosition().toPoint(),
            f"{day.year}-{day.month:02d}-{day.day:02d}　"
            f"{_STATUS_TEXT.get(status, status)}",
            self)

    def leaveEvent(self, event) -> None:  # noqa: N802
        QToolTip.hideText()
