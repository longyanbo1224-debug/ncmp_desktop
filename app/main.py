"""ncmp desktop 入口。

启动顺序：
    1. 构造 ``QApplication``
    2. 加载 ``light.qss`` 浅色扁平主题
    3. 安装 ``GuiLogHandler`` 到 ``logging`` root，把 ncmp 全部日志实时推到 UI
    4. 构造 ``MainWindow`` + ``TrayIcon``
    5. 启动后台 ``ValidateWorker``
    6. ``app.exec()`` 进入事件循环
"""
import logging
import os
import sys

# Windows: 设 AppUserModelID，让任务栏显示自定义品牌图标而非 python.exe 默认图标
# 必须在 QApplication 构造前调用；配合 MainWindow.setWindowIcon 生效
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ncmp.desktop.app")
    except Exception:
        pass

# 确保项目根目录在 sys.path 中（直接 `python app/main.py` 启动时也可用）
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PySide6.QtCore import QFile, QIODevice, Qt
from PySide6.QtWidgets import QApplication

from app.app_config import AppConfig
from app.ui.main_window import MainWindow
from app.ui.widgets.log_view import GuiLogHandler


def _resource_path(*parts: str) -> str:
    """资源路径解析：PyInstaller 打包后从 sys._MEIPASS 读，开发模式从源码目录读。"""
    base = getattr(sys, "_MEIPASS", _HERE)
    return os.path.join(base, *parts)


def load_stylesheet(app: QApplication) -> str:
    """读取 light.qss 文本；读取失败时返回空串。"""
    qss_path = _resource_path("ui", "styles", "light.qss")
    try:
        with open(qss_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        pass
    # 备用：用 QFile 读 Qt 资源路径（本仓库未启用 Qt 资源，仅作占位）
    file = QFile(qss_path)
    if file.open(QIODevice.ReadOnly | QIODevice.Text):
        try:
            return bytes(file.readAll()).decode("utf-8")
        finally:
            file.close()
    return ""


def main() -> int:
    # 单实例锁：已有实例运行则弹窗提示并退出，避免重复执行
    import tempfile
    from PySide6.QtCore import QLockFile
    _lock = QLockFile(os.path.join(tempfile.gettempdir(), "ncmp desktop.lock"))
    _lock.setStaleLockTime(0)  # 进程崩溃残留锁立即判 stale，下次可正常加锁
    if not _lock.tryLock(0):  # 0=不等待立即返回（PySide6 打包后 tryLock 需显式传 timeout）
        _msg = "ncmp desktop 已在运行，请勿重复启动。"
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(0, _msg, "提示", 0x40)
            except Exception:
                print(_msg)
        else:
            print(_msg)
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("ncmp desktop")
    app.setQuitOnLastWindowClosed(False)  # 关闭主窗口时托盘仍在

    # 加载样式
    qss = load_stylesheet(app)
    if qss:
        app.setStyleSheet(qss)

    # 安装日志 Handler 到 root logger
    handler = GuiLogHandler.install(
        level=logging.DEBUG,
        fmt="%(asctime)s - %(levelname)s - %(message)s",
    )
    # pyncm 扫码轮询会狂打 DEBUG 日志（LoginQrcodeCheck 等），调高其级别避免刷屏 UI
    # ncmp 自身日志（core./app.）不受影响，仍走 DEBUG
    logging.getLogger("pyncm").setLevel(logging.WARNING)
    # urllib3（requests 底层）会打 HTTP 请求 DEBUG（扫码轮询 POST 刷屏），调高避免噪音
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)

    # 配置
    app_config = AppConfig()

    # 主窗口
    window = MainWindow(app_config=app_config)
    window.install_log_handler(handler)
    window.show()
    window.start_background_workers()

    logging.getLogger().info("ncmp desktop 已启动")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
