"""本地与 MCP 共用的六个只读工具，避免两套检索业务逻辑。"""

from app.services.hybrid_search import search_evidence
from app.tools.analysis_tools import build_tools


def evidence_tools(factory, settings, snapshot):
    """商品、市场、品类及证据范围由应用绑定，不作为模型可选参数。"""
    def retrieve(kind, query, top_k):
        """检索仍执行当前有效版本与冻结快照双重过滤。"""
        if not query.strip() or len(query) > 2000 or not 1 <= top_k <= 10:
            raise ValueError("查询为 1～2000 字，top_k 为 1～10")
        return search_evidence(
            factory, settings, query=query, top_k=top_k, kind=kind,
            market=snapshot["product"]["market"], category=snapshot["product"]["category"],
            product_id=snapshot["product"]["id"] if kind == "review" else "", snapshot=snapshot,
        )
    return build_tools(snapshot, lambda q, k: retrieve("rule", q, k),
                       lambda q, k: retrieve("review", q, k))
