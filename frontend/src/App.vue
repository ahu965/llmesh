<template>
  <a-layout style="min-height: 100vh">
    <a-layout-sider :width="200" style="background: #fff">
      <div style="padding: 20px 16px 12px; font-size: 18px; font-weight: 700; color: #165dff">
        llmesh
      </div>
      <a-menu :selected-keys="[route.path]" @menu-item-click="(key: string) => router.push(key)">
        <a-menu-item key="/providers">
          <template #icon><icon-apps /></template>
          模型管理
        </a-menu-item>
        <a-menu-item key="/settings">
          <template #icon><icon-settings /></template>
          全局配置
        </a-menu-item>
      </a-menu>
    </a-layout-sider>

    <a-layout>
      <a-layout-header style="background:#fff; padding: 0 24px; border-bottom: 1px solid #e5e6eb; display:flex; align-items:center; justify-content:space-between">
        <span style="font-size:15px; color:#1d2129">{{ route.meta.title }}</span>
      </a-layout-header>
      <a-layout-content style="padding: 24px; background: #f2f3f5; min-height: calc(100vh - 60px)">
        <router-view />
      </a-layout-content>
    </a-layout>
  </a-layout>
</template>

<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { IconApps, IconSettings } from '@arco-design/web-vue/es/icon'

const route = useRoute()
const router = useRouter()
</script>
