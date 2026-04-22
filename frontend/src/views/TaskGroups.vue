<template>
  <div class="tg-page">
    <!-- 工具栏 -->
    <div class="toolbar">
      <a-button type="primary" @click="openCreate">
        <template #icon><icon-plus /></template>
        新建任务组
      </a-button>
      <span class="toolbar-tip">任务组将在下次「生成配置」时写入 secrets.py，调用方通过 <code>get_llm(task_group="名称")</code> 引用</span>
    </div>

    <!-- 列表 -->
    <div v-if="groups.length === 0 && !loading" class="empty-wrap">
      <a-empty description="暂无任务组，点击「新建任务组」创建" />
    </div>

    <div v-for="tg in groups" :key="tg.id" class="tg-card" :class="{ 'tg-disabled': !tg.enabled }">
      <!-- 卡片头 -->
      <div class="tg-header">
        <div class="tg-title-row">
          <span class="tg-name">{{ tg.name }}</span>
          <span v-if="tg.display_name" class="tg-display-name">{{ tg.display_name }}</span>
          <a-tag v-if="!tg.enabled" size="small" color="gray" style="margin-left:6px">已禁用</a-tag>
        </div>
        <div class="tg-actions">
          <a-button size="small" @click="openEdit(tg)">编辑</a-button>
          <a-popconfirm content="确定删除该任务组？" @ok="deleteGroup(tg.id)">
            <a-button size="small" status="danger">删除</a-button>
          </a-popconfirm>
        </div>
      </div>

      <!-- 参数摘要 -->
      <div class="tg-body">
        <!-- code hint -->
        <div class="code-hint">
          <span class="code-label">调用：</span>
          <code class="code-line">get_llm(task_group="{{ tg.name }}"{{ thinkingSnippet(tg) }})</code>
        </div>

        <div class="tg-params">
          <!-- pinned 模型列表 -->
          <div class="param-row">
            <span class="param-label">候选模型</span>
            <div class="pinned-list">
              <span v-if="tg.pinned.length === 0" class="text-muted">— 不限定（全量池）</span>
              <template v-else>
                <span
                  v-for="(vm, idx) in tg.pinned"
                  :key="vm"
                  class="pinned-item"
                  :title="vm"
                >
                  <span class="pinned-index">{{ idx + 1 }}</span>
                  <span class="pinned-vm">{{ vm }}</span>
                </span>
                <span class="pinned-fallback">→ 全部失败后 fallback 全量池</span>
              </template>
            </div>
          </div>

          <!-- 其他参数 -->
          <div class="param-row">
            <span class="param-label">过滤参数</span>
            <a-space wrap :size="6">
              <a-tag v-if="tg.thinking === true" size="small" color="purple">thinking: True</a-tag>
              <a-tag v-else-if="tg.thinking === false" size="small" color="orange">thinking: False</a-tag>
              <a-tag v-else size="small" color="gray">thinking: None</a-tag>
              <template v-if="tg.prefer.length > 0">
                <a-tag v-for="t in tg.prefer" :key="t" size="small" color="arcoblue">prefer: {{ t }}</a-tag>
              </template>
              <template v-if="tg.exclude_tags.length > 0">
                <a-tag v-for="t in tg.exclude_tags" :key="t" size="small" color="red">排除：{{ t }}</a-tag>
              </template>
              <template v-if="tg.tags.length > 0">
                <a-tag v-for="t in tg.tags" :key="t" size="small" color="green">偏好：{{ t }}</a-tag>
              </template>
            </a-space>
          </div>

          <div v-if="tg.remark" class="param-row">
            <span class="param-label">备注</span>
            <span class="text-muted">{{ tg.remark }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 编辑/新建抽屉 -->
    <a-drawer
      :visible="drawerVisible"
      :title="editingId ? '编辑任务组' : '新建任务组'"
      :width="560"
      @cancel="drawerVisible = false"
      @ok="saveGroup"
      :ok-loading="saving"
      ok-text="保存"
    >
      <a-form :model="form" layout="vertical" ref="formRef">
        <a-form-item label="名称（调用侧使用）" field="name" :rules="[{ required: true, message: '请输入名称' }]">
          <a-input v-model="form.name" placeholder="如 scorer_1、text_processor" />
          <div class="field-hint">只用于 Python 代码中 task_group= 参数，建议小写+下划线</div>
        </a-form-item>

        <a-form-item label="展示名（可选）">
          <a-input v-model="form.display_name" placeholder="如「评分器 v1」，仅用于 UI 展示" allow-clear />
        </a-form-item>

        <a-form-item label="候选模型（pinned）">
          <div class="pinned-editor">
            <div
              v-for="(_, idx) in form.pinned"
              :key="idx"
              class="pinned-editor-row"
            >
              <span class="pinned-editor-idx">{{ idx + 1 }}</span>
              <a-select
                v-model="form.pinned![idx]"
                :options="modelOptions"
                placeholder="选择模型"
                allow-search
                style="flex:1"
                @change="(v: string) => form.pinned![idx] = v"
              />
              <a-button
                shape="circle"
                size="mini"
                status="danger"
                @click="removePinned(idx)"
              ><template #icon><icon-minus /></template></a-button>
              <a-button v-if="idx > 0" shape="circle" size="mini" @click="movePinnedUp(idx)">
                <template #icon><icon-up /></template>
              </a-button>
              <a-button v-if="idx < form.pinned!.length - 1" shape="circle" size="mini" @click="movePinnedDown(idx)">
                <template #icon><icon-down /></template>
              </a-button>
            </div>
            <a-button size="small" @click="addPinned" style="margin-top:6px">
              <template #icon><icon-plus /></template>
              添加模型
            </a-button>
          </div>
          <div class="field-hint">按序尝试，全部失败后自动 fallback 全量池；不填则完全走全量池</div>
        </a-form-item>

        <a-form-item label="偏好厂商/模型（prefer，软偏好）">
          <a-select
            v-model="form.prefer"
            multiple
            allow-create
            allow-clear
            placeholder="输入关键字后回车，如 qwen、gpt、claude"
            style="width:100%"
          />
          <div class="field-hint">软偏好：优先选 vendor 或 model 名包含该关键字的模型，全不可用时 fallback 当前优先级层</div>
        </a-form-item>

        <a-form-item label="排除 tags（exclude_tags）">
          <a-select
            v-model="form.exclude_tags"
            multiple
            allow-create
            allow-clear
            placeholder="输入 tag 后回车，如 math、translate、code"
            style="width:100%"
          />
          <div class="field-hint">硬排除：命中任意 tag 的模型直接剔除，不参与本任务组调用</div>
        </a-form-item>

        <a-form-item label="偏好 tags（tags，软偏好）">
          <a-select
            v-model="form.tags"
            multiple
            allow-create
            allow-clear
            placeholder="输入 tag 后回车，如 cheap、fast"
            style="width:100%"
          />
          <div class="field-hint">软偏好：优先选命中 tag 的模型，全不可用时 fallback 当前优先级层</div>
        </a-form-item>

        <a-form-item label="thinking 模式">
          <a-select v-model="form.thinking" style="width:200px">
            <a-option :value="null">None（不限定）</a-option>
            <a-option :value="true">True（开启思考）</a-option>
            <a-option :value="false">False（关闭思考）</a-option>
          </a-select>
        </a-form-item>

        <a-form-item label="备注">
          <a-textarea v-model="formRemark" placeholder="任务场景说明，仅用于记录" :auto-size="{ minRows: 2, maxRows: 4 }" allow-clear />
        </a-form-item>

        <a-form-item label="状态">
          <a-switch v-model="form.enabled" checked-text="启用" unchecked-text="禁用" />
          <span class="field-hint" style="margin-left:10px">禁用后不写入 secrets.py</span>
        </a-form-item>
      </a-form>
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Message } from '@arco-design/web-vue'
import {
  IconPlus, IconMinus, IconUp, IconDown,
} from '@arco-design/web-vue/es/icon'
import {
  apiListTaskGroups, apiCreateTaskGroup, apiUpdateTaskGroup, apiDeleteTaskGroup,
  apiListProviders,
  type TaskGroupRead, type TaskGroupWrite, type ProviderGroup,
} from '../api'

