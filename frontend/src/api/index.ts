import axios from 'axios'

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || 'http://localhost:8000',
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
  enabled: boolean
}

export interface ProviderGroup {
  id?: number
  vendor: string
  api_key: string
  base_url: string
  weight: number
  timeout: number
  remark: string | null
  billing_mode: string | null
  expires_at: string | null
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
  timeout_retries: number
  timeout_step: number
  rate_limit_cooldown: number
}

// ---------- Providers ----------
export const apiListProviders = () => http.get<ProviderGroup[]>('/api/providers')
export const apiCreateProvider = (data: Omit<ProviderGroup, 'id' | 'models'>) => http.post<ProviderGroup>('/api/providers', data)
export const apiUpdateProvider = (id: number, data: Omit<ProviderGroup, 'id' | 'models'>) => http.put<ProviderGroup>(`/api/providers/${id}`, data)
export const apiDeleteProvider = (id: number) => http.delete(`/api/providers/${id}`)

export const apiAddModel = (groupId: number, data: Omit<ModelEntry, 'id' | 'group_id'>) => http.post<ModelEntry>(`/api/providers/${groupId}/models`, data)
export const apiUpdateModel = (groupId: number, modelId: number, data: Omit<ModelEntry, 'id' | 'group_id'>) => http.put<ModelEntry>(`/api/providers/${groupId}/models/${modelId}`, data)
export const apiDeleteModel = (groupId: number, modelId: number) => http.delete(`/api/providers/${groupId}/models/${modelId}`)

// ---------- Settings ----------
export const apiGetSettings = () => http.get<GlobalSettings>('/api/settings')
export const apiUpdateSettings = (data: GlobalSettings) => http.put<GlobalSettings>('/api/settings', data)

// ---------- Import / Export ----------
export const apiExport = (outputPath?: string) =>
  http.post<string>('/api/export', { output_path: outputPath || null }, { responseType: 'text' })
export const apiImportFile = (filePath: string) =>
  http.post('/api/import/file', { file_path: filePath })
