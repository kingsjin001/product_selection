"""FastAPI 应用入口：暴露导入、索引、检索和 Deep Agent 演示接口。"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.agents.rule_researcher import run_rule_research
from app.api.analysis import router as analysis_router
from app.api.evidence import router as evidence_router
from app.api.imports import router as imports_router
from app.api.reports import router as reports_router
from app.api.tasks import router as tasks_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_engine, get_session_factory
from app.ingestion.sample_importer import import_sample_data
from app.schemas import AgentDemoRequest, RuleSearchRequest
from app.services.rules import index_rule_evidence, search_rules

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """初始化日志并记录服务启停；数据库迁移需由 CLI 或 Alembic 显式执行。"""
    # 配置在应用启动后只读取一次；修改 LOG_LEVEL 后应重启本地服务。
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "应用启动 | env=%s embedding_provider=%s embedding_dim=%d model_credentials=%s",
        settings.app_env,
        settings.embedding_provider,
        settings.embedding_dim,
        settings.has_model_credentials,
    )
    yield
    logger.info("应用停止")


app = FastAPI(title="TikTok Selection Agent", version="0.4.0", lifespan=lifespan)
app.include_router(analysis_router)
app.include_router(evidence_router)
app.include_router(tasks_router)
app.include_router(imports_router)
app.include_router(reports_router)


@app.get("/health")
def health() -> dict:
    """检查 PostgreSQL 连通性，并返回不含密钥的当前模型配置摘要。"""
    # 健康检查刻意只执行轻量 SQL，避免每次探针都触发模型或 Milvus 请求。
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
    settings = get_settings()
    logger.debug("健康检查通过 | embedding_provider=%s", settings.embedding_provider)
    return {
        "status": "ok",
        "embedding_provider": settings.embedding_provider,
        "embedding_dimension": settings.embedding_dim,
        "model_credentials_configured": settings.has_model_credentials,
    }


@app.post("/api/imports/sample")
def import_sample() -> dict:
    """导入项目内置合成样例；重复调用会返回已有批次而不会重复写入。"""
    sample_dir = Path(__file__).resolve().parents[1] / "data" / "sample"
    with get_session_factory()() as session:
        try:
            result = import_sample_data(session, sample_dir)
            logger.info("导入接口完成 | status=%s", result["status"])
            return result
        except Exception:
            # 服务层可能已写入部分 ORM 对象，异常时必须清理当前事务。
            session.rollback()
            logger.exception("导入接口失败")
            raise


@app.post("/api/indexes/rules")
def index_rules() -> dict:
    """读取 PostgreSQL 中的规则证据，生成向量后幂等写入 Milvus。"""
    with get_session_factory()() as session:
        try:
            result = index_rule_evidence(session, get_settings())
            logger.info("索引接口完成 | records=%d", result["records"])
            return result
        except Exception:
            session.rollback()
            logger.exception("索引接口失败")
            raise


@app.post("/api/rules/search")
def rule_search(request: RuleSearchRequest) -> dict:
    """按市场检索规则证据，并从 PostgreSQL 回查可追溯业务字段。"""
    with get_session_factory()() as session:
        result = search_rules(
            session,
            get_settings(),
            query=request.query,
            market=request.market,
            top_k=request.top_k,
        )
        logger.info("检索接口完成 | status=%s results=%d", result["status"], len(result["data"]))
        return result


@app.post("/api/agent-demo")
def agent_demo(request: AgentDemoRequest) -> dict:
    """执行真实 Deep Agent；模型只能通过只读规则检索工具访问项目数据。"""
    if not get_settings().has_model_credentials:
        logger.warning("Deep Agent 调用被拒绝：模型凭据不完整")
        raise HTTPException(
            status_code=400,
            detail="请配置 MODEL_API_KEY 和 CHAT_MODEL 后再运行真实 Deep Agent 演示。",
        )
    try:
        result = run_rule_research(get_settings(), request.question, request.market)
        logger.info("Deep Agent 接口完成 | market=%s", request.market)
        return result
    except RuntimeError as error:
        logger.warning("Deep Agent 接口失败 | reason=%s", error)
        raise HTTPException(status_code=400, detail=str(error)) from error


# 前端构建后可由同一 API 进程提供页面；开发期也可使用 Vite 热更新。
frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="workbench")
