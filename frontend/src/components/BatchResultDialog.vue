<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { recallLabels, statusLabels } from '../types'
import type { BatchDetail } from '../types'
import { notificationNotes, notificationState, recordTime } from '../historyPresentation'
import EmployeeAvatar from './EmployeeAvatar.vue'

const props = defineProps<{ detail: BatchDetail; busy: boolean; error: string; clock: number; confirmingRecall: boolean }>()
const emit = defineEmits<{ close: []; refresh: []; recall: [detail: BatchDetail]; retry: [id: string]; 'change-page': [page: number] }>()
const closeButton = ref<HTMLButtonElement | null>(null)
const body = ref<HTMLElement | null>(null)
const deliveries = ref<HTMLElement | null>(null)
const state = computed(() => notificationState(props.detail.total, props.detail.statuses, props.detail.recall_statuses))
const notes = computed(() => notificationNotes(props.detail.statuses, props.detail.recall_statuses))
const created = computed(() => recordTime(props.detail.created_at))
const scores = computed(() => props.detail.snapshot.rows.map(row => ({ row, score: props.detail.scores?.find(score => score.person_id === row.person.id) })))
const messages = computed(() => props.detail.deliveries.map(delivery => ({
  delivery, person: props.detail.snapshot.rows.find(row => row.person.id === delivery.person_id)?.person,
  label: delivery.recall_status ? recallLabels[delivery.recall_status] ?? delivery.recall_status : statusLabels[delivery.status] ?? delivery.status,
  tone: delivery.recall_status === 'recalled' ? 'neutral'
    : delivery.recall_status === 'failed' || delivery.status === 'failed' ? 'danger'
      : delivery.recall_status || delivery.status !== 'sent' ? 'warning' : 'success',
  sent: delivery.sent_at ? recordTime(delivery.sent_at) : null,
  expired: delivery.status === 'sent' && !delivery.recall_status && !!delivery.recall_deadline && new Date(delivery.recall_deadline).getTime() <= props.clock,
})))
const hasRetry = computed(() => props.detail.can_retry && messages.value.some(message => message.delivery.status === 'failed' && !message.delivery.recall_status))
watch(() => props.detail.id, async () => { await nextTick(); if (body.value) body.value.scrollTop = 0 })
watch(() => props.detail.page, async () => { await nextTick(); if (deliveries.value) deliveries.value.scrollTop = 0 })
function trapFocus(event: KeyboardEvent) {
  if (event.key !== 'Tab') return
  const root = event.currentTarget as HTMLElement
  const focusable = [...root.querySelectorAll<HTMLElement>('button:not(:disabled), [tabindex="0"]')].filter(element => element.getClientRects().length)
  const first = focusable[0], last = focusable.at(-1)
  if (!first || !last) { event.preventDefault(); root.focus(); return }
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}
defineExpose({ focusClose: () => closeButton.value?.focus({ preventScroll: true }) })
</script>

