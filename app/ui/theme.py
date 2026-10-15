"""设计变量（design tokens）与样式表生成。

本模块是**全程序唯一的颜色／字体／尺寸来源**。页面代码不得再硬编码色值，
一律 ``from app.ui import theme`` 后取常量。

设计主张：**颜色只用来表示状态，品牌红只用来表示"可交互"。**
详见仓库根目录 ``DESIGN.md``。

QSS 由 :func:`build_qss` 在运行时生成，不再有 ``light.qss`` 文件——
避免"改了 theme.py 忘了重新生成 qss"的漂移。
"""
from __future__ import annotations

import os
import sys
from string import Template

# ----------------------------------------------------------------------
# 颜色 —— 中性色（五个）
# ----------------------------------------------------------------------
GROUND = "#F5F5F5"   # 页面底色：中性浅灰，网易云那套白底＋灰底的分层
PANEL = "#FFFFFF"    # 读数面板：输入框、日志、二维码框、卡片
INK = "#1A1A1A"      # 主要文字
MUTED = "#6B6B6B"    # 次要文字、说明文字、等待状态的文字（对比度 4.89:1）
RULE = "#E5E5E5"     # 细线、边框

# ----------------------------------------------------------------------
# 颜色 —— 品牌色
# ----------------------------------------------------------------------
# 网易云音乐的品牌红。用 #C20C0C 而不是他们界面上的亮红 #EC4141：
# 亮红当文字只有 3.57:1、配白字当按钮只有 3.89:1，两边都不达标；
# #C20C0C 当文字 5.75:1、配白字 6.27:1，两种用法都够。
BRAND = "#C20C0C"
BRAND_HOVER = "#A50A0A"
BRAND_PRESSED = "#8C0808"
BRAND_DISABLED = "#E3A9A9"
# 选中态用的浅红底（导航、标签页）
BRAND_SOFT = "rgba(194, 12, 12, 0.08)"
BRAND_SOFT_HOVER = "rgba(194, 12, 12, 0.14)"

# ----------------------------------------------------------------------
# 颜色 —— 状态色（四个，每个只有一个含义）
# ----------------------------------------------------------------------
# 进行中：琥珀。**只能当填充色**——当文字色对比度只有 2.55:1，不达标。
#
# 为什么"进行中"不用品牌红：如果进行中也是红的，那么"正在跑"和"失败了"
# 就是同一个颜色，而且和主按钮撞车。琥珀把"正在干活"独立出来，
# 品牌红专职表示"可交互"，两者互不干扰。
RUNNING_FILL = "#E8A33D"
RUNNING_TEXT = "#8A5A0A"   # 琥珀色的文字替代，对比度 5.43:1

SUCCESS = "#2C7549"        # 成功
FAILED = "#B3352B"         # 失败（比品牌红更闷一点的砖红，靠图标＋"失败"二字再区分）
PENDING_TEXT = MUTED       # 等待（文字）：就是次要色，语义一致
PENDING_FILL = "#808080"   # 等待（图标）：≥3:1，符合非文字控件要求

# 任务状态 → 颜色。StepList / 电平表 / 状态行共用这一张表。
STATE_FILL = {
    "running": RUNNING_FILL,
    "success": SUCCESS,
    "failed": FAILED,
    "pending": PENDING_FILL,
    "cancelled": PENDING_FILL,
}
STATE_TEXT = {
    "running": RUNNING_TEXT,
    "success": SUCCESS,
    "failed": FAILED,
    "pending": PENDING_TEXT,
    "cancelled": PENDING_TEXT,
}

# 任务状态 → QSS 里的语义 objectName（状态行靠改 objectName + repolish 换色）
STATE_OBJECT = {
    "success": "successText",
    "failed": "dangerText",
    "cancelled": "warningText",
    "running": "captionText",
}


def state_fill(state: str) -> str:
    """取某状态对应的填充色；未知状态回退到等待灰。"""
    return STATE_FILL.get(state, PENDING_FILL)


def state_text(state: str) -> str:
    """取某状态对应的文字色；未知状态回退到等待灰。"""
    return STATE_TEXT.get(state, PENDING_TEXT)


