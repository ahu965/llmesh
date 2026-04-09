<template>
  <div class="simulator-page">
    <!-- 参数面板 -->
    <div class="param-card">
      <div class="param-title">
        <icon-experiment style="color:#165dff;font-size:16px" />
        模拟 get_llm 调用参数
      </div>
      <div class="param-body">
        <a-form layout="inline" :model="form" class="param-form">
          <a-form-item label="prefer">
            <a-input
              v-model="form.prefer"
              placeholder="如 openai,gpt（逗号分隔）"
              allow-clear
              style="width:220px"
            />
          </a-form-item>

          <a-form-item label="thinking">
            <a-select v-model="form.thinking" style="width:120px">
              <a-option :value="null">None（不限）</a-option>
              <a-option :value="true">True（开启）</a-option>
              <a-option :value="false">False（关闭）</a-option>
            </a-select>
          </a-form-item>

          <a-form-item label="vision">
            <a-select v-model="form.vision" style="width:140px">
              <a-option :value="null">None（排除视觉）</a-option>
              <a-option :value="true">True（仅视觉）</a-option>
            </a-select>
          </a-form-item>

          <a-form-item label="tags">
            <a-input
              v-model="form.tags"
              placeholder="如 cheap,fast（逗号分隔）"
              allow-clear
              style="width:200px"
            />
          </a-form-item>

          <a-form-item label="exclude_tags">
            <a-input
              v-model="form.exclude_tags"
              placeholder="如 math,translate（逗号分隔）"
              allow-clear
              style="width:200px"
            />
          </a-form-item>

          <a-form-item>
            <a-button type="primary" :loading="loading" @click="run">
              <template #icon><icon-play-arrow /></template>
              模拟
            </a-button>
            <a-button style="margin-left:8px" @click="reset">重置</a-button>
          </a-form-item>
        </a-form>

        <!-- code hint -->
        <div class="code-hint">
          <span class="code-label">等效调用：</span>
          <code class="code-line">{{ codeHint }}</code>
        </div>
      </div>
    </div>

    <!-- 结果区 -->
    <div v-if="result" class="result-area">
      <!-- 过滤摘要 -->
      <div class="filter-summary">
        <a-space wrap>
          <a-tag v-if="result.disabled_count > 0" color="gray">已禁用 {{ result.disabled_count }} 个模型（不参与路由）</a-tag>
          <a-tag v-if="result.filtered_out_count > 0" color="orange">硬过滤 {{ result.filtered_out_count }} 个模型</a-tag>
          <a-tag v-if="form.exclude_tags" color="red">排除 tag：{{ form.exclude_tags }}</a-tag>
          <span v-if="result.filter_reason" class="filter-reason">{{ result.filter_reason }}</span>
        </a-space>
        <span v-if="result.layers.length === 0" style="color:#f53f3f;font-weight:600">
          ⚠ 无可用模型，所有模型已被过滤
        </span>
      </div>

      <!-- 空状态 -->
      <a-empty v-if="result.layers.length === 0" description="当前参数下无可用模型" style="margin-top:40px" />

      <!-- 分层展示 -->
      <div v-for="layer in result.layers" :key="layer.priority" class="layer-block">
        <div class="layer-header" :class="{ 'layer-active': layer.is_active, 'layer-fallback': !layer.is_active }">
          <span class="layer-badge">P{{ layer.priority }}</span>
          <span class="layer-label">{{ layer.is_active ? '🟢 当前路由层（优先选此层）' : '⬇ 降级备用层（前层全挂后启用）' }}</span>
          <span class="layer-count">{{ layer.models.length }} 个模型</span>
        </div>

        <!-- 层内模型列表 -->
        <div class="model-list">
          <!-- 表头 -->
          <div class="model-row model-header">
            <span class="mc-vendor">厂商</span>
            <span class="mc-model">模型名</span>
            <span class="mc-weight">权重</span>
            <span class="mc-bar">命中权重占比</span>
            <span class="mc-tags">特性 / tags</span>
            <span class="mc-remark">备注</span>
          </div>

          <div
            v-for="m in layer.models"
            :key="`${m.vendor}_${m.model}`"
            class="model-row"
            :class="{
              'row-prefer': m.is_prefer_hit,
              'row-tags': !m.is_prefer_hit && m.is_tags_hit,
              'row-inactive': !m.is_prefer_hit && !m.is_tags_hit && hasActiveFilter(layer),
            }"
          >
            <span class="mc-vendor vendor-text">{{ m.vendor }}</span>
            <span class="mc-model model-text">
              {{ m.model }}
              <a-tag v-if="m.is_prefer_hit" size="small" color="arcoblue" style="margin-left:4px">prefer ✓</a-tag>
              <a-tag v-else-if="m.is_tags_hit" size="small" color="green" style="margin-left:4px">tags ✓</a-tag>
            </span>
            <span class="mc-weight">
              <span :class="m.effective_weight > 0 ? 'weight-active' : 'weight-zero'">
                {{ m.weight }}
              </span>
            </span>
            <span class="mc-bar">
              <template v-if="m.effective_weight > 0">
                <div class="bar-wrap">
                  <div class="bar-fill" :style="{ width: m.weight_pct + '%' }" />
                </div>
                <span class="bar-pct">{{ m.weight_pct }}%</span>
              </template>
              <span v-else class="text-muted">— 未参与</span>
            </span>
            <span class="mc-tags">
              <a-space :size="4" wrap>
                <a-tag v-if="m.supports_thinking" size="small" color="purple">thinking</a-tag>
                <a-tag v-if="m.is_thinking_only" size="small" color="orange">仅思考</a-tag>
                <a-tag v-if="m.is_vision" size="small" color="blue">视觉</a-tag>
                <a-tag v-for="t in m.tags" :key="t" size="small" color="gray">{{ t }}</a-tag>
              </a-space>
            </span>
            <span class="mc-remark text-muted">{{ m.remark || m.group_remark || '—' }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 初始提示 -->
    <div v-else-if="!loading" class="init-tip">
      <a-empty description="设置参数后点击「模拟」查看路由结果" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Message } from '@arco-design/web-vue'
