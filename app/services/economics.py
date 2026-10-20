"""使用 Decimal 计算单件贡献利润；保留缺失项、公式及输入来源。"""

from decimal import ROUND_HALF_UP, Decimal

from app.analysis_contracts import CostInput

COMPONENTS = (
    "procurement", "shipping", "packaging", "platform_rate", "commission_rate",
    "advertising", "return_loss", "other",
)


def calculate_economics(costs: CostInput | None) -> dict:
    """只有成本项全部显式填写后才计算利润；0 表示用户确认无此成本。"""
    if costs is None:
        return {"status": "missing_data", "missing": ["costs"], "scenarios": []}
    missing = [key for key in COMPONENTS if getattr(costs, key) is None]
    base = {
        "formula_version": "unit-contribution-v1",
        "currency": costs.currency,
        "input": costs.model_dump(mode="json"),
        "missing": missing,
        "notes": [
            "平台费和佣金以当前场景售价为基数。",
            "return_loss 是每售出一件分摊的退款退货净损失；不再重复扣减销售收入。",
            "税费或其他成本须包含在 other 中；本结果不等于会计净利润。",
        ],
    }
    if missing:
        return {**base, "status": "missing_data", "scenarios": []}
    fixed = sum(
        getattr(costs, key)
        for key in ("procurement", "shipping", "packaging", "advertising", "return_loss", "other")
    )
    scenarios = []
    # 情景仅改变售价，幅度显式展示；不将这些假设称为销量或市场预测。
    for name, factor in (("conservative", "0.9"), ("base", "1"), ("optimistic", "1.1")):
        price = costs.sale_price * Decimal(factor)
        fees = price * (costs.platform_rate + costs.commission_rate)
        profit = price - fixed - fees
        scenarios.append({
            "name": name, "price_factor": factor,
            "revenue": money(price), "cost": money(fixed + fees),
            "contribution": money(profit),
            "margin": str((profit / price).quantize(Decimal("0.0001"))),
        })
    return {**base, "status": "ok", "scenarios": scenarios}


def money(value: Decimal) -> str:
    """以十进制字符串保存金额，避免 JSON 浮点误差。"""
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