# ----------------------------------------------------------------------
# 中性色的派生（悬停／按下／禁用），不对外暴露为语义
# ----------------------------------------------------------------------
_HOVER_BG = "#F2F2F2"      # 白底控件悬停
_PRESSED_BG = "#EBEBEB"    # 白底控件按下
_DISABLED_BG = "#F0F0F0"   # 禁用底
_DISABLED_FG = "#B0B0B0"   # 禁用文字
_DISABLED_BORDER = "#E8E8E8"
_HOVER_BORDER = "#D0D0D0"
_METER_TRACK = "#E0E0E0"   # 电平表未点亮的格子
_SCROLL_HANDLE = "#CCCCCC"
_SCROLL_HANDLE_HOVER = "#B0B0B0"
METER_TRACK = _METER_TRACK

# ----------------------------------------------------------------------
# 字体
# ----------------------------------------------------------------------
# 前两个是随包分发的子集化字体（OFL，见 app/ui/fonts/OFL.txt）；
# 后面是系统降级链，保证没有随包字体时也不会难看。
FONT_DISPLAY = ('"NCMP Serif SC", "Noto Serif SC", "Source Han Serif SC", '
                '"Songti SC", SimSun, serif')
FONT_UI = ('"NCMP Sans SC", "Noto Sans SC", "Source Han Sans SC", '
           '"HarmonyOS Sans SC", "Microsoft YaHei UI", sans-serif')
FONT_DATA = 'Consolas, "Cascadia Mono", monospace'

# 字号阶梯。
#
# 用户反馈内容区整体偏大（不只是字，输入框也跟着大），所以整体收一档：
# 正文 14 → 13，控件内边距同步缩小，输入框高度从 38px 降到 ~31px。
# 13px 是 Windows 中文桌面程序最主流的正文尺寸，网易云自己也是这一档。
#
# 比值 34/20/15/13/12 —— 底部三档挨得近是 UI 阶梯的正常形态，
# 正文和说明本来就不需要拉开距离，靠字重和颜色区分就够。
FS_DISPLAY = 34
FS_TITLE = 20
FS_HEADING = 15
FS_BODY = 13
FS_CAPTION = 12
FS_DATA = 12

# ----------------------------------------------------------------------
# 圆角与间距
# ----------------------------------------------------------------------
# 控件变小后圆角也要跟着收，否则 6px 圆角配 31px 高的按钮会显得肥。
R_CONTROL = 4
R_PANEL = 6

SP_1, SP_2, SP_3, SP_4, SP_5, SP_6, SP_7 = 4, 8, 12, 16, 24, 32, 48

PAGE_MARGIN = SP_5      # 页面边距 24（原 32，配合整体收一档）
GROUP_GAP = SP_5        # 分组之间 24

# ----------------------------------------------------------------------
# 左侧导航
# ----------------------------------------------------------------------
# 140px 时单项只需要 80px，装得下但**比例太瘦**（140/1100 = 12.7%），
# 看起来像一条细缝。加到 176（16%）才对得上常见侧栏的比例。
NAV_WIDTH = 176
NAV_ICON = 18

# ----------------------------------------------------------------------
# 表单列宽上限
# ----------------------------------------------------------------------
# 设置页原来让输入框横跨整个内容区（实测 677px，占可用宽 79%）。
# 13px 汉字宽 13px，扣掉标签列后正文控制在 40 字以内，落在可读区间。
FORM_MAX_WIDTH = 620
CAPTION_MAX_WIDTH = 560

# ----------------------------------------------------------------------
# 窗口
# ----------------------------------------------------------------------
WINDOW_DEFAULT = (1100, 760)
WINDOW_MINIMUM = (900, 640)

# 电平表格数（40 格 = 每格 2.5%）
METER_SEGMENTS = 40
METER_HEIGHT = 12
METER_GAP = 3

# ----------------------------------------------------------------------
# 路径
# ----------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))


