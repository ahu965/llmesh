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
from backend.models.config import GlobalSettings, ProviderGroup, ModelEntry, TaskGroup
from llmesh.pool import _DEFAULT_EXCLUDE_TAGS

router = APIRouter(prefix="/api/simulate", tags=["simulate"])


# ---------- Schema ----------


class SimulateRequest(BaseModel):
    prefer: Optional[str] = None  # 逗号分隔关键字，如 "openai,gpt"
    thinking: Optional[bool] = None  # True/False/None
    vision: Optional[bool] = None  # True=只视觉模型；None=排除视觉模型
    tags: Optional[str] = None  # 逗号分隔 tag，如 "cheap,fast"
    exclude_tags: Optional[str] = None  # 逗号分隔 tag，命中的模型被硬排除
    task_group: Optional[str] = None  # 任务组名称，自动展开为对应参数


class SimulateModelItem(BaseModel):
    vendor: str
    model: str
    priority: int
    weight: int
    effective_weight: int  # 权重（命中 prefer/tags 时保留，否则=weight）
    weight_pct: float  # 在同层中的权重占比 (0~100)
    is_prefer_hit: bool  # 是否命中 prefer
    is_tags_hit: bool  # 是否命中 tags
    thinking_mode: str  # "none" / "optional" / "always"
    capabilities: List[str]  # ["text"] / ["text","vision"] 等
    # 兼容旧字段（前端 Simulator.vue 可能仍引用）
    supports_thinking: bool
    is_thinking_only: bool
    is_vision: bool
    tags: List[str]
    remark: Optional[str]
    group_remark: Optional[str]


class SimulateLayer(BaseModel):
    priority: int
    is_active: bool  # True=当前实际会被选的层
    models: List[SimulateModelItem]


class PinnedSimulateItem(BaseModel):
    """pinned 阶段每个候选的展示信息"""

    order: int  # 在 pinned 列表中的顺序（从 1 开始）
    vendor: str
    model: str
    in_pool: bool  # 是否在当前启用的模型池中
    thinking_override: Optional[bool]  # 该条目的 thinking 覆盖值（None=继承任务组全局）
    thinking_mode: str  # 模型的 thinking_mode（不在池中时为 "unknown"）
    capabilities: List[str]
    tags: List[str]
    remark: Optional[str]
    group_remark: Optional[str]


class SimulateResponse(BaseModel):
    layers: List[SimulateLayer]
    disabled_count: int  # 被禁用（enabled=False）排除的模型数
    filtered_out_count: int  # 被硬过滤（thinking/vision）剔除的模型数
    filter_reason: str  # 硬过滤说明
    pinned_models: List[
        PinnedSimulateItem
    ] = []  # 任务组 pinned 阶段候选列表（无 pinned 时为空）


# ---------- 构建内存模型池（直接从 DB 读，不依赖 secrets.py）----------


