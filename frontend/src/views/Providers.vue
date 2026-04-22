<template>
  <div class="providers-page">
    <!-- 工具栏 -->
    <div class="toolbar">
      <a-button type="primary" @click="showGroupModal(null)">
        <template #icon><icon-plus /></template>添加厂商组
      </a-button>
      <a-button @click="handleExport">
        <template #icon><icon-download /></template>导出 secrets.py
      </a-button>
      <a-button @click="importVisible = true">
        <template #icon><icon-upload /></template>从文件导入
      </a-button>
    </div>

    <!-- 厂商组列表 -->
    <a-spin :loading="loading" style="width:100%">
      <div v-if="groups.length === 0 && !loading" class="empty-tip">
        <a-empty description="暂无厂商组，点击「添加厂商组」开始配置" />
      </div>

      <draggable
        v-model="groups"
        item-key="id"
        handle=".group-drag-handle"
        ghost-class="drag-ghost"
        @end="onGroupDragEnd"
      >
        <template #item="{ element: group }">
        <div :key="group.id" class="group-card">
          <!-- 卡片头部 -->
          <div class="group-header" @click="toggleGroup(group.id!)">
            <div class="group-header-left">
              <icon-drag-dot-vertical class="group-drag-handle drag-handle" @click.stop />
              <icon-right class="collapse-icon" :class="{ expanded: expandedIds.has(group.id!) }" />
              <a-badge :status="group.enabled ? 'success' : 'default'" />
              <span class="vendor-name">{{ group.alias || group.vendor }}</span>
              <span v-if="group.alias" class="vendor-id-hint">{{ group.vendor }}</span>
              <a-tag size="small" color="arcoblue">{{ group.models.length }} 个模型</a-tag>
              <a-tag v-if="group.priority !== 0" size="small" color="purple">P{{ group.priority }}</a-tag>
              <a-tag v-if="group.billing_mode" size="small" :color="billingColor(group.billing_mode)">
                {{ group.billing_mode }}
              </a-tag>
              <a-tag v-if="group.expires_at" size="small" :color="isExpired(group.expires_at) ? 'red' : 'green'">
                {{ isExpired(group.expires_at) ? '已过期' : '有效至 ' + group.expires_at }}
              </a-tag>
              <span class="api-key-hint">{{ maskKey(group.api_key) }}</span>
              <a
                v-if="group.website"
                :href="group.website"
                target="_blank"
                rel="noopener noreferrer"
                class="website-link"
                @click.stop
                title="打开厂商官网"
              >
                <icon-link />
              </a>
            </div>
            <div class="group-header-right" @click.stop>
              <a-button
                size="small"
                :disabled="!group.models.some((m: ModelEntry) => m.enabled) || groupProbeState[group.id!]?.loading > 0"
                @click="probeGroup(group)"
              >
                <template #icon>
                  <icon-loading v-if="groupProbeState[group.id!]?.loading > 0" class="probe-loading-icon" />
                  <icon-thunderbolt v-else />
                </template>
                <template v-if="groupProbeState[group.id!] && groupProbeState[group.id!].loading === 0">
                  <span v-if="groupProbeState[group.id!].fail === 0" style="color:#00b42a">
                    全部可用 {{ groupProbeState[group.id!].ok }}
                  </span>
                  <span v-else style="color:#f53f3f">
                    {{ groupProbeState[group.id!].ok }}✓ {{ groupProbeState[group.id!].fail }}✗
                  </span>
                </template>
                <template v-else>探测全组</template>
              </a-button>
              <a-button size="small" @click="showModelModal(group, null)">
                <template #icon><icon-plus /></template>添加模型
              </a-button>
              <a-button size="small" @click="showGroupModal(group)">编辑</a-button>
              <a-popconfirm content="确认删除该厂商组及其所有模型？" @ok="deleteGroup(group.id!)">
                <a-button size="small" status="danger">删除</a-button>
              </a-popconfirm>
            </div>
          </div>

          <!-- 模型表格（展开时显示） -->
          <div v-if="expandedIds.has(group.id!)" class="group-body">
            <!-- 模型拖拽表头 -->
            <div class="model-drag-header">
              <span class="col-handle"></span>
              <span class="col-name">模型名</span>
              <span class="col-weight">权重</span>
              <span class="col-timeout">超时(s)</span>
              <span class="col-priority">优先级</span>
              <span class="col-features">特性</span>
              <span class="col-expire">过期时间</span>
              <span class="col-remark">备注</span>
              <span class="col-status">状态</span>
              <span class="col-action">操作</span>
            </div>
            <draggable
              v-model="group.models"
              item-key="id"
              handle=".model-drag-handle"
              ghost-class="drag-ghost"
              @end="onModelDragEnd(group)"
            >
              <template #item="{ element: record }">
                <div class="model-drag-row">
                  <span class="col-handle">
                    <icon-drag-dot-vertical class="model-drag-handle drag-handle" />
                  </span>
                  <span class="col-name model-name">{{ record.model }}</span>
                  <span class="col-weight" :class="record.weight === 0 ? 'text-muted' : ''">
                    {{ record.weight ?? `↑${group.weight}` }}
                  </span>
                  <span class="col-timeout">{{ record.timeout ?? `↑${group.timeout}` }}</span>
                  <span class="col-priority">
                    <a-tag v-if="record.priority !== null" size="small" color="purple">P{{ record.priority }}</a-tag>
                    <span v-else class="text-muted">↑ P{{ group.priority }}</span>
                  </span>
                  <span class="col-features">
                    <a-space :size="4" wrap>
                      <a-tag v-if="record.supports_thinking" size="small" color="purple">thinking</a-tag>
                      <a-tag v-if="record.is_thinking_only" size="small" color="orange">仅思考</a-tag>
                      <a-tag v-if="record.is_vision" size="small" color="blue">视觉</a-tag>
                      <a-tag v-if="record.extra_body" size="small" color="cyan">extra_body</a-tag>
                      <template v-if="record.tags">
                        <a-tag v-for="tag in parseTags(record.tags)" :key="tag" size="small" color="gray">{{ tag }}</a-tag>
                      </template>
                    </a-space>
                  </span>
                  <span class="col-expire">
                    <template v-if="record.expires_at">
                      <a-tag size="small" :color="isExpired(record.expires_at) ? 'red' : 'green'">
                        {{ isExpired(record.expires_at) ? '已过期 ' : '' }}{{ record.expires_at }}
                      </a-tag>
                    </template>
                    <span v-else class="text-muted">↑ 继承组</span>
                  </span>
                  <span class="col-remark text-muted">{{ record.remark || '—' }}</span>
                  <span class="col-status">
                    <a-badge
                      :status="record.enabled ? 'success' : 'default'"
                      :text="record.enabled ? '启用' : '禁用'"
                    />
                  </span>
                  <span class="col-action">
                    <a-space :size="12" style="white-space: nowrap">
                      <!-- 探测按钮（禁用模型不显示） -->
                      <a-tooltip
                        v-if="record.enabled"
                        :content="probeState[record.id!]?.result
                          ? (probeState[record.id!].result!.ok
                              ? `✓ ${probeState[record.id!].result!.latency_ms}ms`
                              : probeState[record.id!].result!.error || '失败')
                          : '发送「你好」测试可用性'"
                        position="top"
                      >
                        <a-link
                          :status="probeState[record.id!]?.result
                            ? (probeState[record.id!].result!.ok ? 'success' : 'danger')
                            : 'normal'"
                          @click="probeModel(group, record)"
                          :disabled="probeState[record.id!]?.loading"
                        >
                          <icon-thunderbolt v-if="!probeState[record.id!]?.loading" />
                          <icon-loading v-else class="probe-loading-icon" />
                        </a-link>
                      </a-tooltip>
                      <a-link @click="showModelModal(group, record)">编辑</a-link>
                      <a-popconfirm content="确认删除？" @ok="deleteModel(group.id!, record.id)">
                        <a-link status="danger">删除</a-link>
                      </a-popconfirm>
                    </a-space>
                  </span>
                </div>
              </template>
            </draggable>
          </div>
        </div>
        </template>
      </draggable>
    </a-spin>

    <!-- 厂商组 Modal -->
    <a-modal
      v-model:visible="groupVisible"
      :title="editingGroup?.id ? '编辑厂商组' : '添加厂商组'"
      @ok="saveGroup"
      @cancel="groupVisible = false"
      :width="560"
    >
      <a-form :model="groupForm" layout="vertical" size="medium">
        <a-form-item label="分组别名（可选，用于 UI 展示）">
          <a-input v-model="groupForm.alias" placeholder="如「科大讯飞-Pro」，留空则显示厂商标识" allow-clear />
        </a-form-item>
        <a-form-item label="厂商网址（可选，用于快捷跳转）">
          <a-input v-model="groupForm.website" placeholder="https://console.example.com" allow-clear />
        </a-form-item>
        <a-form-item label="厂商标识 (vendor)" required>
          <a-input v-model="groupForm.vendor" placeholder="如 openai / aliyuncs / bigmodel" />
        </a-form-item>
        <a-form-item label="API Key" required>
          <a-input-password v-model="groupForm.api_key" allow-clear />
        </a-form-item>
        <a-form-item label="Base URL" required>
          <a-input v-model="groupForm.base_url" placeholder="https://api.openai.com/v1" />
        </a-form-item>
        <a-row :gutter="16">
          <a-col :span="8">
            <a-form-item label="默认权重">
              <a-input-number v-model="groupForm.weight" :min="0" style="width:100%" />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="默认超时(s)">
              <a-input-number v-model="groupForm.timeout" :min="1" style="width:100%" />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="付费模式">
              <a-select v-model="groupForm.billing_mode" allow-clear placeholder="可选">
                <a-option value="free">free</a-option>
                <a-option value="prepaid">prepaid</a-option>
                <a-option value="postpaid">postpaid</a-option>
              </a-select>
            </a-form-item>
          </a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :span="8">
            <a-form-item label="优先级（越小越优先）">
              <a-input-number v-model="groupForm.priority" :min="0" style="width:100%" />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="过期时间">
              <a-date-picker v-model="groupForm.expires_at" style="width:100%" />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="状态">
              <a-switch v-model="groupForm.enabled" checked-text="启用" unchecked-text="禁用" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-form-item label="备注">
          <a-input v-model="groupForm.remark" placeholder="可选描述" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 模型 Modal -->
    <a-modal
      v-model:visible="modelVisible"
      :title="editingModel?.id ? '编辑模型' : '添加模型'"
      @ok="saveModel"
      @cancel="modelVisible = false"
      :width="480"
    >
      <a-form :model="modelForm" layout="vertical" size="medium">
        <a-form-item label="模型名" required>
          <a-input v-model="modelForm.model" placeholder="如 gpt-4o" />
        </a-form-item>
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item label="权重（空=继承组）">
              <a-input-number v-model="modelForm.weight" :min="0" allow-clear placeholder="继承" style="width:100%" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="超时 s（空=继承组）">
              <a-input-number v-model="modelForm.timeout" :min="1" allow-clear placeholder="继承" style="width:100%" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :span="8">
            <a-form-item label="支持 thinking">
              <a-switch v-model="modelForm.supports_thinking" />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="仅思考模型">
              <a-switch v-model="modelForm.is_thinking_only" />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="视觉模型">
              <a-switch v-model="modelForm.is_vision" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item label="thinking 专用超时 s（空=不区分）">
              <a-input-number v-model="modelForm.thinking_timeout" :min="1" allow-clear placeholder="如 120" style="width:100%"
                :disabled="!modelForm.supports_thinking && !modelForm.is_thinking_only" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="优先级（空=继承组）">
              <a-input-number v-model="modelForm.priority" :min="0" allow-clear placeholder="继承" style="width:100%" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item label="状态">
              <a-switch v-model="modelForm.enabled" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-form-item label="tags（JSON 数组，如 [&quot;cheap&quot;,&quot;fast&quot;]）">
          <a-input v-model="modelForm.tags" placeholder='["cheap","fast"]' allow-clear />
        </a-form-item>
        <a-form-item label="extra_body（JSON）">
          <a-textarea
            v-model="modelForm.extra_body"
            :rows="3"
            :auto-size="{ minRows: 2, maxRows: 6 }"
            placeholder='{"enable_thinking": false}'
          />
        </a-form-item>
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item label="过期时间（空=继承组）">
              <a-date-picker v-model="modelForm.expires_at" style="width:100%" allow-clear placeholder="继承组设置" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="备注">
              <a-input v-model="modelForm.remark" />
            </a-form-item>
          </a-col>
        </a-row>
      </a-form>
    </a-modal>

    <!-- 导入 Modal -->
    <a-modal
      v-model:visible="importVisible"
      title="从 secrets.py 文件导入"
      @ok="handleImport"
      @cancel="importVisible = false"
    >
      <a-form layout="vertical">
        <a-form-item label="文件绝对路径">
          <a-input
            v-model="importPath"
            placeholder="/path/to/secrets.py"
            allow-clear
          />
        </a-form-item>
        <a-alert type="warning" style="margin-top:8px">
          导入会追加到现有数据，不会清空已有配置。
        </a-alert>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Message } from '@arco-design/web-vue'
