"""评分策略：把"档位"翻译成"这首歌得几分"。

抽成纯函数的原因有两个：

1. **可以预览。** 今天拉回来的歌单在不提交、不联网的前提下就能算出四种策略
   各会给出什么结果（见 :func:`compare`），用户选策略时看到的是后果而不是标签。
2. **可以测试。** 判定规则是这套程序里唯一会影响"账号上留下什么"的逻辑，
   它不该藏在一个带网络请求的类里。

判定规则本身沿用旧版：歌名 + 歌手名里有没有拉丁字母。它是个粗糙的启发式，
但改它会改变所有老用户的历史结果，所以这次只做搬家，不改规则。
"""
import re
from typing import Dict, Iterable, List

#: 策略 → 展示名（与设置页下拉框、预览文案共用）
STRATEGIES: Dict[int, str] = {
    1: "1-2 分",
    2: "2-3 分",
    3: "3-4 分（默认）",
    4: "固定 4 分",
}

#: 默认策略（3-4 分）
DEFAULT_STRATEGY = 3

_NAME_PATTERN = re.compile(r".*[a-zA-Z].*")


def has_latin(work: dict) -> bool:
    """歌名或歌手名里是否含拉丁字母。"""
    try:
        text = str(work.get("name") or "") + str(work.get("authorName") or "")
    except AttributeError:
        return False
    return bool(_NAME_PATTERN.match(text))


def score_for(work: dict, strategy: int = DEFAULT_STRATEGY) -> str:
    """按策略得出这首歌应得的分数（字符串，接口要的就是字符串）。"""
    try:
        strategy = int(strategy)
    except (TypeError, ValueError):
        strategy = DEFAULT_STRATEGY
    latin = has_latin(work)
    if strategy == 1:
        return "2" if latin else "1"
    if strategy == 2:
        return "3" if latin else "2"
    if strategy == 3:
        return "4" if latin else "3"
    return "4"


def tag_for(score: str) -> str:
    """评分标签（接口的 ``tags`` 字段）：``4-A-1``。"""
    return f"{score}-A-1"


def preview(works: Iterable[dict], strategy: int = DEFAULT_STRATEGY) -> List[dict]:
    """逐首算出分数，供界面预览。"""
    rows = []
    for work in works:
        score = score_for(work, strategy)
        rows.append({
            "name": str(work.get("name") or ""),
            "artist": str(work.get("authorName") or ""),
            "score": score,
        })
    return rows


def compare(works: Iterable[dict]) -> Dict[int, Dict[str, int]]:
    """四种策略各会给出什么结果：``{策略: {"1": n, "2": n, ...}}``。

    这是"配置项变成看得见的选择"的核心：同一份今日歌单，四个答案。
    """
    works = list(works)
    result: Dict[int, Dict[str, int]] = {}
    for strategy in STRATEGIES:
        counts: Dict[str, int] = {}
        for work in works:
            score = score_for(work, strategy)
            counts[score] = counts.get(score, 0) + 1
        result[strategy] = counts
    return result


def describe(counts: Dict[str, int]) -> str:
    """把 ``{"4": 2, "3": 3}`` 说成人话：``2 首 4 分、3 首 3 分``。"""
    if not counts:
        return "今天没有可评的曲子"
    parts = []
    for score in sorted(counts, key=lambda s: int(s), reverse=True):
        parts.append(f"{counts[score]} 首 {score} 分")
    return "、".join(parts)
