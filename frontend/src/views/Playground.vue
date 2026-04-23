<template>
  <div class="playground-page">
    <!-- 顶部输入区 -->
    <div class="input-card">
      <div class="input-title">
        <icon-thunderbolt style="color:#165dff;font-size:16px" />
        多模型对比评测
      </div>
      <div class="input-body">
        <!-- 预设 Prompt 模板 -->
        <div class="preset-bar">
          <span class="preset-label">
            <icon-bookmark style="color:#86909c;font-size:13px" />
            快速评测：
          </span>
          <!-- 分类筛选 -->
          <div class="preset-categories">
            <a-tag
              v-for="cat in categories"
              :key="cat"
              size="small"
              :color="presetCategory === cat ? 'arcoblue' : 'gray'"
              class="preset-cat-tag"
              @click="presetCategory = cat"
            >
              {{ cat === 'all' ? '全部' : cat }}
            </a-tag>
          </div>
          <div class="preset-tags">
            <a-tag
              v-for="p in filteredPresets"
              :key="p.label"
              size="small"
              color="gray"
              class="preset-tag"
              @click="applyPreset(p)"
            >
              {{ p.label }}
            </a-tag>
          </div>
        </div>
        <a-textarea
          v-model="prompt"
          placeholder="输入你想对比测试的 prompt，或点击上方标签快速填充..."
          :auto-size="{ minRows: 3, maxRows: 8 }"
          class="prompt-input"
        />

        <!-- System Prompt 自定义区 -->
        <div class="system-prompt-section">
          <div class="system-prompt-header" @click="showSystemPrompt = !showSystemPrompt">
            <a-checkbox
              :model-value="!!systemPrompt"
              @click.prevent
              @change="(val: any) => { if (!val) systemPrompt = '' }"
            />
            <span class="system-prompt-title">自定义 System Prompt</span>
            <icon-down v-if="!showSystemPrompt" style="font-size:12px;color:#86909c" />
            <icon-up v-else style="font-size:12px;color:#86909c" />
          </div>
          <div v-if="showSystemPrompt" class="system-prompt-body">
            <a-textarea
              v-model="systemPrompt"
              placeholder="设置模型的角色、输出格式等全局指令，留空则使用内置的自我认知探测模式"
              :auto-size="{ minRows: 2, maxRows: 6 }"
              class="system-prompt-input"
            />
          </div>
        </div>

        <!-- Tool Calling 评测区 -->
        <div class="tool-section">
          <div class="tool-header" @click="toolMode = !toolMode">
            <a-checkbox
              :model-value="toolMode"
              @click.prevent
              @change="(val: any) => { toolMode = val; if (val && !toolsJson.trim()) loadToolPreset(toolPresets[0]) }"
            />
            <icon-apps style="color:#722ed1;font-size:13px" />
            <span class="tool-title">Tool Calling 评测</span>
            <a-tag v-if="toolMode" size="small" color="purple">已启用</a-tag>
            <span class="tool-hint">— 评测模型选择和调用工具的能力</span>
          </div>
          <div v-if="toolMode" class="tool-body">
            <a-alert v-if="showToolMismatchWarning" type="warning" style="margin-bottom:8px">
              当前 prompt 可能不是工具调用场景，建议使用上方「工具调用」类别的预设 prompt，或确保你的 prompt 需要模型调用工具来完成任务。
            </a-alert>
            <div class="tool-preset-bar">
              <span class="tool-preset-label">工具模板：</span>
              <a-tag
                v-for="tp in toolPresets"
                :key="tp.label"
                size="small"
                :color="selectedToolPreset === tp.label ? 'purple' : 'gray'"
                class="tool-preset-tag"
                @click="loadToolPreset(tp)"
              >
                {{ tp.label }}
              </a-tag>
            </div>
            <a-textarea
              v-model="toolsJson"
              placeholder='在此粘贴 OpenAI 格式的工具定义 JSON，或选择上方预设模板...\n\n示例：\n[\n  {\n    "type": "function",\n    "function": {\n      "name": "get_weather",\n      "description": "获取天气",\n      "parameters": { "type": "object", "properties": { "city": { "type": "string" } }, "required": ["city"] }\n    }\n  }\n]'
              :auto-size="{ minRows: 4, maxRows: 12 }"
              class="tool-json-editor"
              @input="validateToolsJson"
            />
            <div v-if="!toolsJsonValid" class="tool-json-error">
              JSON 格式错误，请检查
            </div>
          </div>
        </div>

        <div class="input-actions">
          <div class="left-actions">
            <!-- 模型选择 -->
            <a-popover title="选择对比模型" trigger="click" position="bottom">
              <template #content>
                <div class="model-picker">
                  <a-input
                    v-model="modelSearch"
                    placeholder="搜索模型..."
                    size="small"
                    style="margin-bottom:8px"
                    allow-clear
                  />
                  <!-- 厂商快选区 -->
                  <div class="vendor-quick-select">
                    <a-tag
                      v-for="vg in vendorGroups"
                      :key="vg.vendor"
                      size="small"
                      color="arcoblue"
                      class="vendor-tag"
                      @click="selectVendorModels(vg.vendor)"
                    >
                      全选 {{ vg.vendor }}（{{ vg.count }}个）
                    </a-tag>
                    <a-tag
                      size="small"
                      color="red"
                      class="vendor-tag"
                      @click="clearAllModels"
                    >
                      清空全部
                    </a-tag>
                  </div>
                  <div class="model-picker-list">
                    <div
                      v-for="m in filteredModels"
                      :key="`${m.group_id}-${m.model_id}`"
                      class="model-picker-item"
                      :class="{ selected: isSelected(m) }"
                      @click="toggleModel(m)"
                    >
                      <a-checkbox :model-value="isSelected(m)" @click.prevent />
                      <span class="vm-label">{{ m.vendor }}/{{ m.model }}</span>
                      <a-tag
                        v-if="m.thinking_mode === 'always'"
                        size="small"
                        color="orangered"
                      >思考</a-tag>
                      <a-tag
                        v-else-if="m.thinking_mode === 'optional'"
                        size="small"
                        color="cyan"
                      >可选</a-tag>
                      <a-tag
                        v-for="tag in m.tags.slice(0, 3)"
                        :key="tag"
                        size="small"
                        color="gray"
                      >{{ tag }}</a-tag>
                    </div>
                    <div v-if="filteredModels.length === 0" class="no-models">
                      没有匹配的模型
                    </div>
                  </div>
                </div>
              </template>
              <a-button>
                <template #icon><icon-apps /></template>
                已选 {{ selectedModels.length }} 个模型
              </a-button>
            </a-popover>

            <!-- 已选模型标签 -->
            <div class="selected-tags">
              <a-tag
                v-for="(m, idx) in selectedModels"
                :key="idx"
                closable
                color="arcoblue"
                @close="removeModel(idx)"
              >
                {{ m.vendor }}/{{ m.model }}
              </a-tag>
            </div>
          </div>

          <div class="right-actions">
            <a-select
              v-model="thinkingMode"
              style="width:140px"
              placeholder="思考模式"
              allow-clear
            >
              <a-option :value="null">不限</a-option>
              <a-option :value="true">开启思考</a-option>
              <a-option :value="false">关闭思考</a-option>
            </a-select>

            <a-input-number
              v-model="temperature"
              :min="0"
              :max="2"
              :step="0.1"
              :precision="1"
              placeholder="温度"
              style="width:100px"
              allow-clear
            />

            <a-checkbox v-model="enableJudge">
              AI 评分
            </a-checkbox>

            <a-button
              type="primary"
              :loading="running"
              :disabled="selectedModels.length === 0 || !prompt.trim()"
              @click="runComparison"
            >
              <template #icon><icon-play-arrow /></template>
              {{ running ? '评测中...' : '开始评测' }}
            </a-button>
          </div>
        </div>
      </div>
    </div>

    <!-- 结果区 -->
    <div v-if="results.length > 0" class="results-area">
      <!-- AI 评分面板 -->
      <div v-if="judgeResult" class="judge-card">
        <div class="judge-title">
          <icon-trophy style="color:#ff7d00;font-size:16px" />
          AI 评分（{{ judgeResult.judge_vendor }}/{{ judgeResult.judge_model }}）
        </div>
        <div class="judge-body">
          <div class="judge-ranking">
            <div
              v-for="(key, idx) in judgeResult.ranking"
              :key="key"
              class="rank-item"
            >
              <span class="rank-badge" :class="`rank-${idx + 1}`">{{ idx + 1 }}</span>
              <span class="rank-model">{{ key }}</span>
              <span class="rank-score">{{ judgeResult.scores[key]?.toFixed(1) ?? '-' }} 分</span>
            </div>
          </div>
          <div class="judge-comment">
            <a-typography-text type="secondary">{{ judgeResult.comment }}</a-typography-text>
          </div>
        </div>
      </div>

      <!-- 模型结果对比 -->
      <div class="result-grid">
        <div
          v-for="(r, idx) in results"
          :key="idx"
          class="result-card"
          :class="{ 'result-error': !r.ok }"
        >
          <div class="result-header">
            <div class="result-model-name">
              <span class="vendor-label">{{ r.vendor }}</span>
              <span class="model-label">{{ r.model }}</span>
              <a-tag v-if="r.thinking_used" size="small" color="orangered">思考</a-tag>
              <!-- 排名标记 -->
              <a-tag
                v-if="judgeResult && judgeResult.ranking[0] === `${r.vendor}/${r.model}`"
                size="small"
                color="gold"
              >🥇 最佳</a-tag>
              <a-tag
                v-else-if="judgeResult && judgeResult.ranking[1] === `${r.vendor}/${r.model}`"
                size="small"
                color="gray"
              >🥈 第二</a-tag>
              <a-tag
                v-else-if="judgeResult && judgeResult.ranking[2] === `${r.vendor}/${r.model}`"
                size="small"
                color="bronze"
              >🥉 第三</a-tag>
            </div>
            <div class="result-meta">
              <a-tag v-if="r.ok" size="small" color="green">
                {{ r.latency_ms }}ms
              </a-tag>
              <a-tag v-else size="small" color="red">失败</a-tag>
              <a-tag v-if="r.tokens_input != null || r.tokens_output != null" size="small" color="gray">
                ↑{{ r.tokens_input ?? '-' }} ↓{{ r.tokens_output ?? '-' }}
              </a-tag>
              <a-tag
                v-if="judgeResult && judgeResult.scores[`${r.vendor}/${r.model}`] != null"
                size="small"
                color="arcoblue"
              >
                {{ judgeResult.scores[`${r.vendor}/${r.model}`].toFixed(1) }}分
              </a-tag>
            </div>
          </div>
          <div v-if="r.ok && r.reply" class="result-content">
            <pre class="result-text">{{ r.reply }}</pre>
          </div>
          <!-- Tool Calls 展示 -->
          <div v-if="r.ok && r.tool_calls && r.tool_calls.length > 0" class="result-tool-calls">
            <div class="tool-calls-title">
              <icon-apps style="color:#722ed1;font-size:12px" />
              Tool Calls ({{ r.tool_calls.length }})
            </div>
            <div
              v-for="(tc, tcIdx) in r.tool_calls"
              :key="tcIdx"
              class="tool-call-item"
            >
              <div class="tc-header">
                <a-tag size="small" color="purple">{{ tc.name }}</a-tag>
                <span v-if="tc.id" class="tc-id">{{ tc.id }}</span>
              </div>
              <pre class="tc-args">{{ JSON.stringify(tc.arguments, null, 2) }}</pre>
            </div>
          </div>
          <!-- 有 tools 但无 tool_calls 时的提示 -->
          <div v-if="r.ok && toolMode && (!r.tool_calls || r.tool_calls.length === 0)" class="result-content" style="padding-top:0">
            <span class="no-tool-calls">模型未发起工具调用</span>
          </div>
          <!-- 自我认知：仅非 tool calling 模式显示 -->
          <div v-if="r.ok && r.self_identity && !toolMode" class="result-identity">
            <icon-user style="color:#86909c;font-size:12px" />
            <span>{{ r.self_identity }}</span>
          </div>
          <div v-if="!r.ok" class="result-error-msg">
            <icon-close-circle style="color:#f53f3f" /> {{ r.error }}
          </div>
        </div>
      </div>

      <!-- 底部工具栏 -->
      <div class="result-toolbar">
        <span class="total-time">
          总耗时 {{ totalTime }}ms（{{ selectedModels.length }} 个模型并发）
        </span>
        <div class="toolbar-actions">
          <a-button size="small" type="outline" @click="$router.push('/playground/history')">
            <template #icon><icon-history /></template>
            查看历史
          </a-button>
          <a-button size="small" @click="exportJSON">
            <template #icon><icon-download /></template>
            导出 JSON
          </a-button>
          <a-button size="small" @click="copyAllResults">
            <template #icon><icon-copy /></template>
            复制全部结果
          </a-button>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-else class="empty-state">
      <a-empty description="输入 prompt 并选择模型，开始多模型对比评测" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Message } from '@arco-design/web-vue'
