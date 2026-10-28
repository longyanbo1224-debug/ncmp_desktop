"""音乐合伙人积分/等级：一次只读查询 + 称号换算。

账号上真正"有账"的数字：云贝余额、VIP 等级、成长总值、本期/本周积分。
拿不到就返回空字典——界面上"没数据就不显示"，绝不填 0 假装有收益
（这条是参考 ncmm：它把"未知"和"0"分开渲染，我们照做）。

接口字段名各版本不一致，所以每个展示项都配一串候选字段名，按顺序取第一个有值的。

称号按**本期积分**换算（见 :data:`TITLES`），阈值来自用户提供的一手规则：
320 分高级（可维持身份）、400 分资深、480 分首席。
"""
from typing import Any, Dict, List, Optional, Tuple

HOME_URL = "https://interface.music.163.com/weapi/music/partner/home/get"

#: 展示名 → 候选字段名
FIELDS = (
    ("云贝余额", ("cloudBean", "cloudBeanCount", "cloudVillageBean", "cloud_bean")),
    ("VIP 等级", ("vipType", "vipLevel", "vip_type", "level")),
    ("成长总值", ("growthValue", "growth_value", "growth")),
    ("本期积分", ("periodIntegral", "period_integral", "integral", "periodScore")),
    ("本周积分", ("weekIntegral", "week_integral", "weekScore")),
)

#: 称号阈值（积分下限, 称号），按分数升序
TITLES: Tuple[Tuple[int, str], ...] = (
    (320, "高级音乐合伙人"),
    (400, "资深音乐合伙人"),
    (480, "首席音乐合伙人"),
)

#: 低于第一个阈值时的称号
BELOW_FIRST = "未达保级线"


def _flatten(node: Any, out: Dict[str, Any]) -> None:
    """把嵌套 dict/list 摊平成一层，外层同名字段优先（setdefault）。"""
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                _flatten(value, out)
            else:
                out.setdefault(str(key), value)
    elif isinstance(node, list):
        for item in node:
            _flatten(item, out)


def parse_points(payload: Dict[str, Any]) -> Dict[str, str]:
    """从接口返回里挑出要展示的数字。纯函数，方便测。"""
    flat: Dict[str, Any] = {}
    _flatten(payload, flat)
    result: Dict[str, str] = {}
    for label, keys in FIELDS:
        for key in keys:
            value = flat.get(key)
            if value is None or value == "":
                continue
            result[label] = str(value)
            break
    return result


def score_of(points: Dict[str, str]) -> Optional[int]:
    """取用于称号换算的分数：本期积分优先，否则第一个能解析成整数里的分数字段。"""
    for label in ("本期积分", "合伙人积分"):
        value = points.get(label)
        parsed = _to_int(value)
        if parsed is not None:
            return parsed
    for label, value in points.items():
        if "积分" in label:
            parsed = _to_int(value)
            if parsed is not None:
                return parsed
    return None


def _to_int(value: Any) -> Optional[int]:
    try:
        text = str(value).strip().replace(",", "")
        return int(float(text))
    except (TypeError, ValueError):
        return None


def title_for(score: Optional[int]) -> Dict[str, Any]:
    """积分 → 当前称号、下一档称号与差额、以及完整阈值表。

    返回 ``{"label": str, "next_label": str|None, "gap": int|None,
    "table": [(threshold, label), ...]}``；分数未知时 label 为空串。
    """
    table: List[Tuple[int, str]] = list(TITLES)
    if score is None:
        return {"label": "", "next_label": None, "gap": None, "table": table}

    label = BELOW_FIRST
    next_label: Optional[str] = None
    gap: Optional[int] = None
    for threshold, name in table:
        if score >= threshold:
            label = name
        elif next_label is None:
            next_label = name
            gap = threshold - score

    return {"label": label, "next_label": next_label, "gap": gap, "table": table}


def fetch_points(session, logger=None) -> Dict[str, str]:
    """查询一次积分/等级；任何失败都返回空字典（不影响任务本身）。"""
    try:
        from core.signer import Signer

        signer = Signer(session, "", logger, None)
        csrf = str(session.cookies.get("__csrf") or "")
        params = {
            "params": signer._get_params({"csrf_token": csrf}),
            "encSecKey": signer._get_enc_sec_key(),
        }
        response = session.post(
            f"{HOME_URL}?csrf_token={csrf}", data=params, timeout=15).json()
        if response.get("code") != 200:
            if logger is not None:
                logger.debug(f"查询合伙人积分失败：{response.get('message', '未知错误')}")
            return {}
        data = response.get("data") or {}
        # 把原始字段打出来（debug 级）：接口字段名各版本不一致，
        # 只有看到真实名字才能补准候选表，而不是继续猜。
        if logger is not None:
            flat: Dict[str, Any] = {}
            _flatten(data, flat)
            logger.debug(f"合伙人积分原始字段：{flat}")
        return parse_points(data)
    except Exception as e:
        if logger is not None:
            logger.debug(f"查询合伙人积分异常：{e}")
        return {}
