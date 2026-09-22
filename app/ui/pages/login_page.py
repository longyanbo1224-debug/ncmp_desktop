"""登录页：扫码 Tab + 密码 Tab。

扫码 Tab：QLabel 显示二维码 + 状态文字 + 重新生成按钮。
密码 Tab：手机号 + 明文密码（带 eye 切换显隐）+ MD5 密码 + 明文转MD5 按钮 + 登录按钮。

通过 ``LoginWorker`` 信号异步更新 UI，避免阻塞主线程。
"""
import hashlib
import io

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QTabWidget, QVBoxLayout, QWidget,
)

from app.login.pwd_login import PwdLogin
from app.login.qr_login import QrLogin
from app.ui.icons import eye_icon
from app.workers.login_worker import LoginWorker


class LoginPage(QTabWidget):
    """登录页（扫码 + 密码双通道）。"""

    login_succeeded = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._worker = LoginWorker()
        self._connect_signals()
        self.addTab(self._build_qr_tab(), "扫码登录")
        self.addTab(self._build_pwd_tab(), "密码登录")
        # 启动扫码（worker 内部会判断 pyncm 是否可用）

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
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        tip = QLabel("使用网易云音乐 APP 扫描下方二维码登录")
        tip.setAlignment(Qt.AlignCenter)
        layout.addWidget(tip)

        self._qr_label = QLabel("等待二维码生成…")
        self._qr_label.setAlignment(Qt.AlignCenter)
        self._qr_label.setMinimumSize(240, 240)
        self._qr_label.setObjectName("qrFrame")
        self._qr_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        layout.addWidget(self._qr_label)

        self._qr_status_label = QLabel("")
        self._qr_status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._qr_status_label)

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
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)

        layout.addWidget(QLabel("手机号"))
        self._phone_edit = QLineEdit()
        self._phone_edit.setPlaceholderText("11 位手机号，如 13800138000")
        layout.addWidget(self._phone_edit)

        # 明文密码（带 eye 图标切换 echo mode）
        pwd_row1 = QHBoxLayout()
        pwd_row1.addWidget(QLabel("明文密码"))
        pwd_row1.addStretch(1)
        show_plain = QCheckBox()
        show_plain.setToolTip("显示/隐藏明文")
        show_plain.setIcon(eye_icon(False))
        pwd_row1.addWidget(show_plain)
        layout.addLayout(pwd_row1)
        self._pwd_edit = QLineEdit()
        self._pwd_edit.setEchoMode(QLineEdit.Password)
        self._pwd_edit.setPlaceholderText("明文密码（二选一）")
        show_plain.toggled.connect(
            lambda checked: (
                self._pwd_edit.setEchoMode(
                    QLineEdit.Normal if checked else QLineEdit.Password),
                show_plain.setIcon(eye_icon(checked)),
            ))
        layout.addWidget(self._pwd_edit)

        # MD5 密码
        pwd_row2 = QHBoxLayout()
        pwd_row2.addWidget(QLabel("MD5 密码"))
        pwd_row2.addStretch(1)
        show_md5 = QCheckBox()
        show_md5.setToolTip("显示/隐藏 MD5")
        show_md5.setIcon(eye_icon(False))
        pwd_row2.addWidget(show_md5)
        layout.addLayout(pwd_row2)
        self._md5_edit = QLineEdit()
        self._md5_edit.setEchoMode(QLineEdit.Password)
        self._md5_edit.setPlaceholderText("MD5 密码（更安全，推荐）")
        show_md5.toggled.connect(
            lambda checked: (
                self._md5_edit.setEchoMode(
                    QLineEdit.Normal if checked else QLineEdit.Password),
                show_md5.setIcon(eye_icon(checked)),
            ))
        layout.addWidget(self._md5_edit)

        # 明文转 MD5 按钮
        to_md5_btn = QPushButton("明文 → MD5")
        to_md5_btn.setObjectName("secondaryButton")
        to_md5_btn.clicked.connect(self._convert_to_md5)
        layout.addWidget(to_md5_btn)

        layout.addSpacing(8)
        login_btn = QPushButton("登录")
        login_btn.setObjectName("primaryButton")
        login_btn.clicked.connect(self._on_pwd_login_clicked)
        layout.addWidget(login_btn)

        self._pwd_status_label = QLabel("")
        self._pwd_status_label.setWordWrap(True)
        layout.addWidget(self._pwd_status_label)

        layout.addStretch(1)
        return page

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
        # 等比缩放到合理大小
        scaled = pixmap.scaled(
            220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._qr_label.setPixmap(scaled)

    def _on_qr_status(self, text: str) -> None:
        self._qr_status_label.setText(text)

    def _on_login_result(self, ok: bool, msg: str) -> None:
        if ok:
            self._pwd_status_label.setText(msg)
            self._pwd_status_label.setObjectName("successText")
            self._qr_status_label.setText("登录成功")
            self._qr_status_label.setObjectName("successText")
            # 通知 MainWindow 跳回首页并刷新 Cookie 卡片
            self.login_succeeded.emit()
        else:
            self._pwd_status_label.setText(msg)
            self._pwd_status_label.setObjectName("dangerText")
            self._qr_status_label.setText(msg)
            self._qr_status_label.setObjectName("dangerText")

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
