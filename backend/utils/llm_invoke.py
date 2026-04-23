"""
llm_invoke.py — 单模型调用工具

从 DB 对象（ProviderGroup + ModelEntry）构造 ChatOpenAI 实例，
统一处理 thinking 三态、extra_body、超时继承、max_tokens 等逻辑。

公开接口：
    build_chat_llm(group, entry, gs, *, thinking, streaming, max_tokens, timeout)
        -> ChatOpenAI

调用方只负责上层业务（流式输出、消息构造、tool calling 等），
不再各自重复构造 kwargs。
"""
from __future__ import annotations

from typing import Optional

from backend.models.config import GlobalSettings, ModelEntry, ProviderGroup


def build_chat_llm(
    group: ProviderGroup,
    entry: ModelEntry,
    gs: GlobalSettings,
    *,
    thinking: Optional[bool] = None,
    streaming: bool = True,
    max_tokens: Optional[int] = None,
    timeout: Optional[int] = None,
    temperature: Optional[float] = None,
    max_retries: int = 0,
):
    """
    从 DB 对象构造 ChatOpenAI，统一处理 thinking 三态和 extra_body。

    Args:
        group:       ProviderGroup DB 对象
        entry:       ModelEntry DB 对象
        gs:          GlobalSettings DB 对象（提供全局默认值）
        thinking:    True=开启, False=关闭, None=不注入（沿用 extra_body 原始值）
        streaming:   是否开启流式输出（tool calling 时应传 False）
        max_tokens:  覆盖值；None 时按 entry > gs 优先级继承
        timeout:     覆盖值；None 时按 entry > group > gs 优先级继承
        temperature: 覆盖值；None 时使用 gs.temperature
        max_retries: 最大重试次数，默认 0（探测/评测场景不需要重试）

    Returns:
        langchain_openai.ChatOpenAI 实例
    """
    from langchain_openai import ChatOpenAI

    # ---- 参数继承 ----
    effective_temperature = temperature if temperature is not None else gs.temperature
    effective_max_tokens  = max_tokens or entry.max_tokens or gs.max_tokens
    effective_timeout     = timeout or entry.timeout or group.timeout or gs.default_timeout

    # ---- thinking 三态处理 ----
    # 确定模型的 thinking_mode
    thinking_mode = entry.thinking_mode
    if not thinking_mode:
        if entry.supports_thinking and entry.is_thinking_only:
            thinking_mode = "always"
        elif entry.supports_thinking:
            thinking_mode = "optional"
        else:
            thinking_mode = "none"

    # 如果 thinking=True 且模型支持，使用 thinking_timeout
    if thinking is True and thinking_mode in ("optional", "always"):
        if entry.thinking_timeout:
            effective_timeout = entry.thinking_timeout
        elif gs.default_thinking_timeout:
            effective_timeout = gs.default_thinking_timeout

    extra_body = entry.get_extra_body() or {}

    if thinking is True and thinking_mode in ("optional", "always"):
        extra_body["enable_thinking"] = True
    elif thinking is False and thinking_mode != "always":
        # always 模型不能强制关闭 thinking
        extra_body["enable_thinking"] = False
    # thinking is None：不注入 enable_thinking，沿用 extra_body 原始值

    # ---- 构造 ChatOpenAI ----
    kwargs: dict = dict(
        model=entry.model,
        api_key=group.api_key,
        base_url=group.base_url,
        temperature=effective_temperature,
        max_tokens=effective_max_tokens,
        timeout=effective_timeout,
        max_retries=max_retries,
        streaming=streaming,
    )
    if extra_body:
        kwargs["extra_body"] = extra_body

    return ChatOpenAI(**kwargs)
