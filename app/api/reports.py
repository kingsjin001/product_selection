"""报告详情、幂等导出、独立追问与成本修订接口。"""

from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.analysis_contracts import AnalysisRequest, CostInput
from app.core.config import get_settings
from app.db.analysis_models import AnalysisReport, AnalysisRun
from app.db.report_models import ReportExport, ReportQuestion
from app.db.session import get_session_factory
from app.services.reports import ask_report, create_export, load_report
from app.services.tasks import TaskConflict, TaskService

router = APIRouter(prefix="/api", tags=["报告交付"])


class ExportRequest(BaseModel):
    """Word、JSON 与 Markdown 共享同一冻结源。"""

    format: Literal["docx", "json", "md"] = "docx"


class QuestionRequest(BaseModel):
    """引用定位无需模型；model 显式触发一次真实模型追问。"""

    question: str = Field(min_length=1, max_length=2000)
    mode: Literal["extractive", "model"] = "extractive"
    conversation_id: str | None = Field(default=None, max_length=36)
    request_key: str | None = Field(default=None, max_length=120)
    suggest_memory: bool = False


@router.get("/reports")
def list_reports():
    """返回最近 100 份报告用于工作台选择。"""
    with get_session_factory()() as session:
        rows = session.execute(select(AnalysisReport, AnalysisRun.created_at).join(
            AnalysisRun, AnalysisReport.run_id == AnalysisRun.id,
        ).order_by(AnalysisRun.created_at.desc()).limit(100)).all()
        return [{"id": row.run_id, "name": row.content["product"]["name"],
                 "mode": row.content["mode"], "created_at": created.isoformat()}
                for row, created in rows]


@router.get("/reports/{run_id}")
def detail(run_id: str):
    """返回报告及完整性摘要。"""
    try:
        return load_report(get_session_factory(), run_id)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error


@router.post("/reports/{run_id}/exports")
def export(run_id: str, request: ExportRequest):
    """重复请求复用稳定制品 ID，不调用模型。"""
    try:
        identity = create_export(get_session_factory(), run_id, request.format)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
    return {"id": identity, "download_url": f"/api/exports/{identity}"}


@router.get("/exports/{identity}")
def download(identity: str):
    """直接读取数据库保存的制品字节，不允许用户指定磁盘路径。"""
    with get_session_factory()() as session:
        row = session.get(ReportExport, identity)
        if row is None:
            raise HTTPException(404, "导出不存在")
        media = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                 "json": "application/json", "md": "text/markdown"}
        return Response(row.content, media_type=media[row.format], headers={
            "Content-Disposition": f'attachment; filename="report-{row.run_id}.{row.format}"',
            "ETag": f'"{row.file_hash}"',
        })


@router.post("/reports/{run_id}/questions")
def ask(run_id: str, request: QuestionRequest):
    """返回独立回答；失败仅暴露异常类型，供应商原文不进入 HTTP。"""
    detail(run_id)
    try:
        return ask_report(get_session_factory(), get_settings(), run_id,
                          request.question, request.mode, request.conversation_id,
                          request.request_key, request.suggest_memory)
    except TaskConflict as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except Exception as error:
        raise HTTPException(503, f"追问失败：{type(error).__name__}") from error


@router.get("/reports/{run_id}/questions")
def questions(run_id: str):
    """展示追问历史，回答对应的 report_hash 始终明确可见。"""
    detail(run_id)
    with get_session_factory()() as session:
        rows = session.scalars(select(ReportQuestion).where(
            ReportQuestion.run_id == run_id,
        )).all()
        return [{"id": row.id, "request": row.request, "response": row.response,
                 "status": row.status, "report_hash": row.report_hash,
                 "usage": {"input_tokens": row.input_tokens, "output_tokens": row.output_tokens}}
                for row in rows]


@router.post("/reports/{run_id}/revisions", status_code=202)
def revise_costs(run_id: str, costs: CostInput,
                 idempotency_key: str | None = Header(default=None)):
    """沿用报告冻结证据，只替换成本并新建有父版本记录的任务。"""
    detail(run_id)
    key = idempotency_key or str(uuid4())
    if not 1 <= len(key) <= 120:
        raise HTTPException(422, "幂等键长度必须为 1～120")
    factory = get_session_factory()
    with factory() as session:
        parent = session.get(AnalysisRun, run_id)
        request = AnalysisRequest.model_validate({**parent.request, "costs": costs.model_dump(
            mode="json",
        )})
        snapshot = parent.snapshot
    tasks = TaskService(factory, get_settings())
    try:
        return tasks.get(tasks.create(request, key, snapshot_override=snapshot, parent_id=run_id))
    except TaskConflict as error:
        raise HTTPException(409, str(error)) from error