import { IconPlus, IconDownload, IconUpload, IconRight, IconDragDotVertical, IconLink, IconThunderbolt, IconLoading } from '@arco-design/web-vue/es/icon'
import draggable from 'vuedraggable'
import {
  apiListProviders, apiCreateProvider, apiUpdateProvider, apiDeleteProvider,
  apiReorderProviders,
  apiAddModel, apiUpdateModel, apiDeleteModel, apiReorderModels,
  apiExport, apiImportFile, apiProbe,
  type ProviderGroup, type ModelEntry, type ProbeResponse,
} from '../api'

// ---------- state ----------
const loading = ref(false)
const groups = ref<ProviderGroup[]>([])
const expandedIds = ref<Set<number>>(new Set())

const groupVisible = ref(false)
const editingGroup = ref<ProviderGroup | null>(null)
const groupForm = ref(emptyGroupForm())

const modelVisible = ref(false)
const editingModel = ref<ModelEntry | null>(null)
const activeGroupId = ref<number | null>(null)
const modelForm = ref(emptyModelForm())

const importVisible = ref(false)
const importPath = ref('')

// ---------- probe ----------
// key = model.id，value = { loading, result }
const probeState = ref<Record<number, { loading: boolean; result: ProbeResponse | null }>>({})
// key = group.id，value = { loading: 正在进行的探测数, ok, fail }
const groupProbeState = ref<Record<number, { loading: number; ok: number; fail: number }>>({})

