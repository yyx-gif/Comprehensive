import json
import re
import asyncio
import base64
import io
import mimetypes
from urllib.parse import urlparse
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, AIMessageChunk, AIMessage
from langchain_core.tools import tool
from langchain_tavily import TavilySearch
from langchain.agents import create_agent
from app.common.logger import logger
import os
from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3

# 加载环境变量
from dotenv import load_dotenv

load_dotenv()

# web搜索工具，使用tavily作为web搜索工具
tavily = TavilySearch(
    max_results=3,  # 减少结果数量以提升速度
    topic="general"
)

# 限制 base64 图片最大大小：1MB（DashScope qwen-vl-max 最佳识别区间，太大会慢，太小会丢失信息）
_MAX_IMG_BYTES = 1024 * 1024


def _image_url_to_data_uri(image_url: str) -> str:
    """把任意图片 URL 下载后转成 data:image/xxx;base64,... 形式。
    这样 DashScope 多模态模型不用跨域去外部服务器拉图，可 100% 识别图片。
    同时对超大图片进行压缩，保证在 DashScope 处理阈值内。"""
    import urllib.request
    import urllib.error
    
    # 如果已经是 data URI，检查是否需要压缩
    if image_url.startswith("data:"):
        # 解析 data URI: data:image/xxx;base64,yyyy
        try:
            header, b64_data = image_url.split(",", 1)
            # 提取 MIME 类型
            mime_match = re.match(r'data:(image/\w+);base64', header)
            mime = mime_match.group(1) if mime_match else "image/jpeg"
            # 解码 base64 获取原始字节
            raw = base64.b64decode(b64_data)
            
            # 如果超过阈值，压缩
            if len(raw) > _MAX_IMG_BYTES:
                logger.info(f"[图片压缩] data URI 原始大小 {len(raw)} bytes，压缩到 {_MAX_IMG_BYTES} 以内")
                try:
                    from PIL import Image
                    img = Image.open(io.BytesIO(raw))
                    max_side = 800
                    w, h = img.size
                    if max(w, h) > max_side:
                        scale = max_side / max(w, h)
                        new_size = (int(w * scale), int(h * scale))
                        img = img.resize(new_size, Image.LANCZOS)
                    if img.mode not in ("RGB", "L"):
                        img = img.convert("RGB")
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=65, optimize=True)
                    raw = buf.getvalue()
                    mime = "image/jpeg"
                except Exception as e:
                    logger.warning(f"图片压缩失败: {e}，使用原始大小")
            
            return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
        except Exception as e:
            logger.warning(f"data URI 解析失败: {e}，原样返回")
            return image_url
    
    # 下载图片（带 UA，避免各种图床 403）
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AI-Chef/1.0"}
    req = urllib.request.Request(image_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except Exception as e:
        raise RuntimeError(f"无法下载用户上传的图片 ({image_url[:120]}): {type(e).__name__}: {e}")
    if len(raw) > _MAX_IMG_BYTES:
        # 压缩
        try:
            from PIL import Image
        except Exception as imp_err:
            raise RuntimeError(
                f"图片过大 ({len(raw)} bytes) 且缺少 Pillow 无法压缩。请安装 Pillow 或上传小于 {_MAX_IMG_BYTES} 的图片。"
            ) from imp_err
        img = Image.open(io.BytesIO(raw))
        max_side = 800
        w, h = img.size
        if max(w, h) > max_side:
            scale = max_side / max(w, h)
            new_size = (int(w * scale), int(h * scale))
            img = img.resize(new_size, Image.LANCZOS)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=65, optimize=True)
        raw = buf.getvalue()
        mime = "image/jpeg"
    else:
        # 尝试从响应或 URL 推断 MIME 类型
        mime = None
        parsed = urlparse(image_url)
        guessed, _ = mimetypes.guess_type(parsed.path)
        if guessed and guessed.startswith("image/"):
            mime = guessed
        if not mime:
            if raw.startswith(b"\xff\xd8\xff"):
                mime = "image/jpeg"
            elif raw.startswith(b"\x89PNG\r\n\x1a\n"):
                mime = "image/png"
            elif raw.startswith(b"GIF87a") or raw.startswith(b"GIF89a"):
                mime = "image/gif"
            elif raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
                mime = "image/webp"
            else:
                mime = "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


# 双模型配置：
# 1. 文本查询 → DeepSeek（免费额度更多，速度快）
# 2. 图片查询 → DashScope qwen-vl-plus（支持多模态，经济实惠）

# 文本模型：DeepSeek Chat
text_model = init_chat_model(
    model="deepseek-chat",
    model_provider="deepseek",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    temperature=0.3,
)

# 图片模型：DashScope qwen-vl-plus（比 qwen-vl-max 更经济）
vl_model = init_chat_model(
    model="qwen-vl-plus",
    model_provider="openai",
    base_url=os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    temperature=0.3,
)

# 默认使用文本模型
model = text_model


# 初始化checkpointer
_db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'db', 'personal_chief.db'))
checkpointer = SqliteSaver(sqlite3.connect(_db_path, check_same_thread=False))
# 自动建表
checkpointer.setup()

