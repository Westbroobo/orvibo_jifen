<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, downloadFile } from '../api'
import type { ScoreLedgerResponse } from '../types'
import { recordTime } from '../historyPresentation'
import DepartmentTreeSelect from './DepartmentTreeSelect.vue'
import EmployeeAvatar from './EmployeeAvatar.vue'

const props = defineProps<{ currentMonth: string }>()
function currentMonth() {
  const parts = new Intl.DateTimeFormat('en', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit' }).formatToParts(new Date())
  return `${parts.find(p => p.type === 'year')!.value}-${parts.find(p => p.type === 'month')!.value}`
}
const month = ref(props.currentMonth || currentMonth())
const query = ref(''), departmentId = ref(''), operation = ref('all'), status = ref('all'), page = ref(1)
const data = ref<ScoreLedgerResponse | null>(null)
const loading = ref(false), error = ref('')
const exporting = ref(false), exportError = ref('')
const expandedReasons = ref(new Set<string>())
const panel = ref<HTMLElement | null>(null), scroller = ref<HTMLElement | null>(null), panelHeight = ref(480)
const pages = computed(() => Math.max(1, Math.ceil((data.value?.total ?? 0) / 20)))
const departments = computed(() => data.value?.month === month.value ? data.value.departments : [])
const rows = computed(() => (data.value?.items ?? []).map(item => ({ ...item, time: recordTime(item.created_at) })))
let pending: AbortController | undefined
let exportRequest: AbortController | undefined
let debounce: ReturnType<typeof setTimeout> | undefined
let observer: ResizeObserver | undefined
let resizeFrame: number | undefined
let sequence = 0
function filterParams() {
  return new URLSearchParams({ month: month.value, q: query.value.trim(), department_id: departmentId.value,
    operation: operation.value, status: status.value })
}
async function exportExcel() {
  if (exporting.value || loading.value || !data.value?.total) return
  const request = new AbortController()
  exportRequest = request; exporting.value = true; exportError.value = ''
  try {
    await downloadFile(`/score-ledgers/export?${filterParams()}`, `积分明细_${month.value}.xlsx`, request.signal)
  } catch (e) {
    if (!request.signal.aborted) exportError.value = e instanceof Error ? e.message : '导出失败，请稍后重试'
  } finally {
    if (exportRequest === request) { exporting.value = false; exportRequest = undefined }
  }
}
async function load() {
  clearTimeout(debounce); pending?.abort()
  const request = new AbortController(), version = ++sequence
  pending = request; loading.value = true; error.value = ''
  if (!/^[0-9]{4}-(0[1-9]|1[0-2])$/.test(month.value)) {
    data.value = null; error.value = '请选择记分月份'; loading.value = false; return
  }
  try {
    const params = filterParams()
    params.set('page', String(page.value))
    const result = await api<ScoreLedgerResponse>(`/score-ledgers?${params}`, 'GET', undefined, request.signal)
    if (request.signal.aborted || version !== sequence) return
    data.value = result; page.value = result.page; expandedReasons.value = new Set()
    await nextTick()
    if (scroller.value) scroller.value.scrollTop = 0
  } catch (e) {
    if (!request.signal.aborted && version === sequence) {
      data.value = null; error.value = e instanceof Error ? e.message : '积分明细加载失败'
    }
  } finally { if (version === sequence) loading.value = false }
}
watch(month, () => { departmentId.value = '' })
watch([month, query, departmentId, operation, status], (values, previous) => {
  exportRequest?.abort(); exportRequest = undefined; exporting.value = false; exportError.value = ''
  page.value = 1; pending?.abort(); ++sequence; clearTimeout(debounce); loading.value = true; error.value = ''
  debounce = setTimeout(load, values[1] !== previous[1] ? 250 : 0)
})
function changePage(value: number) { page.value = value; void load() }
function reset() {
  month.value = currentMonth(); query.value = ''; departmentId.value = ''; operation.value = 'all'; status.value = 'all'; page.value = 1
  void nextTick(load)
}
function toggleReason(id: string) {
  const ids = new Set(expandedReasons.value)
  ids.has(id) ? ids.delete(id) : ids.add(id)
  expandedReasons.value = ids
}
function fitPanel() {
  if (!panel.value) return
  const fixed = [...panel.value.children].filter(child => child !== scroller.value)
    .reduce((height, child) => height + child.getBoundingClientRect().height, 0)
  panelHeight.value = Math.floor(Math.max(fixed + 202, window.innerHeight - panel.value.getBoundingClientRect().top - window.scrollY - 16))
}
function scheduleResize() {
  if (resizeFrame !== undefined) cancelAnimationFrame(resizeFrame)
  resizeFrame = requestAnimationFrame(fitPanel)
}
onMounted(() => {
  void load(); observer = new ResizeObserver(scheduleResize)
  const outer = panel.value?.closest('.page')
  if (outer) observer.observe(outer)
  if (panel.value) { observer.observe(panel.value); for (const child of panel.value.children) if (child !== scroller.value) observer.observe(child) }
  window.addEventListener('resize', scheduleResize); scheduleResize()
})
onUnmounted(() => {
  ++sequence; pending?.abort(); exportRequest?.abort(); clearTimeout(debounce); observer?.disconnect()
  window.removeEventListener('resize', scheduleResize)
  if (resizeFrame !== undefined) cancelAnimationFrame(resizeFrame)
})
</script>

<template>
  <main class="ledger-page" aria-label="积分明细">
    <header class="ledger-heading"><h1 class="panel-title">积分明细</h1><div class="ledger-actions"><button type="button" class="ledger-export" :disabled="loading || exporting || !data?.total" title="导出当前筛选条件下的全部明细" @click="exportExcel"><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M10 2v10m-4-4 4 4 4-4M3 12v5h14v-5" /></svg>{{ exporting ? '导出中…' : '导出 Excel' }}</button><button type="button" :disabled="loading" @click="load">{{ loading ? '刷新中…' : '刷新' }}</button></div></header>
    <div v-if="exportError" class="ledger-error ledger-export-error" role="alert">{{ exportError }}<button type="button" :disabled="loading || exporting || !data?.total" @click="exportExcel">重试导出</button></div>
    <div class="ledger-summary" aria-live="polite">
      <div><span>记录数</span><b>{{ loading || !data ? '—' : data.total }}<small> 笔</small></b></div>
      <div><span>有效加分合计</span><b class="plus-text">{{ loading || !data ? '—' : `+${data.summary.plus_total}` }}<small> 分</small></b></div>
      <div><span>有效扣分合计</span><b class="minus-text">{{ loading || !data ? '—' : data.summary.minus_total }}<small> 分</small></b></div>
    </div>
    <section ref="panel" class="panel ledger-panel" :style="{ height: `${panelHeight}px` }" aria-label="积分流水">
      <div class="ledger-filters">
        <input v-model="month" type="month" aria-label="记分月份">
        <input v-model="query" type="search" aria-label="搜索记分员工" placeholder="搜索姓名" autocomplete="off" maxlength="200">
        <DepartmentTreeSelect v-model="departmentId" class="ledger-department" :departments="departments" />
        <select v-model="operation" aria-label="筛选加扣分类型"><option value="all">全部类型</option><option value="plus">加分</option><option value="minus">扣分</option></select>
        <select v-model="status" aria-label="筛选记分状态"><option value="all">全部状态</option><option value="valid">有效</option><option value="cancelled">已作废</option></select>
        <button type="button" @click="reset">重置</button>
      </div>
      <p class="ledger-hint">按记分时部门查询；前后总分为当时记账值，合计仅含有效加扣分。</p>
      <div v-if="error" class="ledger-error" role="alert">{{ error }}<button type="button" @click="load">重试</button></div>
      <div ref="scroller" class="ledger-scroller" role="table" aria-label="逐笔积分明细" :aria-busy="loading" tabindex="0">
        <div class="ledger-table-head" role="rowgroup"><div class="ledger-row" role="row"><span role="columnheader">序号</span><span role="columnheader">员工 / 记分时部门</span><span role="columnheader">加减分</span><span role="columnheader">记分前</span><span role="columnheader">记分后</span><span role="columnheader">原因</span><span role="columnheader">时间 / 操作人</span><span role="columnheader">状态</span></div></div>
        <div role="rowgroup">
          <div v-if="loading || !rows.length" role="row"><div role="cell" aria-colspan="8" class="ledger-empty"><span role="status">{{ loading ? '正在加载积分明细…' : error ? '明细暂不可用' : '暂无匹配的积分明细' }}</span></div></div>
          <template v-else><div v-for="(row, index) in rows" :key="row.id" class="ledger-row" :class="{ cancelled: row.cancelled }" role="row">
            <span role="cell" class="ledger-index">{{ (page - 1) * 20 + index + 1 }}</span>
            <div role="cell" class="ledger-person"><EmployeeAvatar :src="row.avatar_url" :name="row.person_name" size="small" /><div><b>{{ row.person_name }}</b><small>{{ row.paths.map(p => p.names.join(' / ')).join('；') || '直属企业' }}</small></div></div>
            <div role="cell" class="ledger-delta" :class="row.delta > 0 ? 'plus-text' : 'minus-text'"><b>{{ row.delta > 0 ? '+' : '' }}{{ row.delta }}</b></div>
            <div role="cell" class="ledger-before"><span class="mobile-label">记分前 </span>{{ row.before_total }}</div>
            <div role="cell" class="ledger-after"><span class="mobile-label">记分后 </span><b>{{ row.final_total }}</b><small v-if="row.override_total !== null" class="ledger-override">手动覆盖</small></div>
            <div role="cell" class="ledger-reason"><p :class="{ collapsed: !expandedReasons.has(row.id) && (row.reason.length > 40 || row.reason.includes('\n')) }">{{ row.reason }}</p><button v-if="row.reason.length > 40 || row.reason.includes('\n')" type="button" :aria-expanded="expandedReasons.has(row.id)" :aria-label="`${expandedReasons.has(row.id) ? '收起' : '展开'}第 ${(page - 1) * 20 + index + 1} 笔原因`" @click="toggleReason(row.id)">{{ expandedReasons.has(row.id) ? '收起' : '展开' }}</button></div>
            <div role="cell" class="ledger-time"><time :datetime="row.created_at">{{ row.time.date }}<span>{{ row.time.time }}</span></time><small>{{ row.operator_name }}</small></div>
            <div role="cell" class="ledger-state"><span :class="row.cancelled ? 'state-cancelled' : 'state-valid'" :title="row.cancelled_at ? `作废于 ${new Date(row.cancelled_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })}` : undefined">{{ row.cancelled ? '已作废' : '有效' }}</span></div>
          </div></template>
        </div>
      </div>
      <footer class="ledger-footer"><span>{{ loading ? '正在加载…' : data?.total ? `显示 ${(page - 1) * 20 + 1}–${Math.min(page * 20, data.total)} / ${data.total} 笔` : '共 0 笔记录' }}</span><div v-if="pages > 1" class="pagination"><button type="button" :disabled="loading || page <= 1" @click="changePage(page - 1)">上一页</button><span>{{ page }} / {{ pages }}</span><button type="button" :disabled="loading || page >= pages" @click="changePage(page + 1)">下一页</button></div></footer>
    </section>
  </main>
</template>

<style scoped>
.ledger-page{display:grid;gap:16px}.ledger-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:4px 0}.ledger-heading h1{margin:0}
.ledger-actions{display:flex;gap:8px;align-items:center}.ledger-export{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}.ledger-export svg{width:16px;height:16px;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}.ledger-export-error{border:1px solid var(--line);border-radius:var(--r-lg)}
.ledger-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.ledger-summary>div{padding:14px 20px;border:1px solid var(--line);border-radius:var(--r-lg);background:var(--surface)}.ledger-summary span{display:block;color:var(--muted);font-size:var(--fs-sm)}.ledger-summary b{display:block;margin-top:4px;font-family:var(--mono);font-size:22px;overflow-wrap:anywhere}.ledger-summary small{font-family:var(--sans);font-size:var(--fs-xs);font-weight:400;color:var(--muted)}
.ledger-panel{display:flex;flex-direction:column;min-height:0;padding:0;overflow:hidden}.ledger-filters{display:flex;gap:10px;flex-wrap:wrap;padding:18px 20px 10px;flex:none}.ledger-filters input,.ledger-filters select{height:40px;border-color:var(--control-line);font-size:var(--fs-sm)}.ledger-filters input[type=month]{width:154px}.ledger-filters input[type=search]{flex:1;min-width:150px}.ledger-department{flex:1;min-width:200px}.ledger-filters select{width:110px}.ledger-filters button{flex:none}.ledger-hint{flex:none;margin:0;padding:0 20px 14px;font-size:var(--fs-xs);color:var(--muted)}
.ledger-scroller{flex:1;min-height:0;overflow:auto;overscroll-behavior:contain;scrollbar-gutter:stable}.ledger-scroller:focus-visible{outline-offset:-2px}.ledger-row{display:grid;grid-template-columns:30px minmax(140px,1.2fr) 65px 65px 75px minmax(130px,1fr) 125px 60px;align-items:center;gap:14px;padding:14px 20px;border-bottom:1px solid var(--line);font-size:var(--fs-sm)}.ledger-table-head{position:sticky;top:0;z-index:1;background:var(--surface-2)}.ledger-table-head .ledger-row{padding-top:11px;padding-bottom:11px;color:var(--muted);font-size:var(--fs-xs);font-weight:600}.ledger-row:has(.ledger-person):hover{background:#FAFBFC}.ledger-index{font-family:var(--mono);color:var(--muted);text-align:center}.ledger-person{display:flex;align-items:flex-start;gap:9px;min-width:0}.ledger-person>div{min-width:0}.ledger-person b{font-weight:600}.ledger-person small{display:block;margin-top:4px;color:var(--muted);overflow-wrap:anywhere;line-height:1.6}.ledger-delta{font-family:var(--mono);font-size:15px;overflow-wrap:anywhere}.ledger-before,.ledger-after{font-family:var(--mono);overflow-wrap:anywhere}.ledger-override{display:block;font-family:var(--sans);color:var(--accent-deep);font-size:10px;margin-top:4px}.ledger-reason{min-width:0}.ledger-reason p{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.7}.ledger-reason p.collapsed{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.ledger-reason button{padding:2px 0;border:0;background:none;color:var(--accent-deep);font-size:var(--fs-xs)}.ledger-time{font-size:var(--fs-xs);color:var(--muted)}.ledger-time time{font-family:var(--mono)}.ledger-time time span,.ledger-time>small{display:block}.ledger-time>small{margin-top:4px;color:var(--text)}.ledger-state>span{display:inline-flex;padding:3px 7px;border-radius:var(--r-sm);font-size:var(--fs-xs);white-space:nowrap}.state-valid{background:var(--plus-soft);color:var(--plus-ink)}.state-cancelled{background:var(--surface-2);color:var(--muted)}.cancelled .ledger-delta b{text-decoration:line-through}.mobile-label{display:none}
.ledger-empty{text-align:center;padding:60px 20px;color:var(--muted);font-size:var(--fs-sm)}.ledger-error{flex:none;display:flex;align-items:center;gap:12px;padding:12px 20px;background:var(--minus-soft);color:var(--minus-ink);font-size:var(--fs-sm)}.ledger-footer{flex:none;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;padding:14px 20px;border-top:1px solid var(--line);font-size:var(--fs-xs);color:var(--muted)}.ledger-footer .pagination{margin:0}
@media(min-width:641px) and (max-width:1100px){.ledger-row{min-width:900px}.ledger-table-head{min-width:900px}}
@media(max-width:640px){.ledger-summary{gap:8px}.ledger-summary>div{padding:10px}.ledger-summary b{font-size:18px}.ledger-summary span{font-size:var(--fs-xs)}.ledger-filters{padding:14px 16px 10px;gap:8px}.ledger-filters input[type=month]{width:145px}.ledger-filters input[type=search]{min-width:110px}.ledger-department{flex-basis:100%}.ledger-filters select{flex:1;min-width:0;width:auto}.ledger-hint{padding:0 16px 12px}.ledger-table-head{display:none}.ledger-row{grid-template-columns:24px minmax(0,1fr) minmax(0,1fr);gap:12px;padding:14px 16px}.ledger-index{grid-column:1;grid-row:1 / span 5;align-self:start}.ledger-person{grid-column:2 / -1}.ledger-delta{grid-column:2}.ledger-state{grid-column:3;grid-row:2;text-align:right}.ledger-before{grid-column:2}.ledger-after{grid-column:3;text-align:right}.mobile-label{display:inline;font-family:var(--sans);font-size:var(--fs-xs);color:var(--muted)}.ledger-reason{grid-column:2 / -1}.ledger-time{grid-column:2 / -1;display:flex;align-items:center;gap:10px;flex-wrap:wrap}.ledger-time time span{display:inline;margin-left:6px}.ledger-time>small{margin:0}.ledger-footer{padding:14px 16px}}
</style>
