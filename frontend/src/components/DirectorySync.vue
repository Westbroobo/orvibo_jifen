<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'
import type { SyncSchedule } from '../types'

const props = defineProps<{ busy: boolean }>()
const emit = defineEmits<{ synced: [] }>()
const schedule = ref<SyncSchedule | null>(null)
const editing = ref(false)
const working = ref(false)
const error = ref('')
const enabled = ref(true)
const intervalDays = ref(1)
const syncTime = ref('02:00')
const disabled = computed(() => props.busy || working.value || !schedule.value)
const running = computed(() => schedule.value?.status === 'running')
const queued = computed(() => schedule.value?.status === 'queued')
const recovering = computed(() => schedule.value?.status === 'recovering')
const stateLabel = computed(() => !schedule.value ? (error.value ? '加载失败' : '加载中')
  : running.value ? '同步中' : queued.value ? '等待同步' : recovering.value ? '等待恢复'
    : schedule.value.status === 'retry' ? '等待重试' : schedule.value.enabled ? '定时已开启' : '定时已关闭')
let timer: ReturnType<typeof setInterval> | undefined
let sequence = 0
let disposed = false

const timeLabel = (value: string | null | undefined, empty: string) => value
  ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : empty

function applyStatus(value: SyncSchedule) {
  const previous = schedule.value
  schedule.value = value
  if (previous && (previous.directory_version !== value.directory_version || previous.last_sync_at !== value.last_sync_at)) emit('synced')
}

async function loadStatus(initial = false) {
  if (working.value || props.busy && !initial) return
  const request = ++sequence
  try {
    const value = await api<SyncSchedule>('/admin/directory/schedule')
    if (disposed || request !== sequence) return
    applyStatus(value)
    error.value = ''
  } catch (e) {
    if (!disposed && request === sequence) error.value = e instanceof Error ? e.message : '无法获取同步状态'
  }
}

function openSettings() {
  if (!schedule.value) return
  enabled.value = schedule.value.enabled
  intervalDays.value = schedule.value.interval_days
  syncTime.value = schedule.value.time
  editing.value = !editing.value
  error.value = ''
}

async function saveSettings() {
  if (disabled.value) return
  if (!Number.isInteger(intervalDays.value) || intervalDays.value < 1 || intervalDays.value > 365) {
    error.value = '同步间隔请填写 1 至 365 天'; return
  }
  if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(syncTime.value)) {
    error.value = '请选择同步时间'; return
  }
  working.value = true; error.value = ''; ++sequence
  try {
    const value = await api<SyncSchedule>('/admin/directory/schedule', 'PUT', {
      enabled: enabled.value, interval_days: intervalDays.value, time: syncTime.value,
    })
    if (!disposed) { applyStatus(value); editing.value = false }
  } catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : '保存失败' }
  finally { working.value = false }
}

async function syncNow() {
  if (disabled.value) return
  working.value = true; error.value = ''; ++sequence
  try {
    await api('/admin/directory/sync', 'POST')
    const value = await api<SyncSchedule>('/admin/directory/schedule')
    if (!disposed) applyStatus(value)
  } catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : '同步申请失败' }
  finally { working.value = false }
}

onMounted(() => { void loadStatus(true); timer = setInterval(() => { void loadStatus() }, 15000) })
onUnmounted(() => { disposed = true; ++sequence; clearInterval(timer) })
</script>