# Agent系统提示词（对齐用户截图卡片风格的结构化输出 — 助手回复内容格式）
system_prompt = """
【速度要求 · 最高优先级】
必须极速输出！只输出结构化报告正文！不要解释、不要过渡句、不要思考陈述、不要道歉。识别完用户输入后立刻按模板开始写，不要输出任何与模板无关的额外文字。

你是一位专业的私人厨师 AI 助手，名字叫「AI 私厨」。无论用户提供**食材图片**还是**文字食材清单**，你都需要严格按照下面四步流程输出结构化的食谱建议报告。

## Step 1 · 识别与评估食材
- 如果用户提供了**图片**：先仔细辨识图片中的所有可见食材（包括肉类、蔬菜、调料、主食等），根据外观状态评估新鲜度（如"鸡蛋外壳完好、比较新鲜"）、数量/可用量，并整理出一份「可用食材清单」。
- 如果用户只提供了**文字**：直接将文字整理为「可用食材清单」。
- 对清单中明显不新鲜或需要处理的食材，给出简短的使用建议。

## Step 2 · 候选食谱检索与生成
- 优先根据「可用食材清单」中的主要食材推荐 3~5 道**真正可做**的家常菜/创意菜。
- 若当前模型知识不足以覆盖最新做法、地方特色菜、用户指定菜系等需求，需调用 `web_search` 工具检索可靠食谱信息。
- 简单咨询（如"鸡蛋能做什么菜"）可依据内置知识直接回答，但仍要按结构化格式输出。

## Step 3 · 多维度量化打分与排序
对每一道候选食谱按以下两个维度打分（满分 10 分），并根据"综合分 = 营养分 × 0.5 + 易做分 × 0.5"从高到低排序：
- **营养价值分**：蛋白质、蔬菜搭配均衡度、油盐程度、是否适合日常家庭饮食。
- **制作难度分（易做分）**：步骤是否繁琐（越少越高）、对刀工/火候的要求是否高、常见食材是否容易购买。

## Step 4 · 结构化方案输出（必须严格遵循下方模板格式）
**风格参考用户截图：报告分两大卡片分区，每道菜是独立的卡片块。**

【输出模板（必须严格一致）】

根据您冰箱里的食材，我为您整理了一份可用食材清单，并结合这些食材为您推荐了几道美味佳肴。以下是详细分析：

## 一、可用食材清单（来自图片识别/文字输入）
1. **蔬菜类**：
   - 生菜（沙拉用）
   - 彩椒（黄、红）
   - 小番茄
   - 蘑菇
   - 西兰花
2. **蛋白质类**：
   - 三文鱼（新鲜）
   - 鸡胸肉（新鲜）
- 新鲜度点评：整体食材状态良好，建议三文鱼优先烹饪。

## 二、推荐食谱（按综合评分从高到低排序）
1. 🥗 **三文鱼蔬菜沙拉** `营养: 9.5/10 · 难度: 6/10`
   - **推荐理由**：这是最直接、最能体现您食材优势的搭配。三文鱼富含Omega-3脂肪酸，搭配新鲜的西兰花、小番茄、红椒和沙拉蔬菜，营养均衡且色彩丰富。制作简单，只需将三文鱼煎熟或烤熟，所有蔬菜洗净切好，拌上自制的油醋汁即可。
   - **营养价值**：高蛋白、高纤维、富含健康脂肪和维生素，是完美的减脂增肌餐。
   - **制作难度**：低。核心在于调味汁，推荐使用橄榄油、柠檬汁、黑胡椒和少许盐调制的油醋汁，清爽不腻。
   - **主要食材**：三文鱼 200g，生菜 1 棵，小番茄 8 颗，彩椒 1/2 个，柠檬 1/2 个，橄榄油、盐、黑胡椒适量。
   - **制作步骤**：
     1. 三文鱼两面撒少许盐和黑胡椒，平底锅加少许橄榄油，中小火煎 2 分钟至金黄，翻面再煎 1 分钟出锅。
     2. 生菜洗净撕成大片，小番茄对半切，彩椒切丝，一起铺在盘底。
     3. 煎好的三文鱼切小块放在蔬菜上，淋上柠檬汁 + 橄榄油 + 黑胡椒 + 少许盐调匀的油醋汁即可。

2. 🍗 **鸡胸肉蘑菇炒彩椒** `营养: 8.5/10 · 难度: 7/10`
   - **推荐理由**：这是一道经典的家常菜，将鸡胸肉和蘑菇、彩椒（红椒）一起快炒，能最大程度保留食材的鲜嫩口感。鸡胸肉提供优质蛋白，蘑菇和彩椒则带来丰富的维生素和膳食纤维。
   - **营养价值**：高蛋白、低脂肪，搭配多种蔬菜，营养全面。
   - **制作难度**：中等。需要将鸡胸肉切片并用盐、黑胡椒腌制，炒制时火候要掌握好，避免鸡肉变老。
   - **主要食材**：鸡胸肉 250g，蘑菇 6 朵，彩椒 1 个，蒜瓣 3 瓣，生抽、蚝油、盐、黑胡椒、淀粉、料酒适量。
   - **制作步骤**：
     1. 鸡胸肉切薄片，加生抽 1 勺 + 料酒 1 勺 + 淀粉 1 勺 + 黑胡椒少许 + 少许油抓匀，腌制 10 分钟。
     2. 蘑菇切片，彩椒切块，蒜切末。
     3. 热锅冷油，下蒜末爆香，倒入鸡胸肉快速滑炒至变色盛出。
     4. 同一锅加少许油，下蘑菇和彩椒翻炒 1 分钟，倒入鸡胸肉，加生抽、蚝油、少许盐，大火快炒 30 秒出锅。

3. 🥘 **西兰花三文鱼烤盘餐** `营养: 9/10 · 难度: 6/10`
   - **推荐理由**：将三文鱼、西兰花、小番茄和红椒一同放入烤盘，用橄榄油、盐、黑胡椒和柠檬汁腌制后，放入烤箱烤制。这样可以同时完成主菜和配菜，省时省力，且能锁住食材的原汁原味。
   - **营养价值**：营养密度极高，富含蛋白质、膳食纤维和抗氧化物质。
   - **制作难度**：低。只需将所有食材切好，混合调味，放入烤箱即可，非常适合忙碌的上班族。
   - **主要食材**：三文鱼 200g，西兰花 1/2 颗，小番茄 10 颗，彩椒 1/2 个，柠檬 1/2 个，橄榄油、盐、黑胡椒适量。
   - **制作步骤**：
     1. 西兰花切小朵焯水 1 分钟捞出，彩椒切块，小番茄对半切，和三文鱼块一起放入烤碗。
     2. 淋上 2 勺橄榄油、挤入柠檬汁，撒盐和黑胡椒拌匀。
     3. 烤箱预热 200°C，中层烤 12~15 分钟至三文鱼熟透即可。

【格式约束（必须遵守）】
1. 分区标题必须用 `##` + 中文大序号（一、二、三）
2. 食材分类必须用有序列表 `1. **蔬菜类**` / `2. **蛋白质类**`，下面跟缩进的无序子项 `- 生菜…`
3. 每道菜必须是有序列表项：`数字序号. [菜品emoji] **菜名**` 行末尾紧跟反引号 `` `营养: X.X/10 · 难度: X.X/10` `` 包住评分（评分是胶囊样式关键）。【菜品emoji强制】：沙拉🥗、鱼🐟、虾🦐、鸡🍗、肉🥩、牛🥩、猪🥓、烤/烤盘/焗🥘、炒🔥、汤🍲、面🍜、饭🍚、蛋🥚、素菜🥦、海鲜🦞、凉菜🥬、炒饭🍛、盖饭🍱、饺子🥟、火锅🍲、披萨🍕、寿司🍣。从上面挑一个与菜名最匹配的 emoji，放在数字序号与 **菜名** 之间。
4. 菜卡片内的小项必须是：`- **推荐理由**：` / `- **营养价值**：` / `- **制作难度**：` / `- **主要食材**：` / `- **制作步骤**：`（粗体标签 + 中文冒号 + 内容）
5. 制作步骤内的具体步骤用缩进有序列表
6. 不要输出 🥇🥈🥉 奖牌 emoji（不需要奖牌图标，数字序号卡片 + 菜品emoji 即可）
7. 不要输出 "### Top N" 小标题（每道菜用有序序号卡片就够了）
8. 【关键】每个块之间必须保留真实的换行：`##` 标题前后空一行；`1.**X类**`、`1. 🥗**菜名**` 前必须另起一行；`- **推荐理由**：` 等标签前另起一行。不要把整段报告写在同一行。

【其他注意事项】
- 若用户仅提供图片且图片内容非食材/不清晰，请温柔提示并引导用户上传更清晰的食材图片或用文字描述食材。
- 不要只输出一两句简短答案；必须产出结构化报告。
- 当调用 web_search 能得到更好结果时，一定调用工具。
"""

