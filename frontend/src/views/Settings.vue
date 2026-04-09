<template>
  <a-space direction="vertical" size="large" style="width:100%">
  <a-card title="全局路由参数" class="settings-card">
    <a-spin :loading="loading">
      <a-form v-if="form" :model="form" layout="vertical" @submit="save">
        <a-row :gutter="24">
          <a-col :xs="12" :sm="12" :md="6">
            <a-form-item label="默认温度 (temperature)">
              <a-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" style="width:100%" />
            </a-form-item>
          </a-col>
          <a-col :xs="12" :sm="12" :md="6">
            <a-form-item label="最大 Token (max_tokens)">
              <a-input-number v-model="form.max_tokens" :min="1" style="width:100%" />
            </a-form-item>
          </a-col>
          <a-col :xs="12" :sm="12" :md="6">
            <a-form-item label="SDK 内部重试 (max_retries)">
              <a-input-number v-model="form.max_retries" :min="0" style="width:100%" />
            </a-form-item>
          </a-col>
          <a-col :xs="12" :sm="12" :md="6">
            <a-form-item label="默认超时 s (default_timeout)">
              <a-input-number v-model="form.default_timeout" :min="1" style="width:100%" />
            </a-form-item>
          </a-col>
          <a-col :xs="12" :sm="12" :md="6">
            <a-form-item label="thinking 全局超时 s（空=不区分）">
              <a-input-number v-model="form.default_thinking_timeout" :min="1" allow-clear placeholder="如 120" style="width:100%" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-row :gutter="24">
          <a-col :xs="12" :sm="12" :md="6">
            <a-form-item label="熔断时长 s (fault_duration)">
              <a-input-number v-model="form.fault_duration" :min="1" style="width:100%" />
            </a-form-item>
          </a-col>
          <a-col :xs="12" :sm="12" :md="6">
            <a-form-item label="限流冷却 s (rate_limit_cooldown)">
              <a-input-number v-model="form.rate_limit_cooldown" :min="1" style="width:100%" />
            </a-form-item>
          </a-col>
          <a-col :xs="12" :sm="12" :md="6">
            <a-form-item label="超时重试次数 (timeout_retries)">
              <a-input-number v-model="form.timeout_retries" :min="0" style="width:100%" />
            </a-form-item>
          </a-col>
          <a-col :xs="12" :sm="12" :md="6">
            <a-form-item label="超时步进 s (timeout_step)">
              <a-input-number v-model="form.timeout_step" :min="0" style="width:100%" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-form-item>
          <a-button type="primary" html-type="submit" :loading="saving">保存</a-button>
        </a-form-item>
      </a-form>
    </a-spin>
  </a-card>

  <!-- 一键发布 -->
  <a-card title="SDK 打包发布" class="settings-card">
    <a-space direction="vertical" size="medium" style="width:100%">

      <!-- 发布配置 -->
      <a-form layout="vertical">
        <a-row :gutter="24">
          <a-col :xs="24" :md="12">
            <a-form-item label="打包 Python 路径（留空使用后端当前解释器）">
              <a-input v-model="buildConfig.python_path" placeholder="/path/to/python" allow-clear />
            </a-form-item>
          </a-col>
          <a-col :xs="24" :md="12">
            <a-form-item label="PyPI 上传地址（留空则不上传）">
              <a-input v-model="buildConfig.pypi_url" placeholder="https://your-pypi.example.com/pypi/" allow-clear />
            </a-form-item>
          </a-col>
        </a-row>
        <a-form-item style="margin-bottom:0">
          <a-button @click="saveBuildConfig" :loading="savingBuildConfig">保存发布配置</a-button>
        </a-form-item>
      </a-form>

      <a-divider style="margin: 4px 0" />

      <!-- 状态 + 操作 -->
      <a-space wrap>
        <a-button
          type="primary" status="success"
          :loading="building"
          :disabled="!buildStatus?.needs_build && !building"
          @click="buildPackage(false)"
        >
          <template #icon><icon-tool /></template>
          {{ buildStatus?.needs_build === false ? '已是最新，无需发包' : '打包' }}
        </a-button>
        <a-button
          v-if="buildConfig.pypi_url"
          type="primary"
          :loading="building"
          :disabled="!buildStatus?.needs_build && !building"
          @click="buildPackage(true)"
        >
          <template #icon><icon-upload /></template>
          打包 + 上传 PyPI
        </a-button>
        <a-tag v-if="buildResult" :color="buildResult.ok ? 'green' : 'red'">
          {{ buildResult.ok
            ? `✓ ${buildResult.wheel}${buildResult.uploaded ? '  已上传' : ''}`
            : '构建失败' }}
        </a-tag>
      </a-space>

      <!-- 时间信息 -->
      <a-descriptions v-if="buildStatus" :column="2" size="small" style="font-size:12px">
        <a-descriptions-item label="上次发包">
          {{ buildStatus.last_built_at ? formatTs(buildStatus.last_built_at) : '从未' }}
        </a-descriptions-item>
        <a-descriptions-item label="配置最后修改">
          {{ buildStatus.db_updated_at ? formatTs(buildStatus.db_updated_at) : '未知' }}
        </a-descriptions-item>
      </a-descriptions>

      <!-- 日志 -->
      <a-textarea
        v-if="buildLog"
        :model-value="buildLog"
        :auto-size="{ minRows: 4, maxRows: 14 }"
        readonly
        style="font-size:12px; font-family: monospace;"
      />
    </a-space>
  </a-card>
  </a-space>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Message } from '@arco-design/web-vue'
