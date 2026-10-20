"""把官方异步 MCP 会话桥接到现有同步 LangGraph，一次研究一个连接生命周期。"""

import json
from contextlib import asynccontextmanager, contextmanager
from functools import partial
from urllib.parse import urlparse

import httpx
from anyio.from_thread import start_blocking_portal
from langchain_core.tools import StructuredTool
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.mcp.context import sign_context
from app.services.evidence_tools import evidence_tools


def schema_contract(value):
    """剔除展示性元数据，保留字段类型、默认值、数组结构等调用约束。"""
    if isinstance(value, dict):
        return {key: schema_contract(item) for key, item in value.items()
                if key not in {"title", "description"}}
    if isinstance(value, list):
        return [schema_contract(item) for item in value]
    return value


@asynccontextmanager
async def connection(url, token):
    """同一异步任务内进入和关闭 transport/session，避免跨循环取消域错误。"""
    async with httpx.AsyncClient(headers={"x-research-context": token},
                                  timeout=httpx.Timeout(30, read=60), trust_env=False) as http:
        async with streamable_http_client(url, http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                yield session


@contextmanager
def research_tools(store, run_id):
    """local/mcp 共用契约；只在工具执行中计费，连接失败直接使研究失败。"""
    run = store.get(run_id)
    local = evidence_tools(store.factory, store.settings, run["snapshot"])
    if run["versions"].get("evidence_transport", "local") == "local":
        yield local
        return
    parsed = urlparse(store.settings.mcp_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("本期 MCP 仅支持 localhost HTTP 服务")
    with store.factory.begin() as session:
        owner = store.check_owner(session)
        epoch = owner.epoch if owner else None
    token = sign_context(store.settings, run, epoch)
    with start_blocking_portal() as portal:
        with portal.wrap_async_context_manager(connection(store.settings.mcp_url, token)) as client:
            remote = portal.call(client.list_tools)
            names = {item.name for item in remote.tools}
            if names != {item.name for item in local}:
                raise ValueError("MCP 工具契约不匹配")
            for item in remote.tools:
                expected = next(tool for tool in local if tool.name == item.name)
                schema = expected.args_schema.model_json_schema()
                # MCP 可以补充 title/description；业务字段和必填约束必须相同。
                if (schema_contract(item.inputSchema.get("properties", {})) !=
                        schema_contract(schema["properties"])
                        or set(item.inputSchema.get("required", [])) !=
                        set(schema.get("required", []))):
                    raise ValueError("MCP 工具参数契约不匹配")

            def invoke(name, **arguments):
                """远端错误显式抛出；调用中间件记录失败与预算，不静默降级。"""
                result = portal.call(partial(client.call_tool, name, arguments))
                if result.isError:
                    raise RuntimeError("MCP 证据查询失败，请查看服务端日志")
                if result.structuredContent is not None:
                    return result.structuredContent
                return json.loads("".join(item.text for item in result.content
                                          if item.type == "text"))

            def bind_tool(item):
                """使用普通函数让 LangGraph 能读取类型注解；partial 不支持 get_type_hints。"""
                def call(**arguments):
                    """绑定固定工具名称，模型只能提供契约参数。"""
                    return invoke(item.name, **arguments)
                return StructuredTool(name=item.name, description=item.description,
                                      args_schema=item.args_schema, func=call)

            yield [bind_tool(item) for item in local]
