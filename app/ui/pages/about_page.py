"""关于页 —— 版权页。

安静的定义列表：版本 / 作者 / 致谢 / 核心依赖 / 许可。
宋体标题，次要色正文，没有别的。

（v1.2 一度改成"先说定位、再说来历"的长版本，太啰嗦，又回到这一版：
关于页是查信息的地方，不是讲故事的页面。）
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from app.ui import theme
from app.version import GITHUB_REPO, RELEASES_URL, __version__

APP_NAME = "ncmp desktop"
APP_DESCRIPTION = (
    "基于 ACAne0320/ncmp 改造的桌面程序。本地执行音乐合伙人任务，"
    "支持扫码/密码登录、任务可视化、GitHub Actions 云端触发；"
    "评分时可同时留下一条批注，今天的曲目与批注会记在「记录」里。"
)
AUTHOR = "Galvin"
GITHUB_URL = f"https://github.com/{GITHUB_REPO}"
GITHUB_LABEL = GITHUB_REPO
UPSTREAM_URL = "https://github.com/ACAne0320/ncmp"
UPSTREAM_LABEL = "ACAne0320/ncmp"
REFERENCE_URL = "https://github.com/Grails125/ncmm"
REFERENCE_LABEL = "Grails125/ncmm"
LICENSE = "MIT License"


def _link(url: str, label: str) -> str:
    """内联样式的富文本链接。

    QSS 管不到 QLabel 里的 <a>，只能写内联样式；颜色取主题的墨色，
    保持"全界面只有状态色"这条规矩。
    """
    return (f'<a href="{url}" style="color:{theme.INK}; '
            f'text-decoration:underline;">{label}</a>')


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
        layout.setContentsMargins(theme.PAGE_MARGIN, theme.PAGE_MARGIN,
                                  theme.PAGE_MARGIN, theme.PAGE_MARGIN)
        layout.setSpacing(0)

        title = QLabel(APP_NAME)
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        layout.addSpacing(theme.SP_2)

        version = QLabel(f"版本 {__version__}　·　{_link(RELEASES_URL, '更新说明')}")
        version.setObjectName("captionText")
        version.setOpenExternalLinks(True)
        version.setTextInteractionFlags(Qt.TextBrowserInteraction)
        layout.addWidget(version)

        # 更新入口：默认隐藏，后台查到新版本才出现（见 set_update_available）
        self._update_label = QLabel("")
        self._update_label.setObjectName("captionText")
        self._update_label.setWordWrap(True)
        self._update_label.setVisible(False)
        layout.addWidget(self._update_label)

        layout.addSpacing(theme.SP_6)

        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SP_5)
        grid.setVerticalSpacing(theme.SP_3)
        grid.setColumnStretch(1, 1)

        rows = [
            ("作者", AUTHOR, False),
            ("致谢", _link(UPSTREAM_URL, UPSTREAM_LABEL)
                     + "　·　" + _link(REFERENCE_URL, REFERENCE_LABEL), True),
            ("核心依赖", self._deps_text(), False),
            ("许可", LICENSE, False),
            ("GitHub", _link(GITHUB_URL, GITHUB_LABEL), True),
        ]
        for i, (key, value, is_html) in enumerate(rows):
            key_label = QLabel(key)
            key_label.setObjectName("captionText")
            key_label.setFixedWidth(64)
            key_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
            grid.addWidget(key_label, i, 0)

            value_label = QLabel(value)
            value_label.setObjectName("captionText")
            value_label.setWordWrap(True)
            if is_html:
                value_label.setOpenExternalLinks(True)
                value_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
            grid.addWidget(value_label, i, 1)

        layout.addLayout(grid)

        layout.addSpacing(theme.SP_6)

        desc = QLabel(APP_DESCRIPTION)
        desc.setObjectName("captionText")
        desc.setWordWrap(True)
        desc.setMaximumWidth(560)
        layout.addWidget(desc)

        layout.addStretch(1)

    # ------------------------------------------------------------------
    # 更新提示
    # ------------------------------------------------------------------
    def set_update_available(self, version: str, url: str) -> None:
        """后台查到新版本时调用，在版本号下方留一条常驻入口。

        只给链接，不下载、不替换——这个 exe 没有代码签名，
        程序自己没法验证更新包有没有被篡改。
        """
        target = url or RELEASES_URL
        self._update_label.setText(
            f"有新版本 {version} 可用　{_link(target, '打开下载页')}")
        self._update_label.setOpenExternalLinks(True)
        self._update_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self._update_label.setVisible(True)

    @staticmethod
    def _deps_text() -> str:
        """运行时获取 pyncm / PySide6 / qtawesome / keyring 版本，缺失标「未安装」。"""
        parts = []
        for module, label in (("pyncm", "pyncm"), ("PySide6", "PySide6"),
                              ("qtawesome", "qtawesome"), ("keyring", "keyring")):
            try:
                mod = __import__(module)
                parts.append(f"{label} {getattr(mod, '__version__', 'unknown')}")
            except Exception:
                parts.append(f"{label} 未安装")
        return "　".join(parts)
