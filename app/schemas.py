"""FastAPI 请求体模型：在接口边界校验用户输入。"""

from pydantic import BaseModel, Field


class RuleSearchRequest(BaseModel):
    """规则检索接口的请求参数。"""

    # 查询文本、目标市场及返回数量均在服务层再次校验。
    query: str = Field(min_length=1, max_length=500)
    market: str = Field(default="US", min_length=2, max_length=12)
    top_k: int = Field(default=3, ge=1, le=10)


class AgentDemoRequest(BaseModel):
    """真实 Deep Agent 演示接口的请求参数。"""

    question: str = Field(min_length=1, max_length=1000)
    market: str = Field(default="US", min_length=2, max_length=12)
