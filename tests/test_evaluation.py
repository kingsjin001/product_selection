"""评测分母与排名指标的独立小规模验算。"""

from scripts.evaluate import score


def test_recall_and_ndcg_do_not_count_duplicates():
    """相关项共两个，只召回其中一个时 Recall 必须为 1/2。"""
    metrics = score(["a", "a", "x"], ["a", "b"])
    assert metrics["recall_at_5"] == .5
    assert 0 < metrics["ndcg_at_5"] < 1


def test_rank_order_affects_ndcg():
    """命中数相同，相关项排第一应高于排第三。"""
    assert score(["a", "x", "y"], ["a"])["ndcg_at_5"] == 1
    assert score(["x", "y", "a"], ["a"])["ndcg_at_5"] == .5
