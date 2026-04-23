"""
Playground — 多模型对比评测
同一 prompt 并发发送给多个模型，可选 LLM-as-Judge 自动评分，结果支持 JSON 格式导出。
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select, func

from backend.database import get_session
from backend.models.config import GlobalSettings, ProviderGroup, ModelEntry, PlaygroundHistory

router = APIRouter(prefix="/api/playground", tags=["playground"])

# ---------- Schema ----------


class PlaygroundModelRef(BaseModel):
    """前端选中的模型引用（group_id + model_id）"""
    group_id: int
    model_id: int


class PlaygroundRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="用户输入的评测 prompt")
    models: List[PlaygroundModelRef] = Field(
        ..., min_length=1, max_length=10, description="参与对比的模型列表"
    )
    thinking: Optional[bool] = Field(None, description="是否开启思考模式")
    temperature: Optional[float] = Field(None, ge=0, le=2, description="覆盖默认温度")
    judge: bool = Field(False, description="是否启用 LLM-as-Judge 自动评分")
    tools: Optional[List[Dict[str, Any]]] = Field(
        None, description="OpenAI 格式的工具定义列表，用于评测 tool calling"
    )
    system_prompt: Optional[str] = Field(
        None, description="自定义 system prompt，为空则使用默认的自我认知探测 system message"
    )


class ToolCall(BaseModel):
    """模型发起的一次工具调用"""
    id: Optional[str] = None           # tool_call_id
    name: str                           # 函数名
    arguments: Dict[str, Any] = {}      # 函数参数（已解析的 JSON）


class ModelResult(BaseModel):
    """单个模型的响应结果"""
    group_id: int
    model_id: int
    vendor: str
    model: str
    ok: bool
    reply: Optional[str] = None
    latency_ms: int = 0
    error: Optional[str] = None
    thinking_used: bool = False      # 实际是否使用了思考模式
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    self_identity: Optional[str] = None  # 模型自报身份（如 "我是 Qwen3，知识截止到 2025-06"）
    tool_calls: Optional[List[ToolCall]] = None  # 模型发起的工具调用列表


class JudgeResult(BaseModel):
    """LLM-as-Judge 的评分结果"""
    judge_vendor: str
    judge_model: str
    ranking: List[str]                 # 排名：["vendor1/model1", "vendor2/model2", ...]
    scores: Dict[str, float]           # 各模型得分：{"vendor/model": 8.5, ...}
    comment: str                       # 评委总评


class PlaygroundResponse(BaseModel):
    prompt: str
    results: List[ModelResult]
    judge: Optional[JudgeResult] = None
    total_time_ms: int


# ---------- 并发调用 ----------


async def _invoke_model(
    group: ProviderGroup,
    entry: ModelEntry,
    prompt: str,
    temperature: float,
    thinking: Optional[bool],
    default_timeout: int,
    default_max_tokens: int,
    tools: Optional[List[Dict[str, Any]]] = None,
    system_prompt: Optional[str] = None,
) -> ModelResult:
    """对单个模型执行调用，返回 ModelResult（在线程池中运行同步 LangChain 调用）"""
    loop = asyncio.get_event_loop()

    def _do_invoke() -> ModelResult:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from backend.utils.llm_invoke import build_chat_llm
            from backend.models.config import GlobalSettings as _GS
        except ImportError as e:
            return ModelResult(
                group_id=group.id, model_id=entry.id,
                vendor=group.vendor, model=entry.model,
                ok=False, error=f"缺少依赖：{e}",
            )

        # 判断 thinking_used（用于前端展示）
        thinking_mode = entry.thinking_mode
        if not thinking_mode:
            if entry.supports_thinking and entry.is_thinking_only:
                thinking_mode = "always"
            elif entry.supports_thinking:
                thinking_mode = "optional"
            else:
                thinking_mode = "none"

        thinking_used = (
            (thinking is True and thinking_mode in ("optional", "always"))
            or thinking_mode == "always"
        )

        # 构造 GlobalSettings 占位（timeout/max_tokens 由显式参数覆盖）
        gs_placeholder = _GS(
            temperature=temperature,
            max_tokens=default_max_tokens,
            default_timeout=default_timeout,
        )

        try:
            llm = build_chat_llm(
                group, entry, gs_placeholder,
                thinking=thinking,
                streaming=not bool(tools),
            )

            # 如果有工具定义，绑定到 LLM
            if tools:
                from langchain_core.utils.function_calling import convert_to_openai_tool
                lc_tools = [convert_to_openai_tool(t) for t in tools]
                llm = llm.bind_tools(lc_tools)

            # System message 构造逻辑：
            # 1. 如果用户提供了自定义 system_prompt，直接使用
            # 2. 否则使用默认的自我认知探测 system message
            # 3. 但当评测 tool calling 时，使用专用的 tool calling system message
            if system_prompt:
                system_msg = SystemMessage(content=system_prompt)
            elif not tools:
                system_msg = SystemMessage(
                    content=(
                        "你是一个智能助手，请认真回答用户的问题。"
                        "如果你知道自己的模型名称和知识截止日期，可以在回答末尾用 "
                        "[ID: 模型名，知识截止到 XXXX-XX] 格式注明，不强制要求。"
                    )
                )
            else:
                system_msg = SystemMessage(
                    content=(
                        "你是一个智能助手，根据用户的需求调用合适的工具完成任务。\n"
                        f"当前日期时间：{datetime.now().strftime('%Y-%m-%d %A')}。"
                        "用户说'明天'、'后天'等相对日期时，请据此计算。"
                    )
                )

            t0 = time.time()
            tool_calls_result: Optional[List[ToolCall]] = None
            tokens_input: Optional[int] = None
            tokens_output: Optional[int] = None

            if tools:
                # tool calling 模式：用 invoke 获取完整响应（含 tool_calls）
                messages = [system_msg, HumanMessage(content=prompt)]
                result = llm.invoke(messages)
                reply = result.content or ""

                # 提取 token 使用量
                usage = result.usage_metadata or {}
                tokens_input = usage.get("input_tokens")
                tokens_output = usage.get("output_tokens")

                # 提取 tool_calls
                if result.tool_calls:
                    tool_calls_result = []
                    for tc in result.tool_calls:
                        tc_args = {}
                        if tc.get("args"):
                            tc_args = tc["args"] if isinstance(tc["args"], dict) else {}
                        tool_calls_result.append(ToolCall(
                            id=tc.get("id"),
                            name=tc.get("name", "unknown"),
                            arguments=tc_args,
                        ))
            else:
                # 普通模式：流式输出
                chunks = []
                last_chunk = None
                for chunk in llm.stream([system_msg, HumanMessage(content=prompt)]):
                    chunks.append(chunk.content or "")
                    last_chunk = chunk
                reply = "".join(chunks)

                # 从最后一个 chunk 提取 token 使用量
                if last_chunk and last_chunk.usage_metadata:
                    usage = last_chunk.usage_metadata
                    tokens_input = usage.get("input_tokens")
                    tokens_output = usage.get("output_tokens")

            latency_ms = int((time.time() - t0) * 1000)

            # 提取 self_identity（仅在非 tool calling 模式下）
            self_identity = None
            if not tools:
                import re
                id_match = re.search(r'\[ID:\s*(.+?)\]', reply)
                if id_match:
                    self_identity = id_match.group(1).strip()
                    reply = re.sub(r'\s*\[ID:\s*.+?\]\s*', '', reply).strip()

                # 如果移除身份标记后 reply 为空，标记为实质无响应
                if not reply:
                    reply = "(模型仅返回了身份标记，无实质回复内容)"
            else:
                # tool calling 模式：空文本回复是正常的（模型直接发 tool_calls）
                if not reply:
                    reply = ""

            return ModelResult(
                group_id=group.id,
                model_id=entry.id,
                vendor=group.vendor,
                model=entry.model,
                ok=True,
                reply=reply,
                latency_ms=latency_ms,
                thinking_used=thinking_used,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                self_identity=self_identity,
                tool_calls=tool_calls_result,
            )
        except Exception as e:
            err = str(e).split("\n")[0][:300]
            return ModelResult(
                group_id=group.id,
                model_id=entry.id,
                vendor=group.vendor,
                model=entry.model,
                ok=False,
                error=err,
            )

    return await loop.run_in_executor(None, _do_invoke)


async def _judge_responses(
    prompt: str,
    results: List[ModelResult],
    participant_keys: set,   # {"vendor_model", ...} 参赛模型，评委排除
    tools: Optional[List[Dict[str, Any]]] = None,  # 工具定义（用于 tool calling 评分）
) -> JudgeResult:
    """使用 get_llm(thinking=False, exclude_tags='math,vision') 从池中选裁判模型评分"""
    loop = asyncio.get_event_loop()

    # 判断是否为 tool calling 评测模式
    is_tool_mode = tools is not None

    # 构造评分 prompt
    if is_tool_mode:
        # ---- Tool Calling 评分模式 ----
        tools_summary = json.dumps(tools, ensure_ascii=False, indent=2)

        responses_text = ""
        for i, r in enumerate(results):
            status = "成功" if r.ok else f"失败({r.error})"
            tc_lines = ""
            if r.tool_calls:
                for tc in r.tool_calls:
                    args_str = json.dumps(tc.arguments, ensure_ascii=False)
                    tc_lines += f"\n    - 调用 {tc.name}({args_str})"
            else:
                tc_lines = "\n    (未发起任何工具调用)"
            responses_text += f"\n--- 回答 {i+1} [{r.vendor}/{r.model}] ({status}) ---\n  文本回复：{r.reply or '(无文本回复)'}\n  工具调用：{tc_lines}\n"

        judge_prompt = f"""你是一位专业的 AI 模型评测专家，擅长评估模型的 Tool Calling（函数调用）能力。请对以下模型的表现进行评分和排名。

