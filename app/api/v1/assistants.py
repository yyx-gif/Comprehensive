"""6 个新助手的 API 路由"""
from typing import Optional
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.agents.base_assistant import (
    ASSISTANT_CONFIGS,
    stream_assistant,
    get_messages as assistant_get_messages,
    clear_messages as assistant_clear_messages,
)
from app.common.logger import logger

router = APIRouter()


class AssistantChatRequest(BaseModel):
    message: str
    thread_id: str
    biz_type: str = "travel"


@router.post("/assistant/stream", tags=["助手对话"])
async def assistant_chat(request: AssistantChatRequest):
    """通用助手流式对话（SSE 格式）"""
    biz_type = request.biz_type
    if biz_type not in ASSISTANT_CONFIGS:
        return {"error": f"未知的助手类型: {biz_type}"}

    logger.info(f"[assistant/stream] biz_type={biz_type} thread_id={request.thread_id} msg_len={len(request.message)}")

    return StreamingResponse(
        stream_assistant(biz_type, request.message, request.thread_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/assistants/config", tags=["助手配置"])
async def get_assistants_config():
    """获取所有助手配置（供前端使用）"""
    return [
        {
            "biz_type": k,
            "name": v["name"],
            "icon": v["icon"],
        }
        for k, v in ASSISTANT_CONFIGS.items()
    ]


@router.get("/assistant/{biz_type}/{thread_id}/messages", tags=["助手历史"])
async def get_assistant_messages(biz_type: str, thread_id: str):
    """获取助手会话历史消息"""
    try:
        result = assistant_get_messages(biz_type, thread_id)
        return {"messages": result}
    except Exception as e:
        return {"messages": [], "error": str(e)}
