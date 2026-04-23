#!/usr/bin/env python3
"""
批量将 /Users/heytea/ai-configs/shared/prompts/ 下的 21 个场景模板
提炼为 Prompt Optimizer 用的 system prompt。

使用 qwen3.5-plus（阿里云 dashscope），直接调 OpenAI 兼容接口，不走 llmesh pool。

输出：backend/routers/scene_prompts_generated.py
执行：python scripts/gen_scene_prompts.py
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from openai import OpenAI

# ──────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────

API_KEY = "sk-67b04a3435fb4f4c90a5d1b6a39f163c"
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "qwen3.5-plus"

PROMPTS_DIR = Path("/Users/heytea/ai-configs/shared/prompts")
OUTPUT_FILE = Path(__file__).parent.parent / "backend/routers/scene_prompts_generated.py"

# 21 个场景文件（按序号）
SCENE_FILES = [
    ("scene_01_verification",   "01-verification.md"),
    ("scene_02_comparison",     "02-comparison.md"),
    ("scene_03_step_execution", "03-step-execution.md"),
    ("scene_04_library_integration", "04-library-integration.md"),
    ("scene_05_bug_analysis",   "05-bug-analysis.md"),
    ("scene_06_rule_optimization", "06-rule-optimization.md"),
    ("scene_07_code_review",    "07-code-review.md"),
    ("scene_08_learning_explain", "08-learning-explain.md"),
    ("scene_09_writing_doc",    "09-writing-doc.md"),
    ("scene_10_code_reading",   "10-code-reading.md"),
    ("scene_11_data_analysis",  "11-data-analysis.md"),
    ("scene_12_question_refine", "12-question-refine.md"),
    ("scene_13_migration",      "13-migration-translate.md"),
    ("scene_14_test_case",      "14-test-case-design.md"),
    ("scene_15_api_debug",      "15-api-debug.md"),
    ("scene_16_script_writing", "16-script-writing.md"),
    ("scene_17_incident_report", "17-incident-report.md"),
    ("scene_18_rule_modification", "18-rule-based-modification.md"),
    ("scene_19_precheck",       "19-precheck.md"),
    ("scene_20_learning",       "20-learning.md"),
    ("scene_21_data_analysis_collab", "21-data-analysis.md"),
]

# ──────────────────────────────────────────────
# 通用结尾段（所有场景 system prompt 统一追加）
# ──────────────────────────────────────────────

COMMON_SUFFIX = """
## 占位符规则
如果原始提示词中有需要用户自己提供的具体信息（如项目名、技术栈、目标 URL、数据结构等），请在优化后的 Prompt 中用 `[请替换: 描述]` 格式标注，不要自行假设。例：`[请替换: 你的编程语言]`、`[请替换: 目标网站 URL]`。

## 输出格式
请直接输出优化后的 Prompt 正文（纯文本，不要加任何标题行、不要加引号或代码块包裹，第一行就是 Prompt 内容），然后在 Prompt 后面空一行，输出：

### 优化说明
- 策略：使用了哪些优化手段
- 假设：如果原始提示词信息不完整，列出你补充或假设的条件；若信息完整则省略此项
- 建议：1-3 条针对这个场景的额外建议"""

# ──────────────────────────────────────────────
# 给 LLM 的元提示词：让它从 .md 文件里提炼 system prompt
# ──────────────────────────────────────────────

META_SYSTEM_PROMPT = """你是一位提示词工程专家。你的任务是：
给定一个场景模板文档（Markdown 格式），提炼出一段供「Prompt Optimizer」使用的 system prompt。

## 关键概念

这个 system prompt 有两个层次，必须严格区分：
- **优化模型**：接收 system prompt 的那个 AI，它的任务是「将用户输入改写为优化后的提示词」
- **下游模型**：用户拿到优化后的提示词后，实际发给另一个 AI 来完成任务

⚠️ system prompt 里的所有约束，都是在指导优化模型「如何生成提示词」，而不是让优化模型直接回答用户问题。
文档「模板」章节里的结构要求（如「输出结论/依据/方案」），是应该被**写进优化后的 Prompt 里**的内容，而不是优化模型自身的输出格式。

## 提炼规则

