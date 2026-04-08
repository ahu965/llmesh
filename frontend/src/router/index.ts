import { createRouter, createWebHistory } from 'vue-router'
import Providers from '../views/Providers.vue'
import Settings from '../views/Settings.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/providers' },
    { path: '/providers', component: Providers, meta: { title: '模型管理' } },
    { path: '/settings', component: Settings, meta: { title: '全局配置' } },
  ],
})

export default router
