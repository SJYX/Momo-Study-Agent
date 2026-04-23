/**
 * api/types.ts — 与后端 schemas.py 对齐的 TypeScript 类型定义。
 */

// 统一响应信封
export interface ApiResponse<T = unknown> {
  ok: boolean
  data: T | null
  error: { code: string; message: string } | null
  user_id: string
}

// /api/session
export interface SessionInfo {
  active_user: string
  ai_provider: string
  batch_size: number
  dry_run: boolean
  db_path: string
}

// /api/health
export interface HealthInfo {
  status: string
  version: string
}

// /api/study/today
export interface TodayItemsResponse {
  count: number
  items: TodayItem[]
}

export interface TodayItem {
  voc_id: string
  voc_spelling: string
  voc_meanings?: string
  review_count?: number
  familiarity_short?: number
}

// /api/study/future
export interface FutureItemsResponse {
  days: number
  count: number
  items: TodayItem[]
}

// /api/study/process & /api/study/iterate
export interface TaskSubmitResponse {
  task_id: string | null
  word_count?: number
  message?: string
}

// /api/tasks/{id}
export interface TaskStatusResponse {
  task_id: string
  status: 'pending' | 'running' | 'done' | 'error' | 'canceled'
  result: unknown
  error: string | null
  created_at: number
  started_at: number | null
  finished_at: number | null
}

// SSE event
export interface TaskEvent {
  type: 'log' | 'status' | 'heartbeat'
  level?: string
  message?: string
  module?: string
  status?: string
  error?: string
  ts: number
  event?: string
  progress?: Record<string, unknown>
}

// /api/words
export interface WordNoteSummary {
  voc_id: string
  spelling: string
  basic_meanings: string
  memory_aid: string
  it_level: number
  sync_status: number
  created_at: string
}

export interface WordsListResponse {
  total: number
  page: number
  page_size: number
  items: WordNoteSummary[]
}

// /api/words/{voc_id} detail
export interface WordNoteDetail extends WordNoteSummary {
  ielts_focus: string
  collocations: string
  traps: string
  synonyms: string
  discrimination: string
  example_sentences: string
  word_ratings: string
  tags: string
  raw_full_text: string
  it_history: string
}

// /api/stats/summary
export interface StatsSummary {
  total_words: number
  processed_words: number
  ai_batches: number
  ai_notes_count: number
  total_tokens: number
  avg_latency_ms: number
  sync_queue_depth: number
  weak_words_count: number
}

// /api/sync/status
export interface SyncConflict {
  voc_id: string
  spelling: string
  basic_meanings: string
  sync_status: number
  created_at: string
}

export interface SyncStatusResponse {
  queue_depth: number
  conflict_count: number
  conflicts: SyncConflict[]
}

// /api/users
export interface UserProfile {
  username: string
  ai_provider: string
  has_momo_token: boolean
  has_ai_key: boolean
  is_active: boolean
}

export interface UsersListResponse {
  users: UserProfile[]
  active_user: string
}

// POST /api/users/wizard
export interface WizardCreateRequest {
  username: string
  momo_token: string
  ai_provider: string
  ai_api_key: string
  user_email?: string
}

export interface WizardValidationResult {
  ok: boolean
  category?: string
  detail?: string
}

export interface WizardCreateResponse {
  username: string
  profile_path: string
  cloud_configured: boolean
  validation: Record<string, WizardValidationResult>
  message: string
}

// POST /api/users/validate
export interface ValidateRequest {
  field: string
  value: string
}

export interface ValidateResponse {
  field: string
  valid: boolean
  message: string
}

// Iteration history
export interface WordIteration {
  voc_id: string
  iteration_type: string
  score: number
  justification: string
  tags: string
  refined_content: string
  raw_response: string
  created_at: string
}

export interface WordIterationsResponse {
  voc_id: string
  iterations: WordIteration[]
}

// /api/preflight
export interface PreflightCheck {
  name: string
  ok: boolean
  status: string
  blocking: boolean
  category: string
  detail: string
  fix_hint: string
}

export interface PreflightResponse {
  username: string
  root_dir: string
  profile_path: string
  force_cloud_mode: boolean
  ok: boolean
  checks: PreflightCheck[]
  blocking_items: PreflightCheck[]
}