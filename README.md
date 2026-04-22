# llmesh

> A lightweight, developer-friendly LLM gateway with stateful routing.

**llmesh** 是一个面向开发者的轻量 LLM 网关，核心差异在于智能路由引擎。短期作为可视化配置管理工具（管理多厂商 API Key 和模型池），长期演进为完整的网关模式，所有调用方通过统一 HTTP API 接入。

---

## 差异化定位

主流竞品（LiteLLM、One API、New API）的共同盲区是**路由智能程度**——均停留在"权重随机 + 失败重试"，没有真正的状态感知路由。

| 特性 | LiteLLM | One API | New API | llmesh |
|---|---|---|---|---|
| 三态熔断（closed / open / **half_open** 探测） | ❌ 仅 cooldown 屏蔽 | ❌ | ❌ | ✅ |
| `prefer` 两阶段路由（优先匹配 → 全量 fallback） | ❌ | ❌ | ❌ | ✅ |
| 限流降权（冷却期内权重归零，≠ 熔断） | ❌ | ❌ | ❌ | ✅ |
| 超时递增重试（`base + step × retry`） | ❌ 固定间隔 | ❌ | ❌ | ✅ |
| `is_thinking_only` 模型语义过滤 | ❌ | ❌ | 命名约定 ⚠️ | ✅ 字段级 |
| per-model `extra_body` 注入 | ✅ | ❌ | ❌ | ✅ |
| 可视化配置 UI | ✅ 依赖 PostgreSQL | ❌ | ❌ | ✅ SQLite（加密，零基础设施） |
| Python 原生，无需 Go 环境 | ✅ | ❌ | ❌ | ✅ |

---

## 快速开始

