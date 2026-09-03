import json
import re
import smtplib
import imaplib
import email as email_lib
import sqlite3
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path
from typing import Callable, Optional

from langchain.agents import AgentState, create_agent
from langchain.tools import tool, ToolRuntime
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from langchain.messages import ToolMessage
from langchain.agents.middleware import wrap_model_call, dynamic_prompt, HumanInTheLoopMiddleware
from langchain.agents.middleware import ModelRequest, ModelResponse
from typing import Callable
from app.common.logger import logger
import aiosqlite
import os

AUTHENTICATED_KEY = "authenticated"


# ============================================================
# 全局凭据表（解决「两条路径 user_id 不一致 → 新会话又让用户填邮箱」的终极兜底）
# ------------------------------------------------------------
# 任何一次 authenticate 工具成功 / /email/auth 表单认证成功,
# 都把 (邮箱,授权码,服务器配置) 写入独立的 SQLite 表 email_global_credentials。
# 之后任何新建 thread, prompt 中间件都先查表 — 只要有有效凭据,
# 立刻强制 state.authenticated=True,不再依赖 agent state 复制时序 / aupdate_state 成功与否。
# ============================================================
_GLOBAL_CRED_DB = Path(__file__).resolve().parent.parent.parent / "db" / "email_global_credentials.db"


