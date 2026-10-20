import logging

from deepagents import create_deep_agent
from langchain_openai import ChatOpenAI

from app.core.config import Settings
from app.tools.rule_search import search_rules_tool

logger = logging.getLogger(__name__)

# 该提示词约束模型先检索证据，防止把泛化知识伪装成项目内事实。
SYSTEM_PROMPT = """You are a product-rule research assistant.
Use search_rules_tool before making factual statements about the supplied market.
Return the evidence IDs and any uncertainty. Do not give legal advice. If evidence is missing,
say that verification is still required. Do not execute code or write files."""


def create_rule_research_agent(settings: Settings):
    """创建真实 Deep Agent，并仅注册只读的规则检索工具。"""
    if not settings.has_model_credentials:
        raise RuntimeError(
            "MODEL_API_KEY and CHAT_MODEL are required for the real Deep Agent demo."
        )
    # ChatOpenAI 接受任意 OpenAI 兼容端点；具体供应商信息只来自运行配置。
    client_options = {
        "model": settings.chat_model,
        "api_key": settings.model_api_key.get_secret_value(),
        "temperature": 0,
        "max_retries": 1,
    }
    if settings.model_base_url:
        client_options["base_url"] = settings.model_base_url
    model = ChatOpenAI(**client_options)
    # 不暴露 Shell、文件或任意 SQL 工具，模型只能查询项目中的规则证据。
    return create_deep_agent(
        model=model,
        tools=[search_rules_tool],
        system_prompt=SYSTEM_PROMPT,
    )


def run_rule_research(settings: Settings, question: str, market: str = "US") -> dict:
    """运行一次规则研究，并将市场约束传给 Agent 的用户消息。"""
    logger.info("开始运行 Deep Agent | market=%s", market)
    logger.debug("Deep Agent 问题样例 | question=%r", question[:160])
    agent = create_rule_research_agent(settings)
    # 调用上限由模型轮次与工具轮次相加，防止异常循环无限消耗请求额度。
    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": f"Market: {market}. Research question: {question}",
                }
            ]
        },
        config={"recursion_limit": settings.max_tool_calls + settings.max_model_calls},
    )
    logger.info("Deep Agent 运行完成")
    return {"status": "ok", "result": result}
