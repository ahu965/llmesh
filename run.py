"""
llmesh 桌面端启动入口
- 在后台线程启动 FastAPI/uvicorn
- 等服务就绪后用 pywebview 打开原生窗口
- 关闭窗口即退出整个进程
"""
import subprocess
import sys
import threading
import time
from pathlib import Path

import uvicorn
import webview


_HOST = "127.0.0.1"
_PORT = 8001
_DIST = Path(__file__).parent / "backend" / "static" / "dist"
_ICON = str(Path(__file__).parent / "llmesh.png")


def _ensure_frontend():
    """如果前端未构建，自动执行 npm run build"""
    if _DIST.exists():
        return
    print("[llmesh] 前端未构建，正在执行 npm run build ...")
    frontend_dir = Path(__file__).parent / "frontend"
    result = subprocess.run(
        ["npm", "run", "build"],
        cwd=str(frontend_dir),
        capture_output=False,
    )
    if result.returncode != 0:
        print("[llmesh] 前端构建失败，请手动执行 cd frontend && npm run build")
        sys.exit(1)
    print("[llmesh] 前端构建完成")


def _start_server():
    uvicorn.run(
        "backend.main:app",
        host=_HOST,
        port=_PORT,
        log_level="warning",
    )


def _wait_for_server(timeout: int = 15) -> bool:
    """轮询直到 HTTP 服务可用"""
    import urllib.request
    url = f"http://{_HOST}:{_PORT}/"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.2)
    return False


def main():
    _ensure_frontend()

    # 后台启动 uvicorn
    server_thread = threading.Thread(target=_start_server, daemon=True)
    server_thread.start()

    print("[llmesh] 等待服务启动...")
    if not _wait_for_server():
        print("[llmesh] 服务启动超时，请检查端口 8001 是否被占用")
        sys.exit(1)

    print(f"[llmesh] 服务已就绪，打开窗口 http://{_HOST}:{_PORT}")
    webview.create_window(
        "llmesh",
        f"http://{_HOST}:{_PORT}",
        width=1400,
        height=900,
        min_size=(900, 600),
    )
    webview.start(private_mode=False, icon=_ICON)


if __name__ == "__main__":
    main()
