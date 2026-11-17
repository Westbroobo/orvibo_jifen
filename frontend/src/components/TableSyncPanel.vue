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
const tab = ref<'config' | 'runs'>('config')
const draft = ref<TableSyncPayload>(emptyDraft()), baseline = ref('')
const editorVersion = ref(0)
const fields = ref<TableSyncField[]>([]), targetTables = ref<{ id: string; name: string }[]>([]), targetName = ref('')
const nextRuns = ref<string[]>([])
const error = ref(''), feedback = ref(''), pendingAction = ref(''), confirmDelete = ref(false)
const runs = ref<TableSyncRun[]>([]), runTotal = ref(0), runPage = ref(1)
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
function setTask(task: TableSyncTask) {
  selectedTask.value = task
  const value: TableSyncPayload = {
    name: task.name, source_kind: task.source_kind, preset_id: task.preset_id,
    selection: task.source_kind === 'selection' ? task.selection : unionSelection(),
    target_url: task.target_url, table_id: task.table_id, field_mapping: task.field_mapping, cron: task.cron,
  }
  draft.value = JSON.parse(JSON.stringify(value)); baseline.value = JSON.stringify(draft.value)
  editorVersion.value = task.config_version
  editing.value = true; fields.value = []; targetTables.value = []; targetName.value = task.table_name
  nextRuns.value = []; confirmDelete.value = false
}
function clearRun() {
  detailsRequest?.abort(); ++detailsSequence
  selectedRun.value = null; rows.value = []; rowTotal.value = 0; rowPage.value = 1; rowFilter.value = 'all'
  logs.value = []; logTotal.value = 0; logPage.value = 1; detailsLoading.value = false
}
function newTask() {
  if (working.value) return
  selectedTask.value = null; editing.value = true; draft.value = emptyDraft(); baseline.value = ''
  tab.value = 'config'; fields.value = []; targetTables.value = []; targetName.value = ''; nextRuns.value = []
  confirmDelete.value = false; error.value = ''; feedback.value = ''; clearRun()
  runsRequest?.abort(); ++runsSequence; runs.value = []; runTotal.value = 0
}
async function openTask(task: TableSyncTask) {
  if (working.value) return
  setTask(task); clearRun(); tab.value = 'config'; error.value = ''; feedback.value = ''
  runPage.value = 1; statusFilter.value = 'all'; kindFilter.value = 'all'
  await loadRuns()
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
  const taskId = selectedTask.value?.id
  runsRequest?.abort(); const request = new AbortController(), sequence = ++runsSequence
  runsRequest = request; if (showLoading) runsLoading.value = true
  const query = new URLSearchParams({ page: String(runPage.value), status: statusFilter.value })
  if (taskId) query.set('task_id', taskId)
  if (kindFilter.value !== 'all') query.set('kind', kindFilter.value)
  try {
    const data = await api<TableSyncPage<TableSyncRun>>(`${prefix}/runs?${query}`, 'GET', undefined, request.signal)
    if (request.signal.aborted || sequence !== runsSequence || selectedTask.value?.id !== taskId || disposed) return
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
async function showAllRuns() {
  if (working.value) return
  selectedTask.value = null; editing.value = false; tab.value = 'runs'; clearRun()
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
    selectedTask.value = null; editing.value = false; confirmDelete.value = false; clearRun()
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
watch(draft, () => { if (dirty.value && selectedRun.value?.kind === 'preview') clearRun() }, { deep: true })
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
    <header class="sync-heading"><div><h1 class="panel-title">名单同步</h1><p>将人员名单同步到指定多维表，支持定时和单次执行。</p></div><div class="sync-heading-actions"><button type="button" :disabled="working" @click="showAllRuns">全部执行记录</button><button type="button" class="primary-button" :disabled="working" @click="newTask">新建任务</button></div></header>
    <p v-if="error" class="sync-feedback error-text" role="alert">{{ error }}</p>
    <p v-if="feedback" class="sync-feedback sync-success" role="status">{{ feedback }}</p>
    <div class="sync-layout">
      <aside class="panel sync-sidebar" aria-label="同步任务列表">
        <div class="sync-section-head"><h2>同步任务 <small>{{ taskTotal }}</small></h2><button type="button" :disabled="tasksLoading || working" @click="loadTasks()">刷新</button></div>
        <p v-if="tasksLoading && !tasks.length" class="hint" role="status">正在加载任务…</p>
        <button v-for="task in tasks" :key="task.id" type="button" class="sync-task" :class="{ selected: selectedTask?.id === task.id }" :disabled="working" @click="openTask(task)">
          <span class="sync-task-title"><b>{{ task.name }}</b><span class="sync-badge" :class="task.enabled ? 'state-good' : 'state-neutral'">{{ task.enabled ? '定时开启' : '定时关闭' }}</span></span>
          <small>{{ task.table_name || '待检查目标表' }}</small>
          <small v-if="task.active_run_id">任务执行中</small><small v-else-if="task.last_status">最近：{{ syncStatusLabels[task.last_status] }}</small>
          <small v-if="task.enabled">下次 {{ syncTime(task.next_run_at) }}</small>
        </button>
        <p v-if="!tasksLoading && !tasks.length" class="hint">暂无同步任务，点击“新建任务”开始配置。</p>
        <div v-if="taskPages > 1" class="pagination"><button type="button" :disabled="tasksLoading || taskPage <= 1" @click="changeTaskPage(taskPage - 1)">上一页</button><small>{{ taskPage }} / {{ taskPages }}</small><button type="button" :disabled="tasksLoading || taskPage >= taskPages" @click="changeTaskPage(taskPage + 1)">下一页</button></div>
      </aside>
      <section v-if="editing || tab === 'runs'" class="sync-main" aria-label="同步任务配置与执行记录">
        <div class="panel sync-task-header">
          <div class="sync-section-head"><h2>{{ selectedTask ? selectedTask.name : tab === 'runs' ? '全部执行记录' : '新建同步任务' }}</h2><button v-if="selectedTask" type="button" role="switch" :aria-checked="selectedTask.enabled" aria-label="定时执行开关" :disabled="working" @click="toggleEnabled">{{ selectedTask.enabled ? '关闭定时' : '开启定时' }}</button></div>
          <p v-if="selectedTask" class="hint">{{ selectedTask.enabled ? `下次定时执行：${syncTime(selectedTask.next_run_at)}` : '定时执行已关闭，仍可手动执行一次。' }}</p><p v-else-if="tab === 'config'" class="hint">新任务保存后默认关闭定时，可先预览并手动核对。</p>
          <div v-if="selectedTask" class="sync-toolbar"><button type="button" :disabled="!canExecute" @click="execute('preview')">{{ pendingAction === 'preview' ? '正在提交…' : '预览同步差异' }}</button><button type="button" class="primary-button" :disabled="!canExecute" @click="execute('run')">{{ pendingAction === 'run' ? '正在提交…' : '手动执行一次' }}</button><span v-if="dirty" class="hint">配置有改动，请先保存。</span><span v-else-if="selectedTask.active_run_id" class="hint">已有任务排队或执行中。</span></div>
          <p v-if="stale" class="error-text" role="alert">任务配置已被其他管理员更新，请重新选择此任务后继续。</p>
          <div v-if="editing" class="sync-tabs" role="group" aria-label="任务内容"><button type="button" :class="{ active: tab === 'config' }" @click="tab = 'config'">任务设置</button><button v-if="selectedTask" type="button" :class="{ active: tab === 'runs' }" @click="tab = 'runs'; loadRuns()">执行记录</button></div>
        </div>
        <form v-if="tab === 'config'" class="panel sync-form" @submit.prevent="saveTask">
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
            <section class="sync-form-section"><h3>定时计划</h3><label class="field-label" for="sync-cron">Cron 表达式 · 北京时间</label><div class="sync-input-action"><input id="sync-cron" v-model="draft.cron" required placeholder="0 4 * * *" @input="nextRuns = []"><button type="button" :disabled="working || !draft.cron.trim()" @click="checkCron">查看执行时间</button></div><p class="hint">五段依次为：分、时、日、月、星期。例如 0 4 * * * 表示每天 04:00。保存后生效，无需重启。</p><ul v-if="nextRuns.length" class="sync-next-runs" aria-label="预计执行时间"><li v-for="time in nextRuns" :key="time">{{ syncTime(time) }}</li></ul></section>
          </fieldset>
          <div class="sync-save-actions"><button type="submit" class="primary-button" :disabled="working || !canSave || stale || !!selectedTask?.active_run_id">{{ pendingAction === 'save' ? '正在保存…' : '保存任务' }}</button><button v-if="selectedTask && !confirmDelete" type="button" class="sync-danger" :disabled="working || !!selectedTask.active_run_id" @click="confirmDelete = true">删除任务</button><template v-if="confirmDelete"><span class="hint">删除任务？目标表数据和历史记录保留。</span><button type="button" :disabled="working" @click="confirmDelete = false">取消</button><button type="button" class="sync-danger" :disabled="working || !!selectedTask?.active_run_id" @click="removeTask">确认删除</button></template></div>
        </form>
        <section v-else class="panel sync-runs" aria-label="任务执行记录">
          <div class="sync-section-head"><h2>执行记录</h2><button type="button" :disabled="runsLoading" @click="loadRuns()">刷新</button></div>
          <div class="sync-run-filters"><select v-model="statusFilter" aria-label="筛选执行状态" @change="filterRuns"><option value="all">全部状态</option><option value="failed">执行失败</option><option value="interrupted">执行中断</option><option value="queued">排队中</option><option value="running">执行中</option><option value="success">已完成</option><option value="unchanged">无变化</option></select><select v-model="kindFilter" aria-label="筛选执行类型" @change="filterRuns"><option value="all">全部类型</option><option value="sync">同步执行</option><option value="preview">预览检查</option></select></div>
          <button v-for="run in runs" :key="run.id" type="button" class="sync-run-item" :class="{ selected: selectedRun?.id === run.id }" @click="openRun(run)"><span><b>{{ !selectedTask ? `${run.task_name} · ` : '' }}{{ syncTriggerLabel(run) }}</b><small>{{ syncTime(run.created_at) }} · {{ run.actor_name || '系统' }}</small><small v-if="run.error" class="error-text">{{ run.error }}</small></span><span class="sync-badge" :class="['failed', 'interrupted'].includes(run.status) ? 'state-error' : isSyncRunning(run) ? 'state-neutral' : 'state-good'">{{ syncStatusLabels[run.status] }}</span></button>
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
      </section>
      <section v-else class="panel sync-welcome"><h2>选择或新建同步任务</h2><p>配置名单、目标数据表和定时计划，再预览同步结果。</p></section>
    </div>
  </main>
</template>

<style scoped>
.sync-page{display:grid;gap:16px}.sync-heading,.sync-section-head{display:flex;justify-content:space-between;align-items:center;gap:12px}.sync-heading p{margin:4px 0 0;color:var(--muted);font-size:var(--fs-sm)}.sync-heading>button{flex:none}.sync-feedback{margin:0;padding:12px 16px;border:1px solid var(--line);border-radius:var(--r-md);background:var(--surface);font-size:var(--fs-sm);overflow-wrap:anywhere}.sync-success{color:var(--plus-ink)}.sync-layout{display:grid;grid-template-columns:260px minmax(0,1fr);gap:20px;align-items:start}.sync-sidebar{padding:18px}.sync-section-head h2,.sync-section-head h3{margin:0;font-size:var(--fs-md);font-family:var(--sans)}.sync-section-head h2 small,.sync-section-head h3 small{margin-left:6px;color:var(--muted);font-weight:400}.sync-section-head>button{padding:5px 9px;white-space:nowrap}.sync-task{display:block;width:100%;text-align:left;padding:12px;margin-top:10px;background:var(--surface);font-family:var(--sans)}.sync-task.selected,.sync-run-item.selected{background:var(--accent-soft);border-color:var(--accent)}.sync-task-title{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}.sync-task-title>b{overflow-wrap:anywhere;font-size:var(--fs-sm)}.sync-task small{display:block;margin-top:6px;color:var(--muted);font-weight:400;overflow-wrap:anywhere}.sync-badge{display:inline-flex;flex:none;padding:2px 6px;font-size:10px;border-radius:var(--r-sm);white-space:nowrap;font-weight:400}.state-good{color:var(--plus-ink);background:var(--plus-soft)}.state-neutral{color:var(--muted);background:var(--surface-2)}.state-error{color:var(--minus-ink);background:var(--minus-soft)}.sync-main{display:grid;gap:16px;min-width:0}.sync-task-header{padding-bottom:0}.sync-toolbar,.sync-save-actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center}.sync-toolbar .primary-button,.sync-save-actions .primary-button{width:auto}.sync-tabs{display:flex;gap:20px;margin-top:18px;border-top:1px solid var(--line)}.sync-tabs button{padding:12px 0;background:none;border:0;border-bottom:2px solid transparent;border-radius:0;color:var(--muted);font-family:var(--sans)}.sync-tabs button.active{border-bottom-color:var(--accent);color:var(--accent-deep)}.sync-form fieldset{display:grid;gap:24px}.sync-form h3,.sync-run-detail>h3{font-size:var(--fs-md);font-family:var(--sans);margin:0 0 14px}.sync-form-section{border-top:1px solid var(--line);padding-top:22px;min-width:0}.sync-source-choice{display:flex;flex-wrap:wrap;gap:18px}.sync-source-choice label{display:flex;align-items:center;gap:7px;font-size:var(--fs-sm)}.sync-input-action{display:flex;gap:8px;align-items:stretch}.sync-input-action>input{flex:1;min-width:0}.sync-input-action>button{flex:none;white-space:nowrap}.sync-mappings{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:16px}.sync-mappings .field-label{font-family:var(--sans);letter-spacing:0}.sync-target-name{font-size:var(--fs-sm);margin-bottom:0;overflow-wrap:anywhere}.sync-next-runs{margin:12px 0 0;padding-left:20px;font-size:var(--fs-xs);color:var(--muted)}.sync-save-actions{border-top:1px solid var(--line);margin-top:24px;padding-top:20px}.sync-danger{color:var(--minus-ink)}.sync-run-filters{display:flex;gap:10px;margin:16px 0}.sync-run-filters select{max-width:180px}.sync-run-item{display:flex;justify-content:space-between;align-items:center;gap:12px;width:100%;margin-top:10px;padding:12px;text-align:left;background:var(--surface);font-family:var(--sans)}.sync-run-item>span:first-child{min-width:0}.sync-run-item b{font-size:var(--fs-sm)}.sync-run-item small{display:block;color:var(--muted);font-weight:400;margin-top:4px;overflow-wrap:anywhere}.sync-run-item small.error-text{color:var(--minus-ink)}.sync-run-detail{margin-top:24px;border-top:1px solid var(--line);padding-top:22px}.sync-run-times{display:flex;flex-wrap:wrap;gap:6px 18px;color:var(--muted);font-size:var(--fs-xs);margin-top:12px}.sync-summary{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin:18px 0 12px}.sync-summary>div{padding:12px;background:var(--surface-2);border-radius:var(--r-md);min-width:0}.sync-summary span{display:block;font-size:var(--fs-xs);color:var(--muted)}.sync-summary b{display:block;margin-top:4px;font-family:var(--mono);font-size:20px;overflow-wrap:anywhere}.sync-empty-source{padding:10px 12px;color:var(--minus-ink);background:var(--minus-soft);font-size:var(--fs-sm);border-radius:var(--r-md)}.sync-run-detail .sync-section-head{margin-top:20px}.sync-run-detail .sync-section-head>select{max-width:120px;font-size:var(--fs-sm)}.sync-table-wrap{overflow:auto;margin-top:12px;border:1px solid var(--line);border-radius:var(--r-md)}.sync-result-table{width:100%;border-collapse:collapse;text-align:left;font-size:var(--fs-sm)}.sync-result-table th{background:var(--surface-2);color:var(--muted);font-size:var(--fs-xs);font-weight:500}.sync-result-table th,.sync-result-table td{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere;min-width:70px}.sync-result-table td:nth-child(3){min-width:130px}.sync-result-table td:nth-child(4){font-family:var(--mono)}.sync-result-table tr:last-child td{border-bottom:0}.sync-table-empty{text-align:center;color:var(--muted);height:80px}.sync-run-detail>h3{margin-top:24px}.sync-events{padding:0;list-style:none;margin:0}.sync-events>li{border-left:2px solid var(--line);padding:0 0 16px 14px;font-size:var(--fs-sm)}.sync-events time{font-family:var(--mono);color:var(--muted);font-size:var(--fs-xs)}.sync-log-level{margin-left:10px;font-size:var(--fs-xs)}.sync-events p{margin:5px 0;white-space:pre-wrap;overflow-wrap:anywhere}.sync-events summary{font-size:var(--fs-xs);color:var(--accent-deep)}.sync-events pre{padding:10px;background:var(--surface-2);border-radius:var(--r-md);overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font-size:var(--fs-xs)}.sync-welcome{text-align:center;padding:80px 24px}.sync-welcome h2{font-size:var(--fs-title)}.sync-welcome p{color:var(--muted);font-size:var(--fs-sm)}
.sync-heading-actions{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px}.sync-heading-actions>button{white-space:nowrap}
@media(max-width:1000px){.sync-layout{grid-template-columns:220px minmax(0,1fr);gap:14px}.sync-mappings{grid-template-columns:1fr}.sync-summary>div{padding:9px}}
@media(max-width:820px){.sync-layout{grid-template-columns:1fr}.sync-sidebar{max-height:360px;overflow:auto}.sync-heading{align-items:flex-start}.sync-summary{gap:6px}.sync-summary>div{padding:8px 6px}.sync-summary b{font-size:17px}.sync-input-action{flex-wrap:wrap}.sync-input-action>input{flex-basis:100%}.sync-input-action>button{width:100%}.sync-run-times{display:grid;gap:4px}.sync-welcome{padding:30px 20px}}
</style>
