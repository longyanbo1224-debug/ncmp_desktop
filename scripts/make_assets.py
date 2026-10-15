"""生成 QSS 需要的小图片资源。

QSS 一旦覆盖 ``QCheckBox::indicator`` 的 ``background-color``，
Qt 就不再绘制默认的对勾，必须自带一张 ``image:``。
这里用 QPainter 直接画，不依赖 QtSvg（少一个打包风险）。

用法：
    python scripts/make_assets.py
"""
import os
import sys

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPixmap

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_OUT_DIR = os.path.join(_ROOT, "app", "ui", "styles")

# 2 倍图，Qt 会按需缩放；14px 指示器下最清晰
_SIZE = 28
_STROKE = 3.4


def make_check(path: str, color: str = "#FFFFFF") -> None:
    """画一个白（或指定色）对勾到透明 PNG。"""
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(color))
        pen.setWidthF(_STROKE)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        s = _SIZE / 14.0  # 按 14x14 的设计网格缩放
        painter.drawPolyline([
            QPointF(3.2 * s, 7.4 * s),
            QPointF(5.8 * s, 10.1 * s),
            QPointF(10.9 * s, 4.4 * s),
        ])
    finally:
        painter.end()
    pixmap.save(path, "PNG")


def main() -> int:
    app = QGuiApplication(sys.argv)  # QPixmap 需要 QGuiApplication
    os.makedirs(_OUT_DIR, exist_ok=True)
    target = os.path.join(_OUT_DIR, "check.png")
    make_check(target)
    print(f"wrote {target}")
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
