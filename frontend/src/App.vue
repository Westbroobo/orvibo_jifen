<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, ApiError, setCsrf } from './api'
import { emptySelection, recallLabels, statusLabels } from './types'
import type { BatchDetail, CardContext, Directory, HistoryItem, Person, Preset, Preview, User } from './types'
import PeoplePicker from './components/PeoplePicker.vue'
import CardPreview from './components/CardPreview.vue'
import EmployeeAvatar from './components/EmployeeAvatar.vue'
import DirectorySync from './components/DirectorySync.vue'

const user = ref<User | null>(null)
const ready = ref(false)
const redirectingToFeishu = ref(false)
const demoAvailable = ref(false)
const page = ref<'console' | 'history' | 'admin'>('console')
const directory = ref<Directory>({ people: [], departments: [], last_sync_at: null, last_sync_error: null, sync_requested: false })
const totals = ref<Record<string, number>>({})
const month = ref('')
const targets = ref(emptySelection())
const recipients = ref(emptySelection())
const operation = ref<'plus' | 'minus'>('plus')
const points = ref(5)
const reason = ref('')
const manual = ref<Record<string, boolean>>({})
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
const presetName = ref('')
const resolvedRecipients = ref<Person[]>([])
const recipientWarnings = ref<string[]>([])
const history = ref<HistoryItem[]>([])
const historyTotal = ref(0)
const historyPage = ref(1)
const detail = ref<BatchDetail | null>(null)
type Balances = { month: string; totals: Record<string, number>; versions?: Record<string, number> }
const recallConfirmation = ref<{ batchId: string; deliveryId?: string; count: number; names: string } | null>(null)
const adminQuery = ref('')
const clock = ref(Date.now())
let timer: ReturnType<typeof setInterval> | undefined
let resolveTimer: ReturnType<typeof setTimeout> | undefined
let resolveSequence = 0
let detailSequence = 0

const authorized = computed(() => user.value?.status === 'active' && user.value.role !== 'none')
const delta = computed(() => operation.value === 'plus' ? points.value : -points.value)
const targetIds = computed(() => [...new Set([
  ...directory.value.people.filter(p => targets.value.person_ids.includes(p.id) && (!targets.value.levels.some(l => l.length) || p.paths.some(path => targets.value.levels.every((ids, i) => !ids.length || ids.includes(path.ids[i] ?? ''))))).map(p => p.id),
  ...targets.value.extra_ids,
])])
const selectedPeople = computed(() => directory.value.people.filter(p => targetIds.value.includes(p.id)))
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
  const parts: { text: string; error: boolean }[] = []
  const add = (text: string, error = false) => parts.push({ text, error })
  if (item.statuses.failed) add(`发送失败 ${item.statuses.failed}`, true)
  if (item.statuses.review) add(`待核实 ${item.statuses.review}`, true)
  if (item.recall_statuses?.recalled) add(`已撤回 ${item.recall_statuses.recalled}`)
  if (item.cancelled_scores) add(`已作废 ${item.cancelled_scores} 笔记分`, true)
  if (item.recall_statuses?.pending || item.recall_statuses?.recalling) add(`撤回处理中 ${(item.recall_statuses.pending ?? 0) + (item.recall_statuses.recalling ?? 0)}`)
  if (item.recall_statuses?.failed) add(`撤回失败 ${item.recall_statuses.failed}`, true)
  if (item.recall_statuses?.review) add(`撤回待核实 ${item.recall_statuses.review}`, true)
  return parts
}

