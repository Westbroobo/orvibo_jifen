<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, useId, watch } from 'vue'
import type { CSSProperties } from 'vue'
import type { Department } from '../types'

const props = withDefaults(defineProps<{ modelValue: string; departments: Department[]; placeholder?: string; label?: string; allowAll?: boolean }>(), { placeholder: '全部部门', label: '筛选员工部门（含下级部门）', allowAll: true })
const emit = defineEmits<{ 'update:modelValue': [id: string] }>()
const trigger = ref<HTMLButtonElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const search = ref<HTMLInputElement | null>(null)
const tree = ref<HTMLElement | null>(null)
const open = ref(false)
const query = ref('')
const expanded = ref(new Set<string>())
const searchExpanded = ref(new Set<string>())
const activeId = ref('')
const menuStyle = ref<CSSProperties>({})
const treeId = `department-tree-${useId()}`
const selected = computed(() => props.departments.find(d => d.id === props.modelValue))
const selectedPath = computed(() => selected.value?.path_names.join(' / ') || selected.value?.name)
const needle = computed(() => query.value.trim().toLocaleLowerCase())
interface Row { id: string; name: string; path: string; ancestors: string[]; children: number; position: number; siblings: number }
const rows = computed(() => {
  const byId = new Map(props.departments.map(d => [d.id, d]))
  const children = new Map<string, Department[]>()
  for (const department of props.departments) {
    const parent = byId.has(department.parent_id) && department.parent_id !== department.id ? department.parent_id : ''
    const siblings = children.get(parent) ?? []
    siblings.push(department); children.set(parent, siblings)
  }
  for (const siblings of children.values()) siblings.sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
  const result: Row[] = []
  const visited = new Set<string>()
  function visit(items: Department[], ancestors: string[]) {
    items.forEach((department, index) => {
      if (visited.has(department.id)) return
      visited.add(department.id)
      const nested = children.get(department.id) ?? []
      result.push({ id: department.id, name: department.name, path: department.path_names.join(' / ') || department.name,
        ancestors, children: nested.length, position: index + 1 + (ancestors.length || !props.allowAll ? 0 : 1), siblings: items.length + (ancestors.length || !props.allowAll ? 0 : 1) })
      visit(nested, [...ancestors, department.id])
    })
  }
  visit(children.get('') ?? [], [])
  return result
})
const matches = computed(() => rows.value.filter(row => row.path.toLocaleLowerCase().includes(needle.value)))
const included = computed(() => new Set(matches.value.flatMap(row => [...row.ancestors, row.id])))
const expansion = computed(() => needle.value ? searchExpanded.value : expanded.value)
const visible = computed<Row[]>(() => [
  ...(props.allowAll ? [{ id: '', name: '全部部门', path: '全部部门', ancestors: [], children: 0, position: 1, siblings: rows.value.filter(row => !row.ancestors.length).length + 1 }] : []),
  ...rows.value.filter(row => (!needle.value || included.value.has(row.id)) && row.ancestors.every(id => expansion.value.has(id))),
])
const rowId = (id: string) => `${treeId}-${id || 'all'}`
watch([needle, rows], () => {
  if (needle.value) {
    searchExpanded.value = new Set(matches.value.flatMap(row => row.ancestors))
    activeId.value = matches.value[0]?.id ?? ''
  }
})
watch(visible, items => { if (!items.some(row => row.id === activeId.value)) activeId.value = items[0]?.id ?? '' })