1. **角色定位**：第一句话明确角色，格式：「你是一位提示词工程专家，专注于「{场景名}」类任务的优化。」
   - 第二句说明目标：「你的目标是将用户的原始问题改写为一个结构化的提示词，该提示词将被用户复制后发给 AI，以[场景目的]。」
2. **优化策略**：说明优化模型应如何构建提示词，列出 3-5 条策略：
   - 描述优化后的 Prompt 应包含哪些要素（结构、约束、格式要求等）
   - 用「将原始问题重构为包含以下要素的提示词：」引导，而不是「核心约束：」
   - 这些要素来自文档「模板」章节，但描述为「应嵌入到生成的提示词里」的内容
3. **不要包含**：
   - 原文档里的示例输入/输出
   - 「使用场景」「常见违规」等说明性章节
   - 任何 HTML 注释或 frontmatter
   - 让优化模型自己「直接回答问题」的约束（这是最常见的错误！）
4. **长度控制**：提炼后的 system prompt（不含通用结尾）控制在 200-400 字之间
5. **只输出 system prompt 正文**：不要加任何前缀说明，直接从角色定位句开始输出（不含「占位符规则」和「输出格式」，这两段会由程序统一追加）"""


def read_md(filename: str) -> str:
    path = PROMPTS_DIR / filename
    return path.read_text(encoding="utf-8")


def extract_frontmatter_title(content: str) -> str:
    """从 frontmatter 里读 title 字段"""
    m = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
    return m.group(1).strip() if m else ""


def gen_system_prompt(client: OpenAI, key: str, md_content: str) -> str:
    """调用 LLM 提炼一个场景的 system prompt"""
    user_msg = f"请为以下场景模板文档提炼 system prompt：\n\n---\n{md_content}\n---"

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": META_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.3,
        max_tokens=800,
        extra_body={"enable_thinking": False},
    )
    core = resp.choices[0].message.content.strip()
    # 拼上统一结尾
    return core + "\n" + COMMON_SUFFIX


def escape_for_python(s: str) -> str:
    """将字符串转义为 Python 三引号字符串安全内容（不处理引号本身，用三引号包裹）"""
    # 只需要转义三引号内的 \，其余保留
    return s.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')


def main():
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    results: dict[str, str] = {}
    errors: list[str] = []

    total = len(SCENE_FILES)
    for i, (key, filename) in enumerate(SCENE_FILES, 1):
        print(f"[{i:02d}/{total}] 处理 {filename} ...", end=" ", flush=True)
        try:
            md_content = read_md(filename)
            system_prompt = gen_system_prompt(client, key, md_content)
            results[key] = system_prompt
            print(f"✓ ({len(system_prompt)} chars)")
        except Exception as e:
            print(f"✗ 失败：{e}")
            errors.append(f"{key}: {e}")
        # 避免触发限流
        if i < total:
            time.sleep(0.5)

    # ── 生成输出文件 ──
    lines = [
        '"""',
        "场景模板 system prompt 字典。",
        "由 scripts/gen_scene_prompts.py 自动生成，human review 后合并到 prompt_optimizer.py。",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "SCENE_SYSTEM_PROMPTS: dict[str, str] = {",
    ]

    for key, prompt in results.items():
        # 找到对应的 .md 文件名写注释
        md_filename = next(f for k, f in SCENE_FILES if k == key)
        lines.append(f"    # {md_filename}")
        lines.append(f"    {key!r}: \"\"\"\\")
        # 每行缩进 4 空格，保留原始换行
        for line in prompt.splitlines():
            escaped = line.replace("\\", "\\\\").replace('"""', r'\"\"\"')
            lines.append(escaped)
        lines.append('""",')
        lines.append("")

    lines.append("}")
    lines.append("")

    output = "\n".join(lines)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(output, encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"输出文件：{OUTPUT_FILE}")
    print(f"成功：{len(results)}/{total} 个场景")
    if errors:
        print(f"失败：{len(errors)} 个：")
        for e in errors:
            print(f"  - {e}")
    print("="*60)
    print("\n下一步：打开输出文件 review 每条 system prompt，确认质量后合并到 prompt_optimizer.py")


if __name__ == "__main__":
    main()
