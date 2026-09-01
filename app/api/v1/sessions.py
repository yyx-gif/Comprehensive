from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.models.session import (
    SessionCreate,
    SessionResponse,
    get_sessions,
    create_session,
    delete_session
)
from app.agents.email_agent import email_agent
from app.agents.personal_chief import get_messages as chef_get_messages, clear_messages as chef_clear_messages
from app.agents.base_assistant import clear_messages as assistant_clear_messages, ASSISTANT_CONFIGS

router = APIRouter()


@router.post("/sessions", response_model=SessionResponse, tags=["会话"])
def create_new_session(session: SessionCreate):
    """创建新会话"""
    return create_session(session)


@router.get("/sessions", response_model=List[SessionResponse], tags=["会话"])
def list_sessions(
    user_id: Optional[str] = Query(None, description="用户ID"),
    biz_type: Optional[str] = Query(None, description="业务类型")
):
    """查询会话列表，支持按 user_id 和 biz_type 筛选"""
    return get_sessions(user_id=user_id, biz_type=biz_type)


@router.delete("/sessions/{thread_id}", tags=["会话"])
async def remove_session(thread_id: str):
    """删除会话及其checkpoint"""
    deleted = delete_session(thread_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        await email_agent.clear_messages(thread_id)
    except Exception:
        pass
    try:
        chef_clear_messages(thread_id)
    except Exception:
        pass
    # 清理新助手会话
    try:
        assistant_clear_messages(thread_id)
    except Exception:
        pass
    return {"message": "Session deleted successfully"}


@router.get("/sessions/{thread_id}/messages", tags=["会话"])
async def get_session_messages(thread_id: str, biz_type: Optional[str] = Query(None)):
    """获取会话的历史消息"""
    try:
        if biz_type == "chef":
            result = chef_get_messages(thread_id)
        elif biz_type in ASSISTANT_CONFIGS:
            from app.agents.base_assistant import get_messages as assistant_get_messages
            result = assistant_get_messages(biz_type, thread_id)
        else:
            result = await email_agent.get_messages(thread_id)
        return {"messages": result}
    except Exception as e:
        return {"messages": [], "error": str(e)}