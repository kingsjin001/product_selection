"""提供给 Deep Agent 的最小只读工具集。"""

import logging

from langchain_core.tools import tool

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.services.rules import search_rules

logger = logging.getLogger(__name__)


@tool
def search_rules_tool(query: str, market: str = "US", top_k: int = 3) -> dict:
    """检索已索引的规则证据，返回可引用证据而非法律结论。"""
    logger.info("Deep Agent 调用检索工具 | market=%s top_k=%d", market, top_k)
    session_factory = get_session_factory()
    with session_factory() as session:
        return search_rules(session, get_settings(), query=query, market=market, top_k=top_k)
