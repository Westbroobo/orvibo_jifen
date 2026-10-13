<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, useId, watch } from 'vue'
import { api } from '../api'
import { statusLabels } from '../types'
import type { Directory, Person, Preset } from '../types'
import EmployeeAvatar from './EmployeeAvatar.vue'

const props = defineProps<{ preset: Preset; directory: Directory }>()
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
const departmentsById = computed(() => new Map(props.directory.departments.map(department => [department.id, department])))
const peopleById = computed(() => new Map(props.directory.people.map(person => [person.id, person])))
const isUnion = computed(() => props.preset.selection.match_mode === 'union')
interface CompositionItem { id: string; name: string; title: string; avatar?: string; unavailable: boolean; status?: string }
interface CompositionGroup { key: string; label: string; hint?: string; kind: 'department' | 'person'; items: CompositionItem[] }
function departmentItems(ids: string[], level?: number): CompositionItem[] {
  return [...new Set(ids)].map(id => {
    const department = departmentsById.value.get(id)
    const name = department?.path_names.join(' / ') || `失效部门（${id}）`
    const unavailable = !department || (level !== undefined && department.path_ids.length !== level + 1)
    return { id, name, title: name, unavailable, status: department && unavailable ? '层级已变化' : undefined }
  })
}
function personItems(ids: string[], checkRange = false): CompositionItem[] {
  return [...new Set(ids)].map(id => {
    const person = peopleById.value.get(id)
    const outOfRange = checkRange && person && props.preset.selection.levels.some(level => level.length) &&
      !person.paths.some(path => props.preset.selection.levels.every((ids, level) => !ids.length || ids.includes(path.ids[level] ?? '')))
    return { id, name: person?.name ?? `失效人员（${id}）`, title: person ? paths(person) : id,
      avatar: person?.avatar_url, unavailable: !person || person.status !== 'active' || !!outOfRange,
      status: person && person.status !== 'active' ? statusLabels[person.status] ?? '不可用' : outOfRange ? '不符合部门范围' : undefined }
  })
}
const compositionGroups = computed(() => {
  const selection = props.preset.selection
  const groups: CompositionGroup[] = isUnion.value ? [
    { key: 'departments', label: '部门全员', hint: '含下级部门', kind: 'department', items: departmentItems(selection.department_ids ?? []) },
    { key: 'people', label: '指定人员', kind: 'person', items: personItems([...selection.person_ids, ...selection.extra_ids]) },
  ] : [
    ...selection.levels.map((ids, level): CompositionGroup => ({ key: `level-${level}`, label: ['一级部门', '二级部门', '三级部门'][level] ?? `第 ${level + 1} 级部门`, kind: 'department', items: departmentItems(ids, level) })),
    { key: 'selected', label: '逐人勾选', kind: 'person', items: selection.mode === 'selected' ? personItems(selection.person_ids, true) : [] },
    { key: 'extra', label: '额外人员', kind: 'person', items: personItems(selection.extra_ids) },
  ]
  return groups.filter(group => group.items.length)
})
const compositionSummary = computed(() => {
  const groups = compositionGroups.value
  const departments = new Set(groups.filter(group => group.kind === 'department').flatMap(group => group.items.map(item => item.id))).size
  const people = new Set(groups.filter(group => group.kind === 'person').flatMap(group => group.items.map(item => item.id))).size
  return [departments ? `${departments} 个部门` : '', people ? `${people} 位指定人员` : ''].filter(Boolean).join(' · ') || '未设置范围'
})
const compositionRule = computed(() => {
  if (isUnion.value) return '部门全员与指定人员合并去重。'
  const selection = props.preset.selection
  const mode = selection.mode === 'all' ? (selection.levels.some(ids => ids.length) ? '取范围内全部人员' : '未选部门，不包含部门全员') : '只取范围内勾选人员'
  return `同层部门取并集，不同层在同一部门路径内取交集；${mode}，再与额外人员合并去重。`
})

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
  const controls = [...dialog.value.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), summary, [tabindex="0"]')]
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
    <details class="list-preview-composition" open>
      <summary><strong>名单组成</strong><span>{{ compositionSummary }}</span><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m5 8 5 5 5-5" /></svg></summary>
      <div class="composition-content">
        <div v-for="group in compositionGroups" :key="group.key" class="composition-group">
          <div class="composition-label">{{ group.label }}<small v-if="group.hint">{{ group.hint }}</small></div>
          <div class="composition-items"><span v-for="item in group.items" :key="item.id" class="composition-item" :class="{ unavailable: item.unavailable }" :title="item.title"><EmployeeAvatar v-if="group.kind === 'person'" :src="item.avatar" :name="item.name" size="tiny" /><span>{{ item.name }}<small v-if="item.status">（{{ item.status }}）</small></span></span></div>
        </div>
        <p v-if="!compositionGroups.length" class="composition-empty">未设置部门或人员</p>
        <p class="composition-rule">{{ compositionRule }}</p>
      </div>
    </details>
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
.recipient-list-preview{width:640px;max-width:calc(100% - 32px);max-height:88dvh;margin:auto;padding:24px;overflow:auto;overscroll-behavior:contain}
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
.list-preview-composition{flex:none;border:1px solid var(--line);border-radius:var(--r-md);background:var(--surface-2);min-width:0}
.list-preview-composition summary{display:flex;align-items:center;gap:10px;list-style:none;padding:9px 12px;font-size:var(--fs-xs)}
.list-preview-composition summary::-webkit-details-marker{display:none}
.list-preview-composition summary strong{font-weight:600;white-space:nowrap}
.list-preview-composition summary>span{color:var(--muted);min-width:0}
.list-preview-composition summary svg{width:14px;height:14px;margin-left:auto;flex:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round;transition:transform .15s}
.list-preview-composition[open] summary svg{transform:rotate(180deg)}
.composition-content{max-height:180px;overflow:auto;overscroll-behavior:contain;padding:0 12px 10px}
.composition-group+.composition-group{margin-top:10px}
.composition-label{display:flex;align-items:center;gap:8px;margin-bottom:6px;color:var(--muted);font-size:var(--fs-xs)}
.composition-label small{color:var(--faint)}
.composition-items{display:flex;flex-wrap:wrap;gap:6px}
.composition-item{display:inline-flex;align-items:center;gap:5px;min-width:0;max-width:100%;padding:3px 7px;border:1px solid var(--line);border-radius:var(--r-sm);background:var(--surface);font-size:var(--fs-xs)}
.composition-item>span{min-width:0;overflow-wrap:anywhere}
.composition-item.unavailable{color:var(--minus-ink);border-color:var(--minus-soft)}
.composition-item small{font-size:inherit}
.composition-rule,.composition-empty{margin:8px 0 0;color:var(--muted);font-size:var(--fs-xs);line-height:1.7}
.list-preview-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex:none;font-size:var(--fs-sm);color:var(--muted)}
.list-preview-toolbar>span{white-space:nowrap}.list-preview-toolbar b{font-family:var(--mono);color:var(--text)}
.list-preview-toolbar input{width:240px;font-size:var(--fs-sm);padding:7px 10px}
.list-preview-warnings{flex:none;max-height:90px;overflow:auto;padding:8px 12px;border-radius:var(--r-md);background:var(--minus-soft)}
.list-preview-warnings p{margin:0}.list-preview-warnings p+p{margin-top:4px}
.list-preview-people{min-height:96px;max-height:380px;overflow:auto;overscroll-behavior:contain;border:1px solid var(--line);border-radius:var(--r-md)}
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