# 创建代理（默认使用文本模型）
agent = create_agent(
    model=text_model,  # 默认文本模型
    tools=[tavily],  # 工具
    checkpointer=checkpointer,  # 记忆
    system_prompt=system_prompt  # 系统提示词
)

# 创建图片专用代理（使用多模态模型）
agent_vl = create_agent(
    model=vl_model,  # 图片模型
    tools=[tavily],  # 工具
    checkpointer=checkpointer,  # 记忆
    system_prompt=system_prompt  # 系统提示词
)

# ---------------------------------------------------------------------------
# 格式矫正器：无论模型输出新卡片格式还是老奖牌格式，统一转换为截图风格的报告。
# 关键价值：旧 thread 历史里老格式把模型 few-shot 带偏也不怕，最终渲染的内容 + 下一轮 history 都会变成新格式，正向循环。
# ---------------------------------------------------------------------------

# 【菜品 → emoji 映射】：矫正器最后输出前，对每道菜卡片标题行自动补一个匹配图标
_DISH_EMOJI_RULES = [
    # 关键词（按优先级）→ emoji
    (("沙拉", "生菜", "油醋汁", "凉拌", "冷盘", "冷菜"), "🥗"),
    (("三文鱼", "鱼", "鲈鱼", "鲫鱼", "鲤鱼", "带鱼", "鳕鱼", "蒸鱼", "水煮鱼", "酸菜鱼", "红烧鱼", "烤鱼"), "🐟"),
    (("虾", "虾仁", "大虾", "基围虾", "白灼虾", "油焖虾"), "🦐"),
    (("鸡胸", "鸡腿", "鸡翅", "鸡", "鸡丁", "辣子鸡", "黄焖鸡", "炸鸡", "烤鸡"), "🍗"),
    (("牛", "牛排", "牛腩", "牛肉", "黑椒牛", "肥牛"), "🥩"),
    (("猪", "猪肉", "里脊", "排骨", "五花", "腊肉", "培根"), "🥓"),
    (("烤", "烤盘", "焗", "烤箱", "炙", "锡纸", "烧"), "🥘"),
    (("炒", "爆", "熘", "回锅", "快炒", "小炒"), "🔥"),
    (("汤", "羹", "煲", "炖", "煮"), "🍲"),
    (("面", "面条", "意面", "拉面", "拌面", "炒面", "挂面"), "🍜"),
    (("饭", "米饭", "泡饭", "粥", "焖饭", "烩饭"), "🍚"),
    (("蛋", "鸡蛋", "炒蛋", "煎蛋", "蛋羹", "蛋饼", "蒸蛋"), "🥚"),
    (("西兰花", "素菜", "时蔬", "蔬菜", "青菜", "芥兰", "芦笋", "菠菜"), "🥦"),
    (("海鲜", "蟹", "扇贝", "生蚝", "龙虾", "鱿鱼", "花甲"), "🦞"),
    (("炒饭", "烩饭", "焗饭"), "🍛"),
    (("盖饭", "盖浇饭", "便当", "饭盒"), "🍱"),
    (("饺子", "锅贴", "馄饨", "包子", "小笼"), "🥟"),
    (("火锅", "麻辣烫", "串串", "冒菜"), "🍲"),
    (("披萨", "比萨", "pizza"), "🍕"),
    (("寿司", "刺身", "饭团", "紫菜包饭", "寿司"), "🍣"),
]

