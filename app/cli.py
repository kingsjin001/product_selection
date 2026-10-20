"""项目命令行入口：用于迁移、导入、索引和人工验证。"""

import argparse
import json
from pathlib import Path

from app.agents.rule_researcher import run_rule_research
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.migrations import upgrade_head
from app.db.session import get_session_factory
from app.ingestion.sample_importer import import_sample_data
from app.services.rules import index_rule_evidence, search_rules


def _sample_dir() -> Path:
    """返回随项目发布的合成样例目录，避免依赖执行命令时的当前路径。"""
    return Path(__file__).resolve().parents[1] / "data" / "sample"


def main() -> None:
    """执行一次性维护命令，并将结果以 JSON 输出到命令行。"""
    # CLI 也使用和 FastAPI 相同的日志配置，便于复现 API 内的运行过程。
    configure_logging(get_settings().log_level)
    parser = argparse.ArgumentParser(
        description="第一期维护与验收命令；不会启动 FastAPI 服务。"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    # 每个子命令复用服务层，避免 CLI 和 API 各自实现一套业务流程。
    subparsers.add_parser("init-db", help="应用 Alembic 数据库迁移")
    subparsers.add_parser("import-sample", help="导入项目内置的合成样例数据")
    subparsers.add_parser("index-rules", help="生成规则向量并写入 Milvus")
    verify = subparsers.add_parser("verify", help="检索已索引的规则证据")
    verify.add_argument("--query", default="food contact material labeling", help="检索文本")
    verify.add_argument("--market", default="US", help="目标市场，例如 US")
    agent = subparsers.add_parser("agent-demo", help="调用真实模型执行 Deep Agent 演示")
    agent.add_argument(
        "--question",
        default="What should I verify before selling a food storage product?",
        help="交给 Deep Agent 的研究问题",
    )
    agent.add_argument("--market", default="US", help="目标市场，例如 US")
    args = parser.parse_args()

    if args.command == "init-db":
        # 保留旧命令名，实际统一由 Alembic 管理结构版本。
        upgrade_head()
        print(json.dumps({"status": "database_migrated"}, ensure_ascii=False))
        return

    if args.command == "agent-demo":
        # 该命令会产生真实模型请求；工具函数会在模型需要检索时自行创建数据库会话。
        print(
            json.dumps(
                run_rule_research(get_settings(), args.question, args.market),
                ensure_ascii=False,
                default=str,
            )
        )
        return

    # 只有导入、索引和检索需要 PostgreSQL 会话。
    session_factory = get_session_factory()
    with session_factory() as session:
        if args.command == "import-sample":
            # 样例导入自身提交事务；重复运行会返回 already_imported。
            print(
                json.dumps(import_sample_data(session, _sample_dir()), ensure_ascii=False, indent=2)
            )
        elif args.command == "index-rules":
            # 索引会读取 PostgreSQL 证据、调用 Embedding，再写入 Milvus。
            print(
                json.dumps(
                    index_rule_evidence(session, get_settings()), ensure_ascii=False, indent=2
                )
            )
        elif args.command == "verify":
            # verify 只检索现有数据，不会请求真实聊天模型。
            result = search_rules(session, get_settings(), query=args.query, market=args.market)
            print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
