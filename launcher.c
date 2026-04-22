/*
 * llmesh macOS .app bundle launcher
 *
 * 使用 execve 构造完全干净的环境变量，绕过 macOS LSEnvironment 注入问题。
 *
 * !! 使用前必须将下方所有路径替换为本机实际路径 !!
 * 参考 README.md 中"macOS 桌面应用"章节。
 *
 * 编译命令（Apple Silicon）：
 *   cc -o llmesh.app/Contents/MacOS/llmesh launcher.c -target arm64-apple-macos11
 * 签名：
 *   codesign --force --deep --sign - llmesh.app
 */
#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>

int main(int argc, char *argv[]) {
    /* 使用真实 Python 二进制，而非 venv 符号链接
     * 查询命令：uv python find
     * 替换为你本机的实际路径 */
    const char *python  = "/Users/heytea/.local/share/uv/python/cpython-3.10.18-macos-aarch64-none/bin/python3.10";
    const char *script  = "/Users/heytea/Projects/python/llmesh/run.py";
    const char *projdir = "/Users/heytea/Projects/python/llmesh";

    chdir(projdir);

    char *envp[] = {
        /* 标准库前缀：uv python find 所在目录的上一级 */
        "PYTHONHOME=/Users/heytea/.local/share/uv/python/cpython-3.10.18-macos-aarch64-none",
        /* site-packages + 项目根
         * 查询：.venv/bin/python -c "import site; print(site.getsitepackages())" */
        "PYTHONPATH=/Users/heytea/Projects/python/llmesh/.venv/lib/python3.10/site-packages:/Users/heytea/Projects/python/llmesh",
        "VIRTUAL_ENV=/Users/heytea/Projects/python/llmesh/.venv",
        "PATH=/Users/heytea/Projects/python/llmesh/.venv/bin:/usr/local/bin:/usr/bin:/bin",
        "HOME=/Users/heytea",
        "USER=heytea",
        "LANG=en_US.UTF-8",
        "TMPDIR=/tmp",
        NULL
    };

    char *new_argv[] = {(char*)python, (char*)script, NULL};
    execve(python, new_argv, envp);
    perror("execve failed");
    return 1;
}