import {
  IconThunderbolt,
  IconApps,
  IconPlayArrow,
  IconTrophy,
  IconDownload,
  IconCopy,
  IconCloseCircle,
  IconUser,
  IconBookmark,
  IconDown,
  IconUp,
  IconHistory,
} from '@arco-design/web-vue/es/icon'
import {
  apiPlaygroundModels,
  apiPlaygroundRun,
  type AvailableModel,
  type ModelResult,
  type JudgeResult,
  type PlaygroundModelRef,
  type ToolCall,
} from '../api'

// ---------- 预设 Prompt 模板 ----------
const presetCategory = ref('all')

const presetPrompts = [
  // 代码能力
  { category: '代码', label: '算法实现', prompt: '用 Python 实现一个 LRU 缓存，要求 get 和 put 操作的时间复杂度均为 O(1)。请给出完整代码和简要说明。' },
  { category: '代码', label: '代码审查', prompt: '请审查以下代码，找出潜在的 bug、性能问题和安全隐患：\n\n```python\nasync def get_user_orders(user_id: str):\n    query = f"SELECT * FROM orders WHERE user_id = \'{user_id}\'"\n    result = db.execute(query)\n    orders = [dict(row) for row in result]\n    for order in orders:\n        order["total"] = order["price"] * order["quantity"]\n    return orders\n```' },
  { category: '代码', label: 'SQL 优化', prompt: '以下 SQL 查询在百万级数据量下执行很慢，请分析原因并给出优化方案：\n\nSELECT u.name, COUNT(o.id) as order_count, SUM(o.amount) as total\nFROM users u\nLEFT JOIN orders o ON u.id = o.user_id\nLEFT JOIN order_items oi ON o.id = oi.order_id\nWHERE o.created_at > \'2025-01-01\'\nGROUP BY u.id, u.name\nORDER BY total DESC\nLIMIT 50;' },
  // 推理能力
  { category: '推理', label: '逻辑推理', prompt: '一个房间里有三盏灯，房间外有三个开关分别控制这三盏灯。你只能在房间外操作开关，然后进入房间一次。如何确定每个开关分别控制哪盏灯？请给出完整的推理过程。' },
  { category: '推理', label: '数学推理', prompt: '甲乙两人同时从 A、B 两地出发相向而行。甲的速度是乙的 1.5 倍，两人相遇时甲比乙多走了 12 公里。如果甲走完全程需要 5 小时，求 A、B 两地的距离。请逐步推导。' },
  { category: '推理', label: '因果分析', prompt: '某电商平台在双11后数据：促销期间 UV 增长 200%，但转化率从 3.2% 下降到 1.8%，客单价从 280 元降到 190 元。请分析可能的原因，并给出改进建议。' },
  // 创作能力
  { category: '创作', label: '文案撰写', prompt: '为一款面向程序员的 AI 代码助手产品写一段 200 字以内的宣传文案。要求：突出核心卖点，语气轻松但不浮夸，包含一个能引起程序员共鸣的痛点场景。' },
  { category: '创作', label: '邮件撰写', prompt: '你是一名技术团队负责人，需要向产品部门解释为什么原定两周的需求需要延期一周。请写一封正式但友好的邮件，说明原因（技术依赖未就绪、测试发现兼容性问题），并给出新的时间计划。' },
  // 知识问答
  { category: '知识', label: '自我认知', prompt: '请告诉我：1. 你是什么模型？你的版本号是什么？2. 你的训练数据大概截止到什么时候？3. 你支持哪些主要能力（如代码生成、图片理解、多语言等）？' },
  { category: '知识', label: '技术概念', prompt: '请用通俗的语言解释 Transformer 架构的核心思想。要求：1. 面向有编程基础但不懂深度学习的人 2. 用一个生活中的类比来帮助理解 3. 不超过 300 字' },
  // 安全与限制
  { category: '限制', label: '幻觉检测', prompt: '请回答以下问题。如果你不确定答案，请直接说"我不知道"，不要编造：\n\n1. Go 语言 3.0 版本引入了哪些新特性？\n2. Python 4.0 是什么时候发布的？\n3. React 20 有什么重大更新？\n4. PostgreSQL 20 的默认最大连接数是多少？' },
  { category: '限制', label: '指令遵循', prompt: '请严格按照以下格式回答，不要添加任何额外内容：\n\n1. 用一个词回答：太阳从哪边升起？\n2. 用恰好 5 个字回答：你喜欢吃什么？\n3. 不使用任何标点符号回答：今天天气怎么样\n4. 只输出一个数字回答：1+2+3+4+5 等于几？\n\n注意：每题单独一行，每题的输出必须严格满足格式要求。' },
  // 工具调用
  { category: '工具调用', label: '天气查询', prompt: '帮我查一下深圳明天的天气怎么样，适合户外运动吗？', tools: true },
  { category: '工具调用', label: '计算器', prompt: '帮我算一下：如果每月定投 3000 元，年化收益率 8%，投资 20 年后总金额是多少？', tools: true },
  { category: '工具调用', label: '多工具协作', prompt: '帮我查询北京到上海的机票，要求明天下午出发，经济舱，然后帮我订一个上海的酒店，靠近外滩，预算每晚 500 以内。', tools: true },
]

