export type Role = string
export type Permission = 'adjustments.write' | 'history.read' | 'history.recall' | 'history.retry' | 'history.others' | 'ledgers.read' | 'ledgers.export'
export interface Grant { role: Role; role_name: string; history_scope: 'own' | 'all'; ledger_scope: 'own' | 'departments' | 'all'; ledger_department_ids: string[] }
export interface RoleDefinition { id: string; name: string; description: string; permissions: Permission[]; builtin: boolean; employee_count: number }
export interface RoleCatalog { items: RoleDefinition[]; permissions: { id: Permission; name: string; requires?: Permission }[]; departments: Department[]; owner_notice: string }
export interface PermissionAuditItem { id: string; event: string; target_id: string; target_name: string; actor_name: string; before: Partial<Grant & RoleDefinition> | null; after: Partial<Grant & RoleDefinition> | null; created_at: string }
export interface Person { id: string; open_id: string; name: string; status: string; role: Role; avatar_url: string; paths: { ids: string[]; names: string[] }[] }
export interface Department { id: string; name: string; parent_id: string; path_ids: string[]; path_names: string[] }
export interface Selection { match_mode?: 'intersection' | 'union'; department_ids?: string[]; levels: string[][]; mode: 'all' | 'selected'; person_ids: string[]; extra_ids: string[] }
export interface User extends Grant { id: string; name: string; avatar_url: string; status: string; csrf_token: string; demo_mode: boolean; permissions: Permission[]; can_manage: boolean; can_configure_roles: boolean; owner_notice: string }
export interface Directory { people: Person[]; departments: Department[]; last_sync_at: string | null; last_sync_error: string | null; sync_requested: boolean }
export interface SyncSchedule { enabled: boolean; interval_days: number; time: string; next_sync_at: string | null; last_sync_at: string | null; last_sync_error: string | null; sync_requested: boolean; sync_started_at: string | null; retry_at: string | null; directory_version: number; status: 'idle' | 'queued' | 'running' | 'recovering' | 'retry' }
export interface CardContext { person_name: string; person_open_id: string; department: string; delta: number; total: number; reason: string; operator_name: string; month: string; time: string; operation: string }
export interface CardVariables { department: string; user_name: string; reason: string; score: string; total_score: string }
export interface PreviewRow { person: Person; before_total: number; final_total: number; override_total: number | null; balance_version: number; context: CardContext; card: { data: { template_id: string; template_version_name: string; template_variable: CardVariables } } }
export interface Snapshot { month: string; delta: number; reason: string; operator_name: string; rows: PreviewRow[]; recipients: Person[]; message_count: number }
export interface Preview extends Snapshot { preview_token: string; expires_at: string }
export interface Preset { id: string; name: string; scope: 'personal' | 'public'; can_edit: boolean; selection: Selection }
export interface RecallSummary { recall_statuses: Record<string, number>; recall_available: number; cancelled_scores: number; can_recall: boolean; can_retry: boolean }
export interface ScoreResult { ledger_id: string; person_id: string; original_total: number; cancelled: boolean; cancelled_at: string | null; current_total: number }
export interface HistoryItem extends RecallSummary { id: string; month: string; delta: number; reason: string; created_at: string; operator_name: string; operator_avatar_url: string; people: Pick<Person, 'id' | 'name' | 'avatar_url'>[]; names: string[]; message_count: number; statuses: Record<string, number> }
export interface ScoreLedgerItem { id: string; batch_id: string; employee_id: string; month: string; person_name: string; avatar_url: string; paths: Person['paths']; delta: number; before_total: number; final_total: number; override_total: number | null; reason: string; operator_name: string; created_at: string; cancelled: boolean; cancelled_at: string | null }
export interface ScoreLedgerResponse { items: ScoreLedgerItem[]; total: number; page: number; page_size: number; month: string; summary: { plus_total: number; minus_total: number }; departments: Department[] }
export interface Delivery { id: string; person_id: string; recipient_name: string; status: string; attempts: number; message_id: string | null; sent_at: string | null; last_error: string | null; recall_status: string | null; recall_error: string | null; recalled_at: string | null; recall_deadline: string | null; can_recall: boolean }
export interface BatchDetail extends RecallSummary { id: string; snapshot: Snapshot; scores: ScoreResult[]; created_at: string; deliveries: Delivery[]; statuses: Record<string, number>; total: number; page: number }
export const emptySelection = (): Selection => ({ levels: [[], [], []], mode: 'selected', person_ids: [], extra_ids: [] })
export const unionSelection = (): Selection => ({ ...emptySelection(), match_mode: 'union', department_ids: [] })
export const statusLabels: Record<string, string> = { pending: '待发送', sending: '发送中', sent: '已发送', failed: '发送失败', review: '待核实', active: '在职', resigned: '离职', inactive: '不可用', unknown: '待核实' }
export const recallLabels: Record<string, string> = { pending: '待撤回', recalling: '撤回中', recalled: '已撤回', failed: '撤回失败', review: '撤回待核实' }