def _ensure_global_cred_table():
    try:
        _GLOBAL_CRED_DB.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(_GLOBAL_CRED_DB), timeout=5) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS email_global_credentials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    auth_code TEXT NOT NULL,
                    smtp_host TEXT,
                    smtp_port INTEGER,
                    imap_host TEXT,
                    imap_port INTEGER,
                    from_name TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now','localtime')),
                    updated_at TEXT DEFAULT (datetime('now','localtime'))
                )
                """
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"[_ensure_global_cred_table] 建表失败: {e}")


def save_global_credentials(
    email: str,
    auth_code: str,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    imap_host: Optional[str] = None,
    imap_port: Optional[int] = None,
    from_name: str = "",
):
    """任何地方认证成功都调用我,把凭据永久保存到全局表。"""
    try:
        _ensure_global_cred_table()
        email_n = (email or "").strip().lower()
        if not email_n or not auth_code:
            return False
        with sqlite3.connect(str(_GLOBAL_CRED_DB), timeout=5) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM email_global_credentials WHERE email = ?", (email_n,))
            row = cur.fetchone()
            if row:
                cur.execute(
                    """
                    UPDATE email_global_credentials
                       SET auth_code = ?, smtp_host = ?, smtp_port = ?,
                           imap_host = ?, imap_port = ?, from_name = ?,
                           updated_at = datetime('now','localtime')
                     WHERE email = ?
                    """,
                    (auth_code, smtp_host, smtp_port, imap_host, imap_port, from_name, email_n),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO email_global_credentials
                    (email, auth_code, smtp_host, smtp_port, imap_host, imap_port, from_name)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (email_n, auth_code, smtp_host, smtp_port, imap_host, imap_port, from_name),
                )
            conn.commit()
            logger.info(f"[global-cred] 已保存/更新邮箱 {email_n} 的全局凭据")
            return True
    except Exception as e:
        logger.warning(f"[global-cred] save_global_credentials 失败: {e}")
        return False


def load_global_credentials(email: Optional[str] = None) -> Optional[dict]:
    """加载全局凭据:
    - email 给定 → 返回该邮箱的凭据
    - email 为 None → 返回最近一次更新的凭据
    """
    try:
        _ensure_global_cred_table()
        if not _GLOBAL_CRED_DB.exists():
            return None
        with sqlite3.connect(str(_GLOBAL_CRED_DB), timeout=5) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            if email and (email or "").strip():
                cur.execute(
                    "SELECT * FROM email_global_credentials WHERE email = ?",
                    ((email or "").strip().lower(),),
                )
            else:
                cur.execute(
                    "SELECT * FROM email_global_credentials ORDER BY updated_at DESC LIMIT 1"
                )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "authenticated": True,
                "email": row["email"],
                "auth_code": row["auth_code"],
                "smtp_host": row["smtp_host"],
                "smtp_port": row["smtp_port"],
                "imap_host": row["imap_host"],
                "imap_port": row["imap_port"],
                "from_name": row["from_name"] or "",
            }
    except Exception as e:
        logger.warning(f"[global-cred] load_global_credentials 失败: {e}")
        return None

EMAIL_PROVIDERS = {
    "163.com":     {"smtp": ("smtp.163.com", 465), "imap": ("imap.163.com", 993), "name": "网易163邮箱"},
    "126.com":     {"smtp": ("smtp.126.com", 465), "imap": ("imap.126.com", 993), "name": "网易126邮箱"},
    "yeah.net":    {"smtp": ("smtp.yeah.net", 465), "imap": ("imap.yeah.net", 993), "name": "网易Yeah邮箱"},
    "netease.com": {"smtp": ("smtp.163.com", 465), "imap": ("imap.163.com", 993), "name": "网易邮箱"},
    "qq.com":      {"smtp": ("smtp.qq.com", 465), "imap": ("imap.qq.com", 993), "name": "QQ邮箱"},
    "foxmail.com": {"smtp": ("smtp.qq.com", 465), "imap": ("imap.qq.com", 993), "name": "Foxmail邮箱"},
    "vip.qq.com":  {"smtp": ("smtp.qq.com", 465), "imap": ("imap.qq.com", 993), "name": "QQ邮箱"},
    "gmail.com":   {"smtp": ("smtp.gmail.com", 465), "imap": ("imap.gmail.com", 993), "name": "Gmail"},
    "sina.com":    {"smtp": ("smtp.sina.com", 465), "imap": ("imap.sina.com", 993), "name": "新浪邮箱"},
    "sina.cn":     {"smtp": ("smtp.sina.com", 465), "imap": ("imap.sina.com", 993), "name": "新浪邮箱"},
    "sohu.com":    {"smtp": ("smtp.sohu.com", 465), "imap": ("imap.sohu.com", 993), "name": "搜狐邮箱"},
    "outlook.com": {"smtp": ("smtp-mail.outlook.com", 587), "imap": ("outlook.office365.com", 993), "name": "Outlook"},
    "hotmail.com": {"smtp": ("smtp-mail.outlook.com", 587), "imap": ("outlook.office365.com", 993), "name": "Hotmail"},
    "live.com":    {"smtp": ("smtp-mail.outlook.com", 587), "imap": ("outlook.office365.com", 993), "name": "Live邮箱"},
    "msn.com":     {"smtp": ("smtp-mail.outlook.com", 587), "imap": ("outlook.office365.com", 993), "name": "MSN邮箱"},
    "aliyun.com":  {"smtp": ("smtp.aliyun.com", 465), "imap": ("imap.aliyun.com", 993), "name": "阿里云邮箱"},
    "139.com":     {"smtp": ("smtp.139.com", 465), "imap": ("imap.139.com", 993), "name": "移动139邮箱"},
}


def _get_provider(email_addr: str):
    if not email_addr or "@" not in email_addr:
        return None
    domain = email_addr.rsplit("@", 1)[-1].strip().lower()
    return EMAIL_PROVIDERS.get(domain)


def _verify_smtp(email_addr: str, auth_code: str, smtp_host: str, smtp_port: int) -> bool:
    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as server:
                server.login(email_addr, auth_code)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
                server.starttls()
                server.login(email_addr, auth_code)
        return True
    except Exception as e:
        logger.warning(f"SMTP 认证失败 (email={email_addr}, host={smtp_host}:{smtp_port}): {e}")
        return False


def _imap_send_id(server: imaplib.IMAP4_SSL) -> None:
    """163/QQ 等邮箱 IMAP 登录后必须发送 ID 命令，否则后续 SELECT 会报 Unsafe Login。"""
    try:
        tag = server._new_tag()
        # tag 在 Python 3 imaplib 中可能是 bytes，统一为字符串方便比较
        tag_str = tag.decode("ascii") if isinstance(tag, bytes) else str(tag)
        cmd = f'{tag_str} ID ("name" "langchain-email-agent" "version" "1.0")\r\n'
        server.send(cmd.encode("utf-8"))
        # 读取响应直到收到以 tag 开头的完成行（最多 20 行，避免无限循环）
        for _ in range(20):
            line = server.readline()
            if not line:
                break
            try:
                decoded = line.decode("utf-8", errors="replace")
            except Exception:
                decoded = str(line)
            # 关键：同时支持 str 和 bytes 形式的 tag 前缀匹配
            if decoded.startswith(tag_str) or (isinstance(line, bytes) and line.startswith(tag)):
                return
        logger.debug("IMAP ID command consumed 20 lines but not found tagged completion; continuing anyway.")
    except Exception as e:
        logger.warning(f"IMAP ID command failed (non-fatal, continuing): {type(e).__name__}: {e}")


def _verify_imap(email_addr: str, auth_code: str, imap_host: str, imap_port: int) -> tuple:
    """验证 IMAP 连接能力，返回 (success: bool, error_detail: str)"""
    try:
        server = imaplib.IMAP4_SSL(imap_host, imap_port, timeout=20)
        try:
            typ, dat = server.login(email_addr, auth_code)
        except imaplib.IMAP4.error as e:
            return False, f"IMAP LOGIN 被拒绝：{e}。请确认授权码是否正确，以及邮箱是否开启了客户端登录权限。"
        if typ != "OK":
            return False, f"IMAP LOGIN 返回非 OK：{typ} {dat}"
        _imap_send_id(server)
        # 直接用普通 SELECT（不使用 readonly=True，避免 163/QQ 不支持 EXAMINE）
        status, _ = server.select("INBOX")
        try:
            server.logout()
        except Exception:
            pass
        if status == "OK":
            return True, ""
        else:
            return False, f"IMAP 登录成功但选择收件箱失败（状态: {status}），请确认已在邮箱设置中开启 IMAP 服务并授权客户端读取。"
    except imaplib.IMAP4.error as e:
        return False, f"IMAP 协议错误：{e}。请确认已在邮箱网页端开启 IMAP 服务并使用正确的授权码。"
    except ConnectionRefusedError:
        return False, f"无法连接到 IMAP 服务器 {imap_host}:{imap_port}，请检查网络或邮箱服务状态。"
    except TimeoutError:
        return False, f"连接 IMAP 服务器 {imap_host}:{imap_port} 超时，请检查网络。"
    except Exception as e:
        return False, f"IMAP 连接失败：{type(e).__name__}: {e}。请确认已在邮箱网页端开启 IMAP 服务。"


def _decode_header_value(value: str) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            try:
                out.append(text.decode(enc or "utf-8", errors="replace"))
            except (LookupError, Exception):
                out.append(text.decode("utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _decode_payload(part) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, Exception):
        return payload.decode("utf-8", errors="replace")


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", "", html or "")
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _get_text_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in (part.get("Content-Disposition") or ""):
                return _decode_payload(part)
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return _strip_html(_decode_payload(part))
        return ""
    else:
        ctype = msg.get_content_type()
        payload = _decode_payload(msg)
        if ctype == "text/html":
            return _strip_html(payload)
        return payload


def _read_inbox_imap(email_addr: str, auth_code: str, imap_host: str, imap_port: int, limit: int = 5) -> list:
    mails = []
    server = None
    try:
        server = imaplib.IMAP4_SSL(imap_host, imap_port, timeout=30)
        login_typ, login_dat = server.login(email_addr, auth_code)
        if login_typ != "OK":
            raise RuntimeError(f"IMAP LOGIN 失败: {login_typ} {login_dat}。请在邮箱网页端「设置 → POP3/SMTP/IMAP」确认已开启 IMAP 服务，并且使用的是正确的「客户端授权码」（不是登录密码）。")
        logger.debug(f"IMAP login OK for {email_addr}")
        _imap_send_id(server)

        # 163 / QQ 等部分服务器不支持 readonly=True（EXAMINE），
        # lesson learned：直接用普通 SELECT，避免触发额外 EXAMINE 指令残留问题
        status, _ = server.select("INBOX")
        if status != "OK":
            raise RuntimeError(f"IMAP 选择收件箱失败 (状态={status})。可能原因：① 该邮箱未开启 IMAP 服务；② 授权码没有 IMAP 权限（仅 SMTP 权限）——请在网页端重新生成同时包含 SMTP 和 IMAP 的授权码。")

        status, data = server.search(None, "ALL")
        if status != "OK" or not data or not data[0]:
            return []
        ids = data[0].split()
        recent_ids = list(reversed(ids))[:limit]
        for num in recent_ids:
            flags_str = ""
            f_status, f_data = server.fetch(num, "(FLAGS)")
            if f_status == "OK" and f_data and f_data[0] and isinstance(f_data[0], bytes):
                flags_str = f_data[0].decode("utf-8", errors="replace")
            status_flag = "已读" if "\\Seen" in flags_str else "未读"

            status, msg_data = server.fetch(num, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            msg = email_lib.message_from_bytes(raw)
            subject = _decode_header_value(msg.get("Subject", ""))
            from_ = _decode_header_value(msg.get("From", ""))
            date_ = msg.get("Date", "")
            body = _get_text_body(msg)
            mails.append({
                "subject": subject or "(无主题)",
                "content": body or "(无正文)",
                "from": from_,
                "date": date_,
                "status": status_flag
            })
    finally:
        if server is not None:
            try:
                server.logout()
            except Exception:
                pass
    return mails


def _send_email_smtp(from_email: str, auth_code: str, smtp_host: str, smtp_port: int,
                     to: str, subject: str, body: str, from_name: str = "") -> None:
    msg = MIMEMultipart()
    sender_name = from_name.strip() if from_name else from_email.split("@")[0]
    msg["From"] = formataddr((sender_name, from_email))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.attach(MIMEText(body, "plain", "utf-8"))

    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
            server.login(from_email, auth_code)
            server.sendmail(from_email, [to], msg.as_string())
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.starttls()
            server.login(from_email, auth_code)
            server.sendmail(from_email, [to], msg.as_string())


class AuthenticatedState(AgentState):
    authenticated: bool
    email: str
    auth_code: str
    smtp_host: str
    smtp_port: int
    imap_host: str
    imap_port: int
    from_name: str


# ==================== 1. 定义工具 ====================

@tool
def authenticate(email: str, password: str, runtime: ToolRuntime) -> Command:
    """Authenticate the user with the given email and authorization code.

    password 应为邮箱的"客户端授权码"（不是登录密码），用于 SMTP/IMAP 登录。
    支持 163、126、QQ、Gmail、Outlook 等主流邮箱。
    """

    authenticated = False
    message = "认证失败"
    smtp_host = smtp_port = imap_host = imap_port = None
    provider_name = ""
    imap_ok = False

    provider = _get_provider(email)
    if not provider:
        message = (f"暂不支持的邮箱地址：{email}。目前支持 163、126、QQ、Gmail、Outlook、阿里云等主流邮箱，"
                   f"请使用这些邮箱地址。")
    else:
        provider_name = provider["name"]
        smtp_host, smtp_port = provider["smtp"]
        imap_host, imap_port = provider["imap"]

        smtp_ok = _verify_smtp(email, password, smtp_host, smtp_port)
        imap_ok, imap_err = _verify_imap(email, password, imap_host, imap_port)

        if smtp_ok and imap_ok:
            authenticated = True
            message = (f"认证成功，已连接到{provider_name}（{email}），SMTP 和 IMAP 均正常。"
                       f"现在可以读取收件箱或发送邮件。")
        elif smtp_ok and not imap_ok:
            authenticated = True
            message = (f"认证成功，已连接到{provider_name}（{email}），SMTP 发送正常，"
                       f"但 IMAP 读取收件箱存在问题：{imap_err}\n\n"
                       f"你现在可以发送邮件，但暂时无法读取收件箱。"
                       f"请在邮箱网页端「设置 → POP3/SMTP/IMAP」中确认已开启 IMAP 服务，"
                       f"或稍后再试。")
        elif not smtp_ok and imap_ok:
            message = (f"IMAP 收件箱连接正常，但 SMTP 发送认证失败。"
                       f"请检查授权码是否正确，或是否已在邮箱设置中开启 SMTP 服务。")
        else:
            message = ("认证失败，SMTP 和 IMAP 均无法连接。请检查："
                       "① 邮箱地址是否正确；② 输入的是不是该邮箱的"
                       "「客户端授权码」（注意 163/QQ 等邮箱使用授权码而非登录密码，"
                       "需在邮箱网页端设置中开启 SMTP/IMAP 服务并生成授权码）；"
                       "③ 网络是否能访问邮件服务器。")

    update = {
        "authenticated": authenticated,
        "messages": [
            ToolMessage(message, tool_call_id=runtime.tool_call_id)
        ],
    }
    if authenticated:
        update["email"] = email
        update["auth_code"] = password
        update["smtp_host"] = smtp_host
        update["smtp_port"] = smtp_port
        update["imap_host"] = imap_host
        update["imap_port"] = imap_port
        update["from_name"] = ""
        # ✅ 新增：认证成功立即写入全局凭据表，未来任何新会话都能直接读到
        save_global_credentials(
            email=email,
            auth_code=password,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            imap_host=imap_host,
            imap_port=imap_port,
            from_name="",
        )
    return Command(update=update)


@tool
def set_sender_name(name: str, runtime: ToolRuntime) -> Command:
    """Set a custom sender name (display name) for outgoing emails.
    This name will appear as the display name in the recipient's inbox.
    Example: set_sender_name("张三") or set_sender_name("小王的助手")。
    """
    update = {
        "from_name": name.strip(),
        "messages": [
            ToolMessage(f"发件人署名已设置为「{name.strip()}」，后续发送的邮件将以此名称显示。",
                        tool_call_id=runtime.tool_call_id)
        ],
    }
    return Command(update=update)


@tool
def check_inbox(runtime: ToolRuntime) -> str:
    """Read recent emails from the user's real inbox (via IMAP). Returns up to 5 latest emails."""

    state = runtime.state or {}
    email_addr = state.get("email")
    auth_code = state.get("auth_code")
    imap_host = state.get("imap_host")
    imap_port = state.get("imap_port")
    authenticated = state.get(AUTHENTICATED_KEY)

    # ✅ 兜底：runtime.state 还没有凭据时，去全局凭据表取最近一次
    if not (email_addr and auth_code and imap_host):
        cred = load_global_credentials(email=email_addr) or load_global_credentials(email=None)
        if cred and cred.get("authenticated"):
            email_addr = cred.get("email")
            auth_code = cred.get("auth_code")
            imap_host = cred.get("imap_host")
            imap_port = cred.get("imap_port")
            authenticated = True
            logger.info(f"[global-cred] check_inbox 从全局凭据表恢复: email={email_addr!r}")

    logger.info(f"[check_inbox] authenticated={authenticated!r}, email={email_addr!r}, imap_host={imap_host!r}")

    if not email_addr or not auth_code or not imap_host:
        return (
            "尚未完成邮箱认证，请先提供邮箱地址和客户端授权码进行登录。\n"
            "操作提示：点击页面底部导航区的「登录」按钮，输入邮箱地址和授权码后即可自动完成认证。"
        )

    try:
        mails = _read_inbox_imap(email_addr, auth_code, imap_host, imap_port, limit=5)
    except RuntimeError as e:
        logger.error(f"读取收件箱失败 (RuntimeError): {e}", exc_info=True)
        return f"读取收件箱失败：{e}"
    except Exception as e:
        logger.error(f"读取收件箱失败: {e}", exc_info=True)
        return (
            f"读取收件箱失败：{e}\n\n"
            f"请按以下步骤排查：\n"
            f"1. 登录邮箱网页端「设置 → POP3/SMTP/IMAP」，确认 IMAP 服务已开启；\n"
            f"2. 确认你使用的授权码同时拥有 SMTP 和 IMAP 两项权限（QQ/163 的旧授权码可能只有 SMTP 权限），必要时重新生成授权码；\n"
            f"3. 当前使用的授权码用户名是否已正确对应到登录邮箱（{email_addr}）。"
        )

    if not mails:
        return "收件箱为空，没有邮件。"

    lines = [f"已获取最新 {len(mails)} 封邮件："]
    for i, m in enumerate(mails, 1):
        lines.append(
            f"\n【邮件 {i}】\n"
            f"发件人：{m['from']}\n"
            f"日期：{m['date']}\n"
            f"状态：{m['status']}\n"
            f"主题：{m['subject']}\n"
            f"正文：\n{m['content']}"
        )
    return "\n".join(lines)


