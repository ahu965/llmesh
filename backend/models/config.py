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
    default_thinking_timeout: Optional[int] = Field(default=None)  # 全局 thinking 超时，None=不单独设置
    timeout_retries: int = Field(default=2)
    timeout_step: int = Field(default=10)
    rate_limit_cooldown: int = Field(default=60)
    # 发布相关
    python_path: Optional[str] = Field(default=None)        # 打包用 Python 可执行文件路径
    pypi_url: Optional[str] = Field(default=None)           # 私有 PyPI 上传地址
    last_built_at: Optional[float] = Field(default=None)    # 上次发包时间戳（unix）
    db_updated_at: Optional[float] = Field(default=None)    # DB 最后变更时间戳（unix）


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
    # 扩展字段
    billing_mode: Optional[str] = Field(default=None)   # "free" / "prepaid" / "postpaid"
    expires_at: Optional[str] = Field(default=None)      # ISO 日期字符串，None=永不过期
    priority: int = Field(default=0)                      # 分层路由优先级，越小越优先
    alias: Optional[str] = Field(default=None)            # 分组别名，仅用于 UI 展示
    website: Optional[str] = Field(default=None)          # 厂商官网/控制台地址，用于 UI 快捷跳转


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
    expires_at: Optional[str] = Field(default=None)   # ISO 日期字符串，None=继承组的过期时间
    priority: Optional[int] = Field(default=None)     # 分层路由优先级，None=继承组的 priority
    is_vision: bool = Field(default=False)             # 视觉模型标记，硬过滤
    tags: Optional[str] = Field(default=None)          # JSON 数组字符串，如 '["cheap","fast"]'
    enabled: bool = Field(default=True)
    thinking_timeout: Optional[int] = Field(default=None)  # thinking 模式专用超时，None=不单独设置
    ai_profile: Optional[str] = Field(default=None)        # AI 生成的结构化模型档案（JSON 字符串）

    def get_extra_body(self) -> Optional[Dict[str, Any]]:
        if self.extra_body:
            return json.loads(self.extra_body)
        return None

    def set_extra_body(self, data: Optional[Dict[str, Any]]):
        self.extra_body = json.dumps(data, ensure_ascii=False) if data else None


class TaskGroup(SQLModel, table=True):
    """
    任务组：将一组固定候选模型 + 调用参数命名存储，调用方只需 task_group="名称" 即可。
    等价于把 pinned/exclude_tags/thinking 等一整套配置封装为一个具名预设。
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)         # 唯一标识，调用侧使用
    display_name: Optional[str] = Field(default=None)  # 可视化展示名
    pinned: Optional[str] = Field(default=None)        # JSON 数组，"vendor/model" 有序列表
    exclude_tags: Optional[str] = Field(default=None)  # JSON 数组
    tags: Optional[str] = Field(default=None)          # JSON 数组（软偏好标签）
    prefer: Optional[str] = Field(default=None)        # JSON 数组，vendor/model 关键字软偏好
    thinking: Optional[int] = Field(default=None)      # NULL=None, 0=False, 1=True
    remark: Optional[str] = Field(default=None)
    enabled: bool = Field(default=True)

    def get_pinned(self) -> List[str]:
        if self.pinned:
            try:
                return json.loads(self.pinned)
            except Exception:
                return []
        return []

    def get_exclude_tags(self) -> List[str]:
        if self.exclude_tags:
            try:
                return json.loads(self.exclude_tags)
            except Exception:
                return []
        return []

    def get_tags(self) -> List[str]:
        if self.tags:
            try:
                return json.loads(self.tags)
            except Exception:
                return []
        return []

    def get_prefer(self) -> List[str]:
        if self.prefer:
            try:
                return json.loads(self.prefer)
            except Exception:
                return []
        return []

    def get_thinking(self) -> Optional[bool]:
        if self.thinking is None:
            return None
        return bool(self.thinking)
