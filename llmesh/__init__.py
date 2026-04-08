"""
llmesh — 多厂商 LLM 路由 SDK

快速上手：
    from llmesh import get_llm

    llm = get_llm()                          # 按权重自动选模型
    llm = get_llm(prefer="openai")           # 优先 openai，不可用时自动 fallback 全量池
    llm = get_llm(thinking=True)             # 仅选支持思考模式的模型
    result = llm.invoke(messages)
    print(llm.last_model)                    # 实际使用的模型名

secrets.py 随包打包发布（编译为 .pyc），通过 llmesh 管理 UI 维护并导出。

与原 hht_tools_config 迁移对照：
    旧：from hht_tools_config.llm import get_llm
    新：from llmesh import get_llm
    接口完全一致，无需其他改动。
"""
from llmesh.pool import (
    get_llm,
    global_llm_pool,
    MultiVendorLLMPool,
    PooledLLM,
    ModelStats,
)

__all__ = [
    "get_llm",
    "global_llm_pool",
    "MultiVendorLLMPool",
    "PooledLLM",
    "ModelStats",
]

__version__ = "0.1.0"