@tool
def send_email(to: str, subject: str, body: str, runtime: ToolRuntime) -> str:
    """Send a real email to the given recipient via SMTP."""

    state = runtime.state or {}
    email_addr = state.get("email")
    auth_code = state.get("auth_code")
    smtp_host = state.get("smtp_host")
    smtp_port = state.get("smtp_port")
    from_name = state.get("from_name", "")
    authenticated = state.get(AUTHENTICATED_KEY)

    # ✅ 兜底：runtime.state 还没有凭据时，去全局凭据表取最近一次
    if not (email_addr and auth_code and smtp_host):
        cred = load_global_credentials(email=email_addr) or load_global_credentials(email=None)
        if cred and cred.get("authenticated"):
            email_addr = cred.get("email")
            auth_code = cred.get("auth_code")
            smtp_host = cred.get("smtp_host")
            smtp_port = cred.get("smtp_port")
            authenticated = True
            if not from_name:
                from_name = cred.get("from_name", "")
            logger.info(f"[global-cred] send_email 从全局凭据表恢复: email={email_addr!r}")

    logger.info(f"[send_email] authenticated={authenticated!r}, from_email={email_addr!r}, smtp_host={smtp_host!r}, to={to!r}")

    if not email_addr or not auth_code or not smtp_host:
        return (
            "尚未完成邮箱认证，无法发送邮件。\n"
            "请先点击页面底部「登录」按钮，输入邮箱地址和客户端授权码完成认证后再发送。"
        )

    try:
        _send_email_smtp(email_addr, auth_code, smtp_host, smtp_port, to, subject, body, from_name)
        sender_label = f"（署名：{from_name}）" if from_name else ""
        return f"邮件已真实发送至 {to}{sender_label}，主题：{subject}"
    except Exception as e:
        logger.error(f"发送邮件失败: {e}", exc_info=True)
        return f"邮件发送失败：{e}\n\n请确认 SMTP 服务已在邮箱网页端开启，并且授权码具备 SMTP 权限。"


