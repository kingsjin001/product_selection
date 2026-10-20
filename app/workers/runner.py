"""领取租约、维持心跳并执行带检查点的 LangGraph。"""

import logging
from threading import Event, Thread

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.services.analysis_store import AnalysisStore
from app.services.tasks import TaskService
from app.workers.celery_app import celery_app
from app.workflows.analysis import execute_analysis, postgres_checkpointer

logger = logging.getLogger(__name__)


def run_task(task_id, *, factory=None, settings=None, researcher=None, lease_seconds=30):
    """独立函数便于真实服务故障测试；Celery 消息只携带任务 ID。"""
    settings, factory = settings or get_settings(), factory or get_session_factory()
    service = TaskService(factory, settings, lease_seconds)
    epoch = service.claim(task_id)
    if epoch is None:
        return {"status": "duplicate_or_terminal"}
    store = AnalysisStore(factory, settings)
    store.guard = lambda session: service.guard(session, task_id, epoch)
    store.on_complete = lambda session: service.complete(session, task_id, epoch)
    store.on_stage = lambda stage: service.stage(task_id, epoch, stage)
    stopped = Event()

    def heartbeat():
        """在途模型请求也持续续租；失去执行权则停止续租。"""
        while not stopped.wait(min(5, lease_seconds / 3)):
            try:
                service.heartbeat(task_id, epoch)
            except Exception:
                logger.warning("任务心跳停止 | task=%s", task_id)
                return

    thread = Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        with postgres_checkpointer(settings) as saver:
            report = execute_analysis(store, task_id, saver, researcher)
        return {"status": report.get("status", "completed"), "run_id": report["run_id"]}
    except Exception as error:
        service.fail(task_id, epoch, error)
        logger.warning("后台任务停止 | task=%s error=%s", task_id, type(error).__name__)
        return {"status": service.get(task_id)["status"], "error": type(error).__name__}
    finally:
        stopped.set()
        thread.join(timeout=2)


@celery_app.task(name="selection.analyze")
def analyze(task_id):
    """重复投递由任务状态与 PostgreSQL advisory lock 去重。"""
    return run_task(task_id)