def resource_path(*parts: str) -> str:
    """资源路径解析：PyInstaller 打包后从 ``sys._MEIPASS`` 读，开发模式从源码目录读。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, *parts)
    return os.path.join(os.path.dirname(_HERE), *parts)


def fonts_dir() -> str:
    """随包字体目录。"""
    return resource_path("ui", "fonts")


def assets_dir() -> str:
    """随包样式资源目录（勾选图标等）。"""
    return resource_path("ui", "styles")


def _qss_url(path: str) -> str:
    """把本地路径转成 QSS 里 url() 能用的形式（统一正斜杠）。"""
    return path.replace("\\", "/")


_CHECK_PNG = _qss_url(os.path.join(assets_dir(), "check.png"))


# ----------------------------------------------------------------------
# 样式表
# ----------------------------------------------------------------------
_QSS = Template("""
/* ==================================================================
   ncmp desktop —— 由 app/ui/theme.py 生成，请勿手工编辑本文件。
   改样式请改 theme.py 里的变量或下面的模板。
   ================================================================== */

/* ---- 基础 ---- */
QWidget {
    background-color: $GROUND;
    color: $INK;
    font-family: $FONT_UI;
    font-size: ${FS_BODY}px;
}

QMainWindow, QWidget#centralWidget, QStackedWidget {
    background-color: $GROUND;
}

/* 标签／复选框自己不带底，否则在白色面板里会露出一块底色方块 */
QLabel, QCheckBox, QRadioButton, QGroupBox {
    background: transparent;
}

/* ---- 左侧导航 ---- */
QListWidget#navList {
    background-color: $PANEL;
    border: none;
    border-right: 1px solid $RULE;
    outline: none;
    padding: ${SP_3}px ${SP_3}px;
}

QListWidget#navList::item {
    padding: 8px ${SP_4}px;
    border: none;
    border-radius: ${R_CONTROL}px;
    color: $INK;
}

QListWidget#navList::item:hover {
    background-color: $BRAND_SOFT;
}

QListWidget#navList::item:selected {
    background-color: $BRAND_SOFT;
    color: $BRAND;
    font-weight: 600;
}

/* ---- 按钮 ---- */
QPushButton {
    background-color: $PANEL;
    color: $INK;
    border: 1px solid $RULE;
    border-radius: ${R_CONTROL}px;
    padding: 6px 14px;
    min-height: 16px;
}

QPushButton:hover {
    background-color: $HOVER_BG;
    border-color: $HOVER_BORDER;
}

QPushButton:pressed {
    background-color: $PRESSED_BG;
}

QPushButton:disabled {
    color: $DISABLED_FG;
    background-color: $DISABLED_BG;
    border-color: $DISABLED_BORDER;
}

/* 键盘焦点：边框加粗到 2px 的同时把内边距各减 1px，
   控件外框尺寸完全不变，不会引起重排。 */
QPushButton:focus {
    border: 2px solid $BRAND;
    padding: 5px 13px;
}

/* 主按钮：网易云品牌红实心。 */
QPushButton#primaryButton {
    background-color: $BRAND;
    color: $PANEL;
    border: 1px solid $BRAND;
    font-weight: 600;
}

QPushButton#primaryButton:hover {
    background-color: $BRAND_HOVER;
    border-color: $BRAND_HOVER;
}

QPushButton#primaryButton:pressed {
    background-color: $BRAND_PRESSED;
    border-color: $BRAND_PRESSED;
}

QPushButton#primaryButton:disabled {
    background-color: $BRAND_DISABLED;
    border-color: $BRAND_DISABLED;
    color: #FFFFFF;
}

/* 红底上再用红焦点框看不见，换墨色 */
QPushButton#primaryButton:focus {
    border: 2px solid $INK;
    padding: 5px 13px;
}

/* 次按钮：白底描边，就是默认按钮的样子（保留 objectName 以便语义清晰） */
QPushButton#secondaryButton {
    background-color: $PANEL;
    color: $INK;
    border: 1px solid $RULE;
}

QPushButton#secondaryButton:hover {
    background-color: $HOVER_BG;
    border-color: $HOVER_BORDER;
}

/* 文字按钮：无边框，用于次要动作 */
QPushButton#textButton {
    background: transparent;
    border: 1px solid transparent;
    color: $BRAND;
    padding: 6px 8px;
}

QPushButton#textButton:hover {
    background-color: $BRAND_SOFT;
}

