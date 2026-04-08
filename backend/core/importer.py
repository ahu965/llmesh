"""
secrets.py 导入器
将现有 secrets.py 中的 MODEL_POOL_RAW 导入到数据库
用于首次迁移或从文件同步配置
"""
from typing import Any
from sqlmodel import Session, select
from backend.models.config import GlobalSettings, ProviderGroup, ModelEntry
import json


def import_secrets(session: Session, raw: dict) -> dict:
    """
    raw: 通过 exec(secrets.py 内容) 得到的命名空间 dict
    返回导入统计 {"groups": N, "models": M}
    """
    gs_data: dict = raw.get("GLOBAL_SETTINGS", {})
    gs = session.exec(select(GlobalSettings)).first()
    if not gs:
        gs = GlobalSettings()
    for k, v in gs_data.items():
        if hasattr(gs, k):
            setattr(gs, k, v)
    session.add(gs)

    pool_raw: list = raw.get("MODEL_POOL_RAW", [])
    group_count = 0
    model_count = 0

    for g in pool_raw:
        group = ProviderGroup(
            vendor=g["vendor"],
            api_key=g["api_key"],
            base_url=g["base_url"],
            weight=g.get("weight", 1),
            timeout=g.get("timeout", gs_data.get("default_timeout", 60)),
            remark=g.get("remark"),
        )
        session.add(group)
        session.flush()  # 获取 group.id
        group_count += 1

        for m in g.get("models", []):
            if isinstance(m, str):
                entry = ModelEntry(group_id=group.id, model=m)
            else:
                extra_body = m.get("extra_body")
                entry = ModelEntry(
                    group_id=group.id,
                    model=m["model"],
                    weight=m.get("weight"),
                    timeout=m.get("timeout"),
                    remark=m.get("remark"),
                    supports_thinking=m.get("supports_thinking", False),
                    is_thinking_only=m.get("is_thinking_only", False),
                    extra_body=json.dumps(extra_body, ensure_ascii=False) if extra_body else None,
                )
            session.add(entry)
            model_count += 1

    session.commit()
    return {"groups": group_count, "models": model_count}


def import_from_file(session: Session, file_path: str) -> dict:
    """从 secrets.py 文件路径导入"""
    ns: dict[str, Any] = {}
    with open(file_path, "r", encoding="utf-8") as f:
        exec(f.read(), ns)
    return import_secrets(session, ns)
