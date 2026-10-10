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
  <div class="panel-head flex-head sync-heading">
    <h1 class="panel-title">权限管理</h1>
    <div class="sync-actions">
      <button :disabled="disabled" :aria-expanded="editing" aria-controls="sync-settings" @click="openSettings">同步设置</button>
      <button :disabled="disabled || running || queued" @click="syncNow">{{ running ? '同步中…' : queued ? '等待同步…' : '同步人员' }}</button>
    </div>
  </div>
  <div class="sync-status" aria-live="polite">
    <span>最近同步：{{ timeLabel(schedule?.last_sync_at, schedule ? '尚未同步' : '加载中…') }}</span>
    <span>下次同步：{{ timeLabel(schedule?.next_sync_at, schedule ? '未开启定时同步' : '加载中…') }}</span>
    <span v-if="running || queued || recovering" class="sync-state">{{ running ? '同步中' : recovering ? '等待恢复同步' : '等待同步' }}</span>
  </div>
  <form v-if="editing" id="sync-settings" class="sync-settings" @submit.prevent="saveSettings">
    <fieldset :disabled="disabled">
      <label class="sync-toggle"><input v-model="enabled" type="checkbox">定时同步</label>
      <div class="sync-fields">
        <label>同步频率<span class="sync-interval">每 <input v-model.number="intervalDays" :disabled="!enabled" aria-label="同步间隔天数" type="number" min="1" max="365" step="1" required> 天</span></label>
        <label>同步时间（北京时间）<input v-model="syncTime" :disabled="!enabled" aria-label="同步时间" type="time" step="60" required></label>
        <div class="sync-actions"><button type="button" @click="editing = false">取消</button><button type="submit" class="sync-save">{{ working ? '保存中…' : '保存' }}</button></div>
      </div>
    </fieldset>
  </form>
  <p v-if="error" class="error-text" role="alert">{{ error }}</p>
  <p v-if="schedule?.last_sync_error" class="error-text">{{ schedule.last_sync_error }}<span v-if="schedule.retry_at"> · 下次重试：{{ timeLabel(schedule.retry_at, '') }}</span></p>
</template>

<style scoped>
.sync-heading{gap:12px;flex-wrap:wrap;margin-bottom:14px}
.sync-heading .panel-title{margin:0}
.sync-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.sync-actions button{white-space:nowrap;font-size:var(--fs-xs)}
.sync-status{display:flex;gap:5px 24px;flex-wrap:wrap;margin-bottom:16px;color:var(--muted);font-size:var(--fs-xs)}
.sync-state{color:var(--accent-deep)}
.sync-settings{border:1px solid var(--line);border-radius:var(--r-md);background:var(--surface-2);padding:14px 16px;margin-bottom:16px}
.sync-toggle{display:flex;align-items:center;gap:7px;font-size:var(--fs-sm);margin-bottom:12px}
.sync-fields{display:flex;align-items:flex-end;gap:12px 20px;flex-wrap:wrap}
.sync-fields>label{font-size:var(--fs-xs);color:var(--muted)}
.sync-fields input{margin-top:5px}
.sync-interval{display:flex;align-items:center;gap:8px;font-size:var(--fs-sm);height:41px;margin-top:5px}
.sync-interval input{width:75px;margin:0}
.sync-fields>label>input{display:block;width:150px}
.sync-fields .sync-actions{padding-bottom:3px}
.sync-save{color:var(--accent-deep);border-color:var(--accent)}
</style>
