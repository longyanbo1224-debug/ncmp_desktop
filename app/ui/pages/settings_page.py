"""参数配置页：按语义分 5 组（QGroupBox）+ GitHub Actions 云端执行预留字段。

字段对应 ncmp setting.json，gh_token 走 keyring：
    Cookie_MUSIC_U、Cookie___csrf、netease_phone、netease_password、
    netease_md5_password、wait_time_min、wait_time_max、score、
    full_extra_tasks、notify_email、email_password、smtp_server、smtp_port、
    gh_token（keyring）、gh_repo、workflow_name、workflow_branch

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
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, QTime, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QTimeEdit, QVBoxLayout, QWidget,
)

from app.app_config import AppConfig
from app.cloud.actions_trigger import ActionsTrigger
from app.cookie_store import CookieStore
from app.ui.icons import eye_icon
from core.utils.config import Config
from core.utils.logger import Logger
from core.utils.notification import NotificationService
from core.validators.cookie import CookieValidator
import requests


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
    "notify_email": "",
    "email_password": "",
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 465,
    "notify_on_task_done": True,
    "notify_on_cookie_expired": True,
    "notify_on_schedule": True,
    "gh_token": "",
    "gh_repo": "",
    "workflow_name": "refresh_cookie.yml",
    "workflow_branch": "main",
}

# keyring 服务名（与 CookieStore / Config 对齐，gh_token 用同一服务下的独立 key）
_KEYRING_SERVICE = "ncmp-desktop"

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
    "notify_email": {
        "placeholder": "接收任务结果通知的邮箱",
        "tooltip": "任务完成/失败时发邮件通知到此邮箱（可选，留空则不发邮件）。",
    },
    "email_password": {
        "placeholder": "邮箱授权码（非登录密码）",
        "tooltip": "SMTP 授权码，如 Gmail 的「应用专用密码」、QQ/163 邮箱的授权码。",
    },
    "smtp_server": {
        "tooltip": "SMTP 服务器地址，预设 Gmail/QQ/163，也可手动输入其他。",
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


class SettingsPage(QWidget):
    """参数配置表单。"""

    # 定时配置保存后通知主窗口重排定时器
    schedule_config_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._controls: Dict[str, Any] = {}
        # 业务字段走 Config；定时字段走 AppConfig（独立文件，不入 setting.json）
        self._app_config = AppConfig()
        self._build_ui()
        self.load_from_config()
        self._load_schedule_config()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 24, 24, 24)
        content_layout.setSpacing(14)

        title = QLabel("参数配置")
        title.setObjectName("pageTitle")
        content_layout.addWidget(title)

        subtitle = QLabel("默认值已预填，按需修改后点「保存」。鼠标悬停字段可见说明。")
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        content_layout.addWidget(subtitle)

        # 4 个分组区
        self._sections = QVBoxLayout()
        self._sections.setSpacing(14)
        content_layout.addLayout(self._sections)

        self._build_account_section()
        self._build_task_section()
        self._build_email_section()
        self._build_schedule_section()
        self._build_github_section()

        content_layout.addStretch(1)

        # 操作按钮
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        save_btn = QPushButton("保存")
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self.save)
        test_btn = QPushButton("测试通知")
        test_btn.setObjectName("secondaryButton")
        test_btn.clicked.connect(self.test_notification)
        validate_btn = QPushButton("验证 Cookie")
        validate_btn.setObjectName("secondaryButton")
        validate_btn.clicked.connect(self.validate_cookie)
        to_md5_btn = QPushButton("明文 → MD5")
        to_md5_btn.setObjectName("secondaryButton")
        to_md5_btn.clicked.connect(self._convert_to_md5)
        import_btn = QPushButton("导入 setting.json")
        import_btn.setObjectName("secondaryButton")
        import_btn.clicked.connect(self.import_setting_json)
        export_btn = QPushButton("导出 setting.json")
        export_btn.setObjectName("secondaryButton")
        export_btn.clicked.connect(self.export_setting_json)
        for b in (save_btn, test_btn, validate_btn, to_md5_btn,
                  import_btn, export_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        content_layout.addLayout(buttons)

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _new_section(self, title: str) -> QFormLayout:
        """创建带标题的 QGroupBox，内部直接用 QFormLayout 作布局。"""
        group = QGroupBox(title)
        self._sections.addWidget(group)
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
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
        score = QComboBox()
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
        smtp_server = QComboBox()
        smtp_server.setEditable(True)
        smtp_server.addItem("smtp.gmail.com")
        smtp_server.addItem("smtp.qq.com")
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

        notify_cookie_expired = QCheckBox("Cookie 失效时邮件通知")
        self._apply_hint(notify_cookie_expired, "notify_on_cookie_expired")
        notify_cookie_expired.setChecked(DEFAULTS["notify_on_cookie_expired"])
        form.addRow("失效通知", notify_cookie_expired)
        self._controls["notify_on_cookie_expired"] = notify_cookie_expired

        notify_schedule = QCheckBox("定时执行结果邮件通知")
        self._apply_hint(notify_schedule, "notify_on_schedule")
        notify_schedule.setChecked(DEFAULTS["notify_on_schedule"])
        form.addRow("定时通知", notify_schedule)
        self._controls["notify_on_schedule"] = notify_schedule

    def _build_schedule_section(self) -> None:
        """定时执行配置（写入 AppConfig，不入 setting.json）。"""
        form = self._new_section("定时执行")

        # 启用开关
        enable_box = QCheckBox("启用定时执行（到点自动触发本地任务/云端 Actions）")
        enable_box.setToolTip(
            "勾选后到点自动按模式触发任务；本地模式要求程序在运行，云端模式由 GitHub Actions 跑（电脑关机也能跑）。")
        form.addRow("启用", enable_box)
        self._schedule_enable_box = enable_box

        # 触发时间（24 小时制）
        time_edit = QTimeEdit()
        time_edit.setDisplayFormat("HH:mm")
        time_edit.setTime(QTime(9, 0))
        time_edit.setToolTip("触发时间（24 小时制），默认 09:00。")
        form.addRow("触发时间", time_edit)
        self._schedule_time_edit = time_edit

        # 模式
        mode_combo = QComboBox()
        mode_combo.addItem("本地（启动 TaskWorker）", "local")
        mode_combo.addItem("云端（触发 GitHub Actions）", "cloud")
        mode_combo.addItem("两者（本地 + 云端都启动）", "both")
        mode_combo.setCurrentIndex(0)
        mode_combo.setToolTip(
            "local=本地跑任务（程序需运行）；cloud=GitHub Actions 跑（关机也跑）；both=两者都启动。")
        form.addRow("模式", mode_combo)
        self._schedule_mode_combo = mode_combo

    def _build_github_section(self) -> None:
        group = QGroupBox("GitHub Actions（云端执行）")
        self._sections.addWidget(group)
        group_v = QVBoxLayout(group)
        group_v.setSpacing(8)

        caption = QLabel(
            "配置后可在任务页选云端执行，触发 GitHub Actions 跑任务（电脑关机也能跑）。\n"
            "配置步骤：\n"
            "1. fork ncmp 仓库：github.com/ACAne0320/ncmp → 右上 Fork\n"
            "2. 把 resources/workflow_example.yml 复制到 fork 仓库 .github/workflows/refresh_cookie.yml\n"
            "3. 生成 GitHub PAT（头像 → Settings → Developer settings → Personal access tokens → 勾 repo+workflow）\n"
            "4. 下方填 gh_token / gh_repo / workflow_name / workflow_branch → 点「保存」\n"
            "5. 点「测试连接」验证；点「同步 Cookie 到 GitHub Secrets」把本地 Cookie 写到仓库\n"
            "鼠标悬停各字段可见详细获取说明。")
        caption.setObjectName("captionText")
        caption.setWordWrap(True)
        group_v.addWidget(caption)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        group_v.addLayout(form)

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
        self._gh_cron_edit = QTimeEdit()
        self._gh_cron_edit.setDisplayFormat("HH:mm")
        self._gh_cron_edit.setTime(QTime(9, 0))
        self._gh_cron_edit.setToolTip(
            "北京时间触发时间。点「同步 cron」时自动转 UTC（北京 -8）写入 GitHub Actions cron。\n"
            "关机也会跑：GitHub 云端定时，不依赖桌面程序在线。")
        cron_row.addWidget(self._gh_cron_edit, 1)
        sync_cron_btn = QPushButton("同步 cron")
        sync_cron_btn.setObjectName("secondaryButton")
        sync_cron_btn.clicked.connect(self._sync_cron_to_workflow)
        cron_row.addWidget(sync_cron_btn)
        group_v.addLayout(cron_row)

        # Cookie 同步到 GitHub Secrets 按钮
        cookie_row = QHBoxLayout()
        cookie_row.setSpacing(8)
        cookie_row.addStretch(0)
        sync_cookie_btn = QPushButton("同步 Cookie 到 GitHub Secrets")
        sync_cookie_btn.setObjectName("secondaryButton")
        sync_cookie_btn.setToolTip(
            "把本地 CookieStore 中的 MUSIC_U 与 __csrf 用 PyNaCl 加密后写入 GitHub Actions Secrets\n"
            "（Cookie_MUSIC_U、Cookie___csrf），供云端 workflow 使用。需先填 gh_token/gh_repo。")
        sync_cookie_btn.clicked.connect(self._sync_cookies_to_github)
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
            "该模板跑 python main.py 评分任务 + 用 Secrets 里的 Cookie，\n"
            "不依赖密码登录刷 Cookie（避免风控）。需先填 gh_token/gh_repo/workflow_name/branch。")
        sync_wf_btn.clicked.connect(self._sync_full_workflow)
        wf_row.addWidget(sync_wf_btn)
        wf_row.addStretch(1)
        group_v.addLayout(wf_row)

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
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit()
        edit.setObjectName("pwdEdit")
        edit.setEchoMode(QLineEdit.Password)
        if read_only:
            edit.setReadOnly(True)
        self._apply_hint(edit, field_key)
        layout.addWidget(edit, 1)
        eye = QCheckBox()
        eye.setToolTip("显示/隐藏")
        eye.setIcon(eye_icon(False))
        eye.toggled.connect(
            lambda checked: (
                edit.setEchoMode(
                    QLineEdit.Normal if checked else QLineEdit.Password),
                eye.setIcon(eye_icon(checked)),
            ))
        layout.addWidget(eye)
        if with_md5_button_target:
            convert_btn = QPushButton("→ MD5")
            convert_btn.setObjectName("secondaryButton")

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
            layout.addWidget(convert_btn)
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
                # score 下拉用 userData（1/2/3/4），其它取文本
                if key == "score":
                    data[key] = ctrl.currentData()
                else:
                    data[key] = ctrl.currentText()
            elif isinstance(ctrl, QCheckBox):
                data[key] = ctrl.isChecked()
        return data

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
            # netease_password / netease_md5_password / email_password / gh_token
            # 也走 keyring（gh_token 与 Cookie 同 service，key 区分为 "gh_token"）
            try:
                import keyring
                if keyring is not None:
                    for k in ("netease_password", "netease_md5_password",
                              "email_password", "gh_token"):
                        v = data.get(k)
                        if v:
                            keyring.set_password(_KEYRING_SERVICE, k, str(v))
            except Exception:
                pass
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))
            return
        # 非敏感字段回写 config/setting.json（gh_token 不入 json，仅 keyring）
        try:
            import os
            os.makedirs("config", exist_ok=True)
            export = {k: v for k, v in data.items()
                      if k not in ("Cookie_MUSIC_U", "Cookie___csrf", "gh_token")}
            with open("config/setting.json", "w", encoding="utf-8") as f:
                json.dump(export, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "部分保存失败",
                                f"keyring 已写入，但 setting.json 写入失败：{e}")
            return
        # 定时执行配置进 AppConfig（独立文件，不入 setting.json）
        self._save_schedule_config()
        QMessageBox.information(self, "保存", "配置已保存。")

    # ------------------------------------------------------------------
    # 定时执行（AppConfig）
    # ------------------------------------------------------------------
    def _load_schedule_config(self) -> None:
        """从 AppConfig 读 schedule_* 到表单控件。"""
        try:
            self._schedule_enable_box.setChecked(self._app_config.schedule_enabled)
            hh, mm = self._app_config.schedule_time.split(":")
            self._schedule_time_edit.setTime(QTime(int(hh), int(mm)))
            mode = self._app_config.schedule_mode
            for i in range(self._schedule_mode_combo.count()):
                if self._schedule_mode_combo.itemData(i) == mode:
                    self._schedule_mode_combo.setCurrentIndex(i)
                    break
        except Exception:
            pass

    def _save_schedule_config(self) -> None:
        """把表单上的 schedule_* 写回 AppConfig，并 emit signal 通知主窗口重排。"""
        try:
            enabled = self._schedule_enable_box.isChecked()
            hhmm = self._schedule_time_edit.time().toString("HH:mm")
            mode = self._schedule_mode_combo.currentData() or "local"
            self._app_config.set("schedule_enabled", enabled)
            self._app_config.set("schedule_time", hhmm)
            self._app_config.set("schedule_mode", mode)
            self._app_config.save()
        except Exception:
            pass
        # 通知主窗口重排定时器
        self.schedule_config_changed.emit()

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

    def _sync_full_workflow(self) -> None:
        """把 resources/workflow_example.yml 全文 PUT 到 fork 仓库覆盖。

        用模板内容（跑 main.py 评分 + 用 Secrets Cookie，不密码登录刷 Cookie）
        覆盖 fork 仓库的 .github/workflows/{workflow_name}，避免用户手动复制。
        """
        import os
        import sys
        token, repo, workflow, branch = self._read_gh_form()
        if not (token and repo and workflow and branch):
            self._set_gh_result(False, "请先填写 gh_token / gh_repo / workflow_name / workflow_branch")
            return
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
                content = f.read()
        except Exception as e:
            self._set_gh_result(False, f"读取本地 workflow 模板失败：{e}")
            return
        self._set_gh_result(True, "正在同步完整 workflow 到仓库…")
        try:
            ok, msg = ActionsTrigger(token, repo).sync_full_workflow(workflow, branch, content)
        except Exception as e:
            ok, msg = False, f"异常：{e}"
        self._set_gh_result(ok, msg)

    def _sync_cron_to_workflow(self) -> None:
        """读 cron 表达式 + workflow 配置，调 ActionsTrigger.update_workflow_cron。"""
        token, repo, workflow, branch = self._read_gh_form()
        # 读北京时间 HH:MM，转 UTC cron（GitHub Actions 用 UTC）
        _t = self._gh_cron_edit.time()
        _utc_h = (_t.hour() - 8) % 24
        cron = f"{_t.minute()} {_utc_h} * * *"
        if not (token and repo and workflow and branch):
            self._set_gh_result(False, "请先填写 gh_token / gh_repo / workflow_name / workflow_branch")
            return
        if not cron:
            self._set_gh_result(False, "请填写云端 cron 表达式（如 0 9 * * *）")
            return
        self._set_gh_result(True, "正在同步 cron 到 workflow…")
        try:
            ok, msg = ActionsTrigger(token, repo).update_workflow_cron(workflow, branch, cron)
        except Exception as e:
            ok, msg = False, f"异常：{e}"
        self._set_gh_result(ok, msg)

    def _sync_cookies_to_github(self) -> None:
        """从 CookieStore 读 MUSIC_U + __csrf，调 ActionsTrigger.sync_cookies 写入 Secrets。"""
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
        self._set_gh_result(True, "正在加密并同步 Cookie 到 GitHub Secrets…")
        try:
            ok, msg = ActionsTrigger(token, repo).sync_cookies(music_u, csrf)
        except Exception as e:
            ok, msg = False, f"异常：{e}"
        self._set_gh_result(ok, msg)

    def test_notification(self) -> None:
        try:
            config = Config()
        except Exception as e:
            QMessageBox.warning(self, "通知测试", f"配置加载失败：{e}")
            return
        svc = NotificationService(config, Logger())
        ok = svc.send_notification("ncmp 测试邮件", "这是来自 ncmp desktop 的通知测试。")
        if ok:
            QMessageBox.information(self, "通知测试", "测试邮件已发送，请查收。")
        else:
            QMessageBox.warning(self, "通知测试", "测试邮件发送失败，请检查 SMTP 配置。")

    def validate_cookie(self) -> None:
        try:
            music_u, csrf, _ = CookieStore().load()
        except Exception as e:
            QMessageBox.warning(self, "Cookie 验证", f"读取 Cookie 失败：{e}")
            return
        if not (music_u and csrf):
            QMessageBox.warning(self, "Cookie 验证", "未配置 Cookie，请先登录。")
            return
        session = requests.Session()
        session.cookies.set("MUSIC_U", music_u)
        session.cookies.set("__csrf", csrf)
        ok, msg = CookieValidator(session, Logger()).validate()
        if ok:
            QMessageBox.information(self, "Cookie 验证", msg)
        else:
            QMessageBox.warning(self, "Cookie 验证", msg)

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
        self._gh_result_label.setObjectName("captionText")
        self._gh_result_label.setText("正在测试连接…")
        self._gh_result_label.style().polish(self._gh_result_label)
        try:
            ok, msg = ActionsTrigger(token, repo).test_auth()
        except Exception as e:
            ok, msg = False, f"异常：{e}"
        if ok:
            self._gh_result_label.setObjectName("successText")
            self._gh_result_label.setText(f"✅ {msg}")
        else:
            self._gh_result_label.setObjectName("dangerText")
            self._gh_result_label.setText(f"❌ {msg}")
        # objectName 改变后需重新 polish 才能套上新样式
        self._gh_result_label.style().polish(self._gh_result_label)

    def _convert_to_md5(self) -> None:
        """「明文 → MD5」按钮：取明文字段，hash 后填入 MD5 字段。"""
        plain_edit = self._controls.get("netease_password")
        md5_edit = self._controls.get("netease_md5_password")
        if not isinstance(plain_edit, QLineEdit) or not isinstance(md5_edit, QLineEdit):
            return
        plain = plain_edit.text().strip()
        if not plain:
            QMessageBox.warning(self, "明文 → MD5", "请先在 netease_password 输入明文。")
            return
        md5 = hashlib.md5(plain.encode("utf-8")).hexdigest()
        md5_edit.setText(md5)
        plain_edit.clear()
        QMessageBox.information(self, "明文 → MD5",
                                "已转换为 MD5 并填入 netease_md5_password（明文已清空）。")

    def import_setting_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 setting.json", "", "JSON Files (*.json);;All Files (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "导入失败", str(e))
            return
        for k in SETTINGS_FIELDS:
            if k in data:
                self._set_control(k, data[k])
        QMessageBox.information(self, "导入", "已加载到表单，记得点「保存」。")

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
            QMessageBox.warning(self, "导出失败", str(e))
            return
        QMessageBox.information(self, "导出", f"已保存到 {path}")
