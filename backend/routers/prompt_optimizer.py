"""
提示词优化工程 — Prompt Optimizer
输入用户的自然语言描述（人话），通过 LLM 输出结构化、可直接复制的优化 Prompt。
支持多种优化策略和自定义场景。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from backend.database import get_session
from backend.models.config import GlobalSettings, ProviderGroup, ModelEntry
from backend.routers.playground import AvailableModel
from backend.routers.scene_prompts_generated import SCENE_SYSTEM_PROMPTS as _SCENE_SYSTEM_PROMPTS
from llmesh.pool import _DEFAULT_EXCLUDE_TAGS

router = APIRouter(prefix="/api/prompt-optimizer", tags=["prompt-optimizer"])


# ---------- Schema ----------


class OptimizeRequest(BaseModel):
    """优化请求"""

    raw_prompt: str = Field(..., min_length=1, description="用户原始提示词（人话）")
    strategy: str = Field(
        "auto",
        description="优化策略：auto / role / cot / few_shot / constraint / format，或场景 key（如 scene_05_bug_analysis）",
    )
    context: Optional[str] = Field(
        None, description="补充上下文信息（技术栈、环境、约束等）"
    )
    output_format: Optional[str] = Field(
        None,
        description="期望的输出格式描述（如：表格、JSON、Markdown列表）",
    )
    model_ref: Optional["ModelRef"] = Field(
        None, description="指定使用的模型（不填则用路由池自动选择）"
    )


class ModelRef(BaseModel):
    group_id: int
    model_id: int


class OptimizeResponse(BaseModel):
    """优化响应"""

    raw_prompt: str
    optimized_prompt: str
    strategy_used: str
    tips: List[str]
    model_vendor: str
    model_name: str
    latency_ms: int
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None


class CompareTestRequest(BaseModel):
    """对比测试请求：用同一个模型分别跑原始 prompt 和优化后的 prompt"""

    raw_prompt: str = Field(..., min_length=1, description="原始提示词")
    optimized_prompt: str = Field(..., min_length=1, description="优化后的提示词")
    test_model: ModelRef = Field(..., description="用于测试的模型")


class CompareTestResult(BaseModel):
    """单个 prompt 的测试结果"""

    prompt_type: str  # "raw" | "optimized"
    reply: str
    latency_ms: int
    ok: bool
    error: Optional[str] = None


class CompareTestResponse(BaseModel):
    """对比测试响应"""

    raw_prompt: str
    optimized_prompt: str
    test_model_vendor: str
    test_model_name: str
    raw_result: CompareTestResult
    optimized_result: CompareTestResult


class AskRequest(BaseModel):
    """直接提问请求：只用优化后的提示词调用模型"""

    optimized_prompt: str = Field(..., min_length=1, description="优化后的提示词")
    test_model: ModelRef = Field(..., description="用于提问的模型")


class AskResponse(BaseModel):
    """直接提问响应"""

    optimized_prompt: str
    test_model_vendor: str
    test_model_name: str
    reply: str
    latency_ms: int
    ok: bool
    error: Optional[str] = None


class MultiModelCompareRequest(BaseModel):
    """多模型对比请求：用多个模型同时跑优化后的提示词"""

    optimized_prompt: str = Field(..., min_length=1, description="优化后的提示词")
    test_models: List[ModelRef] = Field(..., min_length=1, max_length=6, description="参与对比的模型列表")


class MultiModelCompareItem(BaseModel):
    """单个模型的对比结果"""

    group_id: int
    model_id: int
    vendor: str
    model_name: str
    reply: str
    latency_ms: int
    ok: bool
    error: Optional[str] = None


class MultiModelCompareResponse(BaseModel):
    """多模型对比响应"""

    optimized_prompt: str
    results: List[MultiModelCompareItem]


class RecommendRequest(BaseModel):
    """AI 推荐策略请求"""

    raw_prompt: str = Field(..., min_length=1)


class RecommendResponse(BaseModel):
    """AI 推荐策略响应"""

    recommended_keys: List[str]
    reason: str


# ---------- 策略模板 ----------

_STRATEGY_SYSTEM_PROMPTS = {
    "auto": """你是一位提示词工程专家。你的任务是将用户的原始提问优化为结构清晰、约束明确的 Prompt，使 LLM 能够更准确地理解意图并给出高质量回答。

