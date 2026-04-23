<template>
  <div class="history-page">
    <div class="page-header">
      <div class="header-title">
        <icon-history style="color:#165dff;font-size:18px" />
        评测历史
      </div>
      <a-button size="small" @click="$router.back()">
        <template #icon><icon-left /></template>
        返回评测
      </a-button>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="loading-state">
      <a-spin size="large" />
    </div>

    <!-- 空状态 -->
    <div v-else-if="records.length === 0" class="empty-state">
      <a-empty description="暂无评测历史记录" />
    </div>

    <!-- 历史列表 -->
    <div v-else class="history-list">
      <div
        v-for="record in records"
        :key="record.id"
        class="history-item"
      >
        <div class="item-main" @click="viewDetail(record.id)">
          <div class="item-header">
            <span class="item-time">{{ formatTime(record.created_at) }}</span>
            <a-tag v-if="record.tool_mode" size="small" color="purple">Tool Calling</a-tag>
            <span class="item-models">{{ record.model_count }} 个模型</span>
            <span class="item-duration">{{ record.total_time_ms }}ms</span>
          </div>
          <div class="item-prompt">{{ record.prompt }}</div>
        </div>
        <div class="item-actions">
          <a-button type="text" size="small" @click="viewDetail(record.id)">
            查看详情
          </a-button>
          <a-popconfirm
            content="确定要删除这条记录吗？"
            @ok="handleDelete(record.id)"
          >
            <a-button type="text" size="small" status="danger">
              删除
            </a-button>
          </a-popconfirm>
        </div>
      </div>
    </div>

    <!-- 分页 -->
    <div v-if="total > pageSize" class="pagination">
      <a-pagination
        v-model:current="currentPage"
        :total="total"
        :page-size="pageSize"
        show-total
        @change="loadHistory"
      />
    </div>

    <!-- 详情弹窗 -->
    <a-modal
      v-model:visible="showDetail"
      title="评测详情"
      width="900px"
      :footer="null"
    >
      <div v-if="detail" class="detail-content">
        <a-descriptions :column="2" bordered size="small">
          <a-descriptions-item label="评测时间">
            {{ formatTime(detail.created_at) }}
          </a-descriptions-item>
          <a-descriptions-item label="模型数量">
            {{ detail.model_count }} 个
          </a-descriptions-item>
          <a-descriptions-item label="总耗时">
            {{ detail.total_time_ms }}ms
          </a-descriptions-item>
          <a-descriptions-item label="思考模式">
            {{ detail.thinking === true ? '开启' : detail.thinking === false ? '关闭' : '不限' }}
          </a-descriptions-item>
          <a-descriptions-item label="Tool Calling" :span="2">
            {{ detail.tool_mode ? '是' : '否' }}
          </a-descriptions-item>
          <a-descriptions-item label="Prompt" :span="2">
            <pre class="prompt-text">{{ detail.prompt }}</pre>
          </a-descriptions-item>
        </a-descriptions>

        <!-- AI 评分 -->
        <div v-if="detail.judge" class="judge-section">
          <div class="section-title">
            <icon-trophy style="color:#ff7d00;font-size:14px" />
            AI 评分（{{ detail.judge.judge_vendor }}/{{ detail.judge.judge_model }}）
          </div>
          <div class="judge-ranking">
            <div
              v-for="(key, idx) in detail.judge.ranking"
              :key="key"
              class="rank-item"
            >
              <span class="rank-badge" :class="`rank-${idx + 1}`">{{ idx + 1 }}</span>
              <span class="rank-model">{{ key }}</span>
              <span class="rank-score">{{ detail.judge.scores[key]?.toFixed(1) ?? '-' }} 分</span>
            </div>
          </div>
          <div class="judge-comment">{{ detail.judge.comment }}</div>
        </div>

        <!-- 模型结果 -->
        <div class="results-section">
          <div class="section-title">
            <icon-bug style="color:#00b42a;font-size:14px" />
            模型回答
          </div>
          <div class="result-grid">
            <div
              v-for="(r, idx) in detail.results"
              :key="idx"
              class="result-card"
              :class="{ 'result-error': !r.ok }"
            >
              <div class="result-header">
                <div class="result-model-name">
                  <span class="vendor-label">{{ r.vendor }}</span>
                  <span class="model-label">{{ r.model }}</span>
                  <a-tag v-if="r.thinking_used" size="small" color="orangered">思考</a-tag>
                </div>
                <div class="result-meta">
                  <a-tag v-if="r.ok" size="small" color="green">{{ r.latency_ms }}ms</a-tag>
                  <a-tag v-else size="small" color="red">失败</a-tag>
                  <a-tag v-if="r.tokens_input != null || r.tokens_output != null" size="small" color="gray">
                    ↑{{ r.tokens_input ?? '-' }} ↓{{ r.tokens_output ?? '-' }}
                  </a-tag>
                </div>
              </div>
              <div v-if="r.ok && r.reply" class="result-content">
                <pre class="result-text">{{ r.reply }}</pre>
              </div>
              <div v-if="r.ok && r.tool_calls && r.tool_calls.length > 0" class="result-tool-calls">
                <div class="tool-calls-title">Tool Calls ({{ r.tool_calls.length }})</div>
                <div v-for="(tc, tcIdx) in r.tool_calls" :key="tcIdx" class="tool-call-item">
                  <a-tag size="small" color="purple">{{ tc.name }}</a-tag>
                  <pre class="tc-args">{{ JSON.stringify(tc.arguments, null, 2) }}</pre>
                </div>
              </div>
              <div v-if="!r.ok" class="result-error-msg">{{ r.error }}</div>
            </div>
          </div>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Message } from '@arco-design/web-vue'
