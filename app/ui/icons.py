"""图标中心：集中管理 qtawesome 图标定义与语义色。

所有 UI 模块应优先通过本模块取图标，避免散落 emoji 字符与 QStyle 标准图标。

配色一律取自 :mod:`app.ui.theme`——本模块不再自带色值。

图标包用 **Phosphor**（``ph.*``）而不是 Font Awesome（``fa5s.*``）：
Phosphor 的线条粗细更配这套仪器感的界面，而 fa5s 是能选到的最模板化的一档。
qtawesome 1.4.2 内置的是 Phosphor 1.3.0，缺 ``circle-notch`` / ``window`` /
``radio-button`` / ``list-checks`` 四个名字，已用等价图标替代。
"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

import qtawesome as qta

from app.ui import theme

# 默认前景色（与 QSS 文字主色一致）
DEFAULT_COLOR = theme.INK

# 语义色（转发 theme，保留旧名字以免调用方大改）
COLOR_PRIMARY = theme.BRAND
COLOR_SUCCESS = theme.SUCCESS
COLOR_DANGER = theme.FAILED
COLOR_RUNNING = theme.RUNNING_FILL
COLOR_PENDING = theme.PENDING_FILL

# ----------------------------------------------------------------------
# 图标名称常量
# ----------------------------------------------------------------------
# 导航图标
NAV_ICONS = {
    "home": "ph.house",
    "account": "ph.key",
    "task": "ph.play-circle",
    "settings": "ph.gear-six",
    "about": "ph.info",
}

# 步骤状态图标
STEP_ICONS = {
    "success": "ph.check-circle",
    "running": "ph.spinner-gap",
    "failed": "ph.x-circle",
    "pending": "ph.circle",
    "cancelled": "ph.prohibit",
}

# 步骤状态对应的语义色
STEP_COLORS = {
    "success": theme.SUCCESS,
    "running": theme.RUNNING_FILL,
    "failed": theme.FAILED,
    "pending": theme.PENDING_FILL,
    "cancelled": theme.PENDING_FILL,
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
ICON_RUN = "ph.play"
ICON_REFRESH = "ph.arrows-clockwise"
ICON_LOGIN = "ph.sign-in"
ICON_EYE = "ph.eye"
ICON_EYE_OFF = "ph.eye-slash"

# 托盘品牌图标（网易云音乐相关，用音符）
ICON_APP = "ph.music-notes"

# 托盘菜单图标
ICON_SHOW_MAIN = "ph.browsers"
ICON_QUIT = "ph.power"
ICON_ABOUT = "ph.info"

# 空状态图标（未配置 / 无历史 / 无步骤）
ICON_EMPTY_DASHBOARD = "ph.key"              # 首页未配置 Cookie
ICON_EMPTY_HISTORY = "ph.clock"              # 无任务历史
ICON_EMPTY_STEPS = "ph.hourglass-medium"     # 无步骤 / 等待启动

# 结果图标（任务完成后的状态行 / 历史摘要）
ICON_RESULT_OK = "ph.check-circle"
ICON_RESULT_FAIL = "ph.x-circle"


# ----------------------------------------------------------------------
# 构造函数
# ----------------------------------------------------------------------
def _icon(name: str, color: str = DEFAULT_COLOR) -> QIcon:
    """按图标名 + 颜色构造 QIcon；名字不存在时降级到一个安全图标。"""
    try:
        return qta.icon(name, color=color)
    except Exception:
        try:
            return qta.icon("ph.circle", color=color)
        except Exception:
            return QIcon()


def nav_icon(key: str) -> QIcon:
    """取导航图标。

    返回的 QIcon 带两个模式：**未选中是墨色，选中是品牌红**——
    选中项是浅红底＋品牌红字，图标跟着变红才对得上。
    Qt 的列表委托在选中时会用 ``QIcon.Selected`` 模式取图，所以这样能自动切换。
    """
    name = NAV_ICONS[key]
    icon = _icon(name, theme.INK)
    try:
        selected = _icon(name, theme.BRAND)
        for size in (16, 18, 20, 24, 32):
            pm = selected.pixmap(size, size)
            if not pm.isNull():
                icon.addPixmap(pm, QIcon.Selected)
    except Exception:
        pass
    return icon


def step_icon(status: str) -> QIcon:
    """取步骤状态图标（带语义色）。未知状态回退到 pending。"""
    name = STEP_ICONS.get(status, STEP_ICONS["pending"])
    color = STEP_COLORS.get(status, theme.PENDING_FILL)
    return _icon(name, color)


def op_icon(name: str, color: str = DEFAULT_COLOR) -> QIcon:
    """通用操作图标：传入 ``ph.*`` 名 + 颜色。"""
    return _icon(name, color)


def eye_icon(visible: bool) -> QIcon:
    """密码显隐切换：visible=True 时显示 eye，False 时显示 eye-slash。"""
    return _icon(ICON_EYE if visible else ICON_EYE_OFF, theme.MUTED)


def result_icon(ok: bool) -> QIcon:
    """任务结果图标：成功绿勾 / 失败红叉。"""
    return _icon(ICON_RESULT_OK if ok else ICON_RESULT_FAIL,
                 theme.SUCCESS if ok else theme.FAILED)


def create_app_icon(size: int = 256) -> QIcon:
    """绘制品牌图标：品牌红圆角方底 + 白色音符居中。

    刻意用**圆角方形**而不是圆形：圆形红底＋白色音符就是网易云音乐自己的商标，
    这是第三方非官方程序，不该做得像官方图标。圆角方形同色系但不混淆。

    用 QPainter 在透明 QPixmap 上画：
      1. 圆角矩形（半径 = size // 5）填品牌红
      2. 叠加白色音符图标，尺寸 = size * 0.56，居中
    返回 QIcon(pixmap)，Qt 自动多分辨率缩放。
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        radius = max(2, size // 5)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.BRAND))
        painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)
        icon = _icon(ICON_APP, theme.PANEL)
        icon_size = int(size * 0.56)
        margin = (size - icon_size) // 2
        icon.paint(painter, margin, margin, icon_size, icon_size)
    finally:
        painter.end()
    return QIcon(pixmap)


def app_icon() -> QIcon:
    """托盘/窗口品牌图标。"""
    return create_app_icon()