## 优化原则
1. **角色定位**：如果原始提问暗示了特定领域，添加专业的角色设定
2. **上下文补全**：基于用户提供的上下文信息，补充必要的环境/技术栈描述
3. **约束明确**：明确输出格式、边界条件、不要做什么
4. **消除歧义**：消除模糊表述，使指令唯一确定
5. **简洁有力**：优化后的 Prompt 不应过度冗长，保持清晰

## 输出格式
请直接输出优化后的 Prompt 正文（纯文本，不要加任何标题行、不要加引号或代码块包裹，第一行就是 Prompt 内容），然后在 Prompt 后面空一行，输出：

### 优化说明
- 策略：使用了哪些优化手段
- 假设：如果原始提示词信息不完整，列出你补充或假设的条件（例如：假设使用 Python、假设面向初学者）；若信息完整则省略此项
- 建议：1-3 条针对这个场景的额外建议

## 占位符规则
如果原始提示词中有需要用户自己提供的具体信息（如项目名、技术栈、目标 URL、数据结构等），请在优化后的 Prompt 中用 `[请替换: 描述]` 格式标注，不要自行假设。例：`[请替换: 你的编程语言]`、`[请替换: 目标网站 URL]`。""",
    "role": """你是一位提示词工程专家，专注于通过角色设定来提升 LLM 输出质量。

你的任务是将用户的原始提问优化为带有专业角色设定的 Prompt：
1. 根据问题领域设定一个具体的专家角色（含经验年限、擅长领域）
2. 在角色设定中融入回答风格和约束规则
3. 确保角色设定与问题高度匹配

请直接输出优化后的 Prompt 正文（不要加任何标题行，第一行就是 Prompt 内容），然后在空一行后输出优化说明（包含：策略、假设（信息不完整时列出）、建议）。

如果原始提示词中有需要用户自己提供的具体信息，请在优化后的 Prompt 中用 `[请替换: 描述]` 格式标注，不要自行假设。""",
    "cot": """你是一位提示词工程专家，专注于 Chain-of-Thought（思维链）技术。

你的任务是将用户的原始提问优化为引导 LLM 进行逐步推理的 Prompt：
1. 要求 LLM 先展示分析过程，再给出结论
2. 拆解复杂问题为多个子步骤
3. 要求 LLM 在推理过程中自检逻辑一致性

请直接输出优化后的 Prompt 正文（不要加任何标题行，第一行就是 Prompt 内容），然后在空一行后输出优化说明（包含：策略、假设（信息不完整时列出）、建议）。

如果原始提示词中有需要用户自己提供的具体信息，请在优化后的 Prompt 中用 `[请替换: 描述]` 格式标注，不要自行假设。""",
    "few_shot": """你是一位提示词工程专家，专注于 Few-Shot（少样本示例）技术。

你的任务是将用户的原始提问优化为包含示例的 Prompt：
1. 提供 1-3 个输入→输出的示例
2. 示例应覆盖典型场景和边界情况
3. 用清晰的格式分隔示例和实际任务

请直接输出优化后的 Prompt 正文（不要加任何标题行，第一行就是 Prompt 内容），然后在空一行后输出优化说明（包含：策略、假设（信息不完整时列出）、建议）。

如果原始提示词中有需要用户自己提供的具体信息，请在优化后的 Prompt 中用 `[请替换: 描述]` 格式标注，不要自行假设。""",
    "constraint": """你是一位提示词工程专家，专注于通过约束条件来减少 LLM 幻觉和错误输出。

你的任务是将用户的原始提问优化为带有严格约束的 Prompt：
1. 明确"不要做什么"（否定约束）
2. 列出必须遵守的规则
3. 定义输出边界和失败处理方式
4. 要求 LLM 对不确定的信息主动声明

请直接输出优化后的 Prompt 正文（不要加任何标题行，第一行就是 Prompt 内容），然后在空一行后输出优化说明（包含：策略、假设（信息不完整时列出）、建议）。

如果原始提示词中有需要用户自己提供的具体信息，请在优化后的 Prompt 中用 `[请替换: 描述]` 格式标注，不要自行假设。""",
    "format": """你是一位提示词工程专家，专注于输出格式控制。

你的任务是将用户的原始提问优化为格式要求明确的 Prompt：
1. 定义明确的输出结构（标题、分节、编号等）
2. 指定具体格式（Markdown表格、JSON、代码块等）
3. 对关键输出字段给出示例
4. 要求统一的数据格式和单位

