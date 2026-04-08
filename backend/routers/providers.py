"""
厂商分组 & 模型条目 CRUD 路由
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from pydantic import BaseModel

from backend.database import get_session
from backend.models.config import ProviderGroup, ModelEntry

router = APIRouter(prefix="/api/providers", tags=["providers"])


# ---------- 请求/响应 Schema ----------

class ModelEntryRead(BaseModel):
    id: Optional[int]
    group_id: int
    model: str
    weight: Optional[int]
    timeout: Optional[int]
    remark: Optional[str]
    supports_thinking: bool
    is_thinking_only: bool
    extra_body: Optional[str]
    enabled: bool

    class Config:
        from_attributes = True


class ModelEntryWrite(BaseModel):
    model: str
    weight: Optional[int] = None
    timeout: Optional[int] = None
    remark: Optional[str] = None
    supports_thinking: bool = False
    is_thinking_only: bool = False
    extra_body: Optional[str] = None
    enabled: bool = True


class ProviderGroupRead(BaseModel):
    id: Optional[int]
    vendor: str
    api_key: str
    base_url: str
    weight: int
    timeout: int
    remark: Optional[str]
    billing_mode: Optional[str]
    expires_at: Optional[str]
    enabled: bool
    models: List[ModelEntryRead] = []

    class Config:
        from_attributes = True


class ProviderGroupWrite(BaseModel):
    vendor: str
    api_key: str
    base_url: str
    weight: int = 1
    timeout: int = 60
    remark: Optional[str] = None
    billing_mode: Optional[str] = None
    expires_at: Optional[str] = None
    enabled: bool = True


# ---------- ProviderGroup CRUD ----------

@router.get("", response_model=List[ProviderGroupRead])
def list_providers(session: Session = Depends(get_session)):
    groups = session.exec(select(ProviderGroup)).all()
    result = []
    for g in groups:
        models = session.exec(
            select(ModelEntry).where(ModelEntry.group_id == g.id)
        ).all()
        item = ProviderGroupRead.model_validate(g)
        item.models = [ModelEntryRead.model_validate(m) for m in models]
        result.append(item)
    return result


@router.post("", response_model=ProviderGroupRead)
def create_provider(data: ProviderGroupWrite, session: Session = Depends(get_session)):
    group = ProviderGroup(**data.model_dump())
    session.add(group)
    session.commit()
    session.refresh(group)
    item = ProviderGroupRead.model_validate(group)
    item.models = []
    return item


@router.put("/{group_id}", response_model=ProviderGroupRead)
def update_provider(group_id: int, data: ProviderGroupWrite, session: Session = Depends(get_session)):
    group = session.get(ProviderGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Provider group not found")
    for k, v in data.model_dump().items():
        setattr(group, k, v)
    session.add(group)
    session.commit()
    session.refresh(group)
    models = session.exec(select(ModelEntry).where(ModelEntry.group_id == group.id)).all()
    item = ProviderGroupRead.model_validate(group)
    item.models = [ModelEntryRead.model_validate(m) for m in models]
    return item


@router.delete("/{group_id}")
def delete_provider(group_id: int, session: Session = Depends(get_session)):
    group = session.get(ProviderGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Provider group not found")
    # 级联删除模型
    entries = session.exec(select(ModelEntry).where(ModelEntry.group_id == group_id)).all()
    for e in entries:
        session.delete(e)
    session.delete(group)
    session.commit()
    return {"ok": True}


# ---------- ModelEntry CRUD ----------

@router.post("/{group_id}/models", response_model=ModelEntryRead)
def add_model(group_id: int, data: ModelEntryWrite, session: Session = Depends(get_session)):
    if not session.get(ProviderGroup, group_id):
        raise HTTPException(status_code=404, detail="Provider group not found")
    entry = ModelEntry(group_id=group_id, **data.model_dump())
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return ModelEntryRead.model_validate(entry)


@router.put("/{group_id}/models/{model_id}", response_model=ModelEntryRead)
def update_model(group_id: int, model_id: int, data: ModelEntryWrite,
                 session: Session = Depends(get_session)):
    entry = session.get(ModelEntry, model_id)
    if not entry or entry.group_id != group_id:
        raise HTTPException(status_code=404, detail="Model entry not found")
    for k, v in data.model_dump().items():
        setattr(entry, k, v)
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return ModelEntryRead.model_validate(entry)


@router.delete("/{group_id}/models/{model_id}")
def delete_model(group_id: int, model_id: int, session: Session = Depends(get_session)):
    entry = session.get(ModelEntry, model_id)
    if not entry or entry.group_id != group_id:
        raise HTTPException(status_code=404, detail="Model entry not found")
    session.delete(entry)
    session.commit()
    return {"ok": True}
