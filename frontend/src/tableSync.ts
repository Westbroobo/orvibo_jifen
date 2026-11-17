import type { Directory, Preset, Selection } from './types'

export type TableSyncSourceKind = 'preset' | 'selection'
export type TableSyncRunStatus = 'queued' | 'running' | 'success' | 'unchanged' | 'failed' | 'interrupted'
export type TableSyncRowAction = 'create' | 'update' | 'delete' | 'unchanged'
export interface TableSyncMapping { department: string; name: string; user_id: string }
export interface TableSyncPayload {
  name: string
  source_kind: TableSyncSourceKind
  preset_id: string | null
  selection: Selection
  target_url: string
  table_id: string
  field_mapping: TableSyncMapping
  cron: string
}
export interface TableSyncSummary {
  source: number; target: number; create: number; update: number; delete: number; duplicate: number; unchanged: number
  completed_create?: number; completed_update?: number; completed_delete?: number
}
export interface TableSyncTask extends TableSyncPayload {
  id: string; base_token: string; table_name: string; enabled: boolean
  next_run_at: string | null; active_run_id: string | null; last_status: TableSyncRunStatus | null
  last_summary: TableSyncSummary | null; last_run_at: string | null; config_version: number
  created_at: string; updated_at: string
}
export interface TableSyncSources { presets: Preset[]; directory: Directory }
export interface TableSyncField { id: string; name: string; type: number; writable: boolean }
export interface TableSyncInspection {
  base_token: string; table_id: string; table_name: string
  tables: { id: string; name: string }[]; fields: TableSyncField[]
}
export interface TableSyncRun {
  id: string; task_id: string; task_name: string; kind: 'preview' | 'sync'; trigger: string
  status: TableSyncRunStatus; actor_name: string | null; scheduled_at: string | null
  created_at: string; started_at: string | null; finished_at: string | null
  summary: TableSyncSummary | null; error: string | null
}
export interface TableSyncRow { action: TableSyncRowAction; record_id?: string; user_id: string; name: string; department: string; reason?: string }
export interface TableSyncLog { id: string; level: string; stage: string; message: string; created_at: string; details: unknown }
export interface TableSyncPage<T> { items: T[]; total: number; page: number }

export const syncStatusLabels: Record<TableSyncRunStatus, string> = {
  queued: '排队中', running: '执行中', success: '已完成', unchanged: '无变化', failed: '失败', interrupted: '执行中断',
}
export const syncActionLabels: Record<TableSyncRowAction, string> = { create: '新增', update: '更新', delete: '删除', unchanged: '不变' }
export function syncReasonLabel(value?: string): string {
  return ({ duplicate: '重复记录', not_in_source: '已不在当前名单', empty_user_id: '缺少 user_id' } as Record<string, string>)[value ?? ''] ?? value ?? '—'
}
export const isSyncRunning = (run?: Pick<TableSyncRun, 'status'> | null) => !!run && ['queued', 'running'].includes(run.status)
export function syncTime(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '—'
}
export function syncTriggerLabel(run: Pick<TableSyncRun, 'kind' | 'trigger'>): string {
  if (run.kind === 'preview') return '手动预览'
  return ['scheduled', 'schedule', 'cron'].includes(run.trigger) ? '定时执行' : '手动执行'
}
export function mappingComplete(mapping: TableSyncMapping): boolean {
  const values = [mapping.department, mapping.name, mapping.user_id]
  return values.every(Boolean) && new Set(values).size === values.length
}
