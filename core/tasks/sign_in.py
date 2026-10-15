"""每日签到。

接口：``POST /weapi/point/dailyTask``，参数 ``{"type": "0"}``（0=移动端）。

这是 WeAPI，需要加密。**直接复用 pyncm 现成的 ``WeapiCryptoRequest``**：
它是个装饰器工厂（``_BaseWrapper`` 包过），用法是**拿它装饰自己写的端点函数**，
再把 pyncm 会话用 ``session=`` 关键字传进去。既不用碰 pyncm 的全局会话状态，
也不用自己手搓 AES/RSA。

（这也是为什么没有去抄那个 FastAPI 仓库：它的加密层和客户端对 ncmp 是纯冗余，
pyncm 早就覆盖了同样的接口。只有 ``logs`` 字段结构那种文档没写的细节才值得参考。）

**签到失败绝不能让主任务失败。** 它是附赠项：接口挂了、被风控了、
字段变了，都不该影响音乐合伙人。所以本模块所有异常都就地消化，
只返回 (成功, 说明文字)。
"""
from __future__ import annotations

from typing import Tuple

# 签到类型：0=移动端，1=PC 端。移动端积分更多。
SIGN_IN_TYPE = "0"

# 这些返回码表示"今天已经签过了"，对用户来说等同于成功，不该报错
_ALREADY_DONE_CODES = (-2,)


def _daily_sign_in_api():
    """构造签到用的端点函数。

    延迟 import + 延迟构造：pyncm 缺失时不能让 core 整个 import 失败，
    那样连音乐合伙人主任务都跑不起来。
    """
    from pyncm.apis import WeapiCryptoRequest

    @WeapiCryptoRequest
    def _sign_in(dtype: str = SIGN_IN_TYPE):
        return "/weapi/point/dailyTask", {"type": dtype}

    return _sign_in


def _build_pyncm_session(requests_session):
    """用 bot 的 cookies 建一个 pyncm 会话。

    bot 用的是普通 ``requests.Session``，而 pyncm 的加密请求需要
    ``csrf_token`` / ``UA_DEFAULT`` / ``weapi_config`` 这些 pyncm 特有属性，
    所以不能直接用，得转一手。
    """
    from pyncm import Session

    session = Session()
    try:
        for cookie in requests_session.cookies:
            try:
                session.cookies.set(
                    cookie.name, cookie.value,
                    domain=cookie.domain or "", path=cookie.path or "/")
            except Exception:
                continue
    except Exception:
        pass
    session.csrf_token = session.cookies.get("__csrf") or ""
    return session


def do_sign_in(requests_session, logger) -> Tuple[bool, str]:
    """执行每日签到。

    :returns: ``(是否成功, 给人看的说明文字)``。任何异常都不会外抛。
    """
    try:
        api = _daily_sign_in_api()
        session = _build_pyncm_session(requests_session)
        data = api(session=session)
    except Exception as e:
        return False, f"签到请求失败（{e}）"

    # 装饰器在 JSON 解析失败时会把 Response 原样返回，所以两种都要兜住
    if not isinstance(data, dict):
        try:
            data = data.json()
        except Exception:
            return False, "签到返回格式异常"
    if not isinstance(data, dict):
        return False, "签到返回格式异常"

    code = data.get("code")
    if code == 200:
        point = data.get("point")
        return True, (f"签到成功，获得 {point} 点经验" if point else "签到成功")
    if code in _ALREADY_DONE_CODES:
        # 今天已经签过了——对用户来说这就是成功，别报错吓人
        return True, "今天已经签过了"
    if code == 301:
        return False, "签到失败：需要重新登录"
    return False, f"签到未完成（code={code}）"