<template>
  <div class="modal-backdrop" :inert="confirmingRecall" @click.self="!busy && emit('close')">
    <section class="panel modal batch-result" role="dialog" aria-modal="true" aria-labelledby="batch-result-title" tabindex="-1" @keydown="trapFocus">
      <header class="batch-result-heading"><div><h2 id="batch-result-title" class="panel-title">发送结果</h2><p><time :datetime="detail.created_at">{{ created.date }} {{ created.time }}</time><span>·</span>{{ detail.snapshot.operator_name }}</p></div><button ref="closeButton" type="button" aria-label="关闭发送结果" :disabled="busy" @click="emit('close')"><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m5 5 10 10M5 15 15 5" /></svg></button></header>
      <div ref="body" class="batch-result-body">
        <p v-if="error" class="error-text" role="alert">{{ error }}</p>
        <div class="batch-overview">
          <div class="batch-delta" :class="detail.snapshot.delta > 0 ? 'plus' : 'minus'"><span>{{ detail.snapshot.delta > 0 ? '每人加分' : '每人扣分' }}</span><b>{{ detail.snapshot.delta > 0 ? '+' : '' }}{{ detail.snapshot.delta }}<small> 分</small></b></div>
          <div class="batch-scope"><span>记分对象 <b>{{ detail.snapshot.rows.length }}</b> 人</span><span>通知对象 <b>{{ detail.snapshot.recipients.length }}</b> 人</span><span>卡片 <b>{{ detail.total }}</b> 条</span></div>
          <div class="batch-notification"><span class="result-badge" :class="[`tone-${state.tone}`, { pulse: state.pulse }]">{{ state.text }}</span><small>{{ detail.statuses.sent ?? 0 }} / {{ detail.total }} 条已发送</small><small v-if="detail.recall_statuses?.recalled">{{ detail.recall_statuses.recalled }} / {{ detail.total }} 条已撤回</small></div>
        </div>
        <div v-if="notes.length" class="batch-alerts"><span v-for="note in notes" :key="note.text" :class="`result-text-${note.tone}`">{{ note.text }}</span></div>
        <section class="batch-section" aria-labelledby="batch-reason-title"><h3 id="batch-reason-title">原因</h3><p class="batch-reason">{{ detail.snapshot.reason }}</p></section>
        <section class="batch-section" aria-labelledby="batch-scores-title">
          <div class="batch-section-heading"><h3 id="batch-scores-title">记分结果</h3><span>{{ detail.snapshot.month }}</span></div>
          <div class="batch-scores">
            <div class="batch-score-head" aria-hidden="true"><span>记分对象 / 状态</span><span>本次总分</span><span>本月当前总分</span></div>
            <div v-for="entry in scores" :key="entry.row.person.id" class="batch-score">
              <div class="batch-score-person"><EmployeeAvatar :src="entry.row.person.avatar_url" :name="entry.row.person.name" size="small" /><div><b>{{ entry.row.person.name }}</b><span class="result-badge" :class="entry.score?.cancelled ? 'tone-neutral' : entry.score ? 'tone-success' : 'tone-warning'">{{ entry.score ? entry.score.cancelled ? '记分已作废' : '积分有效' : '状态待更新' }}</span></div></div>
              <div class="batch-score-total"><span class="mobile-score-label">本次总分</span><b>{{ entry.row.final_total }}</b><small> 分</small><span v-if="entry.row.override_total !== null" class="manual-score">手动覆盖</span></div>
              <div class="batch-score-total"><span class="mobile-score-label">本月当前总分</span><b>{{ entry.score?.current_total ?? '—' }}</b><small> 分</small></div>
              <small v-if="entry.score?.cancelled_at" class="batch-cancelled-at">作废于 {{ recordTime(entry.score.cancelled_at).date }} {{ recordTime(entry.score.cancelled_at).time }}</small>
            </div>
          </div>
        </section>
        <section class="batch-section" aria-labelledby="batch-messages-title">
          <div class="batch-section-heading"><h3 id="batch-messages-title">通知明细</h3><span>共 {{ detail.total }} 条</span></div>
          <div ref="deliveries" class="batch-deliveries" :class="{ 'has-retry': hasRetry }" role="table" aria-label="本次发送的通知明细" tabindex="0">
            <div class="batch-delivery-head" role="rowgroup"><div class="batch-delivery-row" role="row"><span role="columnheader">卡片对象 → 通知对象</span><span role="columnheader">通知结果</span><span v-if="hasRetry" role="columnheader">操作</span></div></div>
            <div role="rowgroup">
              <div v-for="message in messages" :key="message.delivery.id" class="batch-delivery-row" role="row">
                <div role="cell" class="batch-message"><div class="batch-message-people"><b>{{ message.person?.name ?? '未记录人员' }}</b><span aria-label="通知给">→</span><b>{{ message.delivery.recipient_name }}</b></div><code v-if="message.delivery.message_id" :title="message.delivery.message_id">{{ message.delivery.message_id }}</code><small v-else>尚无 message_id</small><small v-if="message.sent">发送于 {{ message.sent.date }} {{ message.sent.time }}</small><p v-if="message.delivery.last_error" class="error-text">{{ message.delivery.last_error }}</p><p v-if="message.delivery.recall_error" class="error-text">{{ message.delivery.recall_error }}</p><small v-if="message.delivery.recalled_at">撤回于 {{ recordTime(message.delivery.recalled_at).date }} {{ recordTime(message.delivery.recalled_at).time }}</small></div>
                <div role="cell" class="batch-message-state"><span class="result-badge" :class="[`tone-${message.tone}`, { pulse: message.delivery.recall_status === 'pending' || message.delivery.recall_status === 'recalling' || message.delivery.status === 'sending' }]">{{ message.label }}</span><small v-if="message.expired">已超撤回时限</small></div>
                <div v-if="hasRetry" role="cell" class="batch-message-action"><button v-if="message.delivery.status === 'failed' && !message.delivery.recall_status" type="button" :disabled="busy" :aria-label="`重试发送${message.person?.name ?? ''}给${message.delivery.recipient_name}`" @click="emit('retry', message.delivery.id)">重试发送</button></div>
              </div>
              <div v-if="!messages.length" role="row"><div role="cell" :aria-colspan="hasRetry ? 3 : 2" class="batch-no-messages">暂无通知明细</div></div>
            </div>
          </div>
          <div v-if="detail.total > 100" class="batch-delivery-pagination"><span>显示 {{ (detail.page - 1) * 100 + 1 }}–{{ Math.min(detail.page * 100, detail.total) }} / {{ detail.total }} 条</span><div class="pagination"><button type="button" :disabled="busy || detail.page <= 1" @click="emit('change-page', detail.page - 1)">上一页</button><span>{{ detail.page }} / {{ Math.ceil(detail.total / 100) }}</span><button type="button" :disabled="busy || detail.page * 100 >= detail.total" @click="emit('change-page', detail.page + 1)">下一页</button></div></div>
        </section>
      </div>
      <footer class="batch-result-footer"><span>{{ detail.recall_available ? `${detail.recall_available} 条卡片可撤回` : '无可撤回卡片' }}</span><div><button type="button" :disabled="busy" @click="emit('refresh')">刷新结果</button><button v-if="detail.can_recall && detail.recall_available" type="button" class="recall-button" :disabled="busy" @click="emit('recall', detail)">整批撤回</button></div></footer>
    </section>
  </div>
