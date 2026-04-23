import axios from 'axios'

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || 'http://localhost:8001',
  timeout: 10000,
})

// ---------- Types ----------
export interface ModelEntry {
  id?: number
  group_id: number
  model: string
  weight: number | null
  timeout: number | null
  remark: string | null
  // 旧字段（兼容保留）
  supports_thinking: boolean
  is_thinking_only: boolean
  is_vision: boolean
  // 新字段（#7 重构）
  thinking_mode: string | null       // "none" | "optional" | "always" | null（旧数据迁移前）
  capabilities: string | null        // JSON 数组字符串，如 '["text","vision"]'
  extra_body: string | null
  expires_at: string | null
  priority: number | null
  tags: string | null
  enabled: boolean
  thinking_timeout: number | null
  ai_profile: string | null
  max_tokens: number | null          // 模型级 max_tokens 覆盖，null=继承全局
}

export interface ProviderGroup {
  id?: number
  vendor: string
  alias: string | null
  website: string | null
  api_key: string
  base_url: string
  weight: number
  timeout: number
  remark: string | null
  billing_mode: string | null
  expires_at: string | null
  priority: number
  enabled: boolean
  models: ModelEntry[]
}

export interface GlobalSettings {
  id?: number
  temperature: number
  max_tokens: number
  max_retries: number
  fault_duration: number
  default_timeout: number
  default_thinking_timeout: number | null
  timeout_retries: number
  timeout_step: number
  rate_limit_cooldown: number
}

// ---------- Providers ----------
export const apiListProviders = () => http.get<ProviderGroup[]>('/api/providers')
export const apiCreateProvider = (data: Omit<ProviderGroup, 'id' | 'models'>) => http.post<ProviderGroup>('/api/providers', data)
export const apiUpdateProvider = (id: number, data: Omit<ProviderGroup, 'id' | 'models'>) => http.put<ProviderGroup>(`/api/providers/${id}`, data)
export const apiDeleteProvider = (id: number) => http.delete(`/api/providers/${id}`)
export const apiReorderProviders = (ids: number[]) => http.put<ProviderGroup[]>('/api/providers/reorder', { ids })

export const apiAddModel = (groupId: number, data: Omit<ModelEntry, 'id' | 'group_id'>) => http.post<ModelEntry>(`/api/providers/${groupId}/models`, data)
export const apiUpdateModel = (groupId: number, modelId: number, data: Omit<ModelEntry, 'id' | 'group_id'>) => http.put<ModelEntry>(`/api/providers/${groupId}/models/${modelId}`, data)
export const apiDeleteModel = (groupId: number, modelId: number) => http.delete(`/api/providers/${groupId}/models/${modelId}`)
export const apiReorderModels = (groupId: number, ids: number[]) => http.put<ModelEntry[]>(`/api/providers/${groupId}/models/reorder`, { ids })

// ---------- Settings ----------
export const apiGetSettings = () => http.get<GlobalSettings>('/api/settings')
export const apiUpdateSettings = (data: GlobalSettings) => http.put<GlobalSettings>('/api/settings', data)

// ---------- Import / Export ----------
export const apiExport = (outputPath?: string) =>
  http.post<string>('/api/export', { output_path: outputPath || null }, { responseType: 'text' })
export const apiImportFile = (filePath: string) =>
  http.post('/api/import/file', { file_path: filePath })

// ---------- Build ----------
export interface BuildStatus {
  last_built_at: number | null
  db_updated_at: number | null
  needs_build: boolean
  python_path: string | null
  pypi_url: string | null
}

export interface BuildResult {
  ok: boolean
  wheel: string | null
  wheel_path: string | null
  uploaded: boolean
  log: string
}

export const apiBuildStatus = () => http.get<BuildStatus>('/api/build/status')
export const apiBuild = (upload = false) => http.post<BuildResult>('/api/build', { upload }, { timeout: 180000 })

// ---------- Simulate ----------
export interface SimulateRequest {
  prefer?: string | null
  thinking?: boolean | null
  vision?: boolean | null
  tags?: string | null
  exclude_tags?: string | null
  task_group?: string | null
}

export interface SimulateModelItem {
  vendor: string
  model: string
  priority: number
  weight: number
  effective_weight: number
  weight_pct: number
  is_prefer_hit: boolean
  is_tags_hit: boolean
  thinking_mode: string             // "none" / "optional" / "always"
  capabilities: string[]            // ["text"] / ["text","vision"] 等
  // 兼容旧字段
  supports_thinking: boolean
  is_thinking_only: boolean
  is_vision: boolean
  tags: string[]
  remark: string | null
  group_remark: string | null
}

export interface SimulateLayer {
  priority: number
  is_active: boolean
  models: SimulateModelItem[]
}

