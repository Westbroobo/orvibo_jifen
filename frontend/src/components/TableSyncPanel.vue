<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api'
import { unionSelection } from '../types'
import type { Directory, Preset } from '../types'
import { isSyncRunning, mappingComplete, syncActionLabels, syncReasonLabel, syncStatusLabels, syncTime, syncTriggerLabel } from '../tableSync'
import type { TableSyncField, TableSyncInspection, TableSyncLog, TableSyncPage, TableSyncPayload, TableSyncRow, TableSyncRun, TableSyncTask } from '../tableSync'
import RecipientRangeEditor from './RecipientRangeEditor.vue'
import RecipientPresetSelect from './RecipientPresetSelect.vue'

const prefix = '/table-sync'
const tasks = ref<TableSyncTask[]>([]), taskTotal = ref(0), taskPage = ref(1)
const sources = ref<Preset[]>([])
const directory = ref<Directory>({ people: [], departments: [], last_sync_at: null, last_sync_error: null, sync_requested: false })
const sourcesLoading = ref(false), tasksLoading = ref(false), runsLoading = ref(false), detailsLoading = ref(false)
const selectedTask = ref<TableSyncTask | null>(null), editing = ref(false)
const overview = ref(true)
const pendingEditor = ref<TableSyncTask | 'new' | null>(null)
const tab = ref<'config' | 'runs'>('config')
const draft = ref<TableSyncPayload>(emptyDraft()), baseline = ref('')
const editorVersion = ref(0)
const fields = ref<TableSyncField[]>([]), targetTables = ref<{ id: string; name: string }[]>([]), targetName = ref('')
const nextRuns = ref<string[]>([])
const error = ref(''), feedback = ref(''), pendingAction = ref(''), confirmDelete = ref(false)
const runs = ref<TableSyncRun[]>([]), runTotal = ref(0), runPage = ref(1)
const runTask = ref<Pick<TableSyncTask, 'id' | 'name'> | null>(null)
const statusFilter = ref('all'), kindFilter = ref('all')
const selectedRun = ref<TableSyncRun | null>(null)
const rows = ref<TableSyncRow[]>([]), rowTotal = ref(0), rowPage = ref(1), rowFilter = ref('all')
const logs = ref<TableSyncLog[]>([]), logTotal = ref(0), logPage = ref(1)
let sourcesRequest: AbortController | undefined, tasksRequest: AbortController | undefined, runsRequest: AbortController | undefined
let detailsRequest: AbortController | undefined, actionRequest: AbortController | undefined
let taskSequence = 0, runsSequence = 0, detailsSequence = 0
let timer: ReturnType<typeof setInterval> | undefined, polling = false, disposed = false

function emptyDraft(): TableSyncPayload {
  return { name: '', source_kind: 'selection', preset_id: null, selection: unionSelection(), target_url: '', table_id: '', field_mapping: { department: '', name: '', user_id: '' }, cron: '0 4 * * *' }
}
const working = computed(() => !!pendingAction.value)
const dirty = computed(() => editing.value && JSON.stringify(draft.value) !== baseline.value)
const stale = computed(() => !!selectedTask.value && selectedTask.value.config_version !== editorVersion.value)
const writableFields = computed(() => fields.value.filter(field => field.type === 1 && field.writable))
const canSave = computed(() => !!draft.value.name.trim() && !!draft.value.target_url.trim() && !!draft.value.table_id &&
  mappingComplete(draft.value.field_mapping) && !!draft.value.cron.trim() && (draft.value.source_kind === 'selection' || !!draft.value.preset_id))
const canExecute = computed(() => !!selectedTask.value && !dirty.value && !stale.value && !selectedTask.value.active_run_id && !working.value)
const hasRunning = computed(() => tasks.value.some(task => !!task.active_run_id) || !!selectedTask.value?.active_run_id ||
  tab.value === 'runs' && (isSyncRunning(selectedRun.value) || runs.value.some(isSyncRunning)))
const taskPages = computed(() => Math.max(1, Math.ceil(taskTotal.value / 20)))
const runPages = computed(() => Math.max(1, Math.ceil(runTotal.value / 20)))
const rowPages = computed(() => Math.max(1, Math.ceil(rowTotal.value / 100)))
const logPages = computed(() => Math.max(1, Math.ceil(logTotal.value / 100)))
const fieldLabels = { department: '部门', name: '姓名', user_id: 'user_id' } as const
const mappingKeys = ['department', 'name', 'user_id'] as const

