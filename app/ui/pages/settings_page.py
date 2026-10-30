"""参数配置页 —— 一份文档。

按语义分 6 组。分组**不套卡片**：每组是「小标题 + 一条细线 + 字段」，
字段直接坐在页面底色上。输入框是页面上唯一白的东西，
视线自然落到能改的地方，而不是先扫过六张一模一样的白卡片。

字段对应 ncmp setting.json，gh_token 走 keyring：
    Cookie_MUSIC_U、Cookie___csrf、netease_phone、netease_password、
    netease_md5_password、wait_time_min、wait_time_max、score、
    full_extra_tasks、notify_email、email_password、smtp_server、smtp_port、
    gh_token / gh_repo / notify_email（keyring）、workflow_name、workflow_branch

定时执行字段（AppConfig，不入 setting.json）：
    schedule_enabled、schedule_time（HH:MM）、schedule_mode（local/cloud/both）

分组：
    - 网易云账号：Cookie + 手机号 + 密码（明文/MD5）
    - 任务参数：wait_time_min/max、score、full_extra_tasks
    - 邮件通知：notify_email、email_password、smtp_server、smtp_port
    - 定时执行：启用开关 + 触发时间 + 模式（本地/云端/两者）
    - GitHub Actions（云端执行）：gh_token、gh_repo、workflow_name、workflow_branch
      + cron 同步按钮 + Cookie 同步到 Secrets 按钮
"""
import hashlib
import json
from typing import Any, Dict, Optional, Tuple

from PySide6.QtCore import QPoint, QSize, Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from app.app_config import AppConfig
from app.cloud.actions_trigger import ActionsTrigger
from app.cookie_store import CookieStore
from app.ui import dialogs, theme
from app.ui.icons import eye_icon
from app.workers.cookie_check_worker import CookieCheckWorker
from core.utils.config import Config
from core.utils.logger import Logger
from core.utils.notification import NotificationService


# 表单字段名清单
SETTINGS_FIELDS = (
    "Cookie_MUSIC_U",
    "Cookie___csrf",
    "netease_phone",
    "netease_password",
    "netease_md5_password",
    "wait_time_min",
    "wait_time_max",
    "score",
    "full_extra_tasks",
    "note_enabled",
    "note_voice",
    "note_length",
    "notify_email",
    "email_password",
    "smtp_server",
    "smtp_port",
    "notify_on_task_done",
    "notify_on_cookie_expired",
    "notify_on_schedule",
    "gh_token",
    "gh_repo",
    "workflow_name",
    "workflow_branch",
    "gh_disable_schedule",
    "gh_random_delay_minutes",
    "gh_success_email",
)

# 首次使用 / Config 加载失败时的默认值（与 core.utils.config._apply_defaults 对齐）
DEFAULTS: Dict[str, Any] = {
    "Cookie_MUSIC_U": "",
    "Cookie___csrf": "",
    "netease_phone": "",
    "netease_password": "",
    "netease_md5_password": "",
    "wait_time_min": 15,
    "wait_time_max": 20,
    "score": 3,
    "full_extra_tasks": True,
    "note_enabled": True,
    "note_voice": "restrained",
    "note_length": "standard",
    "notify_email": "",
    "email_password": "",
    "smtp_server": "smtp.qq.com",
    "smtp_port": 465,
    "notify_on_task_done": True,
    "notify_on_cookie_expired": True,
    "notify_on_schedule": True,
    "gh_token": "",
    "gh_repo": "",
    "workflow_name": "refresh_cookie.yml",
    "workflow_branch": "main",
    "gh_disable_schedule": False,
    "gh_random_delay_minutes": 0,
    "gh_success_email": False,
}

# keyring 服务名（与 CookieStore / Config 对齐，gh_token 用同一服务下的独立 key）
_KEYRING_SERVICE = "ncmp desktop"

