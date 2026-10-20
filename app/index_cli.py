"""第三期索引维护入口：登记、同步、重试和状态对账。"""

import argparse
import json

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.index_models import IndexEvent, VectorManifest
from app.db.session import get_session_factory
from app.services.indexing import enqueue_all, sync_events


def main():
    """按命令操作 outbox；rebuild 不删除旧模型的集合。"""
    parser = argparse.ArgumentParser(description="第三期规则/评论索引维护")
    parser.add_argument("command", choices=["enqueue", "sync", "rebuild", "status", "retry"])
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)
    factory = get_session_factory()
    if args.command in ("enqueue", "rebuild"):
        print(json.dumps({"enqueued": enqueue_all(factory)}))
    if args.command in ("sync", "rebuild"):
        print(json.dumps(sync_events(factory, settings)))
    if args.command == "retry":
        with factory.begin() as session:
            rows = session.scalars(select(IndexEvent).where(IndexEvent.status == "failed")).all()
            for row in rows:
                row.status, row.attempts, row.retry_at = "pending", 0, None
            print(json.dumps({"reset_failed": len(rows)}))
    if args.command == "status":
        with factory() as session:
            counts = session.execute(
                select(IndexEvent.status, func.count()).group_by(IndexEvent.status)
            ).all()
            print(json.dumps({
                "events": dict(counts),
                "manifests": session.scalar(select(func.count()).select_from(VectorManifest)),
            }))


if __name__ == "__main__":
    main()
