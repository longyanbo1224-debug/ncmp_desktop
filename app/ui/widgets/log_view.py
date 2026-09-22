"""实时日志流（对标 Actions live log）。

``GuiLogHandler`` 挂到 ``logging`` root，把 ncmp 所有日志通过 Qt 信号实时推到 UI。
``LogView`` 是只读 ``QPlainTextEdit``，自动滚到底，等宽字体。

注：``logging.Handler`` 不是 ``QObject``，无法直接在其上定义 ``Signal``，
因此 ``GuiLogHandler`` 内部持有一个 ``_LogSignaler``（QObject）来承载信号，
``log_signal`` 属性代理到它，外部可照常 ``handler.log_signal.connect(...)``。
"""
import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit


class _LogSignaler(QObject):
    """承载 Qt 信号的 QObject（logging.Handler 无法多继承 QObject）。"""
    log_signal = Signal(str)


class GuiLogHandler(logging.Handler):
    """把 logging 记录通过 Qt 信号转发到 UI。

    ``logging.Handler.emit`` 通常在产生日志的线程被调用；
    Qt 信号是线程安全的，会自动切到接收者所在线程（主线程）的槽，
    因此无需手动加锁即可安全更新 UI 控件。
    """

    def __init__(self) -> None:
        super().__init__()
        self._signaler = _LogSignaler()

    @property
    def log_signal(self):
        """代理到内部 signaler 的 bound signal，支持 ``.connect/.emit``。"""
        return self._signaler.log_signal

    def emit(self, record: logging.LogRecord) -> None:  # type: ignore[override]
        # 过滤 pyncm / urllib3 等第三方库的 DEBUG/INFO 噪音（仅 WARNING 以上推到 UI）
        # 双保险：即使 logger 未设高级别也不刷屏；ncmp 自身日志（core./app.）不受影响
        # urllib3 的 HTTP 请求 DEBUG（扫码轮询 POST 刷屏）也在此过滤
        if record.name.startswith(("pyncm", "urllib3")) and record.levelno < logging.WARNING:
            return
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        try:
            self._signaler.log_signal.emit(msg)
        except Exception:
            pass

    @classmethod
    def install(cls, level: int = logging.DEBUG,
                fmt: str = "%(asctime)s - %(levelname)s - %(message)s") -> "GuiLogHandler":
        """构造 ``GuiLogHandler`` 并挂到 ``logging`` root。

        返回创建的 handler 实例，调用方持有引用以避免被 GC。
        必须在 ``QApplication`` 已创建后调用（内部需实例化 QObject）。
        """
        handler = cls()
        handler.setFormatter(logging.Formatter(fmt))
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        root_logger.setLevel(level)
        return handler


class LogView(QPlainTextEdit):
    """只读等宽日志展示控件，接收字符串后追加并滚到底部。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        font = QFont("Consolas")
        if not font.exactMatch():
            font = QFont("Courier New")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(9)
        self.setFont(font)
        self.setMaximumBlockCount(5000)  # 防止无限堆积内存
        # 启动欢迎日志（初始内容，非空状态组件，仅 append 一次）
        self.appendPlainText("ncmp desktop 已就绪，等待操作…")

    def appendLog(self, line: str) -> None:
        """追加一行日志并自动滚到底部。"""
        self.appendPlainText(line)
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.setTextCursor(cursor)
