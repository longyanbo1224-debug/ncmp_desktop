"""日志：所有写入口统一做**脱敏**和**截断**。

两件事必须在写日志的地方做，而不是"记得别打印"：
1. 脱敏——LLM key、Cookie、csrf、Bearer token 一旦进了日志，日志又会被
   持久化（按天存 7 天）和发到界面，等于把凭据写到磁盘上；
2. 截断——接口返回偶尔是几 KB 的 JSON，整段进日志只会把有用的行冲走。

规则来源参考了 Grails125/ncmm 的日志层：服务端原文可以记，但不回声凭据。
"""
import logging
import re
from typing import Optional

#: (正则, 替换)。按顺序套用，越具体的越靠前
_SECRET_PATTERNS = (
    (re.compile(r"sk-[A-Za-z0-9_\-]{6,}"), "sk-***"),
    (re.compile(r"(MUSIC_U=)[^;,\s\"']+"), r"\1***"),
    (re.compile(r"(__csrf=)[^;,\s\"']+"), r"\1***"),
    (re.compile(r"(?i)(authorization:\s*bearer\s+)\S+"), r"\1***"),
    (re.compile(r"(?i)(\"?(?:api_?key|token|password)\"?\s*[:=]\s*\"?)[^\s\",}]{4,}"),
     r"\1***"),
)

#: 单行上限。超过就截断——4xx 的 HTML 页面能把一整屏日志吃掉
MAX_LINE = 400


def redact(message) -> str:
    """把一行日志里的凭据替换掉，并压到 MAX_LINE 以内。"""
    text = str(message)
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    if len(text) > MAX_LINE:
        text = text[:MAX_LINE] + "…"
    return text


class Logger:
    def __init__(self, log_level: Optional[int] = logging.DEBUG):
        # 配置日志格式
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.logger = logging.getLogger(__name__)

    def debug(self, message: str) -> None:
        self.logger.debug(redact(message))

    def warning(self, message: str) -> None:
        self.logger.warning(redact(message))

    def info(self, message: str) -> None:
        self.logger.info(redact(message))

    def error(self, message: str) -> None:
        self.logger.error(redact(message))

    def end(self, message: str, is_error: bool = False) -> None:
        if is_error:
            self.error(message)
        else:
            self.info(message)
