"""
pool_sync.py — 数据库 → llmesh 路由池热重载工具

当前项目（llmesh 管理端）直接用数据库作为模型池数据源，
每次配置变更后调用 reload_pool() 即可让 get_llm() 立刻感知，无需导出 secrets.py、无需重启。
"""
import logging
from sqlmodel import Session

from backend.core.exporter import build_pool_raw, build_global_settings

logger = logging.getLogger("backend.pool_sync")


def reload_pool(session: Session) -> None:
    """
    从数据库读取最新配置，热重载 llmesh 全局路由池。
    线程安全，可在任意请求处理后调用。
    """
    try:
        from llmesh.pool import global_llm_pool
        pool_raw = build_pool_raw(session)
        global_settings = build_global_settings(session)
        global_llm_pool.reload(pool_raw, global_settings)
    except Exception:
        logger.exception("[pool_sync] 热重载失败，当前池保持不变")