QPushButton#dangerButton {
    background-color: $PANEL;
    color: $FAILED;
    border: 1px solid $RULE;
}

QPushButton#dangerButton:hover {
    border-color: $FAILED;
}

/* 纯图标按钮（密码显隐的眼睛） */
QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: ${R_CONTROL}px;
    padding: 3px;
}

QToolButton:hover {
    background-color: $BRAND_SOFT;
}

QToolButton:checked {
    background-color: $BRAND_SOFT;
}

QToolButton:focus {
    border: 2px solid $BRAND;
    padding: 2px;
}

/* ---- 输入控件 ---- */
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {
    background-color: $PANEL;
    color: $INK;
    border: 1px solid $RULE;
    border-radius: ${R_CONTROL}px;
    padding: 5px 8px;
    selection-background-color: $BRAND;
    selection-color: $PANEL;
}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {
    border: 2px solid $BRAND;
    padding: 4px 7px;
}

QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled,
QPlainTextEdit:disabled, QTextEdit:disabled {
    background-color: $DISABLED_BG;
    color: $DISABLED_FG;
}

QLineEdit:read-only {
    background-color: $DISABLED_BG;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox QAbstractItemView {
    background-color: $PANEL;
    border: 1px solid $RULE;
    border-radius: ${R_CONTROL}px;
    padding: 4px;
    selection-background-color: $BRAND_SOFT;
    selection-color: $BRAND;
    outline: none;
}

/* 日志：唯一的等宽面板 */
QPlainTextEdit#logView {
    background-color: $PANEL;
    border: 1px solid $RULE;
    border-radius: ${R_PANEL}px;
    padding: ${SP_3}px;
    color: $INK;
}

/* ---- 面板 ---- */
QFrame#panel, QFrame#card, QFrame#cookieCard {
    background-color: $PANEL;
    border: 1px solid $RULE;
    border-radius: ${R_PANEL}px;
}

/* 一条细线（分组之间的分隔、设置页的分组标题下划线） */
QFrame#rule {
    background-color: $RULE;
    border: none;
    min-height: 1px;
    max-height: 1px;
}

/* ---- 文字分级 ---- */
QLabel#pageTitle {
    font-family: $FONT_DISPLAY;
    font-size: ${FS_TITLE}px;
    font-weight: 600;
    color: $INK;
}

/* 首页那句状态陈述。全界面唯一的展示级文字。 */
QLabel#displayStatement {
    font-family: $FONT_DISPLAY;
    font-size: ${FS_DISPLAY}px;
    font-weight: 700;
    color: $INK;
}

QLabel#sectionTitle, QLabel#sectionHeading {
    font-size: ${FS_HEADING}px;
    font-weight: 600;
    color: $INK;
}

QLabel#subtitle {
    color: $MUTED;
    font-size: ${FS_BODY}px;
}

QLabel#captionText {
    color: $MUTED;
    font-size: ${FS_CAPTION}px;
}

/* 等宽数字：记录表、分数、耗时、百分比 */
QLabel#dataText {
    font-family: $FONT_DATA;
    font-size: ${FS_DATA}px;
    color: $INK;
}

QLabel#dataTextMuted {
    font-family: $FONT_DATA;
    font-size: ${FS_DATA}px;
    color: $MUTED;
}

QLabel#brandText  { color: $BRAND; }
QLabel#successText { color: $SUCCESS; }
QLabel#dangerText  { color: $FAILED; }
QLabel#warningText { color: $RUNNING_TEXT; }
QLabel#infoText    { color: $INK; }

QLabel#emptyState {
    color: $MUTED;
    font-size: ${FS_BODY}px;
}

/* 首页顶部提示条：品牌红实心，2.5 秒后消失 */
QLabel#toast {
    background-color: $BRAND;
    color: $PANEL;
    border-radius: ${R_CONTROL}px;
    padding: 12px 16px;
    font-size: ${FS_BODY}px;
}

/* ---- 应用内通知气泡（右下角，见 widgets/toast.py）----
   系统托盘气泡的样式由操作系统决定，改不了，所以自己画一个。 */
QWidget#toastPanel {
    background-color: $PANEL;
    border: 1px solid $RULE;
    border-radius: ${R_PANEL}px;
}

