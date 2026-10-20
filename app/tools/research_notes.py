"""运行隔离的研究笔记工具，所有笔记引用必须属于冻结证据。"""

from langchain_core.tools import tool
from sqlalchemy import select

from app.db.index_models import ResearchNote


def build_note_tools(factory, run_id, snapshot, guard=None):
    """通过闭包绑定运行 ID，不让模型指定其他运行或任意文件路径。"""
    allowed = {row["id"] for row in snapshot["evidence"]}

    @tool
    def write_research_note(name: str, content: str, evidence_ids: list[str]) -> dict:
        """保存当前任务的研究笔记，关联快照证据 ID。"""
        if not 1 <= len(name) <= 80 or len(content) > 5000:
            raise ValueError("笔记名称最多 80 字，正文最多 5000 字")
        if not set(evidence_ids) <= allowed:
            raise ValueError("笔记引用了任务之外的证据")
        with factory.begin() as session:
            if guard:
                guard(session)
            session.merge(ResearchNote(
                run_id=run_id, name=name, content=content, evidence_ids=evidence_ids,
            ))
        return {"status": "saved", "name": name}

    @tool
    def read_research_notes() -> dict:
        """读取当前运行此前保存的研究笔记。"""
        with factory() as session:
            rows = session.scalars(select(ResearchNote).where(ResearchNote.run_id == run_id)).all()
            return {"data": [
                {"name": row.name, "content": row.content, "evidence_ids": row.evidence_ids}
                for row in rows
            ]}

    return [write_research_note, read_research_notes]