# 定义中间件，实现动态工具
@wrap_model_call
async def dynamic_tool_call(
    request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
) -> ModelResponse:
    authenticated = request.state.get(AUTHENTICATED_KEY)

    # ✅ 兜底：thread state 说未认证，但全局凭据表里有保存过的凭据 → 直接视为已认证
    #    （解决新会话 agent state 还没同步/复制凭据时，又让用户填的问题）
    global_cred = None
    if not authenticated:
        state_email = (request.state.get("email") or "").strip() or None
        global_cred = load_global_credentials(email=state_email)
        if global_cred is None:
            global_cred = load_global_credentials(email=None)  # 取最近一次
        if global_cred and global_cred.get("authenticated"):
            authenticated = True
            logger.info(
                f"[global-cred] dynamic_tool_call 从全局凭据表恢复认证: "
                f"email={global_cred.get('email')!r}"
            )

    if authenticated:
        tools = [check_inbox, send_email, set_sender_name]
    else:
        tools = [authenticate]

    request = request.override(tools=tools)
    return await handler(request)


authenticated_prompt = """你是一个真实可用的邮箱助手，已通过用户的邮箱授权码登录到用户的真实邮箱。
你可以调用 check_inbox 读取用户真实收件箱中的最新邮件，也可以调用 send_email 真实地向他人邮箱发送邮件
（发送前会由用户确认，确认后邮件会真实发出，请务必谨慎准备收件人、主题和正文）。
你还可以调用 set_sender_name 来设置发件人署名——收件人看到的发件人名称会使用这个署名，而不是邮箱地址。
如果用户没有设置署名，默认使用邮箱用户名（@前面的部分）。

行为约定：
- 当用户要求"看邮件/查收件箱/有没有新邮件"时，调用 check_inbox。
- 当用户要求"发邮件/回复/写信"时，先向用户确认收件人、主题、正文，准备好后调用 send_email。
- 当用户说"用XX名字发/署名XX/发件人叫XX"时，调用 set_sender_name(name) 设置署名，然后再发送邮件。
- 涉及他人真实邮箱地址时，务必向用户复述确认，避免发错。
- 回复用户时请使用中文，简洁清晰，可适当归纳邮件要点。"""

