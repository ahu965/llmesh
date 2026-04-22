"""
打包发布路由
- POST /api/build        → 生成 secrets.py → bdist_wheel → 可选 twine upload（SSE 流式日志）
- GET  /api/build/status → 返回发布状态（上次发包时间、DB 变更时间、是否需要发包）
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Generator, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select
from pydantic import BaseModel

from backend.database import get_session
from backend.core.exporter import export_secrets
from backend.models.config import GlobalSettings

router = APIRouter(prefix="/api", tags=["build"])

_PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
_SECRETS_DST  = _PROJECT_ROOT / "llmesh" / "secrets.py"
_DIST_DIR     = _PROJECT_ROOT / "dist"


class BuildRequest(BaseModel):
    upload: bool = False   # 是否在打包后执行 twine upload


class BuildConfigRequest(BaseModel):
    python_path: Optional[str] = None
    pypi_url: Optional[str] = None


def _get_or_init_settings(session: Session) -> GlobalSettings:
    gs = session.exec(select(GlobalSettings)).first()
    if not gs:
        gs = GlobalSettings()
        session.add(gs)
        session.commit()
        session.refresh(gs)
    return gs


def _sse(line: str) -> str:
    """将一行日志包装为 SSE data 帧"""
    return f"data: {line}\n\n"


def _run_stream(cmd: list[str], cwd: str, timeout: int = 180) -> Generator[str, None, int]:
    """
    逐行 yield 子进程输出（stdout + stderr 合并），最后 return returncode。
    用法：gen = _run_stream(...)；for line in gen: ...；code = gen.return_value（不直接支持，见调用侧）
    实际通过 StopIteration.value 获取 returncode。
    """
    # 清除 PYTHONHOME / PYTHONPATH，避免 uv 注入的环境变量污染子进程的标准库解析
    clean_env = os.environ.copy()
    clean_env.pop("PYTHONHOME", None)
    clean_env.pop("PYTHONPATH", None)
    proc = subprocess.Popen(
        cmd, cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, env=clean_env,
    )
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            yield line.rstrip("\n")
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        yield f"[ERROR] 命令超时（>{timeout}s）"
        return 1
    return proc.returncode


def _cleanup(wheel: Path):
    """删除打包产生的所有中间文件和产物 whl"""
    targets = [
        wheel,
        _PROJECT_ROOT / "dist",
        _PROJECT_ROOT / "build",
        *_PROJECT_ROOT.glob("*.egg-info"),
    ]
    for p in targets:
        if p.exists():
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()


@router.get("/build/status")
def build_status(session: Session = Depends(get_session)):
    """返回当前发布状态，前端据此决定按钮是否可用"""
    gs = _get_or_init_settings(session)
    needs_build = (
        gs.last_built_at is None
        or gs.db_updated_at is None
        or gs.db_updated_at > gs.last_built_at
    )
    return {
        "last_built_at": gs.last_built_at,
        "db_updated_at": gs.db_updated_at,
        "needs_build": needs_build,
        "python_path": gs.python_path,
        "pypi_url": gs.pypi_url,
    }


@router.put("/build/config")
def save_build_config(req: BuildConfigRequest, session: Session = Depends(get_session)):
    """保存打包 Python 路径和 PyPI 上传地址"""
    gs = _get_or_init_settings(session)
    gs.python_path = req.python_path
    gs.pypi_url    = req.pypi_url
    session.add(gs)
    session.commit()
    return {"ok": True}


@router.post("/build")
def do_build(req: BuildRequest = BuildRequest(), session: Session = Depends(get_session)):
    """
    流式 SSE 响应：
      - 普通日志行：data: <line>\\n\\n
      - 最终结果行：data: __RESULT__<json>\\n\\n
      - 错误结果行：data: __ERROR__<message>\\n\\n
    """
    gs = _get_or_init_settings(session)
    python_bin = gs.python_path or sys.executable
    pypi_url   = gs.pypi_url
    upload     = req.upload

    def _stream() -> Generator[str, None, None]:
        # 步骤 1：生成 secrets.py
        try:
            export_secrets(session, output_path=_SECRETS_DST)
            yield _sse(f"[OK] secrets.py 已写入 {_SECRETS_DST}")
        except Exception as e:
            yield _sse(f"__ERROR__生成 secrets.py 失败：{e}")
            return

        # 步骤 2：清空旧产物，避免上传到错误版本
        if _DIST_DIR.exists():
            shutil.rmtree(_DIST_DIR)
            yield _sse("[OK] 已清空旧 dist/")

        # 步骤 3：打包（逐行流式）
        # pyproject.toml 是后端项目配置，其 version 字段会覆盖 setup.py，
        # 打包期间临时重命名以确保 setup.py 的时间戳版本生效。
        _pyproject = _PROJECT_ROOT / "pyproject.toml"
        _pyproject_bak = _PROJECT_ROOT / "pyproject.toml.bak"
        if _pyproject.exists():
            _pyproject.rename(_pyproject_bak)
        try:
            yield _sse(f"[RUN] {python_bin} setup.py bdist_wheel --dist-dir dist")
            build_code = 0
            gen = _run_stream(
                [python_bin, "setup.py", "bdist_wheel", "--dist-dir", "dist"],
                cwd=str(_PROJECT_ROOT),
            )
            try:
                while True:
                    line = next(gen)
                    yield _sse(line)
            except StopIteration as e:
                build_code = e.value if e.value is not None else 0
        finally:
            if _pyproject_bak.exists():
                _pyproject_bak.rename(_pyproject)

        if build_code != 0:
            yield _sse(f"__ERROR__打包失败（exit {build_code}）")
            return
        yield _sse(f"[OK] 打包完成（exit {build_code}）")

        # 找最新产物
        wheels = sorted(_DIST_DIR.glob("llmesh-*.whl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not wheels:
            yield _sse("__ERROR__打包完成但未找到 .whl 产物")
            return
        latest_wheel = wheels[0]
        yield _sse(f"[OK] 产物：{latest_wheel.name}")

        # 步骤 4（可选）：twine upload
        if upload:
            if not pypi_url:
                yield _sse("__ERROR__未配置 PyPI 上传地址（pypi_url）")
                return
            twine_bin = str(Path(python_bin).parent / "twine")
            yield _sse(f"[RUN] {twine_bin} upload --repository-url {pypi_url} {latest_wheel.name}")
            upload_code = 0
            gen2 = _run_stream(
                [twine_bin, "upload", "--repository-url", pypi_url,
                 "--non-interactive", "-u", "", "-p", "",
                 str(latest_wheel)],
                cwd=str(_PROJECT_ROOT),
                timeout=60,
            )
            try:
                while True:
                    line = next(gen2)
                    yield _sse(line)
            except StopIteration as e:
                upload_code = e.value if e.value is not None else 0

            if upload_code != 0:
                yield _sse(f"__ERROR__上传失败（exit {upload_code}）")
                return
            yield _sse(f"[OK] 上传完成 → {pypi_url}")

            _cleanup(latest_wheel)
            yield _sse("[OK] 已清理 dist/ build/ *.egg-info/")
        else:
            for p in [_PROJECT_ROOT / "build", *_PROJECT_ROOT.glob("*.egg-info")]:
                if p.exists():
                    shutil.rmtree(p)
            yield _sse(f"[OK] 产物保留于 {latest_wheel}，已清理 build/ *.egg-info/")

        # 步骤 4：记录发布时间
        gs.last_built_at = time.time()
        session.add(gs)
        session.commit()

        result = {
            "ok": True,
            "wheel": latest_wheel.name,
            "wheel_path": str(latest_wheel),
            "uploaded": upload,
        }
        yield _sse(f"__RESULT__{json.dumps(result, ensure_ascii=False)}")

    return StreamingResponse(_stream(), media_type="text/event-stream")
