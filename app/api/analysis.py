"""第二期同步分析 API；后台队列将在第四期独立接入。"""

from fastapi import APIRouter, HTTPException

from app.analysis_contracts import AnalysisRequest
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.db.task_models import Task
from app.services.analysis_store import AnalysisStore
from app.workflows.analysis import execute_analysis, postgres_checkpointer

router = APIRouter(prefix="/api/analyses", tags=["单品分析"])


def store() -> AnalysisStore:
    """取得与 CLI 相同的持久化服务。"""
    return AnalysisStore(get_session_factory(), get_settings())


@router.post("")
def analyze(request: AnalysisRequest) -> dict:
    """创建快照并同步执行一次研究，失败返回可恢复运行 ID。"""
    service = store()
    try:
        run_id = service.create(request)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
    return run_existing(service, run_id)


def run_existing(service: AnalysisStore, run_id: str) -> dict:
    """对外只显示异常类别，详细栈由服务端调试日志定位。"""
    try:
        with postgres_checkpointer(service.settings) as saver:
            return execute_analysis(service, run_id, saver)
    except Exception as error:
        raise HTTPException(503, {"run_id": run_id, "error": type(error).__name__}) from error


@router.get("/{run_id}")
def get_analysis(run_id: str) -> dict:
    """获取运行状态、消费额度及已完成报告。"""
    service = store()
    try:
        result = service.get(run_id)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
    return {**result, "report": service.report(run_id)}


@router.post("/{run_id}/resume")
def resume_analysis(run_id: str) -> dict:
    """保持相同输入、证据和预算，从失败后的检查点继续执行。"""
    service = store()
    with service.factory() as session:
        if session.get(Task, run_id):
            raise HTTPException(409, "后台任务请使用 /api/tasks/{id}/resume，不能绕过租约")
    try:
        service.get(run_id)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
    return run_existing(service, run_id)
