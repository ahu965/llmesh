"""db 工具函数，供各路由共用"""
import time
from sqlmodel import Session, select
from backend.models.config import GlobalSettings


def touch_db(session: Session):
    """任何 DB 写操作后调用，更新 db_updated_at 时间戳"""
    gs = session.exec(select(GlobalSettings)).first()
    if not gs:
        gs = GlobalSettings()
        session.add(gs)
    gs.db_updated_at = time.time()
    session.add(gs)
    session.commit()
