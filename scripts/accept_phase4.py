"""第四期真实 PG/Redis/Celery 与进程退出恢复验收，不调用付费模型。"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.analysis_contracts import AnalysisRequest  # noqa: E402
from app.api.tasks import event_stream  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.analysis_models import AnalysisReport  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.db.task_models import TaskDispatch  # noqa: E402
from app.services.analysis_store import AnalysisStore  # noqa: E402
from app.services.tasks import OwnershipLost, TaskService  # noqa: E402
from app.workers.celery_app import celery_app  # noqa: E402
from app.workers.dispatcher import dispatch_once  # noqa: E402
from app.workers.runner import run_task  # noqa: E402
from app.workflows.analysis import postgres_checkpointer  # noqa: E402


def wait_for(predicate, timeout=45):
    """有限等待真实进程状态；失败保留日志便于排查。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.25)
    raise TimeoutError("验收等待超时")


def main():
    """启动隔离队列 Worker；只操作本脚本创建的任务。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--crash")
    parser.add_argument("--output", default="docs/acceptance/phase-4-results.json")
    args = parser.parse_args()
    settings, factory = get_settings(), get_session_factory()
    tasks = TaskService(factory, settings, lease_seconds=3)
    if args.crash:
        def crash(*args):
            """模拟真实进程消失，来不及写失败状态或释放业务租约。"""
            os._exit(72)
        AnalysisStore.save_report = crash
        run_task(args.crash, lease_seconds=3)
        return
    queue = "acceptance-" + uuid4().hex[:10]
    folder = Path("exports/phase4")
    folder.mkdir(parents=True, exist_ok=True)
    results = []
    request = AnalysisRequest(product_id="prod-cn-001", mode="fixed")
    key = "acceptance-" + uuid4().hex
    identity = tasks.create(request, key)
    assert tasks.create(request, key) == identity
    results.append({"case": "idempotent_submit", "passed": True, "task_id": identity})
    def sender(tid):
        """投递到专用队列，不消费用户已有的默认队列任务。"""
        return celery_app.send_task("selection.analyze", args=[tid], queue=queue)
    with (folder / "worker.log").open("w", encoding="utf-8") as log:
        worker = subprocess.Popen(
            [sys.executable, "-m", "celery", "-A", "app.workers.celery_app:celery_app",
             "worker", "--pool=solo", "--loglevel=INFO", "-Q", queue,
             "--hostname", queue + "@%h", "--without-gossip", "--without-mingle"],
            stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            def fail_after_send():
                raise RuntimeError("injected send/commit gap")
            dispatch_once(factory, sender=sender, after_send=fail_after_send, task_id=identity)
            with factory.begin() as session:
                for row in session.scalars(select(TaskDispatch).where(
                    TaskDispatch.task_id == identity,
                )):
                    row.retry_at = None
            dispatch_once(factory, sender=sender, task_id=identity)
            wait_for(lambda: tasks.get(identity)["status"] == "completed")
            with factory() as session:
                assert len(session.scalars(select(AnalysisReport).where(
                    AnalysisReport.run_id == identity,
                )).all()) == 1
            assert sum(e["type"] == "completed" for e in tasks.events(identity)) == 1
            results.append({"case": "redis_celery_duplicate_after_dispatch_gap", "passed": True})

            crash_id = tasks.create(request, "acceptance-" + uuid4().hex)
            crashed = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--crash", crash_id],
                timeout=45, stdout=log, stderr=log,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            assert crashed.returncode == 72
            old_epoch = tasks.get(crash_id)["epoch"]
            # 外层 validate 已完成，重启只需执行 persist。
            with postgres_checkpointer(settings) as saver:
                checkpoint = saver.get_tuple({"configurable": {"thread_id": crash_id}})
                assert checkpoint is not None
                assert checkpoint.checkpoint["channel_values"].get("report")
            wait_for(lambda: tasks.recover() > 0, timeout=10)
            dispatch_once(factory, sender=sender, task_id=crash_id)
            wait_for(lambda: tasks.get(crash_id)["status"] == "completed")
            with factory.begin() as session:
                try:
                    tasks.guard(session, crash_id, old_epoch)
                    raise AssertionError("旧 Worker 仍可写入")
                except OwnershipLost:
                    pass
            results.append({"case": "process_exit_checkpoint_recovery_fencing",
                            "passed": True, "task_id": crash_id,
                            "attempts": tasks.get(crash_id)["attempts"]})

            cancel_id = tasks.create(request, "acceptance-" + uuid4().hex)
            epoch = tasks.claim(cancel_id)
            tasks.cancel(cancel_id)
            store = AnalysisStore(factory, settings)
            store.guard = lambda session: tasks.guard(session, cancel_id, epoch)
            try:
                store.save_report(cancel_id, {"evidence": [], "research": {"claims": []}}, "late")
                raise AssertionError("取消后发布了报告")
            except OwnershipLost:
                pass
            tasks.fail(cancel_id, epoch, OwnershipLost())
            assert tasks.get(cancel_id)["status"] == "cancelled" and not store.report(cancel_id)
            results.append({"case": "cancel_late_result", "passed": True, "task_id": cancel_id})
            all_events = tasks.events(identity)
            replay = list(event_stream(tasks, identity, 2))
            assert len(replay) == len([e for e in all_events if e["event_seq"] > 2])
            results.append({"case": "sse_durable_replay", "passed": True,
                            "replayed": len(replay)})
        finally:
            worker.terminate()
            worker.wait(timeout=10)
    output = Path(args.output)
    output.write_text(json.dumps({"cases": results, "real_services": ["PostgreSQL", "Redis",
                       "Celery"], "paid_model_calls": 0}, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(json.dumps({"passed": len(results), "output": str(output)}))


if __name__ == "__main__":
    main()
