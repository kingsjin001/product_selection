"""项目命令行入口：用于迁移、导入、索引和人工验证。"""

import argparse
import json
from pathlib import Path

from app.agents.rule_researcher import run_rule_research
from app.core.config import get_settings
from app.db.migrations import upgrade_head
from app.db.session import get_session_factory
from app.ingestion.sample_importer import import_sample_data
from app.services.rules import index_rule_evidence, search_rules


def _sample_dir() -> Path:
    """返回随项目发布的合成样例目录。"""
    return Path(__file__).resolve().parents[1] / "data" / "sample"


def main() -> None:
    """解析子命令并调用对应服务；数据库结构必须先通过 Alembic 创建。"""
    parser = argparse.ArgumentParser(description="Phase 1 verification commands")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db")
    subparsers.add_parser("import-sample")
    subparsers.add_parser("index-rules")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--query", default="food contact material labeling")
    verify.add_argument("--market", default="US")
    agent = subparsers.add_parser("agent-demo")
    agent.add_argument(
        "--question", default="What should I verify before selling a food storage product?"
    )
    agent.add_argument("--market", default="US")
    args = parser.parse_args()

    if args.command == "init-db":
        # 保留旧命令名，实际统一由 Alembic 管理结构版本。
        upgrade_head()
        print(json.dumps({"status": "database_migrated"}, ensure_ascii=False))
        return

    session_factory = get_session_factory()
    with session_factory() as session:
        # 这些命令只读取或写入本地开发数据，不会调用真实聊天模型。
        if args.command == "import-sample":
            print(
                json.dumps(import_sample_data(session, _sample_dir()), ensure_ascii=False, indent=2)
            )
        elif args.command == "index-rules":
            print(
                json.dumps(
                    index_rule_evidence(session, get_settings()), ensure_ascii=False, indent=2
                )
            )
        elif args.command == "verify":
            result = search_rules(session, get_settings(), query=args.query, market=args.market)
            print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.command == "agent-demo":
        print(
            json.dumps(
                run_rule_research(get_settings(), args.question, args.market),
                ensure_ascii=False,
                default=str,
            )
        )


if __name__ == "__main__":
    main()
