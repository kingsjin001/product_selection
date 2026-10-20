"""报告会话的有界历史和并发控制；每次问答独立于原分析预算。"""

from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select

from app.db.interaction_models import ReportConversation
from app.services.tasks import TaskConflict, utc


def start_turn(factory, run_id, report_hash, conversation_id, request_key, payload):
    """绑定报告并领取三分钟租约；相同成功请求重试返回已有回答。"""
    identity = conversation_id or str(uuid5(NAMESPACE_URL, f"{run_id}:{request_key}"))
    token = str(uuid4())
    with factory.begin() as session:
        row = session.scalar(select(ReportConversation).where(
            ReportConversation.id == identity).with_for_update())
        if row is None:
            if conversation_id:
                raise ValueError("会话不存在，请先新建会话")
            row = ReportConversation(id=identity, run_id=run_id,
                                     report_hash=report_hash, history=[])
            session.add(row)
        if row.run_id != run_id or row.report_hash != report_hash:
            raise ValueError("会话不属于当前报告")
        for turn in row.history:
            if turn["key"] == request_key:
                if turn["request"] != payload:
                    raise TaskConflict("同一追问键对应不同内容")
                return identity, None, [], turn["response"]
        if row.busy_until and utc(row.busy_until) > datetime.now(UTC):
            raise TaskConflict("当前会话正在回答，请等待后继续")
        row.busy_token, row.busy_until = token, datetime.now(UTC) + timedelta(minutes=3)
        history = [{"question": turn["request"]["question"][:2000],
                    "answer": turn["response"]["answer"][:4000],
                    "evidence_ids": turn["response"]["evidence_ids"]}
                   for turn in row.history[-6:]]
        return identity, token, history, None


def finish_turn(session, identity, token, key, payload, response):
    """回答和有界会话在同一事务落盘，过期请求不能覆盖新一轮回答。"""
    row = session.scalar(select(ReportConversation).where(
        ReportConversation.id == identity).with_for_update())
    if row.busy_token != token or utc(row.busy_until) <= datetime.now(UTC):
        raise TaskConflict("会话租约已过期，请重新追问")
    row.history = (row.history + [{"key": key, "request": payload, "response": response}])[-6:]
    row.busy_token, row.busy_until = None, None


def release_turn(factory, identity, token):
    """失败释放当前租约；旧请求不能释放新请求持有的租约。"""
    with factory.begin() as session:
        row = session.scalar(select(ReportConversation).where(
            ReportConversation.id == identity).with_for_update())
        if row and row.busy_token == token:
            row.busy_token, row.busy_until = None, None