def _build_pool_from_db(session: Session):
    gs = session.exec(select(GlobalSettings)).first() or GlobalSettings()
    default_timeout = gs.default_timeout

    # 统计禁用数量
    all_groups = session.exec(select(ProviderGroup)).all()
    enabled_group_ids = {g.id for g in all_groups if g.enabled}
    all_models = session.exec(select(ModelEntry)).all()
    disabled_count = sum(
        1 for m in all_models if not m.enabled or m.group_id not in enabled_group_ids
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
            # 新字段优先，旧字段兼容
            thinking_mode = m.thinking_mode
            if not thinking_mode:
                if m.supports_thinking and m.is_thinking_only:
                    thinking_mode = "always"
                elif m.supports_thinking:
                    thinking_mode = "optional"
                else:
                    thinking_mode = "none"

            caps: List[str] = []
            if m.capabilities:
                try:
                    caps = json.loads(m.capabilities)
                except Exception:
                    pass
            if not caps:
                caps = ["text", "vision"] if m.is_vision else ["text"]

            m_priority = m.priority if m.priority is not None else g.priority
            m_weight = m.weight if m.weight is not None else g.weight
            m_tags: List[str] = []
            if m.tags:
                try:
                    m_tags = json.loads(m.tags)
                except Exception:
                    pass

            pool.append(
                {
                    "vendor": g.vendor,
                    "model": m.model,
                    "priority": m_priority,
                    "weight": m_weight,
                    "thinking_mode": thinking_mode,
                    "capabilities": caps,
                    # 兼容旧字段
                    "supports_thinking": thinking_mode in ("optional", "always"),
                    "is_thinking_only": thinking_mode == "always",
                    "is_vision": "vision" in caps,
                    "tags": m_tags,
                    "remark": m.remark,
                    "group_remark": g.remark,
                }
            )
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
    pinned: Optional[List] = None,  # 原始 pinned 列表（str 或 dict 混合）
) -> SimulateResponse:
    prefer_list = [p.strip().lower() for p in prefer.split(",")] if prefer else []
    tags_list = [t.strip() for t in tags.split(",")] if tags else []
    exclude_tags_list = (
        [t.strip() for t in exclude_tags.split(",")] if exclude_tags else []
    )

    total = len(pool)
    available = list(pool)
    filter_reasons = []

    # --- thinking 硬过滤 ---
    # thinking=True：只保留 optional / always
    if thinking is True:
        available = [
            m for m in available if m["thinking_mode"] in ("optional", "always")
        ]
        filter_reasons.append("thinking=True → 仅 thinking_mode=optional/always 模型")
    # thinking=False：排除 always（常开思考模型），其余均可用
    if thinking is False:
        available = [m for m in available if m["thinking_mode"] != "always"]
        filter_reasons.append("thinking=False → 排除 thinking_mode=always 模型")

    # --- vision 硬过滤 ---
    if vision is True:
        available = [m for m in available if "vision" in m["capabilities"]]
        filter_reasons.append("vision=True → 仅含 vision 能力的模型")
    else:
        available = [m for m in available if "vision" not in m["capabilities"]]
        filter_reasons.append("vision=None/False → 排除含 vision 能力的模型")

    # --- exclude_tags 硬排除 ---
    if exclude_tags_list:
        available = [
            m for m in available if not any(t in m["tags"] for t in exclude_tags_list)
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
                if any(
                    k in m["vendor"].lower() or k in m["model"].lower()
                    for k in prefer_list
                ):
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
            items.append(
                SimulateModelItem(
                    vendor=m["vendor"],
                    model=m["model"],
                    priority=pri,
                    weight=m["weight"],
                    effective_weight=eff_w,
                    weight_pct=pct,
                    is_prefer_hit=k in prefer_hits,
                    is_tags_hit=k in tags_hits,
                    thinking_mode=m["thinking_mode"],
                    capabilities=m["capabilities"],
                    supports_thinking=m["supports_thinking"],
                    is_thinking_only=m["is_thinking_only"],
                    is_vision=m["is_vision"],
                    tags=m["tags"],
                    remark=m["remark"],
                    group_remark=m["group_remark"],
                )
            )

        # 只有第一层是 active（后续层只有前层全挂才会被用到）
        layers.append(
            SimulateLayer(
                priority=pri,
                is_active=(idx == 0),
                models=items,
            )
        )

    # --- pinned 阶段展示（镜像 pool.py 的 pinned 逻辑，按序列出候选及在池中的状态）---
    pool_index = {f"{m['vendor']}/{m['model']}": m for m in pool}
    pinned_items: List[PinnedSimulateItem] = []
    if pinned:
        for idx, item in enumerate(pinned, start=1):
            if isinstance(item, dict):
                vm: str = item.get("vm", "")
                thinking_override: Optional[bool] = item.get(
                    "thinking"
                )  # None=继承全局
            else:
                vm = str(item)
                thinking_override = None
            m = pool_index.get(vm)
            if m:
                parts = vm.split("/", 1)
                pinned_items.append(
                    PinnedSimulateItem(
                        order=idx,
                        vendor=parts[0],
                        model=parts[1] if len(parts) > 1 else vm,
                        in_pool=True,
                        thinking_override=thinking_override,
                        thinking_mode=m.get("thinking_mode", "none"),
                        capabilities=m.get("capabilities", []),
                        tags=m.get("tags", []),
                        remark=m.get("remark"),
                        group_remark=m.get("group_remark"),
                    )
                )
            else:
                parts = vm.split("/", 1)
                pinned_items.append(
                    PinnedSimulateItem(
                        order=idx,
                        vendor=parts[0] if len(parts) > 1 else "?",
                        model=parts[1] if len(parts) > 1 else vm,
                        in_pool=False,
                        thinking_override=thinking_override,
                        thinking_mode="unknown",
                        capabilities=[],
                        tags=[],
                        remark=None,
                        group_remark=None,
                    )
                )

    return SimulateResponse(
        layers=layers,
        disabled_count=disabled_count,
        filtered_out_count=filtered_out,
        filter_reason=filter_reason,
        pinned_models=pinned_items,
    )


# ---------- 接口 ----------


class TaskGroupMeta(BaseModel):
    name: str
    display_name: Optional[str]


class SimulateMeta(BaseModel):
    tags: List[str]  # 所有模型 tags 去重
    vendors: List[str]  # 所有启用的 vendor 名去重
    task_groups: List[TaskGroupMeta]  # 所有启用的任务组


@router.get("/meta", response_model=SimulateMeta)
def simulate_meta(session: Session = Depends(get_session)):
    """返回当前所有启用模型的 tags、vendor 集合和任务组列表，用于前端下拉候选"""
    all_groups = session.exec(
        select(ProviderGroup).where(ProviderGroup.enabled == True)
    ).all()  # noqa: E712
    enabled_group_ids = {g.id for g in all_groups}
    vendors = sorted({g.vendor for g in all_groups})

    all_tags: set = set()
    entries = session.exec(
        select(ModelEntry).where(ModelEntry.enabled == True)  # noqa: E712
    ).all()
    for m in entries:
        if m.group_id not in enabled_group_ids:
            continue
        if m.tags:
            try:
                all_tags.update(json.loads(m.tags))
            except Exception:
                pass

    tgs = session.exec(
        select(TaskGroup).where(TaskGroup.enabled == True)  # noqa: E712
    ).all()
    task_groups = [
        TaskGroupMeta(name=tg.name, display_name=tg.display_name) for tg in tgs
    ]

    return SimulateMeta(tags=sorted(all_tags), vendors=vendors, task_groups=task_groups)


@router.post("", response_model=SimulateResponse)
def simulate_routing(body: SimulateRequest, session: Session = Depends(get_session)):
    pool, disabled_count = _build_pool_from_db(session)

    prefer = body.prefer or None
    thinking = body.thinking
    vision = body.vision
    tags = body.tags or None
    # None = 未填，应用与 get_llm() 相同的默认排除标签；
    # 空字符串 "" = 主动清空，模拟不排除任何标签的场景
    if body.exclude_tags is None:
        exclude_tags = ",".join(_DEFAULT_EXCLUDE_TAGS)
    else:
        exclude_tags = body.exclude_tags or None
    pinned: Optional[List] = None

    # 任务组展开（显式参数优先覆盖）
    if body.task_group:
        tg = session.exec(
            select(TaskGroup).where(TaskGroup.name == body.task_group)
        ).first()
        if tg and tg.enabled:
            if pinned is None and tg.pinned:
                try:
                    pinned = json.loads(tg.pinned)  # List[str | dict]
                except Exception:
                    pass
            if prefer is None and tg.prefer:
                try:
                    prefer_list = json.loads(tg.prefer)
                    if prefer_list:
                        prefer = ",".join(prefer_list)
                except Exception:
                    pass
            if thinking is None and tg.thinking is not None:
                thinking = bool(tg.thinking)
            if tags is None and tg.tags:
                try:
                    tags_list = json.loads(tg.tags)
                    if tags_list:
                        tags = ",".join(tags_list)
                except Exception:
                    pass
            if exclude_tags is None and tg.exclude_tags:
                try:
                    exc_list = json.loads(tg.exclude_tags)
                    if exc_list:
                        exclude_tags = ",".join(exc_list)
                except Exception:
                    pass

    return _simulate(
        pool=pool,
        disabled_count=disabled_count,
        prefer=prefer,
        thinking=thinking,
        vision=vision,
        tags=tags,
        exclude_tags=exclude_tags,
        pinned=pinned,
    )
