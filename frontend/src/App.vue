<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, ApiError, setCsrf } from './api'
import { unionSelection } from './types'
import type { BatchDetail, CardContext, Directory, HistoryItem, Person, Preset, Preview, User } from './types'
import PersonMultiSelect from './components/PersonMultiSelect.vue'
import CardPreview from './components/CardPreview.vue'
import EmployeeAvatar from './components/EmployeeAvatar.vue'
import PermissionsPanel from './components/PermissionsPanel.vue'
import SendingHistory from './components/SendingHistory.vue'
import ScoreLedger from './components/ScoreLedger.vue'
import BatchResultDialog from './components/BatchResultDialog.vue'
import RecipientLists from './components/RecipientLists.vue'
import RecipientRangeEditor from './components/RecipientRangeEditor.vue'
import RecipientPresetSelect from './components/RecipientPresetSelect.vue'

const logoUrl = '/logo.svg'
const user = ref<User | null>(null)
const ready = ref(false)
const redirectingToFeishu = ref(false)
const demoAvailable = ref(false)
const page = ref<'console' | 'lists' | 'history' | 'ledger' | 'admin'>('console')
const directory = ref<Directory>({ people: [], departments: [], last_sync_at: null, last_sync_error: null, sync_requested: false })
const totals = ref<Record<string, number>>({})
const month = ref('')
const targets = ref<string[]>([])
const recipients = ref(unionSelection())
const operation = ref<'plus' | 'minus'>('plus')
const points = ref(5)
const reason = ref('')
function stepPoints(step: number) {
  const current = Number.isInteger(points.value) ? points.value : 0
  points.value = Math.min(2_000_000_000, Math.max(1, current + step))
}
const overrides = ref<Record<string, string>>({})
const editingTotal = ref(false)
const preview = ref<Preview | null>(null)
const previewPersonId = ref('')
const confirmation = ref(false)
const idempotency = ref('')
const busy = ref(false)
const loadingPage = ref(false)
const error = ref('')
const notice = ref('')
const presets = ref<Preset[]>([])
const presetId = ref('')
const rangeDialog = ref(false)
const rangeDraft = ref(unionSelection())
const rangeReady = ref(false)
const rangeClose = ref<HTMLButtonElement | null>(null)
const recipientsResolving = ref(false)
const resolvedRecipients = ref<Person[]>([])
const recipientWarnings = ref<string[]>([])
const hasRecipientSelection = computed(() => !!presetId.value || !!recipients.value.department_ids?.length ||
  recipients.value.levels.some(ids => ids.length > 0) || recipients.value.person_ids.length > 0 || recipients.value.extra_ids.length > 0)
const recipientEditLabel = computed(() => presetId.value ? '调整名单' : hasRecipientSelection.value ? '编辑名单' : '临时选人')
const history = ref<HistoryItem[]>([])
const historyTotal = ref(0)
const historyPage = ref(1)
const loadingHistory = ref(false)
const detail = ref<BatchDetail | null>(null)
type Balances = { month: string; totals: Record<string, number>; versions?: Record<string, number> }
const recallConfirmation = ref<{ batchId: string; count: number; names: string } | null>(null)
const clock = ref(Date.now())
const confirmSend = ref<HTMLButtonElement | null>(null)
const recallSend = ref<HTMLButtonElement | null>(null)
const detailPanel = ref<InstanceType<typeof BatchResultDialog> | null>(null)
let timer: ReturnType<typeof setInterval> | undefined
let resolveTimer: ReturnType<typeof setTimeout> | undefined
let resolveSequence = 0
let detailSequence = 0
let historySequence = 0
let pageRequest: AbortController | undefined

function cancelPageLoad() {
  pageRequest?.abort()
  pageRequest = undefined
  loadingPage.value = false
  ++historySequence
  loadingHistory.value = false
}

