"""任务 API 与持久 SSE，HTTP 连接关闭不会取消后台研究。"""

import json
import time
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from app.analysis_contracts import AnalysisRequest
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.services.tasks import TERMINAL, TaskConflict, TaskService

router = APIRouter(prefix="/api/tasks", tags=["后台任务"])


def service():
    """依赖可在接口测试中替换为隔离数据库。"""
    return TaskService(get_session_factory(), get_settings())


@router.post("", status_code=202)
def create(request: AnalysisRequest, idempotency_key: str | None = Header(default=None)):
    """建议客户端为一次用户提交生成稳定幂等键。"""
    key = idempotency_key or str(uuid4())
    if not 1 <= len(key) <= 120:
        raise HTTPException(422, "幂等键长度必须为 1～120")
    tasks = service()
    try:
        return tasks.get(tasks.create(request, key))
    except TaskConflict as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get("/{task_id}")
def detail(task_id: str):
    """刷新页面可以恢复当前状态。"""
    try:
        return service().get(task_id)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error


@router.post("/{task_id}/cancel")
def cancel(task_id: str):
    """协作取消，在途供应商请求仍可能计费。"""
    detail(task_id)
    service().cancel(task_id)
    return detail(task_id)


@router.post("/{task_id}/resume")
def resume(task_id: str):
    """同一运行恢复不修改输入或重置预算。"""
    detail(task_id)
    try:
        service().resume(task_id)
    except TaskConflict as error:
        raise HTTPException(409, str(error)) from error
    return detail(task_id)


def event_stream(tasks, task_id, after):
    """每批先读取持久事件；序号是 SSE id，重连可以补发。"""
    while True:
        rows = tasks.events(task_id, after)
        for row in rows:
            after = row["event_seq"]
            yield f"id: {after}\ndata: {json.dumps(row, ensure_ascii=False)}\n\n"
        current = tasks.get(task_id)
        if current["status"] in TERMINAL and after >= current["event_seq"]:
            return
        yield ": heartbeat\n\n"
        time.sleep(1)


@router.get("/{task_id}/events")
def events(task_id: str, after: int = 0, last_event_id: str | None = Header(default=None)):
    """支持 EventSource 自动 Last-Event-ID 和刷新后的 after 查询参数。"""
    detail(task_id)
    try:
        cursor = int(last_event_id) if last_event_id is not None else after
        if cursor < 0:
            raise ValueError
    except ValueError as error:
        raise HTTPException(422, "事件序号必须为非负整数") from error
    return StreamingResponse(event_stream(service(), task_id, cursor),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
