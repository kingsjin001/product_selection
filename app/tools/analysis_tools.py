"""只读取冻结快照的分析工具；产品、市场约束由应用绑定，不由模型选择。"""

from collections import Counter

from langchain_core.tools import tool


def review_counts(snapshot: dict) -> dict:
    """按实际评论计数并返回分母，不推断总体好评率或市场销量。"""
    rows = [item for item in snapshot["evidence"] if item["kind"] == "review"]
    return {
        "total": len(rows),
        "ratings": dict(Counter(str(row["payload"]["rating"]) for row in rows)),
        "variants": dict(Counter(row["payload"]["variant"] for row in rows)),
        "evidence_ids": [row["id"] for row in rows],
        "limitation": "统计只覆盖当前快照评论，不能代表全市场。",
    }


def build_tools(snapshot: dict, rule_search, review_search=None):
    """创建绑定一个商品快照的工具闭包；不接受任意 SQL、文件或其他商品 ID。"""
    @tool
    def get_product_snapshot() -> dict:
        """获取当前商品的冻结规格和来源。"""
        return {"status": "ok", "data": snapshot["product"], "snapshot_hash": snapshot["hash"]}

    @tool
    def query_reviews(variant: str = "", max_rating: int = 5, limit: int = 10) -> dict:
        """按规格和最高评分筛选当前商品评论，返回总量和原文证据。"""
        if not 1 <= limit <= 20 or not 1 <= max_rating <= 5:
            raise ValueError("limit 必须为 1～20，max_rating 必须为 1～5")
        rows = [
            row for row in snapshot["evidence"]
            if row["kind"] == "review"
            and (not variant or row["payload"]["variant"] == variant)
            and row["payload"]["rating"] <= max_rating
        ]
        return {"status": "ok" if rows else "no_results", "total": len(rows), "data": rows[:limit]}

    @tool
    def summarize_review_counts() -> dict:
        """以代码计算当前商品评论的评分和规格分布，包含分母与证据 ID。"""
        return review_counts(snapshot)

    @tool
    def search_rules(query: str, top_k: int = 3) -> dict:
        """在当前商品市场检索规则，并限制在本次冻结证据范围内。"""
        if not query.strip() or not 1 <= top_k <= 10:
            raise ValueError("查询不能为空，top_k 必须为 1～10")
        hits = rule_search(query, top_k)
        return {"status": "ok" if hits else "no_results", "data": hits}

    @tool
    def get_evidence(evidence_ids: list[str]) -> dict:
        """读取本次快照中指定证据的全文和来源。"""
        if len(evidence_ids) > 20:
            raise ValueError("一次最多读取 20 条证据")
        rows = [row for row in snapshot["evidence"] if row["id"] in evidence_ids]
        return {"status": "ok" if rows else "no_results", "data": rows}

    result = [
        get_product_snapshot, query_reviews, summarize_review_counts, search_rules, get_evidence,
    ]
    if review_search:
        @tool
        def search_reviews(query: str, top_k: int = 5) -> dict:
            """按语义及关键词检索当前商品评论，返回有效版本的快照证据。"""
            hits = review_search(query, top_k)
            return {"status": "ok" if hits else "no_results", "data": hits}
        result.append(search_reviews)
    return result