const authorized = computed(() => user.value?.status === 'active' && user.value.role !== 'none')
const delta = computed(() => operation.value === 'plus' ? points.value : -points.value)
const targetIds = computed(() => [...new Set(targets.value)])
const selectedPeople = computed(() => directory.value.people.filter(p => targetIds.value.includes(p.id)))
const targetWarnings = computed(() => targetIds.value.flatMap(id => {
  const person = directory.value.people.find(p => p.id === id)
  return person?.status === 'active' ? [] : [`${person?.name ?? '已选人员'}当前不可用，请移除后重新选择。`]
}))
const validPreview = computed(() => preview.value && new Date(preview.value.expires_at).getTime() > clock.value)
const activeRow = computed(() => preview.value?.rows.find(row => row.person.id === draftPerson.value?.id) ?? preview.value?.rows[0])
const draftPerson = computed(() => selectedPeople.value.find(person => person.id === previewPersonId.value) ?? selectedPeople.value[0])
const totalErrors = computed(() => Object.fromEntries(selectedPeople.value.flatMap(person => {
  const value = overrides.value[person.id]
  if (value === undefined) return []
  const total = Number(value)
  return !value.trim() || !Number.isInteger(total) || Math.abs(total) > 2_000_000_000
    ? [[person.id, `请为${person.name}填写有效的整数总分。`]] : []
})))
const totalWarnings = computed<string[]>(() => Object.values(totalErrors.value))
const draftContext = computed<CardContext | null>(() => {
  const person = draftPerson.value
  if (!person) return null
  return { person_name: person.name, person_open_id: person.open_id, delta: delta.value,
    department: [...new Set(person.paths.map(path => path.names.join(' / ')).filter(Boolean))].sort().join('；') || '直属企业',
    total: overrides.value[person.id] !== undefined && !totalErrors.value[person.id]
      ? Number(overrides.value[person.id]) : (totals.value[person.id] ?? 60) + delta.value,
    reason: reason.value || '待填写', operator_name: user.value?.name ?? '', month: month.value,
    time: '', operation: operation.value === 'plus' ? '加分' : '扣分' }
})
const cardContext = computed(() => activeRow.value?.context ?? draftContext.value)
const cardPerson = computed(() => activeRow.value?.person ?? draftPerson.value)
watch(targetIds, ids => {
  for (const id of Object.keys(overrides.value)) if (!ids.includes(id)) delete overrides.value[id]
})
watch(selectedPeople, people => {
  if (!people.some(person => person.id === previewPersonId.value)) previewPersonId.value = people[0]?.id ?? ''
})
const timeLabel = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '尚未同步'
const roleLabels = { admin: '管理员', operator: '操作员', none: '未授权' }

