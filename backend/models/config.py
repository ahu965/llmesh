"""
数据模型：厂商组（ProviderGroup）+ 模型条目（ModelEntry）+ 全局配置（GlobalSettings）
短期：配置管理模式，数据持久化到加密 SQLite
长期：网关模式，可无缝切换 PostgreSQL
"""
from typing import Optional, Dict, Any, List
from sqlmodel import SQLModel, Field, JSON, Column
import json


class GlobalSettings(SQLModel, table=True):
    """全局参数，整张表只有一行（id=1）"""
    id: Optional[int] = Field(default=1, primary_key=True)
    temperature: float = Field(default=0.1)
    max_tokens: int = Field(default=4000)
    max_retries: int = Field(default=0)
    fault_duration: int = Field(default=60)
    default_timeout: int = Field(default=60)
    timeout_retries: int = Field(default=2)
    timeout_step: int = Field(default=10)
    rate_limit_cooldown: int = Field(default=60)


class ProviderGroup(SQLModel, table=True):
    """
    厂商分组：同一厂商可有多个分组（不同 api_key 或不同用途）
    对应 secrets.py 里的 MODEL_POOL_RAW 每个顶层 dict
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    vendor: str = Field(index=True)
    api_key: str
    base_url: str
    weight: int = Field(default=1)           # 组级默认权重（model 级可覆盖）
    timeout: int = Field(default=60)          # 组级默认超时
    remark: Optional[str] = Field(default=None)
    enabled: bool = Field(default=True)
    # 扩展字段（长期：付费模式、过期时间等）
    billing_mode: Optional[str] = Field(default=None)   # "free" / "prepaid" / "postpaid"
    expires_at: Optional[str] = Field(default=None)      # ISO 日期字符串，None=永不过期


class ModelEntry(SQLModel, table=True):
    """
    单个模型条目，从属于某个 ProviderGroup
    对应 secrets.py 里 models 数组中的每一项（字符串或 dict）
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="providergroup.id", index=True)
    model: str
    weight: Optional[int] = Field(default=None)    # None = 继承 group.weight
    timeout: Optional[int] = Field(default=None)   # None = 继承 group.timeout
    remark: Optional[str] = Field(default=None)
    supports_thinking: bool = Field(default=False)
    is_thinking_only: bool = Field(default=False)
    extra_body: Optional[str] = Field(default=None)  # JSON 字符串存储
    enabled: bool = Field(default=True)

    def get_extra_body(self) -> Optional[Dict[str, Any]]:
        if self.extra_body:
            return json.loads(self.extra_body)
        return None

    def set_extra_body(self, data: Optional[Dict[str, Any]]):
        self.extra_body = json.dumps(data, ensure_ascii=False) if data else None