unauthenticated_prompt = """你是一个真实可用的邮箱助手，可以连接用户的真实邮箱（如 163、126、QQ、Gmail、Outlook、阿里云等），
读取真实收件箱里的邮件，并向真人邮箱真实发送邮件。

出于系统安全协议，你在进行任何其他操作前，必须先调用 authenticate 工具完成用户邮箱授权。
请向用户说明需要提供：
① 邮箱地址（例如 xxx@163.com 或 xxx@qq.com）；
② 该邮箱的"客户端授权码"——注意：163、QQ 等大多数邮箱使用的是授权码，而不是登录密码，
   授权码需要在对应邮箱的网页端"设置 → POP3/SMTP/IMAP"中开启 SMTP 和 IMAP 服务并生成。

特别提醒：163、QQ 等邮箱的 SMTP 和 IMAP 是两个独立服务，需要都开启才能同时发信和收信。
如果只开启了 SMTP，可以发信但无法读收件箱；如果只开启了 IMAP，可以读收件箱但无法发信。

收集到邮箱地址和授权码后，调用 authenticate(email, password) 完成登录验证；
验证通过后才可读取收件箱或发送邮件。若认证失败，请提示用户检查邮箱地址与授权码。"""


@dynamic_prompt
def dynamic_prompt_func(request: ModelRequest) -> str:
    authenticated = request.state.get(AUTHENTICATED_KEY)

    # ✅ 兜底:thread state 说未认证,但全局凭据表里有 → 照样按已认证prompt走
    if not authenticated:
        state_email = (request.state.get("email") or "").strip() or None
        global_cred = load_global_credentials(email=state_email) or load_global_credentials(email=None)
        if global_cred and global_cred.get("authenticated"):
            authenticated = True
            logger.info(
                f"[global-cred] dynamic_prompt_func 从全局凭据表恢复认证: "
                f"email={global_cred.get('email')!r}"
            )

    final_prompt = authenticated_prompt if authenticated else unauthenticated_prompt
    return final_prompt


