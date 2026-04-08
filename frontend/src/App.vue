<template>
  <a-layout style="min-height: 100vh; background: #f2f3f5">
    <a-layout-sider
      :width="200"
      style="background: #fff; border-right: 1px solid #e5e6eb; box-shadow: 2px 0 8px rgba(0,0,0,0.04)"
    >
      <div class="logo">
        <span class="logo-text">llmesh</span>
        <a-tag size="small" color="arcoblue" style="margin-left:6px">beta</a-tag>
      </div>
      <a-menu
        :selected-keys="[route.path]"
        style="border: none"
        @menu-item-click="(key: string) => router.push(key)"
      >
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
      <a-layout-header class="header">
        <span class="page-title">{{ route.meta.title }}</span>
      </a-layout-header>
      <a-layout-content class="content">
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

<style scoped>
.logo {
  height: 60px;
  display: flex;
  align-items: center;
  padding: 0 16px;
  border-bottom: 1px solid #f2f3f5;
}
.logo-text {
  font-size: 18px;
  font-weight: 700;
  color: #165dff;
  letter-spacing: -0.5px;
}

.header {
  background: #fff;
  height: 52px;
  padding: 0 24px;
  border-bottom: 1px solid #e5e6eb;
  display: flex;
  align-items: center;
}
.page-title {
  font-size: 15px;
  font-weight: 500;
  color: #1d2129;
}

.content {
  padding: 20px 24px;
  min-height: calc(100vh - 52px);
  overflow: auto;
}
</style>
