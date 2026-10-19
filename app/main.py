"""FastAPI 应用入口：暴露导入、索引、检索和 Deep Agent 演示接口。"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from sqlalchemy import text

from app.agents.rule_researcher import run_rule_research
from app.core.config import get_settings
from app.db.session import get_engine, get_session_factory
from app.ingestion.sample_importer import import_sample_data
from app.schemas import AgentDemoRequest, RuleSearchRequest
from app.services.rules import index_rule_evidence, search_rules


@asynccontextmanager
async def lifespan(_: FastAPI):
    """管理应用生命周期；数据库结构由 Alembic 在启动前创建。"""
    yield


app = FastAPI(title="TikTok Selection Agent — Phase 1", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    """检查数据库连通性，并返回当前模型配置是否完整。"""
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
    settings = get_settings()
    return {
        "status": "ok",
        "embedding_provider": settings.embedding_provider,
        "embedding_dimension": settings.embedding_dim,
        "model_credentials_configured": settings.has_model_credentials,
    }


@app.post("/api/imports/sample")
def import_sample() -> dict:
    """导入项目内置的合成样例，用于重复验证整个数据管线。"""
    sample_dir = Path(__file__).resolve().parents[1] / "data" / "sample"
    with get_session_factory()() as session:
        try:
            return import_sample_data(session, sample_dir)
        except Exception:
            session.rollback()
            raise


@app.post("/api/indexes/rules")
def index_rules() -> dict:
    """将已导入的规则证据嵌入并写入 Milvus。"""
    with get_session_factory()() as session:
        try:
            return index_rule_evidence(session, get_settings())
        except Exception:
            session.rollback()
            raise


@app.post("/api/rules/search")
def rule_search(request: RuleSearchRequest) -> dict:
    """按市场检索规则证据，返回可追溯的证据 ID 和版本。"""
    with get_session_factory()() as session:
        return search_rules(
            session,
            get_settings(),
            query=request.query,
            market=request.market,
            top_k=request.top_k,
        )


@app.post("/api/agent-demo")
def agent_demo(request: AgentDemoRequest) -> dict:
    """执行真实 Deep Agent 演示；未配置模型时明确返回配置错误。"""
    if not get_settings().has_model_credentials:
        raise HTTPException(
            status_code=400,
            detail="请配置 MODEL_API_KEY 和 CHAT_MODEL 后再运行真实 Deep Agent 演示。",
        )
    try:
        return run_rule_research(get_settings(), request.question, request.market)
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