async function action(fn: () => Promise<void>) {
  if (busy.value) return
  cancelPageLoad()
  busy.value = true; error.value = ''; notice.value = ''
  try { await fn() } catch (e) { error.value = e instanceof Error ? e.message : '操作失败' } finally { busy.value = false }
}
function onKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape' || busy.value) return
  if (rangeDialog.value) rangeDialog.value = false
  else if (recallConfirmation.value) recallConfirmation.value = null
  else if (detail.value) closeDetail()
  else if (confirmation.value) confirmation.value = false
}
let modalOpener: HTMLElement | null = null
function captureOpener() { const active = document.activeElement; if (active instanceof HTMLElement) modalOpener = active }
function restoreOpener() { if (modalOpener?.isConnected) modalOpener.focus() }
watch(confirmation, async (value) => {
  if (value) { captureOpener(); await nextTick(); confirmSend.value?.focus() }
  else restoreOpener()
})
let recallOpener: HTMLElement | null = null
watch(recallConfirmation, async (value) => {
  if (value) { const active = document.activeElement; recallOpener = active instanceof HTMLElement ? active : null; await nextTick(); recallSend.value?.focus() }
  else { await nextTick(); if (recallOpener?.isConnected) recallOpener.focus({ preventScroll: true }) }
})
watch([() => !!detail.value, busy], async ([open, working], [wasOpen]) => {
  if (open && !wasOpen) captureOpener()
  await nextTick()
  if (open && !working && (!wasOpen || document.activeElement === document.body)) detailPanel.value?.focusClose()
  else if (!open && wasOpen) restoreOpener()
})
watch(rangeDialog, async (value) => {
  if (value) { captureOpener(); await nextTick(); rangeClose.value?.focus() }
  else { await nextTick(); restoreOpener() }
})
async function refresh(signal?: AbortSignal) {
  const [data, balances, configs] = await Promise.all([api<Directory>('/directory', 'GET', undefined, signal), api<Balances>('/balances', 'GET', undefined, signal), api<Preset[]>('/presets', 'GET', undefined, signal)])
  if (signal?.aborted) return
  directory.value = data; applyBalances(balances); presets.value = configs
  if (presetId.value) {
    if (!configs.some(p => p.id === presetId.value)) { presetId.value = ''; notice.value = '原发送名单已删除，请重新选择。' }
    loadPreset()
  }
}
function applyBalances(balances: Balances) {
  if (preview.value && (preview.value.month !== balances.month || preview.value.rows.some(row =>
    balances.versions ? row.balance_version !== (balances.versions[row.person.id] ?? 0)
      : row.before_total !== (balances.totals[row.person.id] ?? 60)))) {
    preview.value = null; confirmation.value = false; idempotency.value = ''
    notice.value = '积分已变化，请更新预览后再发送。'
  }
  totals.value = balances.totals; month.value = balances.month
}
async function initialize() {
  try {
    const config = await api<{ demo_mode: boolean }>('/public-config'); demoAvailable.value = config.demo_mode
    user.value = await api<User>('/auth/me'); setCsrf(user.value.csrf_token)
    if (authorized.value) await refresh()
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      user.value = null; setCsrf('')
      if (!demoAvailable.value && !new URLSearchParams(location.search).has('login_error')) {
        redirectingToFeishu.value = true
        location.replace('/api/auth/login')
        return
      }
    } else error.value = e instanceof Error ? e.message : '加载失败'
  }
  ready.value = true
}
onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  if (new URLSearchParams(location.search).has('login_error')) error.value = '飞书授权未完成，请重新登录'
  await initialize()
  timer = setInterval(() => {
    clock.value = Date.now()
    if (!busy.value && !recallConfirmation.value) {
      if (detail.value && (detail.value.statuses.pending || detail.value.statuses.sending || detail.value.recall_statuses?.pending || detail.value.recall_statuses?.recalling)) void loadDetail(detail.value.id, detail.value.page, true).catch(() => {})
      if (page.value === 'history' && !loadingHistory.value && history.value.some(item => item.recall_statuses?.pending || item.recall_statuses?.recalling)) void loadHistory().catch(() => {})
    }
  }, 3000)
})
const submitHint = computed(() => {
  if (busy.value) return '正在处理…'
  if (loadingPage.value) return '正在加载…'
  if (!selectedPeople.value.length) return '请先选择记分对象'
  if (targetWarnings.value.length) return '请移除不可用的加减分对象'
  if (totalWarnings.value.length) return '请检查手动总分'
  if (!reason.value.trim()) return '请填写原因'
  if (recipientWarnings.value.length) return '通知范围存在冲突,请先处理'
  if (recipientsResolving.value) return '正在解析通知范围…'
  if (!resolvedRecipients.value.length) return '请选择通知范围'
  return ''
})
const noticeBar = ref<HTMLElement | null>(null)
const noticePaused = ref(false)
let noticeTimer: ReturnType<typeof setTimeout> | undefined
watch(notice, async (value) => {
  clearTimeout(noticeTimer)
  if (!value) return
  await nextTick()
  noticeBar.value?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  if (!noticePaused.value) noticeTimer = setTimeout(() => { notice.value = '' }, 5000)
})
function pauseNotice() { noticePaused.value = true; clearTimeout(noticeTimer) }
function resumeNotice() { noticePaused.value = false; if (notice.value) noticeTimer = setTimeout(() => { notice.value = '' }, 5000) }
onUnmounted(() => { cancelPageLoad(); window.removeEventListener('keydown', onKeydown); clearInterval(timer); clearTimeout(resolveTimer); clearTimeout(previewTimer); clearTimeout(noticeTimer) })
let previewTimer: ReturnType<typeof setTimeout> | undefined
const previewReady = computed(() => page.value === 'console' && !busy.value && !loadingPage.value && !editingTotal.value && !recipientsResolving.value && selectedPeople.value.length > 0 && !targetWarnings.value.length && !totalWarnings.value.length && reason.value.trim().length > 0 && resolvedRecipients.value.length > 0 && !recipientWarnings.value.length)
watch([targets, targetWarnings, recipients, operation, points, reason, overrides, resolvedRecipients, recipientWarnings, recipientsResolving], () => {
  clearTimeout(previewTimer)
  preview.value = null; confirmation.value = false; idempotency.value = ''
  if (!previewReady.value) return
  previewTimer = setTimeout(() => { void makePreview() }, 600)
}, { deep: true })
watch(editingTotal, value => {
  clearTimeout(previewTimer)
  if (!value && !preview.value && previewReady.value) previewTimer = setTimeout(() => { void makePreview() }, 600)
})
watch([recipients, directory], () => {
  clearTimeout(resolveTimer); const sequence = ++resolveSequence
  recipientsResolving.value = true
  resolveTimer = setTimeout(async () => {
    if (!authorized.value) return
    try { const result = await api<{ people: Person[]; warnings: string[] }>('/ranges/resolve', 'POST', recipients.value); if (sequence === resolveSequence) { resolvedRecipients.value = result.people; recipientWarnings.value = result.warnings } }
    catch (e) { if (sequence === resolveSequence) { resolvedRecipients.value = []; recipientWarnings.value = [e instanceof Error ? e.message : '范围解析失败'] } }
    finally { if (sequence === resolveSequence) recipientsResolving.value = false }
  }, 150)
}, { deep: true })

