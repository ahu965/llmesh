"""
pool.py — 多厂商 LLM 模型池（路由引擎）

配置来源：llmesh.config（读取 secrets.py），与 hht_tools_config.llm.llm_pool 逻辑完全一致。
公开 API 兼容原接口：
    from llmesh import get_llm
    llm = get_llm(temperature=0.1, prefer="openai", thinking=None)
    result = llm.invoke(messages)
    print(llm.last_model)
"""
from __future__ import annotations

import random
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Union

from langchain_openai import ChatOpenAI
from openai import APIConnectionError, APITimeoutError, RateLimitError

from llmesh.logger import get_logger

logger = get_logger("llmesh.pool")

# ==================== 熔断状态常量 ====================
_STATE_CLOSED    = "closed"
_STATE_OPEN      = "open"
_STATE_HALF_OPEN = "half_open"


@dataclass
class ModelStats:
    """单模型调用统计"""
    success: int = 0
    failure: int = 0
    rate_limit: int = 0
    timeout: int = 0
    total_latency: float = 0.0

    @property
    def total_calls(self) -> int:
        return self.success + self.failure + self.rate_limit + self.timeout

    @property
    def avg_latency(self) -> float:
        return round(self.total_latency / self.success, 2) if self.success else 0.0

    @property
    def success_rate(self) -> str:
        if self.total_calls == 0:
            return "N/A"
        return f"{self.success / self.total_calls * 100:.1f}%"