async function action(fn: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try { await fn() } catch (e) { error.value = e instanceof Error ? e.message : '操作失败' } finally { busy.value = false }
}
async function refresh() {
  const [data, balances, configs] = await Promise.all([api<Directory>('/directory'), api<Balances>('/balances'), api<Preset[]>('/presets')])
  directory.value = data; applyBalances(balances); presets.value = configs
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
onUnmounted(() => { clearInterval(timer); clearTimeout(resolveTimer) })
watch([targets, recipients, operation, points, reason, manual, overrides], () => { preview.value = null; confirmation.value = false; idempotency.value = '' }, { deep: true })
watch([recipients, directory], () => {
  clearTimeout(resolveTimer); const sequence = ++resolveSequence
  resolveTimer = setTimeout(async () => {
    if (!authorized.value) return
    try { const result = await api<{ people: Person[]; warnings: string[] }>('/ranges/resolve', 'POST', recipients.value); if (sequence === resolveSequence) { resolvedRecipients.value = result.people; recipientWarnings.value = result.warnings } }
    catch (e) { if (sequence === resolveSequence) recipientWarnings.value = [e instanceof Error ? e.message : '范围解析失败'] }
  }, 150)
}, { deep: true })

function toggleManual(person: Person, checked: boolean) {
  manual.value[person.id] = checked
  if (checked) overrides.value[person.id] = (totals.value[person.id] ?? 60) + delta.value
}
async function makePreview() {
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
    confirmation.value = false; preview.value = null; targets.value = emptySelection(); manual.value = {}; overrides.value = {}; reason.value = ''
    await loadDetail(result.id); await refresh(); notice.value = '积分已记账，通知正在发送。'
  })
}
function loadPreset() {
  const preset = presets.value.find(p => p.id === presetId.value)
  presetName.value = preset?.name ?? ''
  recipients.value = preset ? JSON.parse(JSON.stringify(preset.selection)) : emptySelection()
}
async function savePreset() { await action(async () => { const saved = await api<Preset>(presetId.value ? `/presets/${presetId.value}` : '/presets', presetId.value ? 'PUT' : 'POST', { name: presetName.value, selection: recipients.value }); presets.value = await api<Preset[]>('/presets'); presetId.value = saved.id; notice.value = '个人发送配置已保存。' }) }
async function deletePreset() { await action(async () => { await api(`/presets/${presetId.value}`, 'DELETE'); presets.value = presets.value.filter(p => p.id !== presetId.value); presetId.value = ''; presetName.value = ''; notice.value = '配置已删除。' }) }
async function loadHistory() {
  const result = await api<{ items: HistoryItem[]; total: number }>('/adjustments?page=' + historyPage.value)
  const balances = await api<Balances>('/balances')
  history.value = result.items; historyTotal.value = result.total; applyBalances(balances)
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
  <div class="page">
    <header class="topbar">
      <a class="brand" href="/"><img class="brand-logo" src="/logo.svg" alt="" width="36" height="36"><span>ORVIBO_员工积分系统</span></a>
      <div v-if="user" class="topbar-right">
        <div class="account-panel" aria-label="当前账号">
          <div class="account-identity">
            <EmployeeAvatar :src="user.avatar_url" :name="user.name" />
            <div class="account-details"><strong class="account-name" :title="user.name">{{ user.name }}</strong><span class="account-role">{{ roleLabels[user.role] }}</span></div>
          </div>
          <div class="account-actions"><button class="logout-button" :disabled="busy" aria-label="退出登录" title="退出登录" @click="logout"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M9 5H5v14h4M14 8l4 4-4 4M9 12h10" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" /></svg><span>退出</span></button></div>
        </div>
      </div>
    </header>
    <div v-if="error" class="feedback error" role="alert">{{ error }}<button aria-label="关闭提示" @click="error = ''">×</button></div>
    <div v-if="notice" class="feedback" role="status">{{ notice }}</div>
    <div v-if="user?.demo_mode" class="demo-banner">本地演示 · 使用虚拟人员，通知仅模拟发送</div>
    <section v-if="!ready" class="panel login-panel"><h1>{{ redirectingToFeishu ? '正在前往飞书授权…' : '正在加载员工积分系统' }}</h1></section>
    <section v-else-if="!user" class="panel login-panel"><h1>{{ error ? '暂时无法进入系统' : '已退出登录' }}</h1><p v-if="!error">需要继续使用时，请授权飞书账号。</p><a class="primary-button" href="/api/auth/login">{{ error ? '重新授权飞书账号' : '使用飞书账号授权' }}</a><button v-if="demoAvailable" :disabled="busy" @click="action(async () => { await api('/auth/demo', 'POST'); await initialize() })">进入本地演示</button></section>
    <section v-else-if="!authorized" class="panel login-panel"><h1>当前账号暂无操作权限</h1><p>请联系管理员分配积分操作权限。{{ user.status === 'unknown' ? '人员目录尚待同步核实。' : '' }}</p><button :disabled="busy" @click="action(initialize)">重新检查权限</button></section>
    <template v-else>
      <nav class="navigation" aria-label="功能导航"><button :class="{ active: page === 'console' }" :disabled="busy" @click="switchPage('console')">操作台</button><button :class="{ active: page === 'history' }" :disabled="busy" @click="switchPage('history')">发送记录</button><button v-if="user.role === 'admin'" :class="{ active: page === 'admin' }" :disabled="busy" @click="switchPage('admin')">权限管理</button><span>{{ month }} · 基础分 60</span></nav>
      <main v-if="page === 'console'" class="layout">
        <section class="panel" aria-label="积分操作">
          <fieldset class="op-form" :disabled="busy">
            <PeoplePicker v-model="targets" :people="directory.people" :departments="directory.departments" title="记分对象" />
            <div><div class="field-label"><span class="prompt">&gt;</span> 操作类型</div><div class="f-seg"><button type="button" class="opt plus" :class="{ active: operation === 'plus' }" @click="operation = 'plus'">＋ 加分</button><button type="button" class="opt minus" :class="{ active: operation === 'minus' }" @click="operation = 'minus'">－ 扣分</button></div></div>
            <div><label class="field-label" for="points"><span class="prompt">&gt;</span> 每人分值</label><div class="f-points"><span :class="operation === 'plus' ? 'plus-text' : 'minus-text'">{{ operation === 'plus' ? '+' : '−' }}</span><input id="points" v-model.number="points" type="number" min="1" step="1" :class="operation === 'plus' ? 'plus-text' : 'minus-text'"><span class="unit">分</span><div class="stepper"><button type="button" aria-label="减少分值" @click="points = Math.max(1, points - 1)">−</button><button type="button" aria-label="增加分值" @click="points++">＋</button></div></div></div>
            <div><label class="field-label" for="reason"><span class="prompt">&gt;</span> 原因 <small>必填</small></label><textarea id="reason" v-model="reason" maxlength="2000" rows="3" placeholder="填写原因"></textarea></div>
            <div v-if="selectedPeople.length"><div class="field-label"><span class="prompt">&gt;</span> 最终总分</div><div v-for="person in selectedPeople" :key="person.id" class="balance-row" role="group" :aria-label="`${person.name}总分`"><EmployeeAvatar :src="person.avatar_url" :name="person.name" size="small" /><div><b>{{ person.name }}</b><span class="balance-line">{{ totals[person.id] ?? 60 }} → <b :class="operation === 'plus' ? 'plus-text' : 'minus-text'">{{ manual[person.id] ? overrides[person.id] : (totals[person.id] ?? 60) + delta }}</b></span></div><label class="manual-toggle"><input type="checkbox" :checked="manual[person.id] ?? false" @change="toggleManual(person, ($event.target as HTMLInputElement).checked)">手动总分</label><input v-if="manual[person.id]" v-model.number="overrides[person.id]" class="override-input" type="number" step="1" :aria-label="`${person.name}最终总分`"></div><p v-if="selectedPeople.some(person => manual[person.id])" class="hint">手动总分已包含本次加减。</p></div>
            <div class="section-divider"></div>
            <div><div class="field-label"><span class="prompt">&gt;</span> 发送配置</div><select v-model="presetId" aria-label="选择个人发送配置" @change="loadPreset"><option value="">临时范围</option><option v-for="preset in presets" :key="preset.id" :value="preset.id">{{ preset.name }}</option></select><div class="preset-actions"><input v-model="presetName" aria-label="发送配置名称" placeholder="配置名称"><button type="button" :disabled="!presetName.trim()" @click="savePreset">{{ presetId ? '更新' : '保存' }}</button><button v-if="presetId" type="button" @click="deletePreset">删除</button></div></div>
            <PeoplePicker v-model="recipients" :people="directory.people" :departments="directory.departments" title="通知范围" allow-all />
            <p v-for="warning in recipientWarnings" :key="warning" class="error-text">{{ warning }}</p>
            <div class="send-summary"><b>{{ selectedPeople.length }}</b> 位记分对象 · <b>{{ resolvedRecipients.length }}</b> 位通知对象 · <b>{{ selectedPeople.length * resolvedRecipients.length }}</b> 条卡片</div>
            <button class="primary-button" :class="{ busy }" :disabled="busy || !selectedPeople.length || !reason.trim() || !resolvedRecipients.length || !!recipientWarnings.length" @click="makePreview">{{ busy ? '正在处理…' : '更新预览' }}</button>
          </fieldset>
        </section>
        <aside class="panel preview-panel"><div class="panel-head"><h2 class="panel-title">卡片预览</h2></div>
          <select v-if="(preview?.rows.length ?? selectedPeople.length) > 1" v-model.number="previewIndex" aria-label="切换卡片预览人员"><option v-for="(person, index) in (preview ? preview.rows.map(r => r.person) : selectedPeople)" :key="person.id" :value="index">{{ person.name }}</option></select>
          <CardPreview v-if="activeRow" :context="activeRow.context" :variables="activeRow.card.data.template_variable" :avatar-url="activeRow.person.avatar_url" /><CardPreview v-else-if="draftContext" :context="draftContext" :avatar-url="draftPerson?.avatar_url" /><div v-else class="empty-preview"><img class="empty-preview-logo" src="/logo.svg" alt="" width="36" height="36"><p>请选择记分对象</p></div>
          <template v-if="preview"><div class="preview-details"><p><b>{{ preview.recipients.length }}</b> 位通知对象 · <b>{{ preview.message_count }}</b> 条卡片</p><details><summary>通知名单</summary><div class="chips"><span v-for="person in preview.recipients" :key="person.id" class="chip"><EmployeeAvatar :src="person.avatar_url" :name="person.name" size="tiny" />{{ person.name }}</span></div></details><small>有效至 {{ timeLabel(preview.expires_at) }}</small></div><p v-if="!validPreview" class="error-text">预览已过期，请更新预览。</p><button class="primary-button" :disabled="busy || !validPreview" @click="confirmation = true">核对并发送</button></template>
        </aside>
      </main>
      <section v-else-if="page === 'history'" class="panel">
        <div class="panel-head flex-head"><h1 class="panel-title">发送记录</h1><button :disabled="busy" @click="action(loadHistory)">刷新</button></div>
        <div v-if="!history.length" class="empty-state">还没有操作记录。</div>
        <div v-for="item in history" :key="item.id" class="history-entry">
          <button class="history-item" :disabled="busy" @click="action(() => loadDetail(item.id))">
            <div><b>{{ item.names.join('、') }}</b><span class="signed-number" :class="item.delta > 0 ? 'plus-text' : 'minus-text'">{{ item.delta > 0 ? '+' : '' }}{{ item.delta }} 分</span></div>
            <p>{{ item.reason }}</p><small>{{ timeLabel(item.created_at) }} · {{ item.operator_name }} · {{ item.statuses.sent ?? 0 }} / {{ item.message_count }} 已发送</small>
            <p v-if="historyStatusParts(item).length" class="status-line"><template v-for="(part, index) in historyStatusParts(item)" :key="index"><span v-if="index"> · </span><span :class="{ 'error-text': part.error }">{{ part.text }}</span></template></p>
          </button>
          <div class="history-actions"><button v-if="item.recall_available" class="recall-button" :disabled="busy" @click="askBatchRecall(item)">撤回卡片 · {{ item.recall_available }}</button><button :disabled="busy" @click="action(() => loadDetail(item.id))">查看结果</button></div>
        </div>
        <div v-if="historyTotal > 20" class="pagination"><button :disabled="busy || historyPage <= 1" @click="historyPage--; action(loadHistory)">上一页</button><span>{{ historyPage }} / {{ Math.max(1, Math.ceil(historyTotal / 20)) }}</span><button :disabled="busy || historyPage * 20 >= historyTotal" @click="historyPage++; action(loadHistory)">下一页</button></div>
      </section>
      <section v-else-if="user.role === 'admin'" class="panel"><DirectorySync :busy="busy" @synced="action(refresh)" /><input v-model="adminQuery" type="search" aria-label="权限管理搜索" placeholder="搜索姓名"><div class="admin-head"><span>姓名</span><span>状态</span><span>权限</span></div><div class="admin-table"><div v-for="person in displayAdminPeople" :key="person.id" class="admin-row"><EmployeeAvatar :src="person.avatar_url" :name="person.name" size="small" /><div><b>{{ person.name }}</b><small>{{ person.paths.map(p => p.names.join(' / ')).join('；') || '直属企业' }}</small></div><span>{{ statusLabels[person.status] }}</span><select :value="person.role" :aria-label="`${person.name}权限`" :disabled="busy || person.status !== 'active' && person.role === 'none'" @change="updateRole(person, $event)"><option value="none">未授权</option><option value="operator" :disabled="person.status !== 'active'">操作员</option><option value="admin" :disabled="person.status !== 'active'">管理员</option></select></div></div></section>
    </template>
  </div>
  <Transition name="modal">
  <div v-if="confirmation && preview" class="modal-backdrop" @click.self="!busy && (confirmation = false)"><section class="panel modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title"><h2 id="confirm-title" class="panel-title">确认发送</h2><p>{{ preview.rows.length }} 人 · 每人{{ preview.delta > 0 ? '加' : '扣' }} {{ Math.abs(preview.delta) }} 分</p><p class="reason-box">{{ preview.reason }}</p><div v-for="row in preview.rows" :key="row.person.id" class="confirm-total"><EmployeeAvatar :src="row.person.avatar_url" :name="row.person.name" size="small" /><span>{{ row.person.name }}</span><b>{{ row.before_total }} → {{ row.final_total }} 分</b><small v-if="row.override_total !== null">手动覆盖</small></div><p>{{ preview.recipients.length }} 位通知对象 · {{ preview.message_count }} 条卡片</p><p class="hint">确认后记分生效，失败通知可重试。</p><div class="modal-actions"><button :disabled="busy" @click="confirmation = false">返回</button><button class="primary-button" :class="{ busy }" :disabled="busy || !validPreview" @click="commit">{{ busy ? '正在提交…' : '确认发送' }}</button></div></section></div></Transition>
  <Transition name="modal">
  <div v-if="detail" class="modal-backdrop" @click.self="!busy && closeDetail()">
    <section class="panel modal wide-modal" role="dialog" aria-modal="true" aria-labelledby="detail-title">
      <div class="flex-head"><h2 id="detail-title" class="panel-title">发送及撤回结果</h2><button aria-label="关闭发送结果" :disabled="busy" @click="closeDetail">×</button></div>
      <div class="modal-section-title">逐人积分状态</div>
      <div class="score-results" aria-label="逐人积分状态">
        <div v-for="row in detailScoreRows" :key="row.person.id" class="score-result">
          <div class="score-person"><EmployeeAvatar :src="row.person.avatar_url" :name="row.person.name" size="small" /><b>{{ row.person.name }}</b><span class="score-state" :class="{ cancelled: row.score?.cancelled }">{{ row.score ? row.score.cancelled ? '记分已作废' : '积分有效' : '积分状态待更新' }}</span></div>
          <div class="score-values"><span>发送时总分 <b>{{ row.originalTotal }}</b> 分</span><span v-if="row.score">{{ detail.snapshot.month }} 当前总分 <b>{{ row.score.current_total }}</b> 分</span></div>
          <small v-if="row.score?.cancelled_at">作废时间：{{ timeLabel(row.score.cancelled_at) }}</small>
        </div>
      </div>
      <p v-if="resultSummary(detail.statuses, statusLabels)" class="hint">{{ resultSummary(detail.statuses, statusLabels) }}</p>
      <div v-if="resultSummary(detail.recall_statuses, recallLabels) || detail.recall_available" class="recall-toolbar"><p v-if="resultSummary(detail.recall_statuses, recallLabels)" class="hint">{{ resultSummary(detail.recall_statuses, recallLabels) }}</p><button v-if="detail.recall_available" class="recall-button" :disabled="busy" @click="askBatchRecall(detail)">撤回本批卡片 · {{ detail.recall_available }}</button></div>
      <div class="modal-section-title">通知明细</div>
      <div class="deliveries"><div v-for="delivery in detail.deliveries" :key="delivery.id" class="delivery-row">
        <div><b>{{ detail.snapshot.rows.find(r => r.person.id === delivery.person_id)?.person.name }} → {{ delivery.recipient_name }}</b><small>{{ delivery.message_id || delivery.last_error || '等待后台发送' }}</small><p v-if="delivery.recall_error" class="error-text">{{ delivery.recall_error }}</p><small v-if="delivery.recalled_at">撤回确认时间：{{ timeLabel(delivery.recalled_at) }}</small><small v-else-if="recallStillAvailable(delivery)">可申请至 {{ timeLabel(delivery.recall_deadline) }}</small></div>
        <span>{{ delivery.recall_status ? recallLabels[delivery.recall_status] : statusLabels[delivery.status] }}</span>
        <button v-if="recallStillAvailable(delivery)" class="recall-button" :disabled="busy" @click="recallConfirmation = { batchId: detail.id, deliveryId: delivery.id, count: 1, names: delivery.recipient_name }">{{ delivery.recall_status ? '重试撤回' : '撤回' }}</button>
        <button v-else-if="delivery.status === 'failed'" :disabled="busy" @click="retry(delivery.id)">重试发送</button>
        <small v-else-if="delivery.status === 'sent' && !delivery.recall_status && !recallStillAvailable(delivery)">已超撤回时限</small>
      </div></div>
      <div class="pagination"><template v-if="detail.total > 100"><button :disabled="busy || detail.page <= 1" @click="action(() => loadDetail(detail!.id, detail!.page - 1))">上一页</button><small>{{ detail.page }} / {{ Math.max(1, Math.ceil(detail.total / 100)) }}</small><button :disabled="busy || detail.page * 100 >= detail.total" @click="action(() => loadDetail(detail!.id, detail!.page + 1))">下一页</button></template><button :disabled="busy" @click="action(() => loadDetail(detail!.id, detail!.page))">刷新</button></div>
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
      <div class="modal-actions"><button :disabled="busy" @click="recallConfirmation = null">取消</button><button class="primary-button" :class="{ busy }" :disabled="busy" @click="confirmRecall">{{ busy ? '正在提交…' : '确认撤回' }}</button></div>
    </section>
  </div>
</Transition>
</template>
