"""
路由模拟器接口
根据当前数据库配置，模拟 get_llm(prefer, thinking, vision, tags) 的选模型过程，
返回经过三阶段过滤+分层后的模型列表及权重占比，不实际调用任何 LLM。
"""
from __future__ import annotations

import json
from typing import List, Optional, Union

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.database import get_session
from backend.models.config import GlobalSettings, ProviderGroup, ModelEntry

router = APIRouter(prefix="/api/simulate", tags=["simulate"])


# ---------- Schema ----------

class SimulateRequest(BaseModel):
    prefer: Optional[str] = None          # 逗号分隔关键字，如 "openai,gpt"
    thinking: Optional[bool] = None       # True/False/None
    vision: Optional[bool] = None         # True=只视觉模型；None=排除视觉模型
    tags: Optional[str] = None            # 逗号分隔 tag，如 "cheap,fast"
    exclude_tags: Optional[str] = None    # 逗号分隔 tag，命中的模型被硬排除


class SimulateModelItem(BaseModel):
    vendor: str
    model: str
    priority: int
    weight: int
    effective_weight: int                 # 权重（命中 prefer/tags 时保留，否则=weight）
    weight_pct: float                     # 在同层中的权重占比 (0~100)
    is_prefer_hit: bool                   # 是否命中 prefer
    is_tags_hit: bool                     # 是否命中 tags
    supports_thinking: bool
    is_thinking_only: bool
    is_vision: bool
    tags: List[str]
    remark: Optional[str]
    group_remark: Optional[str]


class SimulateLayer(BaseModel):
    priority: int
    is_active: bool                       # True=当前实际会被选的层
    models: List[SimulateModelItem]


class SimulateResponse(BaseModel):
    layers: List[SimulateLayer]
    disabled_count: int                   # 被禁用（enabled=False）排除的模型数
    filtered_out_count: int               # 被硬过滤（thinking/vision）剔除的模型数
    filter_reason: str                    # 硬过滤说明


# ---------- 构建内存模型池（直接从 DB 读，不依赖 secrets.py）----------

def _build_pool_from_db(session: Session):
    gs = session.exec(select(GlobalSettings)).first() or GlobalSettings()
    default_timeout = gs.default_timeout

    # 统计禁用数量
    all_groups = session.exec(select(ProviderGroup)).all()
    enabled_group_ids = {g.id for g in all_groups if g.enabled}
    all_models = session.exec(select(ModelEntry)).all()
    disabled_count = sum(
        1 for m in all_models
        if not m.enabled or m.group_id not in enabled_group_ids
    )

    groups = [g for g in all_groups if g.enabled]

    pool = []
    for g in groups:
        if g.priority is None:
            g.priority = 0
        entries = session.exec(
            select(ModelEntry)
            .where(ModelEntry.group_id == g.id)
            .where(ModelEntry.enabled == True)  # noqa: E712
        ).all()
        for m in entries:
            if m.supports_thinking is None:
                m.supports_thinking = False
            if m.is_thinking_only is None:
                m.is_thinking_only = False
            if m.is_vision is None:
                m.is_vision = False

            m_priority = m.priority if m.priority is not None else g.priority
            m_weight = m.weight if m.weight is not None else g.weight
            m_tags: List[str] = []
            if m.tags:
                try:
                    m_tags = json.loads(m.tags)
                except Exception:
                    pass

            pool.append({
                "vendor": g.vendor,
                "model": m.model,
                "priority": m_priority,
                "weight": m_weight,
                "supports_thinking": m.supports_thinking,
                "is_thinking_only": m.is_thinking_only,
                "is_vision": m.is_vision,
                "tags": m_tags,
                "remark": m.remark,
                "group_remark": g.remark,
            })
    return pool, disabled_count


# ---------- 过滤逻辑（镜像 pool._get_next_model，但返回全量结果）----------