import {
  IconHistory,
  IconLeft,
  IconTrophy,
  IconBug,
} from '@arco-design/web-vue/es/icon'
import {
  apiPlaygroundHistory,
  apiPlaygroundHistoryDetail,
  apiPlaygroundHistoryDelete,
  type PlaygroundHistorySummary,
  type PlaygroundHistoryDetail,
} from '../api'

// 状态
const loading = ref(false)
const records = ref<PlaygroundHistorySummary[]>([])
const total = ref(0)
const pageSize = 20
const currentPage = ref(1)

// 详情
const showDetail = ref(false)
const detail = ref<PlaygroundHistoryDetail | null>(null)

// 加载历史列表
async function loadHistory() {
  loading.value = true
  try {
    const { data } = await apiPlaygroundHistory(currentPage.value, pageSize)
    records.value = data.records
    total.value = data.total
  } catch (e: any) {
    Message.error(`加载历史记录失败：${e.message}`)
  } finally {
    loading.value = false
  }
}

// 查看详情
async function viewDetail(id: number) {
  try {
    const { data } = await apiPlaygroundHistoryDetail(id)
    detail.value = data
    showDetail.value = true
  } catch (e: any) {
    Message.error(`加载详情失败：${e.message}`)
  }
}

// 删除记录
async function handleDelete(id: number) {
  try {
    await apiPlaygroundHistoryDelete(id)
    Message.success('删除成功')
    await loadHistory()
  } catch (e: any) {
    Message.error(`删除失败：${e.message}`)
  }
}

// 格式化时间
function formatTime(isoString: string): string {
  const d = new Date(isoString)
  return d.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// 初始化
onMounted(() => {
  loadHistory()
})
</script>

<style scoped>
.history-page {
  max-width: 1000px;
  padding: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.header-title {
  font-size: 16px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}

.loading-state,
.empty-state {
  padding: 60px 0;
  text-align: center;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.history-item {
  background: #fff;
  border: 1px solid #e5e6eb;
  border-radius: 8px;
  overflow: hidden;
  transition: box-shadow 0.2s;
}

.history-item:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.item-main {
  padding: 14px 16px;
  cursor: pointer;
}

.item-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 12px;
  color: #86909c;
}

.item-time {
  color: #4e5969;
}

.item-models {
  color: #165dff;
}

.item-duration {
  color: #0fc6c2;
}

.item-prompt {
  font-size: 13px;
  color: #1d2129;
  line-height: 1.6;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.item-actions {
  display: flex;
  gap: 4px;
  padding: 8px 16px;
  background: #fafbfc;
  border-top: 1px solid #f2f3f5;
}

.pagination {
  margin-top: 20px;
  display: flex;
  justify-content: center;
}

/* 详情弹窗 */
.detail-content {
  max-height: 70vh;
  overflow-y: auto;
}

.prompt-text {
  background: #f2f3f5;
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 8px 0 0;
}

.judge-section,
.results-section {
  margin-top: 20px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.judge-ranking {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.rank-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.rank-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 700;
  color: #fff;
}

.rank-1 { background: linear-gradient(135deg, #ffd700, #ffb800); }
.rank-2 { background: linear-gradient(135deg, #c0c0c0, #a0a0a0); }
.rank-3 { background: linear-gradient(135deg, #cd7f32, #b8651a); }

.rank-model {
  font-size: 13px;
  font-weight: 500;
}

.rank-score {
  font-size: 13px;
  color: #ff7d00;
  font-weight: 600;
}

.judge-comment {
  font-size: 13px;
  color: #4e5969;
  line-height: 1.6;
  padding: 10px 12px;
  background: #fafbfc;
  border-radius: 4px;
}

.result-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 12px;
}

.result-card {
  background: #fff;
  border: 1px solid #e5e6eb;
  border-radius: 6px;
  overflow: hidden;
}

.result-card.result-error {
  border-color: #f53f3f33;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: #fafbfc;
  border-bottom: 1px solid #e5e6eb;
}

.result-model-name {
  display: flex;
  align-items: center;
  gap: 4px;
}

.vendor-label {
  font-size: 11px;
  color: #86909c;
}

.model-label {
  font-size: 13px;
  font-weight: 600;
  color: #1d2129;
}

.result-meta {
  display: flex;
  gap: 4px;
}

.result-content {
  padding: 10px 12px;
  max-height: 300px;
  overflow-y: auto;
}

.result-text {
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  font-family: inherit;
  color: #1d2129;
}

.result-tool-calls {
  padding: 8px 12px;
  background: #f9f0ff;
  border-top: 1px solid #e8d5f5;
}

.tool-calls-title {
  font-size: 12px;
  font-weight: 600;
  color: #722ed1;
  margin-bottom: 6px;
}

.tool-call-item {
  background: #fff;
  border: 1px solid #e8d5f5;
  border-radius: 4px;
  padding: 6px 8px;
  margin-bottom: 4px;
}

.tc-args {
  font-size: 11px;
  line-height: 1.5;
  margin: 4px 0 0;
  white-space: pre-wrap;
  font-family: 'SF Mono', 'Menlo', 'Monaco', monospace;
}

.result-error-msg {
  padding: 10px 12px;
  font-size: 12px;
  color: #f53f3f;
}
</style>
