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

from app.track_log import clean_score
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
    """档位标：4⁄5。用分数斜线（U+2044）而不是 `/`，排版上更像内页标记。

    先归一化：服务端偶尔返回 ``"4.0"``，原样显示会变成「4.0⁄5」。
    """
    score = clean_score(score)
    if not score:
        return ""
    return f"{score}⁄{scale}"


class TrackRow(QWidget):
    """一行曲目。序号 + 歌名 + 歌手 + 档位 + 状态 + 批注。"""

    def __init__(self, index: int, song: str, meta: str = "", parent=None) -> None:
        super().__init__(parent)
        self.song = song
        self.meta = meta
        #: 曲目表内部去重键：默认歌名；同名不同作品时用「歌名|歌手」区分
        self.track_key = song
        self.group = ""       # base / extra：完成总结要分开计数
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
        self.meta = text
        self._meta.setText(text)

    def set_score(self, score: str, scale: str = "5") -> None:
        # 归一化后再存：外部（服务端 / 旧账本）可能给 "4.0"，
        # 不归一化会显示成 "4.0⁄5"，颜色也会因为 int() 失败掉进低档红色
        self.score = clean_score(score)
        self._tier.setText(tier_mark(self.score, scale))
        # 档位色：高档用墨色（满格），中档退一档，低档用失败色（见设计文档 §4.1）
        value = int(self.score) if self.score else 0
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

        # 不做卡片：和手机端一致，曲目直接坐在页面底色上，只靠行间细线分隔
        self._panel = QWidget()
        panel_lay = QVBoxLayout(self._panel)
        panel_lay.setContentsMargins(0, 0, 0, 0)
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
            state: str = "done", note: str = "", scale: str = "5",
            group: str = "", key: str = "", prefer: str = "pending") -> TrackRow:
        track_key = key or song
        row = self._rows.get(track_key)
        if row is None and key:
            # 兼容只按歌名建键的旧行：歌手一致（或旧行没有歌手）就复用它，
            # 避免同一首歌在曲目表里出现两行
            for candidate in list(self._rows.values()):
                if candidate.song != song:
                    continue
                if candidate.meta and meta and candidate.meta != meta:
                    continue
                self._rows.pop(candidate.track_key, None)
                candidate.track_key = track_key
                self._rows[track_key] = candidate
                row = candidate
                break
        if row is None and not key:
            # 进度 / 批注回调只带歌名：同名的多首作品按「先待评、先无批注」匹配
            row = self._find_song(song, prefer)
            if row is not None:
                track_key = row.track_key
        if row is None:
            row = self._row_for(song, meta, track_key)
        if meta:
            row.set_meta(meta)
        # 分组只在第一次确定：基础任务如果也被额外清单列出来，不能让「extra」
        # 覆盖已有的「base」，否则基础行会被算进额外 15 首上限里裁掉
        if group and not row.group:
            row.group = group
        if score:
            row.set_score(score, scale)
        if note:
            row.set_note(note)
        row.set_state(state)
        self._update_empty()
        return row

    def _find_song(self, song: str, prefer: str = "pending") -> Optional[TrackRow]:
        """按歌名找行；同名多作品时优先待评 / 无批注的那一行。"""
        candidates = [row for row in self._rows.values() if row.song == song]
        if not candidates:
            return None
        if prefer == "pending":
            for row in candidates:
                if row.state == "pending":
                    return row
        for row in candidates:
            if not row.note:
                return row
        return candidates[0]

    def contains_key(self, key: str) -> bool:
        return key in self._rows

    def set_note(self, song: str, note: str) -> None:
        row = self._find_song(song, "note")
        if row is not None:
            row.set_note(note)

    def set_state(self, song: str, state: str) -> None:
        row = self._find_song(song, "pending")
        if row is not None:
            row.set_state(state)

    def meta_of(self, song: str, prefer: str = "pending") -> str:
        """某首歌在曲目表里的歌手（评分回调只带歌名，写账本时用它补全）。

        账本记录若只有歌名，下次按「歌名|歌手」索引时会和曲目表的行对不上；
        桌面端的 ``add()`` 有兜底不会多摆一行，但账本本身会丢歌手。
        """
        row = self._find_song(song, prefer)
        return row.meta if row is not None else ""

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
        """已提交批注的行数（记录摘要用）。"""
        return sum(1 for row in self._rows.values() if row.note)

    def done_count(self) -> int:
        """真正评完的行数。

        不能直接用 ``count()``：列表里还有"待评"的行（今天已评完时也会摆出来），
        拿总行数当成绩会比网易云上实际看到的评分多。
        """
        return sum(1 for row in self._rows.values() if row.state == "done")

    def contains(self, song: str) -> bool:
        return any(row.song == song for row in self._rows.values())

    def count_by_group(self, group: str, state: str | None = "done") -> int:
        """按基础/额外分组计数；state=None 时统计所有行。"""
        return sum(
            1 for row in self._rows.values()
            if row.group == group and (state is None or row.state == state)
        )

    def cap_extra(self, limit: int) -> None:
        """裁剪额外行到每日上限，并把「已提交」排到「待评」前面。

        两个目的：
        1. 额外任务每天最多 15 首（基础 5 + 额外 15 = 20），多出来的旧批次行不展示；
        2. 同一天多次执行时，早上评过的曲库不在本次服务端清单里，是由本机账本
           补回来的，会追加在列表末尾——看上去像"最后几首已经评完了"。这里让
           已提交的连续排在前、待评的连续排在后，页头「今日 N/20」才和行号对得上。

        稳定排序：同组内保持原有先后。评分按待评行的顺序推进，刚评完的那一行
        排序后仍然停在原位（它原本就是待评区的第一行），列表不会来回跳。
        """
        rows = list(self._rows.values())
        extras = [row for row in rows if row.group == "extra"]
        if len(extras) > limit:
            extras.sort(key=lambda row: 0 if row.state == "done" else 1)
            keep = {row.track_key for row in extras[:limit]}
            rows = [
                row for row in rows
                if row.group != "extra" or row.track_key in keep
            ]
        ordered = (
            [row for row in rows if row.group != "extra"]
            + [row for row in rows if row.group == "extra"
               and row.state == "done"]
            + [row for row in rows if row.group == "extra"
               and row.state != "done"]
        )
        current = [row.track_key for row in self._rows.values()]
        if [row.track_key for row in ordered] == current:
            return
        data = [
            (row.track_key, row.song, row.meta, row.score, row.state,
             row.note, row.group)
            for row in ordered
        ]
        self.clear()
        for key, song, meta, score, state, note, group in data:
            self.add(song, meta=meta, score=score, state=state,
                     note=note, group=group, key=key)

    def rows_with_state(self, state: str):
        """某状态的行，供收尾时把「跳过」写进账本。"""
        return [row for row in self._rows.values() if row.state == state]

    def settle_pending(self, state: str = "skipped") -> None:
        """给还挂着"待评"的行收尾。

        今天额度用完（服务端回「没有更多」）或任务结束时，那些没轮到的行会一直
        停在"待评"，看着像程序没跑完。统一改成"跳过"，状态与事实一致。
        """
        for row in self._rows.values():
            if row.state == "pending":
                row.set_state(state)

    def mark_extra_skipped_done(self) -> None:
        """服务端确认今日额外额度已用完时，把未轮到的额外曲目按今日完成计。

        只在「服务端明确返回今日没有更多 / 本地已缓存额度用完」时调用；
        普通取消 / 单首失败留下的「跳过」不会被算成完成。
        """
        for row in self._rows.values():
            if row.state == "skipped" and row.group == "extra":
                row.set_state("done")

    def mark_extra_pending_done(self) -> None:
        """今日额外额度已用完：把未完成的额外行（待评 / 跳过）显示为已完成。

        用于刷新页面时本地已经知道额度用完（无需再等服务端探针）。
        只影响额外分组，基础曲目不受影响。
        """
        for row in self._rows.values():
            if row.group == "extra" and row.state in ("pending", "skipped"):
                row.set_state("done")

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _row_for(self, song: str, meta: str, key: str = "") -> TrackRow:
        index = len(self._rows) + 1
        row = TrackRow(index, song, meta)
        row.track_key = key or song
        row.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        # 插在末尾的 stretch 之前
        self._rows_lay.insertWidget(self._rows_lay.count() - 1, row)
        if index > 1:
            sep = QFrame()
            sep.setObjectName("rowRule")
            self._rows_lay.insertWidget(self._rows_lay.count() - 1, sep)
            self._separators.append(sep)
        self._rows[row.track_key] = row
        return row

    def _update_empty(self) -> None:
        has_rows = bool(self._rows)
        self._empty.setVisible(not has_rows)
        self._scroll.setVisible(has_rows)