function updateTotal(value: string) {
  if (cardPerson.value && !busy.value && !loadingPage.value) overrides.value[cardPerson.value.id] = value
}
function resetTotal() {
  if (cardPerson.value && !busy.value && !loadingPage.value) delete overrides.value[cardPerson.value.id]
}
async function makePreview() {
  if (busy.value || loadingPage.value || editingTotal.value || page.value !== 'console') return
  if (totalWarnings.value.length) { error.value = totalWarnings.value[0] ?? '请检查手动总分'; return }
  if (recipientsResolving.value || !selectedPeople.value.length || targetWarnings.value.length || !reason.value.trim() || !resolvedRecipients.value.length || recipientWarnings.value.length) return
  await action(async () => {
    if (!Number.isInteger(points.value) || points.value <= 0) throw new Error('请输入正整数分值')
    const values: Record<string, number> = {}
    targetIds.value.forEach(id => { if (overrides.value[id] !== undefined) values[id] = Number(overrides.value[id]) })
    preview.value = await api<Preview>('/adjustments/preview', 'POST', { person_ids: targetIds.value, operation: operation.value, points: points.value, reason: reason.value, overrides: values, recipients: recipients.value })
    idempotency.value = crypto.randomUUID()
  })
}
async function commit() {
  if (!preview.value || !validPreview.value) return
  await action(async () => {
    const result = await api<{ id: string }>('/adjustments', 'POST', { preview_token: preview.value!.preview_token, idempotency_key: idempotency.value })
    confirmation.value = false; preview.value = null; targets.value = []; overrides.value = {}; reason.value = ''
    await loadDetail(result.id); await refresh(); notice.value = '积分已记账，通知正在发送。'
  })
}
function loadPreset() {
  const preset = presets.value.find(p => p.id === presetId.value)
  recipients.value = preset ? JSON.parse(JSON.stringify(preset.selection)) : unionSelection()
}
function savedPreset(saved: Preset) {
  presets.value = [saved, ...presets.value.filter(p => p.id !== saved.id)]
  if (presetId.value === saved.id) loadPreset()
}
function deletedPreset(id: string) {
  presets.value = presets.value.filter(p => p.id !== id)
  if (presetId.value === id) { presetId.value = ''; loadPreset() }
}
function editRange() {
  rangeDraft.value = JSON.parse(JSON.stringify(recipients.value)); rangeReady.value = false; rangeDialog.value = true
}
function applyRange() {
  if (!rangeReady.value || busy.value) return
  presetId.value = ''; recipients.value = JSON.parse(JSON.stringify(rangeDraft.value)); rangeDialog.value = false
}
function clearRecipientRange() { presetId.value = ''; recipients.value = unionSelection() }
async function loadHistory(signal?: AbortSignal) {
  const sequence = ++historySequence
  loadingHistory.value = true
  try {
    const result = await api<{ items: HistoryItem[]; total: number }>('/adjustments?page=' + historyPage.value, 'GET', undefined, signal)
    const balances = await api<Balances>('/balances', 'GET', undefined, signal)
    if (signal?.aborted || sequence !== historySequence) return
    history.value = result.items; historyTotal.value = result.total; applyBalances(balances)
  } finally { if (sequence === historySequence) loadingHistory.value = false }
}
async function loadDetail(id: string, selectedPage = 1, polling = false) {
  const sequence = ++detailSequence
  const result = await api<BatchDetail>(`/adjustments/${id}?page=${selectedPage}`)
  const balances = await api<Balances>('/balances')
  if (sequence !== detailSequence || polling && detail.value?.id !== id) return
  detail.value = result; applyBalances(balances)
}
function closeDetail() { ++detailSequence; detail.value = null }
async function switchPage(value: typeof page.value) {
  if (busy.value) return
  cancelPageLoad()
  clearTimeout(previewTimer)
  page.value = value; error.value = ''; notice.value = ''
  const request = new AbortController()
  pageRequest = request; loadingPage.value = true
  try {
    if (value === 'history') await loadHistory(request.signal)
    else if (value !== 'ledger') await refresh(request.signal)
  } catch (e) {
    if (!request.signal.aborted) { error.value = e instanceof Error ? e.message : '加载失败'; request.abort() }
  } finally {
    if (pageRequest === request) { pageRequest = undefined; loadingPage.value = false }
  }
}
async function updateRole(person: Person, event: Event) { const role = (event.target as HTMLSelectElement).value; await action(async () => { await api(`/admin/people/${person.id}/role`, 'PUT', { role }); user.value = await api<User>('/auth/me'); if (authorized.value) await refresh(); notice.value = '权限已更新。' }); if (error.value) (event.target as HTMLSelectElement).value = person.role }
async function logout() { await action(async () => { await api('/auth/logout', 'POST'); user.value = null; closeDetail(); preview.value = null; setCsrf('') }) }
async function retry(id: string) { await action(async () => { await api(`/deliveries/${id}/retry`, 'POST'); await loadDetail(detail.value!.id, detail.value!.page); if (page.value === 'history') await loadHistory() }) }
function changeHistoryPage(value: number) { historyPage.value = value; void switchPage('history') }
function askBatchRecall(item: HistoryItem | BatchDetail) {
  const names = 'names' in item ? item.names : item.snapshot.rows.map(row => row.person.name)
  recallConfirmation.value = { batchId: item.id, count: item.recall_available, names: names.join('、') }
}
async function confirmRecall() {
  const request = recallConfirmation.value
  if (!request) return
  await action(async () => {
    const result = await api<{ accepted: number }>(`/adjustments/${request.batchId}/recall`, 'POST')
    recallConfirmation.value = null
    if (detail.value?.id === request.batchId) await loadDetail(request.batchId, detail.value.page)
    if (page.value === 'history') await loadHistory()
    notice.value = result.accepted ? `已申请撤回 ${result.accepted} 条卡片。` : '撤回任务已提交或完成。'
  })
}
</script>

