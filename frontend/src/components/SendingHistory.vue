<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { HistoryItem } from '../types'
import { notificationNotes, notificationState, recordTime } from '../historyPresentation'

const props = defineProps<{ items: HistoryItem[]; total: number; page: number; loading: boolean; busy: boolean }>()
const emit = defineEmits<{ refresh: []; 'change-page': [page: number]; detail: [id: string]; recall: [item: HistoryItem] }>()
const pageSize = 20
const pages = computed(() => Math.max(1, Math.ceil(props.total / pageSize)))
const rows = computed(() => props.items.map(item => ({
  item, state: notificationState(item.message_count, item.statuses, item.recall_statuses),
  notes: notificationNotes(item.statuses, item.recall_statuses), time: recordTime(item.created_at),
})))
const panel = ref<HTMLElement | null>(null)
const scroller = ref<HTMLElement | null>(null)
const panelHeight = ref(480)
let observer: ResizeObserver | undefined
let resizeFrame: number | undefined
function fitPanel() {
  if (!panel.value) return
  const fixed = [...panel.value.children].filter(child => child !== scroller.value)
    .reduce((height, child) => height + child.getBoundingClientRect().height, 0)
  const top = panel.value.getBoundingClientRect().top + window.scrollY
  panelHeight.value = Math.floor(Math.max(fixed + 202, window.innerHeight - top - 16))
}
function scheduleResize() {
  if (resizeFrame !== undefined) cancelAnimationFrame(resizeFrame)
  resizeFrame = requestAnimationFrame(fitPanel)
}
watch(() => props.page, async () => { await nextTick(); if (scroller.value) scroller.value.scrollTop = 0 })
onMounted(() => {
  observer = new ResizeObserver(scheduleResize)
  if (panel.value) { observer.observe(panel.value); const outer = panel.value.closest('.page'); if (outer) observer.observe(outer) }
  window.addEventListener('resize', scheduleResize)
  scheduleResize()
})
onUnmounted(() => { observer?.disconnect(); window.removeEventListener('resize', scheduleResize); if (resizeFrame !== undefined) cancelAnimationFrame(resizeFrame) })
</script>

<template>
  <main class="sending-history" aria-label="发送记录">
    <header class="history-heading">
      <div><h1 class="panel-title">发送记录</h1><span>共 <b>{{ total }}</b> 次操作</span></div>
      <button type="button" :disabled="busy || loading" :aria-busy="loading" @click="emit('refresh')"><svg viewBox="0 0 20 20" fill="none" aria-hidden="true" :class="{ spinning: loading }"><path d="M16.5 8a7 7 0 0 0-12-3L2 8m0-4v4h4M3.5 12a7 7 0 0 0 12 3l2.5-3m0 4v-4h-4" /></svg>{{ loading ? '刷新中…' : '刷新' }}</button>
    </header>
    <section ref="panel" class="panel history-panel" :style="{ height: `${panelHeight}px` }" aria-label="加减分记录">
      <div ref="scroller" class="history-table" role="table" aria-label="加减分记录列表" :aria-busy="loading" tabindex="0">
        <div class="history-table-head" role="rowgroup"><div class="history-row" role="row"><span role="columnheader">序号</span><span role="columnheader">记分对象 / 原因</span><span role="columnheader">每人分值</span><span role="columnheader">通知状态</span><span role="columnheader">发送时间 / 操作人</span><span role="columnheader">操作</span></div></div>
        <div role="rowgroup">
          <div v-if="!rows.length" role="row"><div role="cell" aria-colspan="6"><div class="history-empty" role="status"><svg viewBox="0 0 40 40" fill="none" aria-hidden="true"><path d="M10 5h15l6 6v24H10zM25 5v7h6M15 19h11M15 25h8" /></svg>{{ loading ? '正在加载记录…' : '暂无发送记录' }}</div></div></div>
          <div v-for="(row, index) in rows" :key="row.item.id" class="history-row history-data-row" role="row">
            <span role="cell" class="history-index">{{ (page - 1) * pageSize + index + 1 }}</span>
            <div role="cell" class="history-content"><div class="history-names"><b :title="row.item.names.join('、')">{{ row.item.names.join('、') || '未记录人员' }}</b><span v-if="row.item.names.length > 1">{{ row.item.names.length }} 人</span></div><p :title="row.item.reason">{{ row.item.reason }}</p></div>
            <div role="cell" class="history-score"><b class="signed-number" :class="row.item.delta > 0 ? 'plus-text' : 'minus-text'">{{ row.item.delta > 0 ? '+' : '' }}{{ row.item.delta }}<small> 分</small></b><small v-if="row.item.cancelled_scores" class="history-cancelled">{{ row.item.cancelled_scores === row.item.names.length ? '记分已作废' : `${row.item.cancelled_scores} / ${row.item.names.length} 人已作废` }}</small></div>
            <div role="cell" class="history-status"><span class="result-badge" :class="[`tone-${row.state.tone}`, { pulse: row.state.pulse }]">{{ row.state.text }}</span><small>{{ row.item.statuses.sent ?? 0 }} / {{ row.item.message_count }} 条已发送</small><small v-if="row.item.recall_statuses?.recalled">{{ row.item.recall_statuses.recalled }} / {{ row.item.message_count }} 条已撤回</small><small v-for="note in row.notes" :key="note.text" :class="`result-text-${note.tone}`">{{ note.text }}</small></div>
            <div role="cell" class="history-time"><time :datetime="row.item.created_at">{{ row.time.date }}<span>{{ row.time.time }}</span></time><small>{{ row.item.operator_name }}</small></div>
            <div role="cell" class="history-actions"><button type="button" class="history-view" :disabled="busy || loading" :aria-label="`查看第 ${(page - 1) * pageSize + index + 1} 次发送结果`" @click="emit('detail', row.item.id)">查看结果</button><button v-if="row.item.recall_available" type="button" class="recall-button" :disabled="busy || loading" :aria-label="`整批撤回第 ${(page - 1) * pageSize + index + 1} 次发送`" @click="emit('recall', row.item)">整批撤回</button></div>
          </div>
        </div>
      </div>
      <footer class="history-footer"><span>{{ total ? `显示 ${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)} / ${total} 次` : '共 0 次操作' }}</span><div v-if="pages > 1" class="pagination"><button type="button" :disabled="busy || loading || page <= 1" @click="emit('change-page', page - 1)">上一页</button><span>{{ page }} / {{ pages }}</span><button type="button" :disabled="busy || loading || page >= pages" @click="emit('change-page', page + 1)">下一页</button></div></footer>
    </section>
  </main>