// ---------- 预设工具定义 ----------
const toolPresets = [
  {
    label: '天气查询',
    tools: [
      {
        type: 'function',
        function: {
          name: 'get_weather',
          description: '获取指定城市指定日期的天气信息',
          parameters: {
            type: 'object',
            properties: {
              city: { type: 'string', description: '城市名称，如：深圳、北京' },
              date: { type: 'string', description: '日期，格式 YYYY-MM-DD，如：2025-04-23。留空则返回今天' },
            },
            required: ['city'],
          },
        },
      },
    ],
  },
  {
    label: '计算器',
    tools: [
      {
        type: 'function',
        function: {
          name: 'calculate',
          description: '执行数学计算',
          parameters: {
            type: 'object',
            properties: {
              expression: { type: 'string', description: '数学表达式，如：(1+0.08/12)^240 * 3000 * 240/((1+0.08/12)^240-1)' },
            },
            required: ['expression'],
          },
        },
      },
      {
        type: 'function',
        function: {
          name: 'compound_interest',
          description: '计算复利投资收益',
          parameters: {
            type: 'object',
            properties: {
              monthly_investment: { type: 'number', description: '每月定投金额（元）' },
              annual_rate: { type: 'number', description: '年化收益率（百分比，如 8 表示 8%）' },
              years: { type: 'number', description: '投资年限' },
            },
            required: ['monthly_investment', 'annual_rate', 'years'],
          },
        },
      },
    ],
  },
  {
    label: '多工具（机票+酒店）',
    tools: [
      {
        type: 'function',
        function: {
          name: 'search_flights',
          description: '搜索航班信息',
          parameters: {
            type: 'object',
            properties: {
              from_city: { type: 'string', description: '出发城市' },
              to_city: { type: 'string', description: '到达城市' },
              date: { type: 'string', description: '出发日期，格式 YYYY-MM-DD' },
              time_preference: { type: 'string', description: '时间偏好：上午/下午/晚上' },
              cabin_class: { type: 'string', enum: ['经济舱', '商务舱', '头等舱'], description: '舱位等级' },
            },
            required: ['from_city', 'to_city', 'date'],
          },
        },
      },
      {
        type: 'function',
        function: {
          name: 'book_hotel',
          description: '搜索并预订酒店',
          parameters: {
            type: 'object',
            properties: {
              city: { type: 'string', description: '酒店所在城市' },
              area: { type: 'string', description: '偏好区域，如：外滩、陆家嘴、机场附近' },
              check_in: { type: 'string', description: '入住日期，格式 YYYY-MM-DD' },
              check_out: { type: 'string', description: '退房日期，格式 YYYY-MM-DD' },
              max_budget: { type: 'number', description: '每晚最高预算（元）' },
            },
            required: ['city', 'check_in', 'check_out'],
          },
        },
      },
    ],
  },
]

