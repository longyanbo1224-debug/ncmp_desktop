"""关于页 —— 这个程序是什么、谁做的、基于什么。

v1.2 起把这一页从"版权信息表"改成一页**能看懂来历**的说明：
先说它是干什么的（一句话），再说它站在谁的肩膀上（上游 + 参考项目），
最后才是版本、依赖、许可这些"查得到但不常看"的东西。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from app.ui import theme
from app.version import GITHUB_REPO, RELEASES_URL, __version__

APP_NAME = "ncmp desktop"
APP_TAGLINE = "在电脑上把音乐合伙人的每日评分跑完，并留下今天的记录。"

APP_DESCRIPTION = (
    "登录你自己的网易云账号，按设定的评分策略给「音乐合伙人」的待评作品打分，"
    "可以同时留下一条简短的批注。支持扫码/密码登录、本地定时与云端触发、"
    "断点补跑与失败分类；今天的曲目、分数和批注会存成本地记录，随时回看或导出。"
)

#: 值得一提的参考来源（放在"致谢"里，写清抄了什么、没抄什么）
REFERENCE_NOTE = (
    "v1.2 的评分环节参考了 Grails125/ncmm：从它那里学到"
    "「把评分当成留下一条批注来做」，并把每天的曲目与批注做成可回看的记录；"
    "没有采用它的多账号并行与 WebUI/Docker 部署形态。"
)

AUTHOR = "Galvin"
GITHUB_URL = f"https://github.com/{GITHUB_REPO}"
GITHUB_LABEL = GITHUB_REPO
UPSTREAM_URL = "https://github.com/ACAne0320/ncmp"
UPSTREAM_LABEL = "ACAne0320/ncmp"
REFERENCE_URL = "https://github.com/Grails125/ncmm"
REFERENCE_LABEL = "Grails125/ncmm"
LICENSE = "YanboLong Non-Commercial License（基于 MIT 修改）"


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

        # 一句话说清它是干什么的：这一行是全页最重要的内容
        tagline = QLabel(APP_TAGLINE)
        tagline.setObjectName("displayStatement")
        tagline.setWordWrap(True)
        tagline.setMaximumWidth(theme.CAPTION_MAX_WIDTH + 120)
        layout.addWidget(tagline)

        layout.addSpacing(theme.SP_3)

        version_row = QLabel(
            f"版本 {__version__}　·　{_link(RELEASES_URL, '更新说明')}")
        version_row.setObjectName("captionText")
        version_row.setOpenExternalLinks(True)
        version_row.setTextInteractionFlags(Qt.TextBrowserInteraction)
        layout.addWidget(version_row)

        # 更新入口：默认隐藏，后台查到新版本才出现（见 set_update_available）
        self._update_label = QLabel("")
        self._update_label.setObjectName("captionText")
        self._update_label.setWordWrap(True)
        self._update_label.setVisible(False)
        layout.addWidget(self._update_label)

        layout.addSpacing(theme.SP_6)

        desc = QLabel(APP_DESCRIPTION)
        desc.setObjectName("subtitle")
        desc.setWordWrap(True)
        desc.setMaximumWidth(theme.CAPTION_MAX_WIDTH)
        layout.addWidget(desc)

        layout.addSpacing(theme.SP_6)

        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SP_5)
        grid.setVerticalSpacing(theme.SP_3)
        grid.setColumnStretch(1, 1)

        rows = [
            ("作者", AUTHOR, False),
            ("上游项目", _link(UPSTREAM_URL, UPSTREAM_LABEL), True),
            ("参考项目", _link(REFERENCE_URL, REFERENCE_LABEL), True),
            ("GitHub", _link(GITHUB_URL, GITHUB_LABEL), True),
            ("核心依赖", self._deps_text(), False),
            ("许可", LICENSE, False),
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

        layout.addSpacing(theme.SP_4)

        note = QLabel(REFERENCE_NOTE)
        note.setObjectName("captionText")
        note.setWordWrap(True)
        note.setMaximumWidth(theme.CAPTION_MAX_WIDTH)
        layout.addWidget(note)

        layout.addSpacing(theme.SP_4)

        disclaimer = QLabel(
            "非官方第三方程序，与网易云音乐无关联；仅供个人学习、研究和技术交流，"
            "使用风险自负。批注会以你自己的身份公开发布，请自行确认内容。")
        disclaimer.setObjectName("captionText")
        disclaimer.setWordWrap(True)
        disclaimer.setMaximumWidth(theme.CAPTION_MAX_WIDTH)
        layout.addWidget(disclaimer)

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