def _serialize(obj):
    if hasattr(obj, 'value'):
        return _serialize(obj.value)
    elif hasattr(obj, 'model_dump'):
        return obj.model_dump()
    elif isinstance(obj, (list, tuple)):
        return [_serialize(item) for item in obj]
    elif isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    return obj


class EmailAgent:

    def __init__(self):
        self.conn: aiosqlite.Connection = None
        self.checkpointer: BaseCheckpointSaver = None
        self.agent = None

    async def init(self):
        await self.init_checkpointer()
        logger.info("checkpointer 初始化完成 ....")
        await self.init_agent()
        logger.info("email agent 初始化完成 ....")

    async def init_checkpointer(self):
        os.makedirs("./db", exist_ok=True)
        self.conn = await aiosqlite.connect("./db/mail_fiend.db")
        logger.info("sqlite connection 完成 ....")
        self.checkpointer = AsyncSqliteSaver(conn=self.conn)
        await self.checkpointer.setup()

    async def close(self):
        await self.conn.close()
        logger.info("sqlite connection 关闭 ....")

    async def init_agent(self):
        self.agent = create_agent(
            "deepseek-chat",
            tools=[authenticate, check_inbox, send_email, set_sender_name],
            state_schema=AuthenticatedState,
            checkpointer=self.checkpointer,
            middleware=[
                dynamic_tool_call,
                dynamic_prompt_func,
                HumanInTheLoopMiddleware(
                    interrupt_on={
                        "authenticate": False,
                        "check_inbox": False,
                        "send_email": True,
                        "set_sender_name": False,
                    }
                )
            ],
        )

    async def generate_sse(self, thread_id: str, message: str, interrupt_decision: dict):
        config = {
            "configurable": {
                "thread_id": thread_id
            }
        }

        messages = {"messages": [HumanMessage(content=message)]}
        _input = messages
        if interrupt_decision:
            _input = Command(resume={
                "decisions": [interrupt_decision]
            })

        logger.info(f"调用agent，Input：{_input}")
        try:
            async for chunk in self.agent.astream(
                _input,
                config=config,
                stream_mode=["messages", "updates"],
                version="v2"
            ):
                event_type = chunk["type"]
                data = chunk["data"]

                if event_type == "messages":
                    token, metadata = data
                    content = None
                    if isinstance(token, AIMessage) and hasattr(token, "content"):
                        content = token.content

                    if content:
                        yield {
                            "event": "message",
                            "data": json.dumps(
                                {"type": "message", "content": content},
                                ensure_ascii=False
                            )
                        }

                elif event_type == "updates":
                    if "__interrupt__" in data:
                        interrupt_data = data['__interrupt__']
                        details = _serialize(interrupt_data)
                        yield {
                            "event": "interrupt",
                            "data": json.dumps(
                                {
                                    "type": "interrupt",
                                    "interrupt": {
                                        "reason": "需要人工确认",
                                        "details": details
                                    }
                                },
                                ensure_ascii=False, default=str
                            )
                        }

            yield {
                "event": "done",
                "data": json.dumps({"type": "done", "content": "处理完成"}, ensure_ascii=False)
            }

        except Exception as e:
            logger.error(f"SSE 流中断: {e}", exc_info=True)
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "error": str(e)}, ensure_ascii=False)
            }

    async def get_messages(self, thread_id: str) -> dict:
        logger.info(f"获取历史消息，thread_id: {thread_id}")

        config = {"configurable": {"thread_id": thread_id}}
        state = await self.agent.aget_state(config)
        if state is None or not state.values:
            return {"messages": []}

        messages = state.values.get("messages", [])

        result = []
        for msg in messages:
            if not msg.content:
                continue
            if isinstance(msg, HumanMessage):
                result.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                result.append({"role": "assistant", "content": msg.content})

        response = {"messages": result}

        interrupts = None
        if hasattr(state, 'interrupts') and state.interrupts:
            interrupts = state.interrupts
        elif hasattr(state, 'tasks') and state.tasks:
            for task in state.tasks:
                if hasattr(task, 'interrupts') and task.interrupts:
                    interrupts = task.interrupts
                    break

        if interrupts:
            response["has_interrupt"] = True
            response["interrupt"] = {
                "reason": "需要人工确认",
                "details": _serialize(interrupts)
            }

        return response

email_agent = EmailAgent()

__all__ = ["email_agent"]
