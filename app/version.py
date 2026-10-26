"""版本号与仓库地址的唯一来源。

以前 ``__version__`` 硬编码在 about_page.py 里，更新检查也要用版本号，
放在页面文件里不合适。统一挪到这里。
"""

__version__ = "1.1.2"

GITHUB_REPO = "longyanbo1224-debug/ncmp_desktop"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"
API_LATEST_RELEASE = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def parse_version(text: str) -> tuple:
    """把 "v1.2.3" / "1.2.3" 解析成 (1, 2, 3)；解析不出来返回空元组。

    只认数字段，遇到非数字（如 "1.2.0-beta"）就截断，够用了。
    """
    cleaned = str(text or "").strip().lstrip("vV")
    parts = []
    for chunk in cleaned.split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def is_newer(candidate: str, current: str = __version__) -> bool:
    """candidate 是否比 current 新。任一边解析不出来都返回 False（宁可不提示）。"""
    a, b = parse_version(candidate), parse_version(current)
    if not a or not b:
        return False
    # 补齐长度再比，避免 (1,2) 和 (1,2,0) 判错
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    return a > b
