<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, useId, watch } from 'vue'
import { api } from '../api'
import type { Person, Preset } from '../types'
import EmployeeAvatar from './EmployeeAvatar.vue'

const props = defineProps<{ preset: Preset }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement | null>(null)
const list = ref<HTMLElement | null>(null)
const titleId = `list-preview-${useId()}`
const people = ref<Person[]>([])
const warnings = ref<string[]>([])
const loading = ref(true)
const error = ref('')
const query = ref('')
const page = ref(1)
let request: AbortController | undefined
const paths = (person: Person) => person.paths.map(path => path.names.join(' / ')).join('；') || '直属企业'
const matches = computed(() => people.value.filter(person =>
  `${person.name} ${paths(person)}`.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase())))
const pages = computed(() => Math.max(1, Math.ceil(matches.value.length / 50)))
const visible = computed(() => matches.value.slice((page.value - 1) * 50, page.value * 50))

async function load() {
  request?.abort()
  const current = new AbortController()
  request = current; loading.value = true; error.value = ''; people.value = []; warnings.value = []
  try {
    const result = await api<{ people: Person[]; warnings: string[] }>('/ranges/resolve', 'POST', props.preset.selection, current.signal)
    if (current.signal.aborted) return
    people.value = result.people; warnings.value = result.warnings; page.value = 1
  } catch (e) {
    if (!current.signal.aborted) error.value = e instanceof Error ? e.message : '名单加载失败'
  } finally { if (!current.signal.aborted) loading.value = false }
}
function backdrop(event: MouseEvent) {
  if (event.target !== dialog.value || !dialog.value) return
  const rect = dialog.value.getBoundingClientRect()
  if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) emit('close')
}
function trapFocus(event: KeyboardEvent) {
  if (event.key !== 'Tab' || !dialog.value) return
  const controls = [...dialog.value.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), [tabindex="0"]')]
  const first = controls[0], last = controls.at(-1)
  if (!first || !last) return
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}
watch([page, query], async () => { await nextTick(); if (list.value) list.value.scrollTop = 0 })
onMounted(async () => {
  await nextTick()
  dialog.value?.showModal()
  void load()
})
onUnmounted(() => { request?.abort(); dialog.value?.close() })
</script>

<template>
  <dialog ref="dialog" class="panel modal recipient-list-preview" :aria-labelledby="titleId" @cancel.prevent="emit('close')" @keydown="trapFocus" @keydown.esc.prevent.stop="emit('close')" @click="backdrop">
    <div class="preview-heading"><h2 :id="titleId" class="panel-title">名单预览</h2><button type="button" class="preview-close" aria-label="关闭名单预览" autofocus @click="emit('close')"><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m5 5 10 10M15 5 5 15" /></svg></button></div>
    <div class="list-preview-name"><strong>{{ preset.name }}</strong><span>{{ preset.scope === 'public' ? '公共名单' : '我的名单' }}</span></div>
    <div v-if="loading" class="list-preview-empty" role="status"><span class="recipient-spinner" aria-hidden="true"></span>正在匹配人员…</div>
    <div v-else-if="error" class="list-preview-empty"><p class="error-text" role="alert">{{ error }}</p><button type="button" @click="load">重新加载</button></div>
    <template v-else>
      <div class="list-preview-toolbar"><span><b>{{ people.length }}</b> 位通知对象</span><input v-model="query" type="search" aria-label="搜索预览名单人员" placeholder="搜索姓名或部门" autocomplete="off" @input="page = 1"></div>
      <div v-if="warnings.length" class="list-preview-warnings" tabindex="-1"><p v-for="warning in warnings" :key="warning" class="error-text" role="alert">{{ warning }}</p></div>
      <div ref="list" class="list-preview-people" role="list" aria-label="预览通知人员" tabindex="0">
        <div v-for="person in visible" :key="person.id" class="list-preview-person" role="listitem"><EmployeeAvatar :src="person.avatar_url" :name="person.name" size="small" /><div><b>{{ person.name }}</b><span>{{ paths(person) }}</span></div></div>
        <p v-if="!matches.length" class="list-preview-empty">{{ query ? '没有匹配的人员' : '暂无可通知人员' }}</p>
      </div>
      <div v-if="query || matches.length > 50" class="list-preview-footer"><span>{{ query ? `匹配 ${matches.length} 人` : `共 ${people.length} 人` }}</span><div v-if="matches.length > 50" class="pagination"><button type="button" :disabled="page <= 1" @click="page--">上一页</button><span>{{ page }} / {{ pages }}</span><button type="button" :disabled="page >= pages" @click="page++">下一页</button></div></div>
    </template>
  </dialog>
