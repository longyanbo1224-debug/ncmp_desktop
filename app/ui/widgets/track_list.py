"""曲目表 —— 今日评分的主视角。

旧版把评分过程做成"电平表 + 步骤树 + 日志"，用户看到的是机器在动，
看不到今天评了哪几首歌、每首几分、留下了什么话。曲目表把这三件事
做成屏幕上的实体，设计依据见 ``docs/DESIGN.md`` §4.1。

一行一首：

    01 │ 歌名                              4⁄5   ● 已提交
       │ 歌手 · 03:42
       │ ▏批注：「……」（宋体，像内页上的手写批注）

刻意不做的事：不做卡片、不加阴影、不做每行的圆角、不用星星表示分数。
行与行之间只有一条 1px 细线。
"""
from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from app.ui import theme

#: 单曲状态 → 显示文案（见 docs/DESIGN.md §6 用词表；不要引入同义词）
STATE_TEXT = {
    "pending": "待评",
    "running": "评分中",
    "done": "已提交",
    "skipped": "跳过",
    "failed": "失败",
}

#: 单曲状态 → 圆点颜色（取 theme 的运行时值，跟随明暗主题）
_STATE_COLOR_ATTR = {
    "pending": "PENDING_FILL",
    "running": "RUNNING_FILL",
    "done": "SUCCESS",
    "skipped": "PENDING_FILL",
    "failed": "FAILED",
}

_DOT_PX = 6


def _dot(color: str) -> QLabel:
    """一个 6px 的圆点，颜色跟主题走（用 border-radius 画圆）。"""
    label = QLabel()
    label.setFixedSize(_DOT_PX, _DOT_PX)
    label.setStyleSheet(
        f"background-color: {color}; border-radius: {_DOT_PX // 2}px;")
    return label


def tier_mark(score: str, scale: str = "5") -> str:
    """档位标：4⁄5。用分数斜线（U+2044）而不是 `/`，排版上更像内页标记。"""
    score = str(score or "").strip()
    if not score:
        return ""
    return f"{score}⁄{scale}"


class TrackRow(QWidget):
    """一行曲目。序号 + 歌名 + 歌手 + 档位 + 状态 + 批注。"""

    def __init__(self, index: int, song: str, meta: str = "", parent=None) -> None:
        super().__init__(parent)
        self.song = song
        self.score = ""
        self.state = "pending"
        self.note = ""

        grid = QGridLayout(self)
        grid.setContentsMargins(0, theme.SP_3, 0, theme.SP_3)
        grid.setHorizontalSpacing(theme.SP_3)
        grid.setVerticalSpacing(theme.SP_1)
        grid.setColumnStretch(1, 1)

        self._index = QLabel(f"{index:02d}")
        self._index.setObjectName("trackIndex")
        self._index.setAlignment(Qt.AlignRight | Qt.AlignTop)
        self._index.setFixedWidth(22)
        grid.addWidget(self._index, 0, 0, 2, 1)

        self._name = QLabel(song)
        self._name.setObjectName("trackName")
        self._name.setTextInteractionFlags(Qt.TextSelectableByMouse)
        grid.addWidget(self._name, 0, 1)

        self._tier = QLabel("")
        self._tier.setObjectName("tierMark")
        self._tier.setAlignment(Qt.AlignRight | Qt.AlignTop)
        self._tier.setMinimumWidth(34)
        grid.addWidget(self._tier, 0, 2)

        state_box = QWidget()
        state_lay = QHBoxLayout(state_box)
        state_lay.setContentsMargins(0, 0, 0, 0)
        state_lay.setSpacing(theme.SP_1 + 2)
        self._dot = _dot(theme.PENDING_FILL)
        self._state = QLabel(STATE_TEXT["pending"])
        self._state.setObjectName("trackState")
        state_lay.addWidget(self._dot)
        state_lay.addWidget(self._state)
        state_lay.addStretch(1)
        state_box.setFixedWidth(66)
        grid.addWidget(state_box, 0, 3)

        self._meta = QLabel(meta)
        self._meta.setObjectName("trackMeta")
        grid.addWidget(self._meta, 1, 1, 1, 3)

        # 批注：1px 竖线 + 宋体引文
        note_box = QWidget()
        note_lay = QHBoxLayout(note_box)
        note_lay.setContentsMargins(0, 0, 0, 0)
        note_lay.setSpacing(theme.SP_2)
        self._note_rule = QFrame()
        self._note_rule.setObjectName("noteRule")
        self._note_rule.setFixedWidth(1)
        self._note_label = QLabel("")
        self._note_label.setObjectName("noteText")
        self._note_label.setWordWrap(True)
        self._note_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        note_lay.addWidget(self._note_rule)
        note_lay.addWidget(self._note_label, 1)
        note_box.setVisible(False)
        self._note_box = note_box
        grid.addWidget(note_box, 2, 1, 1, 3)

    # ------------------------------------------------------------------
    def set_meta(self, text: str) -> None:
        self._meta.setText(text)

    def set_score(self, score: str, scale: str = "5") -> None:
        self.score = str(score or "")
        self._tier.setText(tier_mark(self.score, scale))
        # 档位色：高档用墨色（满格），中档退一档，低档用失败色（见设计文档 §4.1）
        try:
            value = int(self.score)
        except (TypeError, ValueError):
            value = 0
        if value >= 4:
            color = theme.INK
        elif value == 3:
            color = theme.MUTED
        else:
            color = theme.FAILED
        self._tier.setStyleSheet(f"color: {color};")

    def set_state(self, state: str) -> None:
        self.state = state if state in STATE_TEXT else "pending"
        self._state.setText(STATE_TEXT[self.state])
        attr = _STATE_COLOR_ATTR.get(self.state, "PENDING_FILL")
        self._dot.setStyleSheet(
            f"background-color: {getattr(theme, attr)};"
            f"border-radius: {_DOT_PX // 2}px;")
        color = theme.INK if self.state == "done" else theme.MUTED
        self._state.setStyleSheet(f"color: {color};")

    def set_note(self, note: str) -> None:
        """设置批注。空字符串时整块收起（不是显示一个空框）。"""
        self.note = str(note or "")
        has_note = bool(self.note)
        self._note_label.setText(self.note)
        self._note_label.setObjectName("noteText" if has_note else "noteTextEmpty")
        try:
            self._note_label.style().polish(self._note_label)
        except Exception:
            pass
        self._note_box.setVisible(has_note)


