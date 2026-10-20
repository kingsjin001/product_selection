"""在独立临时 PostgreSQL 数据库复验迁移和后台闭环，不触碰现有业务库。"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.core.config import get_settings  # noqa: E402


def main():
    """需要当前 PostgreSQL 角色有建库权限；只删除本函数创建的精确数据库名。"""
    original = make_url(get_settings().database_url)
    name = "selection_acceptance_" + uuid4().hex[:12]
    assert re.fullmatch(r"selection_acceptance_[0-9a-f]{12}", name)
    connection_url = original.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(connection_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            env = os.environ.copy()
            env["DATABASE_URL"] = original.set(database=name).render_as_string(hide_password=False)
            env["PYTHONIOENCODING"] = "utf-8"
            env["EMBEDDING_PROVIDER"] = "mock"
            env["EMBEDDING_MODEL"] = name
            env["EMBEDDING_DIM"] = "16"
            migration = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                                       env=env, capture_output=True, text=True, timeout=60,
                                       encoding="utf-8")
            if migration.returncode:
                raise RuntimeError("临时数据库迁移失败")
            # 子进程读取临时库环境，所有连接池与缓存均独立。
            code = """
import json
from pathlib import Path
from uuid import uuid4
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.ingestion.sample_importer import import_sample_data
from app.analysis_contracts import AnalysisRequest
from app.services.tasks import TaskService
from app.workers.runner import run_task
from app.services.analysis_store import AnalysisStore
from app.repositories.vectors import EvidenceVectors, vector_identity
from app.services.indexing import change_evidence, sync_events
from app.services.hybrid_search import search_evidence
from app.db.index_models import IndexEvent
factory=get_session_factory()
with factory() as session:
    imported=import_sample_data(session,Path('data/sample'))
tasks=TaskService(factory,get_settings())
payload=json.loads(Path('data/sample/analysis-request.json').read_text(encoding='utf-8'))
identity=tasks.create(AnalysisRequest.model_validate(payload),str(uuid4()))
result=run_task(identity)
assert result['status']=='completed',result
report=AnalysisStore(factory,get_settings()).report(identity)
assert report['economics']['scenarios'][1]['contribution']=='7.25'
assert tasks.events(identity)[-1]['type']=='completed'
settings=get_settings()
assert settings.embedding_model.startswith('selection_acceptance_')
owned=[vector_identity(settings,kind) for kind in ('rule','review')]
eid='ev-review-review-cn-001'
try:
    with factory.begin() as session:
        session.add(IndexEvent(id=str(uuid4()),evidence_id=eid))
    synced=sync_events(factory,settings)
    assert synced['failed']==0,synced
    with EvidenceVectors(settings,'review') as vectors:
        hits=vectors.client.query(vectors.collection,filter='evidence_id == \"'+eid+'\"',
                                  output_fields=['chunk_id'],consistency_level='Strong')
        assert len(hits)==1,hits
    change_evidence(factory,eid,content='修改一次的合成评论')
    change_evidence(factory,eid,content='最新版本的合成评论')
    assert sync_events(factory,settings)['failed']==0
    with EvidenceVectors(settings,'review') as vectors:
        hits=vectors.client.query(vectors.collection,filter='evidence_id == \"'+eid+'\"',
                                  output_fields=['chunk_id'],consistency_level='Strong')
        assert len(hits)==1,hits
    change_evidence(factory,eid,delete=True)
    assert search_evidence(factory,settings,query='评论',market='US',kind='review',
                           product_id='prod-cn-001')==[]
    assert sync_events(factory,settings)['failed']==0
    with EvidenceVectors(settings,'review') as vectors:
        hits=vectors.client.query(vectors.collection,filter='evidence_id == \"'+eid+'\"',
                                  output_fields=['chunk_id'],consistency_level='Strong')
        assert not hits
    print(json.dumps({'imported':imported,'result':result,'profit':'7.25',
          'milvus_lifecycle':{'duplicate':True,'late_update':True,'soft_delete':True,
                              'physical_delete':True,'embedding':'isolated mock 16d'}}))
finally:
    with EvidenceVectors(settings,'rule') as vectors:
        for collection in owned:
            if vectors.client.has_collection(collection):
                vectors.client.drop_collection(collection)
"""
            verified = subprocess.run([sys.executable, "-c", code], env=env,
                                      capture_output=True, text=True, timeout=180, encoding="utf-8")
            if verified.returncode:
                raise RuntimeError("临时数据库闭环验证失败：" + verified.stderr[-1500:])
            result = json.loads(verified.stdout.strip().splitlines()[-1])
            result.update(passed=True, temporary_database=name,
                          scope="空 PostgreSQL 库迁移与固定研究；复用现有 py12，不是干净 OS 安装")
            Path("docs/acceptance/reproduction-results.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            print(json.dumps({"passed": True, "temporary_database": name}))
        finally:
            # name 是刚刚成功 CREATE 的本地变量，不接受用户输入，也不枚举数据库。
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)),
            )


if __name__ == "__main__":
    main()
