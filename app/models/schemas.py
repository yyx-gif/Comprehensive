from typing import Optional, List

from pydantic import BaseModel, Field

# --- 2. 数据模型 ---
class ChatRequest(BaseModel):
    message: str
    # image_url 是主字段；同时兼容旧前端可能使用的 image 别名
    image_url: Optional[str] = Field(default=None, alias="image")
    thread_id: str

    class Config:
        # 允许按字段名（image_url）或别名（image）两种方式传入（Pydantic V1/V2 兼容写法）
        validate_by_name = True
        allow_population_by_field_name = True