class TrackList(QWidget):
    """曲目表：一个可滚动的行容器 + 空状态。

    API：
        add(song, meta="", score="", state="done", note="") -> 追加或更新一行
        set_note(song, note) / set_state(song, state)
        mark_pending(song, meta="") -> 预置一行待评（还没轮到它）
        clear()
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._panel = QFrame()
        self._panel.setObjectName("panel")
        panel_lay = QVBoxLayout(self._panel)
        panel_lay.setContentsMargins(theme.SP_4, 0, theme.SP_4, 0)
        panel_lay.setSpacing(0)

        self._rows_box = QWidget()
        self._rows_lay = QVBoxLayout(self._rows_box)
        self._rows_lay.setContentsMargins(0, 0, 0, theme.SP_2)
        self._rows_lay.setSpacing(0)
        self._rows_lay.addStretch(1)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setWidget(self._rows_box)
        panel_lay.addWidget(self._scroll)

        self._empty = QLabel("今天还没有排到曲子。点上面的「立即执行」评一次。")
        self._empty.setObjectName("emptyState")
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setWordWrap(True)
        panel_lay.addWidget(self._empty, 1)

        outer.addWidget(self._panel)

        self._rows: Dict[str, TrackRow] = {}
        self._separators: list[QFrame] = []
        self._update_empty()

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------
    def add(self, song: str, meta: str = "", score: str = "",
            state: str = "done", note: str = "", scale: str = "5") -> TrackRow:
        row = self._rows.get(song)
        if row is None:
            row = self._row_for(song, meta)
        if meta:
            row.set_meta(meta)
        if score:
            row.set_score(score, scale)
        if note:
            row.set_note(note)
        row.set_state(state)
        self._update_empty()
        return row

    def set_note(self, song: str, note: str) -> None:
        row = self._rows.get(song)
        if row is not None:
            row.set_note(note)

    def set_state(self, song: str, state: str) -> None:
        row = self._rows.get(song)
        if row is not None:
            row.set_state(state)

    def mark_pending(self, song: str, meta: str = "") -> TrackRow:
        """预置一行"待评"：列表里先出现，状态等评分结果回来再改。"""
        return self.add(song, meta=meta, state="pending")

    def clear(self) -> None:
        for row in self._rows.values():
            self._rows_lay.removeWidget(row)
            row.deleteLater()
        for sep in self._separators:
            self._rows_lay.removeWidget(sep)
            sep.deleteLater()
        self._rows.clear()
        self._separators.clear()
        self._update_empty()

    def count(self) -> int:
        return len(self._rows)

    def note_count(self) -> int:
        """已提交批注的行数（账本摘要用）。"""
        return sum(1 for row in self._rows.values() if row.note)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _row_for(self, song: str, meta: str) -> TrackRow:
        index = len(self._rows) + 1
        row = TrackRow(index, song, meta)
        row.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        # 插在末尾的 stretch 之前
        self._rows_lay.insertWidget(self._rows_lay.count() - 1, row)
        if index > 1:
            sep = QFrame()
            sep.setObjectName("rowRule")
            self._rows_lay.insertWidget(self._rows_lay.count() - 1, sep)
            self._separators.append(sep)
        self._rows[song] = row
        return row

    def _update_empty(self) -> None:
        has_rows = bool(self._rows)
        self._empty.setVisible(not has_rows)
        self._scroll.setVisible(has_rows)
