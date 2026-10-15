"""登录页 —— 一块面板。

扫码 Tab：二维码 + 状态文字 + 重新生成按钮。
密码 Tab：手机号 + 明文密码 + MD5 密码 + 登录按钮。

每个 Tab 上只有一件"白色的东西"（二维码框或输入框），视线不会散。
密码表单限宽 520px——一行 40 个汉字左右的表单最好读。

通过 ``LoginWorker`` 信号异步更新 UI，避免阻塞主线程。
"""
import hashlib

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
    QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from app.login.pwd_login import PwdLogin
from app.login.qr_login import QrLogin
from app.ui import theme
from app.ui.icons import eye_icon
from app.workers.login_worker import LoginWorker

# 二维码显示边长
_QR_SIZE = 240


class LoginPage(QWidget):
    """登录页（扫码 + 密码双通道）。

    外层是 QWidget 而不是直接继承 QTabWidget——否则标签栏会顶到窗口边缘，
    页面自己拿不到上边距。
    """

    login_succeeded = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._worker = LoginWorker()

        root = QVBoxLayout(self)
        root.setContentsMargins(theme.PAGE_MARGIN, theme.SP_5,
                                theme.PAGE_MARGIN, theme.PAGE_MARGIN)
        root.setSpacing(0)

        self._tabs = QTabWidget()
        root.addWidget(self._tabs)
        self._tabs.addTab(self._build_qr_tab(), "扫码登录")
        self._tabs.addTab(self._build_pwd_tab(), "密码登录")
        self._connect_signals()

    # ------------------------------------------------------------------
    # 对外
    # ------------------------------------------------------------------
    def start(self) -> None:
        """启动扫码模式（首次进入页面时调用）。"""
        self.start_qr()

    def start_qr(self) -> None:
        """重新生成二维码并启动扫码流程。"""
        self._worker.start_qr()

    # ------------------------------------------------------------------
    # 扫码 Tab
    # ------------------------------------------------------------------
    def _build_qr_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(theme.SP_4, theme.SP_4,
                                  theme.SP_4, theme.SP_4)
        layout.setSpacing(theme.SP_3)

        tip = QLabel("用网易云音乐 App 扫描下方二维码")
        tip.setObjectName("subtitle")
        tip.setAlignment(Qt.AlignCenter)
        layout.addWidget(tip)

        layout.addSpacing(theme.SP_2)

        self._qr_label = QLabel("等待二维码生成…")
        self._qr_label.setAlignment(Qt.AlignCenter)
        self._qr_label.setFixedSize(_QR_SIZE, _QR_SIZE)
        self._qr_label.setObjectName("qrFrame")
        self._qr_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        layout.addWidget(self._qr_label, 0, Qt.AlignHCenter)

        self._qr_status_label = QLabel("")
        self._qr_status_label.setObjectName("captionText")
        self._qr_status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._qr_status_label)

        layout.addSpacing(theme.SP_2)

        row = QHBoxLayout()
        row.addStretch(1)
        regen_btn = QPushButton("重新生成二维码")
        regen_btn.setObjectName("secondaryButton")
        regen_btn.clicked.connect(self.start_qr)
        row.addWidget(regen_btn)
        row.addStretch(1)
        layout.addLayout(row)

        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------
    # 密码 Tab
    # ------------------------------------------------------------------
    def _build_pwd_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, theme.SP_4, 0, theme.SP_4)
        layout.setSpacing(theme.SP_2)
        layout.addWidget(self._field_label("手机号"))
        self._phone_edit = QLineEdit()
        self._phone_edit.setPlaceholderText("11 位手机号，如 13800138000")
        layout.addWidget(self._phone_edit)

        layout.addSpacing(theme.SP_2)

        # 明文密码
        pwd_head = QHBoxLayout()
        pwd_head.setSpacing(theme.SP_2)
        pwd_head.addWidget(self._field_label("明文密码"))
        pwd_head.addStretch(1)
        layout.addLayout(pwd_head)
        self._pwd_edit = QLineEdit()
        self._pwd_edit.setEchoMode(QLineEdit.Password)
        self._pwd_edit.setPlaceholderText("明文密码（与 MD5 二选一）")
        layout.addWidget(self._pwd_edit)

        layout.addSpacing(theme.SP_2)

        # MD5 密码
        md5_head = QHBoxLayout()
        md5_head.setSpacing(theme.SP_2)
        md5_head.addWidget(self._field_label("MD5 密码"))
        md5_head.addStretch(1)
        layout.addLayout(md5_head)
        self._md5_edit = QLineEdit()
        self._md5_edit.setEchoMode(QLineEdit.Password)
        self._md5_edit.setPlaceholderText("MD5 密码（更安全，推荐）")
        layout.addWidget(self._md5_edit)

        # 两个密码框各自的显隐开关（放输入框右内侧）
        self._pwd_eye = self._attach_eye(self._pwd_edit)
        self._md5_eye = self._attach_eye(self._md5_edit)

        layout.addSpacing(theme.SP_3)

        to_md5_btn = QPushButton("转成 MD5")
        to_md5_btn.setObjectName("secondaryButton")
        to_md5_btn.clicked.connect(self._convert_to_md5)
        layout.addWidget(to_md5_btn)

        layout.addSpacing(theme.SP_3)

        login_btn = QPushButton("登录")
        login_btn.setObjectName("primaryButton")
        login_btn.clicked.connect(self._on_pwd_login_clicked)
        layout.addWidget(login_btn)

        self._pwd_status_label = QLabel("")
        self._pwd_status_label.setObjectName("captionText")
        self._pwd_status_label.setWordWrap(True)
        layout.addWidget(self._pwd_status_label)

        # 表单限宽并居中——拉满 800px 宽的手机号输入框没有意义
        host = QWidget()
        host.setLayout(layout)
        host.setFixedWidth(520)
        outer.addWidget(host, 0, Qt.AlignHCenter)
        outer.addStretch(2)
        return page

    @staticmethod
    def _field_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("captionText")
        return label

    @staticmethod
    def _attach_eye(edit: QLineEdit) -> QToolButton:
        """给密码框挂一个显隐开关。

        用 ``QToolButton`` 而不是 ``QCheckBox``：QCheckBox 即使设了 icon
        也仍会画一个勾选框，眼睛旁边多一个方框很难看。

        按钮直接放进 QLineEdit 自己的布局里（Qt 官方"清除按钮"的做法），
        由布局负责定位和随窗口缩放，不用手写 resizeEvent。
        """
        eye = QToolButton(edit)
        eye.setCheckable(True)
        eye.setIcon(eye_icon(False))
        eye.setIconSize(QSize(15, 15))
        eye.setCursor(Qt.PointingHandCursor)
        eye.setToolTip("显示密码")
        eye.setAutoRaise(True)
        eye.setFixedSize(22, 22)

        def _on_toggle(checked: bool) -> None:
            edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
            eye.setIcon(eye_icon(checked))
            eye.setToolTip("隐藏密码" if checked else "显示密码")

        eye.toggled.connect(_on_toggle)

        row = QHBoxLayout(edit)
        row.setContentsMargins(0, 0, 5, 0)
        row.setSpacing(0)
        row.addStretch(1)
        row.addWidget(eye)
        # 文字别跑到眼睛底下
        edit.setTextMargins(0, 0, 26, 0)
        return eye

    # ------------------------------------------------------------------
    # 槽
    # ------------------------------------------------------------------
    def _connect_signals(self) -> None:
        self._worker.qr_ready.connect(self._on_qr_ready)
        self._worker.qr_status.connect(self._on_qr_status)
        self._worker.login_result.connect(self._on_login_result)

    def _on_qr_ready(self, img_bytes: bytes) -> None:
        pixmap = QPixmap()
        if not pixmap.loadFromData(img_bytes, "PNG"):
            self._qr_label.setText("二维码加载失败")
            return
        scaled = pixmap.scaled(
            _QR_SIZE - 32, _QR_SIZE - 32, Qt.KeepAspectRatio,
            Qt.SmoothTransformation)
        self._qr_label.setPixmap(scaled)

    def _on_qr_status(self, text: str) -> None:
        self._qr_status_label.setText(text)

    def _on_login_result(self, ok: bool, msg: str) -> None:
        obj = "successText" if ok else "dangerText"
        self._pwd_status_label.setText(msg)
        self._pwd_status_label.setObjectName(obj)
        self._qr_status_label.setText("登录成功" if ok else msg)
        self._qr_status_label.setObjectName(obj)
        if ok:
            # 通知 MainWindow 跳回首页并刷新 Cookie 卡片
            self.login_succeeded.emit()

    # ------------------------------------------------------------------
    # 密码 Tab 行为
    # ------------------------------------------------------------------
    def _convert_to_md5(self) -> None:
        plain = self._pwd_edit.text().strip()
        if not plain:
            self._pwd_status_label.setText("请先输入明文密码")
            self._pwd_status_label.setObjectName("dangerText")
            return
        md5 = hashlib.md5(plain.encode("utf-8")).hexdigest()
        self._md5_edit.setText(md5)
        self._pwd_edit.clear()
        self._pwd_status_label.setText("已转换为 MD5 并填入 MD5 字段（明文已清空）。")
        self._pwd_status_label.setObjectName("successText")

    def _on_pwd_login_clicked(self) -> None:
        phone = self._phone_edit.text().strip()
        if not phone:
            self._pwd_status_label.setText("请输入手机号")
            self._pwd_status_label.setObjectName("dangerText")
            return
        md5 = self._md5_edit.text().strip()
        plain = self._pwd_edit.text().strip()
        if md5:
            self._pwd_status_label.setText("登录中…")
            self._pwd_status_label.setObjectName("captionText")
            self._worker.start_pwd(phone, md5, use_md5=True)
        elif plain:
            self._pwd_status_label.setText("登录中…")
            self._pwd_status_label.setObjectName("captionText")
            self._worker.start_pwd(phone, plain, use_md5=False)
        else:
            self._pwd_status_label.setText("请至少填写一种密码")
            self._pwd_status_label.setObjectName("dangerText")