## 原始问题
{prompt}

## 可用工具定义
{tools_summary}

## 模型响应
{responses_text}

## 评分标准（针对 Tool Calling）
- 工具选择准确性（35%）：是否选择了正确的工具函数？有没有调错或漏调？
- 参数正确性（25%）：传递的参数是否正确、完整（特别是日期、城市名、数值等关键参数）？有没有编造不存在的值？
- 任务理解（20%）：是否正确理解了用户的完整需求（包括隐含需求）？
- 文本回复质量（10%）：在工具调用之外的文本回复是否有条理、是否有用？
- 边界处理（10%）：对于用户未明确指定的参数（如酒店住几晚），是否合理处理（如主动询问而非瞎猜）？

## 扣分规则
- 参数编造严重错误（如把2026年写成2023年）：准确性扣 2~4 分
- 漏调了用户明显需要的工具：完整性扣 2~4 分
- 用户未指定但模型瞎猜参数（如自编酒店退房日期）：扣 1~3 分
- 选错了工具函数：准确性扣 3~5 分

## 输出格式（严格 JSON）
```json
{{{{
  "ranking": ["vendor1/model1", "vendor2/model2"],
  "scores": {{"vendor1/model1": 8.5, "vendor2/model2": 7.2}},
  "comment": "评委总评"
}}}}
```