### 环境要求
- Python 3.10+
- Node.js 18+（前端开发时需要）
- [uv](https://github.com/astral-sh/uv)（Python 包管理）

### 安装

```bash
git clone https://github.com/yourname/llmesh.git
cd llmesh

# 配置环境变量
cp .env.example .env
# 编辑 .env，修改 DB_KEY 为自定义加密密钥

# 安装 Python 依赖
uv sync

# 启动后端
uv run uvicorn backend.main:app --reload --reload-dir backend --port 8001
```

### 前端开发模式

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173
```

### 前端构建（生产）

```bash
cd frontend
npm run build
# 构建产物输出到 backend/static/dist/
# 后端直接托管静态文件，访问 http://localhost:8000 即可
```

---

## macOS 桌面应用（.app bundle）

llmesh 支持打包为 macOS 原生 .app，双击即可启动，通过 pywebview 提供桌面窗口。

### 前置依赖

- Xcode Command Line Tools：`xcode-select --install`
- ImageMagick（生成图标）：`brew install imagemagick`

### 1. 生成图标

```bash
# 1. 生成圆角背景
magick -size 860x860 gradient:'#5b6ef5-#2563eb' \
  \( +clone -alpha extract \
     -draw "fill white roundrectangle 0,0,859,859,190,190" \) \
  -alpha off -compose CopyOpacity -composite rounded.png

# 2. 放置到 1024×1024 画布
magick -size 1024x1024 xc:none \
  rounded.png -geometry +82+82 -composite \
  -font "HelveticaNeue" -pointsize 170 -fill white \
  -gravity Center -annotate 0 "llmesh" llmesh.png

rm rounded.png

# 3. 生成 .icns（macOS 图标格式）
mkdir -p llmesh.iconset
for size in 16 32 64 128 256 512; do
  magick llmesh.png -resize ${size}x${size} llmesh.iconset/icon_${size}x${size}.png
  magick llmesh.png -resize $((size*2))x$((size*2)) llmesh.iconset/icon_${size}x${size}@2x.png
done
iconutil -c icns llmesh.iconset -o llmesh.icns
rm -rf llmesh.iconset
```

### 2. 编辑 launcher.c

`launcher.c` 是 .app 的启动器源码，**需要修改为本机路径**后编译：

```c
// 修改以下三个路径为实际值
const char *python  = "/path/to/uv/python/cpython-3.x.x-.../bin/python3.x";
const char *script  = "/path/to/llmesh/run.py";
const char *projdir = "/path/to/llmesh";

// 同时修改 envp[] 中所有包含绝对路径的条目：
// PYTHONHOME=...
// PYTHONPATH=.../site-packages:...
// VIRTUAL_ENV=...
// PATH=.../bin:...
// HOME=...
// USER=...
```

查看当前 Python 路径：

```bash
# uv 管理的 Python 位置
uv python find

# venv site-packages 位置
.venv/bin/python -c "import site; print(site.getsitepackages())"
```

### 3. 编译并签名

```bash
# 编译（Apple Silicon）
cc -o llmesh.app/Contents/MacOS/llmesh launcher.c -target arm64-apple-macos11

# Intel Mac
# cc -o llmesh.app/Contents/MacOS/llmesh launcher.c -target x86_64-apple-macos10.15

# ad-hoc 签名（无需开发者证书）
codesign --force --deep --sign - llmesh.app
```

> **注意：** 每次修改 `launcher.c` 后需要重新执行编译和签名命令。`Info.plist` 修改后只需重新签名（无需重新编译）。

### 4. 配置 .app bundle 结构

确保 `llmesh.app/Contents/Resources/llmesh.icns` 存在：

```bash
cp llmesh.icns llmesh.app/Contents/Resources/llmesh.icns
```

### 5. 首次启动 Gatekeeper 问题

macOS 对未经 App Store 或开发者证书签名的应用会弹出警告。解除方式：

```bash
xattr -cr llmesh.app
```

或在 Finder 中右键 → 打开 → 选择「打开」。

---

## 配置迁移（从现有 secrets.py）

如果你已有 `secrets.py` 配置文件，可以通过 UI 一键导入：

1. 启动后端服务
2. 打开 UI → 模型管理 → 「从文件导入」
3. 输入 `secrets.py` 的绝对路径，点击确认

或通过 API：

```bash
curl -X POST http://localhost:8000/api/import/file \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/path/to/secrets.py"}'
```

---

## 导出 secrets.py

配置修改后，可将数据库内容导出为与原有项目完全兼容的 `secrets.py`，调用方零改动：

```bash
curl -X POST http://localhost:8000/api/export \
  -H "Content-Type: application/json" \
  -d '{"output_path": "/path/to/secrets.py"}'
```

---

## SDK 打包发布

llmesh 同时作为 SDK 分发给调用方项目使用。UI 提供一键打包发布功能：

1. 打开 UI → 设置 → **SDK 打包发布**
2. 配置打包 Python 路径（留空使用后端当前解释器）
3. 配置私有 PyPI 上传地址（留空则仅打包不上传）
4. 点击「打包」或「打包 + 上传 PyPI」，日志实时流式输出

打包流程：
- 从数据库自动生成 `llmesh/secrets.py`（含所有厂商配置，编译为 .pyc 随包发布）
- 执行 `setup.py bdist_wheel`，版本号自动使用时间戳（`YYYY.M.D.HHmmss`）
- 可选通过 `twine` 上传到私有 PyPI
- 上传成功后自动清理 `dist/`、`build/`、`*.egg-info/` 等中间产物

调用方安装：

```bash
pip install llmesh --index-url https://your-pypi.example.com/simple/
```

---



### 三态熔断

```
closed ──[连续失败]──► open ──[到期]──► half_open ──[成功]──► closed
                                              │──[失败]──► open（重置计时）
```

- `closed`：正常调用
- `open`：屏蔽，不参与选模型
- `half_open`：单请求探测，成功恢复，失败重新计时

### prefer 两阶段路由

```python
get_llm(prefer="claude")  # 优先选 vendor/model 名含 "claude" 的模型
                           # 无可用时自动 fallback 到全量池
```

### 限流降权（独立于熔断）

收到 429 时：
- 本次请求跳过该模型
- 冷却期（`rate_limit_cooldown` 秒）内权重归零，但不触发熔断
- 冷却期结束后自动恢复原始权重

### thinking 模型感知

```python
get_llm(thinking=True)   # 只选 supports_thinking=True 的模型
get_llm(thinking=False)  # 排除 is_thinking_only=True 的模型
get_llm(thinking=None)   # 不过滤，沿用 extra_body 默认配置
```

---

## 项目结构

```
llmesh/
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── database.py          # 加密 SQLite 连接（含自动迁移）
│   ├── models/
│   │   └── config.py        # SQLModel 数据模型
│   ├── routers/
│   │   ├── providers.py     # 厂商组 & 模型 CRUD
│   │   ├── settings.py      # 全局配置
│   │   ├── io.py            # 导入/导出
│   │   └── build.py         # SDK 打包发布（SSE 流式日志）
│   └── core/
│       ├── exporter.py      # DB → secrets.py
│       ├── importer.py      # secrets.py → DB
│       └── db_utils.py      # 公共写操作工具（touch_db）
├── llmesh/                  # SDK 包（打包分发给调用方）
│   ├── config.py            # 路由配置入口
│   ├── pool.py              # 智能路由引擎
│   └── secrets.py           # 自动生成，不入 git
├── setup.py                 # SDK 打包脚本（时间戳版本 + .pyc 混淆）
└── frontend/                # Vue 3 + Arco Design
    └── src/
        ├── views/
        │   ├── Providers.vue    # 模型管理
        │   └── Settings.vue     # 全局配置 & SDK 打包发布
        └── api/index.ts         # API 封装
```

---

## Roadmap

- [x] 配置管理 UI（厂商组 + 模型增删改）
- [x] 全局路由参数配置
- [x] secrets.py 导入/导出（兼容现有项目）
- [x] 加密 SQLite 存储
- [x] SDK 一键打包发布（时间戳版本 + .pyc 混淆 + 私有 PyPI 上传）
- [x] SSE 流式构建日志
- [ ] Playground（流式对话测试，多模型对比）
- [ ] 调用统计面板（成功率、延迟、错误分布）
- [ ] 健康检查（主动探测模型可用性）
- [ ] 过期/限额告警
- [ ] 网关模式（HTTP API 代理，所有项目统一接入）
- [ ] 多租户 & Key 管理

---

## License

MIT
