"""全局配置路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from backend.database import get_session
from backend.models.config import GlobalSettings
from backend.core.db_utils import touch_db

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=GlobalSettings)
def get_settings(session: Session = Depends(get_session)):
    gs = session.exec(select(GlobalSettings)).first()
    if not gs:
        raise HTTPException(status_code=404, detail="Settings not found")
    return gs


@router.put("", response_model=GlobalSettings)
def update_settings(data: GlobalSettings, session: Session = Depends(get_session)):
    gs = session.exec(select(GlobalSettings)).first()
    if not gs:
        gs = GlobalSettings()
    for field in data.model_fields:
        if field not in ("id", "last_built_at", "db_updated_at"):
            setattr(gs, field, getattr(data, field))
    session.add(gs)
    session.commit()
    session.refresh(gs)
    touch_db(session)
    session.refresh(gs)
    return gs
