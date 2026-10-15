"""邮件通知。

原来是纯文本一句话（"评分任务失败，请查看日志"），收件人看不出
是哪次任务、什么时候、失败在哪、该怎么办。现在改成 HTML：
状态色条 + 关键信息表 + 「下一步」提示，同时保留纯文本备选部分
（部分客户端不渲染 HTML）。

配色与界面一致：成功绿 / 失败红 / 警告琥珀 / 提示品牌红。
"""
import html
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Sequence, Tuple

from .config import Config
from .logger import Logger

# 状态 → (色条颜色, 给人看的状态词)
_LEVEL_STYLE = {
    "success": ("#2C7549", "成功"),
    "failed": ("#B3352B", "失败"),
    "warning": ("#8A5A0A", "注意"),
    "info": ("#C20C0C", "通知"),
}

_INK = "#1A1A1A"
_MUTED = "#6B6B6B"
_RULE = "#E5E5E5"
_GROUND = "#F5F5F5"
_PANEL = "#FFFFFF"

_FONT = ("-apple-system,'Segoe UI','Microsoft YaHei UI',"
         "'Helvetica Neue',Arial,sans-serif")


def _render_text(subject: str, content: str,
                 facts: Optional[Sequence[Tuple[str, str]]] = None,
                 action: str = "") -> str:
    """纯文本备选部分。"""
    lines = [subject, "", content]
    if facts:
        lines.append("")
        width = max(len(str(k)) for k, _ in facts)
        for key, value in facts:
            lines.append(f"{str(key).ljust(width)}  {value}")
    if action:
        lines.extend(["", f"下一步：{action}"])
    lines.extend(["", "—", f"由 ncmp desktop 自动发送 · "
                          f"{datetime.now().strftime('%Y-%m-%d %H:%M')}"])
    return "\n".join(lines)


def _render_html(subject: str, content: str, level: str,
                 facts: Optional[Sequence[Tuple[str, str]]] = None,
                 action: str = "") -> str:
    """HTML 部分。用 table + 内联样式：邮件客户端对外部 CSS 支持很差。"""
    bar_color, _word = _LEVEL_STYLE.get(level, _LEVEL_STYLE["info"])
    esc = html.escape

    rows = ""
    if facts:
        cells = "".join(
            f'<tr>'
            f'<td style="padding:5px 0;color:{_MUTED};white-space:nowrap;'
            f'vertical-align:top;">{esc(str(k))}</td>'
            f'<td style="padding:5px 0 5px 16px;color:{_INK};'
            f'word-break:break-all;">{esc(str(v))}</td>'
            f'</tr>'
            for k, v in facts
        )
        rows = (
            f'<tr><td style="padding:16px 24px 0;">'
            f'<table width="100%" cellpadding="0" cellspacing="0" '
            f'style="font-size:13px;font-family:{_FONT};">{cells}</table>'
            f'</td></tr>'
        )

    action_block = ""
    if action:
        action_block = (
            f'<tr><td style="padding:16px 24px 0;">'
            f'<div style="background:{_GROUND};border-radius:6px;'
            f'padding:12px 14px;font-size:13px;line-height:1.7;color:{_INK};">'
            f'<span style="color:{_MUTED};">下一步：</span>{esc(action)}'
            f'</div></td></tr>'
        )

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""\
<div style="background:{_GROUND};padding:24px 12px;font-family:{_FONT};">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;\
margin:0 auto;background:{_PANEL};border:1px solid {_RULE};border-radius:8px;">
    <tr><td style="padding:22px 24px 0;">
      <div style="font-size:12px;color:{_MUTED};letter-spacing:0.02em;">\
ncmp desktop</div>
      <div style="font-size:19px;font-weight:600;color:{_INK};padding-top:6px;">\
{esc(subject)}</div>
      <div style="height:3px;width:44px;background:{bar_color};\
border-radius:2px;margin-top:12px;"></div>
    </td></tr>
    <tr><td style="padding:16px 24px 0;font-size:14px;line-height:1.75;\
color:{_INK};">{esc(content)}</td></tr>
    {rows}
    {action_block}
    <tr><td style="padding:22px 24px;font-size:12px;color:{_MUTED};\
border-top:1px solid {_RULE};margin-top:20px;">
      由 ncmp desktop 自动发送　·　{stamp}
    </td></tr>
  </table>
</div>"""


class NotificationService:
    def __init__(self, config: 'Config', logger: Logger):
        self.config = config
        self.logger = logger

    def send_notification(self, subject: str, content: str,
                          level: str = "info",
                          facts: Optional[Sequence[Tuple[str, str]]] = None,
                          action: str = "") -> bool:
        """发送通知邮件。

        :param subject: 邮件标题，也用作正文里的大标题
        :param content: 一句话说清发生了什么
        :param level: ``success`` / ``failed`` / ``warning`` / ``info``，
            决定正文色条颜色
        :param facts: ``[(标签, 值), ...]``，渲染成关键信息表
        :param action: 出问题时给用户的「下一步」提示
        """
        notify_email = self.config.get("notify_email")
        if not notify_email:
            self.logger.info("未配置通知邮箱，跳过通知发送")
            return False

        email_password = self.config.get("email_password")
        if not email_password:
            self.logger.warning("未配置邮箱密码，无法发送通知")
            return False

        smtp_server = self.config.get("smtp_server", "smtp.qq.com")
        smtp_ssl_port = int(self.config.get("smtp_port", 465))
        smtp_tls_port = 587

        msg = MIMEMultipart("alternative")
        msg['From'] = notify_email
        msg['To'] = notify_email
        msg['Subject'] = subject
        # 先纯文本后 HTML：客户端按顺序取它能渲染的最后一部分
        msg.attach(MIMEText(
            _render_text(subject, content, facts, action), 'plain', 'utf-8'))
        msg.attach(MIMEText(
            _render_html(subject, content, level, facts, action),
            'html', 'utf-8'))

        email_sent_successfully = False
        # 尝试使用 SSL 连接发送邮件
        try:
            self.logger.debug(f"尝试使用 SSL 连接到 {smtp_server}:{smtp_ssl_port}")
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_server, smtp_ssl_port, context=context) as server:
                server.login(notify_email, email_password)
                server.send_message(msg)
                email_sent_successfully = True
                self.logger.info(f"通知邮件通过 SSL 发送成功: {subject}")
        except Exception as ssl_error:
            if not email_sent_successfully:
                self.logger.debug(f"SSL 连接或发送失败，将尝试使用 TLS: {str(ssl_error)}")
            else:
                self.logger.warning(f"SSL 连接在邮件发送后出现错误 (可能在关闭连接时): {str(ssl_error)}. 由于邮件已发送，不再尝试 TLS。")
        # 如果 SSL 尝试没有成功发送邮件，则尝试 TLS
        if not email_sent_successfully:
            try:
                self.logger.debug(f"尝试使用 TLS 连接到 {smtp_server}:{smtp_tls_port}")
                with smtplib.SMTP(smtp_server, smtp_tls_port) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(notify_email, email_password)
                    server.send_message(msg)
                    email_sent_successfully = True
                    self.logger.info(f"通知邮件通过 TLS 发送成功: {subject}")
            except Exception as tls_error:
                if not email_sent_successfully:
                    self.logger.error(f"尝试使用 TLS 连接或发送失败: {str(tls_error)}")
                else:
                    self.logger.warning(f"TLS 连接在邮件发送后出现错误 (可能在关闭连接时): {str(tls_error)}.")
        return email_sent_successfully
