from deepagents import create_deep_agent
from langchain_openai import ChatOpenAI

from app.core.config import Settings
from app.tools.rule_search import search_rules_tool

# 该提示词约束模型先检索证据，防止把泛化知识伪装成项目内事实。
SYSTEM_PROMPT = """You are a product-rule research assistant.
Use search_rules_tool before making factual statements about the supplied market.
Return the evidence IDs and any uncertainty. Do not give legal advice. If evidence is missing,
say that verification is still required. Do not execute code or write files."""


def create_rule_research_agent(settings: Settings):
    """创建连接至 OpenAI 兼容服务的 Deep Agent，供真实工具调用验收使用。"""
    if not settings.has_model_credentials:
        raise RuntimeError(
            "MODEL_API_KEY and CHAT_MODEL are required for the real Deep Agent demo."
        )
    client_options = {
        "model": settings.chat_model,
        "api_key": settings.model_api_key.get_secret_value(),
        "temperature": 0,
        "max_retries": 1,
    }
    if settings.model_base_url:
        client_options["base_url"] = settings.model_base_url
    model = ChatOpenAI(**client_options)
    return create_deep_agent(
        model=model,
        tools=[search_rules_tool],
        system_prompt=SYSTEM_PROMPT,
    )


def run_rule_research(settings: Settings, question: str, market: str = "US") -> dict:
    """运行一次规则研究，并将市场约束放进用户输入以便模型调用受限工具。"""
    agent = create_rule_research_agent(settings)
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
    return {"status": "ok", "result": result}
