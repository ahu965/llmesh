"""
AI 辅助接口：
- POST /api/ai/suggest-model        单条模型字段推断 + 结构化档案生成
- POST /api/ai/suggest-model/batch  批量为无档案模型生成 ai_profile
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.database import get_session
from backend.models.config import ModelEntry, ProviderGroup
from backend.core.db_utils import touch_db

router = APIRouter(prefix="/api/ai", tags=["ai"])

# ---------- Schema ----------

class SuggestModelRequest(BaseModel):
    vendor: str
    model_name: str


class SuggestModelResponse(BaseModel):
    thinking_mode: str               # "none" / "optional" / "always"
    capabilities: List[str]          # ["text"] / ["text","vision"] 等
    tags: List[str]
    remark: str
    ai_profile: Dict[str, Any]       # 结构化档案


class BatchSuggestRequest(BaseModel):
    model_ids: List[int] = []        # 空列表 = 全部无档案模型
    force_refresh: bool = False      # True = 对已有档案的模型也强制重新调 AI 刷新


class BatchSuggestResponse(BaseModel):
    total: int
    done: int
    failed: int
    errors: List[str]


# ---------- AI 调用核心 ----------

_SUGGEST_PROMPT = """\
你是一个 LLM 模型知识库，用户给你一个 vendor 和 model_name，你需要根据你的知识返回该模型的关键信息。
对于不确定的字段，请使用【保守默认值】，切勿猜测或推断，宁可填默认值也不要填错。

请以 JSON 格式返回，字段说明：

- thinking_mode: 【严格规则】只有以下情况才填非"none"：
  * "always" —— 该模型强制开启思考链，无法关闭（如 o3、QwQ、DeepSeek-R1、Kimi k1.5 系列）
  * "optional" —— 该模型明确支持可开关的思考模式（如 claude-3-7 extended thinking、qwen3 thinking）
  * "none" —— 默认值，不确定时一律填 "none"，普通对话模型均填 "none"
- capabilities: 【严格规则】只有该模型官方明确支持图片/视频等视觉输入时，才在列表中包含 "vision"；
  纯文本模型（不确定时）一律填 ["text"]，不要猜测
- tags: 场景标签列表，从 ["fast","cheap","coding","reasoning","creative","long-context","multilingual"] 中选取，
  只选有把握的标签，不确定时宁可少选
- remark: 一句话适用场景描述（中文，15-30 字）
- positioning: 模型定位（中文，20 字内）
- strengths: 核心强项列表（3-5 条，中文短语）
- best_for: 最适合的使用场景列表（3-5 条，中文短语）
- not_for: 不适合的场景列表（1-3 条，中文短语）
- notes: 特别说明（可为空字符串）
- context_window: 最大输入上下文 token 数（整数，不确定填 0）
- max_output_tokens: 最大输出 token 数（整数，不确定填 0）

vendor: {vendor}
model_name: {model_name}