请确保：
1. ranking 中的标识符与回答的 vendor/model 完全一致
2. scores 为 0-10 分（保留一位小数）
3. comment 字段中不要使用双引号（用单引号或中文引号代替），以免破坏 JSON 格式
4. 只输出 JSON，不要其他内容"""

    else:
        # ---- 普通文本评分模式 ----
        responses_text = ""
        for i, r in enumerate(results):
            status = "成功" if r.ok else f"失败({r.error})"
            identity_line = f"\n  自我认知：{r.self_identity}" if r.self_identity else ""
            responses_text += f"\n--- 回答 {i+1} [{r.vendor}/{r.model}] ({status}){identity_line} ---\n{r.reply or '(无回复)'}\n"

        judge_prompt = f"""你是一位专业的 AI 模型评测专家。请对以下模型对同一个问题的回答进行评分和排名。

## 原始问题
{prompt}

## 模型回答
{responses_text}

## 评分标准
- 准确性（30%）：回答是否准确、无事实错误
- 完整性（25%）：是否全面覆盖问题涉及的要点
- 清晰性（20%）：表达是否清晰、条理分明
- 实用性（15%）：回答是否具有实际参考价值
- 创新性（10%）：是否有独到见解或新颖角度

## 扣分规则（重要）
- 如果模型否认或歪曲自身能力（如声称不支持某项实际支持的功能），应大幅扣分（准确性 -2~5 分）
- 如果模型捏造不存在的信息或给出明显错误的'我不知道'式回答，应扣分
- 如果模型的知识截止日期明显过旧，导致无法回答该问题，请在 comment 中说明但不额外扣分（这是模型本身的限制）
- 如果模型声称的身份与其实际 vendor/model 明显不符（身份错乱），视为严重问题，准确性扣 3~5 分，并在 comment 中指出