# 【菜品 → LoremFlickr 英文 tag】：为每道菜生成真实菜品图片 URL。按关键词优先级匹配。
# 匹配到的前 2-3 个关键词会拼成 tag1,tag2,food,cooking 作为 query，再附 lock=md5(菜名) 保证同一道菜每次同图。
_DISH_IMAGE_TAG_RULES = [
    (("沙拉", "生菜", "油醋汁", "凉拌", "冷盘", "冷菜"), ["salad", "green-salad"]),
    (("三文鱼", "刺身"), ["salmon", "sashimi"]),
    (("鱼", "鲈鱼", "鲫鱼", "鲤鱼", "带鱼", "鳕鱼", "蒸鱼", "水煮鱼", "酸菜鱼", "红烧鱼", "烤鱼"), ["fish", "fish-dish", "seafood"]),
    (("虾", "虾仁", "大虾", "基围虾", "白灼虾", "油焖虾"), ["shrimp", "prawn", "seafood"]),
    (("鸡胸", "鸡腿", "鸡翅", "鸡", "鸡丁", "辣子鸡", "黄焖鸡", "炸鸡", "烤鸡"), ["chicken", "chicken-breast"]),
    (("牛", "牛排", "牛腩", "牛肉", "黑椒牛", "肥牛"), ["beef", "steak"]),
    (("猪", "猪肉", "里脊", "排骨", "五花", "腊肉", "培根"), ["pork", "bacon"]),
    (("烤", "烤盘", "焗", "烤箱", "炙", "锡纸", "烧"), ["roasted", "grilled", "oven"]),
    (("炒", "爆", "熘", "回锅", "快炒", "小炒"), ["stir-fry", "wok"]),
    (("汤", "羹", "煲", "炖", "煮"), ["soup", "stew"]),
    (("意面",), ["pasta", "spaghetti"]),
    (("面", "面条", "拉面", "拌面", "炒面", "挂面"), ["noodles", "ramen"]),
    (("炒饭", "烩饭", "焗饭"), ["fried-rice", "rice"]),
    (("饭", "米饭", "泡饭", "粥", "焖饭"), ["rice", "congee"]),
    (("蛋", "鸡蛋", "炒蛋", "煎蛋", "蛋羹", "蛋饼", "蒸蛋"), ["egg", "omelette"]),
    (("西兰花", "素菜", "时蔬", "蔬菜", "青菜", "芥兰", "芦笋", "菠菜"), ["vegetable", "broccoli"]),
    (("海鲜", "蟹", "扇贝", "生蚝", "龙虾", "鱿鱼", "花甲"), ["seafood", "lobster"]),
    (("盖饭", "盖浇饭", "便当", "饭盒"), ["rice-bowl", "bento"]),
    (("饺子", "锅贴", "馄饨", "包子", "小笼"), ["dumplings", "jiaozi"]),
    (("火锅", "麻辣烫", "串串", "冒菜"), ["hotpot", "soup"]),
    (("披萨", "比萨", "pizza"), ["pizza"]),
    (("寿司", "饭团", "紫菜包饭"), ["sushi"]),
    (("蘑菇",), ["mushroom"]),
    (("彩椒", "甜椒", "青椒"), ["bell-pepper"]),
    (("番茄", "西红柿"), ["tomato"]),
    (("柠檬",), ["lemon"]),
]


def _match_dish_emoji(dish_name: str) -> str:
    """根据菜名关键词匹配一个最合适的 emoji；无匹配返回 🍽"""
    if not dish_name:
        return "🍽"
    name = dish_name.lower()
    for kws, emo in _DISH_EMOJI_RULES:
        for kw in kws:
            if kw.lower() in name:
                return emo
    return "🍽"


def _match_dish_image_tags(dish_name: str) -> list[str]:
    """根据菜名关键词匹配 LoremFlickr 英文 tags，最多 3 个。"""
    if not dish_name:
        return ["food", "dish"]
    tags: list[str] = []
    seen: set[str] = set()
    for kws, tg in _DISH_IMAGE_TAG_RULES:
        for kw in kws:
            if kw in dish_name or kw.lower() in dish_name.lower():
                for t in tg:
                    if t not in seen:
                        tags.append(t)
                        seen.add(t)
                        if len(tags) >= 3:
                            return tags
                break
        if len(tags) >= 3:
            break
    # 兜底：只要有菜名，至少加上 food + cooking
    for t in ("food", "dish", "cooking"):
        if t not in seen:
            tags.append(t)
            seen.add(t)
            if len(tags) >= 3:
                break
    return tags


