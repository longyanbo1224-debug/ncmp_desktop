"""统一的消息框。

``QMessageBox`` 是系统风格的对话框：图标是 Fusion 自带的蓝 i / 黄三角，
边距、字号、按钮排布都和程序别处不一致。这里改成自绘对话框：

- 图标换成 Phosphor，按语义上色（成功绿 / 警告琥珀 / 失败红 / 提示品牌红）
- 标题 15px 半粗、正文 13px 次要色，按钮靠右、主按钮红底
- 尺寸固定下限，长文案正常折行，不再挤成一条

新增对话框请走这里，不要直接 ``QMessageBox.information(...)``。
"""
from typing import List, Tuple

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from app.ui import theme
from app.ui.icons import op_icon

_ICON_PX = 22

# 语义 → (Phosphor 图标名, 颜色)
_ICONS = {
    "info": ("ph.info", theme.BRAND),
    "success": ("ph.check-circle", theme.SUCCESS),
    "warning": ("ph.warning-circle", theme.RUNNING_TEXT),
    "error": ("ph.x-circle", theme.FAILED),
    "question": ("ph.question", theme.BRAND),
}


class _MessageDialog(QDialog):
    """应用内样式的消息框。``_result`` 是点下的按钮值。"""

    def __init__(self, parent: QWidget, kind: str, title: str, text: str,
                 buttons: List[Tuple[str, object]], default_value) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)
        self._result = default_value

        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.SP_5, theme.SP_4, theme.SP_5, theme.SP_4)
        outer.setSpacing(theme.SP_3)

        head = QHBoxLayout()
        head.setSpacing(theme.SP_2)
        icon = QLabel()
        icon.setFixedSize(_ICON_PX, _ICON_PX)
        name, color = _ICONS.get(kind, _ICONS["info"])
        try:
            icon.setPixmap(op_icon(name, color).pixmap(QSize(_ICON_PX, _ICON_PX)))
        except Exception:
            pass
        head.addWidget(icon, 0, Qt.AlignTop)

        heading = QLabel(title)
        heading.setObjectName("sectionHeading")
        head.addWidget(heading, 1)
        outer.addLayout(head)

        body = QLabel(text)
        body.setObjectName("subtitle")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outer.addWidget(body)

        row = QHBoxLayout()
        row.setSpacing(theme.SP_2)
        row.addStretch(1)
        self._buttons: List[Tuple[QPushButton, object]] = []
        for label, value in buttons:
            button = QPushButton(label)
            button.setObjectName(
                "primaryButton" if value is not False else "secondaryButton")
            button.setMinimumWidth(84)
            button.clicked.connect(
                lambda _checked=False, v=value: self._finish(v))
            row.addWidget(button)
            self._buttons.append((button, value))
        outer.addLayout(row)

        for button, value in self._buttons:
            if value == default_value:
                # 只设默认按钮（回车触发），不抢焦点——否则红底按钮上会挂一圈
                # 深色焦点框，看起来像被选中了。
                button.setDefault(True)
                break

    def _finish(self, value) -> None:
        self._result = value
        self.accept()


def _show(parent, kind: str, title: str, text: str,
          buttons: List[Tuple[str, object]], default_value) -> object:
    dialog = _MessageDialog(parent, kind, title, text, buttons, default_value)
    dialog.exec()
    return dialog._result


def info(parent: QWidget, title: str, text: str) -> None:
    """中性提示。"""
    _show(parent, "info", title, text, [("知道了", True)], True)


def success(parent: QWidget, title: str, text: str) -> None:
    """操作成功的确认。"""
    _show(parent, "success", title, text, [("知道了", True)], True)


def warn(parent: QWidget, title: str, text: str) -> None:
    """警告：能继续，但有东西不对劲。"""
    _show(parent, "warning", title, text, [("知道了", True)], True)


def error(parent: QWidget, title: str, text: str) -> None:
    """失败：这次操作没成。"""
    _show(parent, "error", title, text, [("知道了", True)], True)


def confirm(parent: QWidget, title: str, text: str,
            yes: str = "确定", no: str = "取消",
            default_no: bool = True) -> bool:
    """是/否确认。默认落在"否"上，避免误按回车执行破坏性操作。"""
    result = _show(parent, "question", title, text,
                   [(no, False), (yes, True)], default_no is False)
    return result is True