async function probeModel(group: ProviderGroup, model: ModelEntry) {
  const id = model.id!
  probeState.value[id] = { loading: true, result: null }
  try {
    const res = await apiProbe(group.id!, id)
    probeState.value[id] = { loading: false, result: res.data }
  } catch (e: any) {
    probeState.value[id] = {
      loading: false,
      result: { ok: false, latency_ms: null, reply: null, error: e?.message || '请求失败' },
    }
  }
}

async function probeGroup(group: ProviderGroup) {
  const gid = group.id!
  // 只探测启用的模型
  const models = group.models.filter(m => m.enabled)
  if (!models.length) return

  // 确保展开（方便看到每行结果）
  expandedIds.value.add(gid)

  // 初始化组级状态
  groupProbeState.value[gid] = { loading: models.length, ok: 0, fail: 0 }

  // 并发探测所有模型
  await Promise.all(models.map(async (model) => {
    const id = model.id!
    probeState.value[id] = { loading: true, result: null }
    try {
      const res = await apiProbe(gid, id)
      probeState.value[id] = { loading: false, result: res.data }
      const s = groupProbeState.value[gid]
      s.loading--
      res.data.ok ? s.ok++ : s.fail++
    } catch (e: any) {
      probeState.value[id] = {
        loading: false,
        result: { ok: false, latency_ms: null, reply: null, error: e?.message || '请求失败' },
      }
      const s = groupProbeState.value[gid]
      s.loading--
      s.fail++
    }
  }))
}

