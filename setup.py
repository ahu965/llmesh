from datetime import datetime
import compileall
import os
import shutil

from setuptools import setup, find_packages
from setuptools.command.build_py import build_py


def get_timestamp_version():
    now = datetime.now()
    return f"{now.year}.{now.month}.{now.day}.{now.strftime('%H%M%S')}"


class BuildPyCompileOnly(build_py):
    """
    自定义 build_py：
    1. 先按默认逻辑把 .py 复制到 build/lib/
    2. 清除 build/lib/ 里所有旧 __pycache__
    3. 用当前 Python 重新编译所有 .py 为 .pyc
    4. 把 __pycache__/xxx.cpython-NNN.pyc 移动到包目录，改名为 xxx.pyc
    5. 删除 __pycache__ 目录、所有 .py 源码、测试文件对应的 .pyc
    项目源码目录完全不受影响。

    必须用与部署环境相同的 Python 版本执行打包！
    """

    _TEST_PREFIXES = ("test_",)
    _TEST_SUFFIXES = ("_test",)

    def _is_test_file(self, bare: str) -> bool:
        return (
            any(bare.startswith(p) for p in self._TEST_PREFIXES)
            or any(bare.endswith(s) for s in self._TEST_SUFFIXES)
        )

    def run(self):
        # 步骤1：默认 build（把 .py 复制到 build/lib/）
        super().run()

        build_lib = self.build_lib

        # 步骤2：清除 build/lib 里所有旧 __pycache__
        for root, dirs, files in os.walk(build_lib):
            for d in list(dirs):
                if d == "__pycache__":
                    shutil.rmtree(os.path.join(root, d))
            dirs[:] = [d for d in dirs if d != "__pycache__"]

        # 步骤3：用当前 Python 重新编译
        compileall.compile_dir(build_lib, force=True, quiet=1)

        # 步骤4：把 __pycache__/xxx.cpython-NNN.pyc 移动到包目录，改名为 xxx.pyc
        for root, dirs, files in os.walk(build_lib, topdown=False):
            cache_dir = os.path.join(root, "__pycache__")
            if not os.path.isdir(cache_dir):
                continue
            for pyc in os.listdir(cache_dir):
                if not pyc.endswith(".pyc"):
                    continue
                # "foo.cpython-310.pyc" -> bare = "foo"
                bare = pyc.split(".")[0]
                if self._is_test_file(bare):
                    continue
                src = os.path.join(cache_dir, pyc)
                dst = os.path.join(root, bare + ".pyc")
                shutil.move(src, dst)
            shutil.rmtree(cache_dir)

        # 步骤5：删除所有 .py 源码
        for root, dirs, files in os.walk(build_lib):
            for f in files:
                if f.endswith(".py"):
                    os.remove(os.path.join(root, f))


setup(
    name="llmesh",
    version=get_timestamp_version(),
    packages=find_packages(include=["llmesh", "llmesh.*"]),
    package_data={"": ["**/*.pyc", "*.pyc"]},
    install_requires=[
        "langchain-openai",
        "openai",
    ],
    author="huyanping",
    description="Multi-vendor LLM routing SDK",
    python_requires=">=3.10",
    cmdclass={"build_py": BuildPyCompileOnly},
)
