<template>
  <div class="optimizer-page">
    <!-- 左侧：输入区 -->
    <div class="input-panel">
      <div class="panel-card">
        <div class="input-scroll-area">
        <div class="panel-title">
          <icon-edit style="color:#165dff;font-size:16px" />
          原始提示词
        </div>
        <a-textarea
          v-model="rawPrompt"
          placeholder="输入你想优化的提示词（人话就行，比如：帮我看看这个bug是什么原因）"
          :auto-size="{ minRows: 6, maxRows: 16 }"
          class="raw-input"
        />

        <!-- 补充上下文 -->
        <div class="context-section">
          <div class="section-label">
            补充上下文
            <span class="optional-hint">（可选）</span>
          </div>
          <a-textarea
            v-model="context"
            placeholder="补充技术栈、环境信息、约束条件等，帮助 LLM 更好地理解你的场景..."
            :auto-size="{ minRows: 2, maxRows: 6 }"
          />
        </div>

        <!-- 期望输出格式 -->
        <div class="format-section">
          <div class="section-label">
            期望输出格式
            <span class="optional-hint">（可选）</span>
          </div>
          <a-input
            v-model="outputFormat"
            placeholder="如：Markdown表格、JSON、分步骤说明、代码+注释..."
          />
        </div>

        <!-- 优化模型选择（可选） -->
        <div class="model-ref-section">
          <div class="section-label">
            优化使用的模型
            <span class="optional-hint">（可选，留空则自动选择）</span>
          </div>
          <a-select
            v-model="selectedOptimizeModel"
            placeholder="留空 = 路由池自动选择"
            :loading="loadingOptimizeModels"
            allow-clear
            style="width:100%"
          >
            <a-option
              v-for="m in optimizeModelList"
              :key="`${m.group_id}-${m.model_id}`"
              :value="`${m.group_id}-${m.model_id}`"
              :label="`${m.vendor} / ${m.model}`"
            />
          </a-select>
        </div>

        <!-- 优化方向选择 -->
        <div class="strategy-section">
          <div class="section-label">
            优化方向
            <span class="optional-hint">（可选，默认自动分析）</span>
            <a-spin v-if="recommending" :size="12" style="margin-left:6px" />
          </div>

          <!-- 分组标题 + 卡片，循环 strategyGroups -->
          <div v-for="group in strategyGroups" :key="group.group" class="strategy-group">
            <!-- 分组可折叠头部 -->
            <div
              class="strategy-group-header"
              :class="{ 'has-recommended': group.items.some((s: any) => recommendedKeys.includes(s.key)) }"
              @click="toggleGroup(group.group)"
            >
              <span class="strategy-group-label">{{ group.label }}</span>
              <span class="strategy-group-count">{{ group.items.length }} 个</span>
              <icon-down
                class="strategy-chevron"
                :class="{ collapsed: collapsedGroups.has(group.group) }"
              />
            </div>

            <!-- 分组内容（可折叠） -->
            <div v-show="!collapsedGroups.has(group.group)">
              <div class="strategy-grid">
                <div
                  v-for="s in group.items"
                  :key="s.key"
                  class="strategy-card"
                  :class="{
                    active: selectedStrategy === s.key,
                    recommended: recommendedKeys.includes(s.key)
                  }"
                  @click="selectedStrategy = s.key"
                >
                  <!-- 推荐角标 -->
                  <span v-if="recommendedKeys.includes(s.key)" class="recommend-badge">✨ 推荐</span>
                  <span class="strategy-name">{{ s.name }}</span>
                  <span class="strategy-desc">{{ s.description }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 推荐理由 -->
          <div v-if="recommendedKeys.length && recommendReason" class="recommend-reason">
            💡 {{ recommendReason }}
          </div>
        </div>

        <!-- 优化按钮 -->
        </div><!-- end input-scroll-area -->
        <a-button
          type="primary"
          long
          size="large"
          :loading="loading"
          :disabled="!rawPrompt.trim()"
          @click="handleOptimize"
          class="optimize-btn"
        >
          <template #icon><icon-magic-stick /></template>
          {{ loading ? '优化中...' : '优化提示词' }}
        </a-button>
      </div>
    </div>

    <!-- 右侧：输出区 -->
    <div class="output-panel">
      <div class="panel-card">
        <div class="output-scroll-inner">
        <div class="panel-title">
          <icon-check-circle style="color:#00b42a;font-size:16px" />
          优化结果
          <a-tag v-if="result" size="small" color="green" style="margin-left:8px">
            {{ result.latency_ms }}ms
          </a-tag>
          <a-tag v-if="result" size="small" color="arcoblue" style="margin-left:4px">
            {{ result.model_vendor }}/{{ result.model_name }}
          </a-tag>
          <a-tag
            v-if="result && (result.tokens_input != null || result.tokens_output != null)"
            size="small"
            color="gray"
            style="margin-left:4px"
          >
            ↑{{ result.tokens_input ?? '-' }} ↓{{ result.tokens_output ?? '-' }} tokens
          </a-tag>
        </div>

        <!-- 优化后的 Prompt -->
        <div v-if="result" class="result-section">
          <div class="result-header">
            <span class="result-label">优化后的 Prompt</span>
            <div class="result-actions">
              <a-button size="small" @click="copyResult">
                <template #icon><icon-copy /></template>
                复制
              </a-button>
            </div>
          </div>
          <div class="result-content">
            <a-textarea
              v-model="editableOptimized"
              :auto-size="{ minRows: 8, maxRows: 30 }"
              class="result-textarea"
            />
          </div>

          <!-- 优化建议 -->
          <div v-if="result.tips.length" class="tips-section">
            <div class="tips-title">
              <iconbulb style="color:#ff7d00;font-size:14px" />
              优化建议
            </div>
            <div v-for="(tip, i) in result.tips" :key="i" class="tip-item">
              {{ tip }}
            </div>
          </div>

          <!-- 换个优化角度 -->
          <div class="retry-section">
            <div class="retry-header" @click="showRetry = !showRetry">
              <icon-refresh style="color:#722ed7;font-size:13px" />
              <span class="retry-title">换个优化角度</span>
              <span class="retry-hint">用不同策略重新优化，对比效果</span>
              <a-tag v-if="!showRetry" size="small" color="gray" style="margin-left:auto">点击展开</a-tag>
              <icon-down v-if="!showRetry" style="color:#86909c;font-size:12px" />
              <icon-up v-else style="color:#86909c;font-size:12px;margin-left:auto" />
            </div>
            <div v-if="showRetry" class="retry-grid-wrap">
              <div class="retry-grid">
                <div
                  v-for="s in strategyGroups.flatMap(g => g.items)"
                  :key="s.key"
                  class="retry-btn"
                  :class="{ active: result.strategy_used === s.key, loading: loading && pendingStrategy === s.key }"
                  @click="handleRetryWithStrategy(s.key)"
                >
                  <span class="retry-btn-name">{{ s.name }}</span>
                  <span class="retry-btn-desc">{{ s.description }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 对比测试区域 -->
          <div class="compare-section">
            <div class="compare-header" @click="showCompare = !showCompare">
              <icon-swap style="color:#722ed7;font-size:14px" />
              <span class="compare-title">对比测试</span>
              <a-tag v-if="!showCompare" size="small" color="gray">点击展开</a-tag>
              <icon-down v-if="!showCompare" style="color:#86909c;font-size:12px" />
              <icon-up v-else style="color:#86909c;font-size:12px" />
            </div>

            <div v-if="showCompare" class="compare-body">
              <div class="compare-desc">
                选择一个模型，分别用「原始提示词」和「优化后的提示词」调用，对比回答质量。
              </div>

              <!-- 模型选择器 -->
              <div class="model-select-row">
                <span class="select-label">测试模型：</span>
                <a-select
                  v-model="selectedTestModel"
                  placeholder="选择一个模型进行对比测试"
                  :loading="loadingModels"
                  style="flex:1"
                  allow-clear
                >
                  <a-option
                    v-for="m in availableModels"
                    :key="`${m.group_id}-${m.model_id}`"
                    :value="`${m.group_id}-${m.model_id}`"
                    :label="`${m.vendor} / ${m.model}`"
                  >
                    <div class="model-option">
                      <span class="model-option-name">{{ m.vendor }} / {{ m.model }}</span>
                      <a-tag v-if="m.remark" size="small" color="gray">{{ m.remark }}</a-tag>
                    </div>
                  </a-option>
                </a-select>
              </div>

              <div class="compare-actions">
                <a-button
                  type="outline"
                  long
                  size="large"
                  :loading="asking"
                  :disabled="!selectedTestModel || comparing"
                  @click="handleAsk"
                  class="ask-btn"
                >
                  <template #icon><icon-send /></template>
                  {{ asking ? '提问中...' : '直接提问' }}
                </a-button>
                <a-button
                  type="outline"
                  long
                  size="large"
                  :loading="comparing"
                  :disabled="!selectedTestModel || asking"
                  @click="handleCompareTest"
                  class="compare-btn"
                >
                  <template #icon><icon-swap /></template>
                  {{ comparing ? '测试中...' : '对比测试' }}
                </a-button>
              </div>

              <!-- 直接提问结果 -->
              <div v-if="askResult" class="ask-result">
                <div class="ask-result-header">
                  <span class="ask-result-title">回答</span>
                  <a-tag size="small" :color="askResult.ok ? 'green' : 'red'">
                    {{ askResult.ok ? `${askResult.latency_ms}ms` : '失败' }}
                  </a-tag>
                  <a-tag size="small" color="arcoblue">
                    {{ askResult.test_model_vendor }} / {{ askResult.test_model_name }}
                  </a-tag>
                </div>
                <div class="ask-result-body">
                  <div v-if="askResult.ok" class="ask-reply">{{ askResult.reply }}</div>
                  <a-alert v-else type="error">{{ askResult.error }}</a-alert>
                </div>
              </div>

              <!-- 对比结果 -->
              <div v-if="compareResult" class="compare-results">
                <a-row :gutter="12">
                  <a-col :span="12">
                    <div class="compare-card compare-card-raw">
                      <div class="compare-card-header">
                        <span>原始提示词回答</span>
                        <a-tag size="small" :color="compareResult.raw_result.ok ? 'green' : 'red'">
                          {{ compareResult.raw_result.ok ? `${compareResult.raw_result.latency_ms}ms` : '失败' }}
                        </a-tag>
                      </div>
                      <div class="compare-card-body">
                        <div v-if="compareResult.raw_result.ok" class="compare-reply">
                          {{ compareResult.raw_result.reply }}
                        </div>
                        <a-alert v-else type="error">{{ compareResult.raw_result.error }}</a-alert>
                      </div>
                    </div>
                  </a-col>
                  <a-col :span="12">
                    <div class="compare-card compare-card-optimized">
                      <div class="compare-card-header">
                        <span>优化后提示词回答</span>
                        <a-tag size="small" :color="compareResult.optimized_result.ok ? 'green' : 'red'">
                          {{ compareResult.optimized_result.ok ? `${compareResult.optimized_result.latency_ms}ms` : '失败' }}
                        </a-tag>
                      </div>
                      <div class="compare-card-body">
                        <div v-if="compareResult.optimized_result.ok" class="compare-reply">
                          {{ compareResult.optimized_result.reply }}
                        </div>
                        <a-alert v-else type="error">{{ compareResult.optimized_result.error }}</a-alert>
                      </div>
                    </div>
                  </a-col>
                </a-row>
              </div>
            </div>
          </div>

          <!-- 多模型对比区域 -->
          <div class="compare-section multi-compare-section">
            <div class="compare-header" @click="showMultiCompare = !showMultiCompare">
              <icon-apps style="color:#0072d9;font-size:14px" />
              <span class="compare-title">多模型对比</span>
              <span style="font-size:12px;color:#86909c;margin-left:4px">同一提示词，横向对比多个模型效果</span>
              <a-tag v-if="!showMultiCompare" size="small" color="gray" style="margin-left:auto">点击展开</a-tag>
              <icon-down v-if="!showMultiCompare" style="color:#86909c;font-size:12px" />
              <icon-up v-else style="color:#86909c;font-size:12px;margin-left:auto" />
            </div>

            <div v-if="showMultiCompare" class="compare-body">
              <div class="compare-desc">
                选择 2-6 个模型，用「优化后的提示词」同时调用，并排展示各模型回答，帮你选出最合适的模型。
              </div>

              <!-- 多模型选择器 -->
              <div class="model-select-row">
                <span class="select-label">选择模型：</span>
                <a-select
                  v-model="selectedMultiModels"
                  multiple
                  :max-tag-count="3"
                  placeholder="选择 2-6 个模型进行横向对比"
                  :loading="loadingModels"
                  style="flex:1"
                  allow-clear
                >
                  <a-option
                    v-for="m in availableModels"
                    :key="`${m.group_id}-${m.model_id}`"
                    :value="`${m.group_id}-${m.model_id}`"
                    :label="`${m.vendor} / ${m.model}`"
                    :disabled="selectedMultiModels.length >= 6 && !selectedMultiModels.includes(`${m.group_id}-${m.model_id}`)"
                  >
                    <div class="model-option">
                      <span class="model-option-name">{{ m.vendor }} / {{ m.model }}</span>
                      <a-tag v-if="m.remark" size="small" color="gray">{{ m.remark }}</a-tag>
                    </div>
                  </a-option>
                </a-select>
              </div>

              <a-button
                type="primary"
                long
                size="large"
                :loading="multiComparing"
                :disabled="selectedMultiModels.length < 2"
                @click="handleMultiModelCompare"
                class="multi-compare-btn"
              >
                <template #icon><icon-apps /></template>
                {{ multiComparing ? `对比中 (${selectedMultiModels.length} 个模型并发)...` : `开始多模型对比 (已选 ${selectedMultiModels.length} 个)` }}
              </a-button>

              <!-- 多模型对比结果 -->
              <div v-if="multiCompareResult" class="multi-compare-results">
                <div
                  v-for="item in multiCompareResult.results"
                  :key="`${item.group_id}-${item.model_id}`"
                  class="multi-compare-card"
                  :class="{ 'multi-compare-card-error': !item.ok }"
                >
                  <div class="multi-compare-card-header">
                    <span class="multi-compare-model-name">{{ item.vendor }} / {{ item.model_name }}</span>
                    <a-tag size="small" :color="item.ok ? 'green' : 'red'">
                      {{ item.ok ? `${item.latency_ms}ms` : '失败' }}
                    </a-tag>
                  </div>
                  <div class="multi-compare-card-body">
                    <div v-if="item.ok" class="multi-compare-reply">{{ item.reply }}</div>
                    <a-alert v-else type="error" :title="item.error || '未知错误'" />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 空状态 -->
        <div v-else class="empty-state">
          <icon-magic-stick style="font-size:48px;color:#c9cdd4" />
          <div class="empty-text">在左侧输入你的提示词，点击「优化提示词」即可</div>
        </div>
        </div><!-- end output-scroll-inner -->
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { IconDown, IconSend } from '@arco-design/web-vue/es/icon'
import {
  apiOptimizeStrategies,
  apiOptimizePrompt,
  apiCompareTest,
  apiAskWithOptimized,
  apiMultiModelCompare,
  apiOptimizerModels,
  apiPlaygroundModels,
  apiRecommendStrategy,
  type StrategyItem,
  type StrategyGroup,
  type OptimizeResponse,
  type AvailableModel,
  type CompareTestResponse,
  type AskResponse,
  type MultiModelCompareItem,
  type MultiModelCompareResponse,
} from '../api'

const rawPrompt = ref('')
const context = ref('')
const outputFormat = ref('')
const selectedStrategy = ref('auto')
const strategyGroups = ref<StrategyGroup[]>([])
const recommendedKeys = ref<string[]>([])
const recommendReason = ref('')
const recommending = ref(false)
const collapsedGroups = ref<Set<string>>(new Set(['scene']))   // scene 组默认折叠
const selectedOptimizeModel = ref('')
const optimizeModelList = ref<AvailableModel[]>([])
const loadingOptimizeModels = ref(false)
const loading = ref(false)
const pendingStrategy = ref('')   // 记录当前正在优化的策略 key，用于按钮 loading 态
const result = ref<OptimizeResponse | null>(null)
const editableOptimized = ref('')

// 对比测试相关
const showRetry = ref(false)
const showCompare = ref(false)
const selectedTestModel = ref('')
const availableModels = ref<AvailableModel[]>([])
const loadingModels = ref(false)
const comparing = ref(false)
const compareResult = ref<CompareTestResponse | null>(null)
const asking = ref(false)
const askResult = ref<AskResponse | null>(null)

// 多模型对比相关
const showMultiCompare = ref(false)
const selectedMultiModels = ref<string[]>([])
const multiComparing = ref(false)
const multiCompareResult = ref<MultiModelCompareResponse | null>(null)

onMounted(async () => {
  try {
    const { data } = await apiOptimizeStrategies()
    strategyGroups.value = data
  } catch {
    strategyGroups.value = [
      {
        group: 'technique',
        label: '通用技术策略',
        items: [
          { key: 'auto', name: '🤖 帮我分析', description: '不知道选哪个？让 AI 自动判断最合适的优化方向' },
          { key: 'role', name: '🎭 专家口吻', description: '我想要像专家一样权威、专业的回答' },
          { key: 'cot', name: '🧠 逐步分析', description: '我需要 AI 一步步推理、展示思考过程' },
          { key: 'few_shot', name: '📋 符合格式', description: '我想要输出严格按照某个样式/示例来' },
          { key: 'constraint', name: '🔒 别乱发挥', description: '我不想让 AI 自由发挥，要严格按规则来' },
          { key: 'format', name: '📊 结构化输出', description: '我需要表格、JSON、Markdown 等结构化格式' },
        ],
      },
    ]
  }

  // 加载可用模型列表（排除纯思考模型和视觉模型）
  loadingOptimizeModels.value = true
  try {
    const { data } = await apiOptimizerModels()
    optimizeModelList.value = data
  } catch {
    // 加载失败不阻断，允许继续用路由池
  } finally {
    loadingOptimizeModels.value = false
  }
})

// 展开对比测试时加载模型列表
watch(showCompare, async (val) => {
  if (val && availableModels.value.length === 0) {
    loadingModels.value = true
    try {
      const { data } = await apiPlaygroundModels()
      availableModels.value = data
    } catch {
      Message.error('加载模型列表失败')
    } finally {
      loadingModels.value = false
    }
  }
})

// 展开多模型对比时复用模型列表
watch(showMultiCompare, async (val) => {
  if (val && availableModels.value.length === 0) {
    loadingModels.value = true
    try {
      const { data } = await apiPlaygroundModels()
      availableModels.value = data
    } catch {
      Message.error('加载模型列表失败')
    } finally {
      loadingModels.value = false
    }
  }
})

// ---------- AI 推荐策略 ----------
let recommendTimer: ReturnType<typeof setTimeout> | null = null

function triggerRecommend() {
  if (recommendTimer) clearTimeout(recommendTimer)
  if (!rawPrompt.value.trim() || rawPrompt.value.trim().length < 8) {
    recommendedKeys.value = []
    recommendReason.value = ''
    return
  }
  recommendTimer = setTimeout(async () => {
    recommending.value = true
    try {
      const { data } = await apiRecommendStrategy({ raw_prompt: rawPrompt.value.trim() })
      recommendedKeys.value = data.recommended_keys
      recommendReason.value = data.reason
    } catch {
      recommendedKeys.value = []
      recommendReason.value = ''
    } finally {
      recommending.value = false
    }
  }, 800)
}

watch(rawPrompt, triggerRecommend)

async function handleOptimize() {
  if (!rawPrompt.value.trim()) return
  loading.value = true
  result.value = null
  compareResult.value = null
  askResult.value = null
  multiCompareResult.value = null

  try {
    let model_ref = null
    if (selectedOptimizeModel.value) {
      const [group_id, model_id] = selectedOptimizeModel.value.split('-').map(Number)
      model_ref = { group_id, model_id }
    }

    const { data } = await apiOptimizePrompt({
      raw_prompt: rawPrompt.value.trim(),
      strategy: selectedStrategy.value,
      context: context.value.trim() || null,
      output_format: outputFormat.value.trim() || null,
      model_ref,
    })
    result.value = data
    editableOptimized.value = data.optimized_prompt
  } catch (e: any) {
    const msg = e.response?.data?.detail || e.message || '优化失败'
    Message.error(msg)
  } finally {
    loading.value = false
  }
}

function copyResult() {
  if (!editableOptimized.value) return
  navigator.clipboard.writeText(editableOptimized.value).then(() => {
    Message.success('已复制到剪贴板')
  })
}

async function handleRetryWithStrategy(strategyKey: string) {
  if (!rawPrompt.value.trim() || loading.value) return
  selectedStrategy.value = strategyKey
  pendingStrategy.value = strategyKey
  loading.value = true
  // 不清空 result，保留旧结果到新结果回来前（避免闪烁）

  try {
    let model_ref = null
    if (selectedOptimizeModel.value) {
      const [group_id, model_id] = selectedOptimizeModel.value.split('-').map(Number)
      model_ref = { group_id, model_id }
    }

    const { data } = await apiOptimizePrompt({
      raw_prompt: rawPrompt.value.trim(),
      strategy: strategyKey,
      context: context.value.trim() || null,
      output_format: outputFormat.value.trim() || null,
      model_ref,
    })
    result.value = data
    editableOptimized.value = data.optimized_prompt
    compareResult.value = null
    askResult.value = null
    multiCompareResult.value = null
  } catch (e: any) {
    const msg = e.response?.data?.detail || e.message || '优化失败'
    Message.error(msg)
  } finally {
    loading.value = false
    pendingStrategy.value = ''
  }
}

async function handleCompareTest() {
  if (!result.value || !selectedTestModel.value) return
  comparing.value = true
  compareResult.value = null

  const [groupId, modelId] = selectedTestModel.value.split('-').map(Number)

  try {
    const { data } = await apiCompareTest({
      raw_prompt: result.value.raw_prompt,
      optimized_prompt: editableOptimized.value,
      test_model: { group_id: groupId, model_id: modelId },
    })
    compareResult.value = data
  } catch (e: any) {
    const msg = e.response?.data?.detail || e.message || '对比测试失败'
    Message.error(msg)
  } finally {
    comparing.value = false
  }
}

async function handleAsk() {
  if (!result.value || !selectedTestModel.value) return
  asking.value = true
  askResult.value = null
  compareResult.value = null

  const [groupId, modelId] = selectedTestModel.value.split('-').map(Number)

  try {
    const { data } = await apiAskWithOptimized({
      optimized_prompt: editableOptimized.value,
      test_model: { group_id: groupId, model_id: modelId },
    })
    askResult.value = data
  } catch (e: any) {
    const msg = e.response?.data?.detail || e.message || '提问失败'
    Message.error(msg)
  } finally {
    asking.value = false
  }
}

async function handleMultiModelCompare() {
  if (!result.value || selectedMultiModels.value.length === 0) return
  multiComparing.value = true
  multiCompareResult.value = null

  const testModels = selectedMultiModels.value.map(key => {
    const [groupId, modelId] = key.split('-').map(Number)
    return { group_id: groupId, model_id: modelId }
  })

  try {
    const { data } = await apiMultiModelCompare({
      optimized_prompt: editableOptimized.value,
      test_models: testModels,
    })
    multiCompareResult.value = data
  } catch (e: any) {
    const msg = e.response?.data?.detail || e.message || '多模型对比失败'
    Message.error(msg)
  } finally {
    multiComparing.value = false
  }
}

// 策略 key → name 映射（用于历史记录展示）
function getStrategyName(key: string): string {
  for (const group of strategyGroups.value) {
    const found = group.items.find((s: StrategyItem) => s.key === key)
    if (found) return found.name
  }
  return key
}

// 分组折叠/展开
function toggleGroup(groupKey: string) {
  const next = new Set(collapsedGroups.value)
  if (next.has(groupKey)) {
    next.delete(groupKey)
  } else {
    next.add(groupKey)
  }
  collapsedGroups.value = next
}


</script>

<style scoped>
.optimizer-page {
  display: flex;
  gap: 20px;
  height: 100%;
  overflow: hidden;       /* 整体不滚动 */
}

.input-panel {
  flex: 1;
  min-width: 0;
  min-height: 0;          /* flex 生效 */
}

.output-panel {
  flex: 1;
  min-width: 0;
  min-height: 0;
}

.output-panel .panel-card {
  height: 100%;
  overflow-y: auto;
  scrollbar-gutter: stable;
  padding: 0;   /* padding 移到 output-scroll-inner 内部，避免 overflow 容器 padding-bottom 失效 */
}

.output-scroll-inner {
  padding: 20px;
}

.panel-card {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
  display: flex;
  flex-direction: column;
  min-height: 100%;
}

.input-panel .panel-card {
  height: 100%;
  overflow: hidden;          /* 自身不滚动，交给内部 scroll area */
  display: flex;
  flex-direction: column;
  padding: 0;                /* 由内部子元素控制间距 */
}

.input-scroll-area {
  flex: 1;
  overflow-y: auto;
  scrollbar-gutter: stable;
  padding: 20px 20px 12px;   /* 顶/左右/底 */
}

.optimize-btn {
  flex-shrink: 0;
  margin: 0;
  border-radius: 0 0 8px 8px;  /* 跟 panel-card 圆角保持一致 */
  height: 52px;
}

.panel-title {
  font-size: 15px;
  font-weight: 600;
  color: #1d2129;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.raw-input {
  margin-bottom: 16px;
}

.section-label {
  font-size: 13px;
  font-weight: 500;
  color: #4e5969;
  margin-bottom: 8px;
}

.optional-hint {
  color: #86909c;
  font-weight: 400;
  font-size: 12px;
}

.context-section,
.format-section,
.model-ref-section {
  margin-bottom: 16px;
}

.result-section {
  margin-top: 0;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.result-label {
  font-size: 13px;
  font-weight: 500;
  color: #4e5969;
}

.result-actions {
  display: flex;
  gap: 6px;
}

.result-textarea {
  font-size: 13px;
  line-height: 1.6;
}

.result-content {
  margin-bottom: 16px;
}

.tips-section {
  background: #fff7e8;
  border: 1px solid #ffe4ba;
  border-radius: 6px;
  padding: 12px 16px;
  margin-bottom: 16px;
}

.tips-title {
  font-size: 13px;
  font-weight: 600;
  color: #1d2129;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.tip-item {
  font-size: 12px;
  color: #4e5969;
  padding: 4px 0;
  padding-left: 16px;
  position: relative;
}

.tip-item::before {
  content: '-';
  position: absolute;
  left: 4px;
  color: #ff7d00;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 0;
  gap: 12px;
}

.empty-text {
  font-size: 14px;
  color: #86909c;
}

/* 对比测试 */
.compare-section {
  margin-top: 8px;
  border: 1px solid #e5e6eb;
  border-radius: 8px;
  overflow: hidden;
}

.compare-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  cursor: pointer;
  background: #f7f8fa;
  transition: background 0.2s;
}

.compare-header:hover {
  background: #f2f3f5;
}

.compare-title {
  font-size: 14px;
  font-weight: 600;
  color: #1d2129;
  flex: 1;
}

.compare-body {
  padding: 16px;
}

.compare-desc {
  font-size: 12px;
  color: #86909c;
  margin-bottom: 12px;
}

.model-select-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.select-label {
  font-size: 13px;
  font-weight: 500;
  color: #4e5969;
  white-space: nowrap;
}

.model-option {
  display: flex;
  align-items: center;
  gap: 8px;
}

.model-option-name {
  font-size: 13px;
}

.compare-actions {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.ask-btn,
.compare-btn {
  flex: 1;
}

.ask-result {
  border: 1px solid #d1e9ff;
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 8px;
}

.ask-result-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: #f0f8ff;
  border-bottom: 1px solid #d1e9ff;
}

.ask-result-title {
  font-size: 12px;
  font-weight: 600;
  color: #0072d9;
  flex: 1;
}

.ask-result-body {
  padding: 12px 14px;
}

.ask-reply {
  font-size: 13px;
  color: #1d2129;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.compare-card {
  border: 1px solid #e5e6eb;
  border-radius: 6px;
  overflow: hidden;
}

.compare-card-raw {
  border-left: 3px solid #f53f3f;
}

.compare-card-optimized {
  border-left: 3px solid #00b42a;
}

.compare-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  font-size: 12px;
  font-weight: 600;
  color: #4e5969;
  background: #f7f8fa;
}

.compare-card-body {
  padding: 12px;
}

.compare-reply {
  font-size: 13px;
  color: #1d2129;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 400px;
  overflow-y: auto;
}

/* 多模型对比 */
.multi-compare-section {
  border-color: #d1e9ff;
}

.multi-compare-section .compare-header {
  background: #f0f8ff;
}

.multi-compare-section .compare-header:hover {
  background: #e5f3ff;
}

.multi-compare-btn {
  margin-bottom: 16px;
}

.multi-compare-results {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.multi-compare-card {
  border: 1px solid #e5e6eb;
  border-radius: 8px;
  overflow: hidden;
}

.multi-compare-card-error {
  border-color: #ffcdd2;
}

.multi-compare-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: #f7f8fa;
  border-bottom: 1px solid #e5e6eb;
}

.multi-compare-model-name {
  font-size: 12px;
  font-weight: 600;
  color: #1d2129;
  flex: 1;
}

.multi-compare-card-body {
  padding: 12px 14px;
}

.multi-compare-reply {
  font-size: 13px;
  color: #1d2129;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 360px;
  overflow-y: auto;
}

/* 换个优化角度 */
.retry-section {
  margin-bottom: 16px;
  border: 1px solid #e5e6eb;
  border-radius: 8px;
  overflow: hidden;
}

.retry-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 16px;
  background: #f7f8fa;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s;
}