## 输出格式（严格 JSON）
```json
{{{{
  "ranking": ["vendor1/model1", "vendor2/model2"],
  "scores": {{"vendor1/model1": 8.5, "vendor2/model2": 7.2}},
  "comment": "评委总评"
}}}}
```

请确保：
1. ranking 中的标识符与回答的 vendor/model 完全一致
2. scores 为 0-10 分（保留一位小数）
3. comment 字段中不要使用双引号（用单引号或中文引号代替），以免破坏 JSON 格式
4. 只输出 JSON，不要其他内容"""

    def _do_judge() -> JudgeResult:
        try:
            from llmesh import get_llm
            from langchain_core.messages import HumanMessage, SystemMessage
        except ImportError as e:
            return JudgeResult(
                judge_vendor="", judge_model="",
                ranking=[], scores={},
                comment=f"缺少依赖：{e}",
            )

        try:
            llm = get_llm(
                thinking=False,
                exclude_tags=["math", "vision"],
                exclude_models=participant_keys,
            )
            # 使用 SystemMessage 设定评委角色，提升指令遵循效果
            judge_system = SystemMessage(content=(
                "你是一位专业的 AI 模型评测专家，具备丰富的 NLP 和 LLM 评估经验。"
                "你的评分客观、严谨，严格遵守给定的评分标准，不受模型知名度影响。"
                "输出必须是严格合法的 JSON，不包含任何额外内容。"
            ))
            result = llm.invoke([judge_system, HumanMessage(content=judge_prompt)])
            raw = (result.content or "").strip()
            judge_vendor_model = llm.last_model or "unknown/unknown"
            parts = judge_vendor_model.split("/", 1)
            judge_vendor = parts[0]
            judge_model  = parts[1] if len(parts) > 1 else judge_vendor_model

            # 提取 JSON
            json_str = raw
            if "```json" in raw:
                json_str = raw.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in raw:
                json_str = raw.split("```", 1)[1].split("```", 1)[0].strip()

            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                try:
                    start = json_str.index("{")
                    end = json_str.rindex("}") + 1
                    data = json.loads(json_str[start:end])
                except (json.JSONDecodeError, ValueError):
                    data = None

            if data is None:
                return JudgeResult(
                    judge_vendor=judge_vendor, judge_model=judge_model,
                    ranking=[], scores={},
                    comment=f"评委输出解析失败（非有效 JSON）：{raw[:500]}",
                )

            return JudgeResult(
                judge_vendor=judge_vendor,
                judge_model=judge_model,
                ranking=data.get("ranking", []),
                scores=data.get("scores", {}),
                comment=data.get("comment", ""),
            )
        except Exception as e:
            return JudgeResult(
                judge_vendor="", judge_model="",
                ranking=[], scores={},
                comment=f"评委调用失败：{str(e)[:300]}",
            )

    return await loop.run_in_executor(None, _do_judge)


# ---------- 接口 ----------


class AvailableModel(BaseModel):
    """可选模型（供前端模型选择器使用）"""
    group_id: int
    model_id: int
    vendor: str
    model: str
    alias: Optional[str] = None        # 分组别名
    thinking_mode: str                 # "none" / "optional" / "always"
    tags: List[str] = []
    remark: Optional[str] = None


@router.get("/models", response_model=List[AvailableModel])
def list_available_models(session: Session = Depends(get_session)):
    """返回所有可用模型列表，供前端 Playground 模型选择器使用"""
    all_groups = session.exec(
        select(ProviderGroup).where(ProviderGroup.enabled == True)  # noqa: E712
    ).all()
    enabled_group_ids = {g.id for g in all_groups}

    entries = session.exec(
        select(ModelEntry)
        .where(ModelEntry.enabled == True)  # noqa: E712
        .where(ModelEntry.group_id.in_(enabled_group_ids))
    ).all()

    group_map = {g.id: g for g in all_groups}
    models = []
    for m in entries:
        g = group_map[m.group_id]
        thinking_mode = m.thinking_mode
        if not thinking_mode:
            if m.supports_thinking and m.is_thinking_only:
                thinking_mode = "always"
            elif m.supports_thinking:
                thinking_mode = "optional"
            else:
                thinking_mode = "none"
        tags: List[str] = []
        if m.tags:
            try:
                tags = json.loads(m.tags)
            except Exception:
                pass
        models.append(AvailableModel(
            group_id=g.id,
            model_id=m.id,
            vendor=g.vendor,
            model=m.model,
            alias=g.alias,
            thinking_mode=thinking_mode,
            tags=tags,
            remark=m.remark,
        ))
    return models


@router.post("/run", response_model=PlaygroundResponse)
async def run_playground(
    body: PlaygroundRequest,
    session: Session = Depends(get_session),
):
    """
    执行多模型对比评测：
    1. 并发调用所有选中的模型
    2. 如果启用 judge，使用裁判模型评分
    3. 返回所有结果 + 评分
    """
    # 获取全局配置
    gs = session.exec(select(GlobalSettings)).first() or GlobalSettings()
    temperature = body.temperature if body.temperature is not None else gs.temperature
    default_timeout = gs.default_timeout
    default_max_tokens = gs.max_tokens

    # 加载所有选中的模型配置
    group_map: Dict[int, ProviderGroup] = {}
    entry_map: Dict[int, ModelEntry] = {}
    for ref in body.models:
        g = session.get(ProviderGroup, ref.group_id)
        e = session.get(ModelEntry, ref.model_id)
        if not g or not e or e.group_id != ref.group_id:
            raise HTTPException(
                status_code=404,
                detail=f"模型不存在：group_id={ref.group_id}, model_id={ref.model_id}",
            )
        if not g.enabled or not e.enabled:
            raise HTTPException(
                status_code=400,
                detail=f"模型已禁用：{g.vendor}/{e.model}",
            )
        group_map[ref.group_id] = g
        entry_map[ref.model_id] = e

    # 并发调用所有模型
    t0 = time.time()
    tasks = [
        _invoke_model(
            group=group_map[ref.group_id],
            entry=entry_map[ref.model_id],
            prompt=body.prompt,
            temperature=temperature,
            thinking=body.thinking,
            default_timeout=default_timeout,
            default_max_tokens=default_max_tokens,
            tools=body.tools,
            system_prompt=body.system_prompt,
        )
        for ref in body.models
    ]
    results = await asyncio.gather(*tasks)
    total_time_ms = int((time.time() - t0) * 1000)

    # LLM-as-Judge 评分
    judge_result = None
    if body.judge:
        # 参赛模型的 key 集合（"vendor_model" 格式），评委通过 exclude_models 排除
        participant_keys = {
            f"{group_map[ref.group_id].vendor}_{entry_map[ref.model_id].model}"
            for ref in body.models
        }
        judge_result = await _judge_responses(
            prompt=body.prompt,
            results=list(results),
            participant_keys=participant_keys,
            tools=body.tools,
        )
        total_time_ms = int((time.time() - t0) * 1000)

    # 保存历史记录
    try:
        history = PlaygroundHistory(
            prompt=body.prompt,
            thinking=body.thinking,
            temperature=body.temperature,
            tool_mode=bool(body.tools),
            tools_json=json.dumps(body.tools, ensure_ascii=False) if body.tools else None,
            results_json=json.dumps([r.model_dump() for r in results], ensure_ascii=False),
            judge_json=json.dumps(judge_result.model_dump(), ensure_ascii=False) if judge_result else None,
            total_time_ms=total_time_ms,
            model_count=len(results),
        )
        session.add(history)
        session.commit()
    except Exception as e:
        # 历史记录保存失败不影响主流程，只记录日志
        import logging
        logging.warning(f"保存 Playground 历史记录失败: {e}")

    return PlaygroundResponse(
        prompt=body.prompt,
        results=list(results),
        judge=judge_result,
        total_time_ms=total_time_ms,
    )


# ---------- 历史记录 Schema ----------


class HistorySummary(BaseModel):
    """历史记录列表项（摘要）"""
    id: int
    created_at: datetime
    prompt: str                           # 截取后的预览（前 200 字）
    tool_mode: bool
    total_time_ms: int
    model_count: int


class HistoryDetail(BaseModel):
    """历史记录详情"""
    id: int
    created_at: datetime
    prompt: str
    thinking: Optional[bool] = None
    temperature: Optional[float] = None
    tool_mode: bool
    tools_json: Optional[str] = None
    results: List[ModelResult]
    judge: Optional[JudgeResult] = None
    total_time_ms: int
    model_count: int
    remark: Optional[str] = None


# ---------- 历史记录接口 ----------


@router.get("/history")
def list_history(
    page: int = 1,
    page_size: int = 20,
    session: Session = Depends(get_session),
):
    """
    返回历史评测记录列表（分页，按创建时间倒序）。
    - page: 页码，默认 1
    - page_size: 每页数量，默认 20，最大 100
    """
    # 限制 page_size
    page_size = min(page_size, 100)
    offset = (page - 1) * page_size

    # 查询总数
    total = session.exec(select(func.count()).select_from(PlaygroundHistory)).one()

    # 查询分页数据
    records = session.exec(
        select(PlaygroundHistory)
        .order_by(PlaygroundHistory.created_at.desc())
        .offset(offset)
        .limit(page_size)
    ).all()

    # 转换为摘要格式
    summaries = []
    for r in records:
        prompt_preview = r.prompt[:200] if r.prompt else ""
        summaries.append(HistorySummary(
            id=r.id,
            created_at=r.created_at,
            prompt=prompt_preview,
            tool_mode=r.tool_mode,
            total_time_ms=r.total_time_ms,
            model_count=r.model_count,
        ))

    return {"records": summaries, "total": total}


@router.get("/history/{history_id}", response_model=HistoryDetail)
def get_history_detail(
    history_id: int,
    session: Session = Depends(get_session),
):
    """返回单条历史记录的完整详情"""
    history = session.get(PlaygroundHistory, history_id)
    if not history:
        raise HTTPException(status_code=404, detail="历史记录不存在")

    # 反序列化 results 和 judge
    results = []
    try:
        if history.results_json:
            for r_data in json.loads(history.results_json):
                results.append(ModelResult(**r_data))
    except Exception:
        pass

    judge = None
    try:
        if history.judge_json:
            judge = JudgeResult(**json.loads(history.judge_json))
    except Exception:
        pass

    return HistoryDetail(
        id=history.id,
        created_at=history.created_at,
        prompt=history.prompt,
        thinking=history.thinking,
        temperature=history.temperature,
        tool_mode=history.tool_mode,
        tools_json=history.tools_json,
        results=results,
        judge=judge,
        total_time_ms=history.total_time_ms,
        model_count=history.model_count,
        remark=history.remark,
    )


@router.delete("/history/{history_id}")
def delete_history(
    history_id: int,
    session: Session = Depends(get_session),
):
    """删除指定的历史记录"""
    history = session.get(PlaygroundHistory, history_id)
    if not history:
        raise HTTPException(status_code=404, detail="历史记录不存在")

    session.delete(history)
    session.commit()
    return None
