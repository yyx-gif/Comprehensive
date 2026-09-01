from fastapi import APIRouter
from app.models.schemas import ChatRequest
from app.models.session import ensure_session_exists
from fastapi.responses import StreamingResponse
from app.agents.personal_chief import search_recipes, get_messages, clear_messages
from app.agents.email_agent import email_agent
from pydantic import BaseModel
from typing import Optional
import json
from app.common.logger import logger


router = APIRouter()


@router.post("/chat/stream")
async def chat_endpoint(request: ChatRequest):
    """流式对话（私厨，SSE格式）"""
    # 确保会话存在并更新最后活跃时间
    if request.thread_id:
        ensure_session_exists(request.thread_id)
    
    # 诊断日志
    logger.info(f"[chat/stream] thread_id={request.thread_id} msg_len={len(request.message or '')} image_url={bool(request.image_url)}")
    if request.image_url:
        url_snip = request.image_url[:120]
        logger.info(f"[chat/stream] image_url prefix: {url_snip}")
    
    # SSE 响应：关键是设置正确的 headers 防止缓冲
    return StreamingResponse(
        search_recipes(request.message, request.image_url, request.thread_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 防止 nginx 缓冲
        }
    )


class EmailChatRequest(BaseModel):
    message: Optional[str] = None
    thread_id: str
    interrupt_decision: Optional[dict] = None


@router.post("/email/chat")
async def email_chat_endpoint(request: EmailChatRequest):
    """邮箱助手流式对话（SSE格式，适配app.js）"""
    from app.models.session import get_sessions

    # ====== 凭据自动注入：未认证会话自动复用同一邮箱用户最近一次认证的凭据 ======
    try:
        current_cfg = {"configurable": {"thread_id": request.thread_id}}
        current_state_snap = await email_agent.agent.aget_state(current_cfg)
        current_authed = False
        if current_state_snap and current_state_snap.values:
            current_authed = bool(current_state_snap.values.get("authenticated")) and bool(current_state_snap.values.get("email"))

        if not current_authed:
            # 找到当前会话对应的 user_id
            user_id = None
            all_sessions = get_sessions(biz_type="email-assistant") or []
            for s in all_sessions:
                if s.thread_id == request.thread_id:
                    user_id = s.user_id
                    break
            if not user_id:
                # 找不到就使用 localStorage 返回的 mailfriend_current_user（在请求头里也可以传，这里用兜底：遍历所有会话最新）
                pass

            # 搜索同 user_id 或所有 email-assistant 会话中最近一个已认证的
            candidate_tids = []
            for s in all_sessions:
                if user_id and s.user_id != user_id:
                    continue
                candidate_tids.append(s.thread_id)
            # 优先最近更新的
            candidate_tids_sorted = sorted(candidate_tids, key=lambda t: next(
                (s.updated_at for s in all_sessions if s.thread_id == t), ""), reverse=True)

            copied = False
            for tid in candidate_tids_sorted:
                if tid == request.thread_id:
                    continue
                other_cfg = {"configurable": {"thread_id": tid}}
                other_snap = await email_agent.agent.aget_state(other_cfg)
                if not other_snap or not other_snap.values:
                    continue
                vals = other_snap.values
                if vals.get("authenticated") and vals.get("email") and vals.get("auth_code"):
                    # 找到已认证的凭据，复制到当前线程
                    cred_copy = {
                        "authenticated": True,
                        "email": vals["email"],
                        "auth_code": vals["auth_code"],
                        "smtp_host": vals.get("smtp_host"),
                        "smtp_port": vals.get("smtp_port"),
                        "imap_host": vals.get("imap_host"),
                        "imap_port": vals.get("imap_port"),
                        "from_name": vals.get("from_name", ""),
                    }
                    try:
                        await email_agent.agent.aupdate_state(current_cfg, cred_copy)
                        logger.info(f"[auto-auth] 从 thread {tid} 复制邮箱认证 ({cred_copy['email']}) 到 thread {request.thread_id}")
                        copied = True
                        break
                    except Exception as e2:
                        logger.warning(f"[auto-auth] 复制认证失败: {e2}")
            if copied is False and not current_authed:
                logger.info(f"[auto-auth] thread {request.thread_id} 未认证且未找到可复用凭据，将依赖 agent 交互 authenticate 完成登录")
    except Exception as e:
        logger.warning(f"[auto-auth] 预处理异常（不影响对话继续）: {e}")

    async def sse_generator():
        async for event in email_agent.generate_sse(
            thread_id=request.thread_id,
            message=request.message or "",
            interrupt_decision=request.interrupt_decision
        ):
            yield f"event: {event['event']}\ndata: {event['data']}\n\n"
    return StreamingResponse(sse_generator(), media_type="text/event-stream")