QLabel#toastTitle {
    background: transparent;
    font-size: ${FS_BODY}px;
    font-weight: 600;
    color: $INK;
}

QLabel#toastBody {
    background: transparent;
    font-size: ${FS_CAPTION}px;
    color: $MUTED;
}

/* ---- 步骤树 ---- */
QTreeWidget {
    background-color: $PANEL;
    border: 1px solid $RULE;
    border-radius: ${R_PANEL}px;
    outline: none;
    alternate-background-color: $PANEL;
}

QTreeWidget::item {
    padding: 7px 2px;
    border: none;
}

QTreeWidget::item:hover {
    background-color: $HOVER_BG;
}

QTreeWidget::item:selected {
    background-color: $BRAND_SOFT;
    color: $INK;
}

QHeaderView::section {
    background-color: $PANEL;
    color: $MUTED;
    font-size: ${FS_CAPTION}px;
    padding: 8px ${SP_3}px;
    border: none;
    border-bottom: 1px solid $RULE;
}

/* ---- 滚动条 ---- */
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: $SCROLL_HANDLE;
    border-radius: 6px;
    min-height: 36px;
}

QScrollBar::handle:vertical:hover {
    background: $SCROLL_HANDLE_HOVER;
}

QScrollBar:horizontal {
    background: transparent;
    height: 12px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background: $SCROLL_HANDLE;
    border-radius: 6px;
    min-width: 36px;
}

QScrollBar::handle:horizontal:hover {
    background: $SCROLL_HANDLE_HOVER;
}

QScrollBar::add-line, QScrollBar::sub-line {
    height: 0;
    width: 0;
    border: none;
    background: none;
}

QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
}

/* ---- 菜单 ---- */
QMenu {
    background-color: $PANEL;
    border: 1px solid $RULE;
    border-radius: ${R_CONTROL}px;
    padding: ${SP_1}px;
}

QMenu::item {
    padding: 8px ${SP_5}px;
    border-radius: ${R_CONTROL}px;
}

QMenu::item:selected {
    background-color: $BRAND_SOFT;
    color: $BRAND;
}

QMenu::separator {
    height: 1px;
    background: $RULE;
    margin: ${SP_1}px ${SP_2}px;
}

/* ---- 标签页：和导航一样，选中是浅红底＋品牌红字 ---- */
QTabWidget::pane {
    border: none;
    background: transparent;
}

QTabBar {
    background: transparent;
}

QTabBar::tab {
    background: transparent;
    color: $MUTED;
    padding: 9px 20px;
    border: 1px solid transparent;
    border-radius: ${R_CONTROL}px;
    margin-right: ${SP_1}px;
    font-size: ${FS_BODY}px;
}

QTabBar::tab:hover {
    color: $BRAND;
    background: $BRAND_SOFT;
}

QTabBar::tab:selected {
    background: $BRAND_SOFT;
    color: $BRAND;
    font-weight: 600;
}

QTabBar::tab:focus {
    border: 1px solid $BRAND;
}

/* ---- 复选框 ---- */
QCheckBox {
    spacing: 8px;
    color: $INK;
}

QCheckBox::indicator {
    width: 17px;
    height: 17px;
}

QCheckBox::indicator:unchecked {
    background-color: $PANEL;
    border: 1px solid $HOVER_BORDER;
    border-radius: ${R_CONTROL}px;
}

QCheckBox::indicator:unchecked:hover {
    border-color: $BRAND;
}

QCheckBox::indicator:checked {
    background-color: $BRAND;
    border: 1px solid $BRAND;
    border-radius: ${R_CONTROL}px;
    image: url("$CHECK_PNG");
}

QCheckBox::indicator:disabled {
    background-color: $DISABLED_BG;
    border-color: $DISABLED_BORDER;
}

QCheckBox::indicator:focus {
    border: 2px solid $INK;
}

/* ---- 二维码框 ---- */
QLabel#qrFrame {
    background: $PANEL;
    border: 1px solid $RULE;
    border-radius: ${R_PANEL}px;
}

/* ---- 对话框 ---- */
QDialog {
    background-color: $PANEL;
}