class MultiVendorLLMPool:
    """
    多厂商 LLM 模型池（企业级）

    特性：
    - 权重优先选模型，相同权重加权随机打散
    - 限流(429)：本次跳过 + 动态降权（冷却期内权重归零，自动恢复）
    - 超时：递增超时重试，耗尽后换模型 + 熔断
    - 熔断：closed → open → half_open 单请求探测 → closed 恢复
    - LLM 实例按 (model_key, temperature, timeout, thinking) 缓存复用
    - thinking：True/False/None 三态，None 沿用 secrets.py 中 extra_body 默认值
    - 线程安全（RLock 防止锁嵌套死锁）
    """

    def __init__(self):
        from llmesh.config import (
            MODEL_POOL,
            DEFAULT_TEMPERATURE,
            DEFAULT_MAX_TOKENS,
            DEFAULT_MAX_RETRIES,
            FAULT_DURATION,
            TIMEOUT_RETRIES,
            TIMEOUT_STEP,
            RATE_LIMIT_COOLDOWN,
        )
        self._lock = threading.RLock()

        self._default_temperature: float = DEFAULT_TEMPERATURE
        self._default_max_tokens: int    = DEFAULT_MAX_TOKENS
        self._default_max_retries: int   = DEFAULT_MAX_RETRIES
        self._fault_duration: int        = FAULT_DURATION
        self._timeout_retries: int       = TIMEOUT_RETRIES
        self._timeout_step: int          = TIMEOUT_STEP
        self._rate_limit_cooldown: int   = RATE_LIMIT_COOLDOWN

        self._model_pool: List[Dict]            = list(MODEL_POOL)
        self._circuit: Dict[str, Dict]          = {}
        self._stats: Dict[str, ModelStats]      = {}
        self._llm_cache: Dict[tuple, ChatOpenAI] = {}
        self._rate_limit_penalty: Dict[str, Dict] = {}

    # ==================== 熔断管理 ====================

    def _get_circuit(self, model_key: str) -> Dict:
        with self._lock:
            if model_key not in self._circuit:
                self._circuit[model_key] = {
                    "state": _STATE_CLOSED, "since": 0.0, "probing": False,
                }
            return self._circuit[model_key]

    def _is_model_available(self, model: Dict, skip_keys: Set[str]) -> bool:
        key = f"{model['vendor']}_{model['model']}"
        if key in skip_keys:
            return False
        cb = self._get_circuit(key)
        state = cb["state"]
        if state == _STATE_CLOSED:
            return True
        if state == _STATE_OPEN:
            if time.time() - cb["since"] >= self._fault_duration:
                with self._lock:
                    cb["state"] = _STATE_HALF_OPEN
                return True
            return False
        if state == _STATE_HALF_OPEN:
            with self._lock:
                if cb["probing"]:
                    return False
                cb["probing"] = True
            return True
        return False

    def _open_circuit(self, model_key: str):
        with self._lock:
            cb = self._circuit.setdefault(model_key, {
                "state": _STATE_CLOSED, "since": 0.0, "probing": False,
            })
            cb["state"] = _STATE_OPEN
            cb["since"] = time.time()
            cb["probing"] = False
        logger.warning(f"熔断打开：{model_key}，屏蔽 {self._fault_duration}s")

    def _close_circuit(self, model_key: str):
        with self._lock:
            cb = self._circuit.get(model_key)
            if cb and cb["state"] != _STATE_CLOSED:
                cb["state"] = _STATE_CLOSED
                cb["probing"] = False
                logger.info(f"熔断关闭：{model_key} 恢复正常")

    # ==================== 统计 ====================

    def _get_stats(self, model_key: str) -> ModelStats:
        with self._lock:
            if model_key not in self._stats:
                self._stats[model_key] = ModelStats()
            return self._stats[model_key]

    def _inc_stats(self, model_key: str, field: str, latency: float = 0.0):
        stats = self._get_stats(model_key)
        with self._lock:
            setattr(stats, field, getattr(stats, field) + 1)
            if field == "success" and latency:
                stats.total_latency += latency

    def get_stats_report(self) -> Dict:
        with self._lock:
            return {
                k: {
                    "total": v.total_calls,
                    "success": v.success,
                    "failure": v.failure,
                    "rate_limit": v.rate_limit,
                    "timeout": v.timeout,
                    "success_rate": v.success_rate,
                    "avg_latency_s": v.avg_latency,
                }
                for k, v in self._stats.items()
            }

    # ==================== LLM 实例缓存 ====================

    def _get_llm(self, model_config: Dict, temperature: float, timeout: int,
                 thinking: Optional[bool] = None) -> ChatOpenAI:
        model_key = f"{model_config['vendor']}_{model_config['model']}"
        cache_key = (model_key, temperature, timeout, thinking)
        with self._lock:
            if cache_key not in self._llm_cache:
                kwargs: Dict = dict(
                    model=model_config["model"],
                    api_key=model_config["api_key"],
                    base_url=model_config["base_url"],
                    temperature=temperature,
                    max_tokens=self._default_max_tokens,
                    max_retries=self._default_max_retries,
                    timeout=timeout,
                )
                extra_body = dict(model_config.get("extra_body") or {})
                if thinking is not None and model_config.get("supports_thinking"):
                    extra_body["enable_thinking"] = thinking
                if extra_body:
                    kwargs["extra_body"] = extra_body
                self._llm_cache[cache_key] = ChatOpenAI(**kwargs)
        return self._llm_cache[cache_key]

    # ==================== 限流判断 ====================

    @staticmethod
    def _is_rate_limit_error(e: Exception) -> bool:
        if isinstance(e, RateLimitError):
            return True
        msg = str(e).lower()
        return "429" in msg or "rate limit" in msg or "too many requests" in msg

    # ==================== 模型选择 ====================

    def _get_effective_weight(self, model_key: str, original_weight: int) -> int:
        with self._lock:
            penalty = self._rate_limit_penalty.get(model_key)
            if penalty:
                if time.time() - penalty["since"] < self._rate_limit_cooldown:
                    return 0
                else:
                    del self._rate_limit_penalty[model_key]
        return original_weight

    def _get_next_model(
        self,
        skip_keys: Set[str],
        prefer: Optional[List[str]] = None,
        thinking: Optional[bool] = None,
    ) -> Optional[Dict]:
        """
        两阶段选模型：
        1. prefer 命中的候选集（vendor 或 model 名包含关键字）
        2. prefer 全不可用时 fallback 全量池
        thinking 不为 None 时只从 supports_thinking=True 的模型里选，不 fallback。
        thinking=False 时额外排除 is_thinking_only=True 的模型。
        """
        with self._lock:
            pool = list(self._model_pool)

        available = [m for m in pool if self._is_model_available(m, skip_keys)]
        if not available:
            return None

        if thinking is not None:
            available = [m for m in available if m.get("supports_thinking")]
            if not available:
                return None

        if thinking is False:
            available = [m for m in available if not m.get("is_thinking_only")]
            if not available:
                return None

        def _pick(candidates: List[Dict]) -> Optional[Dict]:
            weighted = [
                (m, self._get_effective_weight(f"{m['vendor']}_{m['model']}", m.get("weight", 1)))
                for m in candidates
            ]
            total = sum(w for _, w in weighted)
            if total > 0:
                r = random.uniform(0, total)
                cumulative = 0.0
                for m, w in weighted:
                    cumulative += w
                    if r <= cumulative:
                        return m
                return weighted[-1][0]
            else:
                logger.warning("所有可用模型均处于限流冷却期，随机兜底选择")
                return random.choice([m for m, _ in weighted])

        if prefer:
            keywords = [p.lower() for p in prefer]
            preferred = [
                m for m in available
                if any(k in m["vendor"].lower() or k in m["model"].lower() for k in keywords)
            ]
            if preferred:
                return _pick(preferred)
            logger.debug(f"prefer {prefer} 无可用模型，fallback 到全量池")

        return _pick(available)

    # ==================== 核心 invoke ====================

    def invoke(
        self,
        messages: Any,
        temperature: Optional[float] = None,
        prefer: Union[str, List[str], None] = None,
        thinking: Optional[bool] = None,
    ) -> Any:
        """
        带完整容错的同步 invoke。

        Args:
            messages:    LangChain 消息列表或字符串
            temperature: 覆盖全局默认温度，None 使用 secrets.py 中的值
            prefer:      优先厂商/模型关键字（str 或 list），不可用时自动 fallback 全量池
            thinking:    True=开启，False=关闭，None=沿用 secrets.py extra_body 默认值

        Returns:
            LangChain AIMessage，附带 ._model_name 属性记录实际使用的模型

        Raises:
            RuntimeError: 所有模型均不可用
        """
        temp = temperature if temperature is not None else self._default_temperature
        prefer_list: List[str] = (
            [prefer] if isinstance(prefer, str) else list(prefer) if prefer else []
        )
        skip_keys: Set[str] = set()

        while True:
            model_config = self._get_next_model(skip_keys=skip_keys, prefer=prefer_list, thinking=thinking)
            if not model_config:
                break

            vendor_model = f"{model_config['vendor']}/{model_config['model']}"
            model_key    = f"{model_config['vendor']}_{model_config['model']}"
            base_timeout = model_config.get("timeout", 20)

            for retry in range(self._timeout_retries):
                timeout = base_timeout + self._timeout_step * retry
                llm = self._get_llm(model_config, temp, timeout, thinking=thinking)
                t0 = time.time()
                try:
                    result = llm.invoke(messages)
                    latency = time.time() - t0
                    self._inc_stats(model_key, "success", latency)
                    self._close_circuit(model_key)
                    logger.info(f"✅ [{vendor_model}] 成功，耗时 {latency:.2f}s")
                    try:
                        result._model_name = vendor_model
                    except Exception:
                        pass
                    return result

                except APITimeoutError:
                    self._inc_stats(model_key, "timeout")
                    logger.warning(
                        f"⏱ [{vendor_model}] 超时（timeout={timeout}s，"
                        f"retry {retry + 1}/{self._timeout_retries}）"
                    )
                    if retry < self._timeout_retries - 1:
                        continue
                    self._open_circuit(model_key)
                    skip_keys.add(model_key)
                    break

                except Exception as e:
                    if self._is_rate_limit_error(e):
                        self._inc_stats(model_key, "rate_limit")
                        skip_keys.add(model_key)
                        with self._lock:
                            self._rate_limit_penalty[model_key] = {"since": time.time()}
                        logger.warning(
                            f"⚡ [{vendor_model}] 限流，本次跳过 + 降权 {self._rate_limit_cooldown}s"
                        )
                        break

                    if isinstance(e, APIConnectionError):
                        self._inc_stats(model_key, "failure")
                        skip_keys.add(model_key)
                        logger.warning(f"🔌 [{vendor_model}] 连接失败，换模型：{e}")
                        break

                    self._inc_stats(model_key, "failure")
                    self._open_circuit(model_key)
                    skip_keys.add(model_key)
                    logger.error(f"❌ [{vendor_model}] 故障：{e}\n{traceback.format_exc()}")
                    break

        raise RuntimeError(f"所有模型均不可用（已尝试：{skip_keys}）")

    def get_llm(
        self,
        temperature: Optional[float] = None,
        prefer: Union[str, List[str], None] = None,
        thinking: Optional[bool] = None,
    ) -> "PooledLLM":
        temp = temperature if temperature is not None else self._default_temperature
        return PooledLLM(pool=self, temperature=temp, prefer=prefer, thinking=thinking)


