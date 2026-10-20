"""可独立重启的分发器：恢复租约、发送 outbox、同步证据索引。"""

import argparse
import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_session_factory
from app.db.task_models import TaskDispatch
from app.services.indexing import sync_events
from app.services.tasks import TaskService
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def dispatch_once(factory, sender=None, after_send=None, task_id=None):
    """发送成功再标记；发送后崩溃会重投，业务不能假设消息只到达一次。"""
    sender = sender or (
        lambda identity: celery_app.send_task("selection.analyze", args=[identity])
    )
    count = 0
    with factory() as session:
        statement = select(TaskDispatch.id).where(
            TaskDispatch.status == "pending",
            (TaskDispatch.retry_at.is_(None)) | (TaskDispatch.retry_at <= datetime.now(UTC)),
        )
        if task_id:
            statement = statement.where(TaskDispatch.task_id == task_id)
        ids = list(session.scalars(statement.limit(100)))
    for identity in ids:
        try:
            with factory.begin() as session:
                row = session.scalar(select(TaskDispatch).where(
                    TaskDispatch.id == identity,
                ).with_for_update())
                if row.status != "pending":
                    continue
                sender(row.task_id)
                if after_send:
                    after_send()  # 故障注入点：消息已发送、事务尚未提交。
                row.status = "sent"
                count += 1
        except Exception as error:
            with factory.begin() as session:
                row = session.get(TaskDispatch, identity)
                row.attempts += 1
                row.retry_at = datetime.now(UTC) + timedelta(seconds=min(60, 2 ** row.attempts))
            logger.warning("投递失败，稍后重试 | error=%s", type(error).__name__)
    return count


def main():
    """默认每两秒运行一轮；--once 用于验收和手工操作。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--indexes", action="store_true", help="同时消费证据索引事件")
    args = parser.parse_args()
    settings, factory = get_settings(), get_session_factory()
    configure_logging(settings.log_level)
    service = TaskService(factory, settings)
    while True:
        recovered, dispatched = service.recover(), dispatch_once(factory)
        if recovered or dispatched:
            logger.info("调度完成 | recovered=%d dispatched=%d", recovered, dispatched)
        if args.indexes:
            sync_events(factory, settings, limit=10)
        if args.once:
            return
        time.sleep(2)


if __name__ == "__main__":
    main()