<template>
  <div class="page" :class="{ 'permissions-layout': authorized && page === 'admin', 'history-layout': authorized && (page === 'history' || page === 'ledger') }" :inert="rangeDialog || !!detail || confirmation || !!recallConfirmation">
    <header class="topbar">
      <a class="brand" href="/"><img class="brand-logo" :src="logoUrl" alt="" width="30" height="30"><span>ORVIBO_员工积分系统</span></a>
      <div v-if="user" class="topbar-right">
        <span v-if="authorized" class="workspace-month" aria-label="当前记分月份">{{ month }}</span>
        <div class="account-panel" aria-label="当前账号">
          <div class="account-identity">
            <EmployeeAvatar :src="user.avatar_url" :name="user.name" size="small" />
            <div class="account-details"><strong class="account-name" :title="user.name">{{ user.name }}</strong><span class="account-role">{{ roleLabels[user.role] }}</span></div>
          </div>
          <div class="account-actions"><button type="button" class="logout-button" :disabled="busy" aria-label="退出登录" title="退出登录" @click="logout"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M9 5H5v14h4M14 8l4 4-4 4M9 12h10" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" /></svg><span>退出</span></button></div>
        </div>
      </div>
    </header>
    <div v-if="error" class="feedback error" role="alert">{{ error }}<button type="button" aria-label="关闭提示" @click="error = ''">×</button></div>
    <div v-if="notice" ref="noticeBar" class="feedback success" role="status" @mouseenter="pauseNotice" @mouseleave="resumeNotice">{{ notice }}<button type="button" aria-label="关闭提示" @click="notice = ''">×</button></div>
    <div v-if="user?.demo_mode" class="demo-banner">本地演示 · 使用虚拟人员，通知仅模拟发送</div>
    <section v-if="!ready" class="panel login-panel"><h1>{{ redirectingToFeishu ? '正在前往飞书授权…' : '正在加载员工积分系统' }}</h1></section>
    <section v-else-if="!user" class="panel login-panel"><h1>{{ error ? '暂时无法进入系统' : '已退出登录' }}</h1><p v-if="!error">需要继续使用时，请授权飞书账号。</p><a class="primary-button" href="/api/auth/login">{{ error ? '重新授权飞书账号' : '使用飞书账号授权' }}</a><button v-if="demoAvailable" type="button" :disabled="busy" @click="action(async () => { await api('/auth/demo', 'POST'); await initialize() })">进入本地演示</button></section>
    <section v-else-if="!authorized" class="panel login-panel"><h1>当前账号暂无操作权限</h1><p>请联系管理员分配积分操作权限。{{ user.status === 'unknown' ? '人员目录尚待同步核实。' : '' }}</p><button type="button" :disabled="busy" @click="action(initialize)">重新检查权限</button></section>
    <template v-else>
      <div class="workspace">
      <nav class="navigation" aria-label="功能导航">
        <button type="button" :class="{ active: page === 'console' }" :aria-current="page === 'console' ? 'page' : undefined" :disabled="busy" @click="switchPage('console')"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z" /></svg><span>操作台</span></button>
        <button type="button" :class="{ active: page === 'lists' }" :aria-current="page === 'lists' ? 'page' : undefined" :disabled="busy" @click="switchPage('lists')"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M14 5h6M14 9h6M14 13h6M14 17h6M4 19v-2a4 4 0 0 1 8 0v2" /><circle cx="8" cy="8" r="3" /></svg><span>发送名单</span></button>
        <button type="button" :class="{ active: page === 'history' }" :aria-current="page === 'history' ? 'page' : undefined" :disabled="busy" @click="switchPage('history')"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 4h11l3 3v13H5zM9 10h6M9 14h6M9 17h4" /></svg><span>发送记录</span></button>
        <button type="button" :class="{ active: page === 'ledger' }" :aria-current="page === 'ledger' ? 'page' : undefined" :disabled="busy" @click="switchPage('ledger')"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 3h14v18H5zM9 7h6M9 12h6M9 17h6M12 9v6" /></svg><span>积分明细</span></button>
        <button v-if="user.role === 'admin'" type="button" :class="{ active: page === 'admin' }" :aria-current="page === 'admin' ? 'page' : undefined" :disabled="busy" @click="switchPage('admin')"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m12 3 8 3v6c0 4-4 7-8 9-4-2-8-5-8-9V6zM9 12l2 2 4-4" /></svg><span>权限管理</span></button>
      </nav>
      <div class="workspace-content">
      <p v-if="loadingPage" class="page-loading" role="status">正在加载…</p>
      <main v-if="page === 'console'" class="layout">
        <section class="panel" aria-label="积分操作">
          <form class="op-form" @submit.prevent="makePreview"><fieldset class="op-form-body" :disabled="busy || loadingPage">
            <div class="form-section">
              <PersonMultiSelect v-model="targets" :people="directory.people" />
              <p v-for="warning in targetWarnings" :key="warning" class="error-text">{{ warning }}</p>
              <div><div class="field-label">操作类型</div><div class="f-seg"><button type="button" class="opt plus" :class="{ active: operation === 'plus' }" @click="operation = 'plus'">＋ 加分</button><button type="button" class="opt minus" :class="{ active: operation === 'minus' }" @click="operation = 'minus'">－ 扣分</button></div></div>
              <div class="points-control" role="group" aria-label="调整分值">
                <button class="points-jump decrease" type="button" aria-label="分值减少 5" :disabled="points <= 1" @click="stepPoints(-5)">−5</button>
                <div class="points-field">
                  <input id="points" v-model.number="points" aria-label="加减分值" type="number" min="1" max="2000000000" step="1">
                  <div class="points-arrows">
                    <button type="button" aria-label="分值增加 1" :disabled="points >= 2000000000" @click="stepPoints(1)"><svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m4 10 4-4 4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" /></svg></button>
                    <button type="button" aria-label="分值减少 1" :disabled="points <= 1" @click="stepPoints(-1)"><svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m4 6 4 4 4-4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" /></svg></button>
                  </div>
                </div>
                <button class="points-jump increase" type="button" aria-label="分值增加 5" :disabled="points >= 2000000000" @click="stepPoints(5)">+5</button>
              </div>
              <div><label class="field-label" for="reason">原因 <small>必填</small></label><textarea id="reason" v-model="reason" maxlength="2000" rows="3" placeholder="填写原因"></textarea></div>
            </div>
            <div class="form-section recipient-section">
              <div class="recipient-heading"><label class="field-label" for="recipient-preset">发送名单</label><button type="button" class="text-link" @click="switchPage('lists')">维护名单</button></div>
              <div class="recipient-controls">
                <RecipientPresetSelect id="recipient-preset" v-model="presetId" :presets="presets" :directory="directory" :placeholder="!presetId && hasRecipientSelection ? '临时名单' : '选择已有名单'" :disabled="busy || loadingPage" @change="loadPreset" />
                <button type="button" class="recipient-edit" aria-haspopup="dialog" @click="editRange"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="9" cy="7" r="3" /><path d="M3 20v-2a6 6 0 0 1 12 0v2M19 7v6M16 10h6" /></svg><span>{{ recipientEditLabel }}</span></button>
              </div>
              <div v-if="recipientsResolving" class="recipient-loading" role="status"><span class="recipient-spinner" aria-hidden="true"></span>正在匹配通知名单…</div>
              <div v-else-if="hasRecipientSelection || recipientWarnings.length" class="recipient-status">
                <details v-if="resolvedRecipients.length" class="recipient-fold">
                  <summary aria-label="查看通知名单"><span class="recipient-avatars" aria-hidden="true"><EmployeeAvatar v-for="person in resolvedRecipients.slice(0, 3)" :key="person.id" :src="person.avatar_url" :name="person.name" size="tiny" /></span><span class="recipient-count"><b>{{ resolvedRecipients.length }}</b> 位通知对象</span><svg class="recipient-chevron" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m7 4 6 6-6 6" /></svg></summary>
                  <div class="chips recipient-chips"><span v-for="person in resolvedRecipients" :key="person.id" class="chip"><EmployeeAvatar :src="person.avatar_url" :name="person.name" size="tiny" />{{ person.name }}</span></div>
                </details>
                <span v-else class="recipient-empty">暂无可通知人员</span>
                <button type="button" class="recipient-clear" aria-label="清空通知名单" @click="clearRecipientRange">清空</button>
              </div>
              <p v-else class="recipient-empty">尚未选择通知对象</p>
              <p v-for="warning in recipientWarnings" :key="warning" class="error-text">{{ warning }}</p>
            </div>
            <div class="send-summary"><b>{{ selectedPeople.length }}</b> 位记分对象 · <b>{{ resolvedRecipients.length }}</b> 位通知对象 · <b>{{ selectedPeople.length * resolvedRecipients.length }}</b> 条卡片</div>
            <button class="primary-button form-submit" :class="{ busy }" type="submit" :disabled="!previewReady">{{ busy ? '正在处理…' : '更新预览' }}</button>
            <p v-if="submitHint" class="hint submit-hint" aria-live="polite">{{ submitHint }}</p>
          </fieldset></form>
        </section>
        <aside class="panel preview-panel"><div class="panel-head"><h2 class="panel-title">卡片预览</h2></div>
          <select v-if="selectedPeople.length > 1" v-model="previewPersonId" aria-label="切换卡片预览人员"><option v-for="person in selectedPeople" :key="person.id" :value="person.id">{{ person.name }}</option></select>
          <CardPreview v-if="cardContext && cardPerson" :context="cardContext" :variables="activeRow?.card.data.template_variable" :avatar-url="cardPerson.avatar_url" editable-total :total-input="overrides[cardPerson.id]" :total-disabled="busy || loadingPage" :total-invalid="!!totalErrors[cardPerson.id]" @update-total="updateTotal" @reset-total="resetTotal" @editing-total="editingTotal = $event" /><div v-else class="empty-preview"><img class="empty-preview-logo" :src="logoUrl" alt="" width="36" height="36"><p>请选择记分对象</p></div>
          <div v-if="cardContext" class="total-guidance"><p><b>自动计算：</b>本月上一笔总分 + 本次加减分；本月首次记分从 60 分开始。</p><p><b>手动覆盖：</b>直接修改卡片里的“当前总分”，作为本次最终结果和后续记分起点，不再额外加减。点击“恢复自动”取消覆盖。</p></div>
          <p v-for="warning in totalWarnings" :key="warning" class="error-text" role="alert">{{ warning }}</p>
          <template v-if="preview"><div class="preview-details"><p><b>{{ preview.recipients.length }}</b> 位通知对象 · <b>{{ preview.message_count }}</b> 条卡片</p><details><summary>通知名单</summary><div class="chips"><span v-for="person in preview.recipients" :key="person.id" class="chip"><EmployeeAvatar :src="person.avatar_url" :name="person.name" size="tiny" />{{ person.name }}</span></div></details><small>有效至 {{ timeLabel(preview.expires_at) }}</small></div><p v-if="!validPreview" class="error-text">预览已过期，请更新预览。</p><button type="button" class="primary-button preview-send" :disabled="busy || loadingPage || !validPreview" @click="confirmation = true">核对并发送</button></template>
        </aside>
        <div class="mobile-actions">
          <button v-if="!preview" type="button" :disabled="!previewReady" @click="makePreview">{{ busy ? '正在处理…' : '更新预览' }}</button>
          <button v-else class="primary-button" type="button" :disabled="busy || loadingPage || !validPreview" @click="confirmation = true">核对并发送</button>
        </div>
      </main>
      <RecipientLists v-else-if="page === 'lists'" :presets="presets" :directory="directory" :user="user" :loading="loadingPage" @working="busy = $event" @saved="savedPreset" @deleted="deletedPreset" />
      <SendingHistory v-else-if="page === 'history'" :items="history" :total="historyTotal" :page="historyPage" :loading="loadingHistory" :busy="busy" @refresh="switchPage('history')" @change-page="changeHistoryPage" @detail="action(() => loadDetail($event))" @recall="askBatchRecall" />
      <ScoreLedger v-else-if="page === 'ledger'" :current-month="month" />
      <PermissionsPanel v-else-if="user.role === 'admin'" :directory="directory" :busy="busy || loadingPage" @synced="switchPage('admin')" @change-role="updateRole" />
      </div>
      </div>
    </template>
  </div>
  <Transition name="modal">
  <div v-if="confirmation && preview" class="modal-backdrop" @click.self="!busy && (confirmation = false)"><section class="panel modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title"><h2 id="confirm-title" class="panel-title">确认发送</h2><p>{{ preview.rows.length }} 人 · 每人{{ preview.delta > 0 ? '加' : '扣' }} {{ Math.abs(preview.delta) }} 分</p><p class="reason-box">{{ preview.reason }}</p><div v-for="row in preview.rows" :key="row.person.id" class="confirm-total"><EmployeeAvatar :src="row.person.avatar_url" :name="row.person.name" size="small" /><span>{{ row.person.name }}</span><b>{{ row.before_total }} → {{ row.final_total }} 分</b><small v-if="row.override_total !== null">手动覆盖</small></div><p>{{ preview.recipients.length }} 位通知对象 · {{ preview.message_count }} 条卡片</p><p class="hint">确认后记分生效，失败通知可重试。</p><div class="modal-actions"><button type="button" :disabled="busy" @click="confirmation = false">返回</button><button ref="confirmSend" type="button" class="primary-button" :class="{ busy }" :disabled="busy || loadingPage || !validPreview" @click="commit">{{ busy ? '正在提交…' : '确认发送' }}</button></div></section></div></Transition>
  <Transition name="modal">
  <BatchResultDialog v-if="detail" ref="detailPanel" :detail="detail" :busy="busy" :error="error" :clock="clock" :confirming-recall="!!recallConfirmation" @close="closeDetail" @refresh="action(() => loadDetail(detail!.id, detail!.page))" @recall="askBatchRecall" @retry="retry" @change-page="action(() => loadDetail(detail!.id, $event))" />