// ---------- helpers ----------
function emptyGroupForm() {
  return {
    vendor: '', alias: null as string | null, website: null as string | null,
    api_key: '', base_url: '', weight: 1, timeout: 60,
    remark: null as string | null, billing_mode: null as string | null,
    expires_at: null as string | null, priority: 0, enabled: true,
  }
}
function emptyModelForm() {
  return {
    model: '', weight: null as number | null, timeout: null as number | null,
    remark: null as string | null, supports_thinking: false,
    is_thinking_only: false, extra_body: undefined as string | undefined,
    expires_at: null as string | null, priority: null as number | null,
    is_vision: false, tags: null as string | null, enabled: true,
    thinking_timeout: null as number | null,
  }
}
function maskKey(key: string) {
  if (!key || key.length < 8) return '***'
  return key.slice(0, 6) + '...' + key.slice(-4)
}
function billingColor(mode: string | null) {
  return mode === 'free' ? 'green' : mode === 'prepaid' ? 'blue' : 'orange'
}
function isExpired(date: string | null) {
  if (!date) return false
  return new Date(date) < new Date()
}
function parseTags(tags: string | null): string[] {
  if (!tags) return []
  try { return JSON.parse(tags) } catch { return [] }
}
function toggleGroup(id: number) {
  if (expandedIds.value.has(id)) {
    expandedIds.value.delete(id)
  } else {
    expandedIds.value.add(id)
  }
}