/* 消息框：默认的 Fusion 样式在这里明显跟别处脱节，
   背景、文字、按钮全部拉齐到本程序的尺寸和配色。 */
QMessageBox {
    background-color: $PANEL;
}

QMessageBox QLabel {
    background: transparent;
    color: $INK;
    font-size: ${FS_BODY}px;
}

QMessageBox QPushButton {
    min-width: 80px;
    padding: 6px 14px;
}

/* ---- 工具提示 ---- */
QToolTip {
    background-color: #3C3C3C;
    color: $PANEL;
    border: none;
    padding: 7px ${SP_3}px;
    border-radius: ${R_CONTROL}px;
    font-size: ${FS_CAPTION}px;
}
""")


def build_qss() -> str:
    """生成完整样式表。"""
    return _QSS.substitute(
        GROUND=GROUND, PANEL=PANEL, INK=INK, MUTED=MUTED, RULE=RULE,
        BRAND=BRAND, BRAND_HOVER=BRAND_HOVER, BRAND_PRESSED=BRAND_PRESSED,
        BRAND_DISABLED=BRAND_DISABLED,
        BRAND_SOFT=BRAND_SOFT, BRAND_SOFT_HOVER=BRAND_SOFT_HOVER,
        HOVER_BG=_HOVER_BG, PRESSED_BG=_PRESSED_BG,
        DISABLED_BG=_DISABLED_BG, DISABLED_FG=_DISABLED_FG,
        DISABLED_BORDER=_DISABLED_BORDER, HOVER_BORDER=_HOVER_BORDER,
        SCROLL_HANDLE=_SCROLL_HANDLE,
        SCROLL_HANDLE_HOVER=_SCROLL_HANDLE_HOVER,
        RUNNING_FILL=RUNNING_FILL, RUNNING_TEXT=RUNNING_TEXT,
        SUCCESS=SUCCESS, FAILED=FAILED,
        FONT_DISPLAY=FONT_DISPLAY, FONT_UI=FONT_UI, FONT_DATA=FONT_DATA,
        FS_BODY=FS_BODY, FS_TITLE=FS_TITLE, FS_DISPLAY=FS_DISPLAY,
        FS_HEADING=FS_HEADING, FS_CAPTION=FS_CAPTION, FS_DATA=FS_DATA,
        R_CONTROL=R_CONTROL, R_PANEL=R_PANEL,
        SP_1=SP_1, SP_2=SP_2, SP_3=SP_3, SP_4=SP_4, SP_5=SP_5, SP_6=SP_6,
        CHECK_PNG=_CHECK_PNG,
    )


def load_bundled_fonts() -> int:
    """把 ``app/ui/fonts/`` 下的随包字体注册进 Qt。返回成功加载的数量。

    没有随包字体时返回 0，此时字体栈自动降级到系统字体（见 ``FONT_*``）。
    """
    from PySide6.QtGui import QFontDatabase

    directory = fonts_dir()
    if not os.path.isdir(directory):
        return 0
    loaded = 0
    for name in sorted(os.listdir(directory)):
        if not name.lower().endswith((".ttf", ".otf")):
            continue
        try:
            if QFontDatabase.addApplicationFont(os.path.join(directory, name)) != -1:
                loaded += 1
        except Exception:
            pass
    return loaded


def reduced_motion() -> bool:
    """Windows 上是否关掉了窗口动画（"在 Windows 中显示动画"）。

    关掉时跳过电平表那一下 250ms 的闪亮。非 Windows 返回 False。
    """
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Control Panel\Desktop\WindowMetrics",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MinAnimate")
            return str(value).strip() == "0"
    except Exception:
        return False


def apply_theme(app) -> None:
    """把主题套到 QApplication 上：Fusion 风格 + 随包字体 + 生成的样式表。

    用 Fusion 而不是 Windows 原生风格：Fusion 对各控件的渲染更一致，
    也更听 QSS 的话，不会出现原生控件和新配色打架的情况。
    """
    try:
        app.setStyle("Fusion")
    except Exception:
        pass
    load_bundled_fonts()
    try:
        app.setStyleSheet(build_qss())
    except Exception:
        pass