function message(e: unknown) { return e instanceof Error ? e.message : '操作失败，请稍后重试' }
function activeRunLabel(task: TableSyncTask) {
  const run = selectedRun.value?.id === task.active_run_id ? selectedRun.value : runs.value.find(item => item.id === task.active_run_id)
  return isSyncRunning(run) ? syncStatusLabels[run!.status] : '排队或执行中'
}
function setTask(task: TableSyncTask) {
  selectedTask.value = task
  const value: TableSyncPayload = {
    name: task.name, source_kind: task.source_kind, preset_id: task.preset_id,
    selection: task.source_kind === 'selection' ? task.selection : unionSelection(),
    target_url: task.target_url, table_id: task.table_id, field_mapping: task.field_mapping, cron: task.cron,
  }
  draft.value = JSON.parse(JSON.stringify(value)); baseline.value = JSON.stringify(draft.value)
  editorVersion.value = task.config_version
  editing.value = true; overview.value = false; fields.value = []; targetTables.value = []; targetName.value = task.table_name
  nextRuns.value = []; confirmDelete.value = false
}
function clearRun() {
  detailsRequest?.abort(); ++detailsSequence
  selectedRun.value = null; rows.value = []; rowTotal.value = 0; rowPage.value = 1; rowFilter.value = 'all'
  logs.value = []; logTotal.value = 0; logPage.value = 1; detailsLoading.value = false
}
function beginNewTask() {
  if (working.value) return
  selectedTask.value = null; editing.value = true; overview.value = false; draft.value = emptyDraft(); baseline.value = JSON.stringify(draft.value)
  tab.value = 'config'; fields.value = []; targetTables.value = []; targetName.value = ''; nextRuns.value = []
  confirmDelete.value = false; pendingEditor.value = null; error.value = ''; feedback.value = ''
}
function newTask() {
  if (working.value) return
  if (dirty.value) { pendingEditor.value = 'new'; return }
  beginNewTask()
}
function beginTask(task: TableSyncTask) {
  setTask(task); pendingEditor.value = null; tab.value = 'config'; error.value = ''; feedback.value = ''
}
function openTask(task: TableSyncTask) {
  if (working.value) return
  if (dirty.value) { pendingEditor.value = task; return }
  beginTask(task)
}
function continueEditing() {
  pendingEditor.value = null; overview.value = false
}
function discardAndContinue() {
  if (working.value) return
  const target = pendingEditor.value
  if (target === 'new') beginNewTask()
  else if (target) beginTask(tasks.value.find(task => task.id === target.id) ?? target)
}
function showTaskList() {
  if (working.value) return
  overview.value = true; confirmDelete.value = false; pendingEditor.value = null
}
function sourceLabel(task: TableSyncTask) {
  return task.source_kind === 'preset' ? sources.value.find(preset => preset.id === task.preset_id)?.name || '公共名单' : '任务专属名单'
}
function targetChanged() {
  draft.value.table_id = ''; draft.value.field_mapping = { department: '', name: '', user_id: '' }
  fields.value = []; targetTables.value = []; targetName.value = ''
}
function tableChanged() {
  draft.value.field_mapping = { department: '', name: '', user_id: '' }; fields.value = []
  targetName.value = targetTables.value.find(table => table.id === draft.value.table_id)?.name ?? ''
}
async function perform(name: string, fn: (signal: AbortSignal) => Promise<void>) {
  if (working.value || disposed) return
  if (['save', 'enabled', 'delete', 'preview', 'run'].includes(name)) {
    tasksRequest?.abort(); tasksRequest = undefined; ++taskSequence; tasksLoading.value = false
  }
  const request = new AbortController(); actionRequest = request; pendingAction.value = name
  error.value = ''; feedback.value = ''
  try { await fn(request.signal) }
  catch (e) { if (!request.signal.aborted && !disposed) error.value = message(e) }
  finally { if (actionRequest === request) { actionRequest = undefined; pendingAction.value = '' } }
}
async function loadSources() {
  sourcesRequest?.abort(); const request = new AbortController(); sourcesRequest = request; sourcesLoading.value = true
  try {
    const data = await api<{ presets: Preset[]; directory: Directory }>(`${prefix}/sources`, 'GET', undefined, request.signal)
    if (request.signal.aborted || disposed) return
    sources.value = data.presets.filter(preset => preset.scope === 'public'); directory.value = data.directory
  } catch (e) { if (!request.signal.aborted && !disposed) error.value = message(e) }
  finally { if (sourcesRequest === request) { sourcesRequest = undefined; sourcesLoading.value = false } }
}
async function loadTasks(showLoading = true) {
  tasksRequest?.abort(); const request = new AbortController(), sequence = ++taskSequence
  const selectedId = selectedTask.value?.id
  tasksRequest = request; if (showLoading) tasksLoading.value = true
  try {
    const data = await api<TableSyncPage<TableSyncTask>>(`${prefix}/tasks?page=${taskPage.value}`, 'GET', undefined, request.signal)
    if (request.signal.aborted || sequence !== taskSequence || disposed) return
    tasks.value = data.items; taskTotal.value = data.total; taskPage.value = data.page
    if (selectedId && selectedTask.value?.id === selectedId) {
      const updated = data.items.find(task => task.id === selectedId) ??
        await api<TableSyncTask>(`${prefix}/tasks/${selectedId}`, 'GET', undefined, request.signal)
      if (!request.signal.aborted && sequence === taskSequence && selectedTask.value?.id === selectedId && !disposed) selectedTask.value = updated
    }
  } catch (e) { if (!request.signal.aborted && sequence === taskSequence && !disposed) error.value = message(e) }
  finally { if (tasksRequest === request) { tasksRequest = undefined; tasksLoading.value = false } }
}
async function loadRuns(showLoading = true) {
  const taskId = runTask.value?.id
  runsRequest?.abort(); const request = new AbortController(), sequence = ++runsSequence
  runsRequest = request; if (showLoading) runsLoading.value = true
  const query = new URLSearchParams({ page: String(runPage.value), status: statusFilter.value })
  if (taskId) query.set('task_id', taskId)
  if (kindFilter.value !== 'all') query.set('kind', kindFilter.value)
  try {
    const data = await api<TableSyncPage<TableSyncRun>>(`${prefix}/runs?${query}`, 'GET', undefined, request.signal)
    if (request.signal.aborted || sequence !== runsSequence || runTask.value?.id !== taskId || disposed) return
    runs.value = data.items; runTotal.value = data.total; runPage.value = data.page
  } catch (e) { if (!request.signal.aborted && sequence === runsSequence && !disposed) error.value = message(e) }
  finally { if (runsRequest === request) { runsRequest = undefined; runsLoading.value = false } }
}
async function loadRunDetails(showLoading = true) {
  const runId = selectedRun.value?.id
  if (!runId) return
  detailsRequest?.abort(); const request = new AbortController(), sequence = ++detailsSequence
  detailsRequest = request; if (showLoading) detailsLoading.value = true
  try {
    const [run, result, events] = await Promise.all([
      api<TableSyncRun>(`${prefix}/runs/${runId}`, 'GET', undefined, request.signal),
      api<TableSyncPage<TableSyncRow>>(`${prefix}/runs/${runId}/rows?action=${rowFilter.value}&page=${rowPage.value}`, 'GET', undefined, request.signal),
      api<TableSyncPage<TableSyncLog>>(`${prefix}/runs/${runId}/logs?page=${logPage.value}`, 'GET', undefined, request.signal),
    ])
    if (request.signal.aborted || sequence !== detailsSequence || selectedRun.value?.id !== runId || disposed) return
    selectedRun.value = run; rows.value = result.items; rowTotal.value = result.total; rowPage.value = result.page
    logs.value = events.items; logTotal.value = events.total; logPage.value = events.page
  } catch (e) { if (!request.signal.aborted && sequence === detailsSequence && !disposed) error.value = message(e) }
  finally { if (detailsRequest === request) { detailsRequest = undefined; detailsLoading.value = false } }
}
async function openRun(run: TableSyncRun) {
  clearRun(); selectedRun.value = run; tab.value = 'runs'; await loadRunDetails()
}
async function switchTab(value: 'config' | 'runs', focus = false) {
  if (working.value) return
  tab.value = value; pendingEditor.value = null
  if (focus) document.getElementById(`sync-tab-${value}`)?.focus()
  if (value === 'runs') await loadRuns()
}
async function showRuns(task: TableSyncTask | null = null) {
  if (working.value) return
  pendingEditor.value = null
  runTask.value = task ? { id: task.id, name: task.name } : null
  tab.value = 'runs'; clearRun()
  runs.value = []; runTotal.value = 0
  runPage.value = 1; statusFilter.value = 'all'; kindFilter.value = 'all'; await loadRuns()
}
async function inspectTarget() {
  if (!draft.value.target_url.trim()) return
  await perform('inspect', async signal => {
    const result = await api<TableSyncInspection>(`${prefix}/inspect`, 'POST', {
      url: draft.value.target_url.trim(), ...(draft.value.table_id ? { table_id: draft.value.table_id } : {}),
    }, signal)
    if (signal.aborted || disposed) return
    targetTables.value = result.tables; fields.value = result.fields; draft.value.table_id = result.table_id || ''
    targetName.value = result.table_name || ''
    for (const key of mappingKeys) {
      const current = draft.value.field_mapping[key]
      if (!writableFields.value.some(field => field.id === current)) {
        draft.value.field_mapping[key] = writableFields.value.find(field => field.name === fieldLabels[key])?.id ?? ''
      }
    }
    feedback.value = result.table_id ? `已读取“${result.table_name}”的字段，请核对下方映射。` : '请选择目标数据表，再点击“读取目标表”。'
  })
}
async function checkCron() {
  await perform('cron', async signal => {
    const result = await api<{ cron: string; timezone: string; next_runs: string[] }>(`${prefix}/cron`, 'POST', { cron: draft.value.cron }, signal)
    if (signal.aborted || disposed) return
    draft.value.cron = result.cron; nextRuns.value = result.next_runs
  })
}
async function saveTask() {
  if (!canSave.value) return
  await perform('save', async signal => {
    const id = selectedTask.value?.id
    const payload = JSON.parse(JSON.stringify(draft.value)) as TableSyncPayload
    payload.name = payload.name.trim(); payload.target_url = payload.target_url.trim()
    if (payload.source_kind === 'selection') payload.preset_id = null
    const saved = await api<TableSyncTask>(`${prefix}/tasks${id ? '/' + id : ''}`, id ? 'PUT' : 'POST', {
      ...payload, ...(id ? { config_version: editorVersion.value } : {}),
    }, signal)
    if (signal.aborted || disposed) return
    clearRun(); setTask(saved); feedback.value = id ? '任务已保存。' : '任务已保存，定时执行默认关闭。'
    await loadTasks(false)
  })
}
async function toggleEnabled() {
  const task = selectedTask.value
  if (!task) return
  await perform('enabled', async signal => {
    const updated = await api<TableSyncTask>(`${prefix}/tasks/${task.id}/enabled`, 'PATCH', { enabled: !task.enabled }, signal)
    if (signal.aborted || disposed) return
    selectedTask.value = updated; tasks.value = tasks.value.map(item => item.id === updated.id ? updated : item)
    feedback.value = updated.enabled ? '已开启定时执行。' : '已关闭定时执行，仍可手动执行。'
  })
}
async function execute(kind: 'preview' | 'run') {
  if (!canExecute.value || !selectedTask.value) return
  await perform(kind, async signal => {
    const run = await api<TableSyncRun>(`${prefix}/tasks/${selectedTask.value!.id}/${kind}`, 'POST', {}, signal)
    if (signal.aborted || disposed) return
    selectedTask.value = { ...selectedTask.value!, active_run_id: run.id }
    tasks.value = tasks.value.map(task => task.id === run.task_id ? { ...task, active_run_id: run.id } : task)
    runTask.value = { id: selectedTask.value.id, name: selectedTask.value.name }
    runPage.value = 1; statusFilter.value = 'all'; kindFilter.value = 'all'
    await openRun(run); await loadRuns(false)
    feedback.value = kind === 'preview' ? '预览已排队，不会写入多维表。' : '单次执行已排队，原定时计划不变。'
  })
}
async function removeTask() {
  const task = selectedTask.value
  if (!task) return
  await perform('delete', async signal => {
    await api(`${prefix}/tasks/${task.id}`, 'DELETE', undefined, signal)
    if (signal.aborted || disposed) return
    selectedTask.value = null; editing.value = false; overview.value = true; confirmDelete.value = false; clearRun()
    feedback.value = '任务已删除，目标表数据和历史执行记录保留。'; await loadTasks(false)
  })
}
async function poll() {
  if (polling || disposed || document.hidden || working.value || !hasRunning.value) return
  polling = true
  try {
    const work: Promise<void>[] = [loadTasks(false)]
    if (tab.value === 'runs') work.push(loadRuns(false))
    if (tab.value === 'runs' && isSyncRunning(selectedRun.value)) work.push(loadRunDetails(false))
    await Promise.allSettled(work)
  } finally { polling = false }
}
function visibleAgain() { if (!document.hidden) void poll() }
async function changeTaskPage(value: number) { taskPage.value = value; await loadTasks() }
async function filterRuns() { runPage.value = 1; await loadRuns() }
async function changeRunPage(value: number) { runPage.value = value; await loadRuns() }
async function filterRows() { rowPage.value = 1; await loadRunDetails() }
async function changeRowPage(value: number) { rowPage.value = value; await loadRunDetails() }
async function changeLogPage(value: number) { logPage.value = value; await loadRunDetails() }
function logDetails(value: unknown) { return typeof value === 'string' ? value : JSON.stringify(value, null, 2) }
watch(draft, () => { if (dirty.value && selectedRun.value?.kind === 'preview' && selectedRun.value.task_id === selectedTask.value?.id) clearRun() }, { deep: true })
onMounted(async () => {
  await Promise.allSettled([loadSources(), loadTasks()])
  if (disposed) return
  timer = setInterval(() => { void poll() }, 3000)
  document.addEventListener('visibilitychange', visibleAgain)
})
onUnmounted(() => {
  disposed = true; clearInterval(timer)
  document.removeEventListener('visibilitychange', visibleAgain)
  for (const request of [sourcesRequest, tasksRequest, runsRequest, detailsRequest, actionRequest]) request?.abort()
  ++taskSequence; ++runsSequence; ++detailsSequence
})
</script>