const categories = ['all', ...new Set(presetPrompts.map(p => p.category))]

const filteredPresets = computed(() => {
  if (presetCategory.value === 'all') return presetPrompts
  return presetPrompts.filter(p => p.category === presetCategory.value)
})

// ---------- 状态 ----------
const allModels = ref<AvailableModel[]>([])
const selectedModels = ref<AvailableModel[]>([])
const modelSearch = ref('')
const prompt = ref('')
const thinkingMode = ref<boolean | null>(null)
const temperature = ref<number | undefined>(undefined)
const enableJudge = ref(false)
const running = ref(false)
const results = ref<ModelResult[]>([])
const judgeResult = ref<JudgeResult | null>(null)
const totalTime = ref(0)

// Tool calling 相关
const toolMode = ref(false)                           // 是否开启 tool calling 评测
const toolsJson = ref('')                             // JSON 编辑器内容
const toolsJsonValid = ref(true)                      // JSON 是否合法
const selectedToolPreset = ref('')                    // 当前选中的工具预设

// System Prompt 相关
const showSystemPrompt = ref(false)                   // 是否展开 System Prompt 区
const systemPrompt = ref('')                           // 自定义 system prompt

// 判断当前 prompt 是否属于 tool calling 类别
const isPromptToolRelated = computed(() => {
  return presetPrompts.some(p => p.category === '工具调用' && p.prompt === prompt.value)
})

