"""分段式电平表 —— 全程序唯一的高光元素。

任务页的进度条就是它。为什么是分段电平表而不是普通进度条：

- 它来自主题本身：这是 VU 表，不是网页进度条；
- 功能上诚实：这个任务本来就是在填一个每日配额；
- 它是颜色系统的载体：跑的时候琥珀，成功变绿，失败变红；
- 它正面回答了这个产品的卖点——替掉"盯着 GitHub Actions 看"。

用自绘而不用 ``QProgressBar`` + QSS：QSS 做不出分段。
``qlineargradient`` 的色标是相对 chunk 的，格子会随填充宽度被拉伸。

动效只花在这里，别处一动不动：填充是瞬间的，**最新点亮的那一格闪亮 250ms**。
闪亮说明"刚刚发生了什么变化"，不是入场表演。系统关掉窗口动画时自动跳过。
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.ui import theme

# 最新点亮那一格的闪亮时长
_FLASH_MS = 250


def _lighten(color: str, amount: float) -> QColor:
    """把颜色朝白色混一点，得到"更亮"的版本（用于闪亮）。"""
    c = QColor(color)
    r = int(c.red() + (255 - c.red()) * amount)
    g = int(c.green() + (255 - c.green()) * amount)
    b = int(c.blue() + (255 - c.blue()) * amount)
    return QColor(r, g, b)


class LevelMeter(QWidget):
    """分段式电平表。

    :param segments: 格子数，默认 40（每格 2.5%）。
    """

    def __init__(self, segments: int = theme.METER_SEGMENTS, parent=None) -> None:
        super().__init__(parent)
        self._segments = max(1, int(segments))
        self._progress = 0          # 0~100
        self._state = "pending"
        self._flash_index = -1      # 正在闪亮的格子下标
        self._last_filled = 0

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(theme.METER_HEIGHT)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAccessibleName("任务进度")

        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._clear_flash)

        self._reduced = theme.reduced_motion()

    # ------------------------------------------------------------------
    # 对外
    # ------------------------------------------------------------------
    def set_progress(self, value: int) -> None:
        """设置进度（0~100）。只前进不后退，避免粗粒度阶段进度盖掉更精确的值。"""
        try:
            value = int(value)
        except Exception:
            return
        value = max(0, min(100, value))
        if value == self._progress:
            return
        self._progress = value
        self.update()

    def set_state(self, state: str) -> None:
        """设置状态（running / success / failed / cancelled / pending），决定填充色。"""
        if state == self._state:
            return
        self._state = state
        self.update()

    def reset(self) -> None:
        """回到 0% 的待命态。"""
        self._progress = 0
        self._state = "pending"
        self._last_filled = 0
        self._flash_index = -1
        self.update()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    @property
    def _filled(self) -> int:
        """已点亮的格子数。四舍五入，保证 100% 时全亮。"""
        return int(round(self._progress / 100.0 * self._segments))

    def _clear_flash(self) -> None:
        self._flash_index = -1
        self.update()

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        filled = self._filled

        # 前进时记下新点亮的那一格，稍后闪一下
        if filled > self._last_filled and not self._reduced:
            self._flash_index = filled - 1
            self._flash_timer.start(_FLASH_MS)
        elif filled < self._last_filled:
            self._flash_index = -1
        self._last_filled = filled

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, False)
            w = self.width()
            h = self.height()
            n = self._segments
            gap = theme.METER_GAP
            seg_w = (w - gap * (n - 1)) / n
            if seg_w <= 0:
                return

            base = QColor(theme.state_fill(self._state))
            track = QColor(theme.METER_TRACK)
            flash = _lighten(base.name(), 0.45)

            # 运行中且还没跑满时，下一格用淡色垫底——
            # 这是静态的"我们在这里、正在往前走"，不靠动画
            leading = -1
            if self._state == "running" and 0 < filled < n:
                leading = filled
            elif self._state == "running" and filled == 0:
                leading = 0

            painter.setPen(Qt.NoPen)
            for i in range(n):
                x = i * (seg_w + gap)
                if i < filled:
                    color = flash if i == self._flash_index else base
                elif i == leading:
                    color = QColor(base)
                    color.setAlpha(70)
                else:
                    color = track
                painter.setBrush(color)
                painter.drawRect(QRectF(x, 0, seg_w, h))
        finally:
            painter.end()