class _DownCombo(QComboBox):
    """下拉列表固定向下展开。

    QComboBox 默认按剩余空间决定方向，界面里常出现"点一下从上面弹出来"。
    弹窗显示后把它移到控件正下方即可。
    """

    def showPopup(self) -> None:  # noqa: N802
        # 短列表一次全部展开（不留滚动条）；长列表按屏幕高度截断后滚动。
        # 高度必须自己按行高算：QComboBox 弹层在设置 maxVisibleItems 之后
        # sizeHint 不可靠，直接用它会把列表压成一条缝，选项看不见。
        self.setMaxVisibleItems(max(1, self.count()))
        super().showPopup()
        try:
            popup = self.view().window()
            anchor = self.mapToGlobal(QPoint(0, self.height()))
            width = max(popup.width(), self.width())
            screen = self.screen()
            area = screen.availableGeometry() if screen is not None else None
            if area is None:
                popup.move(anchor)
                return
            row = self.view().sizeHintForRow(0)
            if row <= 0:
                row = 24
            visible = max(1, (area.height() - 24) // row)
            visible = min(visible, self.count())
            height = row * visible + 8      # 上下各留一点边框
            y = anchor.y()
            if y + height > area.bottom():
                y = max(area.top() + 12, area.bottom() - height)
            popup.setGeometry(anchor.x(), y, width, height)
        except Exception:
            pass


# 每个字段的提示文本（placeholder）与悬停说明（tooltip）
FIELD_HINTS: Dict[str, Dict[str, str]] = {
    "Cookie_MUSIC_U": {
        "placeholder": "由登录流程自动写入，无需手动填写",
        "tooltip": "网易云音乐 Cookie 中的 MUSIC_U，扫码/密码登录成功后自动填充。",
    },
    "Cookie___csrf": {
        "placeholder": "由登录流程自动写入，无需手动填写",
        "tooltip": "网易云音乐 Cookie 中的 __csrf，登录成功后自动填充。",
    },
    "netease_phone": {
        "placeholder": "11 位手机号，如 13800138000",
        "tooltip": "用于密码登录的网易云音乐账号手机号（仅密码登录需要，扫码登录可不填）。",
    },
    "netease_password": {
        "placeholder": "明文密码（二选一，登录后不保存）",
        "tooltip": "明文密码，仅用于本次登录；登录成功后建议用「→ MD5」转为 MD5 保存。",
    },
    "netease_md5_password": {
        "placeholder": "MD5 密码（推荐，更安全）",
        "tooltip": "明文密码的 MD5 值，可用「→ MD5」按钮由明文生成；与明文二选一。",
    },
    "wait_time_min": {
        "tooltip": "每次评分之间等待的最小秒数（默认 15），避免触发风控。",
    },
    "wait_time_max": {
        "tooltip": "每次评分之间等待的最大秒数（默认 20），实际等待在 min~max 间随机。",
    },
    "score": {
        "tooltip": "评分策略：1=1-2 分，2=2-3 分，3=3-4 分（默认），4=固定 4 分。",
    },
    "full_extra_tasks": {
        "tooltip": "勾选后完成所有额外任务，而非只完成固定加分的 7 个。",
    },
    "note_enabled": {
        "tooltip": (
            "勾选后，评分时同时提交一条批注（乐评短句）。\n"
            "批注会公开显示在你的账号下，可在「记录」里回看每一条。"),
    },
    "note_voice": {
        "tooltip": (
            "批注的语气。三套语料都是本地内置的，不联网、不调用 AI：\n"
            "克制=有话但不煽情（默认）；热络=情绪更外露；简短=一句话说完。"),
    },
    "note_length": {
        "tooltip": (
            "批注长度。三档都会真正影响句子长度：\n"
            "简短 ≤40 字（可能丢掉收尾句）；标准 ≤80 字；\n"
            "详细 ≈60–120 字（多写一句判断）。"),
    },
    "notify_email": {
        "placeholder": "接收任务结果通知的邮箱",
        "tooltip": "任务完成/失败时发邮件通知到此邮箱（可选，留空则不发邮件）。",
    },
    "email_password": {
        "placeholder": "邮箱授权码（非登录密码）",
        "tooltip": "SMTP 授权码，如 Gmail 的「应用专用密码」、QQ/163 邮箱的授权码。",
    },
    "smtp_server": {
        "tooltip": "SMTP 服务器地址，预设 QQ/Gmail/163，也可手动输入其他。",
    },
    "smtp_port": {
        "tooltip": "SMTP 端口，SSL 通常 465（默认），TLS 为 587。",
    },
    "notify_on_task_done": {
        "tooltip": (
            "勾选后，手动执行的任务完成/失败/取消时发邮件通知。\n"
            "成功：ncmp 任务完成；失败：ncmp 任务失败；取消：ncmp 任务已取消。"
        ),
    },
    "notify_on_cookie_expired": {
        "tooltip": (
            "勾选后，后台 Cookie 验证发现 Cookie 失效时发邮件通知\n"
            "（Cookie 不存在 / 用户信息无效 / 任务权限失败等场景）。"
        ),
    },
    "notify_on_schedule": {
        "tooltip": (
            "勾选后，定时执行（schedule_mode=local/both）的任务结果通过邮件通知，\n"
            "独立于「任务执行完成时邮件通知」开关——定时执行只看这个开关。"
        ),
    },
    "gh_token": {
        "placeholder": "ghp_xxx（GitHub Personal Access Token）",
        "tooltip": (
            "GitHub Personal Access Token，需 repo + workflow 权限。\n"
            "获取步骤：\n"
            "1. 登录 GitHub → 右上头像 → Settings\n"
            "2. 左侧最底 Developer settings → Personal access tokens → Tokens (classic)\n"
            "3. Generate new token (classic)\n"
            "4. 勾选 repo（全选）+ workflow\n"
            "5. Generate → 复制 token（只显示一次，丢失需重新生成）\n"
            "仅本地 keyring 保存，不上传。"
        ),
    },
    "gh_repo": {
        "placeholder": "如 yourname/ncmp（或完整 URL）",
        "tooltip": (
            "GitHub 仓库全名（owner/repo）。\n"
            "获取步骤：\n"
            "1. fork ncmp 仓库到自己账号：github.com/ACAne0320/ncmp → 右上 Fork\n"
            "2. fork 后仓库 URL：github.com/你的用户名/ncmp\n"
            "3. 填「你的用户名/ncmp」（如 longyanbo1224/ncmp）\n"
            "也可填完整 URL，程序自动提取 owner/repo。"
        ),
    },
    "workflow_name": {
        "placeholder": "refresh_cookie.yml",
        "tooltip": (
            "要触发的 workflow 文件名（.github/workflows/ 下的 yml 文件名）。\n"
            "获取步骤：\n"
            "1. 把本项目 resources/workflow_example.yml 内容复制\n"
            "2. 到 fork 仓库新建 .github/workflows/refresh_cookie.yml 粘贴\n"
            "3. 文件名填 refresh_cookie.yml"
        ),
    },
    "workflow_branch": {
        "placeholder": "main",
        "tooltip": (
            "触发 workflow 的分支名。\n"
            "获取：fork 后默认 main（老仓库可能 master），\n"
            "看 fork 仓库主页左上分支选择器。"
        ),
    },
}




class _GitHubActionWorker(QThread):
    """后台执行一次 GitHub API 调用，避免网络等待卡住 UI。"""

    result_ready = Signal(bool, str)

    def __init__(self, fn, parent=None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            ok, msg = self._fn()
        except Exception as e:
            ok, msg = False, f"异常：{e}"
        self.result_ready.emit(ok, msg)


class SettingsPage(QWidget):
    """参数配置表单。"""

    # 定时配置保存后通知主窗口重排定时器
    schedule_config_changed = Signal()
    close_action_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._controls: Dict[str, Any] = {}
        self._gh_worker: Optional[_GitHubActionWorker] = None
        self._loading_controls = False
        # 业务字段走 Config；定时字段走 AppConfig（独立文件，不入 setting.json）
        self._app_config = AppConfig()
        self._build_ui()
        self.load_from_config()
        self._load_schedule_config()
        self._load_close_action_config()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.PAGE_MARGIN, theme.PAGE_MARGIN,
                                 theme.PAGE_MARGIN, theme.SP_2)
        outer.setSpacing(0)

        title = QLabel("参数配置")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        outer.addSpacing(theme.SP_2)

        subtitle = QLabel("默认值已预填，按需修改后点「保存」。鼠标悬停字段可见说明。")
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        outer.addSpacing(theme.SP_4)

        # 设置项太多，一屏滚不完，按"你要改的是哪一类事"分页签。
        # 每个页签自己是一个纵向布局，_new_section 往 self._sections 里追加，
        # 所以建某一页之前先把 self._sections 指向那一页的布局。
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        outer.addWidget(self._tabs, 1)
        self._pages: Dict[str, QVBoxLayout] = {}

        for key, label in (("account", "账号"), ("task", "任务"),
                           ("notify", "通知"), ("auto", "自动化"),
                           ("general", "通用")):
            # 每个页签各自滚动：以前整页共用一个滚动区，短页也会出现滚动条，
            # 长页（自动化）还会被底部按钮栏裁掉一截。
            page = QWidget()
            page_lay = QVBoxLayout(page)
            page_lay.setContentsMargins(0, 0, 0, 0)
            page_lay.setSpacing(0)
            inner = QWidget()
            layout = QVBoxLayout(inner)
            layout.setContentsMargins(0, theme.SP_4, 0, theme.SP_4)
            layout.setSpacing(theme.GROUP_GAP)
            scroller = QScrollArea()
            scroller.setWidgetResizable(True)
            scroller.setFrameShape(QScrollArea.NoFrame)
            scroller.setWidget(inner)
            page_lay.addWidget(scroller)
            self._tabs.addTab(page, label)
            self._pages[key] = layout

        def build(key: str, *builders) -> None:
            """在某一页里建若干个分组，建完补一个弹簧把它顶到上方。"""
            self._sections = self._pages[key]
            for builder in builders:
                builder()
            self._sections.addStretch(1)

        build("account", self._build_account_section)
        build("task", self._build_task_section, self._build_note_section)
        build("notify", self._build_email_section)
        build("auto", self._build_schedule_section, self._build_github_section)
        build("general", self._build_general_section)
        self._sections = None

        # 操作按钮。原顶部还有一个「明文 → MD5」，和密码字段行内的那个
        # 功能完全重复（都调 hashlib.md5 写 netease_md5_password），已删。
        buttons = QHBoxLayout()
        buttons.setSpacing(theme.SP_2)
        save_btn = QPushButton("保存")
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self.save)
        test_btn = QPushButton("测试通知")
        test_btn.setObjectName("secondaryButton")
        test_btn.clicked.connect(self.test_notification)
        validate_btn = QPushButton("验证 Cookie")
        validate_btn.setObjectName("secondaryButton")
        validate_btn.clicked.connect(self.validate_cookie)
        import_btn = QPushButton("导入 setting.json")
        import_btn.setObjectName("secondaryButton")
        import_btn.clicked.connect(self.import_setting_json)
        export_btn = QPushButton("导出 setting.json")
        export_btn.setObjectName("secondaryButton")
        export_btn.clicked.connect(self.export_setting_json)
        for b in (save_btn, test_btn, validate_btn, import_btn, export_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)

        # 操作按钮**固定在页面底部**，不跟着内容滚动。
        # 分页签之后内容变高，保存按钮被推到很下面，得滚半天才找得到。
        bar = QWidget()
        bar_lay = QVBoxLayout(bar)
        bar_lay.setContentsMargins(theme.PAGE_MARGIN, theme.SP_2,
                                   theme.PAGE_MARGIN, theme.PAGE_MARGIN)
        bar_lay.setSpacing(0)
        rule = QFrame()
        rule.setObjectName("rule")
        bar_lay.addWidget(rule)
        bar_lay.addSpacing(theme.SP_2)
        bar_lay.addLayout(buttons)
        outer.addWidget(bar)

    def _new_section(self, title: str, intro: str = "") -> QFormLayout:
        """建一个分组：小标题 + 一条细线 + 字段。

        **不套卡片。** 字段直接坐在页面底色上，只有输入框是白的。
        :param intro: 可选的说明段落，放在细线下方、字段上方。
        :returns: 该分组的 QFormLayout，调用方往里 addRow。
        """
        container = QWidget()
        box = QVBoxLayout(container)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)

        heading = QLabel(title)
        heading.setObjectName("sectionHeading")
        box.addWidget(heading)

        box.addSpacing(theme.SP_2)

        rule = QFrame()
        rule.setObjectName("rule")
        box.addWidget(rule)

        box.addSpacing(theme.SP_4)

        if intro:
            caption = QLabel(intro)
            caption.setObjectName("captionText")
            caption.setWordWrap(True)
            caption.setMaximumWidth(theme.CAPTION_MAX_WIDTH)
            box.addWidget(caption)
            box.addSpacing(theme.SP_4)

        form_host = QWidget()
        # 限宽：输入框横跨整个窗口时一行能放 60 多个汉字，眼睛要来回扫。
        #
        # 注意必须给 form_host 一个**最小宽度**：外层容器加了 Qt.AlignLeft 之后
        # 只会取 sizeHint，而 QFormLayout 的 sizeHint 就是输入框的自然宽度，
        # 结果字段反而缩到 277px。撑住最小宽度，字段才会跟着展开。
        form_host.setMinimumWidth(theme.FORM_MAX_WIDTH - 60)
        form = QFormLayout(form_host)
        form.setContentsMargins(0, 0, 0, 0)
        # 标签压在字段上方（与手机端一致）。两列式"标签 | 输入框"更像后台管理系统，
        # 堆叠更像"设置项"，也和手机端的分组骨架对得上。
        form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        # 所有字段拉满同一列宽：不设的话，下拉/数字框会按自身 sizeHint 收窄，
        # 一列输入框长短不一。
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        form.setHorizontalSpacing(theme.SP_3)
        form.setVerticalSpacing(theme.SP_2)
        box.addWidget(form_host)

        container.setMaximumWidth(theme.FORM_MAX_WIDTH)
        self._sections.addWidget(container, 0, Qt.AlignLeft)
        # 供 _build_github_section 这类需要在表单外追加整行控件的分组使用
        self._current_section_box = box
        return form

    def _build_account_section(self) -> None:
        form = self._new_section("网易云账号")

        # Cookie_MUSIC_U（只读 + 眼睛切换显隐，由登录流程自动写入）
        cookie_mu_row = self._build_password_row("Cookie_MUSIC_U", read_only=True)
        form.addRow("Cookie_MUSIC_U", cookie_mu_row)
        self._controls["Cookie_MUSIC_U"] = cookie_mu_row.findChild(QLineEdit, "pwdEdit")

        # Cookie___csrf（只读 + 眼睛切换显隐）
        cookie_csrf_row = self._build_password_row("Cookie___csrf", read_only=True)
        form.addRow("Cookie___csrf", cookie_csrf_row)
        self._controls["Cookie___csrf"] = cookie_csrf_row.findChild(QLineEdit, "pwdEdit")

        # netease_phone
        phone_edit = QLineEdit()
        self._apply_hint(phone_edit, "netease_phone")
        form.addRow("netease_phone", phone_edit)
        self._controls["netease_phone"] = phone_edit

        # netease_password（明文 + → MD5）
        pwd_row = self._build_password_row(
            "netease_password", with_md5_button_target="netease_md5_password")
        form.addRow("netease_password", pwd_row)
        self._controls["netease_password"] = pwd_row.findChild(QLineEdit, "pwdEdit")

        # netease_md5_password
        md5_row = self._build_password_row("netease_md5_password")
        form.addRow("netease_md5_password", md5_row)
        self._controls["netease_md5_password"] = md5_row.findChild(QLineEdit, "pwdEdit")

    def _build_task_section(self) -> None:
        form = self._new_section("任务参数")

        # wait_time_min
        wait_min = QSpinBox()
        wait_min.setRange(0, 3600)
        wait_min.setSuffix(" 秒")
        wait_min.setValue(DEFAULTS["wait_time_min"])
        self._apply_hint(wait_min, "wait_time_min")
        form.addRow("wait_time_min", wait_min)
        self._controls["wait_time_min"] = wait_min

        # wait_time_max
        wait_max = QSpinBox()
        wait_max.setRange(0, 3600)
        wait_max.setSuffix(" 秒")
        wait_max.setValue(DEFAULTS["wait_time_max"])
        self._apply_hint(wait_max, "wait_time_max")
        form.addRow("wait_time_max", wait_max)
        self._controls["wait_time_max"] = wait_max

        # score
        score = _DownCombo()
        score.addItem("1-2 (策略 1)", 1)
        score.addItem("2-3 (策略 2)", 2)
        score.addItem("3-4 (策略 3，默认)", 3)
        score.addItem("固定 4 (策略 4)", 4)
        score.setCurrentIndex(2)  # 默认策略 3
        self._apply_hint(score, "score")
        form.addRow("score", score)
        self._controls["score"] = score

        # full_extra_tasks
        full_extra = QCheckBox("完成所有额外任务（忽略每日 7 个上限）")
        self._apply_hint(full_extra, "full_extra_tasks")
        form.addRow("full_extra_tasks", full_extra)
        self._controls["full_extra_tasks"] = full_extra

    def _build_note_section(self) -> None:
        """批注（乐评文案）：开关、语气、字数上限。"""
        form = self._new_section(
            "批注",
            "评分时可以同时留一句话。三种语气都是本地内置的，不联网、不调用 AI，"
            "同一首歌每次生成的都是同一句。")

        note_enabled = QCheckBox("评分时同时提交批注")
        self._apply_hint(note_enabled, "note_enabled")
        form.addRow("note_enabled", note_enabled)
        self._controls["note_enabled"] = note_enabled

        note_voice = _DownCombo()
        note_voice.addItem("克制", "restrained")
        note_voice.addItem("热络", "warm")
        note_voice.addItem("简短", "brief")
        note_voice.setCurrentIndex(0)
        self._apply_hint(note_voice, "note_voice")
        form.addRow("note_voice", note_voice)
        self._controls["note_voice"] = note_voice

        note_length = _DownCombo()
        note_length.addItem("简短（≤40 字）", "brief")
        note_length.addItem("标准（≤80 字）", "standard")
        note_length.addItem("详细（60–120 字）", "detailed")
        self._apply_hint(note_length, "note_length")
        form.addRow("note_length", note_length)
        self._controls["note_length"] = note_length

    def _build_email_section(self) -> None:
        form = self._new_section("邮件通知")

        # notify_email
        notify_email = QLineEdit()
        self._apply_hint(notify_email, "notify_email")
        form.addRow("notify_email", notify_email)
        self._controls["notify_email"] = notify_email

        # email_password
        email_pwd_row = self._build_password_row("email_password")
        form.addRow("email_password", email_pwd_row)
        self._controls["email_password"] = email_pwd_row.findChild(QLineEdit, "pwdEdit")

        # smtp_server（可编辑下拉，预设常用 SMTP 服务器）
        smtp_server = _DownCombo()
        smtp_server.setEditable(False)
        smtp_server.addItem("smtp.qq.com")
        smtp_server.addItem("smtp.gmail.com")
        smtp_server.addItem("smtp.163.com")
        smtp_server.addItem("smtp.outlook.com")
        smtp_server.addItem("smtp.126.com")
        smtp_server.setCurrentText(DEFAULTS["smtp_server"])
        self._apply_hint(smtp_server, "smtp_server")
        form.addRow("smtp_server", smtp_server)
        self._controls["smtp_server"] = smtp_server

        # smtp_port
        smtp_port = QSpinBox()
        smtp_port.setRange(1, 65535)
        smtp_port.setValue(DEFAULTS["smtp_port"])
        self._apply_hint(smtp_port, "smtp_port")
        form.addRow("smtp_port", smtp_port)
        self._controls["smtp_port"] = smtp_port

        # 邮件通知开关（默认勾选）
        notify_task_done = QCheckBox("任务执行完成时邮件通知")
        self._apply_hint(notify_task_done, "notify_on_task_done")
        notify_task_done.setChecked(DEFAULTS["notify_on_task_done"])
        form.addRow("完成通知", notify_task_done)
        self._controls["notify_on_task_done"] = notify_task_done
        notify_task_done.toggled.connect(
            lambda _checked: self._save_notify_options())

        notify_cookie_expired = QCheckBox("Cookie 失效时邮件通知")
        self._apply_hint(notify_cookie_expired, "notify_on_cookie_expired")
        notify_cookie_expired.setChecked(DEFAULTS["notify_on_cookie_expired"])
        form.addRow("失效通知", notify_cookie_expired)
        self._controls["notify_on_cookie_expired"] = notify_cookie_expired
        notify_cookie_expired.toggled.connect(
            lambda _checked: self._save_notify_options())

        notify_schedule = QCheckBox("定时执行结果邮件通知")
        self._apply_hint(notify_schedule, "notify_on_schedule")
        notify_schedule.setChecked(DEFAULTS["notify_on_schedule"])
        form.addRow("定时通知", notify_schedule)
        self._controls["notify_on_schedule"] = notify_schedule
        notify_schedule.toggled.connect(
            lambda _checked: self._save_notify_options())

    def _build_general_section(self) -> None:
        """应用自身行为配置（写入 AppConfig，不入 setting.json）。"""
        form = self._new_section("常规")

        close_combo = _DownCombo()
        close_combo.addItem("每次询问", "ask")
        close_combo.addItem("最小化到托盘", "minimize")
        close_combo.addItem("直接退出", "close")
        close_combo.setCurrentIndex(0)
        close_combo.setToolTip(
            "点击关闭按钮时的行为：每次询问 / 最小化到托盘后台运行 / 直接退出程序。")
        form.addRow("关闭按钮行为", close_combo)
        self._close_action_combo = close_combo

        # 日志文件夹入口。日志按天滚动保留 7 天，出问题时用户得能找到它。
        log_row = QWidget()
        log_lay = QHBoxLayout(log_row)
        log_lay.setContentsMargins(0, 0, 0, 0)
        log_lay.setSpacing(theme.SP_2)
        log_btn = QPushButton("打开日志文件夹")
        log_btn.setObjectName("secondaryButton")
        log_btn.setToolTip(
            "日志按天滚动，保留最近 7 天。反馈问题时把这个文件夹里的日志附上即可。")
        log_btn.clicked.connect(self._open_log_dir)
        log_lay.addWidget(log_btn)
        log_lay.addStretch(1)
        form.addRow("运行日志", log_row)

    @staticmethod
    def _open_log_dir() -> None:
        """打开日志文件夹；打不开就把路径告诉用户，别只说一句失败。"""
        from app.logging_setup import log_dir, open_log_dir
        if open_log_dir():
            return
        try:
            path = str(log_dir())
        except Exception:
            path = "（无法解析日志目录）"
        dialogs.info(None, "运行日志", f"未能自动打开，请手动前往：\n{path}")

    def _build_schedule_section(self) -> None:
        """定时执行配置（写入 AppConfig，不入 setting.json）。"""
        form = self._new_section("定时执行")

        # 启用开关
        enable_box = QCheckBox("启用定时执行（到点自动触发本地任务/云端 Actions）")
        enable_box.setToolTip(
            "勾选后到点自动按模式触发任务；本地模式要求程序在运行，云端模式由 GitHub Actions 跑（电脑关机也能跑）。")
        form.addRow("启用", enable_box)
        self._schedule_enable_box = enable_box

        # 触发时间（24 小时制）：时/分两个下拉。QTimeEdit 的上下箭头在
        # 这个尺寸下画得很脏，而且和其他下拉框不是一套外观。
        time_row, self._schedule_hour_combo, self._schedule_minute_combo = \
            self._build_time_row(9, 0)
        time_row.setToolTip("触发时间（24 小时制），默认 09:00。")
        form.addRow("触发时间", time_row)

        # 模式
        mode_combo = _DownCombo()
        mode_combo.addItem("本地（启动 TaskWorker）", "local")
        mode_combo.addItem("云端（触发 GitHub Actions）", "cloud")
        mode_combo.addItem("两者（本地 + 云端都启动）", "both")
        mode_combo.setCurrentIndex(0)
        mode_combo.setToolTip(
            "local=本地跑任务（程序需运行）；cloud=GitHub Actions 跑（关机也跑）；both=两者都启动。")
        form.addRow("模式", mode_combo)
        self._schedule_mode_combo = mode_combo

        # 本地随机延迟。固定整点执行本身就是个风控特征，
        # 云端早有 RANDOM_DELAY_MINUTES，本地一直缺。
        delay_spin = QSpinBox()
        delay_spin.setRange(0, 30)
        delay_spin.setSuffix(" 分钟")
        delay_spin.setSpecialValueText("不启用")
        delay_spin.setToolTip(
            "0=不启用。设为 N 分钟后，本地定时任务会在到点后的 0~N 分钟内随机时刻启动，\n"
            "避免每天都在同一秒发起请求——固定整点本身就是个风控特征。\n"
            "云端执行有独立的随机延迟设置，见 GitHub Actions 分组。")
        form.addRow("本地随机延迟", delay_spin)
        self._schedule_delay_spin = delay_spin

        # 错过补跑
        catchup_box = QCheckBox("错过补跑（启动时如果今天还没跑，自动补一次）")
        catchup_box.setToolTip(
            "定时设了 09:00，但电脑 09:30 才开机——默认今天就这么无声无息地没了。\n"
            "勾选后启动时会检查「今天该跑但还没跑」，自动补一次并弹通知。\n"
            "限制：只补当天（不追溯更早），每天最多补一次，且只对本地模式生效。")
        form.addRow("错过补跑", catchup_box)
        self._schedule_catchup_box = catchup_box

        deadline_row, self._schedule_deadline_hour, self._schedule_deadline_minute = \
            self._build_time_row(23, 0)
        deadline_row.setToolTip(
            "补跑的截止时间，默认 23:00。过了这个点就不再补——\n"
            "离第二天的定时时间太近，跑完紧接着又跑一次，同样是个风控特征。")
        form.addRow("补跑截止", deadline_row)

    def _build_github_section(self) -> None:
        intro = (
            "配置后可在任务页选云端执行，触发 GitHub Actions 跑任务（电脑关机也能跑）。\n"
            "配置步骤：\n"
            "1. fork ncmp 仓库：github.com/ACAne0320/ncmp → 右上 Fork\n"
            "2. 把 resources/workflow_example.yml 复制到 fork 仓库 .github/workflows/refresh_cookie.yml\n"
            "3. 生成 GitHub PAT（头像 → Settings → Developer settings → Personal access tokens → 勾 repo+workflow）\n"
            "4. 下方填 gh_token / gh_repo / workflow_name / workflow_branch → 点「保存」\n"
            "5. 点「测试连接」验证；点「同步 Cookie、邮件和任务参数到 GitHub Secrets」把本地 Cookie、邮件和任务开关写到仓库\n"
            "鼠标悬停各字段可见详细获取说明。"
        )
        form = self._new_section("GitHub Actions（云端执行）", intro)
        # 表单之后的整行控件（同步按钮、云端定时开关等）都追加到这个竖排盒子里
        group_v = self._current_section_box
        group_v.addSpacing(theme.SP_4)

        # gh_token（密码模式 + 显隐）
        gh_token_row = self._build_password_row("gh_token")
        form.addRow("gh_token", gh_token_row)
        self._controls["gh_token"] = gh_token_row.findChild(QLineEdit, "pwdEdit")

        # gh_repo
        gh_repo = QLineEdit()
        self._apply_hint(gh_repo, "gh_repo")
        form.addRow("gh_repo", gh_repo)
        self._controls["gh_repo"] = gh_repo

        # workflow_name
        workflow_name = QLineEdit()
        self._apply_hint(workflow_name, "workflow_name")
        form.addRow("workflow_name", workflow_name)
        self._controls["workflow_name"] = workflow_name

        # workflow_branch
        workflow_branch = QLineEdit()
        self._apply_hint(workflow_branch, "workflow_branch")
        form.addRow("workflow_branch", workflow_branch)
        self._controls["workflow_branch"] = workflow_branch

        # 测试连接 + 结果行
        test_row = QHBoxLayout()
        test_row.setSpacing(8)
        test_btn = QPushButton("测试连接")
        test_btn.setObjectName("secondaryButton")
        test_btn.clicked.connect(self._test_github_connection)
        self._gh_test_btn = test_btn
        test_row.addWidget(test_btn)
        test_row.addStretch(1)
        self._gh_result_label = QLabel("")
        self._gh_result_label.setWordWrap(True)
        test_row.addWidget(self._gh_result_label, 1)
        group_v.addLayout(test_row)

        # 云端 cron 表达式（不存本地，每次改 workflow 即同步）
        cron_row = QHBoxLayout()
        cron_row.setSpacing(8)
        cron_label = QLabel("云端 cron")
        cron_label.setToolTip(
            "GitHub Actions schedule cron 表达式（5 段：分 时 日 月 周），如 \"0 9 * * *\" 每天 9:00 UTC。\n"
            "不保存到本地，每次点「同步 cron」直接修改 fork 仓库的 workflow 文件。")
        cron_row.addWidget(cron_label)
        cron_time_row, self._gh_cron_hour_combo, self._gh_cron_minute_combo = \
            self._build_time_row(9, 0)
        cron_time_row.setToolTip(
            "北京时间触发时间。点「同步 cron」时自动转 UTC（北京 -8）写入 GitHub Actions cron。\n"
            "关机也会跑：GitHub 云端定时，不依赖桌面程序在线。")
        cron_row.addWidget(cron_time_row, 1)
        sync_cron_btn = QPushButton("同步 cron")
        sync_cron_btn.setObjectName("secondaryButton")
        sync_cron_btn.clicked.connect(self._sync_cron_to_workflow)
        self._gh_cron_btn = sync_cron_btn
        cron_row.addWidget(sync_cron_btn)
        group_v.addLayout(cron_row)

        # Cookie 同步到 GitHub Secrets 按钮
        cookie_row = QHBoxLayout()
        cookie_row.setSpacing(8)
        cookie_row.addStretch(0)
        sync_cookie_btn = QPushButton("同步 Cookie、邮件和任务参数到 GitHub Secrets")
        sync_cookie_btn.setObjectName("secondaryButton")
        sync_cookie_btn.setToolTip(
            "把本地配置加密写入 GitHub Actions Secrets：\n"
            "  1. Cookie：MUSIC_U → Cookie_MUSIC_U\n"
            "  2. Cookie：__csrf → Cookie___csrf\n"
            "  3. 邮件通知：NOTIFY_EMAIL / EMAIL_PASSWORD / SMTP_SERVER / SMTP_PORT\n"
            "  4. 完成所有额外任务开关 → FULL_EXTRA_TASKS（true/false）\n"
            "怎么选：\n"
            "  · 改了 Cookie 或邮箱授权码 → 点这里（只写 Secrets，不用重写 workflow 文件）。\n"
            "  · 改了 cron / 定时 / 成功邮件开关 → 点上方「同步完整 workflow」。\n"
            "需先填 gh_token/gh_repo。")
        sync_cookie_btn.clicked.connect(self._sync_cookies_to_github)
        self._gh_cookie_btn = sync_cookie_btn
        cookie_row.addWidget(sync_cookie_btn)
        cookie_row.addStretch(1)
        group_v.addLayout(cookie_row)

        # 同步完整 workflow 按钮（一键覆盖 fork 仓库的 workflow 文件）
        wf_row = QHBoxLayout()
        wf_row.setSpacing(8)
        wf_row.addStretch(0)
        sync_wf_btn = QPushButton("同步完整 workflow")
        sync_wf_btn.setObjectName("secondaryButton")
        sync_wf_btn.setToolTip(
            "把桌面程序自带的 workflow 模板（resources/workflow_example.yml）\n"
            "完整覆盖到 fork 仓库的 .github/workflows/{workflow_name}。\n"
            "按当前设置写入：\n"
            "  1. 云端 cron：北京时间转 UTC 后写入 schedule\n"
            "  2. 云端定时：选择「关闭」则注释 schedule 块\n"
            "  3. 随机延迟启动：写入 RANDOM_DELAY_MINUTES 默认值\n"
            "  4. 成功邮件通知：写入 SEND_SUCCESS_EMAIL 默认值\n"
            "怎么选：\n"
            "  · 改了 cron / 定时 / 成功邮件开关 → 点这里（只改 workflow 文件，不写 Secrets）。\n"
            "  · 改了 Cookie 或邮箱授权码 → 点下方「同步 Cookie、邮件和任务参数到 GitHub Secrets」。\n"
            "需先填 gh_token/gh_repo/workflow_name/branch。")
        sync_wf_btn.clicked.connect(self._sync_full_workflow)
        self._gh_wf_btn = sync_wf_btn
        wf_row.addWidget(sync_wf_btn)
        wf_row.addStretch(1)
        group_v.addLayout(wf_row)

        all_row = QHBoxLayout()
        all_row.setSpacing(8)
        all_row.addStretch(0)
        sync_all_btn = QPushButton("一键同步全部")
        sync_all_btn.setObjectName("secondaryButton")
        sync_all_btn.setToolTip(
            "按当前设置依次执行：同步完整 workflow → 同步 Cookie → 同步邮件 → 同步任务参数。\n"
            "任一步失败会停止并提示。\n"
            "什么时候点这里：想一次把所有设置都同步到 GitHub。\n"
            "需先填 gh_token/gh_repo/workflow_name/branch，并已登录保存本地 Cookie。")
        sync_all_btn.clicked.connect(self._sync_all_to_github)
        self._gh_all_btn = sync_all_btn
        all_row.addWidget(sync_all_btn)
        all_row.addStretch(1)
        group_v.addLayout(all_row)

        # 云端定时：像随机延迟一样用“标签 + 选择框”，不再用长文案勾选框
        schedule_switch_row = QHBoxLayout()
        schedule_switch_row.setSpacing(8)
        schedule_label = QLabel("云端定时")
        schedule_label.setFixedWidth(96)
        schedule_label.setToolTip(
            "选择「关闭」后点「同步完整 workflow」，会把 workflow 的 schedule 块注释掉。\n"
            "GitHub 将不再按 cron 自动执行，但「云端执行」手动触发仍可用。")
        schedule_switch_row.addWidget(schedule_label)
        self._gh_disable_schedule_combo = _DownCombo()
        self._gh_disable_schedule_combo.addItem("启用", False)
        self._gh_disable_schedule_combo.addItem("关闭", True)
        self._gh_disable_schedule_combo.setToolTip(schedule_label.toolTip())
        self._controls["gh_disable_schedule"] = self._gh_disable_schedule_combo
        self._gh_disable_schedule_combo.currentIndexChanged.connect(
            lambda _index: self._save_gh_workflow_options())
        schedule_switch_row.addWidget(self._gh_disable_schedule_combo, 1)
        group_v.addLayout(schedule_switch_row)

        # 成功邮件通知：同样改成下拉选择「开启 / 关闭」
        success_email_row = QHBoxLayout()
        success_email_row.setSpacing(8)
        success_email_label = QLabel("成功邮件通知")
        success_email_label.setFixedWidth(96)
        success_email_label.setToolTip(
            "选择「开启」后点「同步完整 workflow」，workflow 会在任务成功时也发送邮件到 NOTIFY_EMAIL。\n"
            "选择「关闭」则只在任务失败时发送失败邮件。")
        success_email_row.addWidget(success_email_label)
        self._gh_success_email_combo = _DownCombo()
        self._gh_success_email_combo.addItem("关闭", False)
        self._gh_success_email_combo.addItem("开启", True)
        self._gh_success_email_combo.setToolTip(success_email_label.toolTip())
        self._controls["gh_success_email"] = self._gh_success_email_combo
        self._gh_success_email_combo.currentIndexChanged.connect(
            lambda _index: self._save_gh_workflow_options())
        success_email_row.addWidget(self._gh_success_email_combo, 1)
        group_v.addLayout(success_email_row)

        # 随机延迟启动：0=不启用；N=「同步完整 workflow」时把 0–N 分钟随机延迟写入 workflow
        delay_row = QHBoxLayout()
        delay_row.setSpacing(8)
        delay_label = QLabel("随机延迟启动")
        delay_label.setFixedWidth(96)
        delay_label.setToolTip(
            "0=不启用。设为 N 分钟后，点「同步完整 workflow」会在 workflow 里写入 0–N 分钟随机延迟，\n"
            "用于错开每日固定时间，降低风控风险。")
        delay_row.addWidget(delay_label)
        self._gh_random_delay_spin = QSpinBox()
        self._gh_random_delay_spin.setRange(0, 30)
        self._gh_random_delay_spin.setSuffix(" 分钟")
        self._gh_random_delay_spin.setSpecialValueText("不启用")
        self._gh_random_delay_spin.setToolTip(
            "0=不启用；N=0–N 分钟随机延迟（同步 workflow 时写入）。")
        self._controls["gh_random_delay_minutes"] = self._gh_random_delay_spin
        self._gh_random_delay_spin.valueChanged.connect(
            lambda _value: self._save_gh_workflow_options())
        delay_row.addWidget(self._gh_random_delay_spin, 1)
        group_v.addLayout(delay_row)

        # GitHub 操作按钮的异步请求加载状态：indeterminate 进度条 + 文案
        busy_row = QHBoxLayout()
        busy_row.setSpacing(8)
        self._gh_busy_bar = QProgressBar()
        self._gh_busy_bar.setRange(0, 0)
        self._gh_busy_bar.setTextVisible(False)
        self._gh_busy_bar.setFixedWidth(140)
        self._gh_busy_bar.hide()
        busy_row.addWidget(self._gh_busy_bar)
        self._gh_busy_label = QLabel("")
        self._gh_busy_label.setObjectName("captionText")
        busy_row.addWidget(self._gh_busy_label, 1)
        group_v.addLayout(busy_row)

    def _apply_hint(self, ctrl: Any, key: str) -> None:
        """给控件套上 placeholder 与 tooltip（如有）。"""
        hint = FIELD_HINTS.get(key, {})
        ph = hint.get("placeholder")
        tt = hint.get("tooltip")
        if ph and hasattr(ctrl, "setPlaceholderText"):
            try:
                ctrl.setPlaceholderText(ph)
            except Exception:
                pass
        if tt and hasattr(ctrl, "setToolTip"):
            try:
                ctrl.setToolTip(tt)
            except Exception:
                pass

    def _build_password_row(self, field_key: str,
                            with_md5_button_target: Optional[str] = None,
                            read_only: bool = False) -> QWidget:
        """构造带 eye 图标切换显隐的密码输入行。

        :param field_key: 字段名，用于取 placeholder/tooltip 提示。
        :param with_md5_button_target: 若不为 None，则在该行额外加「→ MD5」按钮，
            把该字段明文 hash 后写入目标字段（``netease_password`` → ``netease_md5_password``）。
        :param read_only: True 时输入框设为只读（用于 Cookie 字段，由登录流程自动写入，
            用户无法手编但可点眼睛查看）。
        """
        row = QWidget()
        # 行本身要占满整列，否则带按钮的行会比别的输入框窄一截
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SP_2)
        edit = QLineEdit()
        edit.setObjectName("pwdEdit")
        edit.setEchoMode(QLineEdit.Password)
        # 密钥/令牌通常是长串：用等宽小字显示（圆点更窄、字形对齐），
        # 宽度和其他输入框保持一致，不单独缩窄——否则整列参差不齐。
        mono = QFont("Consolas")
        mono.setPixelSize(theme.FS_CAPTION)
        edit.setFont(mono)
        if read_only:
            edit.setReadOnly(True)
        self._apply_hint(edit, field_key)
        layout.addWidget(edit, 1)

        # 眼睛放进输入框自己的布局里（Qt 官方"清除按钮"的做法），
        # 由布局负责定位和缩放，不用手写 resizeEvent。
        # 用 QToolButton 而不是 QCheckBox：QCheckBox 设了 icon 也仍会画一个勾选框。
        eye = QToolButton(edit)
        eye.setCheckable(True)
        eye.setIcon(eye_icon(False))
        eye.setIconSize(QSize(15, 15))
        eye.setCursor(Qt.PointingHandCursor)
        eye.setToolTip("显示")
        eye.setAutoRaise(True)
        eye.setFixedSize(22, 22)

        def _toggle(checked: bool) -> None:
            edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
            eye.setIcon(eye_icon(checked))
            eye.setToolTip("隐藏" if checked else "显示")

        eye.toggled.connect(_toggle)
        eye_row = QHBoxLayout(edit)
        eye_row.setContentsMargins(0, 0, 5, 0)
        eye_row.setSpacing(0)
        eye_row.addStretch(1)
        eye_row.addWidget(eye)
        edit.setTextMargins(0, 0, 26, 0)

        if with_md5_button_target:
            # 按钮放在输入框内部右侧（和眼睛同一排），这样这一行的输入框
            # 仍与其他字段同宽，不会因为多一个按钮而短一截。
            convert_btn = QToolButton(edit)
            convert_btn.setText("MD5")
            convert_btn.setCursor(Qt.PointingHandCursor)
            convert_btn.setToolTip(
                "把左边这串明文算成 MD5 填进 MD5 字段，并清空明文。")

            def _convert():
                plain = edit.text().strip()
                if not plain:
                    return
                md5 = hashlib.md5(plain.encode("utf-8")).hexdigest()
                target = self._controls.get(with_md5_button_target)
                if isinstance(target, QLineEdit):
                    target.setText(md5)
                    edit.clear()

            convert_btn.clicked.connect(_convert)
            eye_row.insertWidget(eye_row.count() - 1, convert_btn)
            edit.setTextMargins(0, 0, 54, 0)
        return row

    # ------------------------------------------------------------------
    # 数据装载
    # ------------------------------------------------------------------
    @staticmethod
    def _read_keyring(key: str) -> str:
        """从 keyring 读指定 key（core/Config 未映射 gh_token，这里直读）。"""
        try:
            import keyring
            if keyring is not None:
                return keyring.get_password(_KEYRING_SERVICE, key) or ""
        except Exception:
            pass
        return ""

    def load_from_config(self) -> None:
        """从 Config（keyring>env>json）加载到表单；Config 不可用时用默认值预填。"""
        self._loading_controls = True
        config: Optional[Config] = None
        try:
            config = Config()
        except Exception:
            config = None

        def _val(key: str) -> Any:
            """优先用已保存配置，缺失则用默认值。"""
            default = DEFAULTS.get(key, "")
            if config is None:
                return default
            v = config.get(key, default)
            # 空字符串视为未配置，回退默认值（让首次用户看到默认数值）
            if v in (None, ""):
                return default
            return v

        self._set_control("Cookie_MUSIC_U", _val("Cookie_MUSIC_U"))
        self._set_control("Cookie___csrf", _val("Cookie___csrf"))
        self._set_control("netease_phone", _val("netease_phone"))
        self._set_control("netease_password", _val("netease_password"))
        self._set_control("netease_md5_password", _val("netease_md5_password"))
        self._set_control("wait_time_min", int(_val("wait_time_min")))
        self._set_control("wait_time_max", int(_val("wait_time_max")))
        self._set_control("score", int(_val("score")))
        self._set_control("full_extra_tasks", bool(_val("full_extra_tasks")))
        self._set_control("note_enabled", bool(_val("note_enabled")))
        self._set_control("note_voice", str(_val("note_voice")))
        legacy_cap = int(_val("note_max_chars"))
        legacy_length = "brief" if legacy_cap <= 40 else (
            "detailed" if legacy_cap > 80 else "standard")
        self._set_control("note_length", str(_val("note_length") or legacy_length))
        self._set_control("notify_email", _val("notify_email"))
        self._set_control("email_password", _val("email_password"))
        self._set_control("smtp_server", _val("smtp_server"))
        self._set_control("smtp_port", int(_val("smtp_port")))
        self._set_control("notify_on_task_done", bool(_val("notify_on_task_done")))
        self._set_control("notify_on_cookie_expired", bool(_val("notify_on_cookie_expired")))
        self._set_control("notify_on_schedule", bool(_val("notify_on_schedule")))
        # gh_token 从 keyring 直接读；其他 3 字段从 Config / 默认值
        self._set_control("gh_token", self._read_keyring("gh_token"))
        self._set_control("gh_repo", _val("gh_repo"))
        self._set_control("workflow_name", _val("workflow_name"))
        self._set_control("workflow_branch", _val("workflow_branch"))
        self._set_control("gh_disable_schedule",
                          bool(_val("gh_disable_schedule")))
        self._set_control("gh_random_delay_minutes",
                          int(_val("gh_random_delay_minutes")))
        self._set_control("gh_success_email",
                          bool(_val("gh_success_email")))
        self._loading_controls = False

    def _set_control(self, key: str, value: Any) -> None:
        ctrl = self._controls.get(key)
        if ctrl is None:
            return
        if isinstance(ctrl, QLineEdit):
            ctrl.setText("" if value is None else str(value))
        elif isinstance(ctrl, QSpinBox):
            try:
                ctrl.setValue(int(value))
            except Exception:
                pass
        elif isinstance(ctrl, QComboBox):
            if key in ("gh_disable_schedule", "gh_success_email"):
                target = bool(value)
                for i in range(ctrl.count()):
                    if bool(ctrl.itemData(i)) == target:
                        ctrl.setCurrentIndex(i)
                        break
            elif key in ("note_voice", "note_length"):
                # 语气下拉用 userData（restrained/warm/brief）
                for i in range(ctrl.count()):
                    if str(ctrl.itemData(i)) == str(value):
                        ctrl.setCurrentIndex(i)
                        break
            elif key == "smtp_server":
                # 下拉是只读的（点开选择）：配置里若是自定义服务器，
                # 先补一个条目再选中，免得保存时被改成预设值。
                text = "" if value is None else str(value)
                index = ctrl.findText(text)
                if index < 0 and text:
                    ctrl.addItem(text)
                    index = ctrl.count() - 1
                if index >= 0:
                    ctrl.setCurrentIndex(index)
            else:
                ctrl.setCurrentText("" if value is None else str(value))
        elif isinstance(ctrl, QCheckBox):
            ctrl.setChecked(bool(value))

    def _collect_form(self) -> Dict[str, Any]:
        """收集表单值为字典。"""
        data: Dict[str, Any] = {}
        for key, ctrl in self._controls.items():
            if isinstance(ctrl, QLineEdit):
                data[key] = ctrl.text().strip()
            elif isinstance(ctrl, QSpinBox):
                data[key] = ctrl.value()
            elif isinstance(ctrl, QComboBox):
                # score / note_voice 下拉用 userData，GitHub 开关也用 userData
                if key in ("score", "note_voice", "note_length", "gh_disable_schedule", "gh_success_email"):
                    data[key] = ctrl.currentData()
                else:
                    data[key] = ctrl.currentText()
            elif isinstance(ctrl, QCheckBox):
                data[key] = ctrl.isChecked()
        return data

    def _save_form_keys(self, keys) -> None:
        """把指定表单字段立即写入 setting.json，重启后仍保留。"""
        if getattr(self, "_loading_controls", False):
            return
        import os
        path = Config.config_file()
        data: Dict[str, Any] = {}
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        data = loaded
        except Exception:
            data = {}
        for key in keys:
            ctrl = self._controls.get(key)
            if isinstance(ctrl, QCheckBox):
                data[key] = ctrl.isChecked()
            elif isinstance(ctrl, QComboBox):
                # 选项类下拉存真实值；开关类（bool userData）保持布尔
                if key in ("score", "note_voice", "note_length"):
                    data[key] = ctrl.currentData()
                else:
                    data[key] = bool(ctrl.currentData())
            elif isinstance(ctrl, QSpinBox):
                data[key] = ctrl.value()
        try:
            Config.write_file_config(data)
        except Exception:
            pass

    def _save_gh_workflow_options(self) -> None:
        """GitHub workflow 选项变更后立即持久化。"""
        self._save_form_keys(
            ("gh_disable_schedule", "gh_random_delay_minutes", "gh_success_email"))

    def _save_notify_options(self) -> None:
        """邮件通知开关变更后立即持久化。"""
        self._save_form_keys(
            ("notify_on_task_done", "notify_on_cookie_expired",
             "notify_on_schedule"))

    # ------------------------------------------------------------------
    # 按钮行为
    # ------------------------------------------------------------------
    def save(self) -> None:
        """把表单值保存到 CookieStore + keyring + 写回 setting.json。"""
        data = self._collect_form()
        # 敏感字段进 keyring
        try:
            store = CookieStore()
            if data.get("Cookie_MUSIC_U") and data.get("Cookie___csrf"):
                store.save(data["Cookie_MUSIC_U"], data["Cookie___csrf"])
            # 凭据/身份字段统一走 keyring，与打包目录无关
            try:
                import keyring
                if keyring is not None:
                    for cfg_key, kr_key in Config._KEYRING_KEY_MAP.items():
                        if cfg_key in ("Cookie_MUSIC_U", "Cookie___csrf"):
                            continue
                        v = data.get(cfg_key)
                        if v:
                            try:
                                keyring.set_password(
                                    _KEYRING_SERVICE, kr_key, str(v))
                            except Exception:
                                pass
                        else:
                            try:
                                keyring.delete_password(_KEYRING_SERVICE, kr_key)
                            except Exception:
                                pass
            except Exception:
                pass
        except Exception as e:
            dialogs.warn(self, "保存失败", str(e))
            return
        # 非敏感字段写入用户目录固定路径；keyring 字段不落 JSON
        try:
            export = {k: v for k, v in data.items()
                      if k not in Config._KEYRING_KEY_MAP}
            Config.write_file_config(export)
        except Exception as e:
            dialogs.warn(self, "部分保存失败",
                                f"keyring 已写入，但 setting.json 写入失败：{e}")
            return
        # 定时执行配置进 AppConfig（独立文件，不入 setting.json）
        self._save_schedule_config()
        self._save_close_action_config()
        dialogs.info(self, "保存", "配置已保存。")

    # ------------------------------------------------------------------
    # 定时执行（AppConfig）
    # ------------------------------------------------------------------
    def _load_schedule_config(self) -> None:
        """从 AppConfig 读 schedule_* 到表单控件。"""
        try:
            self._schedule_enable_box.setChecked(self._app_config.schedule_enabled)
            self._set_time_combos(self._schedule_hour_combo,
                                  self._schedule_minute_combo,
                                  self._app_config.schedule_time, (9, 0))
            mode = self._app_config.schedule_mode
            for i in range(self._schedule_mode_combo.count()):
                if self._schedule_mode_combo.itemData(i) == mode:
                    self._schedule_mode_combo.setCurrentIndex(i)
                    break
            self._schedule_delay_spin.setValue(
                int(self._app_config.get("local_delay_minutes", 0) or 0))
            self._schedule_catchup_box.setChecked(
                bool(self._app_config.get("catchup_enabled", True)))
            self._set_time_combos(
                self._schedule_deadline_hour, self._schedule_deadline_minute,
                self._app_config.get("catchup_deadline", "23:00"), (23, 0))
        except Exception:
            pass

    @staticmethod
    def _parse_hhmm(text, default):
        try:
            hh, mm = str(text or "").split(":")
            h, m = int(hh), int(mm)
            if 0 <= h <= 23 and 0 <= m <= 59:
                return h, m
        except Exception:
            pass
        return default

    def _build_time_row(self, hour: int, minute: int):
        """「时 + 分」两个下拉。返回 ``(行控件, 时下拉, 分下拉)``。"""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SP_2)
        hour_combo = _DownCombo()
        for h in range(24):
            hour_combo.addItem(f"{h:02d} 时", h)
        minute_combo = _DownCombo()
        for m in range(60):
            minute_combo.addItem(f"{m:02d} 分", m)
        hour_combo.setCurrentIndex(max(0, min(23, hour)))
        minute_combo.setCurrentIndex(max(0, min(59, minute)))
        layout.addWidget(hour_combo, 1)
        layout.addWidget(minute_combo, 1)
        return row, hour_combo, minute_combo

    @staticmethod
    def _time_from_combos(hour_combo: QComboBox, minute_combo: QComboBox) -> str:
        hour = int(hour_combo.currentData() or 0)
        minute = int(minute_combo.currentData() or 0)
        return f"{hour:02d}:{minute:02d}"

    def _set_time_combos(self, hour_combo: QComboBox, minute_combo: QComboBox,
                         text, default=(9, 0)) -> None:
        hour, minute = self._parse_hhmm(text, default)
        hour_combo.setCurrentIndex(hour)
        minute_combo.setCurrentIndex(minute)

    def _save_schedule_config(self) -> None:
        """把表单上的 schedule_* 写回 AppConfig，并 emit signal 通知主窗口重排。"""
        try:
            enabled = self._schedule_enable_box.isChecked()
            hhmm = self._time_from_combos(self._schedule_hour_combo,
                                          self._schedule_minute_combo)
            mode = self._schedule_mode_combo.currentData() or "local"
            self._app_config.set("schedule_enabled", enabled)
            self._app_config.set("schedule_time", hhmm)
            self._app_config.set("schedule_mode", mode)
            self._app_config.set("local_delay_minutes",
                                 int(self._schedule_delay_spin.value()))
            self._app_config.set("catchup_enabled",
                                 bool(self._schedule_catchup_box.isChecked()))
            self._app_config.set(
                "catchup_deadline",
                self._time_from_combos(self._schedule_deadline_hour,
                                       self._schedule_deadline_minute))
            self._app_config.save()
        except Exception:
            pass
        # 通知主窗口重排定时器
        self.schedule_config_changed.emit()

    def refresh_app_config(self) -> None:
        """进入设置页时从磁盘重读 AppConfig 字段，避免与主窗口的改动不同步。"""
        try:
            self._app_config.load()
        except Exception:
            pass
        self._load_schedule_config()
        self._load_close_action_config()

    def _load_close_action_config(self) -> None:
        """从 AppConfig 读 close_action 到下拉框。"""
        try:
            value = self._app_config.close_action
            data = "ask" if value is None else value
            for i in range(self._close_action_combo.count()):
                if self._close_action_combo.itemData(i) == data:
                    self._close_action_combo.setCurrentIndex(i)
                    break
        except Exception:
            pass

    def _save_close_action_config(self) -> None:
        """把下拉框选择写回 AppConfig（None=每次询问），并通知主窗口重读。"""
        try:
            data = self._close_action_combo.currentData() or "ask"
            value = None if data == "ask" else data
            self._app_config.set("close_action", value)
            self._app_config.save()
        except Exception:
            pass
        self.close_action_changed.emit()

    # ------------------------------------------------------------------
    # GitHub cron / Cookie Secrets 同步
    # ------------------------------------------------------------------
    def _read_gh_form(self) -> tuple[str, str, str, str]:
        """从 GitHub 区表单读 (gh_token, gh_repo, workflow_name, workflow_branch)。"""
        def _text(key: str) -> str:
            ctrl = self._controls.get(key)
            return ctrl.text().strip() if isinstance(ctrl, QLineEdit) else ""
        return _text("gh_token"), _text("gh_repo"), _text("workflow_name"), _text("workflow_branch")

    def _set_gh_result(self, ok: bool, msg: str) -> None:
        """把 GitHub 区结果回显到 _gh_result_label（successText/dangerText）。"""
        if ok:
            self._gh_result_label.setObjectName("successText")
            self._gh_result_label.setText(f"✅ {msg}")
        else:
            self._gh_result_label.setObjectName("dangerText")
            self._gh_result_label.setText(f"❌ {msg}")
        # objectName 改变后需重新 polish 才能套上新样式
        self._gh_result_label.style().polish(self._gh_result_label)

    def _set_gh_busy(self, busy: bool) -> None:
        """切换 GitHub 区加载状态：显示/隐藏进度条并禁用相关按钮。"""
        for btn in (self._gh_test_btn, self._gh_cron_btn,
                    self._gh_cookie_btn, self._gh_wf_btn,
                    self._gh_all_btn):
            btn.setEnabled(not busy)
        if busy:
            self._gh_busy_bar.show()
        else:
            self._gh_busy_bar.hide()
            self._gh_busy_label.setText("")

    def _run_gh_async(self, message: str, fn) -> None:
        """启动后台 GitHub API 调用；请求期间显示加载状态。"""
        if self._gh_worker is not None and self._gh_worker.isRunning():
            return
        self._set_gh_busy(True)
        self._gh_busy_label.setText(message)
        self._gh_result_label.setObjectName("captionText")
        self._gh_result_label.setText("")
        self._gh_result_label.style().polish(self._gh_result_label)
        worker = _GitHubActionWorker(fn, parent=self)
        worker.result_ready.connect(self._on_gh_async_finished)
        self._gh_worker = worker
        worker.start()

    def _on_gh_async_finished(self, ok: bool, msg: str) -> None:
        """GitHub API 后台调用结束：收起加载状态并回显结果。"""
        self._set_gh_busy(False)
        self._set_gh_result(ok, msg)

    def _sync_full_workflow(self) -> None:
        """把 resources/workflow_example.yml 全文 PUT 到 fork 仓库覆盖。

        用模板内容（跑 main.py 评分 + 用 Secrets Cookie，不密码登录刷 Cookie）
        覆盖 fork 仓库的 .github/workflows/{workflow_name}，避免用户手动复制。
        若选择「关闭云端定时」，会先注释掉 workflow 的 schedule 块。
        """
        token, repo, workflow, branch = self._read_gh_form()
        if not (token and repo and workflow and branch):
            self._set_gh_result(False, "请先填写 gh_token / gh_repo / workflow_name / workflow_branch")
            return
        content, err = self._read_workflow_template()
        if content is None:
            self._set_gh_result(False, err)
            return
        content = self._build_workflow_content(content)
        message = ("正在同步完整 workflow（已关闭云端定时）…"
                   if bool(self._gh_disable_schedule_combo.currentData())
                   else "正在同步完整 workflow 到仓库…")
        self._run_gh_async(
            message,
            lambda: ActionsTrigger(token, repo).sync_full_workflow(
                workflow, branch, content),
        )

    def _sync_all_to_github(self) -> None:
        """按当前设置依次同步 workflow、Cookie、邮件和任务参数。"""
        token, repo, workflow, branch = self._read_gh_form()
        if not (token and repo and workflow and branch):
            self._set_gh_result(False, "请先填写 gh_token / gh_repo / workflow_name / workflow_branch")
            return
        content, err = self._read_workflow_template()
        if content is None:
            self._set_gh_result(False, err)
            return
        content = self._build_workflow_content(content)
        try:
            music_u, csrf, _ = CookieStore().load()
        except Exception as e:
            self._set_gh_result(False, f"读取本地 Cookie 失败：{e}")
            return
        if not (music_u and csrf):
            self._set_gh_result(False, "本地无 Cookie，请先登录后再一键同步全部")
            return
        form = self._collect_form()
        notify_email = str(form.get("notify_email") or "").strip()
        email_password = str(form.get("email_password") or "").strip()
        smtp_server = str(form.get("smtp_server") or "").strip()
        smtp_port = str(form.get("smtp_port") or "").strip()
        full_extra_tasks = bool(form.get("full_extra_tasks", True))

        def _do_sync():
            trigger = ActionsTrigger(token, repo)
            ok, msg = trigger.sync_full_workflow(workflow, branch, content)
            if not ok:
                return False, f"同步 workflow 失败：{msg}"
            parts = [msg]
            ok2, msg2 = trigger.sync_cookies(music_u, csrf)
            if not ok2:
                return False, f"同步 Cookie 失败：{msg2}"
            parts.append(msg2)
            if notify_email and email_password:
                ok3, msg3 = trigger.sync_email(
                    notify_email, email_password, smtp_server, smtp_port)
                if not ok3:
                    return False, f"同步邮件配置失败：{msg3}"
                parts.append(msg3)
            ok4, msg4 = trigger.sync_full_extra_tasks(full_extra_tasks)
            if not ok4:
                return False, f"同步任务参数失败：{msg4}"
            parts.append(msg4)
            return True, "；".join(parts)

        self._run_gh_async(
            "正在一键同步 workflow 和 Secrets…",
            _do_sync,
        )

    def _read_workflow_template(self) -> Tuple[Optional[str], str]:
        """读取 resources/workflow_example.yml；失败返回 (None, 错误信息)。"""
        import os
        import sys
        # 定位 resources/workflow_example.yml
        # 打包后 __file__ 在 _internal/app/ui/pages/，sys._MEIPASS = _internal/
        # 开发模式 __file__ 在 <root>/app/ui/pages/settings_page.py，向上 4 级到项目根
        if hasattr(sys, "_MEIPASS"):
            base = sys._MEIPASS
        else:
            base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        yml_path = os.path.join(base, "resources", "workflow_example.yml")
        try:
            with open(yml_path, "r", encoding="utf-8") as f:
                return f.read(), ""
        except Exception as e:
            return None, f"读取本地 workflow 模板失败：{e}"

    def _build_workflow_content(self, content: str) -> str:
        """按当前 GitHub 区设置生成要上传的完整 workflow 内容。"""
        disable_schedule = bool(self._gh_disable_schedule_combo.currentData())
        self._save_gh_workflow_options()
        content = self._set_workflow_schedule(content, not disable_schedule)
        if not disable_schedule:
            content = self._set_workflow_cron(content, self._cloud_cron_from_editor())
        random_delay = self._gh_random_delay_spin.value()
        content = self._set_workflow_random_delay(content, random_delay)
        success_email = bool(self._gh_success_email_combo.currentData())
        self._save_gh_workflow_options()
        content = self._set_workflow_success_email(content, success_email)
        return content

    @staticmethod
    def _set_workflow_schedule(content: str, enabled: bool) -> str:
        """注释/恢复 workflow 里的 GitHub 原生 schedule 块。"""
        out_lines = []
        for raw in content.splitlines(keepends=True):
            line = raw.rstrip("\r\n")
            newline = raw[len(line):]
            if line == "  schedule:":
                line = "  schedule:" if enabled else "  # schedule:"
            elif line.startswith("    - cron:"):
                line = line if enabled else "    # " + line[4:]
            out_lines.append(line + newline)
        return "".join(out_lines)

    def _cloud_cron_from_editor(self) -> str:
        """把「云端 cron」的北京时间 HH:MM 转成 GitHub Actions UTC cron。"""
        _t = self._time_from_combos(self._gh_cron_hour_combo, self._gh_cron_minute_combo)
        _h, _m = (int(part) for part in _t.split(":"))
        _utc_h = (_h - 8) % 24
        return f"{_m} {_utc_h} * * *"

    @staticmethod
    def _set_workflow_cron(content: str, cron: str) -> str:
        """把 workflow 里第一个 cron 行替换为新的 cron 表达式。"""
        import re

        pattern = re.compile(
            r'^([ \t]*(?:-[ \t]+)?cron[ \t]*:[ \t]*)([\'"]?)([^\'"\n#]+)([\'"]?)([ \t]*(?:#.*)?)$',
            re.MULTILINE,
        )
        return pattern.sub(
            lambda m: f"{m.group(1)}'{cron}'{m.group(5)}", content, count=1)

    @staticmethod
    def _set_workflow_random_delay(content: str, minutes: int) -> str:
        """把随机延迟启动的最大分钟数写入 workflow 的默认值。

        workflow 模板里该行为：
          RANDOM_DELAY_MINUTES: ${{ secrets.RANDOM_DELAY_MINUTES || '0' }}
        本方法只替换 ``|| '0'`` 里的数字，保留 Secret 覆盖能力。
        """
        import re
        value = max(0, int(minutes or 0))
        pattern = re.compile(
            r"^(\s*RANDOM_DELAY_MINUTES:\s*\$\{\{\s*secrets\.RANDOM_DELAY_MINUTES\s*\|\|\s*')"
            r"([0-9]+)('\s*\}\}\s*)$",
            re.MULTILINE,
        )
        return pattern.sub(
            lambda m: f"{m.group(1)}{value}{m.group(3)}", content)

    @staticmethod
    def _set_workflow_success_email(content: str, enabled: bool) -> str:
        """把 workflow 成功邮件通知的默认开关写成 true/false。

        workflow 模板里对应行：
            SEND_SUCCESS_EMAIL: ${{ secrets.SEND_SUCCESS_EMAIL || 'false' }}
        只替换 || 后面的默认值，保留仓库 Secret 覆盖能力。
        """
        import re
        pattern = re.compile(
            r"^(\s*SEND_SUCCESS_EMAIL:\s*\$\{\{\s*secrets\.SEND_SUCCESS_EMAIL\s*\|\|\s*')"
            r"(true|false)('\s*\}\}\s*)$",
            re.MULTILINE,
        )
        return pattern.sub(
            lambda m: f"{m.group(1)}{'true' if enabled else 'false'}{m.group(3)}",
            content)

    def _sync_cron_to_workflow(self) -> None:
        """读 cron 表达式 + workflow 配置，调 ActionsTrigger.update_workflow_cron。"""
        if bool(self._gh_disable_schedule_combo.currentData()):
            self._set_gh_result(
                False, "已关闭云端定时，请先在「云端定时」选择启用后再同步 cron")
            return
        token, repo, workflow, branch = self._read_gh_form()
        # 读北京时间 HH:MM，转 UTC cron（GitHub Actions 用 UTC）
        cron = self._cloud_cron_from_editor()
        if not (token and repo and workflow and branch):
            self._set_gh_result(False, "请先填写 gh_token / gh_repo / workflow_name / workflow_branch")
            return
        if not cron:
            self._set_gh_result(False, "请填写云端 cron 表达式（如 0 9 * * *）")
            return
        self._run_gh_async(
            "正在同步 cron 到 workflow…",
            lambda: ActionsTrigger(token, repo).update_workflow_cron(
                workflow, branch, cron),
        )

    def _sync_cookies_to_github(self) -> None:
        """把 Cookie 和邮件通知配置一起写入 GitHub Actions Secrets。"""
        token, repo, _wf, _br = self._read_gh_form()
        if not token or not repo:
            self._set_gh_result(False, "请先填写 gh_token 与 gh_repo")
            return
        try:
            music_u, csrf, _ = CookieStore().load()
        except Exception as e:
            self._set_gh_result(False, f"读取本地 Cookie 失败：{e}")
            return
        if not (music_u and csrf):
            self._set_gh_result(False, "本地无 Cookie，请先登录后再同步")
            return
        form = self._collect_form()
        notify_email = str(form.get("notify_email") or "").strip()
        email_password = str(form.get("email_password") or "").strip()
        smtp_server = str(form.get("smtp_server") or "").strip()
        smtp_port = str(form.get("smtp_port") or "").strip()
        full_extra_tasks = bool(form.get("full_extra_tasks", True))

        def _do_sync():
            trigger = ActionsTrigger(token, repo)
            ok, msg = trigger.sync_cookies(music_u, csrf)
            if not ok:
                return ok, msg
            parts = [msg]
            if notify_email and email_password:
                ok2, msg2 = trigger.sync_email(
                    notify_email, email_password, smtp_server, smtp_port)
                if not ok2:
                    return ok2, msg2
                parts.append(msg2)
            ok3, msg3 = trigger.sync_full_extra_tasks(full_extra_tasks)
            if not ok3:
                return ok3, msg3
            parts.append(msg3)
            return True, "；".join(parts)

        self._run_gh_async(
            "正在加密并同步 Cookie、邮件和任务参数到 GitHub Secrets…",
            _do_sync,
        )

    def test_notification(self) -> None:
        try:
            config = Config()
        except Exception as e:
            dialogs.warn(self, "通知测试", f"配置加载失败：{e}")
            return
        svc = NotificationService(config, Logger())
        ok = svc.send_notification(
            "ncmp 测试邮件",
            "这是一封测试邮件，说明邮件通知配置可用。",
            level="info",
            facts=[("SMTP", str(config.get("smtp_server", ""))),
                   ("收件人", str(config.get("notify_email", "")))],
            action="收到这封就说明配置没问题，不用做别的。")
        if ok:
            dialogs.info(self, "通知测试", "测试邮件已发送，请查收。")
        else:
            dialogs.warn(self, "通知测试", "测试邮件发送失败，请检查 SMTP 配置。")

    def validate_cookie(self) -> None:
        """验证 Cookie。

        走后台线程：验证要发一次网络请求，放在按钮槽里会把界面冻住，
        用户点完没反应还以为程序死了。
        """
        if getattr(self, "_cookie_check", None) is not None \
                and self._cookie_check.isRunning():
            return
        btn = self.sender()
        if isinstance(btn, QPushButton):
            btn.setEnabled(False)
            btn.setText("验证中…")
        self._cookie_check = CookieCheckWorker(self)
        self._cookie_check.done.connect(
            lambda ok, msg: self._on_cookie_checked(ok, msg, btn))
        self._cookie_check.start()

    def _on_cookie_checked(self, ok: bool, msg: str, btn) -> None:
        if isinstance(btn, QPushButton):
            btn.setEnabled(True)
            btn.setText("验证 Cookie")
        if ok:
            dialogs.success(self, "Cookie 验证", msg)
        else:
            dialogs.warn(self, "Cookie 验证", msg)

    def _test_github_connection(self) -> None:
        """测试 gh_token + gh_repo 能否访问 GitHub API（GET /repos/{repo}）。

        从表单现填值读取（无需保存），结果在 GitHub 区下方以
        successText / dangerText 样式显示。
        """
        token = ""
        repo = ""
        ctrl_t = self._controls.get("gh_token")
        if isinstance(ctrl_t, QLineEdit):
            token = ctrl_t.text().strip()
        ctrl_r = self._controls.get("gh_repo")
        if isinstance(ctrl_r, QLineEdit):
            repo = ctrl_r.text().strip()
        if not token or not repo:
            self._gh_result_label.setObjectName("dangerText")
            self._gh_result_label.setText("❌ 请先填写 gh_token 与 gh_repo")
            self._gh_result_label.style().polish(self._gh_result_label)
            return
        self._run_gh_async(
            "正在测试连接…",
            lambda: ActionsTrigger(token, repo).test_auth(),
        )

    def import_setting_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 setting.json", "", "JSON Files (*.json);;All Files (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            dialogs.warn(self, "导入失败", str(e))
            return
        for k in SETTINGS_FIELDS:
            if k in data:
                self._set_control(k, data[k])
        dialogs.info(self, "导入", "已加载到表单，记得点「保存」。")

    def export_setting_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "保存 setting.json", "setting.json",
            "JSON Files (*.json);;All Files (*)")
        if not path:
            return
        data = self._collect_form()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            dialogs.warn(self, "导出失败", str(e))
            return
        dialogs.info(self, "导出", f"已保存到 {path}")