import {
  apiGetSettings, apiUpdateSettings, apiBuildStatus, apiUpdateSettings as _apiUpdateSettings,
  type GlobalSettings, type BuildResult, type BuildStatus,
} from '../api'
import axios from 'axios'

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || 'http://localhost:8001',
  timeout: 10000,
})

const loading = ref(false)
const saving = ref(false)
const form = ref<GlobalSettings | null>(null)

// 发布配置（python_path / pypi_url 存在 GlobalSettings 扩展字段里）
const buildConfig = ref({ python_path: '', pypi_url: '' })
const savingBuildConfig = ref(false)

const building = ref(false)
const buildResult = ref<BuildResult | null>(null)
const buildLog = ref('')
const buildStatus = ref<BuildStatus | null>(null)

function formatTs(ts: number): string {
  return new Date(ts * 1000).toLocaleString()
}

onMounted(async () => {
  loading.value = true
  try {
    const [settingsRes, statusRes] = await Promise.all([
      apiGetSettings(),
      apiBuildStatus(),
    ])
    form.value = settingsRes.data
    buildStatus.value = statusRes.data
    buildConfig.value.python_path = statusRes.data.python_path || ''
    buildConfig.value.pypi_url    = statusRes.data.pypi_url    || ''
  } finally {
    loading.value = false
  }
})

async function save() {
  if (!form.value) return
  saving.value = true
  try {
    const res = await apiUpdateSettings(form.value)
    form.value = res.data
    Message.success('保存成功')
    buildStatus.value = (await apiBuildStatus()).data
  } catch {
    Message.error('保存失败')
  } finally {
    saving.value = false
  }
}

async function saveBuildConfig() {
  savingBuildConfig.value = true
  try {
    await http.put('/api/build/config', {
      python_path: buildConfig.value.python_path || null,
      pypi_url:    buildConfig.value.pypi_url    || null,
    })
    Message.success('发布配置已保存')
    buildStatus.value = (await apiBuildStatus()).data
  } catch {
    Message.error('保存失败')
  } finally {
    savingBuildConfig.value = false
  }
}

async function buildPackage(upload: boolean) {
  building.value = true
  buildResult.value = null
  buildLog.value = ''

  const baseURL = import.meta.env.VITE_API_BASE || 'http://localhost:8001'
  try {
    const resp = await fetch(`${baseURL}/api/build`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ upload }),
    })
    if (!resp.ok || !resp.body) {
      const text = await resp.text()
      throw new Error(text || `HTTP ${resp.status}`)
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      // SSE 帧以 \n\n 分隔
      const parts = buf.split('\n\n')
      buf = parts.pop() ?? ''
      for (const part of parts) {
        // 取 data: 后面的内容
        const line = part.replace(/^data: /, '')
        if (line.startsWith('__RESULT__')) {
          const result = JSON.parse(line.slice('__RESULT__'.length))
          buildResult.value = { ...result, log: buildLog.value }
          Message.success(upload ? `打包并上传成功：${result.wheel}` : `打包成功：${result.wheel}`)
          buildStatus.value = (await apiBuildStatus()).data
        } else if (line.startsWith('__ERROR__')) {
          const msg = line.slice('__ERROR__'.length)
          buildLog.value += (buildLog.value ? '\n' : '') + `[ERROR] ${msg}`
          buildResult.value = { ok: false, wheel: null, wheel_path: null, uploaded: false, log: buildLog.value }
          Message.error(msg)
        } else if (line) {
          buildLog.value += (buildLog.value ? '\n' : '') + line
        }
      }
    }
  } catch (err: any) {
    const msg = err?.message || '未知错误'
    buildLog.value += (buildLog.value ? '\n' : '') + `[ERROR] ${msg}`
    buildResult.value = { ok: false, wheel: null, wheel_path: null, uploaded: false, log: buildLog.value }
    Message.error('打包失败')
  } finally {
    building.value = false
  }
}
</script>

<style scoped>
.settings-card {
  width: 100%;
}

:deep(.arco-card-body) {
  padding: 24px;
}
</style>