</Transition>
  <Transition name="modal">
  <div v-if="recallConfirmation" class="modal-backdrop recall-confirmation" @click.self="!busy && (recallConfirmation = null)">
    <section class="panel modal" role="dialog" aria-modal="true" aria-labelledby="recall-title">
      <h2 id="recall-title" class="panel-title">确认整批撤回</h2>
      <p class="reason-box">{{ recallConfirmation.names }}</p>
      <p>本次申请撤回 <b>{{ recallConfirmation.count }}</b> 条卡片</p>
      <p class="hint">处理本次操作中 24 小时内可撤回的卡片，自动跳过已撤回的通知。每位记分对象的全部通知撤回成功后，该记分作废。</p>
      <p v-if="error" class="error-text">{{ error }}</p>
      <div class="modal-actions"><button type="button" :disabled="busy" @click="recallConfirmation = null">取消</button><button ref="recallSend" type="button" class="primary-button" :class="{ busy }" :disabled="busy" @click="confirmRecall">{{ busy ? '正在提交…' : '确认整批撤回' }}</button></div>
    </section>
  </div>
</Transition>
  <Transition name="modal">
    <div v-if="rangeDialog" class="modal-backdrop" @click.self="!busy && (rangeDialog = false)">
      <section class="panel modal range-modal" role="dialog" aria-modal="true" aria-labelledby="range-dialog-title">
        <div class="panel-head flex-head"><h2 id="range-dialog-title" class="panel-title">{{ hasRecipientSelection ? '调整通知名单' : '选择通知对象' }}</h2><button ref="rangeClose" type="button" :disabled="busy" @click="rangeDialog = false">取消</button></div>
        <RecipientRangeEditor v-model="rangeDraft" :people="directory.people" :departments="directory.departments" @ready="rangeReady = $event" />
        <div class="modal-actions"><button type="button" class="primary-button" :disabled="busy || !rangeReady" @click="applyRange">使用此名单</button></div>
      </section>
    </div>
  </Transition>
</template>