</template>

<style scoped>
.sending-history{display:grid;gap:16px}
.history-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:4px 0}
.history-heading>div{display:flex;align-items:center;gap:16px;min-width:0}.history-heading .panel-title{margin:0}
.history-heading span{font-size:var(--fs-sm);color:var(--muted)}.history-heading span b{font-family:var(--mono);color:var(--text)}
.history-heading button{display:flex;align-items:center;gap:6px;white-space:nowrap}.history-heading svg{width:15px;height:15px;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}.spinning{animation:spin 1s linear infinite}
.history-panel{display:flex;flex-direction:column;padding:0;overflow:hidden;min-height:0}
.history-table{flex:1;min-height:0;overflow:auto;overscroll-behavior:contain;scrollbar-gutter:stable;scroll-padding-top:42px}.history-table:focus-visible{outline-offset:-2px}
.history-row{display:grid;grid-template-columns:32px minmax(0,1fr) 92px 140px 138px 88px;gap:18px;align-items:center;padding:16px 22px;font-size:var(--fs-sm);border-bottom:1px solid var(--line)}
.history-table-head{position:sticky;top:0;z-index:1;background:var(--surface-2)}.history-table-head .history-row{padding-top:11px;padding-bottom:11px;color:var(--muted);font-size:var(--fs-xs);font-weight:600}.history-table-head [role=columnheader]:first-child{text-align:center}
.history-data-row:hover{background:#FAFBFC}.history-index{font-family:var(--mono);font-variant-numeric:tabular-nums;color:var(--muted);text-align:center}
.history-content{min-width:0}.history-names{display:flex;align-items:flex-start;gap:8px}.history-names b{min-width:0;overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;line-height:1.65;font-weight:600}.history-names>span{flex:none;white-space:nowrap;padding:1px 6px;background:var(--surface-2);border-radius:var(--r-sm);font-size:var(--fs-xs);color:var(--muted)}
.history-content p{margin:5px 0 0;color:var(--muted);font-size:var(--fs-xs);line-height:1.7;overflow-wrap:anywhere;white-space:pre-wrap;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.history-score{display:flex;flex-direction:column;gap:5px;min-width:0}.history-score>b{font-size:16px;font-weight:700;white-space:normal;overflow-wrap:anywhere}.history-score>b small{font-family:var(--sans);font-weight:400;font-size:var(--fs-xs);white-space:nowrap}.history-cancelled{color:var(--muted);line-height:1.6}
.history-status{display:flex;align-items:flex-start;flex-direction:column;gap:5px;min-width:0;color:var(--muted)}.history-status>small{font-size:var(--fs-xs);line-height:1.5}
.history-time{min-width:0;font-size:var(--fs-xs);color:var(--muted)}.history-time time{font-family:var(--mono);display:block;line-height:1.6}.history-time time span{display:block}.history-time>small{display:block;color:var(--text);margin-top:4px;overflow-wrap:anywhere}
.history-actions{display:flex;flex-direction:column;align-items:stretch;gap:8px}.history-actions button{padding:7px 9px;font-size:var(--fs-xs);white-space:nowrap}.history-view{color:var(--text);background:var(--surface-2)}
.history-empty{display:flex;flex-direction:column;align-items:center;gap:12px;padding:64px 16px;font-size:var(--fs-sm);color:var(--muted)}.history-empty svg{width:38px;height:38px;stroke:var(--control-line);stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
.history-footer{flex:none;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;padding:14px 22px;font-size:var(--fs-xs);color:var(--muted);border-top:1px solid var(--line)}.history-footer .pagination{margin:0}
@media(max-width:820px){.history-row{grid-template-columns:24px minmax(0,1fr) 76px 110px 104px;gap:12px;padding:14px 16px}.history-table-head [role=columnheader]:last-child{display:none}.history-actions{grid-column:2 / -1;flex-direction:row;justify-content:flex-end}.history-actions button{min-width:88px}}
@media(max-width:640px){.history-heading>div{align-items:flex-start;flex-direction:column;gap:4px}.history-table-head{display:none}.history-row{grid-template-columns:24px minmax(0,1fr) 82px;gap:12px}.history-index{grid-column:1;grid-row:1 / span 3;align-self:start;padding-top:2px}.history-content{grid-column:2 / -1}.history-score{grid-column:3;grid-row:2;align-self:start;text-align:right}.history-status{grid-column:2;grid-row:2}.history-time{grid-column:2;grid-row:3;align-self:center}.history-time time span{display:inline;margin-left:6px}.history-actions{grid-column:2 / -1;justify-content:flex-end}.history-footer{padding:14px 16px}}
@media(max-width:360px){.history-row{gap:10px;padding:14px 12px}.history-names{flex-wrap:wrap;gap:4px}.history-time time span{display:block;margin-left:0}}
</style>
