"""共享助手基类：所有 6 个新助手复用此模块。
每个助手通过 biz_type 区分，共享同一个 SQLite checkpointer。
"""
import os
import re
import sqlite3
import threading
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, AIMessageChunk, AIMessage
from langchain.agents import create_agent
from langgraph.checkpoint.sqlite import SqliteSaver
from app.common.logger import logger
from dotenv import load_dotenv

load_dotenv()

# 共享模型（DeepSeek，免费额度多、速度快）
_model = init_chat_model(
    model="deepseek-chat",
    model_provider="deepseek",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    temperature=0.4,
)

# 共享 checkpointer（每个 biz_type 用不同 thread_id 命名空间）
# timeout=30 等待锁释放，check_same_thread=False 允许跨线程
_db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'db', 'assistants.db'))
_db_lock = threading.Lock()
_db_conn = sqlite3.connect(_db_path, check_same_thread=False, timeout=30)
_db_conn.execute("PRAGMA journal_mode=WAL")  # WAL 模式提升并发性能
_db_conn.execute("PRAGMA busy_timeout=30000")  # 忙等待 30 秒
_checkpointer = SqliteSaver(_db_conn)
_checkpointer.setup()

# 各助手配置
ASSISTANT_CONFIGS = {
    "travel": {
        "name": "AI 旅行规划师",
        "icon": "✈️",
        "system_prompt": """你是「AI 旅行规划师」，一位专业的旅行规划助手。用户会告诉你目的地、预算、时间或偏好，你需要：

1. 根据用户需求推荐合适的目的地或行程方案
2. 生成逐日行程安排（包含景点、餐厅、交通方式）
3. 提供实用信息（天气、签证、货币、交通卡、注意事项）
4. 给出预算估算（交通/住宿/餐饮/门票分别估算）
5. 推荐当地特色美食和必体验项目

输出格式要求：
- 使用 Markdown 结构化输出
- 用 ## 标题分区块（行程概览、每日安排、预算估算、实用贴士等）
- 每日用有序列表列出行程
- 金额用人民币标注
- 保持语言简洁有温度，像朋友给建议
""",
    },
    "fitness": {
        "name": "AI 健身教练",
        "icon": "💪",
        "system_prompt": """你是「AI 健身教练」，一位专业的运动健身助手。用户会告诉你健身目标、当前体型、运动经验等，你需要：

1. 根据目标（减脂/增肌/塑形/耐力）制定个性化训练计划
2. 每周训练安排（含具体动作、组数、次数、休息时间）
3. 详细的动作要领和注意事项（避免受伤）
4. 配合饮食建议（与 AI 私厨联动思路）
5. 阶段性目标和进度回顾方法

输出格式要求：
- 使用 Markdown 结构化输出
- 用 ## 标题分区块（训练目标、周计划、动作详解、饮食建议等）
- 动作用有序列表，包含名称/组数/次数/要点
- 用表格展示周计划概览
- 语言专业但易懂，鼓励性强
""",
    },
    "study": {
        "name": "AI 学习伴侣",
        "icon": "📚",
        "system_prompt": """你是「AI 学习伴侣」，一位全科学习辅导助手。用户会问你各种学科的问题，你需要：

1. 逐步讲解解题思路，不要直接给答案（先引导思考）
2. 用通俗易懂的语言解释复杂概念
3. 提供知识点关联和思维导图式的知识结构
4. 针对薄弱点给出练习建议
5. 制定个性化复习计划

输出格式要求：
- 使用 Markdown 结构化输出
- 数学公式用 LaTeX 语法
- 用 ## 标题分区块（问题分析、解题思路、知识点扩展、练习建议等）
- 解题步骤用有序列表
- 语言耐心、鼓励性强
""",
    },
    "finance": {
        "name": "AI 理财顾问",
        "icon": "💰",
        "system_prompt": """你是「AI 理财顾问」，一位专业的个人财务规划助手。用户会告诉你收入、支出、储蓄目标等，你需要：

1. 分析用户收支状况并给出可视化建议（用表格）
2. 制定储蓄目标和进度追踪方案
3. 科普基础理财知识（定存、基金定投、保险等）
4. 给出消费优化建议（哪些可以节流）
5. 提醒理财风险和注意事项

输出格式要求：
- 使用 Markdown 结构化输出
- 用 ## 标题分区块（收支分析、储蓄方案、理财科普、消费建议等）
- 金额用人民币标注
- 用表格展示收支明细和预算分配
- 语言专业但通俗，不给出具体投资产品推荐，只做知识科普
""",
    },
    "copywriting": {
        "name": "AI 文案写手",
        "icon": "✍️",
        "system_prompt": """你是「AI 文案写手」，一位创意写作助手。用户会告诉你文案用途、风格要求、目标受众等，你需要：

1. 生成朋友圈/小红书/公众号/广告文案
2. 支持多种风格切换（正式/活泼/文艺/搞笑）
3. 提供多个版本的文案供选择
4. 给出文案优化建议（SEO 友好、情感共鸣等）
5. 生成产品描述、广告语、Slogan 等

输出格式要求：
- 使用 Markdown 结构化输出
- 用 ## 标题分区块（文案选项、风格说明、优化建议等）
- 每个文案选项用引用块标注
- 语言有创意、有感染力
""",
    },
    "coding": {
        "name": "AI 编程助手",
        "icon": "💻",
        "system_prompt": """你是「AI 编程助手」，一位专业的技术答疑和代码助手。用户会问你编程问题、让你写代码或调试代码，你需要：

1. 代码审查与 Bug 定位（指出问题并给出修复方案）
2. 代码片段生成（提供完整可运行的代码）
3. 技术概念讲解（框架/算法/设计模式，通俗易懂）
4. 代码优化建议（性能/可读性/最佳实践）
5. 支持多种编程语言（Python/JavaScript/Java/Go 等）

输出格式要求：
- 代码必须用 Markdown 代码块包裹，并标注语言
- 用 ## 标题分区块（问题分析、解决方案、代码实现、优化建议等）
- 代码注释用中文
- 语言专业、精准、简洁
""",
    },
}