// Tool mode 开启但 prompt 不匹配时的警告
const showToolMismatchWarning = computed(() => {
  return toolMode.value && !isPromptToolRelated.value && toolsJson.value.trim()
})

// ---------- 计算属性 ----------
const filteredModels = computed(() => {
  const q = modelSearch.value.toLowerCase().trim()
  if (!q) return allModels.value
  return allModels.value.filter(
    (m) =>
      m.vendor.toLowerCase().includes(q) ||
      m.model.toLowerCase().includes(q) ||
      m.tags.some((t) => t.includes(q))
  )
})

// 获取所有不重复的厂商列表（带数量统计）
const vendorGroups = computed(() => {
  const vendors: Record<string, number> = {}
  for (const m of allModels.value) {
    vendors[m.vendor] = (vendors[m.vendor] || 0) + 1
  }
  return Object.entries(vendors).map(([vendor, count]) => ({ vendor, count }))
})

function isSelected(m: AvailableModel) {
  return selectedModels.value.some(
    (s) => s.group_id === m.group_id && s.model_id === m.model_id
  )
}

function toggleModel(m: AvailableModel) {
  if (isSelected(m)) {
    selectedModels.value = selectedModels.value.filter(
      (s) => !(s.group_id === m.group_id && s.model_id === m.model_id)
    )
  } else if (selectedModels.value.length < 10) {
    selectedModels.value.push(m)
  } else {
    Message.warning('最多选择 10 个模型进行对比')
  }
}