@router.get("/chat/messages")
async def get_chat_messages(thread_id: str):
    """获取历史消息"""
    messages = get_messages(thread_id)
    return {"messages": messages}


@router.delete("/chat/messages")
async def clear_chat_messages(thread_id: str):
    """清空历史消息"""
    clear_messages(thread_id)
    return {"success": True}


class EmailAuthRequest(BaseModel):
    email: str
    auth_code: str


@router.post("/email/auth")
async def email_auth_endpoint(request: EmailAuthRequest):
    """邮箱直接认证 - 验证连接、创建会话并直接写入 AgentState"""
    from app.agents.email_agent import _get_provider, _verify_smtp, _verify_imap

    email_addr = request.email.strip()
    auth_code = request.auth_code.strip()

    provider = _get_provider(email_addr)
    if not provider:
        return {"success": False, "message": f"暂不支持的邮箱地址：{email_addr}"}

    smtp_host, smtp_port = provider["smtp"]
    imap_host, imap_port = provider["imap"]
    provider_name = provider["name"]

    smtp_ok = _verify_smtp(email_addr, auth_code, smtp_host, smtp_port)
    imap_ok, imap_err = _verify_imap(email_addr, auth_code, imap_host, imap_port)

    if not smtp_ok and not imap_ok:
        return {
            "success": False,
            "message": (
                f"SMTP 和 IMAP 均连接失败。请检查：\n"
                f"1. 是否已在{provider_name}网页端「设置 → POP3/SMTP/IMAP」中开启 SMTP 和 IMAP 服务\n"
                f"2. 输入的是否为「客户端授权码」（不是登录密码，163/QQ 等需在网页端生成授权码）\n"
                f"3. 网络是否能正常访问邮件服务器"
            ),
        }

    # 即使 IMAP 失败也允许创建会话（仅 SMTP 也能发邮件）
    try:
        import uuid
        from app.models.session import create_session, SessionCreate

        thread_id = str(uuid.uuid4())
        session = create_session(SessionCreate(
            user_id=email_addr,
            biz_type="email-assistant",
            name=f"{email_addr.split('@')[0]} 的会话"
        ))

        config = {"configurable": {"thread_id": thread_id}}

        # 直接写入 AgentState，不依赖 agent 调用 tool
        state_update = {
            "authenticated": True,
            "email": email_addr,
            "auth_code": auth_code,
            "smtp_host": smtp_host,
            "smtp_port": smtp_port,
            "imap_host": imap_host,
            "imap_port": imap_port,
            "from_name": "",
        }

        try:
            await email_agent.agent.aupdate_state(config, state_update)
            logger.info(f"直接写入 AgentState 成功: {email_addr}, thread_id: {thread_id}")
        except Exception as e:
            logger.warning(f"aupdate_state 失败，回退到 ainvoke: {e}")
            from langchain_core.messages import HumanMessage
            await email_agent.agent.ainvoke(
                {"messages": [HumanMessage(
                    content=f"请使用 authenticate 工具认证我的邮箱：邮箱地址 {email_addr}，授权码 {auth_code}。"
                )]},
                config=config
            )

        success_msg = f"已连接到 {email_addr}"
        if smtp_ok and not imap_ok:
            success_msg += f"（SMTP 正常，IMAP 失败：{imap_err}）"

        logger.info(f"邮箱认证成功: {email_addr}, thread_id: {thread_id}")
        return {
            "success": True,
            "message": success_msg,
            "thread_id": thread_id
        }
    except Exception as e:
        logger.error(f"邮箱认证异常: {e}", exc_info=True)
        return {"success": False, "message": f"认证过程出错：{str(e)}"}