def _simulate(
    pool: list,
    disabled_count: int,
    prefer: Optional[str],
    thinking: Optional[bool],
    vision: Optional[bool],
    tags: Optional[str],
    exclude_tags: Optional[str] = None,
) -> SimulateResponse:
    prefer_list = [p.strip().lower() for p in prefer.split(",")] if prefer else []
    tags_list = [t.strip() for t in tags.split(",")] if tags else []
    exclude_tags_list = [t.strip() for t in exclude_tags.split(",")] if exclude_tags else []

    total = len(pool)
    available = list(pool)
    filter_reasons = []

    # --- thinking 硬过滤 ---
    # thinking=True：只保留支持思考模式的模型
    if thinking is True:
        available = [m for m in available if m["supports_thinking"]]
        filter_reasons.append("thinking=True → 仅 supports_thinking 模型")
    # thinking=False：排除纯思考模型（is_thinking_only=True），其余模型均可用
    if thinking is False:
        available = [m for m in available if not m["is_thinking_only"]]
        filter_reasons.append("thinking=False → 排除 is_thinking_only 模型")

    # --- vision 硬过滤 ---
    if vision is True:
        available = [m for m in available if m["is_vision"]]
        filter_reasons.append("vision=True → 仅视觉模型")
    else:
        available = [m for m in available if not m["is_vision"]]
        filter_reasons.append("vision=None/False → 排除视觉模型")

    # --- exclude_tags 硬排除 ---
    if exclude_tags_list:
        available = [
            m for m in available
            if not any(t in m["tags"] for t in exclude_tags_list)
        ]
        filter_reasons.append(f"exclude_tags={exclude_tags_list} → 排除命中 tag 的模型")

    filtered_out = total - len(available)
    filter_reason = "；".join(filter_reasons)

    # --- priority 分层 ---
    priorities = sorted({m["priority"] for m in available})
    layers: List[SimulateLayer] = []

    for idx, pri in enumerate(priorities):
        layer_models = [m for m in available if m["priority"] == pri]

        # 判断 prefer / tags 命中
        prefer_hits = set()
        tags_hits = set()
        if prefer_list:
            for m in layer_models:
                key = f"{m['vendor']}_{m['model']}"
                if any(k in m["vendor"].lower() or k in m["model"].lower() for k in prefer_list):
                    prefer_hits.add(key)
        if tags_list:
            for m in layer_models:
                key = f"{m['vendor']}_{m['model']}"
                if any(t in m["tags"] for t in tags_list):
                    tags_hits.add(key)

        # 当前层实际参与抽签的子集
        key_fn = lambda m: f"{m['vendor']}_{m['model']}"
        if prefer_hits:
            active_keys = prefer_hits
        elif tags_hits:
            active_keys = tags_hits
        else:
            active_keys = {key_fn(m) for m in layer_models}

        # 计算层内权重占比
        active_models = [m for m in layer_models if key_fn(m) in active_keys]
        total_w = sum(m["weight"] for m in active_models) or 1

        items: List[SimulateModelItem] = []
        for m in layer_models:
            k = key_fn(m)
            is_active_candidate = k in active_keys
            eff_w = m["weight"] if is_active_candidate else 0
            pct = round(eff_w / total_w * 100, 1) if is_active_candidate else 0.0
            items.append(SimulateModelItem(
                vendor=m["vendor"],
                model=m["model"],
                priority=pri,
                weight=m["weight"],
                effective_weight=eff_w,
                weight_pct=pct,
                is_prefer_hit=k in prefer_hits,
                is_tags_hit=k in tags_hits,
                supports_thinking=m["supports_thinking"],
                is_thinking_only=m["is_thinking_only"],
                is_vision=m["is_vision"],
                tags=m["tags"],
                remark=m["remark"],
                group_remark=m["group_remark"],
            ))

        # 只有第一层是 active（后续层只有前层全挂才会被用到）
        layers.append(SimulateLayer(
            priority=pri,
            is_active=(idx == 0),
            models=items,
        ))

    return SimulateResponse(
        layers=layers,
        disabled_count=disabled_count,
        filtered_out_count=filtered_out,
        filter_reason=filter_reason,
    )


# ---------- 接口 ----------

@router.post("", response_model=SimulateResponse)
def simulate_routing(body: SimulateRequest, session: Session = Depends(get_session)):
    pool, disabled_count = _build_pool_from_db(session)
    return _simulate(
        pool=pool,
        disabled_count=disabled_count,
        prefer=body.prefer or None,
        thinking=body.thinking,
        vision=body.vision,
        tags=body.tags or None,
        exclude_tags=body.exclude_tags or None,
    )
