"""ncmp desktop 入口。

启动顺序：
    1. 构造 ``QApplication``
    2. 套主题（Fusion 风格 + 随包字体 + 由 ``theme.py`` 生成的样式表）
    3. 安装 ``GuiLogHandler`` 到 ``logging`` root，把 ncmp 全部日志实时推到 UI
    4. 构造 ``MainWindow`` + ``TrayIcon``
    5. 启动后台 ``ValidateWorker``
    6. ``app.exec()`` 进入事件循环

样式表不再是 ``light.qss`` 文件，而是由 :mod:`app.ui.theme` 在运行时生成，
保证设计变量只有一个来源，不会出现"改了 theme 忘了重新生成 qss"的漂移。
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

from PySide6.QtCore import QLockFile, QThread
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from app.app_config import AppConfig
from app.logging_setup import install_file_logging
from app.ui import theme
from app.ui.main_window import MainWindow
from app.ui.widgets.log_view import GuiLogHandler
from app.version import __version__

# 单实例通信用的本地套接字名（Windows 上是命名管道）
_INSTANCE_SERVER = "ncmp-desktop-instance"


def _activate_running_instance() -> bool:
    """连上已运行的实例，让它把窗口拉回前台。连不上返回 False。"""
    # 连试几次：已运行的实例刚抢到锁、还没开始监听的那一两百毫秒里会连不上
    for _ in range(4):
        sock = QLocalSocket()
        sock.connectToServer(_INSTANCE_SERVER)
        if sock.waitForConnected(300):
            sock.write(b"show")
            sock.flush()
            sock.waitForBytesWritten(300)
            sock.disconnectFromServer()
            return True
        QThread.msleep(120)
    return False


def _notify_already_running() -> None:
    _msg = "ncmp desktop 已在运行，请勿重复启动。"
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, _msg, "提示", 0x40)
        except Exception:
            print(_msg)
    else:
        print(_msg)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ncmp desktop")
    app.setQuitOnLastWindowClosed(False)  # 关闭主窗口时托盘仍在

    # 单实例：已有实例在跑就直接唤醒它的窗口，而不是弹一句"已在运行"。
    # 用户最小化到托盘后忘了，再点桌面图标，最符合直觉的结果是窗口回到前台。
    import tempfile
    _lock = QLockFile(os.path.join(tempfile.gettempdir(), "ncmp desktop.lock"))
    _lock.setStaleLockTime(0)  # 进程崩溃残留锁立即判 stale，下次可正常加锁
    if not _lock.tryLock(0):  # 0=不等待立即返回（PySide6 打包后 tryLock 需显式传 timeout）
        if _activate_running_instance():
            return 0
        # 旧实例没在监听（例如卡死）：保留原来的提示，不抢它的锁
        _notify_already_running()
        return 1

    # 主实例：监听唤醒请求。newConnection 在窗口建好后再接，避免空指针。
    QLocalServer.removeServer(_INSTANCE_SERVER)
    _server = QLocalServer()
    _server.listen(_INSTANCE_SERVER)

    # 套主题：Fusion 风格 + 随包字体 + 由 theme.py 生成的样式表
    theme.apply_theme(app)

    # 安装日志 Handler 到 root logger
    # 先装文件日志（按天滚动保留 7 天），再装 UI Handler——
    # 这样即使 UI 那边出问题，日志也已经落到磁盘上了。
    # 必须在 QApplication 之后：日志目录解析走 QStandardPaths。
    log_dir_path = install_file_logging(level=logging.DEBUG)
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

    def _on_activation() -> None:
        # 连上就说明用户又点了一次图标；内容不重要，把窗口拉回来即可
        while _server.hasPendingConnections():
            conn = _server.nextPendingConnection()
            conn.disconnectFromServer()
        window.show_from_second_instance()

    _server.newConnection.connect(_on_activation)
    if _server.hasPendingConnections():  # 窗口建好前就有人连过
        _on_activation()

    window.show()
    window.start_background_workers()

    logging.getLogger().info("ncmp desktop 已启动（版本 %s）", __version__)
    if log_dir_path:
        logging.getLogger().info("日志目录：%s", log_dir_path)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
