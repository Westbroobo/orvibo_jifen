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
type ConfigSection = 'source' | 'target' | 'schedule'
const configSection = ref<ConfigSection>('source')
const configSections = [
  { id: 'source', label: '人员来源' }, { id: 'target', label: '目标多维表' }, { id: 'schedule', label: '定时计划' },
] as const
const draft = ref<TableSyncPayload>(emptyDraft()), baseline = ref('')
const editorVersion = ref(0)
const fields = ref<TableSyncField[]>([]), targetTables = ref<{ id: string; name: string }[]>([]), targetName = ref('')
const nextRuns = ref<string[]>([])
const error = ref(''), feedback = ref(''), pendingAction = ref(''), confirmDelete = ref(false)
const pendingTaskId = ref(''), rowError = ref<{ taskId: string; message: string } | null>(null)
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
let lastDueCheck = 0

function emptyDraft(): TableSyncPayload {
  return { name: '', source_kind: 'selection', preset_id: null, selection: unionSelection(), target_url: '', table_id: '', field_mapping: { department: '', name: '', user_id: '' }, cron: '0 4 * * *' }
}
const working = computed(() => !!pendingAction.value)
const dirty = computed(() => editing.value && JSON.stringify(draft.value) !== baseline.value)
const stale = computed(() => !!selectedTask.value && selectedTask.value.config_version !== editorVersion.value)
const writableFields = computed(() => fields.value.filter(field => field.type === 1 && field.writable))
const validTargetUrl = computed(() => { try { return ['http:', 'https:'].includes(new URL(draft.value.target_url.trim()).protocol) } catch { return false } })
const canSave = computed(() => !!draft.value.name.trim() && validTargetUrl.value && !!draft.value.table_id &&
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
const sourceSummary = computed(() => {
  if (draft.value.source_kind === 'preset') return sources.value.find(preset => preset.id === draft.value.preset_id)?.name || '请选择公共名单'
  if (draft.value.selection.match_mode !== 'union') return '沿用原部门交集名单'
  const departments = draft.value.selection.department_ids?.length ?? 0
  const people = new Set([...(draft.value.selection.person_ids ?? []), ...(draft.value.selection.extra_ids ?? [])]).size
  return departments || people ? `${departments} 个部门 · ${people} 位指定人员` : '选择部门或指定人员'
})
const configSummary = computed(() => ({
  source: sourceSummary.value,
  target: draft.value.table_id && mappingComplete(draft.value.field_mapping) ? targetName.value || '已配置目标表' : '粘贴链接并设置字段',
  schedule: draft.value.cron.trim() || '设置执行时间',
}))
const saveHint = computed(() => {
  if (!draft.value.name.trim()) return '请填写任务名称'
  if (draft.value.source_kind === 'preset' && !draft.value.preset_id) return '请选择公共名单'
  if (!validTargetUrl.value || !draft.value.table_id || !mappingComplete(draft.value.field_mapping)) return '请完成目标多维表配置'
  if (!draft.value.cron.trim()) return '请填写定时计划'
  return dirty.value ? '修改尚未保存' : selectedTask.value ? '配置已保存' : '保存后可预览并执行'
})

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
  nextRuns.value = []; confirmDelete.value = false; configSection.value = 'source'
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
  configSection.value = 'source'
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
function switchConfigSection(value: ConfigSection, focus = false) {
  if (working.value) return
  configSection.value = value
  if (focus) document.getElementById(`sync-config-tab-${value}`)?.focus()
}
function moveConfigSection(direction: number, focus = false) {
  const index = configSections.findIndex(section => section.id === configSection.value)
  switchConfigSection(configSections[(index + direction + configSections.length) % configSections.length]!.id, focus)
}
function executionBlock(task: TableSyncTask) {
  if (task.active_run_id) return '已有任务排队或执行中'
  if (selectedTask.value?.id === task.id) {
    if (stale.value) return '配置已更新，请重新打开配置'
    if (dirty.value) return '请先保存配置'
  }
  return ''
}
function updateTask(task: TableSyncTask) {
  tasks.value = tasks.value.map(item => item.id === task.id ? task : item)
  if (selectedTask.value?.id === task.id) selectedTask.value = task
}
function targetChanged() {
  draft.value.table_id = ''; draft.value.field_mapping = { department: '', name: '', user_id: '' }
  fields.value = []; targetTables.value = []; targetName.value = ''
}
function tableChanged() {
  draft.value.field_mapping = { department: '', name: '', user_id: '' }; fields.value = []
  targetName.value = targetTables.value.find(table => table.id === draft.value.table_id)?.name ?? ''
}
async function perform(name: string, fn: (signal: AbortSignal) => Promise<void>, taskId = '') {
  if (working.value || disposed) return
  if (['save', 'enabled', 'delete', 'preview', 'run'].includes(name)) {
    tasksRequest?.abort(); tasksRequest = undefined; ++taskSequence; tasksLoading.value = false
  }
  const request = new AbortController(); actionRequest = request; pendingAction.value = name; pendingTaskId.value = taskId
  error.value = ''; feedback.value = ''; rowError.value = null
  try { await fn(request.signal) }
  catch (e) {
    if (!request.signal.aborted && !disposed) {
      if (taskId) rowError.value = { taskId, message: message(e) }
      else error.value = message(e)
    }
  }
  finally { if (actionRequest === request) { actionRequest = undefined; pendingAction.value = ''; pendingTaskId.value = '' } }
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
    const section = configSection.value
    clearRun(); setTask(saved); configSection.value = section
    feedback.value = id ? '任务已保存。' : '任务已保存，定时执行默认关闭。'
    await loadTasks(false)
  })
}
async function toggleEnabled(task = selectedTask.value, fromList = false) {
  if (!task) return
  await perform('enabled', async signal => {
    const updated = await api<TableSyncTask>(`${prefix}/tasks/${task.id}/enabled`, 'PATCH', { enabled: !task.enabled }, signal)
    if (signal.aborted || disposed) return
    updateTask(updated)
    if (!fromList) feedback.value = updated.enabled ? '已开启定时执行。' : '已关闭定时执行，仍可手动执行。'
  }, fromList ? task.id : '')
}
async function execute(kind: 'preview' | 'run', task = selectedTask.value, fromList = false) {
  if (!task || working.value || executionBlock(task)) return
  await perform(kind, async signal => {
    const run = await api<TableSyncRun>(`${prefix}/tasks/${task.id}/${kind}`, 'POST', {}, signal)
    if (signal.aborted || disposed) return
    updateTask({ ...task, active_run_id: run.id })
    if (fromList) return
    runTask.value = { id: task.id, name: task.name }
    runPage.value = 1; statusFilter.value = 'all'; kindFilter.value = 'all'
    await openRun(run); await loadRuns(false)
    feedback.value = kind === 'preview' ? '预览已排队，不会写入多维表。' : '单次执行已排队，原定时计划不变。'
  }, fromList ? task.id : '')
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
  if (polling || disposed || document.hidden || working.value) return
  const now = Date.now()
  if (!hasRunning.value) {
    const due = tasks.value.some(task => task.enabled && task.next_run_at && new Date(task.next_run_at).getTime() <= now)
    if (!due || now - lastDueCheck < 30000) return
    lastDueCheck = now
  }
  polling = true
  try {
    const work: Promise<void>[] = [loadTasks(false)]
    if (tab.value === 'runs') work.push(loadRuns(false))
    if (tab.value === 'runs' && isSyncRunning(selectedRun.value)) work.push(loadRunDetails(false))
    await Promise.allSettled(work)
  } finally { polling = false }
}
function visibleAgain() { if (!document.hidden) void poll() }
async function changeTaskPage(value: number) { if (working.value) return; taskPage.value = value; await loadTasks() }
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
            <div class="sync-task-table-head" role="rowgroup"><div class="sync-task-row" role="row"><span role="columnheader" class="sync-index-heading">序号</span><span role="columnheader">任务 / 人员来源</span><span role="columnheader">目标多维表</span><span role="columnheader">定时执行</span><span role="columnheader">下次运行 <small>北京时间</small></span><span role="columnheader">最近执行</span><span role="columnheader" class="sync-actions-heading">操作</span></div></div>
            <div role="rowgroup">
              <div v-for="(task, index) in tasks" :key="task.id" class="sync-task-row sync-task-data" role="row">
                <div class="sync-task-index" role="cell" :aria-label="`序号 ${(taskPage - 1) * 20 + index + 1}`">{{ (taskPage - 1) * 20 + index + 1 }}</div>
                <div class="sync-task-info" role="cell"><b>{{ task.name }}</b><small>{{ sourceLabel(task) }}</small></div>
                <div class="sync-task-target" role="cell"><a :href="task.target_url" target="_blank" rel="noopener noreferrer" :aria-label="`打开目标多维表：${task.table_name || task.name}`">{{ task.table_name || '待检查目标表' }}<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M9 3h4v4M13 3 7 9M6 3H3v10h10v-3" /></svg></a></div>
                <div class="sync-task-schedule" role="cell">
                  <span class="sync-cell-label">定时执行</span>
                  <button type="button" class="sync-row-switch" role="switch" :aria-checked="task.enabled" :aria-label="`${task.name}的定时执行开关`" :aria-busy="pendingTaskId === task.id && pendingAction === 'enabled'" :disabled="working" :title="task.enabled ? '关闭后仍可手动执行' : '开启后按已保存的计划执行'" @click="toggleEnabled(task, true)"><span class="sync-switch-track" aria-hidden="true"><span /></span><span aria-live="polite">{{ task.enabled ? '已开启' : '已关闭' }}</span></button>
                  <small class="sync-cron" :title="`Cron：${task.cron}（北京时间）`">{{ task.cron }}</small>
                </div>
                <div class="sync-task-next" role="cell" aria-live="polite"><span class="sync-cell-label">下次运行 · 北京时间</span><time v-if="task.enabled && task.next_run_at" :datetime="task.next_run_at">{{ syncTime(task.next_run_at) }}</time><span v-else class="hint">{{ task.enabled ? '等待调度' : '未开启定时' }}</span></div>
                <div class="sync-task-result" role="cell" aria-live="polite"><span class="sync-cell-label">最近执行</span><span v-if="task.active_run_id" class="sync-badge state-neutral">{{ activeRunLabel(task) }}</span><span v-else-if="task.last_status" class="sync-badge" :class="['failed', 'interrupted'].includes(task.last_status) ? 'state-error' : ['success', 'unchanged'].includes(task.last_status) ? 'state-good' : 'state-neutral'">{{ syncStatusLabels[task.last_status] }}</span><span v-else class="hint">尚未执行</span><small v-if="task.last_run_at">{{ syncTime(task.last_run_at) }}</small></div>
                <div class="sync-task-actions" role="cell">
                  <div class="sync-row-actions">
                    <button type="button" class="sync-row-run" :aria-label="`执行一次：${task.name}`" :disabled="working || !!executionBlock(task)" :aria-busy="pendingTaskId === task.id && pendingAction === 'run'" :title="executionBlock(task) || '按已保存配置执行一次，不改变定时计划'" @click="execute('run', task, true)"><svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m6 3 7 5-7 5V3Z" /></svg>{{ pendingTaskId === task.id && pendingAction === 'run' ? '正在提交…' : task.active_run_id ? '执行中' : '执行一次' }}</button>
                    <button type="button" class="sync-task" :aria-label="`配置任务：${task.name}`" :disabled="working" @click="openTask(task)"><svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3 4h10M3 8h10M3 12h10" /><path d="M6 2v4M10 6v4M6 10v4" /></svg>配置</button>
                    <button type="button" class="sync-row-history" :aria-label="`查看记录：${task.name}`" :disabled="working" @click="showRuns(task)"><svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3 5a5.5 5.5 0 1 1-.5 5M3 2v3h3M8 5v3l2 1" /></svg>查看记录</button>
                  </div>
                  <small v-if="!task.active_run_id && executionBlock(task)" class="sync-action-hint">{{ executionBlock(task) }}</small>
                  <p v-if="rowError?.taskId === task.id" class="sync-row-error error-text" role="alert">{{ rowError.message }}</p>
                </div>
              </div>
            </div>
          </div>
          <div v-if="!tasks.length" class="sync-empty" role="status"><svg viewBox="0 0 40 40" fill="none" aria-hidden="true"><path d="M8 8h24v25H8zM8 15h24M16 15v18M13 4v8M27 4v8" /></svg><b>{{ tasksLoading ? '正在加载任务…' : '暂无同步任务' }}</b><p v-if="!tasksLoading">点击右上角“新建任务”，配置人员来源和目标表。</p></div>
          <footer class="sync-list-footer"><span>共 {{ taskTotal }} 个任务</span><div v-if="taskPages > 1" class="pagination"><button type="button" :disabled="working || tasksLoading || taskPage <= 1" @click="changeTaskPage(taskPage - 1)">上一页</button><small>{{ taskPage }} / {{ taskPages }}</small><button type="button" :disabled="working || tasksLoading || taskPage >= taskPages" @click="changeTaskPage(taskPage + 1)">下一页</button></div></footer>
        </section>
      </template>
      <section v-else class="sync-main" aria-label="同步任务配置">
        <div class="sync-editor-heading"><div><button type="button" class="sync-back-button" :disabled="working" @click="showTaskList"><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m8 5-5 5 5 5M3 10h14" /></svg>返回任务列表</button><h2>{{ selectedTask ? selectedTask.name : '新建同步任务' }}</h2></div><button v-if="selectedTask" type="button" class="sync-link-button" :disabled="working" @click="showRuns(selectedTask)">查看执行记录</button></div>
        <form class="panel sync-form" novalidate @submit.prevent="saveTask">
          <fieldset :disabled="working">
            <div class="sync-config-top">
              <div class="sync-config-name"><label class="field-label" for="sync-name">任务名称</label><input id="sync-name" v-model="draft.name" maxlength="100" required placeholder="例如：战报推送名单同步"></div>
              <div v-if="selectedTask" class="sync-toolbar"><button type="button" :disabled="!canExecute" @click="execute('preview')">{{ pendingAction === 'preview' ? '正在提交…' : '预览同步差异' }}</button><button type="button" :disabled="!canExecute" @click="execute('run')">{{ pendingAction === 'run' ? '正在提交…' : '手动执行一次' }}</button></div>
              <span v-else class="hint sync-new-hint">新任务保存后默认关闭定时</span>
            </div>
            <p v-if="dirty" class="sync-config-notice hint">配置有改动，请先保存。</p><p v-else-if="selectedTask?.active_run_id" class="sync-config-notice hint">已有任务排队或执行中，可在执行记录中查看进度。</p>
            <p v-if="stale" class="sync-config-notice error-text" role="alert">任务配置已被其他管理员更新，请重新选择此任务后继续。</p>
            <div class="sync-config-tabs" role="tablist" aria-label="任务配置分区" @keydown.left.prevent="moveConfigSection(-1, true)" @keydown.right.prevent="moveConfigSection(1, true)" @keydown.home.prevent="switchConfigSection('source', true)" @keydown.end.prevent="switchConfigSection('schedule', true)">
              <button v-for="(section, index) in configSections" :id="`sync-config-tab-${section.id}`" :key="section.id" type="button" role="tab" :aria-label="section.label" :aria-controls="`sync-config-panel-${section.id}`" :aria-selected="configSection === section.id" :tabindex="configSection === section.id ? 0 : -1" :class="{ active: configSection === section.id }" @click="switchConfigSection(section.id)"><span class="sync-step-number" aria-hidden="true">{{ index + 1 }}</span><span><b>{{ section.label }}</b><small>{{ configSummary[section.id] }}</small></span></button>
            </div>
            <section v-show="configSection === 'source'" id="sync-config-panel-source" class="sync-form-section" role="tabpanel" aria-labelledby="sync-config-tab-source">
              <div class="sync-config-section-head"><div><h3>选择同步人员</h3><p class="hint">按部门全员与指定人员合并去重，仅同步在职人员。</p></div></div>
              <div class="sync-source-choice"><label :class="{ active: draft.source_kind === 'selection' }"><input v-model="draft.source_kind" type="radio" value="selection">任务专属名单</label><label :class="{ active: draft.source_kind === 'preset' }"><input v-model="draft.source_kind" type="radio" value="preset">引用公共名单</label></div>
              <template v-if="draft.source_kind === 'selection'"><RecipientRangeEditor v-if="!sourcesLoading" v-model="draft.selection" :people="directory.people" :departments="directory.departments" columns /><p v-else class="hint">正在加载部门与人员…</p></template>
              <div v-else class="sync-preset-field"><label class="field-label" for="sync-preset">公共名单</label><RecipientPresetSelect id="sync-preset" :model-value="draft.preset_id ?? ''" :presets="sources" :directory="directory" placeholder="选择公共名单" :disabled="working || sourcesLoading" @update:model-value="draft.preset_id = $event" /><p class="hint">每次执行使用该公共名单的最新配置。</p></div>
            </section>
            <section v-show="configSection === 'target'" id="sync-config-panel-target" class="sync-form-section" role="tabpanel" aria-labelledby="sync-config-tab-target">
              <div class="sync-config-section-head"><div><h3>连接目标多维表</h3><p class="hint">先读取数据表，再将三个来源字段对应到目标文本字段。</p></div></div>
              <div class="sync-target-connection"><label class="field-label" for="sync-url">数据表链接</label><div class="sync-input-action"><input id="sync-url" v-model="draft.target_url" type="url" required placeholder="粘贴目标数据表链接" @input="targetChanged"><button type="button" :disabled="working || !draft.target_url.trim()" @click="inspectTarget">{{ pendingAction === 'inspect' ? '正在读取…' : '读取目标表' }}</button></div>
              <div v-if="targetTables.length > 1 || targetTables.length && !draft.table_id"><label class="field-label" for="sync-table">目标数据表</label><select id="sync-table" v-model="draft.table_id" @change="tableChanged"><option value="">请选择数据表</option><option v-for="table in targetTables" :key="table.id" :value="table.id">{{ table.name }}</option></select><p class="hint">选择后点击“读取目标表”获取该表字段。</p></div>
              <p v-if="targetName" class="sync-target-name">目标：<b>{{ targetName }}</b></p></div>
              <div class="sync-mapping-heading"><b>字段对应关系</b><span class="hint">来源字段 → 目标文本字段</span></div>
              <div class="sync-mappings"><div v-for="key in mappingKeys" :key="key"><label class="field-label" :for="`sync-field-${key}`">{{ fieldLabels[key] }} → 目标文本字段</label><select :id="`sync-field-${key}`" v-model="draft.field_mapping[key]"><option value="">请选择字段</option><option v-if="draft.field_mapping[key] && !writableFields.some(field => field.id === draft.field_mapping[key])" :value="draft.field_mapping[key]">已保存的“{{ fieldLabels[key] }}”字段</option><option v-for="field in writableFields" :key="field.id" :value="field.id">{{ field.name }}</option></select></div></div>
              <p v-if="fields.length && writableFields.length < 3" class="error-text">目标表至少需要三个可写的文本字段，用于部门、姓名和 user_id。</p><p v-else class="hint">按 user_id 匹配人员，新增缺少记录、更新变化字段并删除多余记录；已有记录的自动编号保留。</p>
            </section>
            <section v-show="configSection === 'schedule'" id="sync-config-panel-schedule" class="sync-form-section" role="tabpanel" aria-labelledby="sync-config-tab-schedule">
              <div class="sync-config-section-head"><div><h3>设置执行计划</h3><p class="hint">按北京时间运行。关闭定时后仍可手动执行一次。</p></div></div>
              <div class="sync-schedule-layout"><div class="sync-cron-editor"><label class="field-label" for="sync-cron">Cron 表达式 · 北京时间</label><div class="sync-input-action"><input id="sync-cron" v-model="draft.cron" required placeholder="0 4 * * *" @input="nextRuns = []"><button type="button" :disabled="working || !draft.cron.trim()" @click="checkCron">查看执行时间</button></div><p class="hint">分、时、日、月、星期。例如 0 4 * * * 表示每天 04:00。</p><ul v-if="nextRuns.length" class="sync-next-runs" aria-label="预计执行时间"><li v-for="time in nextRuns" :key="time">{{ syncTime(time) }}</li></ul></div>
                <div class="sync-schedule"><div><b>自动执行</b><p class="hint">{{ selectedTask?.enabled ? `下次执行：${syncTime(selectedTask.next_run_at)}` : selectedTask ? '已关闭，仍可手动执行一次。' : '新任务保存后可开启定时。' }}</p></div><button v-if="selectedTask" type="button" role="switch" :aria-checked="selectedTask.enabled" aria-label="定时执行开关" :disabled="working" @click="toggleEnabled()">{{ selectedTask.enabled ? '关闭定时' : '开启定时' }}</button></div>
              </div><p v-if="selectedTask && draft.cron !== selectedTask.cron" class="hint">执行时间有修改，保存后生效；开关按当前已保存的计划执行。</p>
            </section>
          </fieldset>
          <footer class="sync-config-footer">
            <div class="sync-save-status"><span class="hint" role="status">{{ saveHint }}</span><button v-if="selectedTask && !confirmDelete" type="button" class="sync-danger sync-delete-button" :disabled="working || !!selectedTask.active_run_id" @click="confirmDelete = true">删除任务</button><template v-if="confirmDelete"><span class="hint">删除任务？目标表数据和历史记录保留。</span><button type="button" :disabled="working" @click="confirmDelete = false">取消</button><button type="button" class="sync-danger" :disabled="working || !!selectedTask?.active_run_id" @click="removeTask">确认删除</button></template></div>
            <div class="sync-save-actions"><button v-if="configSection !== 'source'" type="button" :disabled="working" @click="moveConfigSection(-1)">上一步</button><button v-if="configSection !== 'schedule'" type="button" :disabled="working" @click="moveConfigSection(1)">下一步</button><button type="submit" class="primary-button" :disabled="working || !canSave || stale || !!selectedTask?.active_run_id">{{ pendingAction === 'save' ? '正在保存…' : '保存任务' }}</button></div>
          </footer>
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
.sync-task-list{padding:0;overflow:hidden;box-shadow:var(--shadow-soft)}.sync-task-table{overflow:auto}.sync-task-row{display:grid;grid-template-columns:36px minmax(115px,1fr) minmax(145px,1.25fr) 100px 132px 120px 264px;align-items:center;gap:12px;padding:20px;font-size:var(--fs-sm)}.sync-task-table-head{background:var(--surface-2);color:var(--muted)}.sync-task-table-head .sync-task-row{padding-top:12px;padding-bottom:12px;font-size:var(--fs-xs);font-weight:500}.sync-task-table-head small{display:inline;margin:0 0 0 4px;font-size:10px;font-weight:400;white-space:nowrap}.sync-actions-heading,.sync-index-heading,.sync-task-index{text-align:center}.sync-task-index{color:var(--muted);font-family:var(--mono);font-size:var(--fs-xs)}.sync-task-data+.sync-task-data{border-top:1px solid var(--line)}.sync-task-data:hover{background:#FAFBFC}.sync-task-row [role=cell]{min-width:0}.sync-task-info b{font-weight:600;overflow-wrap:anywhere}.sync-task-row small{display:block;margin-top:5px;color:var(--muted);font-size:var(--fs-xs);overflow-wrap:anywhere}.sync-task-target a{overflow-wrap:anywhere;line-height:1.8}.sync-task-target a:hover{color:var(--accent-deep);text-decoration:underline;text-underline-offset:3px}.sync-task-target svg{display:inline-block;width:12px;height:12px;margin-left:5px;vertical-align:-1px;stroke:currentColor;stroke-width:1.3;stroke-linecap:round;stroke-linejoin:round;color:var(--muted)}.sync-task-next time{font-size:var(--fs-sm);line-height:1.8;font-variant-numeric:tabular-nums}.sync-task-result small{font-size:10px;font-variant-numeric:tabular-nums}.sync-task-result .hint{margin:0}.sync-cell-label{display:none}
.sync-row-switch{display:inline-flex;align-items:center;gap:7px;padding:5px 0;border:0;background:transparent;color:var(--muted);font-family:var(--sans);font-size:var(--fs-xs);font-weight:500;white-space:nowrap}.sync-row-switch[aria-checked=true]{color:var(--plus-ink)}.sync-switch-track{position:relative;display:block;flex:none;width:30px;height:18px;border:1px solid var(--control-line);border-radius:10px;background:var(--surface-2);transition:background .15s,border-color .15s}.sync-switch-track>span{position:absolute;top:2px;left:2px;width:12px;height:12px;border-radius:50%;background:var(--control-line);transition:transform .15s,background .15s}.sync-row-switch[aria-checked=true] .sync-switch-track{border-color:var(--plus-ink);background:var(--plus-ink)}.sync-row-switch[aria-checked=true] .sync-switch-track>span{background:white;transform:translateX(12px)}.sync-task-schedule .sync-cron{margin-top:3px;font-family:var(--mono);font-size:var(--fs-xs);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sync-row-actions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}.sync-row-actions>button{display:inline-flex;align-items:center;justify-content:center;gap:5px;width:100%;min-width:0;min-height:32px;border:1px solid var(--line);background:var(--surface);color:var(--text);font-size:var(--fs-xs);padding:6px 5px;white-space:nowrap;font-family:var(--sans);font-weight:500}.sync-row-actions>button:hover:not(:disabled){border-color:var(--accent-deep);background:var(--accent-soft);color:var(--accent-deep)}.sync-row-actions svg{width:13px;height:13px;flex:none;stroke:currentColor;stroke-width:1.4;stroke-linecap:round;stroke-linejoin:round}.sync-row-actions [aria-busy=true] svg{display:none}.sync-task-actions .sync-action-hint{text-align:center}.sync-row-error{margin:8px 0 0;font-size:var(--fs-xs);text-align:center;overflow-wrap:anywhere}
.sync-badge{display:inline-flex;align-items:center;padding:2px 8px;font-size:var(--fs-xs);border-radius:var(--r-sm);white-space:nowrap;font-weight:400}.state-good{color:var(--plus-ink);background:var(--plus-soft)}.state-neutral{color:var(--muted);background:var(--surface-2)}.state-error{color:var(--minus-ink);background:var(--minus-soft)}
.sync-list-footer{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;padding:14px 22px;border-top:1px solid var(--line);color:var(--muted);font-size:var(--fs-xs)}.sync-list-footer .pagination{margin:0}.sync-empty{display:flex;align-items:center;justify-content:center;flex-direction:column;gap:10px;padding:48px 20px;color:var(--muted);font-size:var(--fs-sm)}.sync-empty svg{width:38px;height:38px;stroke:var(--control-line);stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}.sync-empty b{font-weight:500;color:var(--text)}.sync-empty p{margin:0;text-align:center}
.sync-link-button,.sync-back-button{border:0;background:transparent;color:var(--accent-deep);font-family:var(--sans)}.sync-link-button:hover:not(:disabled),.sync-back-button:hover:not(:disabled){background:var(--accent-soft)}.sync-editor-heading{display:flex;align-items:center;justify-content:space-between;gap:16px}.sync-editor-heading>div{display:flex;align-items:center;gap:18px;min-width:0}.sync-editor-heading h2{margin:0;border-left:1px solid var(--line);padding-left:18px;font-family:var(--sans);font-size:15px;overflow-wrap:anywhere}.sync-back-button{display:inline-flex;align-items:center;gap:6px;padding:5px 0;flex:none;white-space:nowrap;color:var(--muted)}.sync-editor-heading>.sync-link-button{white-space:nowrap;padding:6px 0}.sync-draft-notice{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 16px;background:var(--accent-soft);border:1px solid var(--line);border-radius:var(--r-md);font-size:var(--fs-sm)}.sync-draft-notice>span{min-width:0;overflow-wrap:anywhere}.sync-draft-notice>button{flex:none;white-space:nowrap;font-family:var(--sans)}.sync-draft-notice .sync-inline-actions{flex:none}
.sync-toolbar,.sync-save-actions{flex-wrap:wrap;gap:10px}.sync-save-actions .primary-button{width:auto}.sync-toolbar>button{padding:8px 12px;font-size:var(--fs-sm);font-family:var(--sans);white-space:nowrap;background:var(--surface);border-color:var(--line);font-weight:500}
.sync-section-head{display:flex;justify-content:space-between;align-items:center;gap:12px}.sync-section-head h2,.sync-section-head h3{margin:0;font-size:var(--fs-md);font-family:var(--sans)}.sync-section-head h2 small,.sync-section-head h3 small{margin-left:6px;color:var(--muted);font-weight:400}.sync-section-head>button{padding:5px 9px;white-space:nowrap}.sync-inline-actions>button{font-family:var(--sans);white-space:nowrap}
.sync-form{padding:0}.sync-form fieldset{display:grid;gap:0}.sync-config-top{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;padding:20px 24px}.sync-config-name{flex:1;max-width:480px;min-width:0}.sync-config-name .field-label{font-family:var(--sans);margin-bottom:6px}.sync-config-notice{margin:0;padding:0 24px 12px;font-size:var(--fs-xs)}.sync-new-hint{margin:0 0 8px}.sync-config-tabs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:0 24px;padding:0 0 20px;border-bottom:1px solid var(--line)}.sync-config-tabs>button{display:flex;align-items:center;gap:10px;padding:12px 14px;border:1px solid var(--line);background:var(--surface);text-align:left;font-family:var(--sans);font-weight:400;min-width:0}.sync-config-tabs>button.active{border-color:var(--accent);background:var(--accent-soft)}.sync-step-number{display:flex;justify-content:center;align-items:center;flex:none;width:26px;height:26px;border-radius:50%;background:var(--surface-2);color:var(--muted);font-family:var(--mono);font-size:var(--fs-xs)}.sync-config-tabs .active .sync-step-number{background:var(--accent-deep);color:white}.sync-config-tabs>button>span:last-child{min-width:0}.sync-config-tabs b{display:block;font-size:var(--fs-md);font-weight:500;color:var(--text)}.sync-config-tabs .active b{color:var(--accent-deep)}.sync-config-tabs small{display:block;color:var(--muted);margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:var(--fs-xs)}
.sync-form h3,.sync-run-detail>h3{font-size:var(--fs-md);font-family:var(--sans);margin:0 0 14px}.sync-form-section{padding:20px 24px 24px;min-width:0;min-height:320px}.sync-config-section-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px}.sync-config-section-head h3{margin:0;font-size:14px}.sync-config-section-head .hint{margin:4px 0 0}.sync-source-choice{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px}.sync-source-choice label{display:flex;align-items:center;gap:7px;font-size:var(--fs-sm);padding:8px 12px;border:1px solid var(--line);border-radius:var(--r-md);cursor:pointer}.sync-source-choice label.active{background:var(--accent-soft);border-color:var(--accent);color:var(--accent-deep)}.sync-preset-field{max-width:600px}.sync-input-action{display:flex;gap:8px;align-items:stretch}.sync-input-action>input{flex:1;min-width:0}.sync-input-action>button{flex:none;white-space:nowrap;font-family:var(--sans);font-weight:500}.sync-target-connection{padding:16px;border:1px solid var(--line);border-radius:var(--r-md);background:var(--bg)}.sync-target-connection .field-label{font-family:var(--sans)}.sync-target-connection>div+div{margin-top:14px}.sync-mapping-heading{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:20px;font-size:var(--fs-sm)}.sync-mapping-heading b{font-weight:500}.sync-mappings{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:10px}.sync-mappings>div{padding:14px;background:var(--surface-2);border-radius:var(--r-md);min-width:0}.sync-mappings .field-label{font-family:var(--sans);letter-spacing:0}.sync-target-name{font-size:var(--fs-sm);margin-bottom:0;overflow-wrap:anywhere}.sync-next-runs{margin:12px 0 0;padding-left:20px;font-size:var(--fs-xs);color:var(--muted)}
.sync-config-footer{position:sticky;bottom:0;z-index:2;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:16px 24px;border-top:1px solid var(--line);background:var(--surface);border-radius:0 0 var(--r-lg) var(--r-lg);box-shadow:0 -3px 10px rgba(31,35,41,.03)}.sync-save-status{display:flex;align-items:center;gap:10px;flex-wrap:wrap;min-width:0}.sync-save-status>button,.sync-save-actions>button{font-family:var(--sans);font-size:var(--fs-sm);white-space:nowrap}.sync-save-status>.hint{margin:0}.sync-delete-button{padding:4px 0;background:transparent;border:0;font-weight:400}.sync-save-actions{flex:none}.sync-save-actions>button{min-width:78px;padding:8px 14px}.sync-danger{color:var(--minus-ink)}
.sync-schedule-layout{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:20px;align-items:start}.sync-cron-editor{min-width:0}.sync-schedule{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:16px;background:var(--surface-2);border-radius:var(--r-md)}.sync-schedule>div{min-width:0}.sync-schedule b{font-size:var(--fs-sm);font-weight:500}.sync-schedule .hint{margin:4px 0 0;overflow-wrap:anywhere}.sync-schedule>button{flex:none;font-family:var(--sans);white-space:nowrap}
.sync-run-filters{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}.sync-run-filters select{max-width:180px}.sync-run-item{display:flex;justify-content:space-between;align-items:center;gap:12px;width:100%;margin-top:10px;padding:12px 16px;text-align:left;background:var(--surface);font-family:var(--sans);border-color:var(--line)}.sync-run-item.selected{background:var(--accent-soft);border-color:var(--accent)}.sync-run-item>span:first-child{min-width:0}.sync-run-item b{font-size:var(--fs-sm);font-weight:500}.sync-run-item small{display:block;color:var(--muted);font-weight:400;margin-top:4px;overflow-wrap:anywhere}.sync-run-item small.error-text{color:var(--minus-ink)}
.sync-run-detail{margin-top:24px;border-top:1px solid var(--line);padding-top:22px}.sync-run-times{display:flex;flex-wrap:wrap;gap:6px 18px;color:var(--muted);font-size:var(--fs-xs);margin-top:12px}.sync-summary{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin:18px 0 12px}.sync-summary>div{padding:12px;background:var(--surface-2);border-radius:var(--r-md);min-width:0}.sync-summary span{display:block;font-size:var(--fs-xs);color:var(--muted)}.sync-summary b{display:block;margin-top:4px;font-family:var(--mono);font-size:20px;overflow-wrap:anywhere}.sync-empty-source{padding:10px 12px;color:var(--minus-ink);background:var(--minus-soft);font-size:var(--fs-sm);border-radius:var(--r-md)}.sync-run-detail .sync-section-head{margin-top:20px}.sync-run-detail .sync-section-head>select{max-width:120px;font-size:var(--fs-sm)}
.sync-table-wrap{overflow:auto;margin-top:12px;border:1px solid var(--line);border-radius:var(--r-md)}.sync-result-table{width:100%;border-collapse:collapse;text-align:left;font-size:var(--fs-sm)}.sync-result-table th{background:var(--surface-2);color:var(--muted);font-size:var(--fs-xs);font-weight:500}.sync-result-table th,.sync-result-table td{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere;min-width:70px}.sync-result-table td:nth-child(3){min-width:130px}.sync-result-table td:nth-child(4){font-family:var(--mono)}.sync-result-table tr:last-child td{border-bottom:0}.sync-table-empty{text-align:center;color:var(--muted);height:80px}.sync-run-detail>h3{margin-top:24px}.sync-events{padding:0;list-style:none;margin:0}.sync-events>li{border-left:2px solid var(--line);padding:0 0 16px 14px;font-size:var(--fs-sm)}.sync-events time{font-family:var(--mono);color:var(--muted);font-size:var(--fs-xs)}.sync-log-level{margin-left:10px;font-size:var(--fs-xs)}.sync-events p{margin:5px 0;white-space:pre-wrap;overflow-wrap:anywhere}.sync-events summary{font-size:var(--fs-xs);color:var(--accent-deep)}.sync-events pre{padding:10px;background:var(--surface-2);border-radius:var(--r-md);overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font-size:var(--fs-xs)}
@media(max-width:1260px){.sync-task-table-head{display:none}.sync-task-row{position:relative;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px 20px;padding:20px}.sync-task-info,.sync-task-target,.sync-task-result,.sync-task-actions{grid-column:1 / -1}.sync-task-index{display:flex;align-items:center;justify-content:center;position:absolute;top:20px;left:20px;width:28px;height:28px;border-radius:var(--r-sm);background:var(--surface-2)}.sync-task-info{padding-left:40px}.sync-task-info b{font-size:var(--fs-md)}.sync-cell-label{display:block;font-size:var(--fs-xs);color:var(--muted);margin-bottom:6px}.sync-task-actions{border-top:1px solid var(--line);padding-top:14px}.sync-task-result{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.sync-task-result .sync-cell-label{margin:0}.sync-task-result small{margin:0 0 0 auto}.sync-editor-heading{align-items:flex-start}.sync-editor-heading>div{align-items:flex-start;flex-direction:column;gap:8px}.sync-editor-heading h2{border:0;padding:0}.sync-summary{grid-template-columns:repeat(3,minmax(0,1fr))}.sync-run-times{display:grid;gap:4px}.sync-list-footer{padding:14px 20px}}
@media(max-width:1000px){.sync-config-top{flex-wrap:wrap;gap:14px}.sync-config-name{max-width:none;flex-basis:100%}.sync-config-tabs>button{padding:10px;gap:8px}.sync-schedule-layout{grid-template-columns:1fr}}
@media(max-width:640px){.sync-draft-notice{flex-wrap:wrap}.sync-draft-notice .sync-inline-actions{flex-wrap:wrap}.sync-navigation{flex-wrap:wrap;gap:10px}.sync-tabs{flex:1}.sync-tabs button{padding:10px 12px}.sync-page-actions{margin-left:auto}.sync-input-action{flex-wrap:wrap}.sync-input-action>input{flex-basis:100%}.sync-input-action>button{width:100%}.sync-mappings{grid-template-columns:1fr}.sync-runs>.sync-section-head{align-items:flex-start;flex-wrap:wrap}.sync-summary{gap:6px}.sync-summary>div{padding:8px 6px}.sync-summary b{font-size:17px}.sync-run-filters select{flex:1;max-width:none}.sync-config-top{padding:18px 16px}.sync-config-notice{padding-left:16px;padding-right:16px}.sync-config-tabs{margin:0 16px;gap:6px;padding-bottom:16px}.sync-config-tabs>button{padding:10px 4px;justify-content:center}.sync-config-tabs .sync-step-number,.sync-config-tabs small{display:none}.sync-config-tabs b{font-size:var(--fs-sm)}.sync-form-section{padding:18px 16px;min-height:280px}.sync-config-footer{padding:12px 16px;flex-wrap:wrap;gap:10px}.sync-save-actions{margin-left:auto;gap:6px}.sync-save-actions>button{min-width:0;padding:8px 12px}.sync-save-status{flex-basis:100%;justify-content:space-between}.sync-schedule{flex-wrap:wrap}}
@media(max-width:480px){.sync-row-actions svg{display:none}}
</style>