function positionMenu() {
  if (!open.value || !trigger.value) return
  const rect = trigger.value.getBoundingClientRect()
  const width = Math.min(Math.max(rect.width, 340), window.innerWidth - 24)
  const below = window.innerHeight - rect.bottom - 12
  const above = rect.top - 12
  const upward = below < 240 && above > below
  menuStyle.value = {
    left: `${Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))}px`, width: `${width}px`,
    top: upward ? undefined : `${rect.bottom + 6}px`, bottom: upward ? `${window.innerHeight - rect.top + 6}px` : undefined,
    maxHeight: `${Math.max(100, Math.min(420, (upward ? above : below) - 6))}px`,
  }
}
function scrollActive() {
  const element = document.getElementById(rowId(activeId.value))
  if (!element || !tree.value) return
  const itemRect = element.getBoundingClientRect(), listRect = tree.value.getBoundingClientRect()
  if (itemRect.top < listRect.top) tree.value.scrollTop -= listRect.top - itemRect.top
  else if (itemRect.bottom > listRect.bottom) tree.value.scrollTop += itemRect.bottom - listRect.bottom
}
async function showMenu() {
  query.value = ''
  const current = rows.value.find(row => row.id === props.modelValue)
  expanded.value = new Set([...expanded.value, ...(current?.ancestors ?? [])])
  open.value = true; positionMenu()
  await nextTick()
  activeId.value = current?.id ?? visible.value[0]?.id ?? ''
  search.value?.focus({ preventScroll: true }); scrollActive()
}
function closeMenu(restoreFocus = false) {
  open.value = false
  if (restoreFocus) trigger.value?.focus({ preventScroll: true })
}
function choose(id: string) { emit('update:modelValue', id); closeMenu(true) }
function toggle(row: Row) {
  const target = needle.value ? searchExpanded : expanded
  const ids = new Set(target.value)
  ids.has(row.id) ? ids.delete(row.id) : ids.add(row.id)
  target.value = ids; activeId.value = row.id
}
async function onKey(event: KeyboardEvent) {
  if (event.isComposing) return
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closeMenu(true); return }
  if (event.key === 'Tab') { closeMenu(true); return }
  const index = visible.value.findIndex(row => row.id === activeId.value)
  const row = visible.value[index]
  if (!row) return
  if (event.key === 'Enter') { event.preventDefault(); choose(row.id); return }
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    activeId.value = visible.value[Math.max(0, Math.min(visible.value.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)))]!.id
  } else if (!query.value && ['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) {
    event.preventDefault()
    if (event.key === 'Home') activeId.value = visible.value[0]?.id ?? ''
    else if (event.key === 'End') activeId.value = visible.value.at(-1)!.id
    else if (event.key === 'ArrowRight' && row.children) {
      if (!expansion.value.has(row.id)) toggle(row)
      else activeId.value = visible.value[index + 1]?.id ?? row.id
    } else if (event.key === 'ArrowLeft') {
      if (row.children && expansion.value.has(row.id)) toggle(row)
      else activeId.value = row.ancestors.at(-1) ?? visible.value[0]?.id ?? ''
    }
  } else return
  await nextTick(); scrollActive()
}
function contains(target: EventTarget | null) {
  return target instanceof Node && (trigger.value?.contains(target) || menu.value?.contains(target))
}
function outside(event: PointerEvent) { if (!contains(event.target)) closeMenu() }
function focusOut(event: FocusEvent) { if (event.relatedTarget && !contains(event.relatedTarget)) closeMenu() }
onMounted(() => {
  document.addEventListener('pointerdown', outside)
  window.addEventListener('resize', positionMenu)
  window.addEventListener('scroll', positionMenu, true)
})
onUnmounted(() => {
  document.removeEventListener('pointerdown', outside)
  window.removeEventListener('resize', positionMenu)
  window.removeEventListener('scroll', positionMenu, true)
})
</script>

<template>
  <div class="department-select">
    <button ref="trigger" type="button" class="department-trigger" :class="{ expanded: open, chosen: modelValue }" :aria-label="label" aria-haspopup="tree" :aria-expanded="open" :aria-controls="treeId" :title="selectedPath || (modelValue ? '部门已失效' : placeholder)" @click="open ? closeMenu(true) : showMenu()" @keydown.down.prevent="showMenu()" @focusout="focusOut">
      <svg class="department-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M7 2h6v4H7zM2 14h5v4H2zM13 14h5v4h-5zM10 6v4M4.5 14v-4h11v4" /></svg>
      <span>{{ selected?.name || (modelValue ? '部门已失效' : placeholder) }}</span>
      <svg class="department-arrow" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m5 8 5 5 5-5" /></svg>
    </button>
    <Teleport to="body">
      <div v-if="open" ref="menu" class="department-menu" :style="menuStyle" @focusout="focusOut" @keydown="onKey">
        <div class="department-search">
          <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5" /><path d="m12 12 4 4" /></svg>
          <input ref="search" v-model="query" type="search" role="combobox" aria-label="搜索部门" placeholder="搜索部门" autocomplete="off" aria-autocomplete="list" aria-haspopup="tree" :aria-expanded="true" :aria-controls="treeId" :aria-activedescendant="rowId(activeId)">
        </div>
        <div :id="treeId" ref="tree" class="department-tree" role="tree" aria-label="部门通讯录">
          <div v-for="row in visible" :id="rowId(row.id)" :key="row.id" class="department-row" :class="{ selected: modelValue === row.id, active: activeId === row.id, 'all-departments': !row.id }" role="treeitem" :aria-label="row.path" :aria-level="row.ancestors.length + 1" :aria-posinset="row.position" :aria-setsize="row.siblings" :aria-selected="modelValue === row.id" :aria-expanded="row.children ? expansion.has(row.id) : undefined" :title="row.path" :style="{ paddingLeft: `${8 + row.ancestors.length * 18}px` }" @pointerdown.prevent @pointermove="activeId = row.id" @click="choose(row.id)">
            <button v-if="row.children" type="button" class="department-toggle" :class="{ expanded: expansion.has(row.id) }" :aria-label="`${expansion.has(row.id) ? '收起' : '展开'}${row.name}`" tabindex="-1" @click.stop="toggle(row)"><svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m6 4 4 4-4 4" /></svg></button>
            <span v-else class="department-toggle-spacer" aria-hidden="true"></span>
            <svg class="department-folder" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M2.5 5a1 1 0 0 1 1-1h4l2 2h7a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1h-13a1 1 0 0 1-1-1Z" /></svg>
            <span class="department-name">{{ row.name }}</span>
            <svg v-if="modelValue === row.id" class="department-check" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m4 10 4 4 8-8" /></svg>
          </div>
          <p v-if="needle && !matches.length" class="department-empty" role="status">没有匹配的部门</p>
          <p v-else-if="!rows.length" class="department-empty" role="status">暂无部门数据</p>
        </div>
        <div class="department-hint">选择部门时包含其下级人员</div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.department-select{min-width:0}