<template>
  <section class="panel directory-sync" aria-labelledby="directory-sync-title">
  <div class="sync-heading">
    <div class="sync-title"><h2 id="directory-sync-title">人员同步</h2><span class="sync-state" role="status" :class="{ active: schedule?.enabled, pulse: running || queued || recovering }"><i aria-hidden="true"></i>{{ stateLabel }}</span></div>
    <div class="sync-actions">
      <button type="button" :disabled="disabled" :aria-expanded="editing" aria-controls="sync-settings" @click="openSettings"><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M4 5h12M4 10h12M4 15h12" /><circle cx="7" cy="5" r="2" /><circle cx="13" cy="10" r="2" /><circle cx="8" cy="15" r="2" /></svg>同步设置</button>
      <button type="button" class="primary-button sync-now" :disabled="disabled || running || queued" :aria-busy="running" @click="syncNow"><svg viewBox="0 0 20 20" fill="none" aria-hidden="true" :class="{ spinning: running }"><path d="M16.5 8a7 7 0 0 0-12-3L2 8m0-4v4h4M3.5 12a7 7 0 0 0 12 3l2.5-3m0 4v-4h-4" /></svg>{{ running ? '同步中…' : queued ? '等待同步…' : '同步人员' }}</button>
    </div>
  </div>
  <div class="sync-status" aria-live="polite">
    <div><span>最近同步</span><strong>{{ timeLabel(schedule?.last_sync_at, schedule ? '尚未同步' : '加载中…') }}</strong></div>
    <div><span>下次同步</span><strong>{{ timeLabel(schedule?.next_sync_at, schedule ? '未开启定时同步' : '加载中…') }}</strong></div>
    <div><span>同步计划 · 北京时间</span><strong>{{ schedule ? schedule.enabled ? `每 ${schedule.interval_days} 天 · ${schedule.time}` : '仅手动同步' : '加载中…' }}</strong></div>
  </div>
  <form v-if="editing" id="sync-settings" class="sync-settings" @submit.prevent="saveSettings">
    <fieldset :disabled="disabled">
      <label class="sync-toggle"><input v-model="enabled" type="checkbox">定时同步</label>
      <div class="sync-fields">
        <label>同步频率<span class="sync-interval">每 <input v-model.number="intervalDays" :disabled="!enabled" aria-label="同步间隔天数" type="number" min="1" max="365" step="1" required> 天</span></label>
        <label>同步时间（北京时间）<input v-model="syncTime" :disabled="!enabled" aria-label="同步时间" type="time" step="60" required></label>
        <div class="sync-actions"><button type="button" @click="editing = false">取消</button><button type="submit" class="primary-button sync-save">{{ working ? '保存中…' : '保存设置' }}</button></div>
      </div>
    </fieldset>
  </form>
  <p v-if="error" class="error-text" role="alert">{{ error }}</p>
  <p v-if="schedule?.last_sync_error" class="error-text">{{ schedule.last_sync_error }}<span v-if="schedule.retry_at"> · 下次重试：{{ timeLabel(schedule.retry_at, '') }}</span></p>
  </section>
</template>

<style scoped>
.directory-sync{padding:20px 24px}
.sync-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:18px}
.sync-title{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.sync-title h2{font-family:var(--sans);font-size:14px;font-weight:600;margin:0}
.sync-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.sync-actions button{display:inline-flex;align-items:center;justify-content:center;gap:6px;width:auto;white-space:nowrap;font-size:var(--fs-sm);padding:8px 12px;min-height:38px}
.sync-actions svg{width:15px;height:15px;flex:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
.sync-actions svg.spinning{animation:spin 1s linear infinite}
.sync-status{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;color:var(--muted);font-size:var(--fs-xs);background:var(--surface-2);border-radius:var(--r-md);padding:14px 16px}
.sync-status>div{min-width:0}.sync-status>div+div{border-left:1px solid var(--line);padding-left:16px}
.sync-status span{display:block;margin-bottom:4px}
.sync-status strong{display:block;font-family:var(--mono);font-size:var(--fs-sm);font-weight:400;color:var(--text);overflow-wrap:anywhere}
.sync-state{display:inline-flex;align-items:center;gap:5px;color:var(--muted);font-size:var(--fs-xs);background:var(--surface-2);border-radius:var(--r-sm);padding:3px 8px}
.sync-state.active{background:var(--accent-soft);color:var(--accent-deep)}
.sync-state i{width:5px;height:5px;border-radius:50%;background:currentColor}
.sync-settings{border-top:1px solid var(--line);padding-top:16px;margin-top:16px}
.sync-toggle{display:flex;align-items:center;gap:8px;font-size:var(--fs-sm);margin-bottom:12px}
.sync-fields{display:flex;align-items:flex-end;gap:12px 16px;flex-wrap:wrap}
.sync-fields>label{font-size:var(--fs-xs);color:var(--muted)}
.sync-fields input{margin-top:4px}
.sync-interval{display:flex;align-items:center;gap:8px;font-size:var(--fs-sm);height:calc(var(--fs-md) * 1.65 + var(--sp-2) * 2 + 2px);margin-top:4px}
.sync-interval input{width:75px;margin:0}
.sync-fields>label>input{display:block;width:150px}
.sync-fields .sync-actions{padding-bottom:4px}
.directory-sync>.error-text{margin:12px 0 0}
@media(max-width:820px){.sync-status{grid-template-columns:repeat(2,minmax(0,1fr))}.sync-status>div:last-child{grid-column:1 / -1;border-left:0;border-top:1px solid var(--line);padding:10px 0 0}}
@media(max-width:640px){.directory-sync{padding:18px 16px}.sync-heading{align-items:flex-start;gap:14px}.sync-heading>.sync-actions{width:100%}.sync-heading>.sync-actions button{flex:1}.sync-status{grid-template-columns:1fr;gap:10px;padding:12px}.sync-status>div+div{border-left:0;border-top:1px solid var(--line);padding:10px 0 0}.sync-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.sync-fields>label>input{width:100%}.sync-interval input{width:55px}.sync-fields .sync-actions{grid-column:1 / -1;justify-content:flex-end;padding:0}}
</style>