// ---- 数据 ----
const loading = ref(false)
const groups = ref<TaskGroupRead[]>([])
const modelOptions = ref<{ label: string; value: string }[]>([])

async function loadGroups() {
  loading.value = true
  try {
    const res = await apiListTaskGroups()
    groups.value = res.data
  } catch {
    Message.error('加载失败')
  } finally {
    loading.value = false
  }
}

async function loadModels() {
  try {
    const res = await apiListProviders()
    const opts: { label: string; value: string }[] = []
    for (const g of res.data as ProviderGroup[]) {
      if (!g.enabled) continue
      for (const m of g.models) {
        if (!m.enabled) continue
        const vm = `${g.vendor}/${m.model}`
        opts.push({ label: vm, value: vm })
      }
    }
    modelOptions.value = opts
  } catch {
    // 静默失败，不阻塞页面
  }
}

onMounted(() => {
  loadGroups()
  loadModels()
})

// ---- 抽屉 ----
const drawerVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const formRef = ref()

const emptyForm = (): TaskGroupWrite & { id?: number } => ({
  name: '',
  display_name: '',
  pinned: [],
  exclude_tags: [],
  tags: [],
  prefer: [],
  thinking: null,
  remark: '',
  enabled: true,
})

const form = ref<TaskGroupWrite & { id?: number }>(emptyForm())

// a-textarea 要求 string，用计算属性桥接
const formRemark = computed<string>({
  get: () => form.value.remark ?? '',
  set: (v: string) => { form.value.remark = v || null },
})

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  drawerVisible.value = true
}