class PooledLLM:
    """
    LLM 代理对象，对外接口与 ChatOpenAI 一致（支持 .invoke）。
    实际委托给 MultiVendorLLMPool，享有全部容错能力。
    """

    def __init__(
        self,
        pool: MultiVendorLLMPool,
        temperature: float,
        prefer: Union[str, List[str], None] = None,
        thinking: Optional[bool] = None,
    ):
        self.pool = pool
        self.temperature = temperature
        self.prefer = prefer
        self.thinking = thinking
        self.last_model: Optional[str] = None  # invoke 后可读，记录实际使用的模型

    def invoke(self, messages: Any, **kwargs) -> Any:
        result = self.pool.invoke(
            messages,
            temperature=self.temperature,
            prefer=self.prefer,
            thinking=self.thinking,
        )
        self.last_model = getattr(result, "_model_name", None)
        return result


# ==================== 全局池（懒加载）====================

_global_pool: Optional[MultiVendorLLMPool] = None
_pool_lock = threading.Lock()


def _get_pool() -> MultiVendorLLMPool:
    global _global_pool
    if _global_pool is None:
        with _pool_lock:
            if _global_pool is None:
                _global_pool = MultiVendorLLMPool()
    return _global_pool


# 兼容旧用法：global_llm_pool.invoke(...) 等
class _PoolProxy:
    """代理对象，将属性/方法访问转发到懒加载的真实池实例"""
    def __getattr__(self, item):
        return getattr(_get_pool(), item)

    def __setattr__(self, key, value):
        if key.startswith("__"):
            object.__setattr__(self, key, value)
        else:
            setattr(_get_pool(), key, value)


global_llm_pool = _PoolProxy()


def get_llm(
    temperature: Optional[float] = None,
    prefer: Union[str, List[str], None] = None,
    thinking: Optional[bool] = None,
) -> PooledLLM:
    """
    全局入口，与原 hht_tools_config.llm.get_llm 接口完全兼容。

    配置来源：secrets.py（通过 LLMESH_SECRETS_PATH 指定，或放在项目根目录）
    """
    return _get_pool().get_llm(temperature=temperature, prefer=prefer, thinking=thinking)