<template>
  <main class="sync-page" aria-label="名单同步">
    <header class="sync-navigation">
      <div class="sync-tabs" role="tablist" aria-label="名单同步视图" @keydown.left.prevent="switchTab(tab === 'config' ? 'runs' : 'config', true)" @keydown.right.prevent="switchTab(tab === 'config' ? 'runs' : 'config', true)" @keydown.home.prevent="switchTab('config', true)" @keydown.end.prevent="switchTab('runs', true)">
        <button id="sync-tab-config" type="button" role="tab" aria-controls="sync-panel-config" :aria-selected="tab === 'config'" :tabindex="tab === 'config' ? 0 : -1" :class="{ active: tab === 'config' }" :disabled="working" @click="switchTab('config')">同步任务</button>
        <button id="sync-tab-runs" type="button" role="tab" aria-controls="sync-panel-runs" :aria-selected="tab === 'runs'" :tabindex="tab === 'runs' ? 0 : -1" :class="{ active: tab === 'runs' }" :disabled="working" @click="switchTab('runs')">执行记录</button>
      </div>
      <div v-if="tab === 'config'" class="sync-page-actions"><button type="button" :disabled="tasksLoading || working" :aria-busy="tasksLoading" @click="loadTasks()"><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M16.5 8a7 7 0 0 0-12-3L2 8m0-4v4h4M3.5 12a7 7 0 0 0 12 3l2.5-3m0 4v-4h-4" /></svg>{{ tasksLoading ? '刷新中…' : '刷新' }}</button><button type="button" class="primary-button" :disabled="working" @click="newTask"><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M10 4v12M4 10h12" /></svg>新建任务</button></div>
    </header>
    <p v-if="error" class="sync-feedback error-text" role="alert">{{ error }}</p>
    <p v-if="feedback" class="sync-feedback sync-success" role="status">{{ feedback }}</p>
    <div v-if="pendingEditor" class="sync-draft-notice" role="alert"><span>当前配置尚未保存，切换任务将丢失这些修改。</span><div class="sync-inline-actions"><button type="button" :disabled="working" @click="continueEditing">继续编辑</button><button type="button" class="sync-danger" :disabled="working" @click="discardAndContinue">放弃修改并继续</button></div></div>
    <div v-if="tab === 'config'" id="sync-panel-config" class="sync-content" role="tabpanel" aria-labelledby="sync-tab-config">
      <template v-if="overview">
        <div v-if="editing && dirty && !pendingEditor" class="sync-draft-notice" role="status"><span>未保存的配置：<b>{{ draft.name || '新建任务' }}</b></span><button type="button" :disabled="working" @click="continueEditing">继续编辑</button></div>
        <section class="panel sync-task-list" aria-label="同步任务列表">
          <div class="sync-task-table" role="table" aria-label="同步任务" :aria-busy="tasksLoading">
            <div class="sync-task-table-head" role="rowgroup"><div class="sync-task-row" role="row"><span role="columnheader">任务 / 人员来源</span><span role="columnheader">目标多维表</span><span role="columnheader">定时计划</span><span role="columnheader">最近执行</span><span role="columnheader">操作</span></div></div>
            <div role="rowgroup">
              <div v-for="task in tasks" :key="task.id" class="sync-task-row sync-task-data" role="row">
                <div class="sync-task-info" role="cell"><b>{{ task.name }}</b><small>{{ sourceLabel(task) }}</small></div>
                <div class="sync-task-target" role="cell"><a :href="task.target_url" target="_blank" rel="noopener noreferrer" :aria-label="`打开目标多维表：${task.table_name || task.name}`">{{ task.table_name || '待检查目标表' }}<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M9 3h4v4M13 3 7 9M6 3H3v10h10v-3" /></svg></a></div>
                <div class="sync-task-schedule" role="cell"><span class="sync-badge" :class="task.enabled ? 'state-good' : 'state-neutral'">{{ task.enabled ? '定时开启' : '定时关闭' }}</span><small v-if="task.enabled">下次 {{ syncTime(task.next_run_at) }}</small><small v-else>可手动执行</small></div>
                <div class="sync-task-result" role="cell"><span v-if="task.active_run_id" class="sync-badge state-neutral">{{ activeRunLabel(task) }}</span><span v-else-if="task.last_status" class="sync-badge" :class="['failed', 'interrupted'].includes(task.last_status) ? 'state-error' : ['success', 'unchanged'].includes(task.last_status) ? 'state-good' : 'state-neutral'">{{ syncStatusLabels[task.last_status] }}</span><span v-else class="hint">尚未执行</span><small v-if="task.last_run_at">{{ syncTime(task.last_run_at) }}</small></div>
                <div class="sync-row-actions" role="cell"><button type="button" class="sync-task" :disabled="working" @click="openTask(task)">配置</button><button type="button" class="sync-link-button" :disabled="working" @click="showRuns(task)">查看记录</button></div>
              </div>
            </div>
          </div>
          <div v-if="!tasks.length" class="sync-empty" role="status"><svg viewBox="0 0 40 40" fill="none" aria-hidden="true"><path d="M8 8h24v25H8zM8 15h24M16 15v18M13 4v8M27 4v8" /></svg><b>{{ tasksLoading ? '正在加载任务…' : '暂无同步任务' }}</b><p v-if="!tasksLoading">点击右上角“新建任务”，配置人员来源和目标表。</p></div>
          <footer class="sync-list-footer"><span>共 {{ taskTotal }} 个任务</span><div v-if="taskPages > 1" class="pagination"><button type="button" :disabled="tasksLoading || taskPage <= 1" @click="changeTaskPage(taskPage - 1)">上一页</button><small>{{ taskPage }} / {{ taskPages }}</small><button type="button" :disabled="tasksLoading || taskPage >= taskPages" @click="changeTaskPage(taskPage + 1)">下一页</button></div></footer>
        </section>
      </template>
      <section v-else class="sync-main" aria-label="同步任务配置">
        <div class="sync-editor-heading"><div><button type="button" class="sync-back-button" :disabled="working" @click="showTaskList"><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m8 5-5 5 5 5M3 10h14" /></svg>返回任务列表</button><h2>{{ selectedTask ? selectedTask.name : '新建同步任务' }}</h2></div><button v-if="selectedTask" type="button" class="sync-link-button" :disabled="working" @click="showRuns(selectedTask)">查看执行记录</button></div>
        <div class="panel sync-task-header">
          <div v-if="selectedTask" class="sync-execution-bar"><div><b>单次操作</b><p class="hint">先预览同步差异，确认后执行。</p></div><div class="sync-toolbar"><button type="button" :disabled="!canExecute" @click="execute('preview')">{{ pendingAction === 'preview' ? '正在提交…' : '预览同步差异' }}</button><button type="button" class="primary-button" :disabled="!canExecute" @click="execute('run')">{{ pendingAction === 'run' ? '正在提交…' : '手动执行一次' }}</button></div></div><p v-else class="hint">新任务保存后默认关闭定时，可先预览并手动核对。</p>
          <p v-if="dirty" class="hint">配置有改动，请先保存。</p><p v-else-if="selectedTask?.active_run_id" class="hint">已有任务排队或执行中，可在执行记录中查看进度。</p>
          <p v-if="stale" class="error-text" role="alert">任务配置已被其他管理员更新，请重新选择此任务后继续。</p>
        </div>
        <form class="panel sync-form" @submit.prevent="saveTask">
          <fieldset :disabled="working">
            <div><label class="field-label" for="sync-name">任务名称</label><input id="sync-name" v-model="draft.name" maxlength="100" required placeholder="例如：战报推送名单同步"></div>
            <section class="sync-form-section"><h3>人员来源</h3><div class="sync-source-choice"><label><input v-model="draft.source_kind" type="radio" value="selection">任务专属名单</label><label><input v-model="draft.source_kind" type="radio" value="preset">引用公共名单</label></div>
              <template v-if="draft.source_kind === 'selection'"><p class="hint">仅用于本任务，在部门全员和指定人员中合并去重。</p><RecipientRangeEditor v-if="!sourcesLoading" v-model="draft.selection" :people="directory.people" :departments="directory.departments" /><p v-else class="hint">正在加载部门与人员…</p></template>
              <template v-else><RecipientPresetSelect id="sync-preset" :model-value="draft.preset_id ?? ''" :presets="sources" :directory="directory" placeholder="选择公共名单" :disabled="working || sourcesLoading" @update:model-value="draft.preset_id = $event" /><p class="hint">每次执行使用该公共名单的最新配置。</p></template>
            </section>
            <section class="sync-form-section"><h3>目标多维表</h3><label class="field-label" for="sync-url">数据表链接</label><div class="sync-input-action"><input id="sync-url" v-model="draft.target_url" type="url" required placeholder="粘贴目标数据表链接" @input="targetChanged"><button type="button" :disabled="working || !draft.target_url.trim()" @click="inspectTarget">{{ pendingAction === 'inspect' ? '正在读取…' : '读取目标表' }}</button></div><p class="hint">从需要同步的数据表复制链接；该表的人员记录将与本任务名单保持一致。</p>
              <div v-if="targetTables.length > 1 || targetTables.length && !draft.table_id"><label class="field-label" for="sync-table">目标数据表</label><select id="sync-table" v-model="draft.table_id" @change="tableChanged"><option value="">请选择数据表</option><option v-for="table in targetTables" :key="table.id" :value="table.id">{{ table.name }}</option></select><p class="hint">选择后点击“读取目标表”获取该表字段。</p></div>
              <p v-if="targetName" class="sync-target-name">目标：<b>{{ targetName }}</b></p>
              <div class="sync-mappings"><div v-for="key in mappingKeys" :key="key"><label class="field-label" :for="`sync-field-${key}`">{{ fieldLabels[key] }} → 目标文本字段</label><select :id="`sync-field-${key}`" v-model="draft.field_mapping[key]"><option value="">请选择字段</option><option v-if="draft.field_mapping[key] && !writableFields.some(field => field.id === draft.field_mapping[key])" :value="draft.field_mapping[key]">已保存的“{{ fieldLabels[key] }}”字段</option><option v-for="field in writableFields" :key="field.id" :value="field.id">{{ field.name }}</option></select></div></div>
              <p v-if="fields.length && writableFields.length < 3" class="error-text">目标表至少需要三个可写的文本字段，用于部门、姓名和 user_id。</p><p v-else class="hint">按 user_id 匹配人员，新增缺少记录、更新变化字段并删除多余记录；已有记录的自动编号保留。</p>
            </section>
            <section class="sync-form-section"><h3>定时计划</h3><div v-if="selectedTask" class="sync-schedule"><div><b>自动执行</b><p class="hint">{{ selectedTask.enabled ? `下次执行：${syncTime(selectedTask.next_run_at)}` : '已关闭，仍可手动执行一次。' }}</p></div><button type="button" role="switch" :aria-checked="selectedTask.enabled" aria-label="定时执行开关" :disabled="working" @click="toggleEnabled">{{ selectedTask.enabled ? '关闭定时' : '开启定时' }}</button></div><label class="field-label" for="sync-cron">Cron 表达式 · 北京时间</label><div class="sync-input-action"><input id="sync-cron" v-model="draft.cron" required placeholder="0 4 * * *" @input="nextRuns = []"><button type="button" :disabled="working || !draft.cron.trim()" @click="checkCron">查看执行时间</button></div><p class="hint">五段依次为：分、时、日、月、星期。例如 0 4 * * * 表示每天 04:00。保存后生效，无需重启。</p><ul v-if="nextRuns.length" class="sync-next-runs" aria-label="预计执行时间"><li v-for="time in nextRuns" :key="time">{{ syncTime(time) }}</li></ul></section>
          </fieldset>
          <div class="sync-save-actions"><button type="submit" class="primary-button" :disabled="working || !canSave || stale || !!selectedTask?.active_run_id">{{ pendingAction === 'save' ? '正在保存…' : '保存任务' }}</button><button v-if="selectedTask && !confirmDelete" type="button" class="sync-danger" :disabled="working || !!selectedTask.active_run_id" @click="confirmDelete = true">删除任务</button><template v-if="confirmDelete"><span class="hint">删除任务？目标表数据和历史记录保留。</span><button type="button" :disabled="working" @click="confirmDelete = false">取消</button><button type="button" class="sync-danger" :disabled="working || !!selectedTask?.active_run_id" @click="removeTask">确认删除</button></template></div>
        </form>
      </section>
    </div>
    <section v-else id="sync-panel-runs" class="panel sync-runs" role="tabpanel" aria-labelledby="sync-tab-runs">
          <div class="sync-section-head"><h2>{{ runTask ? runTask.name : '全部执行记录' }} <small>{{ runTotal }}</small></h2><div class="sync-inline-actions"><button v-if="runTask" type="button" :disabled="working" @click="showRuns()">全部任务</button><button type="button" :disabled="runsLoading" @click="loadRuns()">刷新</button></div></div>
          <div class="sync-run-filters"><select v-model="statusFilter" aria-label="筛选执行状态" @change="filterRuns"><option value="all">全部状态</option><option value="failed">执行失败</option><option value="interrupted">执行中断</option><option value="queued">排队中</option><option value="running">执行中</option><option value="success">已完成</option><option value="unchanged">无变化</option></select><select v-model="kindFilter" aria-label="筛选执行类型" @change="filterRuns"><option value="all">全部类型</option><option value="sync">同步执行</option><option value="preview">预览检查</option></select></div>
          <button v-for="run in runs" :key="run.id" type="button" class="sync-run-item" :class="{ selected: selectedRun?.id === run.id }" @click="openRun(run)"><span><b>{{ !runTask ? `${run.task_name} · ` : '' }}{{ syncTriggerLabel(run) }}</b><small>{{ syncTime(run.created_at) }} · {{ run.actor_name || '系统' }}</small><small v-if="run.error" class="error-text">{{ run.error }}</small></span><span class="sync-badge" :class="['failed', 'interrupted'].includes(run.status) ? 'state-error' : isSyncRunning(run) ? 'state-neutral' : 'state-good'">{{ syncStatusLabels[run.status] }}</span></button>
          <p v-if="!runs.length" class="hint" role="status">{{ runsLoading ? '正在加载执行记录…' : '暂无匹配的执行记录。' }}</p>
          <div v-if="runPages > 1" class="pagination"><button type="button" :disabled="runsLoading || runPage <= 1" @click="changeRunPage(runPage - 1)">上一页</button><small>{{ runPage }} / {{ runPages }}</small><button type="button" :disabled="runsLoading || runPage >= runPages" @click="changeRunPage(runPage + 1)">下一页</button></div>
          <section v-if="selectedRun" class="sync-run-detail" aria-label="执行详情">
            <div class="sync-section-head"><h3>{{ syncTriggerLabel(selectedRun) }}详情 · {{ syncStatusLabels[selectedRun.status] }}</h3><button type="button" :disabled="detailsLoading" @click="loadRunDetails()">刷新详情</button></div>
            <div class="sync-run-times"><span>开始：{{ syncTime(selectedRun.started_at) }}</span><span>结束：{{ syncTime(selectedRun.finished_at) }}</span></div>
            <p v-if="selectedRun.error" class="error-text" role="alert">{{ selectedRun.error }}</p>
            <p v-if="isSyncRunning(selectedRun)" class="hint" role="status">{{ selectedRun.status === 'queued' ? '正在等待后台执行。' : '后台执行中，完成后更新结果。' }}</p>
            <template v-if="selectedRun.summary"><div class="sync-summary"><div><span>名单人数</span><b>{{ selectedRun.summary.source ?? 0 }}</b></div><div><span>计划新增</span><b>{{ selectedRun.summary.create ?? 0 }}</b></div><div><span>计划更新</span><b>{{ selectedRun.summary.update ?? 0 }}</b></div><div><span>计划删除</span><b>{{ selectedRun.summary.delete ?? 0 }}</b></div><div><span>不变</span><b>{{ selectedRun.summary.unchanged ?? 0 }}</b></div></div><p v-if="selectedRun.summary.completed_create !== undefined && selectedRun.kind === 'sync'" class="hint">已完成：新增 {{ selectedRun.summary.completed_create ?? 0 }} 条、更新 {{ selectedRun.summary.completed_update ?? 0 }} 条、删除 {{ selectedRun.summary.completed_delete ?? 0 }} 条。</p><p v-if="selectedRun.summary.duplicate" class="hint">其中 {{ selectedRun.summary.duplicate }} 条为重复记录。</p><p v-if="selectedRun.kind === 'preview' && !isSyncRunning(selectedRun) && selectedRun.summary.source === 0 && selectedRun.summary.delete" class="sync-empty-source">当前名单为 0 人；执行同步将删除目标表中 {{ selectedRun.summary.delete }} 条记录。</p><p v-if="selectedRun.kind === 'preview'" class="hint">预览只核对数据；实际执行会重新读取当时的名单和目标表。</p></template>
            <div class="sync-section-head"><h3>人员明细 <small>{{ rowTotal }}</small></h3><select v-model="rowFilter" aria-label="筛选同步明细" @change="filterRows"><option value="all">全部变化</option><option v-for="(label, action) in syncActionLabels" :key="action" :value="action">{{ label }}</option></select></div>
            <div class="sync-table-wrap"><table class="sync-result-table"><thead><tr><th>处理</th><th>姓名</th><th>部门</th><th>user_id</th><th>说明</th></tr></thead><tbody><tr v-for="(row, index) in rows" :key="`${row.record_id || row.user_id}-${row.action}-${index}`"><td>{{ syncActionLabels[row.action] }}</td><td>{{ row.name || '—' }}</td><td>{{ row.department || '—' }}</td><td>{{ row.user_id || '—' }}</td><td>{{ syncReasonLabel(row.reason) }}</td></tr><tr v-if="!rows.length"><td colspan="5" class="sync-table-empty">{{ detailsLoading ? '正在加载明细…' : '暂无匹配明细。' }}</td></tr></tbody></table></div>
            <div v-if="rowPages > 1" class="pagination"><button type="button" :disabled="detailsLoading || rowPage <= 1" @click="changeRowPage(rowPage - 1)">上一页</button><small>{{ rowPage }} / {{ rowPages }}</small><button type="button" :disabled="detailsLoading || rowPage >= rowPages" @click="changeRowPage(rowPage + 1)">下一页</button></div>
            <h3>执行日志 <small>{{ logTotal }}</small></h3><ol class="sync-events"><li v-for="event in logs" :key="event.id"><div><time :datetime="event.created_at">{{ syncTime(event.created_at) }}</time><span class="sync-log-level" :class="event.level === 'error' ? 'error-text' : ''">{{ event.level }}</span></div><p>{{ event.message }}</p><details v-if="event.details && Object.keys(Object(event.details)).length"><summary>查看详情</summary><pre>{{ logDetails(event.details) }}</pre></details></li></ol><p v-if="!logs.length" class="hint">暂无日志。</p>
            <div v-if="logPages > 1" class="pagination"><button type="button" :disabled="detailsLoading || logPage <= 1" @click="changeLogPage(logPage - 1)">上一页</button><small>{{ logPage }} / {{ logPages }}</small><button type="button" :disabled="detailsLoading || logPage >= logPages" @click="changeLogPage(logPage + 1)">下一页</button></div>
          </section>
    </section>
  </main>
