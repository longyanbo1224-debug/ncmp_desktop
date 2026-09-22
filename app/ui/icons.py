"""图标中心：集中管理 qtawesome 图标定义与语义色。

所有 UI 模块应优先通过本模块取图标，避免散落 emoji 字符与 QStyle 标准图标。

颜色用 QSS 已定语义色：
    success  #2E7DDE（运行中蓝）
    primary  #2E7DDE
    danger   #C62828
    success-fg #2E9E55
    muted    #9aa4b2
    default  #1f2933
"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

import qtawesome as qta

# 默认前景色（与 QSS 文字主色一致）
DEFAULT_COLOR = "#1f2933"

# 语义色（与 app/ui/styles.qss 对齐）
COLOR_PRIMARY = "#2E7DDE"
COLOR_SUCCESS = "#2E9E55"
COLOR_DANGER = "#C62828"
COLOR_RUNNING = "#2E7DDE"
COLOR_PENDING = "#9aa4b2"

# ----------------------------------------------------------------------
# 图标名称常量
# ----------------------------------------------------------------------
# 导航图标（fa5s = Font Awesome 5 Solid）
NAV_ICONS = {
    "home": "fa5s.home",
    "account": "fa5s.key",
    "task": "fa5s.play-circle",
    "settings": "fa5s.cog",
    "about": "fa5s.info-circle",
}

# 步骤状态图标
STEP_ICONS = {
    "success": "fa5s.check-circle",
    "running": "fa5s.spinner",
    "failed": "fa5s.times-circle",
    "pending": "fa5s.circle",
    "cancelled": "fa5s.ban",
}

# 步骤状态对应的语义色
STEP_COLORS = {
    "success": COLOR_SUCCESS,
    "running": COLOR_RUNNING,
    "failed": COLOR_DANGER,
    "pending": COLOR_PENDING,
    "cancelled": COLOR_DANGER,
}

# 步骤状态对应的简短文字（用于无障碍/复制场景）
STEP_TEXTS = {
    "success": "成功",
    "running": "进行中",
    "failed": "失败",
    "pending": "等待",
    "cancelled": "已取消",
}

# 操作图标
ICON_RUN = "fa5s.play"
ICON_REFRESH = "fa5s.sync-alt"
ICON_LOGIN = "fa5s.sign-in-alt"
ICON_EYE = "fa5s.eye"
ICON_EYE_OFF = "fa5s.eye-slash"

# 托盘品牌图标（网易云音乐相关，用 music 图标）
ICON_APP = "fa5s.music"

# 托盘菜单图标
ICON_SHOW_MAIN = "fa5s.window-restore"
ICON_QUIT = "fa5s.power-off"
ICON_ABOUT = "fa5s.info-circle"

# 空状态图标（未配置 / 无历史 / 无步骤）
ICON_EMPTY_DASHBOARD = "fa5s.key"            # 首页未配置 Cookie
ICON_EMPTY_HISTORY = "fa5s.clock"            # 无任务历史
ICON_EMPTY_STEPS = "fa5s.hourglass-half"     # 无步骤 / 等待启动


# ----------------------------------------------------------------------
# 构造函数
# ----------------------------------------------------------------------
def _icon(name: str, color: str = DEFAULT_COLOR) -> QIcon:
    """按 fa5s 图标名 + 颜色构造 QIcon。"""
    return qta.icon(name, color=color)


def nav_icon(key: str) -> QIcon:
    """取导航图标（默认主色）。"""
    return _icon(NAV_ICONS[key], COLOR_PRIMARY)


def step_icon(status: str) -> QIcon:
    """取步骤状态图标（带语义色）。未知状态回退到 pending。"""
    name = STEP_ICONS.get(status, STEP_ICONS["pending"])
    color = STEP_COLORS.get(status, COLOR_PENDING)
    return qta.icon(name, color=color)


def op_icon(name: str, color: str = DEFAULT_COLOR) -> QIcon:
    """通用操作图标：传入 fa5s.* 名 + 颜色。"""
    return _icon(name, color)


def eye_icon(visible: bool) -> QIcon:
    """密码显隐切换：visible=True 时显示 eye，False 时显示 eye-slash。"""
    return _icon(ICON_EYE if visible else ICON_EYE_OFF)


def create_app_icon(size: int = 256) -> QIcon:
    """绘制品牌图标：圆角方形主色蓝底 + 白色音乐元素居中。

    用 QPainter 在透明 QPixmap 上画：
      1. 圆角矩形（半径 = size // 6）填主色 #2E7DDE
      2. 叠加白色 fa5s.music 图标，尺寸 = size * 0.6，居中
    返回 QIcon(pixmap)，Qt 自动多分辨率缩放。
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        # 圆角方形底
        radius = max(2, size // 6)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(COLOR_PRIMARY))
        painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)
        # 叠加白色 music 图标居中
        icon = qta.icon(ICON_APP, color="#ffffff")
        icon_size = int(size * 0.6)
        margin = (size - icon_size) // 2
        icon.paint(painter, margin, margin, icon_size, icon_size)
    finally:
        painter.end()
    return QIcon(pixmap)


def app_icon() -> QIcon:
    """托盘/窗口品牌图标。"""
    return create_app_icon()
