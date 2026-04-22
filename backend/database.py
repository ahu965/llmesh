"""
数据库连接管理
- 使用加密 SQLite（sqlcipher3），密钥从 .env 读取
- SQLCipher 密钥通过 connect_args 的 creator 注入 PRAGMA key，避免 URL 解析问题
- 长期可通过修改为 PostgreSQL URL 切换，上层代码无感知
"""
from pathlib import Path
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import event
from pydantic_settings import BaseSettings


_PROJECT_ROOT = Path(__file__).parent.parent


class Settings(BaseSettings):
    db_path: str = ""
    db_key: str = "llmesh_default_key"   # 加密密钥，生产环境务必通过 .env 覆盖

    class Config:
        env_file = str(_PROJECT_ROOT / ".env")
        extra = "ignore"


settings = Settings()

_DB_PATH = Path(settings.db_path) if settings.db_path else _PROJECT_ROOT / "data" / "llmesh.db"
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# 使用普通 sqlite:/// URL，密钥通过连接事件注入 PRAGMA key
_DATABASE_URL = f"sqlite:///{_DB_PATH.resolve()}"

engine = create_engine(
    _DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _connection_record):
    """每次新连接时注入 SQLCipher 加密密钥"""
    cursor = dbapi_conn.cursor()
    cursor.execute(f"PRAGMA key='{settings.db_key}'")
    cursor.close()


def _migrate_db():
    """对已存在的 SQLite 表执行增量列迁移（ALTER TABLE ADD COLUMN IF NOT EXISTS 模拟）"""
    new_columns = [
        ("globalsettings", "python_path",               "TEXT"),
        ("globalsettings", "pypi_url",                  "TEXT"),
        ("globalsettings", "last_built_at",             "REAL"),
        ("globalsettings", "db_updated_at",             "REAL"),
        ("globalsettings", "default_thinking_timeout",  "INTEGER"),
        ("modelentry",     "expires_at",         "TEXT"),
        ("modelentry",     "priority",           "INTEGER"),
        ("modelentry",     "is_vision",          "INTEGER"),
        ("modelentry",     "tags",               "TEXT"),
        ("modelentry",     "thinking_timeout",   "INTEGER"),
        ("modelentry",     "ai_profile",         "TEXT"),
        ("modelentry",     "thinking_mode",      "TEXT"),
        ("modelentry",     "capabilities",       "TEXT"),
        ("modelentry",     "max_tokens",         "INTEGER"),
        ("providergroup",  "priority",       "INTEGER"),
        ("providergroup",  "alias",          "TEXT"),
        ("providergroup",  "website",        "TEXT"),
        ("taskgroup",      "display_name",   "TEXT"),
        ("taskgroup",      "pinned",         "TEXT"),
        ("taskgroup",      "exclude_tags",   "TEXT"),
        ("taskgroup",      "tags",           "TEXT"),
        ("taskgroup",      "prefer",         "TEXT"),
        ("taskgroup",      "thinking",       "INTEGER"),
        ("taskgroup",      "remark",         "TEXT"),
        ("taskgroup",      "enabled",        "INTEGER"),
        ("taskgroup",      "max_tokens",     "INTEGER"),
    ]
    with engine.connect() as conn:
        for table, col, col_type in new_columns:
            # 查询现有列
            result = conn.execute(
                __import__("sqlalchemy").text(f"PRAGMA table_info({table})")
            )
            existing = {row[1] for row in result}
            if col not in existing:
                conn.execute(
                    __import__("sqlalchemy").text(
                        f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"
                    )
                )
        conn.commit()

    # ---- 数据迁移：旧布尔字段 → thinking_mode / capabilities ----
    # 仅对 thinking_mode IS NULL 的行执行，已迁移的不重复覆盖
    with engine.connect() as conn:
        import sqlalchemy
        # thinking_mode 迁移
        conn.execute(sqlalchemy.text(
            "UPDATE modelentry SET thinking_mode = 'always' "
            "WHERE thinking_mode IS NULL AND supports_thinking = 1 AND is_thinking_only = 1"
        ))
        conn.execute(sqlalchemy.text(
            "UPDATE modelentry SET thinking_mode = 'optional' "
            "WHERE thinking_mode IS NULL AND supports_thinking = 1 AND is_thinking_only = 0"
        ))
        conn.execute(sqlalchemy.text(
            "UPDATE modelentry SET thinking_mode = 'none' "
            "WHERE thinking_mode IS NULL AND supports_thinking = 0"
        ))
        # capabilities 迁移
        conn.execute(sqlalchemy.text(
            "UPDATE modelentry SET capabilities = '[\"text\",\"vision\"]' "
            "WHERE capabilities IS NULL AND is_vision = 1"
        ))
        conn.execute(sqlalchemy.text(
            "UPDATE modelentry SET capabilities = '[\"text\"]' "
            "WHERE capabilities IS NULL AND is_vision = 0"
        ))
        conn.commit()


def init_db():
    """初始化数据库表结构（首次运行时调用）"""
    from backend.models.config import GlobalSettings, ProviderGroup, ModelEntry, TaskGroup  # noqa: F401
    SQLModel.metadata.create_all(engine)
    _migrate_db()
    # 确保 GlobalSettings 有默认行
    with Session(engine) as session:
        from sqlmodel import select
        gs = session.exec(select(GlobalSettings)).first()
        if not gs:
            session.add(GlobalSettings())
            session.commit()


def get_session():
    """FastAPI 依赖注入用"""
    with Session(engine) as session:
        yield session