.department-trigger{display:flex;align-items:center;gap:9px;width:100%;height:40px;padding:8px 12px;background:var(--surface);text-align:left;font-family:var(--sans);font-size:var(--fs-sm);font-weight:400}
.department-trigger.expanded{border-color:var(--accent-deep);box-shadow:0 0 0 2px var(--accent-soft)}
.department-trigger.chosen{color:var(--accent-deep)}
.department-trigger>span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.department-icon,.department-arrow,.department-folder,.department-check{width:16px;height:16px;flex:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
.department-icon,.department-arrow{color:var(--muted)}
.department-arrow{width:14px;height:14px;transition:transform .15s}
.department-trigger.expanded .department-arrow{transform:rotate(180deg)}
.department-menu{position:fixed;z-index:11;display:flex;flex-direction:column;overflow:hidden;border:1px solid var(--line);border-radius:var(--r-lg);background:var(--surface);box-shadow:0 8px 28px rgba(31,35,41,.14);font-family:var(--sans)}
.department-search{display:flex;align-items:center;gap:8px;padding:10px 14px;border-bottom:1px solid var(--line);flex:none}
.department-search>svg{width:16px;height:16px;flex:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;color:var(--muted)}
.department-search input{border:0;padding:4px 0;border-radius:0;background:transparent;font-size:var(--fs-sm)}
.department-search input:focus-visible{outline:none}
.department-tree{overflow:auto;overscroll-behavior:contain;min-height:0;padding:6px;scrollbar-gutter:stable}
.department-row{display:flex;align-items:center;gap:7px;min-height:38px;padding:7px 10px;border-radius:var(--r-md);font-size:var(--fs-sm);cursor:pointer;color:var(--text)}
.department-row.active{background:var(--surface-2)}
.department-row.selected{background:var(--accent-soft);color:var(--accent-deep);font-weight:600}
.department-row.selected.active{background:rgba(217,119,87,.14)}
.department-row.all-departments{margin-bottom:4px}
.department-toggle,.department-toggle-spacer{width:20px;height:22px;flex:none}
.department-toggle{display:flex;align-items:center;justify-content:center;padding:0;border:0;background:transparent;color:var(--muted)}
.department-toggle:hover:not(:disabled){background:var(--line);color:var(--text)}
.department-toggle svg{width:14px;height:14px;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round;transition:transform .15s}
.department-toggle.expanded svg{transform:rotate(90deg)}
.department-folder{color:var(--muted)}
.selected .department-folder,.department-check{color:var(--accent-deep)}
.department-name{flex:1;min-width:0;overflow-wrap:anywhere}
.department-hint{flex:none;padding:9px 14px;border-top:1px solid var(--line);font-size:var(--fs-xs);color:var(--muted);background:var(--surface-2)}
.department-empty{margin:0;padding:24px 10px;text-align:center;font-size:var(--fs-sm);color:var(--muted)}
</style>
