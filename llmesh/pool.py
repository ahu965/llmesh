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
                    streaming=True,   # 兼容仅支持流式的模型（如 qwen3 开启 thinking 时）
                )
                extra_body = dict(model_config.get("extra_body") or {})
                if thinking is True and model_config.get("supports_thinking"):
                    # thinking=True：只对支持思考的模型开启
                    extra_body["enable_thinking"] = True
                elif thinking is False:
                    # thinking=False：无条件写入，确保默认开启思考的模型也能被关闭
                    extra_body["enable_thinking"] = False
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
        vision: Optional[bool] = None,
        tags: Optional[List[str]] = None,
        exclude_tags: Optional[List[str]] = None,
    ) -> Optional[Dict]:
        """
        多阶段选模型：
        1. thinking/vision 硬过滤
        2. exclude_tags 硬排除：命中任意 tag 的模型直接剔除
        3. priority 分层（先取 priority 最小层，该层全 skip 后降级）
        4. prefer / tags 软偏好（命中则在该子集内权重随机，否则 fallback 全量当前层）
        thinking 不为 None 时只从 supports_thinking=True 的模型里选，不 fallback。
        thinking=False 时额外排除 is_thinking_only=True 的模型。
        vision=True 时只从 is_vision=True 的模型里选；未传时排除 is_vision=True 的模型。
        tags 传入时优先从命中任意 tag 的模型里选，全不可用时 fallback 当前优先级层。
        exclude_tags 传入时硬性剔除命中任意 tag 的模型。
        """
        with self._lock:
            pool = list(self._model_pool)

        available = [m for m in pool if self._is_model_available(m, skip_keys)]
        if not available:
            return None

        # --- thinking 硬过滤 ---
        # thinking=True：只保留支持思考模式的模型
        if thinking is True:
            available = [m for m in available if m.get("supports_thinking")]
            if not available:
                return None
        # thinking=False：排除纯思考模型（is_thinking_only=True），其余模型均可用
        if thinking is False:
            available = [m for m in available if not m.get("is_thinking_only")]
            if not available:
                return None

        # --- vision 硬过滤 ---
        if vision is True:
            available = [m for m in available if m.get("is_vision")]
            if not available:
                return None
        else:
            available = [m for m in available if not m.get("is_vision")]
            if not available:
                return None

        # --- exclude_tags 硬排除 ---
        if exclude_tags:
            available = [
                m for m in available
                if not any(t in (m.get("tags") or []) for t in exclude_tags)
            ]
            if not available:
                return None

        # --- priority 分层：从最小优先级层开始，逐层降级 ---
        priorities = sorted({m.get("priority", 0) for m in available})

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

        for pri in priorities:
            layer = [m for m in available if m.get("priority", 0) == pri]
            if not layer:
                continue

            # prefer 软偏好（仅在当前层内生效）
            if prefer:
                keywords = [p.lower() for p in prefer]
                preferred = [
                    m for m in layer
                    if any(k in m["vendor"].lower() or k in m["model"].lower() for k in keywords)
                ]
                if preferred:
                    return _pick(preferred)
                logger.debug(f"prefer {prefer} 在 priority={pri} 层无匹配，尝试 tags / 全层")

            # tags 软偏好（仅在当前层内生效）
            if tags:
                tagged = [
                    m for m in layer
                    if any(t in (m.get("tags") or []) for t in tags)
                ]
                if tagged:
                    return _pick(tagged)
                logger.debug(f"tags {tags} 在 priority={pri} 层无匹配，fallback 全层")

            result = _pick(layer)
            if result:
                return result

        return None

    # ==================== pinned 模型查找 ====================

    def _find_model_config(self, vendor_model: str) -> Optional[Dict]:
        """按 'vendor/model' 从池中找到对应配置，找不到返回 None。"""
        with self._lock:
            pool = list(self._model_pool)
        for m in pool:
            if f"{m['vendor']}/{m['model']}" == vendor_model:
                return m
        return None

    # ==================== 核心 invoke ====================

    def invoke(
        self,
        messages: Any,
        temperature: Optional[float] = None,
        prefer: Union[str, List[str], None] = None,
        thinking: Optional[bool] = None,
        vision: Optional[bool] = None,
        tags: Union[str, List[str], None] = None,
        exclude_tags: Union[str, List[str], None] = None,
        exclude_models: Union[Set[str], None] = None,
        pinned: Union[List[str], None] = None,
        task_group: Optional[str] = None,
    ) -> Any:
        """
        带完整容错的同步 invoke。

        Args:
            messages:      LangChain 消息列表或字符串
            temperature:   覆盖全局默认温度，None 使用 secrets.py 中的值
            prefer:        优先厂商/模型关键字（str 或 list），不可用时自动 fallback 全量池
            thinking:      True=开启，False=关闭，None=沿用 secrets.py extra_body 默认值
            vision:        True=只选视觉模型；None/False=排除视觉模型（默认行为）
            tags:          场景软标签（str 或 list），优先选命中 tag 的模型，全不可用时 fallback
            exclude_tags:  硬排除标签（str 或 list），命中任意 tag 的模型被强制剔除
            exclude_models: 本次调用直接跳过的模型 key 集合（"vendor_model" 格式）
            pinned:        固定候选列表（"vendor/model" 格式，按序尝试），全部失败后
                           fallback 到全量池选模型逻辑
            task_group:    任务组名称（secrets.py 中 TASK_GROUPS 定义），
                           自动展开为对应的 pinned/exclude_tags/tags/thinking，
                           与显式参数合并（显式参数优先）

        Returns:
            LangChain AIMessage，附带 ._model_name 属性记录实际使用的模型

        Raises:
            RuntimeError: 所有模型均不可用
        """
        # ---------- task_group 展开（显式参数优先覆盖） ----------
        if task_group:
            from llmesh.config import get_task_group
            tg = get_task_group(task_group)
            if tg is None:
                logger.warning(f"[task_group] '{task_group}' 不存在于 TASK_GROUPS，忽略")
            else:
                if pinned is None and tg.get("pinned"):
                    pinned = tg["pinned"]
                if exclude_tags is None and tg.get("exclude_tags"):
                    exclude_tags = tg["exclude_tags"]
                if tags is None and tg.get("tags"):
                    tags = tg["tags"]
                if prefer is None and tg.get("prefer"):
                    prefer = tg["prefer"]
                if thinking is None and tg.get("thinking") is not None:
                    thinking = tg["thinking"]
                logger.debug(f"[task_group] '{task_group}' 展开：pinned={pinned}, "
                             f"prefer={prefer}, exclude_tags={exclude_tags}, "
                             f"tags={tags}, thinking={thinking}")

        temp = temperature if temperature is not None else self._default_temperature
        prefer_list: List[str] = (
            [prefer] if isinstance(prefer, str) else list(prefer) if prefer else []
        )
        tags_list: List[str] = (
            [tags] if isinstance(tags, str) else list(tags) if tags else []
        )
        exclude_tags_list: List[str] = (
            [exclude_tags] if isinstance(exclude_tags, str) else list(exclude_tags) if exclude_tags else []
        )
        skip_keys: Set[str] = set(exclude_models) if exclude_models else set()

        # ---------- pinned 阶段：按序尝试固定候选列表 ----------
        if pinned:
            pinned_exhausted: Set[str] = set()
            for vm in pinned:
                model_key = vm.replace("/", "_", 1)
                if model_key in skip_keys:
                    pinned_exhausted.add(model_key)
                    continue
                model_config = self._find_model_config(vm)
                if not model_config:
                    logger.warning(f"[pinned] {vm} 不在模型池中，跳过")
                    pinned_exhausted.add(model_key)
                    continue
                if not self._is_model_available(model_config, skip_keys):
                    pinned_exhausted.add(model_key)
                    continue

                vendor_model = vm
                if thinking is True and model_config.get("thinking_timeout"):
                    base_timeout = model_config["thinking_timeout"]
                elif model_config.get("is_thinking_only") and model_config.get("thinking_timeout"):
                    base_timeout = model_config["thinking_timeout"]
                else:
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
                        logger.info(f"✅ [pinned:{vendor_model}] 成功，耗时 {latency:.2f}s")
                        try:
                            result._model_name = vendor_model
                        except Exception:
                            pass
                        return result

                    except APITimeoutError:
                        self._inc_stats(model_key, "timeout")
                        logger.warning(
                            f"⏱ [pinned:{vendor_model}] 超时（timeout={timeout}s，"
                            f"retry {retry + 1}/{self._timeout_retries}）"
                        )
                        if retry < self._timeout_retries - 1:
                            continue
                        self._open_circuit(model_key)
                        skip_keys.add(model_key)
                        pinned_exhausted.add(model_key)
                        break

                    except Exception as e:
                        if self._is_rate_limit_error(e):
                            self._inc_stats(model_key, "rate_limit")
                            skip_keys.add(model_key)
                            pinned_exhausted.add(model_key)
                            with self._lock:
                                self._rate_limit_penalty[model_key] = {"since": time.time()}
                            logger.warning(
                                f"⚡ [pinned:{vendor_model}] 限流，跳过 + 降权 {self._rate_limit_cooldown}s"
                            )
                            break

                        if isinstance(e, APIConnectionError):
                            self._inc_stats(model_key, "failure")
                            skip_keys.add(model_key)
                            pinned_exhausted.add(model_key)
                            logger.warning(f"🔌 [pinned:{vendor_model}] 连接失败：{e}")
                            break

                        self._inc_stats(model_key, "failure")
                        self._open_circuit(model_key)
                        skip_keys.add(model_key)
                        pinned_exhausted.add(model_key)
                        logger.error(f"❌ [pinned:{vendor_model}] 故障：{e}\n{traceback.format_exc()}")
                        break

            logger.warning(f"[pinned] 固定候选列表全部失败，fallback 全量池（已尝试：{pinned_exhausted}）")

        # ---------- 常规阶段（全量池选模型）----------
        while True:
            model_config = self._get_next_model(
                skip_keys=skip_keys,
                prefer=prefer_list,
                thinking=thinking,
                vision=vision,
                tags=tags_list or None,
                exclude_tags=exclude_tags_list or None,
            )
            if not model_config:
                break

            vendor_model = f"{model_config['vendor']}/{model_config['model']}"
            model_key    = f"{model_config['vendor']}_{model_config['model']}"
            # thinking 开启时优先使用 thinking_timeout，未设置则 fallback 到普通 timeout
            if thinking is True and model_config.get("thinking_timeout"):
                base_timeout = model_config["thinking_timeout"]
            elif model_config.get("is_thinking_only") and model_config.get("thinking_timeout"):
                base_timeout = model_config["thinking_timeout"]
            else:
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
        vision: Optional[bool] = None,
        tags: Union[str, List[str], None] = None,
        exclude_tags: Union[str, List[str], None] = None,
        exclude_models: Union[Set[str], None] = None,
        pinned: Union[List[str], None] = None,
        task_group: Optional[str] = None,
    ) -> "PooledLLM":
        temp = temperature if temperature is not None else self._default_temperature
        return PooledLLM(pool=self, temperature=temp, prefer=prefer, thinking=thinking,
                         vision=vision, tags=tags, exclude_tags=exclude_tags,
                         exclude_models=exclude_models, pinned=pinned, task_group=task_group)


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
        vision: Optional[bool] = None,
        tags: Union[str, List[str], None] = None,
        exclude_tags: Union[str, List[str], None] = None,
        exclude_models: Union[Set[str], None] = None,
        pinned: Union[List[str], None] = None,
        task_group: Optional[str] = None,
    ):
        self.pool = pool
        self.temperature = temperature
        self.prefer = prefer
        self.thinking = thinking
        self.vision = vision
        self.tags = tags
        self.exclude_tags = exclude_tags
        self.exclude_models: Set[str] = set(exclude_models) if exclude_models else set()
        self.pinned = pinned
        self.task_group = task_group
        self.last_model: Optional[str] = None  # invoke 后可读，记录实际使用的模型

    def invoke(self, messages: Any, **kwargs) -> Any:
        result = self.pool.invoke(
            messages,
            temperature=self.temperature,
            prefer=self.prefer,
            thinking=self.thinking,
            vision=self.vision,
            tags=self.tags,
            exclude_tags=self.exclude_tags,
            exclude_models=self.exclude_models if self.exclude_models else None,
            pinned=self.pinned,
            task_group=self.task_group,
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
    vision: Optional[bool] = None,
    tags: Union[str, List[str], None] = None,
    exclude_tags: Union[str, List[str], None] = None,
    exclude_models: Union[Set[str], None] = None,
    pinned: Union[List[str], None] = None,
    task_group: Optional[str] = None,
) -> PooledLLM:
    """
    全局入口，与原 hht_tools_config.llm.get_llm 接口完全兼容。

    配置来源：secrets.py（通过 LLMESH_SECRETS_PATH 指定，或放在项目根目录）

    task_group: 任务组名称，自动从 secrets.py 中的 TASK_GROUPS 展开为
                pinned/exclude_tags/tags/thinking 组合，显式参数优先。
    """
    return _get_pool().get_llm(temperature=temperature, prefer=prefer, thinking=thinking,
                               vision=vision, tags=tags, exclude_tags=exclude_tags,
                               exclude_models=exclude_models, pinned=pinned,
                               task_group=task_group)
