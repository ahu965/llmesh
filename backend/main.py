"""
llmesh backend 入口
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from backend.database import init_db
from backend.routers import settings, providers, io, build, simulate, probe, task_groups


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="llmesh",
    description="Lightweight LLM gateway with stateful routing — configuration manager & playground",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 路由
app.include_router(settings.router)
app.include_router(providers.router)
app.include_router(io.router)
app.include_router(build.router)
app.include_router(simulate.router)
app.include_router(probe.router)
app.include_router(task_groups.router)

# 前端静态文件（构建后）
_DIST = Path(__file__).parent / "static" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        return FileResponse(str(_DIST / "index.html"))