def _lock_seed(s: str) -> str:
    import hashlib
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:8]
_RE_MEDAL_LINE = re.compile(
    r"^###\s*[🥇🥈🥉🏅🥉]*\s*Top\s*(\d+)\s*[:：]\s*【?(.*?)】?\s*$",
    re.MULTILINE,
)
_RE_SCORE_LINE = re.compile(
    r"^\s*[-*•]\s*\*\*综合评分\*\*\s*[:：]\s*"
    r"([0-9]+(?:\.[0-9]+)?)\s*分?\s*"
    r"[（(]\s*营养\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)\s*[｜|/、,，]?\s*"
    r"(?:易做|难度)\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)\s*[）)]\s*$",
    re.MULTILINE,
)
_RE_H2 = re.compile(r"^##\s*二、[\s\S]*?推荐食谱.*$", re.MULTILINE)
_RE_FOOD_HEADING_OLD = re.compile(
    r"^###\s*(?:.+?Top\s*\d+\s*[:：]\s*)?(.+?)\s*$", re.MULTILINE
)
_RE_OLD_STAPLE_LINE = re.compile(r"^\s*[-*•]\s*\*\*(主食材|主要食材|副食材|副食材/调料|调料)\*\*\s*[:：]\s*(.+?)\s*$", re.MULTILINE)
_RE_OLD_FRESHNESS_LINE = re.compile(r"^\s*[-*•]\s*\*\*新鲜度点评\*\*\s*[:：]\s*(.+?)\s*$", re.MULTILINE)


