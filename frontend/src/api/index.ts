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
  supports_thinking: boolean
  is_thinking_only: boolean
  extra_body: string | null
  expires_at: string | null
  priority: number | null
  is_vision: boolean
  tags: string | null
  enabled: boolean
  thinking_timeout: number | null
  ai_profile: string | null
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

export interface SimulateResponse {
  layers: SimulateLayer[]
  disabled_count: number
  filtered_out_count: number
  filter_reason: string
}

export interface SimulateMeta {
  tags: string[]
  vendors: string[]
}

export const apiSimulateMeta = () => http.get<SimulateMeta>('/api/simulate/meta')

export const apiSimulate = (body: SimulateRequest) =>
  http.post<SimulateResponse>('/api/simulate', body)

// ---------- Task Groups ----------
export interface TaskGroupWrite {
  name: string
  display_name?: string | null
  pinned?: string[]
  exclude_tags?: string[]
  tags?: string[]
  prefer?: string[]
  thinking?: boolean | null
  remark?: string | null
  enabled: boolean
}

export interface TaskGroupRead {
  id: number
  name: string
  display_name: string | null
  pinned: string[]
  exclude_tags: string[]
  tags: string[]
  prefer: string[]
  thinking: boolean | null
  remark: string | null
  enabled: boolean
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
