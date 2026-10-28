"""音乐合伙人积分/等级：一次只读查询。

账号上真正"有账"的数字：云贝余额、VIP 等级、成长总值、本期/本周积分。
拿不到就返回空字典——界面上"没数据就不显示"，绝不填 0 假装有收益
（这条是参考 ncmm：它把"未知"和"0"分开渲染，我们照做）。

接口字段名各版本不一致，所以每个展示项都配一串候选字段名，按顺序取第一个有值的。
"""
from typing import Any, Dict

HOME_URL = "https://interface.music.163.com/weapi/music/partner/home/get"

#: 展示名 → 候选字段名
FIELDS = (
    ("云贝余额", ("cloudBean", "cloudBeanCount", "cloudVillageBean", "cloud_bean")),
    ("VIP 等级", ("vipType", "vipLevel", "vip_type", "level")),
    ("成长总值", ("growthValue", "growth_value", "growth")),
    ("本期积分", ("periodIntegral", "period_integral", "integral", "periodScore")),
    ("本周积分", ("weekIntegral", "week_integral", "weekScore")),
)


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
        return parse_points(response.get("data") or {})
    except Exception as e:
        if logger is not None:
            logger.debug(f"查询合伙人积分异常：{e}")
        return {}