请直接输出优化后的 Prompt 正文（不要加任何标题行，第一行就是 Prompt 内容），然后在空一行后输出优化说明（包含：策略、假设（信息不完整时列出）、建议）。

如果原始提示词中有需要用户自己提供的具体信息，请在优化后的 Prompt 中用 `[请替换: 描述]` 格式标注，不要自行假设。""",
}


# ---------- 场景策略元信息（与 scene_prompts_generated.py 的 key 一一对应）----------

_SCENE_META = [
    {"key": "scene_01_verification",        "name": "🔍 验证事实",      "description": "确认某个功能/API是否真实存在，防止AI编造"},
    {"key": "scene_02_comparison",          "name": "⚖️ 多方案对比",    "description": "对比多个方案优劣，辅助技术选型决策"},
    {"key": "scene_03_step_execution",      "name": "🏗️ 分步执行",      "description": "复杂任务拆步执行，每步验证后再继续"},
    {"key": "scene_04_library_integration", "name": "📦 第三方库集成",  "description": "集成不熟悉的库，要求给出处和最小示例"},
    {"key": "scene_05_bug_analysis",        "name": "🐛 Bug 排查",      "description": "报错/异常排查，结构化列出原因和验证方法"},
    {"key": "scene_06_rule_optimization",   "name": "📊 规则调优",      "description": "基于 Badcase 数据迭代优化规则/策略"},
    {"key": "scene_07_code_review",         "name": "✏️ 代码 Review",   "description": "AI改完代码后强制输出结构化改动说明"},
    {"key": "scene_08_learning_explain",    "name": "🎓 学习解释",      "description": "读不懂的概念/代码，用类比+例子降维解释"},
    {"key": "scene_09_writing_doc",         "name": "📝 文档写作",      "description": "写 README、周报、会议纪要等结构化文档"},
    {"key": "scene_10_code_reading",        "name": "🔍 代码解读",      "description": "深度理解项目架构或某段复杂逻辑"},
    {"key": "scene_11_data_analysis",       "name": "📈 数据分析",      "description": "从原始数据到结论的完整分析链路"},
    {"key": "scene_12_question_refine",     "name": "❓ 提问优化",      "description": "模糊想法转为精确 Prompt，补充缺失信息"},
    {"key": "scene_13_migration",           "name": "🔄 迁移转换",      "description": "代码/框架/数据库迁移，关注语义等价和陷阱"},
    {"key": "scene_14_test_case",           "name": "🧪 测试用例设计",  "description": "多维度覆盖：正常/异常/边界/安全场景"},
    {"key": "scene_15_api_debug",           "name": "🌐 接口调试",      "description": "接口联调排查，逐层链路定位问题"},
    {"key": "scene_16_script_writing",      "name": "⌨️ 脚本编写",      "description": "生产级脚本：幂等+错误处理+日志+清理"},
    {"key": "scene_17_incident_report",     "name": "🐛 Bug 报告",      "description": "整理成完整 Bug 报告/Jira/复盘文档"},
    {"key": "scene_18_rule_modification",   "name": "✅ 按规则修改",    "description": "按明确规则改文件，改完强制逐条复核"},
    {"key": "scene_19_precheck",            "name": "🧐 使用前自检",    "description": "提问前三问+答后三检，防止被 AI 误导"},
    {"key": "scene_20_learning",            "name": "🎓 系统化学习",    "description": "概念→例子→边界→资源，防止假学习"},
    {"key": "scene_21_data_analysis_collab","name": "📊 数据分析协作",  "description": "先观察再给数据，防 Token 黑洞的协作协议"},
]

# 所有可用 system prompt：技术策略 + 场景策略
_ALL_SYSTEM_PROMPTS: dict[str, str] = {**_STRATEGY_SYSTEM_PROMPTS, **_SCENE_SYSTEM_PROMPTS}

# ---------- 00-router.md 决策树内容（用于 /recommend 接口） ----------
_ROUTER_MD_PATH = Path("/Users/heytea/ai-configs/shared/prompts/00-router.md")
_ROUTER_SYSTEM_PROMPT: str | None = None


def _get_router_system_prompt() -> str:
    global _ROUTER_SYSTEM_PROMPT
    if _ROUTER_SYSTEM_PROMPT is None:
        _ROUTER_SYSTEM_PROMPT = _ROUTER_MD_PATH.read_text(encoding="utf-8")
    return _ROUTER_SYSTEM_PROMPT


# ---------- 接口 ----------


@router.get("/strategies")
def list_strategies():
    """返回所有可用的优化策略，分两组：通用技术策略 + 场景模板"""
    return [
        {
            "group": "technique",
            "label": "通用技术策略",
            "items": [
                {"key": "auto",        "name": "🤖 帮我分析",   "description": "不知道选哪个？让 AI 自动判断最合适的优化方向"},
                {"key": "role",        "name": "🎭 专家口吻",   "description": "我想要像专家一样权威、专业的回答"},
                {"key": "cot",         "name": "🧠 逐步分析",   "description": "我需要 AI 一步步推理、展示思考过程"},
                {"key": "few_shot",    "name": "📋 符合格式",   "description": "我想要输出严格按照某个样式/示例来"},
                {"key": "constraint",  "name": "🔒 别乱发挥",   "description": "我不想让 AI 自由发挥，要严格按规则来"},
                {"key": "format",      "name": "📊 结构化输出", "description": "我需要表格、JSON、Markdown 等结构化格式"},
            ],
        },
        {
            "group": "scene",
            "label": "场景模板",
            "items": _SCENE_META,
        },
    ]


@router.post("/recommend", response_model=RecommendResponse)
async def recommend_strategy(body: RecommendRequest):
    """
    根据用户输入的原始提示词，用 00-router.md 决策树推荐 1-3 个最合适的场景 key。
    """
    import asyncio, re

    router_prompt = _get_router_system_prompt()
    system_content = router_prompt + """