</template>

<style scoped>
.batch-result{display:flex;flex-direction:column;width:840px;max-height:90vh;padding:0;overflow:hidden}
.batch-result-heading{flex:none;display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding:20px 24px;border-bottom:1px solid var(--line)}.batch-result-heading h2{margin:0}.batch-result-heading p{display:flex;gap:8px;flex-wrap:wrap;margin:5px 0 0;color:var(--muted);font-size:var(--fs-xs)}.batch-result-heading time{font-family:var(--mono)}.batch-result-heading button{display:flex;align-items:center;justify-content:center;width:32px;height:32px;padding:0;flex:none}.batch-result-heading svg{width:16px;height:16px;stroke:currentColor;stroke-width:1.5;stroke-linecap:round}
.batch-result-body{overflow:auto;min-height:0;padding:20px 24px;overscroll-behavior:contain}
.batch-overview{display:grid;grid-template-columns:140px minmax(0,1fr) 160px;border:1px solid var(--line);border-radius:var(--r-md);overflow:hidden}
.batch-delta{padding:14px 18px;min-width:0}.batch-delta.plus{background:var(--plus-soft);color:var(--plus-ink)}.batch-delta.minus{background:var(--minus-soft);color:var(--minus-ink)}.batch-delta>span{font-size:var(--fs-xs)}.batch-delta>b{display:block;font-family:var(--mono);font-size:22px;margin-top:3px;overflow-wrap:anywhere}.batch-delta small{font-size:var(--fs-xs);font-family:var(--sans);font-weight:400;white-space:nowrap}
.batch-scope{display:flex;gap:6px 20px;flex-wrap:wrap;align-content:center;padding:14px 18px;font-size:var(--fs-sm);color:var(--muted)}.batch-scope span{white-space:nowrap}.batch-scope b{font-family:var(--mono);color:var(--text);margin:0 2px}
.batch-notification{display:flex;align-items:flex-start;flex-direction:column;justify-content:center;gap:5px;border-left:1px solid var(--line);padding:14px 18px;color:var(--muted);font-size:var(--fs-xs)}
.batch-alerts{display:flex;gap:6px 16px;flex-wrap:wrap;padding:10px 0 0;font-size:var(--fs-xs)}
.batch-section{margin-top:22px}.batch-section h3{font-family:var(--sans);font-size:var(--fs-sm);font-weight:600;margin:0 0 10px}.batch-section-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}.batch-section-heading h3{margin:0}.batch-section-heading>span{font-family:var(--mono);font-size:var(--fs-xs);color:var(--muted)}
.batch-reason{margin:0;border-left:3px solid var(--control-line);background:var(--surface-2);padding:10px 14px;border-radius:0 var(--r-sm) var(--r-sm) 0;font-size:var(--fs-sm);line-height:1.8;white-space:pre-wrap;overflow-wrap:anywhere;max-height:160px;overflow:auto}
.batch-scores{border:1px solid var(--line);border-radius:var(--r-md);overflow:hidden}.batch-score,.batch-score-head{display:grid;grid-template-columns:minmax(0,1fr) 138px 138px;gap:12px;padding:12px 16px;align-items:center}.batch-score-head{background:var(--surface-2);color:var(--muted);font-size:var(--fs-xs);padding-top:9px;padding-bottom:9px}.batch-score{border-top:1px solid var(--line);font-size:var(--fs-sm)}
.batch-score-person{display:flex;align-items:center;gap:10px;min-width:0}.batch-score-person>div{min-width:0}.batch-score-person b{display:block;overflow-wrap:anywhere;margin-bottom:5px;font-weight:600}.batch-score-total{min-width:0}.batch-score-total>b{font-family:var(--mono);font-size:16px;overflow-wrap:anywhere}.batch-score-total>small{color:var(--muted)}.manual-score{display:block;color:var(--accent-deep);font-size:var(--fs-xs);margin-top:4px}.mobile-score-label{display:none}.batch-cancelled-at{grid-column:1 / -1;color:var(--muted);font-family:var(--mono)}
.batch-deliveries{max-height:360px;overflow:auto;overscroll-behavior:contain;scrollbar-gutter:stable;border:1px solid var(--line);border-radius:var(--r-md);scroll-padding-top:36px}.batch-deliveries:focus-visible{outline-offset:-2px}
.batch-delivery-head{position:sticky;top:0;z-index:1;background:var(--surface-2)}.batch-delivery-row{display:grid;grid-template-columns:minmax(0,1fr) 112px;gap:16px;align-items:start;padding:13px 16px;border-bottom:1px solid var(--line);font-size:var(--fs-xs)}.has-retry .batch-delivery-row{grid-template-columns:minmax(0,1fr) 112px 92px}.batch-delivery-head .batch-delivery-row{padding-top:9px;padding-bottom:9px;color:var(--muted)}
.batch-message{min-width:0}.batch-message-people{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;margin-bottom:5px}.batch-message-people b{overflow-wrap:anywhere;font-size:var(--fs-sm);font-weight:600}.batch-message-people>span{color:var(--muted)}.batch-message code{display:block;font-family:var(--mono);font-size:var(--fs-xs);color:var(--muted);overflow-wrap:anywhere;user-select:text}.batch-message>small{display:block;margin-top:4px;color:var(--muted);font-size:var(--fs-xs);line-height:1.7}.batch-message p{margin:5px 0 0}
.batch-message-state{display:flex;align-items:flex-start;flex-direction:column;gap:6px}.batch-message-state>small{color:var(--muted);line-height:1.6}.batch-message-action button{white-space:nowrap;padding:6px 8px;font-size:var(--fs-xs)}.batch-no-messages{padding:28px 16px;text-align:center;color:var(--muted)}
.batch-delivery-pagination{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap;margin-top:10px;color:var(--muted);font-size:var(--fs-xs)}.batch-delivery-pagination .pagination{margin:0}
.batch-result-footer{flex:none;display:flex;align-items:center;justify-content:space-between;gap:12px;border-top:1px solid var(--line);padding:14px 24px;background:var(--surface)}.batch-result-footer>span{color:var(--muted);font-size:var(--fs-xs)}.batch-result-footer>div{display:flex;gap:8px}.batch-result-footer button{white-space:nowrap;font-size:var(--fs-sm)}
@media(max-width:640px){.batch-result{max-height:92vh}.batch-result-heading{padding:16px}.batch-result-body{padding:16px}.batch-overview{grid-template-columns:110px minmax(0,1fr)}.batch-delta{padding:12px}.batch-delta>b{font-size:20px}.batch-scope{padding:12px;gap:5px 12px}.batch-notification{grid-column:1 / -1;flex-direction:row;flex-wrap:wrap;align-items:center;justify-content:flex-start;border-left:0;border-top:1px solid var(--line);gap:6px 12px;padding:10px 12px}.batch-score-head{display:none}.batch-score{grid-template-columns:1fr 1fr;padding:12px;gap:10px}.batch-score-person{grid-column:1 / -1;align-items:flex-start}.batch-score-person>div{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.batch-score-person b{margin:0}.mobile-score-label{display:block;font-size:var(--fs-xs);color:var(--muted);margin-bottom:3px}.batch-delivery-head{display:none}.batch-delivery-row,.has-retry .batch-delivery-row{grid-template-columns:minmax(0,1fr) 94px;gap:10px;padding:12px}.batch-message{grid-column:1 / -1}.batch-message-state{grid-column:1}.batch-message-action{grid-column:2}.batch-result-footer{padding:12px 16px;align-items:flex-start;flex-direction:column;gap:8px}.batch-result-footer>div{width:100%;justify-content:flex-end}.batch-result-footer button{flex:1}}
</style>