function openEdit(tg: TaskGroupRead) {
  editingId.value = tg.id
  form.value = {
    name: tg.name,
    display_name: tg.display_name ?? '',
    pinned: [...tg.pinned],
    exclude_tags: [...tg.exclude_tags],
    tags: [...tg.tags],
    prefer: [...tg.prefer],
    thinking: tg.thinking,
    remark: tg.remark ?? '',
    enabled: tg.enabled,
  }
  drawerVisible.value = true
}

async function saveGroup() {
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  saving.value = true
  const payload: TaskGroupWrite = {
    name: form.value.name.trim(),
    display_name: form.value.display_name || null,
    pinned: (form.value.pinned ?? []).filter(v => v),
    exclude_tags: form.value.exclude_tags,
    tags: form.value.tags,
    prefer: form.value.prefer,
    thinking: form.value.thinking,
    remark: form.value.remark || null,
    enabled: form.value.enabled,
  }
  try {
    if (editingId.value) {
      await apiUpdateTaskGroup(editingId.value, payload)
      Message.success('已更新')
    } else {
      await apiCreateTaskGroup(payload)
      Message.success('已创建')
    }
    drawerVisible.value = false
    await loadGroups()
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function deleteGroup(id: number) {
  try {
    await apiDeleteTaskGroup(id)
    Message.success('已删除')
    await loadGroups()
  } catch {
    Message.error('删除失败')
  }
}

// ---- pinned 编辑 ----
function addPinned() {
  form.value.pinned!.push('')
}
function removePinned(idx: number) {
  form.value.pinned!.splice(idx, 1)
}
function movePinnedUp(idx: number) {
  const arr = form.value.pinned!
  ;[arr[idx - 1], arr[idx]] = [arr[idx], arr[idx - 1]]
}
function movePinnedDown(idx: number) {
  const arr = form.value.pinned!
  ;[arr[idx], arr[idx + 1]] = [arr[idx + 1], arr[idx]]
}

// ---- 代码提示 ----
function thinkingSnippet(tg: TaskGroupRead): string {
  if (tg.thinking === true) return ', thinking=True'
  if (tg.thinking === false) return ', thinking=False'
  return ''
}
</script>

<style scoped>
.tg-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
}
.toolbar-tip {
  font-size: 12px;
  color: #86909c;
}
.toolbar-tip code {
  font-family: 'SF Mono', 'Fira Code', monospace;
  color: #165dff;
  background: #f0f4ff;
  padding: 1px 5px;
  border-radius: 3px;
}

.empty-wrap {
  padding: 60px 0;
  text-align: center;
}

/* 卡片 */
.tg-card {
  background: #fff;
  border-radius: 8px;
  border: 1px solid #e5e6eb;
  overflow: hidden;
  transition: box-shadow 0.2s;
}
.tg-card:hover {
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
}
.tg-disabled {
  opacity: 0.6;
}

.tg-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: linear-gradient(90deg, #f0f4ff 0%, #f7f8fa 60%);
  border-bottom: 1px solid #e5e6eb;
  border-left: 4px solid #165dff;
}
.tg-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.tg-name {
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 15px;
  font-weight: 700;
  color: #165dff;
}
.tg-display-name {
  font-size: 13px;
  color: #4e5969;
}
.tg-actions {
  display: flex;
  gap: 8px;
}

.tg-body {
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* code hint */
.code-hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: #f7f8fa;
  border-radius: 5px;
  border: 1px solid #e5e6eb;
  align-self: flex-start;
}
.code-label {
  font-size: 11px;
  color: #86909c;
  white-space: nowrap;
}
.code-line {
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 12px;
  color: #165dff;
}

/* 参数行 */
.tg-params {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.param-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.param-label {
  font-size: 12px;
  color: #86909c;
  width: 72px;
  flex-shrink: 0;
  padding-top: 2px;
}

/* pinned 模型列表 */
.pinned-list {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.pinned-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #f0f4ff;
  border: 1px solid #bedaff;
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 12px;
}
.pinned-index {
  font-size: 10px;
  color: #86909c;
  font-weight: 600;
  min-width: 14px;
}
.pinned-vm {
  font-family: 'SF Mono', 'Fira Code', monospace;
  color: #1d2129;
}
.pinned-fallback {
  font-size: 11px;
  color: #86909c;
  font-style: italic;
}

.text-muted { color: #86909c; font-size: 12px; }

/* 抽屉表单 */
.field-hint {
  font-size: 11px;
  color: #86909c;
  margin-top: 3px;
}

/* pinned 编辑器 */
.pinned-editor {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.pinned-editor-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.pinned-editor-idx {
  font-size: 11px;
  color: #86909c;
  width: 18px;
  text-align: center;
  flex-shrink: 0;
}
</style>
