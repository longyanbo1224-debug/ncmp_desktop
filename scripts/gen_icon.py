"""生成 resources/app.ico：多分辨率 Windows ICO。

用 QPainter 绘 6 个尺寸 PNG (16, 32, 48, 64, 128, 256)：
圆角方形主色蓝 (#2E7DDE) 底 + 白色 fa5s.music 元素居中，
再用 Pillow 合并保存为多分辨率 ICO，供 PyInstaller ``--icon`` 与 exe 文件图标使用。

用法：
    python scripts/gen_icon.py
"""
import io
import os
import sys

from PySide6.QtCore import QBuffer, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
from PIL import Image
import qtawesome as qta

COLOR_PRIMARY = "#2E7DDE"
ICON_NAME = "fa5s.music"
SIZES = (16, 32, 48, 64, 128, 256)


def render_pixmap(size: int) -> QPixmap:
    """以指定尺寸绘制品牌图标 QPixmap。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        # 圆角方形底
        radius = max(2, size // 6)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(COLOR_PRIMARY))
        painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)
        # 白色 music 元素居中
        icon = qta.icon(ICON_NAME, color="#ffffff")
        icon_size = int(size * 0.6)
        margin = (size - icon_size) // 2
        icon.paint(painter, margin, margin, icon_size, icon_size)
    finally:
        painter.end()
    return pm


def to_png_bytes(pm: QPixmap) -> bytes:
    """QPixmap → PNG 字节。"""
    buf = QBuffer()
    buf.open(QBuffer.ReadWrite)
    pm.save(buf, "PNG")
    return bytes(buf.data())


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    res_dir = os.path.join(root, "resources")
    os.makedirs(res_dir, exist_ok=True)
    out = os.path.join(res_dir, "app.ico")

    # qtawesome 需要 QCoreApplication 已构造
    app = QApplication.instance() or QApplication(sys.argv)

    images = []
    for s in SIZES:
        pm = render_pixmap(s)
        bio = io.BytesIO(to_png_bytes(pm))
        images.append(Image.open(bio).convert("RGBA"))

    # 用最大尺寸作 base，其余作 append_images；
    # 同时给 sizes= 全部目标尺寸，PIL 会为每个目标挑选最贴合的源图（精确匹配则不缩放）。
    base = max(images, key=lambda im: im.size[0])
    others = [im for im in images if im is not base]
    base.save(out, format="ICO",
              sizes=[(s, s) for s in SIZES],
              append_images=others)

    size_bytes = os.path.getsize(out)
    print(f"Generated: {out}")
    print(f"File size: {size_bytes} bytes")

    # 校验：读回 ICO，列出内部所有 entry 尺寸
    try:
        ico = Image.open(out)
        entry_sizes = sorted(set(ico.ico.sizes()))
        print(f"ICO entries: {entry_sizes}")
        missing = [s for s in SIZES if (s, s) not in entry_sizes]
        if missing:
            print(f"WARN: missing sizes: {missing}")
            return 1
    except Exception as e:
        print(f"WARN: ico verify failed: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
