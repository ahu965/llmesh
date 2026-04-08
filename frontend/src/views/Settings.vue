<template>
  <a-card title="全局路由参数" style="max-width: 600px">
    <a-spin :loading="loading">
      <a-form v-if="form" :model="form" layout="vertical" @submit="save">
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item label="默认温度 (temperature)">
              <a-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" style="width:100%" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="最大 Token (max_tokens)">
              <a-input-number v-model="form.max_tokens" :min="1" style="width:100%" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item label="SDK 内部重试 (max_retries)">
              <a-input-number v-model="form.max_retries" :min="0" style="width:100%" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="默认超时 s (default_timeout)">
              <a-input-number v-model="form.default_timeout" :min="1" style="width:100%" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item label="熔断时长 s (fault_duration)">
              <a-input-number v-model="form.fault_duration" :min="1" style="width:100%" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="限流冷却 s (rate_limit_cooldown)">
              <a-input-number v-model="form.rate_limit_cooldown" :min="1" style="width:100%" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item label="超时重试次数 (timeout_retries)">
              <a-input-number v-model="form.timeout_retries" :min="0" style="width:100%" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
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
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Message } from '@arco-design/web-vue'
import { apiGetSettings, apiUpdateSettings, type GlobalSettings } from '../api'

const loading = ref(false)
const saving = ref(false)
const form = ref<GlobalSettings | null>(null)

onMounted(async () => {
  loading.value = true
  try {
    const res = await apiGetSettings()
    form.value = res.data
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
  } catch {
    Message.error('保存失败')
  } finally {
    saving.value = false
  }
}
</script>
