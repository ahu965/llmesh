"""
任务组 CRUD 路由
任务组 = 命名的调用预设（pinned + exclude_tags + tags + thinking），
调用方通过 get_llm(task_group="名称") 一键引用，无需在代码里硬写模型列表。
"""
import json
import time
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.database import get_session
from backend.models.config import TaskGroup, GlobalSettings

router = APIRouter(prefix="/api/task-groups", tags=["task_groups"])


# ==================== Schema ====================

class TaskGroupWrite(BaseModel):
    name: str
    display_name: Optional[str] = None
    pinned: Optional[List[str]] = None        # ["vendor/model", ...]
    exclude_tags: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    prefer: Optional[List[str]] = None        # 关键字软偏好，如 ["qwen", "gpt"]
    thinking: Optional[bool] = None
    remark: Optional[str] = None
    enabled: bool = True


class TaskGroupRead(BaseModel):
    id: int
    name: str
    display_name: Optional[str]
    pinned: List[str]
    exclude_tags: List[str]
    tags: List[str]
    prefer: List[str]
    thinking: Optional[bool]
    remark: Optional[str]
    enabled: bool


def _to_read(tg: TaskGroup) -> TaskGroupRead:
    return TaskGroupRead(
        id=tg.id,
        name=tg.name,
        display_name=tg.display_name,
        pinned=tg.get_pinned(),
        exclude_tags=tg.get_exclude_tags(),
        tags=tg.get_tags(),
        prefer=tg.get_prefer(),
        thinking=tg.get_thinking(),
        remark=tg.remark,
        enabled=tg.enabled,
    )


def _apply_write(tg: TaskGroup, data: TaskGroupWrite):
    tg.name = data.name.strip()
    tg.display_name = data.display_name
    tg.pinned = json.dumps(data.pinned or [], ensure_ascii=False)
    tg.exclude_tags = json.dumps(data.exclude_tags or [], ensure_ascii=False)
    tg.tags = json.dumps(data.tags or [], ensure_ascii=False)
    tg.prefer = json.dumps(data.prefer or [], ensure_ascii=False)
    tg.thinking = None if data.thinking is None else (1 if data.thinking else 0)
    tg.remark = data.remark
    tg.enabled = data.enabled


def _touch_db(session: Session):
    gs = session.exec(select(GlobalSettings)).first()
    if gs:
        gs.db_updated_at = time.time()
        session.add(gs)


# ==================== 路由 ====================

@router.get("", response_model=List[TaskGroupRead])
def list_task_groups(session: Session = Depends(get_session)):
    tgs = session.exec(select(TaskGroup)).all()
    return [_to_read(tg) for tg in tgs]


@router.post("", response_model=TaskGroupRead)
def create_task_group(data: TaskGroupWrite, session: Session = Depends(get_session)):
    existing = session.exec(select(TaskGroup).where(TaskGroup.name == data.name.strip())).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"任务组名称 '{data.name}' 已存在")
    tg = TaskGroup()
    _apply_write(tg, data)
    session.add(tg)
    _touch_db(session)
    session.commit()
    session.refresh(tg)
    return _to_read(tg)


@router.put("/{tg_id}", response_model=TaskGroupRead)
def update_task_group(tg_id: int, data: TaskGroupWrite, session: Session = Depends(get_session)):
    tg = session.get(TaskGroup, tg_id)
    if not tg:
        raise HTTPException(status_code=404, detail="任务组不存在")
    # 名称唯一性检查（排除自身）
    dup = session.exec(
        select(TaskGroup).where(TaskGroup.name == data.name.strip()).where(TaskGroup.id != tg_id)
    ).first()
    if dup:
        raise HTTPException(status_code=409, detail=f"任务组名称 '{data.name}' 已存在")
    _apply_write(tg, data)
    session.add(tg)
    _touch_db(session)
    session.commit()
    session.refresh(tg)
    return _to_read(tg)


@router.delete("/{tg_id}")
def delete_task_group(tg_id: int, session: Session = Depends(get_session)):
    tg = session.get(TaskGroup, tg_id)
    if not tg:
        raise HTTPException(status_code=404, detail="任务组不存在")
    session.delete(tg)
    _touch_db(session)
    session.commit()
    return {"ok": True}