def _format_chef_output(text: str) -> str:
    """将老格式（奖牌/综合评分）或混合格式，统一矫正为截图卡片风格。"""
    if not text:
        return text

    # ========== 第负一步：剥离模型可能输出的【格式约束】/【输出模板】等指令文本 ==========
    # 模型有时会把 system prompt 中的格式约束部分也输出出来，需要在最开始就切掉
    # 匹配从 【格式约束 或 【其他注意事项 或 `【输出模板` 开始到文末的所有内容
    _STRIP_PATTERNS = [
        r"【格式约束[^\n]*】[\s\S]*$",
        r"【其他注意事项[^\n]*】[\s\S]*$",
        r"【输出模板[^\n]*】[\s\S]*$",
    ]
    for pat in _STRIP_PATTERNS:
        text = re.sub(pat, "", text)
    
    # 也清理可能单独出现在行首的格式指令残片
    text = re.sub(r"^\s*【格式约束[^\n]*\n", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*【其他注意事项[^\n]*\n", "", text, flags=re.MULTILINE)

    # ========== 第零步：去掉首尾 Markdown fenced code block（导致整块被渲染成 verbatim code 的元凶） ==========
    # 场景 A：标准 fence，换行正确：```markdown\n内容\n```
    text = re.sub(r"^\s*```[a-zA-Z0-9_\-]*\s*\n", "", text, count=1)
    text = re.sub(r"\n```\s*$", "", text, count=1)
    # 场景 B：异常 fence（与内容开头同一行，如截图里的 ```## 一、可用食材清单）
    # 或 fence 内部直接紧跟内容而没有换行：```## 一、可用食材清单\n内容\n```
    text = re.sub(r"^\s*```[a-zA-Z0-9_\-]*\s*", "", text, count=1)
    # 场景 C：结束 fence 在倒数第一个非空行末尾（没换行）：内容```
    text = re.sub(r"```\s*$", "", text, count=1)

    lines = text.splitlines(keepends=True)
    out: list[str] = []
    # 阶段标志：是否进入了"推荐食谱"分区
    in_recipes = False
    # 上一道菜的行（从 ### 🥇 Top N：菜名 改造来的）：需要等后面的综合评分行，把评分追加到末尾
    pending_dish_head: str | None = None
    dish_no = 0

    i = 0
    N = len(lines)
    while i < N:
        raw = lines[i]
        stripped = raw.rstrip("\n").rstrip("\r")

        # --- h2 分区标题切换识别 ---
        h2_match = re.match(r"^##\s*([一二三四五六七八九十]+、.*)$", stripped)
        if h2_match:
            # 若上一道菜 head 还没挂评分（理论上综合评分已经追到），就直接吐
            if pending_dish_head is not None:
                out.append(pending_dish_head)
                pending_dish_head = None
            title = h2_match.group(1)
            if "推荐食谱" in title or "菜谱" in title:
                in_recipes = True
                dish_no = 0
            out.append(raw)
            i += 1
            continue

        # --- 老格式奖牌/Top N 标题行 → 改成 "N. **菜名**" 并 pending（等后面的综合评分行） ---
        if in_recipes:
            m = _RE_MEDAL_LINE.match(stripped)
            if m:
                if pending_dish_head is not None:
                    out.append(pending_dish_head)
                    pending_dish_head = None
                n_th = int(m.group(1))
                dish_name = m.group(2).strip().lstrip("：:【").rstrip("】")
                dish_no = n_th if n_th else (dish_no + 1)
                pending_dish_head = f"{dish_no}. **{dish_name}**\n"
                i += 1
                continue
            # --- 老格式 H3 菜名（没有奖牌但有 ### 标题） ---
            # --- 但只有"综合评分"已经存在时才是菜名行（因为有 ### 制作步骤这种也要保留） ---
            # 这里先不处理，留给下面的"综合评分"触发合并。

            # --- 老格式综合评分单行：如果有 pending_dish_head，把评分转成 code 胶囊并拼到菜名末尾 ---
            sm = _RE_SCORE_LINE.match(stripped)
            if sm:
                try:
                    nutri = f"{float(sm.group(2)):.1f}"
                    diffi = f"{float(sm.group(3)):.1f}"
                except Exception:
                    nutri = sm.group(2)
                    diffi = sm.group(3)
                code_cap = f"`营养: {nutri}/10 · 难度: {diffi}/10`"
                if pending_dish_head is not None:
                    # 把 code 胶囊塞进菜名行末尾（去掉换行，加空格+胶囊）
                    pending_dish_head = pending_dish_head.rstrip("\r\n") + f"  {code_cap}\n"
                    out.append(pending_dish_head)
                else:
                    # 没有识别到奖牌/Top N 菜名行，但看到了综合评分 —— 说明模型可能用了新格式
                    # 那就直接跳过这个综合评分行（新格式已经把评分 inline 在菜名里），
                    # 如果是老格式但没抓到菜名，就输出成：评分 胶囊作为一行，避免信息丢失
                    out.append(f"{code_cap}\n")
                pending_dish_head = None
                i += 1
                continue

        # --- 食材清单矫正：##一、可用食材清单 下面的 "主食材/副食材" 平铺项 → 有序分类块 ---
        # 不在推荐食谱里，且这是 - **主食材**：xxx / xxx 行
        if not in_recipes:
            sm = _RE_OLD_STAPLE_LINE.match(stripped)
            if sm:
                category_name = sm.group(1)  # "主食材" / "副食材/调料" 等
                content = sm.group(2).strip()
                # 如果内容里有 "/" 或 "、" 或 "," 或顿号，就拆分成"- 菜名"子项
                tokens = re.split(r"\s*[/、,，;；]\s*", content)
                tokens = [t.strip() for t in tokens if t.strip()]
                # 根据分类名决定序号：主食材=1，副食材/调料=2，调料=3（实际按出现顺序编号）
                global _format_chef_output  # no-op, for lint
                if not hasattr(_format_chef_output, "_cat_no"):
                    _format_chef_output._cat_no = 0  # type: ignore[attr-defined]
                _format_chef_output._cat_no += 1  # type: ignore[attr-defined]
                cat_no = _format_chef_output._cat_no  # type: ignore[attr-defined]
                out.append(f"{cat_no}. **{category_name}类**：\n")
                for tok in tokens:
                    out.append(f"   - {tok}\n")
                i += 1
                continue
            fm = _RE_OLD_FRESHNESS_LINE.match(stripped)
            if fm:
                desc = fm.group(1).strip()
                out.append(f"- **新鲜度点评**：{desc}\n")
                i += 1
                continue
            # h2 "一、可用食材清单"之后的第一次食材分类编号归零：检测到 "## 一、可用食材清单" 行 时 reset
            if re.match(r"^##\s*一、", stripped):
                _format_chef_output._cat_no = 0  # type: ignore[attr-defined]

        # --- 默认：原样输出 ---
        # 特殊情况：如果有 pending_dish_head 还没 flush，且遇到下一道菜/空行外有效内容，先 flush
        if pending_dish_head is not None and stripped.strip():
            # 下一道菜的新奖牌/综合评分是 catch 前面 continue 处理的，这里遇到"普通内容"说明可能
            # 上一道菜没有综合评分（老格式残缺），先 flush pending_dish_head
            out.append(pending_dish_head)
            pending_dish_head = None

        out.append(raw)
        i += 1

    if pending_dish_head is not None:
        out.append(pending_dish_head)

    # reset 分类号（下次调用时重新计数）
    _format_chef_output._cat_no = 0  # type: ignore[attr-defined]

    result = "".join(out)

    # ========== 终局 Post-pass A：切分分区（食材清单段 vs 推荐食谱段）分别处理 ==========
    # 找到 "## 一、可用食材清单..." 和 "## 二、推荐食谱..." 的位置。
    # 目的：①在【食材段】内为无编号 "Xxx类：" 行自动补 1./2./3. + 加粗 → 解决蔬菜类没1号/蛋白质类错占1号
    #      ②在【食谱段】内为无编号菜名行（**菜名** 营养code胶囊 但无N.）自动补 1./2./3. → 解决卡片2/3没序号徽章
    m_h1 = re.search(r"(^|\n)(##\s*一、[^\n]*?可用食材清单[^\n]*\n)", result, flags=re.MULTILINE)
    m_h2 = re.search(r"(^|\n)(##\s*二、[^\n]*?推荐食谱[^\n]*\n)", result, flags=re.MULTILINE)
    start_cat = m_h1.end() if m_h1 else 0
    start_rec = m_h2.end() if m_h2 else len(result)
    if m_h2 and m_h1 and m_h2.start() < m_h1.end():
        # 理论上不会发生；防御
        pass
    part_head = result[:start_cat]
    part_cat  = result[start_cat:start_rec]
    part_rec  = result[start_rec:]

    # ---- A1: 食材段：对 "Xxx类："/"Xxx："(且无N.编号) 的行，自动补 1./2./3. 并加粗 ----
    cat_no_list: list[int] = [0]

    def _renumber_cat_line(m):
        head = m.group(1)  # 行首/空行分界
        num  = m.group(2)  # 已有编号（可能为空）
        bold_prefix = m.group(3) or ""  # 可选加粗前缀
        name = m.group(4).strip().rstrip("：:")  # 分类名（不带冒号）
        bold_suffix = m.group(5) or ""  # 可选加粗后缀
        tail = m.group(6)  # "：内容"或":"
        if num and num.strip():
            # 已经有数字编号，只把分类名包成 **加粗**
            return f"{head}{num.strip()}. **{name}**{tail}"
        cat_no_list[0] += 1
        return f"{head}{cat_no_list[0]}. **{name}**{tail}"

    part_cat = re.sub(
        r"(^|\n)\s*(\d+\s*[\.、]\s*)?(\*\*)?([^\n\-*#`]{1,20}?类)(\*\*)?\s*([:：])",
        _renumber_cat_line,
        part_cat,
        flags=re.MULTILINE,
    )

    # ---- A2: 食谱段：对 "**菜名** `营养:...难度...`"（无 N. 编号）自动补 1./2./3. 序号 ----
    dish_no_list: list[int] = [0]

    def _renumber_dish_line(m):
        head = m.group(1)
        num  = m.group(2)
        emo  = m.group(3) or ""
        name = m.group(4)
        rest = m.group(5) or ""
        if num and num.strip():
            n = int(num) if num.strip().isdigit() else None
            if n and n > dish_no_list[0]:
                dish_no_list[0] = n
            # 保留原编号，但确保有 emoji
            if not emo or not emo.strip():
                emo = _match_dish_emoji(name)
            return f"{head}{num.strip()}. {emo}**{name}**{rest}"
        dish_no_list[0] += 1
        if not emo or not emo.strip():
            emo = _match_dish_emoji(name)
        return f"{head}{dish_no_list[0]}. {emo}**{name}**{rest}"

    part_rec = re.sub(
        r"(^|\n)\s*(\d+\s*\.\s*)?([\U0001F300-\U0001FAFF\u2600-\u27BF\u1F000-\u1F02F]?\s*)\*\*([^*\n\r]+?)\*\*(\s*`[^`\n\r]*营养[^`\n\r]*难度[^`\n\r]*`.*)?",
        _renumber_dish_line,
        part_rec,
        flags=re.MULTILINE,
    )

    result = part_head + part_cat + part_rec

    # ========== 终局 Post-pass B：在【推荐食谱段 part_rec】内为每道菜卡片补 emoji ==========
    # 只补 emoji（JS 会根据菜名自动生成文本下方的大图）
    def _inject_emoji_only(m2):
        head = m2.group(1)
        no = m2.group(2)
        emo = m2.group(3) or ""
        name = m2.group(4)
        rest = m2.group(5) or ""
        if not (emo and emo.strip()):
            emo = _match_dish_emoji(name)
        return f"{head}{no}. {emo}**{name}**{rest}"

    part_rec = re.sub(
        r"(^|\n)(\d+)\.\s*([\U0001F300-\U0001FAFF\u2600-\u27BF\U0001F000-\U0001F02F]?\s*)\*\*([^*\n\r]+?)\*\*(\s*`[^`\n\r]*营养[^`\n\r]*难度[^`\n\r]*`.*)?",
        _inject_emoji_only,
        part_rec,
        flags=re.MULTILINE,
    )
    result = part_head + part_cat + part_rec

    # ========== 终局 Post-pass C：清理多余空行 + 规范 Markdown 间距 ==========
    # 1. 连续 3+ 空行 → 2 空行
    result = re.sub(r"\n{3,}", "\n\n", result)
    # 2. ##标题后无空格补空格：##一、 → ## 一、
    result = re.sub(r"##([^\s#])", r"## \1", result)
    # 3. 有序列表编号修复: 1.** → 1. ** (确保句号和空格正确)
    result = re.sub(r"(\d+)\.(?!\s)(\*\*)", r"\1. \2", result)
    # 4. 列表项 - 后无空格补空格（仅在行首）
    result = re.sub(r"^(\s*)-([^\s])", r"\1- \2", result, flags=re.MULTILINE)
    # 5. 胶囊评分格式统一
    result = re.sub(r"`营养:\s*([\d.]+)/10[·•]\s*难度:\s*([\d.]+)/10`", r"`营养: \1/10 · 难度: \2/10`", result)
    # 6. 确保每个分区标题前有空行（## 出现在文本中间时）
    result = re.sub(r"([^\n\s])\s+(## )", r"\1\n\n\2", result)
    # 7. 去掉开头结尾的空白
    result = result.strip()

    return result


# SSE 格式辅助函数：把内容包装成标准 SSE 消息
def _sse_send(content: str) -> str:
    """把内容包装成 SSE 标准格式：data: <content>\n\n
       每个字符/小段独立发送，确保真正的流式效果。
       
    重要：必须先转义换行符（\\n → \\\\n, \\r → \\\\r），否则内容中的 \\n\\n 
    会与 SSE 消息分隔符（\\n\\n）冲突，导致换行丢失——这正是菜品名称不换行的根因。
    前端在收到 SSE data 后会做反向还原（\\\\n → \\n）。
    """
    # 转义换行符，防止与 SSE 分隔符 \n\n 冲突
    content = content.replace("\n", "\\n").replace("\r", "\\r")
    return f"data: {content}\n\n"


# 流式对话
async def search_recipes(prompt: str, image: str, thread_id: str):
    """调用 agent 搜索食谱 → 真实流式（立刻逐 chunk yield）→ 后台矫正格式 + 写回 history
       若有矫正：额外发一条 "__REPLACE_FULL__:<fixed_answer>" SSE 指令，前端整体替换为正确卡片格式。
       SSE 格式：每条消息以 "data: " 开头，以 "\n\n" 结尾。
       
       根据是否有图片自动选择模型：
       - 无图片 → DeepSeek Chat（免费额度更多）
       - 有图片 → DashScope qwen-vl-plus（支持多模态）"""
    logger.info(f"[用户]: {prompt}, image: {bool(image)}, thread_id: {thread_id}")
    
    # 根据是否有图片选择对应的 agent
    use_vl = bool(image and image.strip())
    current_agent = agent_vl if use_vl else agent
    logger.info(f"[模型选择] 使用 {'多模态模型(vl-plus)' if use_vl else '文本模型(deepseek-chat)'}")
    
    try:
        # 判断是否有图片，封装不同格式的消息
        if not image or image.strip() == "":
            message = HumanMessage(content=prompt)
        else:
            # 关键修复：DashScope 兼容模式对外部 URL 拉图非常苛刻，
            # 因此先在后端下载图片并转 base64 data URI，让模型直接读像素。
            try:
                data_uri = _image_url_to_data_uri(image)
            except Exception as img_err:
                logger.warning(f"图片下载/编码失败：{img_err}")
                yield _sse_send(f"图片读取失败：{img_err}\n\n你可以尝试重新上传一张更小的图片，或者直接用文字描述可用食材，我照样能帮你推荐食谱。")
                return
            logger.info(f"图片编码完成，data URI 长度: {len(data_uri)}")
            message = HumanMessage(content=[
                {"type": "image_url", "image_url": {"url": data_uri}},
                {"type": "text", "text": prompt if prompt else "请帮我识别这张图里的食材并推荐食谱。"}
            ])

        # 0) 立刻 yield SSE 格式的占位消息（让前端立刻收到首字节，解除"思考中"状态）
        yield _sse_send("\u200b")

        # ① 真实流式：AIMessageChunk 一到立刻 SSE yield
        answer_buf: list[str] = []
        chunk_count = 0
        for chunk, metadata in current_agent.stream(
            {"messages": [message]},
            {"configurable": {"thread_id": thread_id}},
            stream_mode="messages"
        ):
            if isinstance(chunk, AIMessageChunk) and chunk.content:
                text = chunk.content
                answer_buf.append(text)
                chunk_count += 1
                # 用 SSE 格式 yield 每个 chunk
                yield _sse_send(text)
        
        logger.info(f"[流式完成] thread={thread_id} 共收到 {chunk_count} 个 chunk，总长度 {len(''.join(answer_buf))}")
        raw_answer = "".join(answer_buf)

        # ② 强制格式矫正
        fixed_answer = _format_chef_output(raw_answer)
        need_replace = False
        if fixed_answer.strip() != raw_answer.strip():
            diff_ratio = 0.0
            if len(raw_answer) > 0:
                diff_ratio = sum(1 for a, b in zip(raw_answer, fixed_answer) if a != b) / max(len(raw_answer), 1)
            if diff_ratio > 0.04 or len(fixed_answer) != len(raw_answer):
                need_replace = True
            logger.info(
                f"[格式矫正] thread={thread_id} 长度 {len(raw_answer)}→{len(fixed_answer)}，"
                f"diff_ratio={diff_ratio:.2f}，需要前端替换: {need_replace}"
            )

        # ③ 写回 history
        try:
            _patch_last_assistant_message(thread_id, fixed_answer)
        except Exception as patch_err:
            logger.warning(f"写回 history 失败: {patch_err}")

        # ④ 若需要矫正 → 发 "__REPLACE_FULL__" SSE 指令
        if need_replace and fixed_answer.strip():
            safe = (
                fixed_answer
                .replace("\\", "\\\\")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace('"', '\\"')
            )
            yield _sse_send(f"__REPLACE_FULL__:{safe}")

    except Exception as e:
        logger.error(f"\n[错误]: {type(e).__name__}: {str(e)}")
        err_body = str(e)[:500]
        if "InvalidParameter" in err_body or "image format is illegal" in err_body:
            yield _sse_send(f"图片分析失败（错误信息：{err_body[:200]}）。请重新上传图片，若问题持续可直接用文字描述食材。")
        else:
            yield _sse_send(f"处理失败：{err_body}。可以尝试刷新页面或直接输入文字食材清单继续。")


def _patch_last_assistant_message(thread_id: str, new_content: str) -> None:
    """把 checkpointer 中当前 thread 最后一条 AIMessage.content 替换为矫正后的新内容。
       目的：让下一轮对话的 history 参考新格式报告，模型被 new-format few-shot 带动，正向循环。"""
    try:
        cfg = {"configurable": {"thread_id": thread_id}}
        cp = checkpointer.get(cfg)
        if not cp:
            return
        msgs = cp.get("channel_values", {}).get("messages") or []
        # 倒序找最后一条 AIMessage
        for idx in range(len(msgs) - 1, -1, -1):
            if isinstance(msgs[idx], AIMessage):
                old_content = getattr(msgs[idx], "content", "")
                if old_content and old_content != new_content:
                    # 直接 mutate 对象（langchain message.content 允许直接赋值）
                    msgs[idx].content = new_content
                    # 把修正后的 channel_values 写回 checkpointer
                    channel_values = dict(cp.get("channel_values") or {})
                    channel_values["messages"] = msgs
                    checkpointer.put(
                        cfg,
                        {
                            "v": cp.get("v", 1),
                            "ts": cp.get("ts"),
                            "id": cp.get("id"),
                            "channel_values": channel_values,
                            "versions": cp.get("versions", {}),
                        },
                    )
                break
    except Exception as e:
        logger.warning(f"_patch_last_assistant_message skip: {e}")

# 清空会话
def clear_messages(thread_id: str):
    """清空会话"""
    logger.info(f"清空历史消息，thread_id: {thread_id}")
    checkpointer.delete_thread(thread_id)

# 查询会话历史
def get_messages(thread_id: str) -> list[dict[str, str]]:
    """获取会话历史"""
    logger.info(f"获取历史消息，thread_id: {thread_id}")

    # 根据 thread_id 查询 checkpoint
    checkpoint = checkpointer.get({"configurable": {"thread_id": thread_id}})

    # 如果不存在，返回空列表
    if not checkpoint:
        return []

    # 安全获取 messages
    channel_values = checkpoint.get("channel_values")
    if not channel_values:
        return []

    messages = channel_values.get("messages", [])
    if not messages:
        return []

    # 转换消息格式
    result = []
    for msg in messages:
        if not msg.content:
            continue

        if isinstance(msg, HumanMessage):
            result.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            result.append({"role": "assistant", "content": msg.content})

    return result