import { IconExperiment, IconPlayArrow } from '@arco-design/web-vue/es/icon'
import { apiSimulate, type SimulateResponse, type SimulateLayer } from '../api'

const loading = ref(false)
const result = ref<SimulateResponse | null>(null)

const form = ref({
  prefer: '',
  thinking: null as boolean | null,
  vision: null as boolean | null,
  tags: '',
  exclude_tags: '',
})

function reset() {
  form.value = { prefer: '', thinking: null, vision: null, tags: '', exclude_tags: '' }
  result.value = null
}

async function run() {
  loading.value = true
  try {
    // a-select 绑定 null 值时可能返回字符串 "null"，需显式还原为真实 null/boolean
    const toTriBool = (v: unknown): boolean | null =>
      v === null || v === 'null' || v === undefined ? null : Boolean(v)
    const res = await apiSimulate({
      prefer: form.value.prefer || null,
      thinking: toTriBool(form.value.thinking),
      vision: toTriBool(form.value.vision),
      tags: form.value.tags || null,
      exclude_tags: form.value.exclude_tags || null,
    })
    result.value = res.data
  } catch {
    Message.error('模拟失败，请检查后端连接')
  } finally {
    loading.value = false
  }
}

// 当前层是否存在 prefer/tags 命中（影响非命中行样式）
function hasActiveFilter(layer: SimulateLayer): boolean {
  return layer.models.some(m => m.is_prefer_hit || m.is_tags_hit)
}

// 生成等效代码提示
const codeHint = computed(() => {
  const parts: string[] = []
  if (form.value.prefer) parts.push(`prefer="${form.value.prefer}"`)
  if (form.value.thinking !== null) parts.push(`thinking=${form.value.thinking}`)
  if (form.value.vision !== null) parts.push(`vision=${form.value.vision}`)
  if (form.value.tags) parts.push(`tags="${form.value.tags}"`)
  if (form.value.exclude_tags) parts.push(`exclude_tags="${form.value.exclude_tags}"`)
  return `get_llm(${parts.join(', ')})`
})

