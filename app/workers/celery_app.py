"""Redis 只承担投递，任务终态与结果以 PostgreSQL 为准。"""

from celery import Celery

from app.core.config import get_settings

celery_app = Celery("selection", broker=get_settings().redis_url,
                    include=["app.workers.runner"])
celery_app.conf.update(
    task_default_queue="selection",
    task_serializer="json", accept_content=["json"],
    task_acks_late=True, task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_transport_options={"visibility_timeout": 3600},
    task_ignore_result=True,
)
