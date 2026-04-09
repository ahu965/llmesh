"""
厂商分组 & 模型条目 CRUD 路由
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from pydantic import BaseModel

from backend.database import get_session
from backend.models.config import ProviderGroup, ModelEntry
from backend.core.db_utils import touch_db

router = APIRouter(prefix="/api/providers", tags=["providers"])


# ---------- 请求/响应 Schema ----------

class ModelEntryRead(BaseModel):
    id: Optional[int]
    group_id: int
    model: str
    weight: Optional[int]
    timeout: Optional[int]
    remark: Optional[str]
    supports_thinking: bool = False
    is_thinking_only: bool = False
    extra_body: Optional[str]
    expires_at: Optional[str]
    priority: Optional[int]
    is_vision: bool = False
    tags: Optional[str]
    enabled: bool = True
    thinking_timeout: Optional[int]

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
    expires_at: Optional[str] = None
    priority: Optional[int] = None
    is_vision: bool = False
    tags: Optional[str] = None
    enabled: bool = True
    thinking_timeout: Optional[int] = None


class ProviderGroupRead(BaseModel):
    id: Optional[int]
    vendor: str
    alias: Optional[str]
    website: Optional[str]
    api_key: str
    base_url: str
    weight: int
    timeout: int
    remark: Optional[str]
    billing_mode: Optional[str]
    expires_at: Optional[str]
    priority: int = 0
    enabled: bool
    models: List[ModelEntryRead] = []

    class Config:
        from_attributes = True


class ProviderGroupWrite(BaseModel):
    vendor: str
    alias: Optional[str] = None
    website: Optional[str] = None
    api_key: str
    base_url: str
    weight: int = 1
    timeout: int = 60
    remark: Optional[str] = None
    billing_mode: Optional[str] = None
    expires_at: Optional[str] = None
    priority: int = 0
    enabled: bool = True


# ---------- 老数据 NULL 回填工具 ----------

def _fix_group(g: ProviderGroup) -> ProviderGroup:
    """迁移新增列在老数据行里可能为 NULL，读取时统一回填默认值"""
    if g.priority is None:
        g.priority = 0
    return g


def _fix_model(m: ModelEntry) -> ModelEntry:
    """迁移新增 bool 列在老数据行里可能为 NULL，读取时统一回填默认值"""
    if m.supports_thinking is None:
        m.supports_thinking = False
    if m.is_thinking_only is None:
        m.is_thinking_only = False
    if m.is_vision is None:
        m.is_vision = False
    if m.enabled is None:
        m.enabled = True
    return m


def _load_group_read(g: ProviderGroup, session: Session) -> ProviderGroupRead:
    """读取单个 ProviderGroup 及其 ModelEntry，返回 ProviderGroupRead（含 NULL 回填）"""
    _fix_group(g)
    models = session.exec(
        select(ModelEntry)
        .where(ModelEntry.group_id == g.id)
        .order_by(ModelEntry.priority, ModelEntry.id)
    ).all()
    item = ProviderGroupRead.model_validate(g)
    item.models = [ModelEntryRead.model_validate(_fix_model(m)) for m in models]
    return item


# ---------- ProviderGroup CRUD ----------

@router.get("", response_model=List[ProviderGroupRead])
def list_providers(session: Session = Depends(get_session)):
    groups = session.exec(select(ProviderGroup).order_by(ProviderGroup.priority)).all()
    return [_load_group_read(g, session) for g in groups]


@router.post("", response_model=ProviderGroupRead)
def create_provider(data: ProviderGroupWrite, session: Session = Depends(get_session)):
    group = ProviderGroup(**data.model_dump())
    session.add(group)
    session.commit()
    session.refresh(group)
    touch_db(session)
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
    touch_db(session)
    return _load_group_read(group, session)


@router.delete("/{group_id}")
def delete_provider(group_id: int, session: Session = Depends(get_session)):
    group = session.get(ProviderGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Provider group not found")
    entries = session.exec(select(ModelEntry).where(ModelEntry.group_id == group_id)).all()
    for e in entries:
        session.delete(e)
    session.delete(group)
    session.commit()
    touch_db(session)
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
    touch_db(session)
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
    touch_db(session)
    return ModelEntryRead.model_validate(entry)


@router.delete("/{group_id}/models/{model_id}")
def delete_model(group_id: int, model_id: int, session: Session = Depends(get_session)):
    entry = session.get(ModelEntry, model_id)
    if not entry or entry.group_id != group_id:
        raise HTTPException(status_code=404, detail="Model entry not found")
    session.delete(entry)
    session.commit()
    touch_db(session)
    return {"ok": True}


# ---------- 拖拽排序接口 ----------

class ReorderBody(BaseModel):
    ids: List[int]  # 按新顺序排列的 id 列表


@router.put("/reorder", response_model=List[ProviderGroupRead])
def reorder_groups(body: ReorderBody, session: Session = Depends(get_session)):
    """按传入 id 顺序重新写入 priority（0, 1, 2 …）"""
    for idx, gid in enumerate(body.ids):
        group = session.get(ProviderGroup, gid)
        if group:
            group.priority = idx
            session.add(group)
    session.commit()
    touch_db(session)
    return list_providers(session)


@router.put("/{group_id}/models/reorder", response_model=List[ModelEntryRead])
def reorder_models(group_id: int, body: ReorderBody, session: Session = Depends(get_session)):
    """按传入 id 顺序重新写入模型的 priority（0, 1, 2 …）"""
    if not session.get(ProviderGroup, group_id):
        raise HTTPException(status_code=404, detail="Provider group not found")
    for idx, mid in enumerate(body.ids):
        entry = session.get(ModelEntry, mid)
        if entry and entry.group_id == group_id:
            entry.priority = idx
            session.add(entry)
    session.commit()
    touch_db(session)
    models = session.exec(
        select(ModelEntry)
        .where(ModelEntry.group_id == group_id)
        .order_by(ModelEntry.priority, ModelEntry.id)
    ).all()
    return [ModelEntryRead.model_validate(m) for m in models]