</template>

<style scoped>
.recipient-list-preview{width:640px;max-width:calc(100% - 32px);max-height:88dvh;margin:auto;padding:24px;overflow:hidden}
.recipient-list-preview[open]{display:flex;flex-direction:column;gap:16px}
.recipient-list-preview::backdrop{background:var(--overlay)}
.preview-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;flex:none}
.preview-heading .panel-title{margin:0}
.preview-close{display:flex;align-items:center;justify-content:center;width:30px;height:30px;flex:none;padding:5px;border:0;background:transparent;color:var(--muted)}
.preview-close:hover{background:var(--surface-2);color:var(--text)}
.preview-close svg{width:18px;height:18px;stroke:currentColor;stroke-width:1.5;stroke-linecap:round}
.list-preview-name{display:flex;align-items:flex-start;gap:10px;flex:none}
.list-preview-name strong{min-width:0;flex:1;font-size:14px;font-weight:600;overflow-wrap:anywhere}
.list-preview-name>span{flex:none;margin-top:2px;padding:2px 8px;border-radius:var(--r-sm);background:var(--accent-soft);color:var(--accent-deep);font-size:var(--fs-xs)}
.list-preview-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex:none;font-size:var(--fs-sm);color:var(--muted)}
.list-preview-toolbar>span{white-space:nowrap}.list-preview-toolbar b{font-family:var(--mono);color:var(--text)}
.list-preview-toolbar input{width:240px;font-size:var(--fs-sm);padding:7px 10px}
.list-preview-warnings{flex:none;max-height:90px;overflow:auto;padding:8px 12px;border-radius:var(--r-md);background:var(--minus-soft)}
.list-preview-warnings p{margin:0}.list-preview-warnings p+p{margin-top:4px}
.list-preview-people{min-height:0;max-height:380px;overflow:auto;overscroll-behavior:contain;border:1px solid var(--line);border-radius:var(--r-md)}
.list-preview-person{display:flex;align-items:center;gap:10px;padding:12px;border-bottom:1px solid var(--line)}
.list-preview-person:last-child{border-bottom:0}.list-preview-person>div{min-width:0;flex:1}
.list-preview-person b{display:block;font-size:var(--fs-sm);font-weight:600;overflow-wrap:anywhere}
.list-preview-person span{display:block;margin-top:2px;color:var(--muted);font-size:var(--fs-xs);overflow-wrap:anywhere;line-height:1.7}
.list-preview-empty{display:flex;align-items:center;justify-content:center;flex-wrap:wrap;gap:8px;padding:36px 12px;margin:0;color:var(--muted);font-size:var(--fs-sm);text-align:center}
.list-preview-empty .error-text{width:100%;margin:0 0 6px}
.list-preview-footer{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;flex:none;font-size:var(--fs-xs);color:var(--muted)}
.list-preview-footer .pagination{margin:0}.list-preview-footer .pagination>span{font-family:var(--mono)}
@media(max-width:640px){.recipient-list-preview{padding:20px}.list-preview-toolbar{align-items:flex-start;flex-direction:column;gap:8px}.list-preview-toolbar input{width:100%}.list-preview-name{flex-wrap:wrap}.list-preview-name strong{flex-basis:100%}}
</style>