# 为每个助手创建独立的 agent 实例
_agents = {}
for _biz_type, _config in ASSISTANT_CONFIGS.items():
    _agents[_biz_type] = create_agent(
        model=_model,
        tools=[],
        checkpointer=_checkpointer,
        system_prompt=_config["system_prompt"],
    )
    logger.info(f"助手 agent 初始化完成: {_config['name']} ({_biz_type})")


def _sse_send(text: str) -> str:
    """SSE 格式包装"""
    safe = text.replace("\n", "\\n").replace("\r", "\\r")
    return f"data: {safe}\n\n"


async def stream_assistant(biz_type: str, prompt: str, thread_id: str):
    """通用流式对话函数，所有助手共用"""
    config = ASSISTANT_CONFIGS.get(biz_type)
    if not config:
        yield _sse_send(f"未知的助手类型: {biz_type}")
        return

    agent = _agents[biz_type]
    logger.info(f"[{config['name']}] thread={thread_id} msg={prompt[:80]}")

    try:
        message = HumanMessage(content=prompt)
        # 立刻发占位字符，让前端解除"等待"状态
        yield _sse_send("\u200b")

        answer_buf: list[str] = []
        chunk_count = 0
        # 使用线程锁保护数据库访问
        with _db_lock:
            for chunk, metadata in agent.stream(
                {"messages": [message]},
                {"configurable": {"thread_id": thread_id}},
                stream_mode="messages",
            ):
                if isinstance(chunk, AIMessageChunk) and chunk.content:
                    text = chunk.content
                    answer_buf.append(text)
                    chunk_count += 1
                    yield _sse_send(text)

        logger.info(f"[{config['name']}] 流式完成 thread={thread_id} chunks={chunk_count} len={len(''.join(answer_buf))}")

    except Exception as e:
        logger.error(f"[{config['name']}] 错误: {type(e).__name__}: {e}")
        yield _sse_send(f"处理失败：{str(e)[:300]}。请刷新页面重试。")


def get_messages(biz_type: str, thread_id: str) -> list[dict[str, str]]:
    """获取指定助手会话的历史消息"""
    try:
        with _db_lock:
            checkpoint = _checkpointer.get({"configurable": {"thread_id": thread_id}})
        if not checkpoint:
            return []
        channel_values = checkpoint.get("channel_values")
        if not channel_values:
            return []
        messages = channel_values.get("messages", [])
        if not messages:
            return []
        result = []
        for msg in messages:
            if not msg.content:
                continue
            if isinstance(msg, HumanMessage):
                result.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                result.append({"role": "assistant", "content": msg.content})
        return result
    except Exception as e:
        logger.error(f"获取历史消息失败: {type(e).__name__}: {e}")
        return []


def clear_messages(thread_id: str):
    """清空会话历史"""
    logger.info(f"清空助手会话: {thread_id}")
    try:
        with _db_lock:
            _checkpointer.delete_thread(thread_id)
    except Exception as e:
        logger.error(f"清空会话失败: {type(e).__name__}: {e}")
