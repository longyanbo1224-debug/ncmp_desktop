"""关于页：应用名 / 版本号 / 核心依赖 / 说明 / GitHub 链接 / 版权。

版本号硬编码在模块常量 ``__version__``（AppConfig 无版本字段）。
核心依赖版本在运行时按需 import 获取，缺失则标记「未安装」。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

__version__ = "1.0.0"

APP_NAME = "ncmp desktop"
APP_DESCRIPTION = (
    "基于 ACAne0320/ncmp 改造的桌面程序。本地执行音乐合伙人任务，"
    "支持扫码/密码登录、任务可视化、GitHub Actions 云端触发。"
)
GITHUB_URL = "https://github.com/ACAne0320/ncmp"
GITHUB_LABEL = "ACAne0320/ncmp"
LICENSE = "MIT License"


class AboutPage(QWidget):
    """关于页。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel(APP_NAME)
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        version_label = QLabel(f"版本 {__version__}")
        version_label.setObjectName("subtitle")
        layout.addWidget(version_label)

        deps_label = QLabel(f"核心依赖：{self._deps_text()}")
        deps_label.setObjectName("captionText")
        deps_label.setWordWrap(True)
        layout.addWidget(deps_label)

        desc_label = QLabel(APP_DESCRIPTION)
        desc_label.setObjectName("captionText")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        github_label = QLabel(
            f'GitHub：<a href="{GITHUB_URL}">{GITHUB_LABEL}</a>')
        github_label.setObjectName("captionText")
        github_label.setOpenExternalLinks(True)
        github_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        layout.addWidget(github_label)

        license_label = QLabel(f"版权：{LICENSE}")
        license_label.setObjectName("captionText")
        layout.addWidget(license_label)

        layout.addStretch(1)

    @staticmethod
    def _deps_text() -> str:
        """运行时获取 pyncm / PySide6 / qtawesome / keyring 版本，缺失标「未安装」。"""
        parts = []
        try:
            import pyncm
            parts.append(f"pyncm {getattr(pyncm, '__version__', 'unknown')}")
        except Exception:
            parts.append("pyncm 未安装")
        try:
            import PySide6
            parts.append(f"PySide6 {PySide6.__version__}")
        except Exception:
            parts.append("PySide6 未安装")
        try:
            import qtawesome
            parts.append(f"qtawesome {qtawesome.__version__}")
        except Exception:
            parts.append("qtawesome 未安装")
        try:
            import keyring
            parts.append(f"keyring {keyring.__version__}")
        except Exception:
            parts.append("keyring 未安装")
        return " / ".join(parts)
