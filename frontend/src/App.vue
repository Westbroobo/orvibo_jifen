<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, ApiError, setCsrf } from './api'
import { emptySelection, unionSelection, recallLabels, statusLabels } from './types'
import type { BatchDetail, CardContext, Directory, HistoryItem, Person, Preset, Preview, User } from './types'
import PersonMultiSelect from './components/PersonMultiSelect.vue'
import CardPreview from './components/CardPreview.vue'
import EmployeeAvatar from './components/EmployeeAvatar.vue'
import DirectorySync from './components/DirectorySync.vue'
import RecipientLists from './components/RecipientLists.vue'
import RecipientRangeEditor from './components/RecipientRangeEditor.vue'

const logoUrl = '/logo.svg'
const user = ref<User | null>(null)
const ready = ref(false)
const redirectingToFeishu = ref(false)
const demoAvailable = ref(false)
const page = ref<'console' | 'lists' | 'history' | 'admin'>('console')
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
const manual = ref<Record<string, boolean>>({})
const mirrorRecipients = ref(false)
const overrides = ref<Record<string, number>>({})
const preview = ref<Preview | null>(null)
const previewIndex = ref(0)
const confirmation = ref(false)
const idempotency = ref('')
const busy = ref(false)
const error = ref('')
const notice = ref('')
const presets = ref<Preset[]>([])
const presetId = ref('')
const rangeDialog = ref(false)
const rangeDraft = ref(unionSelection())
const rangeReady = ref(false)
const rangeClose = ref<HTMLButtonElement | null>(null)
const recipientsResolving = ref(false)
const publicPresets = computed(() => presets.value.filter(p => p.scope === 'public'))
const personalPresets = computed(() => presets.value.filter(p => p.scope === 'personal'))
const resolvedRecipients = ref<Person[]>([])
const recipientWarnings = ref<string[]>([])
const history = ref<HistoryItem[]>([])
const historyTotal = ref(0)
const historyPage = ref(1)
const loadingHistory = ref(false)
const detail = ref<BatchDetail | null>(null)
type Balances = { month: string; totals: Record<string, number>; versions?: Record<string, number> }
const recallConfirmation = ref<{ batchId: string; deliveryId?: string; count: number; names: string } | null>(null)
const adminQuery = ref('')
const clock = ref(Date.now())
const confirmSend = ref<HTMLButtonElement | null>(null)
const recallSend = ref<HTMLButtonElement | null>(null)
const detailClose = ref<HTMLButtonElement | null>(null)
let timer: ReturnType<typeof setInterval> | undefined
let resolveTimer: ReturnType<typeof setTimeout> | undefined
let resolveSequence = 0
let detailSequence = 0

const authorized = computed(() => user.value?.status === 'active' && user.value.role !== 'none')
const delta = computed(() => operation.value === 'plus' ? points.value : -points.value)
const targetIds = computed(() => [...new Set(targets.value)])
const selectedPeople = computed(() => directory.value.people.filter(p => targetIds.value.includes(p.id)))
const targetWarnings = computed(() => targetIds.value.flatMap(id => {
  const person = directory.value.people.find(p => p.id === id)
  return person?.status === 'active' ? [] : [`${person?.name ?? '已选人员'}当前不可用，请移除后重新选择。`]
}))
const displayAdminPeople = computed(() => directory.value.people.filter(p => p.name.includes(adminQuery.value.trim())))
const validPreview = computed(() => preview.value && new Date(preview.value.expires_at).getTime() > clock.value)
const activeRow = computed(() => preview.value?.rows[previewIndex.value] ?? preview.value?.rows[0])
const detailScoreRows = computed(() => detail.value?.snapshot.rows.map(row => ({
  person: row.person, originalTotal: row.final_total,
  score: detail.value?.scores?.find(score => score.person_id === row.person.id),
})) ?? [])
const draftPerson = computed(() => selectedPeople.value[previewIndex.value] ?? selectedPeople.value[0])
const draftContext = computed<CardContext | null>(() => {
  const person = draftPerson.value
  if (!person) return null
  return { person_name: person.name, person_open_id: person.open_id, delta: delta.value,
    department: [...new Set(person.paths.map(path => path.names.join(' / ')).filter(Boolean))].sort().join('；') || '直属企业',
    total: manual.value[person.id] ? overrides.value[person.id] ?? 0 : (totals.value[person.id] ?? 60) + delta.value,
    reason: reason.value || '待填写', operator_name: user.value?.name ?? '', month: month.value,
    time: '', operation: operation.value === 'plus' ? '加分' : '扣分' }
})
const timeLabel = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '尚未同步'
const roleLabels = { admin: '管理员', operator: '操作员', none: '未授权' }
function resultSummary(counts: Record<string, number> | undefined, labels: Record<string, string>) {
  return Object.entries(counts ?? {}).filter(([, count]) => count > 0)
    .map(([status, count]) => `${labels[status] ?? status} ${count}`).join(' · ')
}

