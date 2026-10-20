"""独立 localhost Streamable HTTP 服务：python -m app.mcp.server。"""

import logging

from mcp.server.fastmcp import Context, FastMCP

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_session_factory
from app.mcp.context import scoped_snapshot, secret, verify_context
from app.services.evidence_tools import evidence_tools

logger = logging.getLogger(__name__)


def create_server(settings=None, factory=None):
    """依赖可注入；只监听回环地址，SDK 同时启用 DNS rebinding 防护。"""
    settings, factory = settings or get_settings(), factory or get_session_factory()
    secret(settings)
    server = FastMCP("selection-evidence-v1", host="127.0.0.1", port=settings.mcp_port,
                     stateless_http=True, json_response=True, log_level=settings.log_level)

    def invoke(name, arguments, ctx):
        """统一检查上下文，不把服务错误伪装成 no_results。"""
        request = ctx.request_context.request
        token = request.headers.get("x-research-context", "") if request else ""
        scope = verify_context(settings, token)
        snapshot = scoped_snapshot(factory, scope, settings)
        tools = {item.name: item for item in evidence_tools(factory, settings, snapshot)}
        result = tools[name].invoke(arguments)
        scoped_snapshot(factory, scope, settings)
        logger.info("MCP 查询完成 | run=%s tool=%s", scope["run_id"], name)
        return result

    @server.tool()
    def get_product_snapshot(ctx: Context) -> dict:
        """获取当前运行冻结的商品规格与来源。"""
        return invoke("get_product_snapshot", {}, ctx)

    @server.tool()
    def query_reviews(ctx: Context, variant: str = "", max_rating: int = 5,
                      limit: int = 10) -> dict:
        """查询当前商品的评论原文，按规格和最高评分筛选。"""
        return invoke("query_reviews", {"variant": variant, "max_rating": max_rating,
                                        "limit": limit}, ctx)

    @server.tool()
    def summarize_review_counts(ctx: Context) -> dict:
        """返回当前商品评论评分及规格分布和真实样本分母。"""
        return invoke("summarize_review_counts", {}, ctx)

    @server.tool()
    def search_reviews(ctx: Context, query: str, top_k: int = 5) -> dict:
        """在当前快照和商品范围内混合检索评论证据。"""
        return invoke("search_reviews", {"query": query, "top_k": top_k}, ctx)

    @server.tool()
    def search_rules(ctx: Context, query: str, top_k: int = 3) -> dict:
        """在当前市场和冻结证据内混合检索规则。"""
        return invoke("search_rules", {"query": query, "top_k": top_k}, ctx)

    @server.tool()
    def get_evidence(ctx: Context, evidence_ids: list[str]) -> dict:
        """读取当前快照指定证据全文，不接受其他运行证据。"""
        return invoke("get_evidence", {"evidence_ids": evidence_ids}, ctx)

    return server


def main():
    """启动独立进程，不要求 Docker，也不启动业务 API。"""
    configure_logging(get_settings().log_level)
    create_server().run(transport="streamable-http")


if __name__ == "__main__":
    main()
