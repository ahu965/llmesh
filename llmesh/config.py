"""
config.py — 从 secrets.py 读取配置并构建运行时模型池。

secrets.py 随包一起打包发布（编译为 .pyc）。
使用方式与原 hht_tools_config 完全一致：
  from llmesh.config import MODEL_POOL, DEFAULT_TEMPERATURE, ...
"""
import logging
from typing import Any, Dict, List, Optional

from llmesh.secrets import GLOBAL_SETTINGS, MODEL_POOL_RAW  # noqa: F401

logger = logging.getLogger("llmesh.config")

# ====================== 全局参数 ======================
DEFAULT_TEMPERATURE: float = GLOBAL_SETTINGS["temperature"]
DEFAULT_MAX_TOKENS: int    = GLOBAL_SETTINGS["max_tokens"]
DEFAULT_MAX_RETRIES: int   = GLOBAL_SETTINGS["max_retries"]
FAULT_DURATION: int        = GLOBAL_SETTINGS["fault_duration"]
TIMEOUT_RETRIES: int       = GLOBAL_SETTINGS["timeout_retries"]
TIMEOUT_STEP: int          = GLOBAL_SETTINGS["timeout_step"]
RATE_LIMIT_COOLDOWN: int   = GLOBAL_SETTINGS["rate_limit_cooldown"]


# ====================== 构建运行时模型池 ======================
def _build_model_pool(pool_raw: Optional[List[Dict]] = None) -> List[Dict]:
    """
    构建运行时模型池。
    pool_raw: 指定原始数据时使用该数据（热重载场景）；不传则使用模块级 MODEL_POOL_RAW（初始化场景）。
    """
    source = pool_raw if pool_raw is not None else MODEL_POOL_RAW
    valid = []
    for group in source:
        if not all(group.get(k) for k in ["vendor", "api_key", "base_url", "models"]):
            logger.warning(f"忽略配置不完整的厂商分组：{group.get('vendor', '未知厂商')}")
            continue
        group_priority = group.get("priority", 0)
        for m in group["models"]:
            if isinstance(m, str):
                m = {"model": m}
            if not m.get("model"):
                logger.warning(f"忽略缺少 model 字段的条目：{group['vendor']}")
                continue

            # 解析 thinking_mode（新格式）+ 兼容旧布尔字段
            thinking_mode: str = m.get("thinking_mode", "")
            if not thinking_mode:
                # 旧格式兼容
                if m.get("supports_thinking") and m.get("is_thinking_only"):
                    thinking_mode = "always"
                elif m.get("supports_thinking"):
                    thinking_mode = "optional"
                else:
                    thinking_mode = "none"

            # 解析 capabilities（新格式）+ 兼容旧 is_vision
            caps: list = m.get("capabilities") or []
            if not caps:
                caps = ["text", "vision"] if m.get("is_vision") else ["text"]

            entry: Dict = {
                "vendor":        group["vendor"],
                "api_key":       group["api_key"],
                "base_url":      group["base_url"],
                "model":         m["model"],
                "weight":        m.get("weight",  group.get("weight",  1)),
                "timeout":       m.get("timeout", group.get("timeout", GLOBAL_SETTINGS["default_timeout"])),
                "priority":      m.get("priority", group_priority),
                "thinking_mode": thinking_mode,
                "capabilities":  caps,
                # 旧字段保留（pool.py 过渡期兼容，后续删除）
                "supports_thinking": thinking_mode in ("optional", "always"),
                "is_thinking_only":  thinking_mode == "always",
                "is_vision":         "vision" in caps,
            }
            if "remark" in m:
                entry["remark"] = m["remark"]
            if "tags" in m:
                entry["tags"] = list(m["tags"])
            elif "tags" in group:
                entry["tags"] = list(group["tags"])
            if "extra_body" in m:
                entry["extra_body"] = m["extra_body"]
            elif "extra_body" in group:
                entry["extra_body"] = group["extra_body"]
            if "thinking_timeout" in m:
                entry["thinking_timeout"] = m["thinking_timeout"]
            elif GLOBAL_SETTINGS.get("default_thinking_timeout") is not None:
                entry["thinking_timeout"] = GLOBAL_SETTINGS["default_thinking_timeout"]
            if "max_tokens" in m:
                entry["max_tokens"] = m["max_tokens"]
            valid.append(entry)

    if not valid:
        raise ValueError("模型池无有效配置，请检查 secrets.py 中的 MODEL_POOL_RAW")
    return valid


MODEL_POOL: List[Dict] = _build_model_pool()


# ====================== 任务组 ======================
def _build_task_groups() -> Dict[str, Dict[str, Any]]:
    """
    从 secrets.py 读取 TASK_GROUPS（可选），构建以 name 为 key 的字典。
    secrets.py 中未定义 TASK_GROUPS 时返回空字典，兼容旧版本。
    """
    try:
        from llmesh.secrets import TASK_GROUPS as _raw  # type: ignore
    except ImportError:
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    for tg in (_raw or []):
        name = tg.get("name", "").strip()
        if not name:
            continue
        # pinned：兼容字符串（旧格式）和 dict（新格式 {"vm": "vendor/model", "thinking": ...}）
        # 统一转为 dict 列表，pool.py 直接读取
        raw_pinned = tg.get("pinned") or []
        pinned_items = []
        for item in raw_pinned:
            if isinstance(item, str):
                pinned_items.append({"vm": item, "thinking": None})
            elif isinstance(item, dict):
                pinned_items.append({"vm": item.get("vm", ""), "thinking": item.get("thinking")})
        result[name] = {
            "display_name":  tg.get("display_name"),
            "pinned":        pinned_items,          # List[{"vm", "thinking"}]
            "exclude_tags":  list(tg.get("exclude_tags") or []),
            "tags":          list(tg.get("tags") or []),
            "prefer":        list(tg.get("prefer") or []),
            "thinking":      tg.get("thinking"),    # None / True / False
            "remark":        tg.get("remark"),
            "max_tokens":    tg.get("max_tokens"),  # None = 继承全局
        }
    return result


TASK_GROUPS: Dict[str, Dict[str, Any]] = _build_task_groups()


def get_task_group(name: str) -> Optional[Dict[str, Any]]:
    """按名称查找任务组配置，不存在返回 None。"""
    return TASK_GROUPS.get(name)
