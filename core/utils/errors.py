"""任务失败原因分类。

原来失败一律显示「任务执行失败」，但对非技术用户来说，
网络超时 / 风控拦截 / Cookie 失效是三件完全不同的事，
处理方式也完全不同（等一会重试 / 调大等待时间 / 重新登录）。
这里按异常类型和错误文案分五类，并给出对应的下一步建议。

分类顺序很关键：**网络类优先判**。因为 ``验证用户信息失败: <内层异常>``
这种包装过的消息里既有"验证用户信息"（像 Cookie 问题）又有网络错误的原文，
先判网络才不会误报成 Cookie 失效。
"""
from __future__ import annotations

import re
from typing import List, Tuple

COOKIE = "cookie"
RISK = "risk"
NETWORK = "network"
API = "api"
UNKNOWN = "unknown"

#: 分类 → 给人看的标签
LABELS = {
    COOKIE: "Cookie 失效",
    RISK: "风控拦截",
    NETWORK: "网络异常",
    API: "接口返回错误",
    UNKNOWN: "未知错误",
}

#: 分类 → 下一步建议（界面上显示，也进失败邮件）
HINTS = {
    COOKIE: "到「账号」页重新扫码登录，Cookie 恢复后定时任务会自动继续。",
    RISK: "网易限制了请求频率。别马上重试——把「等待时间」调大一点，"
          "或者换一个执行时间。",
    NETWORK: "网络不通或超时。检查网络后重试；如果开着代理或 VPN，"
             "关掉再试一次。",
    API: "网易接口返回了非预期结果。稍后重试；如果反复出现，"
         "把「设置 → 运行日志」里的日志附上反馈。",
    UNKNOWN: "打开「任务」页看日志，里面有具体的报错原文。",
}

#: 网络类失败可以自动重试一次；其余一律不重试
RETRYABLE = frozenset({NETWORK})

_NETWORK_KEYWORDS = (
    "timeout", "timed out", "connection", "max retries", "unreachable",
    "name resolution", "proxy", "ssl", "network", "网络", "超时", "连接",
)
_RISK_KEYWORDS = (
    "风控", "频繁", "操作过于", "限制", "异常流量", "安全验证", "验证码",
    "cheat", "risk",
)
_COOKIE_KEYWORDS = (
    "需要登录", "未登录", "登录已过期", "登录失效", "登录状态",
    "cookie", "获取用户信息失败", "认证", "鉴权",
)

#: 从 ``(响应码: -460)`` 这种文案里抠出数字
_CODE_RE = re.compile(r"响应码[:：]\s*(-?\d+)")

_RISK_CODES = {"-460", "-461", "-462", "8821"}
_COOKIE_CODES = {"301", "-2", "-10", "250"}


def _chain(exc) -> List[BaseException]:
    """把异常链摊平（``raise ... from ...`` 会串成 __cause__）。"""
    out: List[BaseException] = []
    seen = set()
    cur = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        out.append(cur)
        cur = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)
    return out


def _is_network_exception(exc) -> bool:
    """异常链里有没有 requests 的网络类异常。"""
    try:
        import requests
    except Exception:
        return False
    types = (
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
        requests.exceptions.SSLError,
        requests.exceptions.ProxyError,
        requests.exceptions.ChunkedEncodingError,
    )
    return any(isinstance(e, types) for e in _chain(exc))


def _text(exc) -> str:
    return " ".join(str(e) for e in _chain(exc)).lower()


def _codes(text: str) -> List[str]:
    return _CODE_RE.findall(text)


def classify(exc) -> Tuple[str, str, str]:
    """把异常归到五类之一。

    :returns: ``(分类, 标签, 下一步建议)``。``exc`` 为 None 时返回「未知」。
    """
    if exc is None:
        return UNKNOWN, LABELS[UNKNOWN], HINTS[UNKNOWN]

    text = _text(exc)
    codes = set(_codes(str(exc)))

    # 1. 网络类优先：包装过的消息里同时含"验证用户信息"和网络错误原文，
    #    先判网络才不会误报成 Cookie 失效
    if _is_network_exception(exc) or any(k in text for k in _NETWORK_KEYWORDS):
        return NETWORK, LABELS[NETWORK], HINTS[NETWORK]

    # 2. 风控
    if codes & _RISK_CODES or any(k in text for k in _RISK_KEYWORDS):
        return RISK, LABELS[RISK], HINTS[RISK]

    # 3. Cookie
    if codes & _COOKIE_CODES or any(k in text for k in _COOKIE_KEYWORDS):
        return COOKIE, LABELS[COOKIE], HINTS[COOKIE]

    # 4. 接口明确返回了错误码
    if codes:
        return API, LABELS[API], HINTS[API]

    return UNKNOWN, LABELS[UNKNOWN], HINTS[UNKNOWN]
