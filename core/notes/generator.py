"""批注生成器：默认走本地模板库，可选走外部 LLM。

设计约束（见 docs/DESIGN.md §4、§6）：

- **确定性**：同一首歌、同一个分数，永远生成同一句。种子取 ``work.id``，
  不用 ``random``。这样重跑、补跑、预览和实际提交发出去的话是一致的，
  也才能写测试。
- **永不抛异常**：批注失败不能拖垮评分。任何异常都退化成空字符串（不写批注）。
- **不重复**：同一次运行里尽量不和已经用过的句子撞车；撞了换下一个种子偏移。

配置项（``Config`` / ``setting.json``）::

    note_enabled    bool    是否随评分提交批注，默认 True
    note_source     str     "template"（默认）或 "llm"
    note_max_chars  int     批注长度上限，默认 80
"""
from __future__ import annotations

import zlib
from typing import Any, Dict, Optional

from . import templates

#: 同一次运行里为避开重复句子最多重摇几次。
_MAX_REROLL = 6


def _seed(work: Dict[str, Any], score: str, salt: int = 0) -> int:
    """由歌曲标识与分数算出稳定种子。salt 用于重摇。"""
    key = "|".join((
        str(work.get("id") or ""),
        str(work.get("name") or ""),
        str(work.get("authorName") or ""),
        str(score),
        str(salt),
    ))
    return zlib.crc32(key.encode("utf-8"))


def _pick(pool, seed: int) -> str:
    return pool[seed % len(pool)]


def _sentence(text: str) -> str:
    """句子收尾统一加一个句号，已经有的不重复加。

    简短语气的判断句自带句号，拼接时再补就是「。。」。
    """
    return text if text.endswith("。") else text + "。"


class NoteGenerator:
    """按固定骨架拼一句批注。线程内可复用，内部只记「已用过的句子」。"""

    def __init__(self, config: Optional[Any] = None) -> None:
        self._config = config
        self._used: set[str] = set()

    # ------------------------------------------------------------------
    # 配置读取（config 可能为 None / dict / Config）
    # ------------------------------------------------------------------
    def _get(self, key: str, default: Any = None) -> Any:
        config = self._config
        if config is None:
            return default
        try:
            return config.get(key, default)
        except TypeError:
            return default
        except Exception:
            return default

    @property
    def enabled(self) -> bool:
        return bool(self._get("note_enabled", True))

    @property
    def source(self) -> str:
        source = str(self._get("note_source", "template") or "template").strip().lower()
        return source if source in ("template", "llm") else "template"

    @property
    def max_chars(self) -> int:
        try:
            value = int(self._get("note_max_chars", 80))
        except (TypeError, ValueError):
            return 80
        return max(10, min(200, value))

    @property
    def voice(self) -> str:
        """语气：restrained（默认）/ warm / brief。不认识的回落默认。"""
        voice = str(self._get("note_voice", templates.DEFAULT_VOICE) or "").strip().lower()
        return voice if voice in templates.VOICES else templates.DEFAULT_VOICE

    # ------------------------------------------------------------------
    # 生成
    # ------------------------------------------------------------------
    def is_muted(self, work: Dict[str, Any]) -> bool:
        """这首是不是被用户点过"这一首不写批注"。"""
        muted = self._get("note_muted_songs", ()) or ()
        if not muted:
            return False
        keys = {str(work.get("id") or ""), str(work.get("name") or "")}
        keys.discard("")
        try:
            return any(str(item) in keys for item in muted)
        except TypeError:
            return False

    def generate(self, work: Dict[str, Any], score: str) -> str:
        """为某首歌生成一句批注；禁用、被静音或失败时返回空字符串。"""
        if not self.enabled or self.is_muted(work):
            return ""
        try:
            if self.source == "llm":
                from .llm import generate_with_llm
                text = generate_with_llm(work, score, self._config)
                if text:
                    text = self._fit(text)
                    self._used.add(text)
                    return text
            return self.from_template(work, score)
        except Exception:
            return ""

    def from_template(self, work: Dict[str, Any], score: str) -> str:
        """纯本地模板生成，确定性且不联网。"""
        text = ""
        for salt in range(_MAX_REROLL):
            seed = _seed(work, score, salt)
            candidate = self._compose(seed, score, work)
            if candidate and candidate not in self._used:
                text = candidate
                break
        if not text:
            # 全撞车了就接受第一句，总比没有批注好
            text = self._compose(_seed(work, score, 0), score, work)
        text = self._fit(text)
        self._used.add(text)
        return text

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _compose(self, seed: int, score: str, work: Dict[str, Any]) -> str:
        """按种子拼一句。排法也由种子决定，四种轮着来。"""
        tier = templates.tier_for_score(score)
        voice = self.voice
        opener = _pick(templates.openers_for(voice), seed)
        judgement = _pick(templates.judgements_for(voice, tier), seed // 7)

        closer = ""
        closers = templates.closers_for(voice)
        if closers:
            closer = self._fill(_pick(closers, seed // 31), work)

        # 简短语气只有一句；收尾缺失（拿不到歌名）时也不硬凑
        if voice == "brief" or not closer:
            fmt = "single"
        else:
            fmt = templates.FORMATS[seed % len(templates.FORMATS)]

        if fmt == "full":
            return f"{opener}{_sentence(judgement)}{closer}"
        if fmt == "no_closer":
            return f"{opener}{_sentence(judgement)}"
        if fmt == "no_opener":
            return f"{_sentence(judgement)}{closer}"
        return _sentence(judgement)

    @staticmethod
    def _fill(text: str, work: Dict[str, Any]) -> str:
        """把 ``{name}`` 换成歌名；拿不到歌名就返回空串（调用方当没有这句）。"""
        if "{name}" not in text:
            return text
        name = str(work.get("name") or "").strip()
        return text.replace("{name}", name) if name else ""

    def _fit(self, text: str) -> str:
        """把批注压到长度上限内：先丢收尾，再截断判断部分。"""
        text = " ".join(str(text).split())
        limit = self.max_chars
        if len(text) <= limit:
            return text
        # 优先保留前两段（开场 + 判断），收尾是最先可以牺牲的
        parts = text.split("。")
        if len(parts) >= 2:
            kept = "。".join(parts[:-1]) + "。"
            if len(kept) <= limit:
                return kept
        return text[: max(1, limit - 1)].rstrip("，。") + "。"


def build_note(config: Optional[Any], work: Dict[str, Any], score: str) -> str:
    """一次性便捷入口：给一首歌生成批注。"""
    return NoteGenerator(config).generate(work, score)