export interface PinnedSimulateItem {
  order: number
  vendor: string
  model: string
  in_pool: boolean
  thinking_override: boolean | null
  thinking_mode: string
  capabilities: string[]
  tags: string[]
  remark: string | null
  group_remark: string | null
}

export interface SimulateResponse {
  layers: SimulateLayer[]
  disabled_count: number
  filtered_out_count: number
  filter_reason: string
  pinned_models: PinnedSimulateItem[]
}

export interface SimulateMeta {
  tags: string[]
  vendors: string[]
  task_groups: { name: string; display_name: string | null }[]
}

export const apiSimulateMeta = () => http.get<SimulateMeta>('/api/simulate/meta')

export const apiSimulate = (body: SimulateRequest) =>
  http.post<SimulateResponse>('/api/simulate', body)

// ---------- Task Groups ----------
export interface PinnedItem {
  vm: string                  // "vendor/model"
  thinking: boolean | null    // null=继承任务组全局，true/false=覆盖
}

export interface TaskGroupWrite {
  name: string
  display_name?: string | null
  pinned?: PinnedItem[]
  exclude_tags?: string[]
  tags?: string[]
  prefer?: string[]
  thinking?: boolean | null
  remark?: string | null
  enabled: boolean
  max_tokens?: number | null         // 任务组级 max_tokens 覆盖，null=继承全局
}

export interface TaskGroupRead {
  id: number
  name: string
  display_name: string | null
  pinned: PinnedItem[]
  exclude_tags: string[]
  tags: string[]
  prefer: string[]
  thinking: boolean | null
  remark: string | null
  enabled: boolean
  max_tokens: number | null          // 任务组级 max_tokens 覆盖，null=继承全局
}

export const apiListTaskGroups = () => http.get<TaskGroupRead[]>('/api/task-groups')
export const apiCreateTaskGroup = (data: TaskGroupWrite) => http.post<TaskGroupRead>('/api/task-groups', data)
export const apiUpdateTaskGroup = (id: number, data: TaskGroupWrite) => http.put<TaskGroupRead>(`/api/task-groups/${id}`, data)
export const apiDeleteTaskGroup = (id: number) => http.delete(`/api/task-groups/${id}`)

// ---------- Probe ----------
export interface ProbeResponse {
  ok: boolean
  latency_ms: number | null
  reply: string | null
  error: string | null
}

export const apiProbe = (groupId: number, modelId: number) =>
  http.post<ProbeResponse>('/api/probe', { group_id: groupId, model_id: modelId }, { timeout: 20000 })

// ---------- AI Suggest ----------
export interface AiProfile {
  positioning: string
  description?: string      // AI 一句话适用场景描述（归入档案，不写入 entry.remark）
  strengths: string[]
  best_for: string[]
  not_for: string[]
  notes: string
  context_window: number
  max_output_tokens: number
}

export interface SuggestModelResponse {
  thinking_mode: string
  capabilities: string[]
  tags: string[]
  remark: string
  ai_profile: AiProfile
}

export const apiSuggestModel = (vendor: string, model_name: string) =>
  http.post<SuggestModelResponse>('/api/ai/suggest-model', { vendor, model_name }, { timeout: 60000 })

export const apiApplySuggest = (modelId: number) =>
  http.post(`/api/ai/suggest-model/apply/${modelId}`, {}, { timeout: 60000 })

export const apiBatchSuggest = (modelIds: number[] = [], forceRefresh = false) =>
  http.post('/api/ai/suggest-model/batch', { model_ids: modelIds, force_refresh: forceRefresh }, { timeout: 300000 })

// ---------- Playground ----------
export interface PlaygroundModelRef {
  group_id: number
  model_id: number
}

export interface AvailableModel {
  group_id: number
  model_id: number
  vendor: string
  model: string
  alias: string | null
  thinking_mode: string            // "none" | "optional" | "always"
  tags: string[]
  remark: string | null
}

export interface ToolCall {
  id: string | null
  name: string
  arguments: Record<string, any>
}

export interface ModelResult {
  group_id: number
  model_id: number
  vendor: string
  model: string
  ok: boolean
  reply: string | null
  latency_ms: number
  error: string | null
  thinking_used: boolean
  tokens_input: number | null
  tokens_output: number | null
  self_identity: string | null       // 模型自报身份（如 "Qwen3-235B，知识截止到 2025-04"）
  tool_calls: ToolCall[] | null       // 模型发起的工具调用列表
}

export interface JudgeResult {
  judge_vendor: string
  judge_model: string
  ranking: string[]
  scores: Record<string, number>
  comment: string
}

export interface PlaygroundRequest {
  prompt: string
  models: PlaygroundModelRef[]
  thinking?: boolean | null
  temperature?: number | null
  judge: boolean
  tools?: Record<string, any>[] | null   // OpenAI 格式的工具定义列表
  system_prompt?: string | null          // 自定义 system prompt
}