// 初始自动执行一次（展示全量无过滤状态）
run()
</script>

<style scoped>
.simulator-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 参数面板 */
.param-card {
  background: #fff;
  border-radius: 8px;
  border: 1px solid #e5e6eb;
  overflow: hidden;
}
.param-title {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  font-weight: 600;
  font-size: 14px;
  color: #1d2129;
  background: linear-gradient(90deg, #e8f3ff 0%, #f2f3f5 60%);
  border-bottom: 1px solid #d1e9ff;
  border-left: 4px solid #165dff;
}
.param-body {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.param-form {
  flex-wrap: wrap;
  gap: 8px;
}

/* 代码提示 */
.code-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #f7f8fa;
  border-radius: 6px;
  border: 1px solid #e5e6eb;
}
.code-label {
  font-size: 12px;
  color: #86909c;
  white-space: nowrap;
}
.code-line {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  color: #165dff;
}

/* 过滤摘要 */
.filter-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  flex-wrap: wrap;
}
.filter-reason {
  font-size: 12px;
  color: #86909c;
}

/* 分层块 */
.layer-block {
  background: #fff;
  border-radius: 8px;
  border: 1px solid #e5e6eb;
  overflow: hidden;
}

.layer-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  font-size: 13px;
  border-bottom: 1px solid #f2f3f5;
}
.layer-active {
  background: linear-gradient(90deg, #e8ffea 0%, #f7f8fa 60%);
  border-left: 4px solid #00b42a;
}
.layer-fallback {
  background: linear-gradient(90deg, #fff7e6 0%, #f7f8fa 60%);
  border-left: 4px solid #ff7d00;
}
.layer-badge {
  font-weight: 700;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  background: #f2f3f5;
  color: #4e5969;
}
.layer-label {
  font-weight: 500;
  color: #1d2129;
  flex: 1;
}
.layer-count {
  font-size: 12px;
  color: #86909c;
}

/* 模型行 */
.model-list {
  font-size: 12px;
}
.model-row {
  display: flex;
  align-items: center;
  padding: 7px 16px;
  gap: 0;
  border-bottom: 1px solid #f2f3f5;
}
.model-row:last-child { border-bottom: none; }
.model-header {
  background: #fafafa;
  color: #86909c;
  font-weight: 500;
}

/* 行高亮 */
.row-prefer  { background: #f0f9ff; }
.row-tags    { background: #f6ffed; }
.row-inactive { opacity: 0.45; }
.model-row:not(.model-header):hover { background: #f7f8fa; }

/* 列宽 */
.mc-vendor  { width: 100px; flex-shrink: 0; }
.mc-model   { flex: 2; min-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mc-weight  { width: 60px; flex-shrink: 0; text-align: center; }
.mc-bar     { width: 200px; flex-shrink: 0; display: flex; align-items: center; gap: 8px; }
.mc-tags    { flex: 1; min-width: 120px; }
.mc-remark  { width: 160px; flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.vendor-text {
  color: #4e5969;
  font-weight: 500;
}
.model-text {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  color: #1d2129;
}

/* 权重 */
.weight-active { color: #1d2129; font-weight: 600; }
.weight-zero   { color: #c9cdd4; }

/* 进度条 */
.bar-wrap {
  flex: 1;
  height: 8px;
  background: #f2f3f5;
  border-radius: 4px;
  overflow: hidden;
}
.bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #165dff, #4080ff);
  border-radius: 4px;
  transition: width 0.4s ease;
}
.bar-pct {
  width: 40px;
  text-align: right;
  color: #165dff;
  font-weight: 600;
}

.text-muted { color: #86909c; }
.init-tip { padding: 60px 0; text-align: center; }
</style>
