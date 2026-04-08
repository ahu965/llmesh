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

      <div v-for="group in groups" :key="group.id" class="group-card">
        <!-- 卡片头部 -->
        <div class="group-header" @click="toggleGroup(group.id!)">
          <div class="group-header-left">
            <icon-right class="collapse-icon" :class="{ expanded: expandedIds.has(group.id!) }" />
            <a-badge :status="group.enabled ? 'success' : 'default'" />
            <span class="vendor-name">{{ group.vendor }}</span>
            <a-tag size="small" color="arcoblue">{{ group.models.length }} 个模型</a-tag>
            <a-tag v-if="group.billing_mode" size="small" :color="billingColor(group.billing_mode)">
              {{ group.billing_mode }}
            </a-tag>
            <a-tag v-if="group.expires_at" size="small" :color="isExpired(group.expires_at) ? 'red' : 'green'">
              {{ isExpired(group.expires_at) ? '已过期' : '有效至 ' + group.expires_at }}
            </a-tag>
            <span class="api-key-hint">{{ maskKey(group.api_key) }}</span>
          </div>
          <div class="group-header-right" @click.stop>
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
          <a-table
            :data="group.models"
            :pagination="false"
            size="small"
            :bordered="{ wrapper: false, cell: false }"
            row-class="model-row"
          >
            <template #columns>
              <a-table-column title="模型名" data-index="model" :width="240" />
              <a-table-column title="权重" :width="90">
                <template #cell="{ record }">
                  <span :class="record.weight === 0 ? 'text-muted' : ''">
                    {{ record.weight ?? `↑${group.weight}` }}
                  </span>
                </template>
              </a-table-column>
              <a-table-column title="超时(s)" :width="90">
                <template #cell="{ record }">
                  {{ record.timeout ?? `↑${group.timeout}` }}
                </template>
              </a-table-column>
              <a-table-column title="特性" :width="180">
                <template #cell="{ record }">
                  <a-space :size="4" wrap>
                    <a-tag v-if="record.supports_thinking" size="small" color="purple">thinking</a-tag>
                    <a-tag v-if="record.is_thinking_only" size="small" color="orange">仅思考</a-tag>
                    <a-tag v-if="record.extra_body" size="small" color="cyan">extra_body</a-tag>
                  </a-space>
                </template>
              </a-table-column>
              <a-table-column title="过期时间" :width="150">
                <template #cell="{ record }">
                  <template v-if="record.expires_at">
                    <a-tag size="small" :color="isExpired(record.expires_at) ? 'red' : 'green'">
                      {{ isExpired(record.expires_at) ? '已过期 ' : '' }}{{ record.expires_at }}
                    </a-tag>
                  </template>
                  <span v-else class="text-muted">↑ 继承组</span>
                </template>
              </a-table-column>
              <a-table-column title="备注" data-index="remark">
                <template #cell="{ record }">
                  <span class="text-muted">{{ record.remark || '—' }}</span>
                </template>
              </a-table-column>
              <a-table-column title="状态" :width="80">
                <template #cell="{ record }">
                  <a-badge
                    :status="record.enabled ? 'success' : 'default'"
                    :text="record.enabled ? '启用' : '禁用'"
                  />
                </template>
              </a-table-column>
              <a-table-column title="操作" :width="120" fixed="right">
                <template #cell="{ record }">
                  <a-space :size="12" style="white-space: nowrap">
                    <a-link @click="showModelModal(group, record)">编辑</a-link>
                    <a-popconfirm content="确认删除？" @ok="deleteModel(group.id!, record.id)">
                      <a-link status="danger">删除</a-link>
                    </a-popconfirm>
                  </a-space>
                </template>
              </a-table-column>
            </template>
          </a-table>
        </div>
      </div>
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
          <a-col :span="12">
            <a-form-item label="过期时间">
              <a-date-picker v-model="groupForm.expires_at" style="width:100%" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
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
            <a-form-item label="状态">
              <a-switch v-model="modelForm.enabled" />
            </a-form-item>
          </a-col>
        </a-row>
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
import { IconPlus, IconDownload, IconUpload, IconRight } from '@arco-design/web-vue/es/icon'
import {
  apiListProviders, apiCreateProvider, apiUpdateProvider, apiDeleteProvider,
  apiAddModel, apiUpdateModel, apiDeleteModel,
  apiExport, apiImportFile,
  type ProviderGroup, type ModelEntry,
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

// ---------- helpers ----------
function emptyGroupForm() {
  return {
    vendor: '', api_key: '', base_url: '', weight: 1, timeout: 60,
    remark: null as string | null, billing_mode: null as string | null,
    expires_at: null as string | null, enabled: true,
  }
}
function emptyModelForm() {
  return {
    model: '', weight: null as number | null, timeout: null as number | null,
    remark: null as string | null, supports_thinking: false,
    is_thinking_only: false, extra_body: null as string | null,
    expires_at: null as string | null, enabled: true,
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
    ? { vendor: group.vendor, api_key: group.api_key, base_url: group.base_url, weight: group.weight, timeout: group.timeout, remark: group.remark, billing_mode: group.billing_mode, expires_at: group.expires_at, enabled: group.enabled }
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
    ? { model: model.model, weight: model.weight, timeout: model.timeout, remark: model.remark, supports_thinking: model.supports_thinking, is_thinking_only: model.is_thinking_only, extra_body: model.extra_body, expires_at: model.expires_at, enabled: model.enabled }
    : emptyModelForm()
  modelVisible.value = true
}
async function saveModel() {
  try {
    if (editingModel.value?.id) {
      await apiUpdateModel(activeGroupId.value!, editingModel.value.id, modelForm.value)
    } else {
      await apiAddModel(activeGroupId.value!, modelForm.value)
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
  gap: 12px;
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
}
.group-card:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  cursor: pointer;
  user-select: none;
  gap: 12px;
}
.group-header:hover {
  background: #f7f8fa;
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
  font-weight: 600;
  font-size: 14px;
  color: #1d2129;
}

.api-key-hint {
  font-size: 12px;
  color: #86909c;
  font-family: monospace;
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
</style>