// ---------- load ----------
async function loadGroups() {
  loading.value = true
  try {
    const res = await apiListProviders()
    groups.value = res.data
    // 默认展开所有组
    expandedIds.value = new Set(res.data.map((g: ProviderGroup) => g.id!))
  } finally {
    loading.value = false
  }
}

onMounted(loadGroups)

// ---------- group CRUD ----------
function showGroupModal(group: ProviderGroup | null) {
  editingGroup.value = group
  groupForm.value = group
    ? { vendor: group.vendor, alias: group.alias, website: group.website, api_key: group.api_key, base_url: group.base_url, weight: group.weight, timeout: group.timeout, remark: group.remark, billing_mode: group.billing_mode, expires_at: group.expires_at, priority: group.priority, enabled: group.enabled }
    : emptyGroupForm()
  groupVisible.value = true
}
async function saveGroup() {
  try {
    if (editingGroup.value?.id) {
      await apiUpdateProvider(editingGroup.value.id, groupForm.value)
    } else {
      await apiCreateProvider(groupForm.value)
    }
    groupVisible.value = false
    await loadGroups()
    Message.success('保存成功')
  } catch {
    Message.error('保存失败')
  }
}
async function deleteGroup(id: number) {
  await apiDeleteProvider(id)
  expandedIds.value.delete(id)
  await loadGroups()
  Message.success('已删除')
}

// ---------- model CRUD ----------
function showModelModal(group: ProviderGroup, model: ModelEntry | null) {
  activeGroupId.value = group.id!
  editingModel.value = model
  modelForm.value = model
    ? { model: model.model, weight: model.weight, timeout: model.timeout, remark: model.remark, supports_thinking: model.supports_thinking, is_thinking_only: model.is_thinking_only, extra_body: model.extra_body ?? undefined, expires_at: model.expires_at, priority: model.priority, is_vision: model.is_vision, tags: model.tags, enabled: model.enabled, thinking_timeout: model.thinking_timeout }
    : emptyModelForm()
  modelVisible.value = true
}
async function saveModel() {
  try {
    const payload = { ...modelForm.value, extra_body: modelForm.value.extra_body ?? null }
    if (editingModel.value?.id) {
      await apiUpdateModel(activeGroupId.value!, editingModel.value.id, payload)
    } else {
      await apiAddModel(activeGroupId.value!, payload)
    }
    modelVisible.value = false
    await loadGroups()
    Message.success('保存成功')
  } catch {
    Message.error('保存失败')
  }
}
async function deleteModel(groupId: number, modelId: number) {
  await apiDeleteModel(groupId, modelId)
  await loadGroups()
  Message.success('已删除')
}

// ---------- 拖拽排序 ----------
async function onGroupDragEnd() {
  const ids = groups.value.map(g => g.id!)
  try {
    const res = await apiReorderProviders(ids)
    groups.value = res.data
  } catch {
    Message.error('排序保存失败')
    await loadGroups()
  }
}

async function onModelDragEnd(group: ProviderGroup) {
  const ids = group.models.map(m => m.id!)
  try {
    const res = await apiReorderModels(group.id!, ids)
    group.models = res.data
  } catch {
    Message.error('排序保存失败')
    await loadGroups()
  }
}