## 你的输出任务
根据用户输入，从以下 21 个 key 中选出最匹配的 1-3 个（按匹配度排序）：
scene_01_verification, scene_02_comparison, scene_03_step_execution,
scene_04_library_integration, scene_05_bug_analysis, scene_06_rule_optimization,
scene_07_code_review, scene_08_learning_explain, scene_09_writing_doc,
scene_10_code_reading, scene_11_data_analysis, scene_12_question_refine,
scene_13_migration, scene_14_test_case, scene_15_api_debug,
scene_16_script_writing, scene_17_incident_report, scene_18_rule_modification,
scene_19_precheck, scene_20_learning, scene_21_data_analysis_collab

严格按以下 JSON 格式输出，不要有其他内容：
{"recommended_keys": ["scene_xx_yyy", ...], "reason": "一句话说明推荐理由"}
"""
    loop = asyncio.get_event_loop()

    def _do_invoke():
        try:
            from llmesh import get_llm
            from langchain_core.messages import HumanMessage, SystemMessage
        except ImportError as e:
            return {"recommended_keys": [], "reason": ""}

        try:
            llm = get_llm(thinking=False)
            result = llm.invoke(
                [
                    SystemMessage(content=system_content),
                    HumanMessage(content=body.raw_prompt),
                ]
            )
            raw = (result.content or "").strip()

            # 提取 JSON（去掉可能的前后文本）
            match = re.search(
                r'\{[^{}]*"recommended_keys"[^{}]*\}',
                raw,
                re.DOTALL,
            )
            if not match:
                return {"recommended_keys": [], "reason": ""}

            data = json.loads(match.group())
            keys = data.get("recommended_keys", [])
            reason = data.get("reason", "")

            # 只保留有效的 scene key
            valid_keys = [k for k in keys if k.startswith("scene_")]
            return {"recommended_keys": valid_keys[:3], "reason": reason}

        except Exception:
            return {"recommended_keys": [], "reason": ""}

    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _do_invoke),
            timeout=15,
        )
    except asyncio.TimeoutError:
        result = {"recommended_keys": [], "reason": ""}

    return RecommendResponse(**result)


@router.get("/models", response_model=List[AvailableModel])
def list_optimizer_models(session: Session = Depends(get_session)):
    """返回适合用于提示词优化任务的模型列表（排除纯思考模型、视觉模型及 _DEFAULT_EXCLUDE_TAGS 中的特殊用途模型）"""
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
        # 判断 thinking_mode
        thinking_mode = m.thinking_mode
        if not thinking_mode:
            if m.supports_thinking and m.is_thinking_only:
                thinking_mode = "always"
            elif m.supports_thinking:
                thinking_mode = "optional"
            else:
                thinking_mode = "none"

        # 过滤：纯思考模型（always）直接排除
        if thinking_mode == "always":
            continue

        # 过滤：视觉模型直接排除
        caps: List[str] = []
        if m.capabilities:
            try:
                caps = json.loads(m.capabilities)
            except Exception:
                pass
        if "vision" in caps or m.is_vision:
            continue

        g = group_map[m.group_id]
        tags: List[str] = []
        if m.tags:
            try:
                tags = json.loads(m.tags)
            except Exception:
                pass

        # 过滤：与 get_llm() 默认排除保持一致（_DEFAULT_EXCLUDE_TAGS）
        if set(_DEFAULT_EXCLUDE_TAGS).intersection(tags):
            continue
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


@router.post("/optimize", response_model=OptimizeResponse)
async def optimize_prompt(
    body: OptimizeRequest,
    session: Session = Depends(get_session),
):
    """
    核心接口：将用户的人话提示词优化为结构化 Prompt。
    通过 LLM 路由池调用，支持自动选模型或手动指定。
    """
    # 获取全局配置
    gs = session.exec(select(GlobalSettings)).first() or GlobalSettings()

    # 构造给 LLM 的完整输入
    user_content = f"## 用户原始提示词\n{body.raw_prompt}"

    if body.context:
        user_content += f"\n\n## 补充上下文\n{body.context}"

    if body.output_format:
        user_content += f"\n\n## 期望输出格式\n{body.output_format}"

    strategy_key = (
        body.strategy if body.strategy in _ALL_SYSTEM_PROMPTS else "auto"
    )
    system_prompt = _ALL_SYSTEM_PROMPTS[strategy_key]

    # 调用 LLM
    import asyncio

    loop = asyncio.get_event_loop()

    def _do_invoke():
        vendor = "路由池"
        model_name = "自动选择"
        try:
            from llmesh import get_llm
            from langchain_core.messages import HumanMessage, SystemMessage
        except ImportError as e:
            raise HTTPException(status_code=500, detail=f"缺少依赖：{e}")

        try:
            # 如果指定了模型，直接用该模型
            if body.model_ref:
                g = session.get(ProviderGroup, body.model_ref.group_id)
                e = session.get(ModelEntry, body.model_ref.model_id)
                if not g or not e:
                    raise HTTPException(status_code=404, detail="指定的模型不存在")
                from backend.utils.llm_invoke import build_chat_llm

                llm = build_chat_llm(g, e, gs, thinking=False, streaming=True)
                vendor = g.vendor
                model_name = e.model
            else:
                # 使用路由池自动选择
                llm = get_llm(thinking=False)

            t0 = time.time()
            result = llm.invoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_content),
                ]
            )
            latency_ms = int((time.time() - t0) * 1000)

            # 读取 token 统计
            usage = result.usage_metadata or {}
            tokens_input = usage.get("input_tokens")
            tokens_output = usage.get("output_tokens")

            raw = (result.content or "").strip()

            # 获取模型信息：优先从 last_model 获取（路由池模式）
            if not body.model_ref:
                vendor_model = llm.last_model
                if vendor_model and "/" in vendor_model:
                    parts = vendor_model.split("/", 1)
                    vendor = parts[0]
                    model_name = parts[1]
                else:
                    vendor = "路由池"
                    model_name = "自动选择"

            return raw, vendor, model_name, latency_ms, tokens_input, tokens_output

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"LLM 调用失败：{str(e)[:300]}")

    (
        raw_output,
        vendor,
        model_name,
        latency_ms,
        tokens_input,
        tokens_output,
    ) = await loop.run_in_executor(None, _do_invoke)

    # 解析输出：优化后的 Prompt 和优化说明
    # LLM 输出格式：优化后的 Prompt \n\n### 优化说明\n...
    optimized_prompt = raw_output
    tips = []

    # 尝试分离优化说明
    separator_patterns = ["\n\n### 优化说明", "\n\n## 优化说明", "\n\n优化说明"]
    for sep in separator_patterns:
        if sep in raw_output:
            parts = raw_output.split(sep, 1)
            optimized_prompt = parts[0].strip()
            tip_text = parts[1].strip()
            # 提取要点（以 - 或 • 开头的行）
            import re

            tip_lines = re.findall(r"^[-•]\s*(.+)$", tip_text, re.MULTILINE)
            if tip_lines:
                tips = [line.strip() for line in tip_lines if line.strip()]
            else:
                # 如果没有列表格式，整段作为一条建议
                if tip_text:
                    tips = [tip_text[:200]]
            break

    # 去掉可能包裹的代码块
    if optimized_prompt.startswith("```"):
        lines = optimized_prompt.split("\n")
        # 去掉第一行的 ```xxx 和最后一行的 ```
        lines = [l for l in lines if not l.strip().startswith("```")]
        optimized_prompt = "\n".join(lines).strip()

    # 去掉 LLM 可能自行添加的开头标题行
    # 例如：### 优化后的 Prompt、## 优化结果、**优化后的 Prompt** 等
    import re as _re
    optimized_prompt = _re.sub(
        r'^#{1,4}\s*(优化后的\s*Prompt|优化结果|优化后的提示词)[^\n]*\n+',
        '',
        optimized_prompt,
        flags=_re.IGNORECASE,
    ).strip()
    # 去掉加粗形式的标题（**优化后的 Prompt**\n）
    optimized_prompt = _re.sub(
        r'^\*{1,2}(优化后的\s*Prompt|优化结果|优化后的提示词)\*{1,2}\s*\n+',
        '',
        optimized_prompt,
    ).strip()

    return OptimizeResponse(
        raw_prompt=body.raw_prompt,
        optimized_prompt=optimized_prompt,
        strategy_used=strategy_key,
        tips=tips,
        model_vendor=vendor,
        model_name=model_name,
        latency_ms=latency_ms,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
    )


# ---------- 对比测试 ----------


@router.post("/compare-test", response_model=CompareTestResponse)
async def compare_test(
    body: CompareTestRequest,
    session: Session = Depends(get_session),
):
    """
    对比测试：用同一个模型分别跑原始 prompt 和优化后的 prompt，
    返回两个结果供用户对比。
    """
    import asyncio

    loop = asyncio.get_event_loop()

    g = session.get(ProviderGroup, body.test_model.group_id)
    e = session.get(ModelEntry, body.test_model.model_id)
    if not g or not e:
        raise HTTPException(status_code=404, detail="指定的模型不存在")

    gs = session.exec(select(GlobalSettings)).first() or GlobalSettings()

    def _run_prompt(prompt: str, prompt_type: str) -> CompareTestResult:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from backend.utils.llm_invoke import build_chat_llm
        except ImportError as err:
            return CompareTestResult(
                prompt_type=prompt_type,
                reply="",
                latency_ms=0,
                ok=False,
                error=f"缺少依赖：{err}",
            )
        try:
            llm = build_chat_llm(g, e, gs, thinking=False, streaming=True)
            t0 = time.time()
            system_msg = SystemMessage(
                content=(
                    "你是一个智能助手，请认真回答用户的问题。"
                    "如果你知道自己的模型名称和知识截止日期，可以在回答末尾用 "
                    "[ID: 模型名，知识截止到 XXXX-XX] 格式注明，不强制要求。"
                )
            )
            result = llm.invoke([system_msg, HumanMessage(content=prompt)])
            latency_ms = int((time.time() - t0) * 1000)
            return CompareTestResult(
                prompt_type=prompt_type,
                reply=(result.content or "").strip(),
                latency_ms=latency_ms,
                ok=True,
            )
        except Exception as err:
            return CompareTestResult(
                prompt_type=prompt_type,
                reply="",
                latency_ms=0,
                ok=False,
                error=str(err)[:300],
            )

    def _do_both():
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_raw = pool.submit(_run_prompt, body.raw_prompt, "raw")
            fut_opt = pool.submit(_run_prompt, body.optimized_prompt, "optimized")
            return fut_raw.result(), fut_opt.result()

    raw_result, optimized_result = await loop.run_in_executor(None, _do_both)

    return CompareTestResponse(
        raw_prompt=body.raw_prompt,
        optimized_prompt=body.optimized_prompt,
        test_model_vendor=g.vendor,
        test_model_name=e.model,
        raw_result=raw_result,
        optimized_result=optimized_result,
    )


@router.post("/ask", response_model=AskResponse)
async def ask_with_optimized(
    body: AskRequest,
    session: Session = Depends(get_session),
):
    """
    直接提问：只用优化后的提示词调用一次模型，不做对比。
    """
    import asyncio

    loop = asyncio.get_event_loop()

    g = session.get(ProviderGroup, body.test_model.group_id)
    e = session.get(ModelEntry, body.test_model.model_id)
    if not g or not e:
        raise HTTPException(status_code=404, detail="指定的模型不存在")

    gs = session.exec(select(GlobalSettings)).first() or GlobalSettings()

    def _do_ask():
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from backend.utils.llm_invoke import build_chat_llm
        except ImportError as err:
            return None, 0, False, f"缺少依赖：{err}"
        try:
            llm = build_chat_llm(g, e, gs, thinking=False, streaming=True)
            system_msg = SystemMessage(
                content=(
                    "你是一个智能助手，请认真回答用户的问题。"
                    "如果你知道自己的模型名称和知识截止日期，可以在回答末尾用 "
                    "[ID: 模型名，知识截止到 XXXX-XX] 格式注明，不强制要求。"
                )
            )
            t0 = time.time()
            result = llm.invoke([system_msg, HumanMessage(content=body.optimized_prompt)])
            latency_ms = int((time.time() - t0) * 1000)
            return (result.content or "").strip(), latency_ms, True, None
        except Exception as err:
            return "", 0, False, str(err)[:300]

    reply, latency_ms, ok, error = await loop.run_in_executor(None, _do_ask)

    return AskResponse(
        optimized_prompt=body.optimized_prompt,
        test_model_vendor=g.vendor,
        test_model_name=e.model,
        reply=reply or "",
        latency_ms=latency_ms,
        ok=ok,
        error=error,
    )


@router.post("/multi-model-compare", response_model=MultiModelCompareResponse)
async def multi_model_compare(
    body: MultiModelCompareRequest,
    session: Session = Depends(get_session),
):
    """
    多模型对比：用同一条优化后的提示词并发调用多个模型，结果一起返回。
    最多支持 6 个模型同时对比。
    """
    import asyncio

    loop = asyncio.get_event_loop()
    gs = session.exec(select(GlobalSettings)).first() or GlobalSettings()

    # 预先查询所有模型，避免在线程中访问 session
    model_infos = []
    for ref in body.test_models:
        g = session.get(ProviderGroup, ref.group_id)
        e = session.get(ModelEntry, ref.model_id)
        if not g or not e:
            raise HTTPException(status_code=404, detail=f"模型 {ref.group_id}-{ref.model_id} 不存在")
        model_infos.append((ref, g, e))

    def _run_one(ref: ModelRef, g: ProviderGroup, e: ModelEntry) -> MultiModelCompareItem:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from backend.utils.llm_invoke import build_chat_llm
        except ImportError as err:
            return MultiModelCompareItem(
                group_id=ref.group_id, model_id=ref.model_id,
                vendor=g.vendor, model_name=e.model,
                reply="", latency_ms=0, ok=False, error=f"缺少依赖：{err}",
            )
        try:
            llm = build_chat_llm(g, e, gs, thinking=False, streaming=True)
            system_msg = SystemMessage(
                content=(
                    "你是一个智能助手，请认真回答用户的问题。"
                    "如果你知道自己的模型名称和知识截止日期，可以在回答末尾用 "
                    "[ID: 模型名，知识截止到 XXXX-XX] 格式注明，不强制要求。"
                )
            )
            t0 = time.time()
            result = llm.invoke([system_msg, HumanMessage(content=body.optimized_prompt)])
            latency_ms = int((time.time() - t0) * 1000)
            return MultiModelCompareItem(
                group_id=ref.group_id, model_id=ref.model_id,
                vendor=g.vendor, model_name=e.model,
                reply=(result.content or "").strip(),
                latency_ms=latency_ms, ok=True,
            )
        except Exception as err:
            return MultiModelCompareItem(
                group_id=ref.group_id, model_id=ref.model_id,
                vendor=g.vendor, model_name=e.model,
                reply="", latency_ms=0, ok=False, error=str(err)[:300],
            )

    def _do_all():
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=len(model_infos)) as pool:
            futures = [pool.submit(_run_one, ref, g, e) for ref, g, e in model_infos]
            return [f.result() for f in futures]

    results = await loop.run_in_executor(None, _do_all)

    return MultiModelCompareResponse(
        optimized_prompt=body.optimized_prompt,
        results=results,
    )
