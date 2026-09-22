"""ncmp desktop 核心逻辑层（基于 ACAne0320/ncmp 改造）。"""


class CancelledError(Exception):
    """用户取消任务时抛出。"""
    pass