function removeModel(idx: number) {
  selectedModels.value.splice(idx, 1)
}

// ---------- 厂商快速选择 ----------
function selectVendorModels(vendor: string) {
  const vendorModels = allModels.value.filter((m) => m.vendor === vendor)
  let added = 0
  for (const m of vendorModels) {
    if (!isSelected(m) && selectedModels.value.length < 10) {
      selectedModels.value.push(m)
      added++
    }
  }
  if (added > 0) {
    Message.success(`已添加 ${vendor} 的 ${added} 个模型`)
  } else if (selectedModels.value.length >= 10) {
    Message.warning('已达最大模型数量限制（10个）')
  } else {
    Message.info(`${vendor} 的模型已全部选中`)
  }
}

function clearAllModels() {
  selectedModels.value = []
}

// ---------- 核心操作 ----------
async function loadModels() {
  try {
    const { data } = await apiPlaygroundModels()
    allModels.value = data
  } catch (e: any) {
    Message.error(`加载模型列表失败：${e.message}`)
  }
}

async function runComparison() {
  if (selectedModels.value.length === 0) {
    Message.warning('请至少选择一个模型')
    return
  }
  if (!prompt.value.trim()) {
    Message.warning('请输入评测 prompt')
    return
  }

  running.value = true
  results.value = []
  judgeResult.value = null

  try {
    const models: PlaygroundModelRef[] = selectedModels.value.map((m) => ({
      group_id: m.group_id,
      model_id: m.model_id,
    }))

    // 解析 tools JSON
    let tools: Record<string, any>[] | undefined = undefined
    if (toolMode.value && toolsJson.value.trim()) {
      try {
        tools = JSON.parse(toolsJson.value)
      } catch {
        Message.error('工具定义 JSON 格式错误，请检查')
        running.value = false
        return
      }
    }

    const { data } = await apiPlaygroundRun({
      prompt: prompt.value.trim(),
      models,
      thinking: thinkingMode.value,
      temperature: temperature.value,
      judge: enableJudge.value,
      tools,
      system_prompt: systemPrompt.value || null,
    })

    results.value = data.results
    judgeResult.value = data.judge
    totalTime.value = data.total_time_ms

    const successCount = data.results.filter((r) => r.ok).length
    const failCount = data.results.length - successCount
    if (failCount > 0) {
      Message.warning(`${successCount} 个模型成功，${failCount} 个模型失败`)
    } else {
      Message.success(`全部 ${successCount} 个模型响应成功`)
    }
  } catch (e: any) {
    Message.error(`评测失败：${e.response?.data?.detail || e.message}`)
  } finally {
    running.value = false
  }
}