// ---------- export ----------
async function handleExport() {
  const path = prompt('导出到文件路径（留空仅下载预览）：') ?? ''
  try {
    const res = await apiExport(path || undefined)
    const blob = new Blob([res.data], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = 'secrets.py'; a.click()
    URL.revokeObjectURL(url)
    Message.success('导出成功')
  } catch {
    Message.error('导出失败')
  }
}

// ---------- import ----------
async function handleImport() {
  try {
    const res = await apiImportFile(importPath.value)
    importVisible.value = false
    importPath.value = ''
    await loadGroups()
    Message.success(`导入成功：${res.data.groups} 组，${res.data.models} 个模型`)
  } catch {
    Message.error('导入失败，请检查文件路径')
  }
}
</script>

<style scoped>
.providers-page {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.toolbar {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.group-card {
  background: #fff;
  border-radius: 8px;
  border: 1px solid #e5e6eb;
  overflow: hidden;
  transition: box-shadow 0.2s;
  margin-bottom: 12px;
}
.group-card:last-child {
  margin-bottom: 0;
}
.group-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
}

.group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  cursor: pointer;
  user-select: none;
  gap: 12px;
  background: linear-gradient(90deg, #e8f3ff 0%, #f2f3f5 60%);
  border-bottom: 1px solid #d1e9ff;
  border-left: 4px solid #165dff;
}
.group-header:hover {
  background: linear-gradient(90deg, #d6eaff 0%, #e8eaed 60%);
}

.group-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  flex: 1;
  min-width: 0;
}

.group-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  white-space: nowrap;
}

.collapse-icon {
  font-size: 12px;
  color: #86909c;
  transition: transform 0.2s;
  flex-shrink: 0;
}
.collapse-icon.expanded {
  transform: rotate(90deg);
}

.vendor-name {
  font-weight: 700;
  font-size: 15px;
  color: #1d2129;
  letter-spacing: 0.02em;
}

.vendor-id-hint {
  font-size: 11px;
  color: #86909c;
  font-family: monospace;
  background: rgba(0,0,0,0.04);
  padding: 1px 5px;
  border-radius: 3px;
}

.api-key-hint {
  font-size: 12px;
  color: #86909c;
  font-family: monospace;
}

.website-link {
  display: inline-flex;
  align-items: center;
  color: #86909c;
  font-size: 14px;
  line-height: 1;
  transition: color 0.15s;
}
.website-link:hover {
  color: #165dff;
}

.group-body {
  border-top: 1px solid #f2f3f5;
  padding: 0 0 8px 0;
}

.text-muted {
  color: #86909c;
}

.empty-tip {
  padding: 60px 0;
  text-align: center;
}

/* 拖拽手柄 */
.drag-handle {
  cursor: grab;
  color: #c9cdd4;
  font-size: 16px;
  flex-shrink: 0;
  transition: color 0.15s;
}
.drag-handle:hover { color: #4e5969; }
.drag-ghost { opacity: 0.4; background: #e8f3ff; border-radius: 6px; }

/* 模型拖拽自定义行布局 */
.model-drag-header,
.model-drag-row {
  display: flex;
  align-items: center;
  padding: 8px 16px;
  gap: 0;
  font-size: 12px;
}
.model-drag-header {
  background: #fafafa;
  color: #86909c;
  font-weight: 500;
  border-bottom: 1px solid #f2f3f5;
}
.model-drag-row {
  border-bottom: 1px solid #f2f3f5;
  transition: background 0.15s;
  background: #fff;
}
.model-drag-row:last-child { border-bottom: none; }
.model-drag-row:hover { background: #f7f8fa; }

.col-handle  { width: 24px; flex-shrink: 0; }
.col-name    { flex: 2; min-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.col-weight  { width: 64px; flex-shrink: 0; }
.col-timeout { width: 72px; flex-shrink: 0; }
.col-priority{ width: 80px; flex-shrink: 0; }
.col-features{ flex: 2; min-width: 140px; }
.col-expire  { width: 140px; flex-shrink: 0; }
.col-remark  { flex: 1; min-width: 60px; color: #86909c; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.col-status  { width: 72px; flex-shrink: 0; }
.col-action  { width: 140px; flex-shrink: 0; text-align: right; }

.probe-loading-icon {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}

.model-name {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 12.5px;
  color: #1d2129;
}
</style>
