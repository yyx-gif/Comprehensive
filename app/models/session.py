import sqlite3
import uuid
from datetime import datetime
from typing import List, Optional
from pathlib import Path

from pydantic import BaseModel


# Pydantic 模型
class SessionCreate(BaseModel):
    """创建会话的请求模型"""
    user_id: str
    biz_type: str
    name: str


class SessionResponse(BaseModel):
    """会话响应模型"""
    thread_id: str
    user_id: str
    biz_type: str
    name: str
    created_at: str
    updated_at: str


# 数据库配置
DB_PATH = Path(__file__).parent.parent.parent / "db/sessions.db"


def get_db_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库，创建 sessions 表"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            thread_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            biz_type TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def create_session(session: SessionCreate) -> SessionResponse:
    """创建新会话"""
    conn = get_db_connection()
    cursor = conn.cursor()

    thread_id = str(uuid.uuid4())
    now = datetime.now().isoformat()

    cursor.execute(
        """
        INSERT INTO sessions (thread_id, user_id, biz_type, name, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (thread_id, session.user_id, session.biz_type, session.name, now, now)
    )
    conn.commit()
    conn.close()

    return SessionResponse(
        thread_id=thread_id,
        user_id=session.user_id,
        biz_type=session.biz_type,
        name=session.name,
        created_at=now,
        updated_at=now
    )


def get_sessions(user_id: Optional[str] = None, biz_type: Optional[str] = None) -> List[SessionResponse]:
    """查询会话列表，支持按 user_id 和 biz_type 筛选，同时合并 checkpointer 中的会话"""
    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT thread_id, user_id, biz_type, name, created_at, updated_at FROM sessions"
    params = []

    if user_id or biz_type:
        conditions = []
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if biz_type:
            conditions.append("biz_type = ?")
            params.append(biz_type)
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY updated_at DESC"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    sessions = [
        SessionResponse(
            thread_id=row["thread_id"],
            user_id=row["user_id"],
            biz_type=row["biz_type"],
            name=row["name"],
            created_at=row["created_at"],
            updated_at=row["updated_at"]
        )
        for row in rows
    ]

    # 从 checkpointer 数据库获取有对话历史的 thread_id，并合并到会话列表
    if biz_type == "chef" or not biz_type:
        try:
            import re
            from datetime import datetime, timedelta, timezone
            
            # 中国时区 UTC+8
            china_tz = timezone(timedelta(hours=8))
            
            chef_db_path = Path(__file__).parent.parent.parent / "db" / "personal_chief.db"
            if chef_db_path.exists():
                chef_conn = sqlite3.connect(str(chef_db_path))
                chef_cursor = chef_conn.cursor()
                
                # 查询每个 thread_id 的最新 checkpoint
                chef_cursor.execute("""
                    SELECT thread_id, MAX(rowid) as max_rowid
                    FROM checkpoints 
                    GROUP BY thread_id
                    ORDER BY max_rowid DESC
                """)
                checkpoint_rows = chef_cursor.fetchall()
                
                existing_thread_ids = {s.thread_id for s in sessions}
                
                for row in checkpoint_rows:
                    thread_id = row[0]
                    
                    if thread_id not in existing_thread_ids:
                        # 获取该 thread_id 最新的 checkpoint 记录
                        chef_cursor.execute("""
                            SELECT checkpoint FROM checkpoints 
                            WHERE thread_id = ?
                            ORDER BY rowid DESC
                            LIMIT 1
                        """, (thread_id,))
                        checkpoint_row = chef_cursor.fetchone()
                        
                        # 从 checkpoint blob 中提取时间戳
                        updated_at = datetime.now().isoformat()
                        session_name = "AI 私厨会话"
                        if checkpoint_row and checkpoint_row[0]:
                            try:
                                # checkpoint 是 pickle 数据，尝试提取时间戳
                                blob_bytes = checkpoint_row[0]
                                if isinstance(blob_bytes, bytes):
                                    # 尝试解码为字符串
                                    try:
                                        text = blob_bytes.decode('utf-8', errors='ignore')
                                    except:
                                        text = ''
                                    # 查找 ISO 格式时间戳 (通常为 UTC)
                                    match = re.search(r'(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})', text)
                                    if match:
                                        utc_ts = f"{match.group(1)}T{match.group(2)}"
                                        # 解析 UTC 时间并转换为本地时间
                                        utc_dt = datetime.fromisoformat(utc_ts).replace(tzinfo=timezone.utc)
                                        local_dt = utc_dt.astimezone(china_tz)
                                        updated_at = local_dt.isoformat()
                                        # 生成会话名称：AI 私厨会话 MM/DD HH:MM
                                        session_name = f"AI 私厨会话 {local_dt.strftime('%m/%d %H:%M')}"
                            except:
                                pass
                        
                        sessions.append(SessionResponse(
                            thread_id=thread_id,
                            user_id=user_id or "chef_default",
                            biz_type="chef",
                            name=session_name,
                            created_at=updated_at,
                            updated_at=updated_at
                        ))
                
                chef_conn.close()
        except Exception:
            pass

    # 按 updated_at 排序
    sessions.sort(key=lambda s: s.updated_at, reverse=True)
    
    return sessions


def delete_session(thread_id: str) -> bool:
    """删除会话"""
    deleted_any = False

    # 从 sessions 表删除
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE thread_id = ?", (thread_id,))
        if cursor.rowcount > 0:
            deleted_any = True
        conn.commit()
        conn.close()
    except Exception:
        pass

    # 从 personal_chief.db 的 checkpoints 表也删除
    try:
        chef_db_path = Path(__file__).parent.parent.parent / "db" / "personal_chief.db"
        if chef_db_path.exists():
            chef_conn = sqlite3.connect(str(chef_db_path))
            chef_cursor = chef_conn.cursor()
            chef_cursor.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
            if chef_cursor.rowcount > 0:
                deleted_any = True
            chef_conn.commit()
            chef_conn.close()
    except Exception:
        pass

    # 如果在任何表中找到了并删除了，返回成功
    # 即使没有找到也返回成功（处理边缘情况）
    return True


def update_session_time(thread_id: str) -> bool:
    """更新会话的最后活跃时间"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute(
            "UPDATE sessions SET updated_at = ? WHERE thread_id = ?",
            (now, thread_id)
        )
        updated = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return updated
    except Exception:
        return False


def ensure_session_exists(thread_id: str, user_id: str = "chef_default", biz_type: str = "chef") -> bool:
    """确保会话存在，如果不存在则自动创建"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        # 检查会话是否存在
        cursor.execute("SELECT thread_id FROM sessions WHERE thread_id = ?", (thread_id,))
        exists = cursor.fetchone() is not None
        
        if not exists:
            # 自动创建会话
            name = f"AI 私厨会话 {datetime.now().strftime('%m/%d %H:%M')}"
            cursor.execute(
                """
                INSERT INTO sessions (thread_id, user_id, biz_type, name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (thread_id, user_id, biz_type, name, now, now)
            )
            conn.commit()
            created = True
        else:
            # 更新最后活跃时间
            cursor.execute(
                "UPDATE sessions SET updated_at = ? WHERE thread_id = ?",
                (now, thread_id)
            )
            conn.commit()
            created = True
        
        conn.close()
        return created
    except Exception:
        return False


# 初始化数据库
init_db()