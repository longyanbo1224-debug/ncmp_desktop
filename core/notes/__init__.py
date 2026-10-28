"""批注（乐评文案）生成。

评分提交时的 ``comment`` 字段原来恒为空字符串，本模块负责把它填上：
默认用本地模板库（确定性、离线、可测），可选接用户自己的 LLM。
详见 ``docs/DESIGN.md`` §4、§6 与 ``core/notes/templates.py`` 里的两条底线。
"""
from .generator import NoteGenerator, build_note
from .templates import CLOSERS, JUDGEMENTS, OPENERS, tier_for_score

__all__ = [
    "NoteGenerator",
    "build_note",
    "tier_for_score",
    "OPENERS",
    "JUDGEMENTS",
    "CLOSERS",
]