export interface PlaygroundResponse {
  prompt: string
  results: ModelResult[]
  judge: JudgeResult | null
  total_time_ms: number
}

export const apiPlaygroundModels = () =>
  http.get<AvailableModel[]>('/api/playground/models')

export const apiPlaygroundRun = (body: PlaygroundRequest) =>
  http.post<PlaygroundResponse>('/api/playground/run', body, { timeout: 300000 })

// ---------- Playground History ----------
export interface PlaygroundHistorySummary {
  id: number
  created_at: string
  prompt: string
  tool_mode: boolean
  total_time_ms: number
  model_count: number
}

export interface PlaygroundHistoryDetail extends PlaygroundHistorySummary {
  thinking: boolean | null
  temperature: number | null
  tools_json: string | null
  results: ModelResult[]
  judge: JudgeResult | null
  remark: string | null
}

export const apiPlaygroundHistory = (page = 1, pageSize = 20) =>
  http.get<{ records: PlaygroundHistorySummary[]; total: number }>('/api/playground/history', { params: { page, page_size: pageSize } })

export const apiPlaygroundHistoryDetail = (id: number) =>
  http.get<PlaygroundHistoryDetail>(`/api/playground/history/${id}`)

export const apiPlaygroundHistoryDelete = (id: number) =>
  http.delete(`/api/playground/history/${id}`)

// ---------- Prompt Optimizer ----------
export interface OptimizeRequest {
  raw_prompt: string
  strategy: string
  context?: string | null
  output_format?: string | null
  model_ref?: { group_id: number; model_id: number } | null
}

export interface OptimizeResponse {
  raw_prompt: string
  optimized_prompt: string
  strategy_used: string
  tips: string[]
  model_vendor: string
  model_name: string
  latency_ms: number
  tokens_input?: number | null
  tokens_output?: number | null
}

export interface StrategyItem {
  key: string
  name: string
  description: string
}

export interface StrategyGroup {
  group: string
  label: string
  items: StrategyItem[]
}

export interface RecommendRequest {
  raw_prompt: string
}

export interface RecommendResponse {
  recommended_keys: string[]
  reason: string
}

export const apiOptimizeStrategies = () =>
  http.get<StrategyGroup[]>('/api/prompt-optimizer/strategies')

export const apiRecommendStrategy = (body: RecommendRequest) =>
  http.post<RecommendResponse>('/api/prompt-optimizer/recommend', body, { timeout: 15000 })

export const apiOptimizePrompt = (body: OptimizeRequest) =>
  http.post<OptimizeResponse>('/api/prompt-optimizer/optimize', body, { timeout: 60000 })

export const apiOptimizerModels = () =>
  http.get<AvailableModel[]>('/api/prompt-optimizer/models')

// ---------- Prompt Optimizer: Compare Test ----------
export interface CompareTestRequest {
  raw_prompt: string
  optimized_prompt: string
  test_model: { group_id: number; model_id: number }
}

export interface CompareTestSingleResult {
  prompt_type: string
  reply: string
  latency_ms: number
  ok: boolean
  error: string | null
}

export interface CompareTestResponse {
  raw_prompt: string
  optimized_prompt: string
  test_model_vendor: string
  test_model_name: string
  raw_result: CompareTestSingleResult
  optimized_result: CompareTestSingleResult
}

export const apiCompareTest = (body: CompareTestRequest) =>
  http.post<CompareTestResponse>('/api/prompt-optimizer/compare-test', body, { timeout: 120000 })

// ---------- Prompt Optimizer: Ask ----------
export interface AskRequest {
  optimized_prompt: string
  test_model: { group_id: number; model_id: number }
}

export interface AskResponse {
  optimized_prompt: string
  test_model_vendor: string
  test_model_name: string
  reply: string
  latency_ms: number
  ok: boolean
  error: string | null
}

export const apiAskWithOptimized = (body: AskRequest) =>
  http.post<AskResponse>('/api/prompt-optimizer/ask', body, { timeout: 120000 })

// ---------- Prompt Optimizer: Multi Model Compare ----------
export interface MultiModelCompareRequest {
  optimized_prompt: string
  test_models: { group_id: number; model_id: number }[]
}

export interface MultiModelCompareItem {
  group_id: number
  model_id: number
  vendor: string
  model_name: string
  reply: string
  latency_ms: number
  ok: boolean
  error: string | null
}

export interface MultiModelCompareResponse {
  optimized_prompt: string
  results: MultiModelCompareItem[]
}

export const apiMultiModelCompare = (body: MultiModelCompareRequest) =>
  http.post<MultiModelCompareResponse>('/api/prompt-optimizer/multi-model-compare', body, { timeout: 180000 })