</template>

<style scoped>
.sync-page,.sync-content,.sync-main{display:grid;gap:16px;min-width:0}
.sync-navigation{display:flex;align-items:center;justify-content:space-between;gap:16px;border-bottom:1px solid var(--line);padding-bottom:10px}
.sync-tabs{display:flex;gap:6px}.sync-tabs button{border:0;background:transparent;color:var(--muted);padding:10px 16px;font-family:var(--sans);font-size:var(--fs-md)}.sync-tabs button.active{background:var(--accent-soft);color:var(--accent-deep);font-weight:600}
.sync-page-actions,.sync-inline-actions,.sync-row-actions,.sync-toolbar,.sync-save-actions{display:flex;align-items:center;gap:8px}.sync-page-actions>button{display:inline-flex;align-items:center;justify-content:center;gap:6px;white-space:nowrap;font-family:var(--sans)}.sync-page-actions .primary-button{width:auto;padding:8px 12px;font-size:var(--fs-sm)}.sync-page-actions svg,.sync-back-button svg{width:15px;height:15px;flex:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
.sync-feedback{margin:0;padding:12px 16px;border:1px solid var(--line);border-radius:var(--r-md);background:var(--surface);font-size:var(--fs-sm);overflow-wrap:anywhere}.sync-success{color:var(--plus-ink)}
.sync-task-list{padding:0;overflow:hidden}.sync-task-table{overflow:auto}.sync-task-row{display:grid;grid-template-columns:minmax(140px,1.1fr) minmax(160px,1.3fr) minmax(125px,1fr) minmax(125px,1fr) 128px;align-items:center;gap:18px;padding:18px 22px;font-size:var(--fs-sm)}.sync-task-table-head{background:var(--surface-2);color:var(--muted)}.sync-task-table-head .sync-task-row{padding-top:11px;padding-bottom:11px;font-size:var(--fs-xs);font-weight:500}.sync-task-data+.sync-task-data{border-top:1px solid var(--line)}.sync-task-data:hover{background:#FAFBFC}.sync-task-row [role=cell]{min-width:0}.sync-task-info b{font-weight:600;overflow-wrap:anywhere}.sync-task-row small{display:block;margin-top:5px;color:var(--muted);font-size:var(--fs-xs);overflow-wrap:anywhere}.sync-task-target a{overflow-wrap:anywhere;line-height:1.8}.sync-task-target a:hover{color:var(--accent-deep);text-decoration:underline;text-underline-offset:3px}.sync-task-target svg{display:inline-block;width:12px;height:12px;margin-left:5px;vertical-align:-1px;stroke:currentColor;stroke-width:1.3;stroke-linecap:round;stroke-linejoin:round;color:var(--muted)}.sync-task-result small{font-family:var(--mono)}.sync-task-result .hint{margin:0}.sync-row-actions{justify-content:flex-end;gap:12px}.sync-row-actions>button{font-size:var(--fs-xs);padding:6px 10px;white-space:nowrap;font-family:var(--sans)}.sync-row-actions .sync-link-button{padding:6px 0}
.sync-badge{display:inline-flex;align-items:center;padding:2px 8px;font-size:var(--fs-xs);border-radius:var(--r-sm);white-space:nowrap;font-weight:400}.state-good{color:var(--plus-ink);background:var(--plus-soft)}.state-neutral{color:var(--muted);background:var(--surface-2)}.state-error{color:var(--minus-ink);background:var(--minus-soft)}
.sync-list-footer{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;padding:14px 22px;border-top:1px solid var(--line);color:var(--muted);font-size:var(--fs-xs)}.sync-list-footer .pagination{margin:0}.sync-empty{display:flex;align-items:center;justify-content:center;flex-direction:column;gap:10px;padding:48px 20px;color:var(--muted);font-size:var(--fs-sm)}.sync-empty svg{width:38px;height:38px;stroke:var(--control-line);stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}.sync-empty b{font-weight:500;color:var(--text)}.sync-empty p{margin:0;text-align:center}
.sync-link-button,.sync-back-button{border:0;background:transparent;color:var(--accent-deep);font-family:var(--sans)}.sync-link-button:hover:not(:disabled),.sync-back-button:hover:not(:disabled){background:var(--accent-soft)}.sync-editor-heading{display:flex;align-items:center;justify-content:space-between;gap:16px}.sync-editor-heading>div{display:flex;align-items:center;gap:18px;min-width:0}.sync-editor-heading h2{margin:0;border-left:1px solid var(--line);padding-left:18px;font-family:var(--sans);font-size:15px;overflow-wrap:anywhere}.sync-back-button{display:inline-flex;align-items:center;gap:6px;padding:5px 0;flex:none;white-space:nowrap;color:var(--muted)}.sync-editor-heading>.sync-link-button{white-space:nowrap;padding:6px 0}.sync-draft-notice{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 16px;background:var(--accent-soft);border:1px solid var(--line);border-radius:var(--r-md);font-size:var(--fs-sm)}.sync-draft-notice>span{min-width:0;overflow-wrap:anywhere}.sync-draft-notice>button{flex:none;white-space:nowrap;font-family:var(--sans)}.sync-draft-notice .sync-inline-actions{flex:none}
.sync-task-header{padding:18px 22px}.sync-task-header>.hint{margin:10px 0 0}.sync-task-header>.hint:first-child{margin:0}.sync-execution-bar{display:flex;align-items:center;justify-content:space-between;gap:20px}.sync-execution-bar b{font-size:var(--fs-sm);font-weight:500}.sync-execution-bar .hint{margin:4px 0 0}.sync-toolbar,.sync-save-actions{flex-wrap:wrap;gap:10px}.sync-toolbar .primary-button,.sync-save-actions .primary-button{width:auto}.sync-toolbar>button{padding:9px 14px;font-size:var(--fs-sm);font-family:var(--sans);white-space:nowrap}
.sync-section-head{display:flex;justify-content:space-between;align-items:center;gap:12px}.sync-section-head h2,.sync-section-head h3{margin:0;font-size:var(--fs-md);font-family:var(--sans)}.sync-section-head h2 small,.sync-section-head h3 small{margin-left:6px;color:var(--muted);font-weight:400}.sync-section-head>button{padding:5px 9px;white-space:nowrap}.sync-inline-actions>button{font-family:var(--sans);white-space:nowrap}
.sync-form fieldset{display:grid;gap:24px}.sync-form h3,.sync-run-detail>h3{font-size:var(--fs-md);font-family:var(--sans);margin:0 0 14px}.sync-form-section{border-top:1px solid var(--line);padding-top:22px;min-width:0}.sync-source-choice{display:flex;flex-wrap:wrap;gap:18px}.sync-source-choice label{display:flex;align-items:center;gap:7px;font-size:var(--fs-sm)}.sync-input-action{display:flex;gap:8px;align-items:stretch}.sync-input-action>input{flex:1;min-width:0}.sync-input-action>button{flex:none;white-space:nowrap}.sync-mappings{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:16px}.sync-mappings .field-label{font-family:var(--sans);letter-spacing:0}.sync-target-name{font-size:var(--fs-sm);margin-bottom:0;overflow-wrap:anywhere}.sync-next-runs{margin:12px 0 0;padding-left:20px;font-size:var(--fs-xs);color:var(--muted)}.sync-save-actions{border-top:1px solid var(--line);margin-top:24px;padding-top:20px}.sync-save-actions>button{font-family:var(--sans)}.sync-save-actions>.sync-danger{margin-left:auto}.sync-danger{color:var(--minus-ink)}
.sync-schedule{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:18px;padding:14px 16px;background:var(--surface-2);border-radius:var(--r-md)}.sync-schedule>div{min-width:0}.sync-schedule b{font-size:var(--fs-sm);font-weight:500}.sync-schedule .hint{margin:4px 0 0;overflow-wrap:anywhere}.sync-schedule>button{flex:none;font-family:var(--sans);white-space:nowrap}
.sync-run-filters{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}.sync-run-filters select{max-width:180px}.sync-run-item{display:flex;justify-content:space-between;align-items:center;gap:12px;width:100%;margin-top:10px;padding:12px 16px;text-align:left;background:var(--surface);font-family:var(--sans);border-color:var(--line)}.sync-run-item.selected{background:var(--accent-soft);border-color:var(--accent)}.sync-run-item>span:first-child{min-width:0}.sync-run-item b{font-size:var(--fs-sm);font-weight:500}.sync-run-item small{display:block;color:var(--muted);font-weight:400;margin-top:4px;overflow-wrap:anywhere}.sync-run-item small.error-text{color:var(--minus-ink)}
.sync-run-detail{margin-top:24px;border-top:1px solid var(--line);padding-top:22px}.sync-run-times{display:flex;flex-wrap:wrap;gap:6px 18px;color:var(--muted);font-size:var(--fs-xs);margin-top:12px}.sync-summary{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin:18px 0 12px}.sync-summary>div{padding:12px;background:var(--surface-2);border-radius:var(--r-md);min-width:0}.sync-summary span{display:block;font-size:var(--fs-xs);color:var(--muted)}.sync-summary b{display:block;margin-top:4px;font-family:var(--mono);font-size:20px;overflow-wrap:anywhere}.sync-empty-source{padding:10px 12px;color:var(--minus-ink);background:var(--minus-soft);font-size:var(--fs-sm);border-radius:var(--r-md)}.sync-run-detail .sync-section-head{margin-top:20px}.sync-run-detail .sync-section-head>select{max-width:120px;font-size:var(--fs-sm)}
.sync-table-wrap{overflow:auto;margin-top:12px;border:1px solid var(--line);border-radius:var(--r-md)}.sync-result-table{width:100%;border-collapse:collapse;text-align:left;font-size:var(--fs-sm)}.sync-result-table th{background:var(--surface-2);color:var(--muted);font-size:var(--fs-xs);font-weight:500}.sync-result-table th,.sync-result-table td{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere;min-width:70px}.sync-result-table td:nth-child(3){min-width:130px}.sync-result-table td:nth-child(4){font-family:var(--mono)}.sync-result-table tr:last-child td{border-bottom:0}.sync-table-empty{text-align:center;color:var(--muted);height:80px}.sync-run-detail>h3{margin-top:24px}.sync-events{padding:0;list-style:none;margin:0}.sync-events>li{border-left:2px solid var(--line);padding:0 0 16px 14px;font-size:var(--fs-sm)}.sync-events time{font-family:var(--mono);color:var(--muted);font-size:var(--fs-xs)}.sync-log-level{margin-left:10px;font-size:var(--fs-xs)}.sync-events p{margin:5px 0;white-space:pre-wrap;overflow-wrap:anywhere}.sync-events summary{font-size:var(--fs-xs);color:var(--accent-deep)}.sync-events pre{padding:10px;background:var(--surface-2);border-radius:var(--r-md);overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font-size:var(--fs-xs)}
@media(max-width:1100px) and (min-width:821px){.sync-task-row{grid-template-columns:minmax(130px,1fr) minmax(150px,1fr) 125px 125px 112px;gap:12px;padding:16px}.sync-row-actions{gap:8px}.sync-row-actions>button{padding:6px 8px}}
@media(max-width:1000px){.sync-task-table-head{display:none}.sync-task-row{grid-template-columns:repeat(2,minmax(0,1fr));gap:14px 20px;padding:18px 20px}.sync-task-info,.sync-task-target{grid-column:1 / -1}.sync-task-info b{font-size:var(--fs-md)}.sync-row-actions{grid-column:1 / -1;justify-content:flex-end;border-top:1px solid var(--line);padding-top:12px}.sync-task-result{text-align:right}.sync-editor-heading{align-items:flex-start}.sync-editor-heading>div{align-items:flex-start;flex-direction:column;gap:8px}.sync-editor-heading h2{border:0;padding:0}.sync-summary{grid-template-columns:repeat(3,minmax(0,1fr))}.sync-run-times{display:grid;gap:4px}.sync-list-footer{padding:14px 20px}}
@media(max-width:640px){.sync-draft-notice{flex-wrap:wrap}.sync-draft-notice .sync-inline-actions{flex-wrap:wrap}.sync-navigation{flex-wrap:wrap;gap:10px}.sync-tabs{flex:1}.sync-tabs button{padding:10px 12px}.sync-page-actions{margin-left:auto}.sync-execution-bar{align-items:flex-start;flex-direction:column;gap:14px}.sync-task-header{padding:18px 20px}.sync-input-action{flex-wrap:wrap}.sync-input-action>input{flex-basis:100%}.sync-input-action>button{width:100%}.sync-mappings{grid-template-columns:1fr}.sync-runs>.sync-section-head{align-items:flex-start;flex-wrap:wrap}.sync-summary{gap:6px}.sync-summary>div{padding:8px 6px}.sync-summary b{font-size:17px}.sync-run-filters select{flex:1;max-width:none}}
</style>
