"""
导入/导出路由
- POST /api/export        → 生成 secrets.py 内容（可选写入文件）
- POST /api/import/file   → 从 secrets.py 文件路径导入到 DB
- POST /api/import/raw    → 直接上传 secrets.py 内容导入
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import PlainTextResponse
from sqlmodel import Session
from pydantic import BaseModel

from backend.database import get_session
from backend.core.exporter import export_secrets
from backend.core.importer import import_from_file, import_secrets

router = APIRouter(prefix="/api", tags=["import-export"])


class ExportRequest(BaseModel):
    output_path: Optional[str] = None  # 非空时同时写入文件


class ImportFileRequest(BaseModel):
    file_path: str  # secrets.py 绝对路径


@router.post("/export", response_class=PlainTextResponse)
def do_export(req: ExportRequest = ExportRequest(), session: Session = Depends(get_session)):
    try:
        content = export_secrets(session, output_path=req.output_path)
        return content
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import/file")
def do_import_file(req: ImportFileRequest, session: Session = Depends(get_session)):
    try:
        stats = import_from_file(session, req.file_path)
        return {"ok": True, **stats}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {req.file_path}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import/upload")
async def do_import_upload(file: UploadFile = File(...), session: Session = Depends(get_session)):
    """上传 secrets.py 文件内容直接导入"""
    try:
        content = await file.read()
        ns: dict = {}
        exec(content.decode("utf-8"), ns)
        stats = import_secrets(session, ns)
        return {"ok": True, **stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
