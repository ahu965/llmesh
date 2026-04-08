"""
数据库连接管理
- 使用加密 SQLite（sqlcipher3），密钥从 .env 读取
- 长期可通过修改 DATABASE_URL 切换 PostgreSQL，上层代码无感知
"""
from pathlib import Path
from sqlmodel import SQLModel, create_engine, Session
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_path: str = "data/llmesh.db"
    db_key: str = "llmesh_default_key"   # 加密密钥，生产环境务必通过 .env 覆盖

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

_DB_PATH = Path(settings.db_path)
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# SQLCipher 加密连接串：使用 pysqlcipher3 方言
_DATABASE_URL = f"sqlite+pysqlcipher://:{settings.db_key}@/{_DB_PATH.resolve()}"

engine = create_engine(
    _DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)


def init_db():
    """初始化数据库表结构（首次运行时调用）"""
    from backend.models.config import GlobalSettings, ProviderGroup, ModelEntry  # noqa: F401
    SQLModel.metadata.create_all(engine)
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
