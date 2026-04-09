"""
模型探测接口
对指定模型发送一条简单消息，验证其是否可用，返回延迟或错误原因。
不依赖 secrets.py，直接从数据库读取 api_key / base_url。
"""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from backend.database import get_session
from backend.models.config import ProviderGroup, ModelEntry

router = APIRouter(prefix="/api/probe", tags=["probe"])

PROBE_MESSAGE = "你好"
PROBE_TIMEOUT = 15  # 探测固定超时 15s，不走模型配置的超时


class ProbeRequest(BaseModel):
    group_id: int
    model_id: int


class ProbeResponse(BaseModel):
    ok: bool
    latency_ms: Optional[int] = None   # 成功时的耗时（毫秒）
    reply: Optional[str] = None        # 模型的简短回复（前 80 字）
    error: Optional[str] = None        # 失败时的错误摘要


@router.post("", response_model=ProbeResponse)
def probe_model(body: ProbeRequest, session: Session = Depends(get_session)):
    group = session.get(ProviderGroup, body.group_id)
    entry = session.get(ModelEntry, body.model_id)

    if not group or not entry or entry.group_id != body.group_id:
        raise HTTPException(status_code=404, detail="模型或厂商组不存在")

    if not entry.enabled or not group.enabled:
        return ProbeResponse(ok=False, error="模型或厂商组已禁用，跳过探测")

    # 动态引入，避免循环依赖
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"缺少依赖：{e}")

    extra_body = entry.get_extra_body() or {}
    # 思考模型探测时关闭 thinking，避免超时
    if entry.supports_thinking and "enable_thinking" not in extra_body:
        extra_body["enable_thinking"] = False

    try:
        kwargs: dict = dict(
            model=entry.model,
            api_key=group.api_key,
            base_url=group.base_url,
            temperature=0.1,
            max_tokens=64,
            timeout=PROBE_TIMEOUT,
            max_retries=0,
            streaming=True,  # 兼容仅支持流式的模型
        )
        if extra_body:
            kwargs["extra_body"] = extra_body
        llm = ChatOpenAI(**kwargs)
        t0 = time.time()
        chunks = []
        for chunk in llm.stream([HumanMessage(content=PROBE_MESSAGE)]):
            chunks.append(chunk.content or "")
            if sum(len(c) for c in chunks) >= 80:
                break
        latency_ms = int((time.time() - t0) * 1000)
        reply = "".join(chunks)[:80]
        return ProbeResponse(ok=True, latency_ms=latency_ms, reply=reply)

    except Exception as e:
        err = str(e)
        # 截取关键错误信息，避免返回超长堆栈
        summary = err.split("\n")[0][:200]
        return ProbeResponse(ok=False, error=summary)
