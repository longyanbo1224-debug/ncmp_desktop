"""首页：Cookie 状态驱动三态卡片 + 最近任务摘要 + 闭环 toast。"""
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from app.cookie_store import CookieStore
from app.task_history import TaskHistory
from app.ui.icons import (
    COLOR_DANGER, COLOR_PENDING, COLOR_SUCCESS, ICON_EMPTY_DASHBOARD,
    ICON_LOGIN, ICON_RUN, op_icon,
)


# 三态常量（UNCONFIGURED 无 Cookie / VALID 有效 / EXPIRED 失效）
_UNCONFIGURED = "unconfigured"
_VALID = "valid"
_EXPIRED = "expired"


class DashboardPage(QWidget):
    """首页 Dashboard：根据 Cookie 状态切换三态卡片。"""

    run_task = Signal()
    goto_login = Signal()
    goto_settings = Signal()
    refresh_cookie = Signal()  # 预留：供外部触发刷新

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._state = _UNCONFIGURED
        self._expired_msg = ""
        self._build_ui()
        self.refresh_cookie_card()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        title = QLabel("ncmp desktop")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        # 顶部 toast（默认隐藏）
        self._toast = QLabel("")
        self._toast.setObjectName("toast")
        self._toast.setVisible(False)
        outer.addWidget(self._toast)

        # 中部状态卡
        self._card = QFrame()
        self._card.setObjectName("card")
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(12)

        self._card_icon_label = QLabel()
        self._card_icon_label.setAlignment(Qt.AlignCenter)
        self._card_icon_label.setVisible(False)
        card_layout.addWidget(self._card_icon_label)

        self._card_status_label = QLabel("")
        self._card_status_label.setWordWrap(True)
        self._card_status_label.setStyleSheet("font-size: 14px; font-weight: 600;")
        card_layout.addWidget(self._card_status_label)

        self._card_button = QPushButton("")
        self._card_button.setObjectName("primaryButton")
        self._card_button.setIconSize(QSize(16, 16))
        self._card_button.clicked.connect(self._on_card_button_clicked)
        card_layout.addWidget(self._card_button)

        self._summary_label = QLabel("暂无任务记录")
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet("padding: 4px 0;")
        self._summary_label.setObjectName("captionText")
        card_layout.addWidget(self._summary_label)

        outer.addWidget(self._card)

        outer.addStretch(1)

        # 底部设置入口
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        settings_btn = QPushButton("设置 →")
        settings_btn.setObjectName("secondaryButton")
        settings_btn.clicked.connect(self.goto_settings.emit)
        bottom.addWidget(settings_btn)
        outer.addLayout(bottom)

    def _on_card_button_clicked(self) -> None:
        if self._state == _UNCONFIGURED:
            self.goto_login.emit()
        elif self._state == _VALID:
            self.run_task.emit()
        else:  # _EXPIRED
            self.goto_login.emit()

    def _render(self) -> None:
        if self._state == _UNCONFIGURED:
            # 大图标空状态引导（48px 灰色 key 图标，居中显示在文字上方）
            pix = op_icon(ICON_EMPTY_DASHBOARD, COLOR_PENDING).pixmap(QSize(48, 48))
            self._card_icon_label.setPixmap(pix)
            self._card_icon_label.setVisible(True)
            self._card_status_label.setText("未配置 Cookie，无法执行任务")
            self._card_status_label.setObjectName("captionText")
            self._card_button.setText("立即获取 Cookie")
            self._card_button.setIcon(op_icon(ICON_LOGIN))
            self._summary_label.setVisible(False)
        elif self._state == _VALID:
            self._card_icon_label.setVisible(False)
            self._card_status_label.setText("Cookie 有效")
            self._card_status_label.setObjectName("successText")
            self._card_button.setText("立即执行任务")
            self._card_button.setIcon(op_icon(ICON_RUN))
            self._summary_label.setVisible(True)
            self._refresh_summary_from_history()
        else:  # _EXPIRED
            self._card_icon_label.setVisible(False)
            msg = self._expired_msg or "未知原因"
            self._card_status_label.setText(f"Cookie 失效：{msg}")
            self._card_status_label.setObjectName("dangerText")
            self._card_button.setText("重新登录")
            self._card_button.setIcon(op_icon(ICON_LOGIN))
            self._summary_label.setVisible(False)

    def _refresh_summary_from_history(self) -> None:
        try:
            recent = TaskHistory().load_recent(1)
        except Exception:
            recent = []
        if not recent:
            self._summary_label.setText("暂无任务记录")
            return
        item = recent[0]
        ts = item.get("ts", "")
        summary = item.get("summary", "")
        success = item.get("success", False)
        marker = "成功" if success else "失败"
        self._summary_label.setText(f"最近：{marker} {summary}（{ts}）")

    # ------------------------------------------------------------------
    # 对外
    # ------------------------------------------------------------------
    def refresh_cookie_card(self) -> None:
        """从 CookieStore 判断存在性：无 Cookie → UNCONFIGURED；有 → VALID。"""
        try:
            music_u, csrf, _ = CookieStore().load()
        except Exception:
            music_u, csrf = "", ""
        if not (music_u and csrf):
            self._state = _UNCONFIGURED
        else:
            self._state = _VALID
        self._expired_msg = ""
        self._render()

    def set_cookie_status(self, ok: bool, msg: str = "") -> None:
        """后台验证结果驱动：ok=True → VALID；ok=False → EXPIRED。"""
        if ok:
            self._state = _VALID
            self._expired_msg = ""
        else:
            self._state = _EXPIRED
            self._expired_msg = msg
        self._render()

    def set_last_task_summary(self, msg: str = "") -> None:
        """刷新最近任务摘要（从 TaskHistory 读最近一条；msg 兼容旧调用）。"""
        self._refresh_summary_from_history()

    def show_toast(self, msg: str) -> None:
        """顶部短暂提示，2.5 秒后自动隐藏。"""
        self._toast.setText(msg)
        self._toast.show()
        QTimer.singleShot(2500, self._hide_toast)

    def _hide_toast(self) -> None:
        self._toast.hide()
