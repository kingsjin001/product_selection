"""导入页面使用的商品列表、JSON 和三个文件上传接口。"""

import csv
import io
import json
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import Product
from app.db.session import get_session_factory
from app.ingestion.imports import ImportRequest, import_records

router = APIRouter(prefix="/api", tags=["导入工作台"])


@router.get("/products")
def products():
    """只列出页面选择商品需要的字段。"""
    with get_session_factory()() as session:
        rows = session.scalars(select(Product).order_by(Product.id).limit(5000)).all()
        return [{"id": row.id, "name": row.name, "market": row.market, "category": row.category}
                for row in rows]


@router.post("/imports")
def import_json(request: ImportRequest):
    """输入无效或 ID 冲突时整体回滚，不静默覆盖手工资料。"""
    try:
        return import_records(get_session_factory(), request)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except IntegrityError as error:
        raise HTTPException(409, "导入与其他写入冲突，请检查 ID 后重试") from error


@router.post("/imports/files")
async def import_files(products: Annotated[UploadFile | None, File()] = None,
                       reviews: Annotated[UploadFile | None, File()] = None,
                       rules: Annotated[UploadFile | None, File()] = None):
    """CSV 商品/评论与 JSONL 规则，按文件类型解析，不执行上传内容。"""
    records = {}
    try:
        for name, upload in (("products", products), ("reviews", reviews), ("rules", rules)):
            if upload is None:
                continue
            raw = await upload.read(5 * 1024 * 1024 + 1)
            if len(raw) > 5 * 1024 * 1024:
                raise HTTPException(413, "每个文件最多 5 MiB")
            content = raw.decode("utf-8-sig")
            records[name] = ([json.loads(line) for line in content.splitlines() if line.strip()]
                             if name == "rules" else list(csv.DictReader(io.StringIO(content))))
        return import_json(ImportRequest.model_validate(records))
    except (ValueError, UnicodeError, ValidationError) as error:
        raise HTTPException(422, f"文件格式或字段不符合要求：{error}") from error
