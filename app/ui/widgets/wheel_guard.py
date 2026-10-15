"""滚轮误改保护。

问题：鼠标停在设置页的下拉框或数字框上滚动页面时，Qt 会把滚轮当成
"改数值"——用户明明只是想往下看，结果 cookie 有效期被改了。
虽然没点保存不会落盘，但用起来很别扭。

做法：**无条件**吞掉这些控件上的滚轮事件，并转发给最近的父级滚动区。
"滚页面"照常工作，改数值只能靠点箭头或直接输入。

为什么不是"只在没焦点时拦"：控件只要被点过一次就会获得焦点，
之后滚轮照样能改数值。第一版就是这么写的，所以用户反馈"还是会发生"。
彻底去掉这个交互反而更可预测。
"""
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import (
    QAbstractScrollArea, QAbstractSpinBox, QApplication, QComboBox,
)


class WheelGuard(QObject):
    """拦住下拉框／数字框／时间框上的滚轮事件，一律不改数值。"""

    #: 会被保护的控件类型
    GUARDED = (QComboBox, QAbstractSpinBox)

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() != QEvent.Wheel:
            return False
        if not isinstance(obj, self.GUARDED):
            return False

        # 转发给最近的父级滚动区，页面照常滚动。
        # 注意不能只 ignore() 就返回：那样事件仍会送到控件自己手里。
        parent = obj.parent()
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                QApplication.sendEvent(parent.viewport(), event)
                return True
            parent = parent.parent()
        # 没有可滚动的父级：直接吞掉，不改数值也不让它冒泡
        event.ignore()
        return True


def install(app: QApplication) -> WheelGuard:
    """把保护装到 QApplication 上。返回实例（调用方需持引用）。"""
    guard = WheelGuard(app)
    app.installEventFilter(guard)
    return guard