只返回 JSON，不要有任何额外说明。"""


def _call_ai_suggest(vendor: str, model_name: str) -> Dict[str, Any]:
    """调用已有 LLM 生成模型建议，返回解析后的 dict"""
    try:
        from llmesh import get_llm
        from langchain_core.messages import HumanMessage
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"llmesh 未安装或未配置 secrets.py：{e}")

    prompt = _SUGGEST_PROMPT.format(vendor=vendor, model_name=model_name)
    try:
        llm = get_llm(
            temperature=0.1,
            thinking=False,          # 排除纯思考模型（deepseek-r1 / qwq 等），避免无谓等待
            vision=False,            # 排除视觉模型，档案生成只需纯文本模型
            exclude_tags=["coding"], # 档案生成是纯文本推断，不需要代码专用模型
        )
        result = llm.invoke([HumanMessage(content=prompt)])
        raw = result.content if hasattr(result, "content") else str(result)
        # 提取 JSON 块（容错：去掉可能的 ```json ... ``` 包裹）
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"AI 返回内容无法解析为 JSON：{e}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI 调用失败：{e}")


def _parse_suggest(data: Dict[str, Any]) -> SuggestModelResponse:
    ai_profile = {
        "positioning": data.get("positioning", ""),
        "description": data.get("remark", ""),   # AI 一句话描述，归入档案，不写入 entry.remark
        "strengths": data.get("strengths", []),
        "best_for": data.get("best_for", []),
        "not_for": data.get("not_for", []),
        "notes": data.get("notes", ""),
        "context_window": data.get("context_window", 0),
        "max_output_tokens": data.get("max_output_tokens", 0),
    }
    return SuggestModelResponse(
        thinking_mode=data.get("thinking_mode", "none"),
        capabilities=data.get("capabilities", ["text"]),
        tags=data.get("tags", []),
        remark=data.get("remark", ""),
        ai_profile=ai_profile,
    )


# 已知支持思考模式的模型名关键词白名单（全小写）
# AI 推断 thinking_mode 非 none 时，必须命中此列表才真正写入，避免误判
_THINKING_KEYWORDS = {
    # always（仅思考）
    "o1", "o3", "o4",
    "qwq", "qvq",
    "deepseek-r1", "deepseek-r2",
    "k1.5", "k1-5",
    "moonshot-v1-thinking",
    "hunyuan-t1",
    "minimax-m2",               # MiniMax-M2.x 系列均为仅思考
    # optional（可开关）
    "claude-3-7", "claude-3.7",
    "qwen3",                    # qwen3 系列支持可开关 thinking（含 qwen3-vl、qwen3-coder）
    "thinking",                 # 兜底：模型名本身含 thinking（如 LongCat-Flash-Thinking）
    "reasoner",                 # 兜底：模型名本身含 reasoner
    "think",                    # 兜底：模型名本身含 think（如 deepseek-v3.1-think-250821）
}

# 已知支持视觉的模型名关键词白名单（全小写）
_VISION_KEYWORDS = {
    # 通用后缀/前缀
    "vision", "vl", "visual",
    # OpenAI
    "gpt-4o", "gpt-4-turbo", "gpt-4.1", "o4-mini",
    # Anthropic
    "claude-3",
    # Google
    "gemini",
    # Alibaba
    "qwen-vl", "qwen2-vl", "qwen2.5-vl", "qwen3-vl",
    # 开源视觉
    "internvl", "minicpm-v", "llava", "pixtral", "moondream",
    # 国内
    "glm-4v", "glm-4.6v", "step-1v", "hunyuan-vision",
    "ernie-vl", "ernie-4.5-turbo-vl",
}


def _model_matches_keywords(model_name: str, keywords: set) -> bool:
    name = model_name.lower()
    return any(kw in name for kw in keywords)


def _apply_inferred_fields(
    entry: ModelEntry,
    parsed: SuggestModelResponse,
    force: bool = False,
) -> None:
    """将 AI 推断的结果同步回模型字段。

    Args:
        entry:  数据库模型行
        parsed: AI 推断结果
        force:  True = 强制覆盖所有字段（force_refresh 场景）
                False = 以已有值为准，仅在字段为默认值时才写入（默认行为）

    字段写入规则（force=False 时）：
    - supports_thinking / is_thinking_only：已有 True 则保留，不被 AI 清零
    - is_vision：已有 True 则保留，不被 AI 清零
    - tags：与已有值合并去重（人工 + AI 取并集，互不冲突）
    - remark：AI 有返回时直接覆盖（非核心配置，AI 描述通常更准确）
    """
    model_name = entry.model or ""

    # ---- thinking ----
    # 双重校验：AI thinking_mode 非 none + 模型名命中白名单，才认为应开启
    ai_wants_thinking = (
        parsed.thinking_mode in ("always", "optional")
        and _model_matches_keywords(model_name, _THINKING_KEYWORDS)
    )
    ai_wants_only = ai_wants_thinking and parsed.thinking_mode == "always"

    if force:
        # 强制模式：完全由 AI + 白名单决定
        entry.supports_thinking = ai_wants_thinking
        entry.is_thinking_only = ai_wants_only
    else:
        # 保留模式：已有 True 则不降级；AI 认为应开启才往上写
        if ai_wants_thinking:
            entry.supports_thinking = True
            if ai_wants_only:
                entry.is_thinking_only = True
            # optional 时不改 is_thinking_only，保留人工设置
        # AI 认为不支持时：不主动清零已有的 True（以人工设置为准）

    # ---- vision ----
    ai_wants_vision = (
        "vision" in parsed.capabilities
        and _model_matches_keywords(model_name, _VISION_KEYWORDS)
    )

    if force:
        entry.is_vision = ai_wants_vision
    else:
        # 保留模式：已有 True 则不降级
        if ai_wants_vision:
            entry.is_vision = True
        # AI 认为不支持时：不主动清零

    # ---- tags：合并去重（人工 + AI 取并集） ----
    if parsed.tags:
        if force:
            entry.tags = json.dumps(parsed.tags, ensure_ascii=False)
        else:
            existing = json.loads(entry.tags) if entry.tags else []
            merged = list(dict.fromkeys(existing + parsed.tags))  # 保序去重，人工值在前
            entry.tags = json.dumps(merged, ensure_ascii=False)

    # remark 是人工备注字段，AI 不写入


# ---------- 接口 ----------

@router.post("/suggest-model", response_model=SuggestModelResponse)
def suggest_model(body: SuggestModelRequest):
    """根据 vendor + model_name 调用 AI 推断模型字段及生成结构化档案"""
    data = _call_ai_suggest(body.vendor, body.model_name)
    return _parse_suggest(data)


@router.post("/suggest-model/apply/{model_id}")
def apply_suggest_to_model(model_id: int, session: Session = Depends(get_session)):
    """对已有模型调用 AI 生成档案并写入 ai_profile 字段（不覆盖其他字段）"""
    entry = session.get(ModelEntry, model_id)
    if not entry:
        raise HTTPException(status_code=404, detail="模型不存在")
    group = session.get(ProviderGroup, entry.group_id)
    if not group:
        raise HTTPException(status_code=404, detail="厂商组不存在")

    data = _call_ai_suggest(group.vendor, entry.model)
    parsed = _parse_suggest(data)
    entry.ai_profile = json.dumps(parsed.ai_profile, ensure_ascii=False)
    _apply_inferred_fields(entry, parsed, force=False)  # 以已有值为准，不覆盖人工设置
    session.add(entry)
    session.commit()
    session.refresh(entry)
    touch_db(session)
    return {
        "ok": True,
        "ai_profile": parsed.ai_profile,
        "supports_thinking": entry.supports_thinking,
        "is_thinking_only": entry.is_thinking_only,
        "is_vision": entry.is_vision,
        "tags": entry.tags,
    }


@router.post("/suggest-model/batch", response_model=BatchSuggestResponse)
def batch_suggest(body: BatchSuggestRequest, session: Session = Depends(get_session)):
    """批量为无 ai_profile 的模型生成档案；force_refresh=True 时对已有档案的模型也强制重新调 AI"""
    if body.model_ids:
        entries = [session.get(ModelEntry, mid) for mid in body.model_ids]
        entries = [e for e in entries if e is not None]
    else:
        no_profile = session.exec(
            select(ModelEntry).where(
                (ModelEntry.ai_profile == None) | (ModelEntry.ai_profile == "")  # noqa: E711
            )
        ).all()
        if body.force_refresh:
            # force_refresh：对已有档案的模型也重新调 AI，同步所有推断字段
            has_profile = session.exec(
                select(ModelEntry).where(
                    ModelEntry.ai_profile != None,  # noqa: E711
                    ModelEntry.ai_profile != "",
                )
            ).all()
            entries = list(no_profile) + list(has_profile)
        else:
            entries = list(no_profile)

    total = len(entries)
    done = 0
    failed = 0
    errors: List[str] = []

    for entry in entries:
        group = session.get(ProviderGroup, entry.group_id)
        if not group:
            failed += 1
            errors.append(f"model_id={entry.id}: 厂商组不存在")
            continue
        try:
            data = _call_ai_suggest(group.vendor, entry.model)
            parsed = _parse_suggest(data)
            entry.ai_profile = json.dumps(parsed.ai_profile, ensure_ascii=False)
            # force_refresh 时强制覆盖所有推断字段；否则以已有值为准
            _apply_inferred_fields(entry, parsed, force=body.force_refresh)
            session.add(entry)
            session.commit()
            done += 1
        except Exception as e:
            failed += 1
            errors.append(f"model_id={entry.id} ({entry.model}): {e}")

    if done > 0:
        touch_db(session)

    return BatchSuggestResponse(total=total, done=done, failed=failed, errors=errors)