.retry-header:hover {
  background: #f0f1f3;
}

.retry-title {
  font-size: 13px;
  font-weight: 600;
  color: #1d2129;
}

.retry-hint {
  font-size: 12px;
  color: #86909c;
  margin-left: 4px;
}

.retry-grid-wrap {
  max-height: 320px;
  overflow-y: auto;
  scrollbar-gutter: stable;
}

.retry-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1px;
  background: #e5e6eb;
}

.retry-btn {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px;
  background: #fff;
  cursor: pointer;
  transition: background 0.15s;
}

.retry-btn:hover {
  background: #f2f3f5;
}

.retry-btn.active {
  background: #e8f3ff;
}

.retry-btn.loading {
  opacity: 0.6;
  cursor: not-allowed;
}

.retry-btn-name {
  font-size: 12px;
  font-weight: 600;
  color: #1d2129;
}

.retry-btn-desc {
  font-size: 11px;
  color: #86909c;
  line-height: 1.4;
}

/* 策略分组 */
.strategy-section {
  margin-bottom: 0;
}

.strategy-group {
  margin-bottom: 8px;
}

.strategy-group-header {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 2px;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.15s;
  user-select: none;
}

.strategy-group-header:hover {
  background: #f7f8fa;
}

.strategy-group-label {
  font-size: 13px;
  font-weight: 500;
  color: #1d2129;
}

