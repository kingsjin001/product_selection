"""隔离 PG/Milvus 库的第七期验收；--live 才调用真实聊天和向量模型。"""

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402
from pymilvus import MilvusClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.analysis_contracts import AnalysisRequest  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.analysis_models import AnalysisCall  # noqa: E402
from app.db.session import get_engine, get_session_factory  # noqa: E402
from app.ingestion.imports import ImportRequest, import_records  # noqa: E402
from app.mcp.client import research_tools  # noqa: E402
from app.services.analysis_store import AnalysisStore  # noqa: E402
from app.services.indexing import sync_events  # noqa: E402
from app.services.reports import ask_report  # noqa: E402
from app.services.reviews import decide_review, get_review  # noqa: E402
from app.services.tasks import TaskService  # noqa: E402
from app.workers.runner import run_task  # noqa: E402


def worker_process(identity, timeout=360):
    """每次执行启动全新进程，验证检查点与决定不依赖进程内存。"""
    result = subprocess.run(
        [sys.executable, __file__, "--child-run", identity],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )
    Path(f"artifacts/{identity}-worker.log").write_text(result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError("验收 Worker 失败：" + result.stderr[-1500:])
    return json.loads(result.stdout.strip().splitlines()[-1])


def acceptance(live, output):
    """验收只删除本函数创建的精确隔离库；现有用户库不写入。"""
    original = get_settings()
    original_url = make_url(original.database_url)
    name = "selection_v7_" + uuid4().hex[:12]
    assert re.fullmatch(r"selection_v7_[0-9a-f]{12}", name)
    admin = original_url.set(drivername="postgresql").render_as_string(hide_password=False)
    report = {"live": live, "cases": [], "isolated_database": name}
    server = None
    vector_admin = MilvusClient(uri=original.milvus_uri, timeout=15)
    pg_created = milvus_created = False
    log_path = Path("artifacts") / f"{name}-mcp.log"
    log_path.parent.mkdir(exist_ok=True)
    with (
        psycopg.connect(admin, autocommit=True) as connection,
        log_path.open("w", encoding="utf-8") as log,
    ):
        try:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            pg_created = True
            vector_admin.create_database(name)
            milvus_created = True
            os.environ.update(
                {
                    "DATABASE_URL": original_url.set(database=name).render_as_string(
                        hide_password=False
                    ),
                    "MILVUS_DATABASE": name,
                    "MCP_SHARED_SECRET": uuid4().hex * 2,
                    "EVIDENCE_TRANSPORT": "mcp",
                    "PYTHONIOENCODING": "utf-8",
                }
            )
            if not live:
                os.environ.update(
                    {
                        "EMBEDDING_PROVIDER": "mock",
                        "EMBEDDING_MODEL": "v7-mock",
                        "EMBEDDING_DIM": "16",
                    }
                )
            with socket.socket() as port:
                port.bind(("127.0.0.1", 0))
                number = port.getsockname()[1]
            os.environ["MCP_PORT"] = str(number)
            os.environ["MCP_URL"] = f"http://127.0.0.1:{number}/mcp"
            get_settings.cache_clear()
            settings = get_settings()
            migrated = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
            )
            if migrated.returncode:
                raise RuntimeError("隔离库迁移失败：" + migrated.stderr[-1500:])
            factory = get_session_factory()
            imported = ImportRequest.model_validate_json(
                Path("data/workbench/import.json").read_text(encoding="utf-8")
            )
            import_records(factory, imported)
            indexed = sync_events(factory, settings)
            assert indexed["failed"] == 0, indexed
            report["index"] = indexed
            server = subprocess.Popen(
                [sys.executable, "-m", "app.mcp.server"],
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                with socket.socket() as probe:
                    if probe.connect_ex(("127.0.0.1", number)) == 0:
                        break
                if server.poll() is not None:
                    raise RuntimeError(f"MCP 服务启动失败，日志 {log_path}")
                time.sleep(0.1)
            tasks, store = TaskService(factory, settings), AnalysisStore(factory, settings)
            query_id = tasks.create(
                AnalysisRequest(product_id="demo-v5-conflict", mode="agent"), str(uuid4())
            )
            epoch = tasks.claim(query_id)
            store.guard = lambda session: tasks.guard(session, query_id, epoch)
            store.status(query_id, "running")
            with research_tools(store, query_id) as tools:
                by_name = {tool.name: tool for tool in tools}
                for tool_name, args in {
                    "get_product_snapshot": {},
                    "query_reviews": {},
                    "summarize_review_counts": {},
                    "search_reviews": {"query": "漏水"},
                    "search_rules": {"query": "密封条件"},
                    "get_evidence": {"evidence_ids": ["ev-review-demo-v5-c1"]},
                }.items():
                    result = by_name[tool_name].invoke(args)
                    assert result and result.get("status", "ok") == "ok", (tool_name, result)
                tasks.cancel(query_id)
                try:
                    by_name["query_reviews"].invoke({})
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("取消后 MCP 查询未拒绝")
            tasks.fail(query_id, epoch, RuntimeError("验收查询结束"))
            store.guard = None
            report["cases"].append(
                {"name": "MCP 六工具真实 HTTP/PG/Milvus 与取消拒绝", "passed": True}
            )
            print("MCP HTTP cases passed", flush=True)

            for action in ("approve", "reject", "cancel", "request_changes"):
                identity = tasks.create(
                    AnalysisRequest(
                        product_id="demo-v5-conflict", mode="fixed", review_policy="always"
                    ),
                    str(uuid4()),
                )
                assert worker_process(identity)["status"] == "waiting_for_review"
                assert tasks.recover() == 0
                review = get_review(factory, identity)
                if action == "cancel":
                    tasks.cancel(identity)
                    assert worker_process(identity)["status"] == "duplicate_or_terminal"
                else:
                    decision = decide_review(
                        factory,
                        settings,
                        identity,
                        review["draft_hash"],
                        action,
                        "明确列出样本局限" if action == "request_changes" else "",
                    )
                    if action == "approve":
                        assert worker_process(identity)["status"] == "completed"
                        assert store.report(identity)
                    elif action == "request_changes":
                        child = decision["revision_task_id"]
                        assert worker_process(child)["status"] == "waiting_for_review"
                        tasks.cancel(child)
                report["cases"].append({"name": f"PG 跨进程复核 {action}", "passed": True})
            print("PostgreSQL checkpoint review cases passed", flush=True)
            if live:
                identity = tasks.create(
                    AnalysisRequest(
                        product_id="demo-v5-conflict",
                        mode="multi",
                        review_policy="always",
                        question="先读取适用技能，再各委派一次 reviews 和 rules。"
                        "专项读取自己的技能，分别用 query_reviews 和 search_rules 核验密封表现。"
                        "汇总最多3条声明，说明合成样例和使用条件差异。",
                    ),
                    str(uuid4()),
                )
                print(f"live multi run={identity}", flush=True)
                result = worker_process(identity)
                assert result["status"] == "waiting_for_review", result
                review = get_review(factory, identity)
                decide_review(factory, settings, identity, review["draft_hash"], "approve")
                assert worker_process(identity)["status"] == "completed"
                with factory() as session:
                    calls = session.scalars(
                        select(AnalysisCall).where(AnalysisCall.run_id == identity)
                    ).all()
                    names = [row.name for row in calls]
                assert "read_file" in names and "task" in names and "search_rules" in names, names
                first = ask_report(
                    factory, settings, identity, "解释500ml与1L的测试条件差异", "model"
                )
                second = ask_report(
                    factory,
                    settings,
                    identity,
                    "这些差异能证明规格导致漏水吗？",
                    "model",
                    first["conversation_id"],
                    "live-second",
                )
                report["live_sample"] = {
                    "run_id": identity,
                    "model": settings.chat_model,
                    "embedding": settings.embedding_model,
                    "skills_hash": store.get(identity)["versions"]["skills"]["hash"],
                    "usage": store.get(identity)["usage"],
                    "tool_names": names,
                    "first_answer": first["answer"],
                    "followup_answer": second["answer"],
                }
                report["cases"].append(
                    {"name": "真实 multi 模型/MCP/Skills/复核/连续追问", "passed": True}
                )
            report["passed"] = True
        finally:
            if server:
                server.terminate()
                server.wait(timeout=15)
            if get_engine.cache_info().currsize:
                get_engine().dispose()
            if milvus_created:
                owned = MilvusClient(uri=original.milvus_uri, db_name=name, timeout=15)
                for collection in owned.list_collections():
                    owned.drop_collection(collection)
                owned.close()
                vector_admin.drop_database(name)
            vector_admin.close()
            if pg_created:
                connection.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
                )
            report["temporary_databases_removed"] = True
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    print(
        json.dumps(
            {
                "passed": report.get("passed", False),
                "cases": len(report["cases"]),
                "output": output,
            },
            ensure_ascii=False,
        )
    )


def main():
    """默认使用 mock 向量但保留真实服务；真实模型必须显式 --live。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--child-run")
    parser.add_argument("--output", default="docs/acceptance/phase-7-integration.json")
    args = parser.parse_args()
    if args.child_run:
        # 只在验收子进程记录脱敏堆栈，正式接口仍仅返回异常类别。
        import traceback

        original_fail = TaskService.fail

        def diagnostic_fail(self, task_id, epoch, error):
            """为协议/多 Agent 嵌套异常提供定位信息，删除所有已配置密钥。"""
            detail = "".join(traceback.format_exception(error))
            for value in (self.settings.model_api_key, self.settings.mcp_shared_secret):
                if value and value.get_secret_value():
                    detail = detail.replace(value.get_secret_value(), "[REDACTED]")
            print(detail, file=sys.stderr)
            return original_fail(self, task_id, epoch, error)

        TaskService.fail = diagnostic_fail
        print(json.dumps(run_task(args.child_run)))
    else:
        acceptance(args.live, args.output)


if __name__ == "__main__":
    main()