function exportJSON() {
  const payload = {
    prompt: prompt.value,
    models: selectedModels.value.map((m) => ({
      vendor: m.vendor,
      model: m.model,
    })),
    thinking: thinkingMode.value,
    temperature: temperature.value,
    tools: toolMode.value && toolsJson.value.trim() ? JSON.parse(toolsJson.value) : null,
    results: results.value,
    judge: judgeResult.value,
    total_time_ms: totalTime.value,
    exported_at: new Date().toISOString(),
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `playground-${Date.now()}.json`
  a.click()
  URL.revokeObjectURL(url)
  Message.success('JSON 已导出')
}

function copyAllResults() {
  const lines = results.value.map((r) => {
    const status = r.ok ? `✅ ${r.latency_ms}ms` : `❌ ${r.error}`
    const judge = judgeResult.value?.scores[`${r.vendor}/${r.model}`]
      ? ` | ${judgeResult.value.scores[`${r.vendor}/${r.model}`].toFixed(1)}分`
      : ''
    const toolInfo = r.tool_calls?.length
      ? ` | 🔧 ${r.tool_calls.length}次工具调用`
      : ''
    return `[${r.vendor}/${r.model}] ${status}${judge}${toolInfo}\n${r.reply || '(无回复)'}`
  })
  const text = `# Playground 评测结果\n\n## 问题\n${prompt.value}\n\n## 回答\n${lines.join('\n\n---\n\n')}`
  navigator.clipboard.writeText(text).then(() => {
    Message.success('已复制到剪贴板')
  })
}

// ---------- Tool Calling 辅助 ----------

function applyPreset(p: { category: string; label: string; prompt: string; tools?: boolean | string }) {
  prompt.value = p.prompt
  // 如果是 tool calling 类别的预设，自动开启 tool mode 并加载对应工具
  if (p.category === '工具调用') {
    toolMode.value = true
    const match = toolPresets.find(tp => tp.label === p.label)
    if (match) {
      loadToolPreset(match)
    }
  } else {
    // 非工具调用类别的预设，自动关闭 tool mode（避免不匹配）
    toolMode.value = false
    toolsJson.value = ''
    selectedToolPreset.value = ''
  }
}

function loadToolPreset(tp: { label: string; tools: any[] }) {
  selectedToolPreset.value = tp.label
  toolsJson.value = JSON.stringify(tp.tools, null, 2)
  toolsJsonValid.value = true
}

function validateToolsJson() {
  if (!toolsJson.value.trim()) {
    toolsJsonValid.value = true
    return
  }
  try {
    JSON.parse(toolsJson.value)
    toolsJsonValid.value = true
  } catch {
    toolsJsonValid.value = false
  }
}

// ---------- 生命周期 ----------
onMounted(() => {
  loadModels()
})
</script>

<style scoped>
.playground-page {
  max-width: 1400px;
}

.input-card {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  margin-bottom: 16px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}

.input-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.prompt-input {
  margin-bottom: 12px;
}

/* System Prompt 自定义区 */
.system-prompt-section {
  border: 1px solid #e5e6eb;
  border-radius: 6px;
  margin-bottom: 12px;
  overflow: hidden;
}

.system-prompt-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: #fafbfc;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
}

.system-prompt-header:hover {
  background: #f2f3f5;
}

.system-prompt-title {
  font-size: 13px;
  font-weight: 500;
  color: #1d2129;
}

.system-prompt-body {
  padding: 10px 12px;
  border-top: 1px solid #e5e6eb;
}

.system-prompt-input {
  font-family: 'SF Mono', 'Menlo', 'Monaco', monospace !important;
  font-size: 12px !important;
}

/* Tool Calling 评测区 */
.tool-section {
  border: 1px solid #e5e6eb;
  border-radius: 6px;
  margin-bottom: 12px;
  overflow: hidden;
}

.tool-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: #fafbfc;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
}

.tool-header:hover {
  background: #f2f3f5;
}

.tool-title {
  font-size: 13px;
  font-weight: 500;
  color: #1d2129;
}

.tool-hint {
  font-size: 12px;
  color: #86909c;
}

.tool-body {
  padding: 10px 12px;
  border-top: 1px solid #e5e6eb;
}

.tool-preset-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.tool-preset-label {
  font-size: 12px;
  color: #4e5969;
  white-space: nowrap;
}

.tool-preset-tag {
  cursor: pointer;
  transition: all 0.15s;
}

.tool-preset-tag:hover {
  border-color: #722ed1;
}

.tool-json-editor {
  font-family: 'SF Mono', 'Menlo', 'Monaco', monospace !important;
  font-size: 12px !important;
  line-height: 1.6;
}

.tool-json-error {
  color: #f53f3f;
  font-size: 12px;
  margin-top: 4px;
}

/* Tool Calls 展示区 */
.result-tool-calls {
  padding: 10px 16px;
  border-top: 1px solid #e5e6eb;
  background: #f9f0ff;
}

.tool-calls-title {
  font-size: 12px;
  font-weight: 600;
  color: #722ed1;
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 8px;
}

.tool-call-item {
  background: #fff;
  border: 1px solid #e8d5f5;
  border-radius: 4px;
  padding: 8px 10px;
  margin-bottom: 6px;
}

