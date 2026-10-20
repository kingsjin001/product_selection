"""短期签名上下文把 MCP 请求绑定到可信运行和当前 Worker。"""

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.analysis_models import AnalysisRun
from app.db.index_models import EvidenceState
from app.db.models import Evidence
from app.db.task_models import Task


def secret(settings):
    """强制显式设置服务密钥，拒绝无鉴权启动和短默认口令。"""
    value = settings.mcp_shared_secret
    if value is None or len(value.get_secret_value()) < 32:
        raise ValueError("MCP_SHARED_SECRET 至少 32 字符，客户端和服务端需一致")
    return value.get_secret_value().encode()


def sign_context(settings, run, epoch):
    """签名仅由 Worker 生成；不会出现在模型工具参数或日志中。"""
    payload = {"run_id": run["id"], "snapshot": run["snapshot"]["hash"],
               "epoch": epoch, "expires": int(time.time()) + settings.agent_timeout_seconds + 30,
               "contract": "evidence-v1"}
    body = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode()
    signature = hmac.new(secret(settings), body.encode(), hashlib.sha256).hexdigest()
    return body + "." + signature


def verify_context(settings, token):
    """拒绝篡改、过期或非本期协议上下文，异常不泄露签名内容。"""
    try:
        body, signature = token.split(".")
        expected = hmac.new(secret(settings), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        value = json.loads(base64.urlsafe_b64decode(body))
        if value["expires"] <= time.time() or value["contract"] != "evidence-v1":
            raise ValueError
        return value
    except (ValueError, KeyError, TypeError) as error:
        raise PermissionError("MCP 运行上下文无效或已过期") from error


def scoped_snapshot(factory, context, settings=None):
    """调用前后检查任务与证据；取消、旧 epoch 或删除资料立即使上下文失效。"""
    with factory() as session:
        run = session.get(AnalysisRun, context["run_id"])
        if run is None or run.status != "running" or run.snapshot["hash"] != context["snapshot"]:
            raise PermissionError("MCP 运行已失效")
        if settings and any(run.versions[key] != getattr(settings, field) for key, field in (
            ("embedding", "embedding_model"), ("embedding_dim", "embedding_dim"),
            ("embedding_provider", "embedding_provider"), ("milvus_database", "milvus_database"),
        )):
            raise PermissionError("MCP 服务检索配置与冻结版本不一致")
        task = session.get(Task, run.id)
        if task:
            lease = task.lease_until
            if lease and lease.tzinfo is None:
                lease = lease.replace(tzinfo=UTC)
            if (task.status != "running" or task.epoch != context["epoch"]
                    or lease is None or lease <= datetime.now(UTC)):
                raise PermissionError("MCP Worker 已失去执行权")
        elif context["epoch"] is not None:
            raise PermissionError("MCP 运行类型不匹配")
        frozen = {row["id"]: row for row in run.snapshot["evidence"]}
        rows = session.scalars(select(Evidence).where(Evidence.id.in_(frozen))).all()
        states = {row.evidence_id: row for row in session.scalars(select(EvidenceState).where(
            EvidenceState.evidence_id.in_(frozen))).all()}
        if len(rows) != len(frozen) or any(
            row.content_hash != frozen[row.id]["content_hash"] or
            (row.id in states and not states[row.id].active) for row in rows
        ):
            raise PermissionError("MCP 冻结证据已经变更，请新建研究")
        return run.snapshot
