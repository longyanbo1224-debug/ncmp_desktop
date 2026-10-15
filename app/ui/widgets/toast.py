"""应用内通知气泡。

系统托盘气泡（``QSystemTrayIcon.showMessage``）长什么样由操作系统决定，
程序改不了——用户反馈"不够好看"就是这个原因。这里自己画一个右下角弹出的小窗，
配色、圆角、字号跟程序其他部分完全一致。

行为：
- 无边框、置顶、**不抢焦点**（弹出时不会打断你正在做的事）
- 5 秒后自动淡出，点一下立刻关掉
- 多条通知向上堆叠，不会互相盖住
- 系统关掉窗口动画时不做淡入
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import (
    QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer,
)
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from app.ui import theme
from app.ui.icons import op_icon

_MARGIN = 16          # 距屏幕右下角的边距
_GAP = 10             # 气泡之间的间距
_WIDTH = 340
_TIMEOUT_MS = 5000
_FADE_MS = 160


class Toast(QWidget):
    """右下角的一条通知。"""

    #: 当前活着的通知，用来堆叠定位
    _active: List["Toast"] = []

    def __init__(self, title: str, body: str,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint
                         | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("toastPanel")
        self.setFixedWidth(_WIDTH)
        self.setCursor(Qt.PointingHandCursor)
        self._build(title, body)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._fade: Optional[QPropertyAnimation] = None

    # ------------------------------------------------------------------
    def _build(self, title: str, body: str) -> None:
        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SP_4, theme.SP_3, theme.SP_4, theme.SP_3)
        row.setSpacing(theme.SP_3)

        icon = QLabel()
        icon.setFixedSize(22, 22)
        icon.setPixmap(op_icon("ph.music-notes", theme.BRAND).pixmap(22, 22))
        row.addWidget(icon, 0, Qt.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("toastTitle")
        title_label.setWordWrap(True)
        text_col.addWidget(title_label)

        body_label = QLabel(body)
        body_label.setObjectName("toastBody")
        body_label.setWordWrap(True)
        text_col.addWidget(body_label)

        row.addLayout(text_col, 1)

    # ------------------------------------------------------------------
    def show_at_corner(self) -> None:
        """放到屏幕右下角，已存在的通知依次往上叠。"""
        self.adjustSize()
        geo = self._available_geometry()
        y = geo.bottom() - self.height() - _MARGIN
        for other in Toast._active:
            y -= other.height() + _GAP
        x = geo.right() - self.width() - _MARGIN
        self.move(QPoint(x, y))

        Toast._active.append(self)
        self.show()
        self.raise_()
        self._fade_in()
        self._timer.start(_TIMEOUT_MS)

    @staticmethod
    def _available_geometry():
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return QApplication.primaryScreen().availableGeometry()
        return screen.availableGeometry()

    def _fade_in(self) -> None:
        if theme.reduced_motion():
            return
        try:
            self.setWindowOpacity(0.0)
            anim = QPropertyAnimation(self, b"windowOpacity", self)
            anim.setDuration(_FADE_MS)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start()
            self._fade = anim
        except Exception:
            self.setWindowOpacity(1.0)

    def dismiss(self) -> None:
        """立刻关掉并重排剩下的通知。"""
        self._timer.stop()
        try:
            if self in Toast._active:
                Toast._active.remove(self)
        except Exception:
            pass
        self.close()
        self.deleteLater()
        Toast._restack()

    @staticmethod
    def _restack() -> None:
        """剩下的通知重新贴回右下角，避免留下空档。"""
        geo = None
        try:
            screen = QGuiApplication.primaryScreen()
            geo = screen.availableGeometry() if screen else None
        except Exception:
            pass
        if geo is None:
            return
        y = geo.bottom() - _MARGIN
        for toast in reversed(Toast._active):
            y -= toast.height()
            try:
                toast.move(QPoint(
                    geo.right() - toast.width() - _MARGIN, y))
            except Exception:
                pass
            y -= _GAP

    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.dismiss()

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            if self in Toast._active:
                Toast._active.remove(self)
        except Exception:
            pass
        super().closeEvent(event)


def show(title: str, body: str) -> bool:
    """弹一条通知。失败返回 False，调用方可以降级到系统气泡。"""
    try:
        toast = Toast(title, body)
        toast.show_at_corner()
        return True
    except Exception:
        return False