.strategy-group-count {
  font-size: 12px;
  color: #86909c;
}

.strategy-chevron {
  margin-left: auto;
  color: #86909c;
  font-size: 12px;
  transition: transform 0.2s;
  flex-shrink: 0;
}

.strategy-chevron.collapsed {
  transform: rotate(-90deg);
}

/* 策略网格 */
.strategy-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  max-height: 260px;
  overflow-y: auto;
  border-radius: 4px;
}

.strategy-grid::-webkit-scrollbar {
  width: 4px;
}
.strategy-grid::-webkit-scrollbar-track {
  background: transparent;
}
.strategy-grid::-webkit-scrollbar-thumb {
  background: #c9cdd4;
  border-radius: 2px;
}

.strategy-card {
  position: relative;
  padding: 8px 10px;
  border: 1.5px solid #e5e6eb;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.strategy-card:hover {
  border-color: #165dff;
  background: #f2f6ff;
}

.strategy-card.active {
  border-color: #165dff;
  background: #e8f3ff;
}

.strategy-card.recommended {
  border-color: #ff7d00;
  background: #fff7e8;
}

.strategy-card.recommended.active {
  border-color: #ff7d00;
  background: #ffe7ba;
}

.recommend-badge {
  position: absolute;
  top: -1px;
  right: -1px;
  font-size: 10px;
  background: #ff7d00;
  color: #fff;
  padding: 1px 5px;
  border-radius: 0 6px 0 6px;
  line-height: 16px;
}

.strategy-name {
  font-size: 12px;
  font-weight: 500;
  color: #1d2129;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.strategy-desc {
  font-size: 11px;
  color: #86909c;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.recommend-reason {
  margin-top: 6px;
  font-size: 12px;
  color: #ff7d00;
  background: #fff7e8;
  border-radius: 4px;
  padding: 4px 8px;
}



@media (max-width: 900px) {
  .optimizer-page {
    flex-direction: column;
    overflow-y: auto;   /* 移动端允许页面滚动 */
  }
  .input-panel,
  .output-panel {
    overflow-y: visible; /* 堆叠时不需要独立滚动 */
    min-height: auto;
  }
  .input-panel .panel-card {
    height: auto;
  }
}
</style>
