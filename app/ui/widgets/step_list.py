"""结构化步骤视图。

每行渲染一个步骤，状态用 QIcon 显示（成功 fa5s.check-circle / 进行中 fa5s.spinner /
失败 fa5s.times-circle / 等待 fa5s.circle / 已取消 fa5s.ban）。
步骤下面带歌曲子项，显示评分进度（done/total、歌名、分数）。

使用 ``QTreeWidget`` 实现：top-level 节点是步骤，子节点是歌曲。
"""
from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QLabel, QHeaderView,
)

from app.ui.icons import STEP_TEXTS, step_icon


class StepList(QWidget):
    """步骤+歌曲进度视图。

    API：
        addStep(name, status, elapsed) -> 新增一个步骤
        updateStep(name, status, elapsed) -> 更新已有步骤状态
        addProgress(done, total, song, score) -> 在当前 running 步骤下挂歌曲子项
        clear() -> 清空
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._title = QLabel("任务步骤")
        self._title.setObjectName("sectionTitle")
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["项目", "状态", "用时/评分"])
        self._tree.setIndentation(12)
        self._tree.setUniformRowHeights(True)
        self._tree.setAlternatingRowColors(True)
        # 自动拉伸第 0 列
        header = self._tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._layout.addWidget(self._title)
        # 空状态占位（树为空时显示，有步骤时隐藏）
        self._empty_label = QLabel("等待任务启动…")
        self._empty_label.setObjectName("emptyState")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._layout.addWidget(self._empty_label)
        self._layout.addWidget(self._tree, 1)
        # name -> QTreeWidgetItem
        self._step_items: Dict[str, QTreeWidgetItem] = {}

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------
    def addStep(self, name: str, status: str, elapsed: float = 0.0) -> None:
        """新增步骤；如已存在则更新。"""
        item = self._step_items.get(name)
        if item is None:
            item = QTreeWidgetItem([name, STEP_TEXTS.get(status, STEP_TEXTS["pending"]),
                                     self._fmt_elapsed(elapsed)])
            self._apply_icon(item, status)
            self._tree.addTopLevelItem(item)
            self._step_items[name] = item
        else:
            self._apply_status(item, status, elapsed)
        # 确保可见
        self._tree.scrollToItem(item)
        # 已有步骤，隐藏空状态占位
        self._empty_label.setVisible(False)

    def updateStep(self, name: str, status: str, elapsed: float = 0.0) -> None:
        """更新步骤状态。不存在则创建。"""
        self.addStep(name, status, elapsed)

    def addProgress(self, done: int, total: int, song: str, score: str) -> None:
        """在当前 running 步骤下挂歌曲子项。"""
        parent = self._find_running_step()
        if parent is None:
            # 没有正在跑的步骤，挂在临时根节点
            parent = self._ensure_misc_parent()
        child = QTreeWidgetItem(parent, [
            song,
            f"{done}/{total}" if total else str(done),
            f"{score} 分" if score else "",
        ])
        child.setData(0, Qt.UserRole, "song")
        parent.setExpanded(True)
        self._tree.scrollToItem(child)

    def clear(self) -> None:
        self._tree.clear()
        self._step_items.clear()
        self._empty_label.setVisible(True)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    @staticmethod
    def _apply_icon(item: QTreeWidgetItem, status: str) -> None:
        """把状态对应的 QIcon 贴到第 0 列（项目名前）。"""
        try:
            item.setIcon(0, step_icon(status))
        except Exception:
            pass

    def _apply_status(self, item: QTreeWidgetItem, status: str, elapsed: float) -> None:
        item.setText(1, STEP_TEXTS.get(status, STEP_TEXTS["pending"]))
        self._apply_icon(item, status)
        item.setData(0, Qt.UserRole, status)
        if status == "running":
            item.setText(2, self._fmt_elapsed(elapsed))
        elif status == "success":
            item.setText(2, self._fmt_elapsed(elapsed))

    def _find_running_step(self) -> Optional[QTreeWidgetItem]:
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            if item.data(0, Qt.UserRole) == "running":
                return item
        return None

    def _ensure_misc_parent(self) -> QTreeWidgetItem:
        if "评分进度" in self._step_items:
            return self._step_items["评分进度"]
        item = QTreeWidgetItem(["评分进度", STEP_TEXTS["pending"], ""])
        self._apply_icon(item, "pending")
        self._tree.addTopLevelItem(item)
        self._step_items["评分进度"] = item
        return item

    @staticmethod
    def _fmt_elapsed(elapsed: float) -> str:
        if elapsed is None or elapsed <= 0:
            return ""
        if elapsed < 60:
            return f"{elapsed:.1f}s"
        minutes = int(elapsed // 60)
        seconds = elapsed - minutes * 60
        return f"{minutes}m{seconds:.0f}s"
