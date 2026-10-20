"""第二期分析输入、成本参数与模型研究结果的严格契约。"""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CostInput(BaseModel):
    """同币种、单件口径的成本假设；缺失项保持空值，不默认为零。"""

    model_config = ConfigDict(extra="forbid")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    source: str = Field(min_length=1, max_length=500)
    observed_on: date
    assumed: bool = True
    sale_price: Decimal = Field(gt=0, le=1000000)
    procurement: Decimal | None = Field(default=None, ge=0, le=1000000)
    shipping: Decimal | None = Field(default=None, ge=0, le=1000000)
    packaging: Decimal | None = Field(default=None, ge=0, le=1000000)
    platform_rate: Decimal | None = Field(default=None, ge=0, le=1)
    commission_rate: Decimal | None = Field(default=None, ge=0, le=1)
    advertising: Decimal | None = Field(default=None, ge=0, le=1000000)
    return_loss: Decimal | None = Field(default=None, ge=0, le=1000000)
    other: Decimal | None = Field(default=None, ge=0, le=1000000)


class AnalysisRequest(BaseModel):
    """一次单品研究的输入；模式明确区分确定性基线与真实模型。"""

    model_config = ConfigDict(extra="forbid")
    product_id: str = Field(min_length=1, max_length=80)
    question: str = Field(default="该商品进入候选清单前需要核验哪些事项？", max_length=1000)
    mode: Literal["fixed", "prompt", "agent"] = "agent"
    costs: CostInput | None = None


class Claim(BaseModel):
    """模型只输出有证据的观察或推断；数值利润由确定性服务负责。"""

    model_config = ConfigDict(extra="forbid")
    statement: str = Field(min_length=1, max_length=1500)
    kind: Literal["observation", "inference"] = "observation"
    evidence_ids: list[str] = Field(min_length=1, max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=10)


class ResearchResult(BaseModel):
    """JSON 研究结果，模型不能直接写入利润或最终任务状态。"""

    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=3000)
    claims: list[Claim] = Field(default_factory=list, max_length=30)
    missing_data: list[str] = Field(default_factory=list, max_length=20)
    next_steps: list[str] = Field(default_factory=list, max_length=20)