const historyStatusParts = (item: HistoryItem) => {
  const parts: { text: string; error: boolean; pulse: boolean }[] = []
  const add = (text: string, error = false, pulse = false) => parts.push({ text, error, pulse })
  if (item.statuses.failed) add(`发送失败 ${item.statuses.failed}`, true)
  if (item.statuses.review) add(`待核实 ${item.statuses.review}`, true)
  if (item.recall_statuses?.recalled) add(`已撤回 ${item.recall_statuses.recalled}`)
  if (item.cancelled_scores) add(`已作废 ${item.cancelled_scores} 笔记分`, true)
  if (item.recall_statuses?.pending || item.recall_statuses?.recalling) add(`撤回处理中 ${(item.recall_statuses.pending ?? 0) + (item.recall_statuses.recalling ?? 0)}`, false, true)
  if (item.recall_statuses?.failed) add(`撤回失败 ${item.recall_statuses.failed}`, true)
  if (item.recall_statuses?.review) add(`撤回待核实 ${item.recall_statuses.review}`, true)
  return parts
}

async function action(fn: () => Promise<void>) {
  if (busy.value) return
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
watch(recallConfirmation, async (value) => {
  if (value) { captureOpener(); await nextTick(); recallSend.value?.focus() }
  else restoreOpener()
})
watch(detail, async (value) => {
  if (value) { captureOpener(); await nextTick(); detailClose.value?.focus() }
  else restoreOpener()
})
watch(rangeDialog, async (value) => {
  if (value) { captureOpener(); await nextTick(); rangeClose.value?.focus() }
  else { await nextTick(); restoreOpener() }
})
async function refresh() {
  const [data, balances, configs] = await Promise.all([api<Directory>('/directory'), api<Balances>('/balances'), api<Preset[]>('/presets')])
  directory.value = data; applyBalances(balances); presets.value = configs
  if (presetId.value && !mirrorRecipients.value) {
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
      if (page.value === 'history' && history.value.some(item => item.recall_statuses?.pending || item.recall_statuses?.recalling)) void loadHistory().catch(() => {})
    }
  }, 3000)
})
const submitHint = computed(() => {
  if (busy.value) return '正在处理…'
  if (!selectedPeople.value.length) return '请先选择记分对象'
  if (targetWarnings.value.length) return '请移除不可用的加减分对象'
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
onUnmounted(() => { window.removeEventListener('keydown', onKeydown); clearInterval(timer); clearTimeout(resolveTimer); clearTimeout(previewTimer); clearTimeout(noticeTimer) })
let previewTimer: ReturnType<typeof setTimeout> | undefined
const previewReady = computed(() => !busy.value && !recipientsResolving.value && selectedPeople.value.length > 0 && !targetWarnings.value.length && reason.value.trim().length > 0 && resolvedRecipients.value.length > 0 && !recipientWarnings.value.length)
watch([targets, targetWarnings, recipients, operation, points, reason, manual, overrides, resolvedRecipients, recipientWarnings, recipientsResolving], () => {
  clearTimeout(previewTimer)
  preview.value = null; confirmation.value = false; idempotency.value = ''
  if (!previewReady.value) return
  previewTimer = setTimeout(() => { void makePreview() }, 600)
}, { deep: true })
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
watch([targetIds, mirrorRecipients], () => {
  if (mirrorRecipients.value) { presetId.value = ''; recipients.value = { ...emptySelection(), person_ids: [...targetIds.value] } }
}, { deep: true })

function toggleManual(person: Person, checked: boolean) {
  manual.value[person.id] = checked
  if (checked) overrides.value[person.id] = (totals.value[person.id] ?? 60) + delta.value
}
async function makePreview() {
  if (busy.value) return
  if (recipientsResolving.value || !selectedPeople.value.length || targetWarnings.value.length || !reason.value.trim() || !resolvedRecipients.value.length || recipientWarnings.value.length) return
  await action(async () => {
    if (!Number.isInteger(points.value) || points.value <= 0) throw new Error('请输入正整数分值')
    const values: Record<string, number> = {}
    targetIds.value.forEach(id => { if (manual.value[id]) values[id] = overrides.value[id] ?? 0 })
    preview.value = await api<Preview>('/adjustments/preview', 'POST', { person_ids: targetIds.value, operation: operation.value, points: points.value, reason: reason.value, overrides: values, recipients: recipients.value })
    previewIndex.value = 0; idempotency.value = crypto.randomUUID()
  })
}
async function commit() {
  if (!preview.value || !validPreview.value) return
  await action(async () => {
    const result = await api<{ id: string }>('/adjustments', 'POST', { preview_token: preview.value!.preview_token, idempotency_key: idempotency.value })
    confirmation.value = false; preview.value = null; targets.value = []; manual.value = {}; overrides.value = {}; reason.value = ''
    await loadDetail(result.id); await refresh(); notice.value = '积分已记账，通知正在发送。'
  })
}
function loadPreset() {
  const preset = presets.value.find(p => p.id === presetId.value)
  mirrorRecipients.value = false
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
  mirrorRecipients.value = false; presetId.value = ''; recipients.value = JSON.parse(JSON.stringify(rangeDraft.value)); rangeDialog.value = false
}
function clearRecipientRange() { mirrorRecipients.value = false; presetId.value = ''; recipients.value = unionSelection() }
async function loadHistory() {
  loadingHistory.value = true
  try {
    const result = await api<{ items: HistoryItem[]; total: number }>('/adjustments?page=' + historyPage.value)
    const balances = await api<Balances>('/balances')
    history.value = result.items; historyTotal.value = result.total; applyBalances(balances)
  } finally { loadingHistory.value = false }
}
async function loadDetail(id: string, selectedPage = 1, polling = false) {
  const sequence = ++detailSequence
  const result = await api<BatchDetail>(`/adjustments/${id}?page=${selectedPage}`)
  const balances = await api<Balances>('/balances')
  if (sequence !== detailSequence || polling && detail.value?.id !== id) return
  detail.value = result; applyBalances(balances)
}
function closeDetail() { ++detailSequence; detail.value = null }
async function switchPage(value: typeof page.value) { page.value = value; await action(async () => { if (value === 'history') await loadHistory(); else await refresh() }) }
async function updateRole(person: Person, event: Event) { const role = (event.target as HTMLSelectElement).value; await action(async () => { await api(`/admin/people/${person.id}/role`, 'PUT', { role }); user.value = await api<User>('/auth/me'); if (authorized.value) await refresh(); notice.value = '权限已更新。' }); if (error.value) (event.target as HTMLSelectElement).value = person.role }
async function logout() { await action(async () => { await api('/auth/logout', 'POST'); user.value = null; closeDetail(); preview.value = null; setCsrf('') }) }
async function retry(id: string) { await action(async () => { await api(`/deliveries/${id}/retry`, 'POST'); await loadDetail(detail.value!.id, detail.value!.page) }) }
function recallStillAvailable(delivery: import('./types').Delivery) { return delivery.can_recall && !!delivery.recall_deadline && new Date(delivery.recall_deadline).getTime() > clock.value }
function askBatchRecall(item: HistoryItem | BatchDetail) {
  const names = 'names' in item ? item.names : item.snapshot.rows.map(row => row.person.name)
  recallConfirmation.value = { batchId: item.id, count: item.recall_available, names: names.join('、') }
}
async function confirmRecall() {
  const request = recallConfirmation.value
  if (!request) return
  await action(async () => {
    const result = await api<{ accepted: number }>(request.deliveryId ? `/deliveries/${request.deliveryId}/recall` : `/adjustments/${request.batchId}/recall`, 'POST')
    recallConfirmation.value = null
    if (detail.value?.id === request.batchId) await loadDetail(request.batchId, detail.value.page)
    if (page.value === 'history') await loadHistory()
    notice.value = result.accepted ? `已申请撤回 ${result.accepted} 条卡片。` : '撤回任务已提交或完成。'
  })
}
</script>

<template>
  <div class="page" :inert="rangeDialog">
    <header class="topbar">
      <a class="brand" href="/"><img class="brand-logo" :src="logoUrl" alt="" width="36" height="36"><span>ORVIBO_员工积分系统</span></a>
      <div v-if="user" class="topbar-right">
        <div class="account-panel" aria-label="当前账号">
          <div class="account-identity">
            <EmployeeAvatar :src="user.avatar_url" :name="user.name" />
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
      <nav class="navigation" aria-label="功能导航"><button type="button" :class="{ active: page === 'console' }" :disabled="busy" @click="switchPage('console')">操作台</button><button type="button" :class="{ active: page === 'lists' }" :disabled="busy" @click="switchPage('lists')">发送名单</button><button type="button" :class="{ active: page === 'history' }" :disabled="busy" @click="switchPage('history')">发送记录</button><button v-if="user.role === 'admin'" type="button" :class="{ active: page === 'admin' }" :disabled="busy" @click="switchPage('admin')">权限管理</button><span>{{ month }}</span></nav>
      <main v-if="page === 'console'" class="layout">
        <section class="panel" aria-label="积分操作">
          <form class="op-form" @submit.prevent="makePreview"><fieldset class="op-form-body" :disabled="busy">
            <div class="form-section">
              <PersonMultiSelect v-model="targets" :people="directory.people" />
              <p v-for="warning in targetWarnings" :key="warning" class="error-text">{{ warning }}</p>
              <div><div class="field-label"><span class="prompt">&gt;</span> 操作类型</div><div class="f-seg"><button type="button" class="opt plus" :class="{ active: operation === 'plus' }" @click="operation = 'plus'">＋ 加分</button><button type="button" class="opt minus" :class="{ active: operation === 'minus' }" @click="operation = 'minus'">－ 扣分</button></div></div>
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
              <div><label class="field-label" for="reason"><span class="prompt">&gt;</span> 原因 <small>必填</small></label><textarea id="reason" v-model="reason" maxlength="2000" rows="3" placeholder="填写原因"></textarea></div>
              <div v-if="selectedPeople.length"><div class="field-label"><span class="prompt">&gt;</span> 最终总分</div><div v-for="person in selectedPeople" :key="person.id" class="balance-row" role="group" :aria-label="`${person.name}总分`"><EmployeeAvatar :src="person.avatar_url" :name="person.name" size="small" /><div><b>{{ person.name }}</b><span class="balance-line">{{ totals[person.id] ?? 60 }} → <b :class="operation === 'plus' ? 'plus-text' : 'minus-text'">{{ manual[person.id] ? overrides[person.id] : (totals[person.id] ?? 60) + delta }}</b></span></div><label class="manual-toggle"><input type="checkbox" :checked="manual[person.id] ?? false" @change="toggleManual(person, ($event.target as HTMLInputElement).checked)">手动总分</label><input v-if="manual[person.id]" v-model.number="overrides[person.id]" class="override-input" type="number" step="1" :aria-label="`${person.name}最终总分`"></div><p v-if="selectedPeople.some(person => manual[person.id])" class="hint">手动总分已包含本次加减。</p></div>
            </div>
            <div class="form-section">
              <div class="recipient-heading"><label class="field-label" for="recipient-preset"><span class="prompt">&gt;</span> 发送名单</label><button type="button" class="text-link" @click="switchPage('lists')">维护名单</button></div>
              <select id="recipient-preset" v-model="presetId" aria-label="选择发送名单" :disabled="mirrorRecipients" @change="loadPreset"><option value="">临时范围</option><optgroup v-if="publicPresets.length" label="公共名单"><option v-for="preset in publicPresets" :key="preset.id" :value="preset.id">{{ preset.name }}</option></optgroup><optgroup v-if="personalPresets.length" label="我的名单"><option v-for="preset in personalPresets" :key="preset.id" :value="preset.id">{{ preset.name }}</option></optgroup></select>
              <label class="mirror-toggle"><input type="checkbox" v-model="mirrorRecipients">通知范围同记分对象</label>
              <div class="recipient-toolbar"><span>{{ recipientsResolving ? '正在匹配…' : `${resolvedRecipients.length} 位通知对象` }}</span><div v-if="!mirrorRecipients" class="recipient-range-actions"><button v-if="resolvedRecipients.length || recipientWarnings.length" type="button" class="text-link" @click="clearRecipientRange">清空</button><button type="button" @click="editRange">{{ presetId ? '临时调整' : '选择范围' }}</button></div></div>
              <details v-if="resolvedRecipients.length" class="recipient-fold"><summary>查看通知名单</summary><div class="chips recipient-chips"><span v-for="person in resolvedRecipients" :key="person.id" class="chip"><EmployeeAvatar :src="person.avatar_url" :name="person.name" size="tiny" />{{ person.name }}</span></div></details>
              <p v-for="warning in recipientWarnings" :key="warning" class="error-text">{{ warning }}</p>
            </div>
            <div class="send-summary"><b>{{ selectedPeople.length }}</b> 位记分对象 · <b>{{ resolvedRecipients.length }}</b> 位通知对象 · <b>{{ selectedPeople.length * resolvedRecipients.length }}</b> 条卡片</div>
            <button class="primary-button form-submit" :class="{ busy }" type="submit" :disabled="!previewReady">{{ busy ? '正在处理…' : '更新预览' }}</button>
            <p v-if="submitHint" class="hint submit-hint" aria-live="polite">{{ submitHint }}</p>
          </fieldset></form>
        </section>
        <aside class="panel preview-panel"><div class="panel-head"><h2 class="panel-title">卡片预览</h2></div>
          <select v-if="(preview?.rows.length ?? selectedPeople.length) > 1" v-model.number="previewIndex" aria-label="切换卡片预览人员"><option v-for="(person, index) in (preview ? preview.rows.map(r => r.person) : selectedPeople)" :key="person.id" :value="index">{{ person.name }}</option></select>
          <CardPreview v-if="activeRow" :context="activeRow.context" :variables="activeRow.card.data.template_variable" :avatar-url="activeRow.person.avatar_url" /><CardPreview v-else-if="draftContext" :context="draftContext" :avatar-url="draftPerson?.avatar_url" /><div v-else class="empty-preview"><img class="empty-preview-logo" :src="logoUrl" alt="" width="36" height="36"><p>请选择记分对象</p></div>
          <template v-if="preview"><div class="preview-details"><p><b>{{ preview.recipients.length }}</b> 位通知对象 · <b>{{ preview.message_count }}</b> 条卡片</p><details><summary>通知名单</summary><div class="chips"><span v-for="person in preview.recipients" :key="person.id" class="chip"><EmployeeAvatar :src="person.avatar_url" :name="person.name" size="tiny" />{{ person.name }}</span></div></details><small>有效至 {{ timeLabel(preview.expires_at) }}</small></div><p v-if="!validPreview" class="error-text">预览已过期，请更新预览。</p><button type="button" class="primary-button preview-send" :disabled="busy || !validPreview" @click="confirmation = true">核对并发送</button></template>
        </aside>
        <div class="mobile-actions">
          <button v-if="!preview" type="button" :disabled="!previewReady" @click="makePreview">{{ busy ? '正在处理…' : '更新预览' }}</button>
          <button v-else class="primary-button" type="button" :disabled="busy || !validPreview" @click="confirmation = true">核对并发送</button>
        </div>
      </main>
      <RecipientLists v-else-if="page === 'lists'" :presets="presets" :directory="directory" :user="user" @saved="savedPreset" @deleted="deletedPreset" />
      <section v-else-if="page === 'history'" class="panel">
        <div class="panel-head flex-head"><h1 class="panel-title">发送记录</h1><button type="button" :disabled="busy" @click="action(loadHistory)">刷新</button></div>
        <div v-if="loadingHistory" class="empty-state">加载中…</div>
        <div v-else-if="!history.length" class="empty-state">还没有操作记录。</div>
        <div v-for="item in history" :key="item.id" class="history-entry">
          <button type="button" class="history-item" :disabled="busy" @click="action(() => loadDetail(item.id))">
            <div><b>{{ item.names.join('、') }}</b><span class="signed-number" :class="item.delta > 0 ? 'plus-text' : 'minus-text'">{{ item.delta > 0 ? '+' : '' }}{{ item.delta }} 分</span></div>
            <p>{{ item.reason }}</p><small>{{ timeLabel(item.created_at) }} · {{ item.operator_name }} · {{ item.statuses.sent ?? 0 }} / {{ item.message_count }} 已发送</small>
            <p v-if="historyStatusParts(item).length" class="status-line"><template v-for="(part, index) in historyStatusParts(item)" :key="index"><span v-if="index"> · </span><span :class="{ 'error-text': part.error, pulse: part.pulse }">{{ part.text }}</span></template></p>
          </button>
          <div class="history-actions"><button v-if="item.recall_available" type="button" class="recall-button" :disabled="busy" @click="askBatchRecall(item)">撤回卡片 · {{ item.recall_available }}</button><button type="button" :disabled="busy" @click="action(() => loadDetail(item.id))">查看结果</button></div>
        </div>
        <div v-if="historyTotal > 20" class="pagination"><button type="button" :disabled="busy || historyPage <= 1" @click="historyPage--; action(loadHistory)">上一页</button><span>{{ historyPage }} / {{ Math.max(1, Math.ceil(historyTotal / 20)) }}</span><button type="button" :disabled="busy || historyPage * 20 >= historyTotal" @click="historyPage++; action(loadHistory)">下一页</button></div>
      </section>
      <section v-else-if="user.role === 'admin'" class="panel"><DirectorySync :busy="busy" @synced="action(refresh)" /><input v-model="adminQuery" type="search" aria-label="权限管理搜索" placeholder="搜索姓名"><div class="admin-head"><span>姓名</span><span>状态</span><span>权限</span></div><div class="admin-table"><div v-for="person in displayAdminPeople" :key="person.id" class="admin-row"><EmployeeAvatar :src="person.avatar_url" :name="person.name" size="small" /><div><b>{{ person.name }}</b><small>{{ person.paths.map(p => p.names.join(' / ')).join('；') || '直属企业' }}</small></div><span>{{ statusLabels[person.status] }}</span><select :value="person.role" :aria-label="`${person.name}权限`" :disabled="busy || person.status !== 'active' && person.role === 'none'" @change="updateRole(person, $event)"><option value="none">未授权</option><option value="operator" :disabled="person.status !== 'active'">操作员</option><option value="admin" :disabled="person.status !== 'active'">管理员</option></select></div></div></section>
    </template>
  </div>
  <Transition name="modal">
  <div v-if="confirmation && preview" class="modal-backdrop" @click.self="!busy && (confirmation = false)"><section class="panel modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title"><h2 id="confirm-title" class="panel-title">确认发送</h2><p>{{ preview.rows.length }} 人 · 每人{{ preview.delta > 0 ? '加' : '扣' }} {{ Math.abs(preview.delta) }} 分</p><p class="reason-box">{{ preview.reason }}</p><div v-for="row in preview.rows" :key="row.person.id" class="confirm-total"><EmployeeAvatar :src="row.person.avatar_url" :name="row.person.name" size="small" /><span>{{ row.person.name }}</span><b>{{ row.before_total }} → {{ row.final_total }} 分</b><small v-if="row.override_total !== null">手动覆盖</small></div><p>{{ preview.recipients.length }} 位通知对象 · {{ preview.message_count }} 条卡片</p><p class="hint">确认后记分生效，失败通知可重试。</p><div class="modal-actions"><button type="button" :disabled="busy" @click="confirmation = false">返回</button><button ref="confirmSend" type="button" class="primary-button" :class="{ busy }" :disabled="busy || !validPreview" @click="commit">{{ busy ? '正在提交…' : '确认发送' }}</button></div></section></div></Transition>
  <Transition name="modal">
  <div v-if="detail" class="modal-backdrop" @click.self="!busy && closeDetail()">
    <section class="panel modal wide-modal" role="dialog" aria-modal="true" aria-labelledby="detail-title">
      <div class="flex-head"><h2 id="detail-title" class="panel-title">发送及撤回结果</h2><button ref="detailClose" type="button" aria-label="关闭发送结果" :disabled="busy" @click="closeDetail">×</button></div>
      <div class="modal-section-title">逐人积分状态</div>
      <div class="score-results" aria-label="逐人积分状态">
        <div v-for="row in detailScoreRows" :key="row.person.id" class="score-result">
          <div class="score-person"><EmployeeAvatar :src="row.person.avatar_url" :name="row.person.name" size="small" /><b>{{ row.person.name }}</b><span class="score-state" :class="{ cancelled: row.score?.cancelled }">{{ row.score ? row.score.cancelled ? '记分已作废' : '积分有效' : '积分状态待更新' }}</span></div>
          <div class="score-values"><span>发送时总分 <b>{{ row.originalTotal }}</b> 分</span><span v-if="row.score">{{ detail.snapshot.month }} 当前总分 <b>{{ row.score.current_total }}</b> 分</span></div>
          <small v-if="row.score?.cancelled_at">作废时间：{{ timeLabel(row.score.cancelled_at) }}</small>
        </div>
      </div>
      <p v-if="resultSummary(detail.statuses, statusLabels)" class="hint">{{ resultSummary(detail.statuses, statusLabels) }}</p>
      <div v-if="resultSummary(detail.recall_statuses, recallLabels) || detail.recall_available" class="recall-toolbar"><p v-if="resultSummary(detail.recall_statuses, recallLabels)" class="hint" :class="{ pulse: detail.recall_statuses?.pending || detail.recall_statuses?.recalling }">{{ resultSummary(detail.recall_statuses, recallLabels) }}</p><button v-if="detail.recall_available" type="button" class="recall-button" :disabled="busy" @click="askBatchRecall(detail)">撤回本批卡片 · {{ detail.recall_available }}</button></div>
      <div class="modal-section-title">通知明细</div>
      <div class="deliveries"><div v-for="delivery in detail.deliveries" :key="delivery.id" class="delivery-row">
        <div><b>{{ detail.snapshot.rows.find(r => r.person.id === delivery.person_id)?.person.name }} → {{ delivery.recipient_name }}</b><small>{{ delivery.message_id || delivery.last_error || '等待后台发送' }}</small><p v-if="delivery.recall_error" class="error-text">{{ delivery.recall_error }}</p><small v-if="delivery.recalled_at">撤回确认时间：{{ timeLabel(delivery.recalled_at) }}</small><small v-else-if="recallStillAvailable(delivery)">可申请至 {{ timeLabel(delivery.recall_deadline) }}</small></div>
        <span>{{ delivery.recall_status ? recallLabels[delivery.recall_status] : statusLabels[delivery.status] }}</span>
        <button v-if="recallStillAvailable(delivery)" type="button" class="recall-button" :disabled="busy" @click="recallConfirmation = { batchId: detail.id, deliveryId: delivery.id, count: 1, names: delivery.recipient_name }">{{ delivery.recall_status ? '重试撤回' : '撤回' }}</button>
        <button v-else-if="delivery.status === 'failed'" type="button" :disabled="busy" @click="retry(delivery.id)">重试发送</button>
        <small v-else-if="delivery.status === 'sent' && !delivery.recall_status && !recallStillAvailable(delivery)">已超撤回时限</small>
      </div></div>
      <div class="pagination"><template v-if="detail.total > 100"><button type="button" :disabled="busy || detail.page <= 1" @click="action(() => loadDetail(detail!.id, detail!.page - 1))">上一页</button><small>{{ detail.page }} / {{ Math.max(1, Math.ceil(detail.total / 100)) }}</small><button type="button" :disabled="busy || detail.page * 100 >= detail.total" @click="action(() => loadDetail(detail!.id, detail!.page + 1))">下一页</button></template><button type="button" :disabled="busy" @click="action(() => loadDetail(detail!.id, detail!.page))">刷新</button></div>
    </section>
  </div>
</Transition>
  <Transition name="modal">
  <div v-if="recallConfirmation" class="modal-backdrop recall-confirmation" @click.self="!busy && (recallConfirmation = null)">
    <section class="panel modal" role="dialog" aria-modal="true" aria-labelledby="recall-title">
      <h2 id="recall-title" class="panel-title">确认撤回</h2>
      <p>{{ recallConfirmation.deliveryId ? '通知接收人' : '记分对象' }}：{{ recallConfirmation.names }}</p>
      <p>撤回 {{ recallConfirmation.count }} 条卡片</p>
      <p class="hint">全部通知撤回成功后，对应记分作废；部分撤回仍有效。</p>
      <p v-if="error" class="error-text">{{ error }}</p>
      <div class="modal-actions"><button type="button" :disabled="busy" @click="recallConfirmation = null">取消</button><button ref="recallSend" type="button" class="primary-button" :class="{ busy }" :disabled="busy" @click="confirmRecall">{{ busy ? '正在提交…' : '确认撤回' }}</button></div>
    </section>
  </div>
</Transition>
  <Transition name="modal">
    <div v-if="rangeDialog" class="modal-backdrop" @click.self="!busy && (rangeDialog = false)">
      <section class="panel modal range-modal" role="dialog" aria-modal="true" aria-labelledby="range-dialog-title">
        <div class="panel-head flex-head"><h2 id="range-dialog-title" class="panel-title">临时通知范围</h2><button ref="rangeClose" type="button" :disabled="busy" @click="rangeDialog = false">取消</button></div>
        <RecipientRangeEditor v-model="rangeDraft" :people="directory.people" :departments="directory.departments" @ready="rangeReady = $event" />
        <div class="modal-actions"><button type="button" class="primary-button" :disabled="busy || !rangeReady" @click="applyRange">使用此范围</button></div>
      </section>
    </div>
  </Transition>
</template>
