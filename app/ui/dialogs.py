"""统一的消息框。

``QMessageBox`` 自带的图标是 Fusion 风格的蓝色 i / 黄色三角，跟这套界面不搭，
尺寸也和程序别处对不上。这里包一层：

- 图标换成 Phosphor，按语义上色（成功绿 / 警告琥珀 / 失败红 / 提示品牌红）
- 背景、文字、按钮由 ``theme.py`` 里的 ``QMessageBox`` 规则统一
- 调用方只给标题和正文，不用每次重复拼

新增对话框请走这里，不要直接 ``QMessageBox.information(...)``。
"""
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QMessageBox, QWidget

from app.ui import theme
from app.ui.icons import op_icon

_ICON_PX = 40

# 语义 → (Phosphor 图标名, 颜色)
_ICONS = {
    "info": ("ph.info", theme.BRAND),
    "success": ("ph.check-circle", theme.SUCCESS),
    "warning": ("ph.warning-circle", theme.RUNNING_TEXT),
    "error": ("ph.x-circle", theme.FAILED),
    "question": ("ph.question", theme.BRAND),
}


def _make(parent, kind: str, title: str, text: str) -> QMessageBox:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    name, color = _ICONS.get(kind, _ICONS["info"])
    try:
        box.setIconPixmap(op_icon(name, color).pixmap(QSize(_ICON_PX, _ICON_PX)))
    except Exception:
        pass
    return box


def info(parent: QWidget, title: str, text: str) -> None:
    """中性提示。"""
    _make(parent, "info", title, text).exec()


def success(parent: QWidget, title: str, text: str) -> None:
    """操作成功的确认。"""
    _make(parent, "success", title, text).exec()


def warn(parent: QWidget, title: str, text: str) -> None:
    """警告：能继续，但有东西不对劲。"""
    _make(parent, "warning", title, text).exec()


def error(parent: QWidget, title: str, text: str) -> None:
    """失败：这次操作没成。"""
    _make(parent, "error", title, text).exec()


def confirm(parent: QWidget, title: str, text: str,
            yes: str = "确定", no: str = "取消",
            default_no: bool = True) -> bool:
    """是/否确认。默认落在"否"上，避免误按回车执行破坏性操作。"""
    box = _make(parent, "question", title, text)
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    try:
        box.button(QMessageBox.Yes).setText(yes)
        box.button(QMessageBox.No).setText(no)
    except Exception:
        pass
    box.setDefaultButton(QMessageBox.No if default_no else QMessageBox.Yes)
    return box.exec() == QMessageBox.Yes
