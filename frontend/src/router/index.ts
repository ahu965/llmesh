import { createRouter, createWebHistory } from 'vue-router'
import Providers from '../views/Providers.vue'
import Settings from '../views/Settings.vue'
import Simulator from '../views/Simulator.vue'
import TaskGroups from '../views/TaskGroups.vue'
import Playground from '../views/Playground.vue'
import PlaygroundHistory from '../views/PlaygroundHistory.vue'
import PromptOptimizer from '../views/PromptOptimizer.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/providers' },
    { path: '/providers', component: Providers, meta: { title: '模型管理' } },
    { path: '/task-groups', component: TaskGroups, meta: { title: '任务组' } },
    { path: '/simulator', component: Simulator, meta: { title: '路由模拟器' } },
    { path: '/playground', component: Playground, meta: { title: 'Playground' } },
    { path: '/playground/history', component: PlaygroundHistory, meta: { title: '评测历史' } },
    { path: '/prompt-optimizer', component: PromptOptimizer, meta: { title: '提示词优化' } },
    { path: '/settings', component: Settings, meta: { title: '全局配置' } },
  ],
})

export default router