.tool-call-item:last-child {
  margin-bottom: 0;
}

.tc-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.tc-id {
  font-size: 11px;
  color: #86909c;
  font-family: 'SF Mono', monospace;
}

.tc-args {
  font-size: 12px;
  line-height: 1.5;
  margin: 0;
  color: #4e5969;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'SF Mono', 'Menlo', 'Monaco', monospace;
}

.no-tool-calls {
  font-size: 12px;
  color: #c0c4cc;
  font-style: italic;
}

/* 预设 Prompt 模板栏 */
.preset-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.preset-label {
  font-size: 13px;
  color: #4e5969;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 4px;
}

.preset-categories {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.preset-cat-tag {
  cursor: pointer;
  transition: all 0.15s;
}

.preset-cat-tag:hover {
  color: #165dff;
  border-color: #165dff;
}

.preset-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.preset-tag {
  cursor: pointer;
  transition: all 0.15s;
}

.preset-tag:hover {
  color: #165dff;
  border-color: #165dff;
}

.input-actions {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}

.left-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
  flex-wrap: wrap;
}

.selected-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.right-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

/* 模型选择器弹窗 */
.model-picker {
  width: 420px;
  max-height: 400px;
}

.vendor-quick-select {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid #e5e6eb;
}

.vendor-tag {
  cursor: pointer;
  transition: all 0.15s;
}

.vendor-tag:hover {
  opacity: 0.8;
}

.model-picker-list {
  max-height: 300px;
  overflow-y: auto;
}

.model-picker-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.15s;
}

.model-picker-item:hover {
  background: #f2f3f5;
}

.model-picker-item.selected {
  background: #e8f3ff;
}

.vm-label {
  font-size: 13px;
  font-weight: 500;
  color: #1d2129;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 180px;
}

.no-models {
  text-align: center;
  color: #86909c;
  padding: 16px;
  font-size: 13px;
}

/* 评委卡片 */
.judge-card {
  background: linear-gradient(135deg, #fff7e6 0%, #fff 100%);
  border: 1px solid #ffe4ba;
  border-radius: 8px;
  padding: 16px 20px;
  margin-bottom: 16px;
}

.judge-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.judge-ranking {
  display: flex;
  gap: 16px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.rank-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.rank-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 700;
  color: #fff;
}

.rank-1 { background: linear-gradient(135deg, #ffd700, #ffb800); }
.rank-2 { background: linear-gradient(135deg, #c0c0c0, #a0a0a0); }
.rank-3 { background: linear-gradient(135deg, #cd7f32, #b8651a); }

.rank-model {
  font-size: 13px;
  font-weight: 500;
}

.rank-score {
  font-size: 13px;
  color: #ff7d00;
  font-weight: 600;
}

.judge-comment {
  font-size: 13px;
  line-height: 1.6;
}

/* 结果网格 */
.result-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(580px, 1fr));
  gap: 12px;
}

.result-card {
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
  overflow: hidden;
  border: 1px solid #e5e6eb;
}

.result-card.result-error {
  border-color: #f53f3f33;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  background: #fafbfc;
  border-bottom: 1px solid #e5e6eb;
}

.result-model-name {
  display: flex;
  align-items: center;
  gap: 4px;
}

.vendor-label {
  font-size: 12px;
  color: #86909c;
}

.model-label {
  font-size: 14px;
  font-weight: 600;
  color: #1d2129;
}

.result-meta {
  display: flex;
  gap: 4px;
}

.result-content {
  padding: 12px 16px;
  max-height: 400px;
  overflow-y: auto;
}

.result-text {
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  font-family: inherit;
  color: #1d2129;
}

.result-error-msg {
  padding: 12px 16px;
  font-size: 13px;
  color: #f53f3f;
  display: flex;
  align-items: center;
  gap: 6px;
}

.result-identity {
  padding: 6px 16px 10px;
  font-size: 12px;
  color: #86909c;
  display: flex;
  align-items: center;
  gap: 4px;
  border-top: 1px dashed #e5e6eb;
}

/* 底部工具栏 */
.result-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 12px;
  padding: 8px 0;
}

.total-time {
  font-size: 12px;
  color: #86909c;
}

.toolbar-actions {
  display: flex;
  gap: 8px;
}

/* 空状态 */
.empty-state {
  padding: 80px 0;
}

/* 响应式 */
@media (max-width: 768px) {
  .result-grid {
    grid-template-columns: 1fr;
  }

  .input-actions {
    flex-direction: column;
  }

  .left-actions,
  .right-actions {
    width: 100%;
    flex-wrap: wrap;
  }
}
</style>
