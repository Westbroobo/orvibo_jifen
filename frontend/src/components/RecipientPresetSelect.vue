<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, useId, watch } from 'vue'
import type { Directory, Preset } from '../types'
import RecipientListPreview from './RecipientListPreview.vue'

const props = defineProps<{ id: string; modelValue: string; presets: Preset[]; directory: Directory; placeholder: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string]; change: [] }>()
const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const search = ref<HTMLInputElement | null>(null)
const open = ref(false)
const query = ref('')
const previewPreset = ref<Preset | null>(null)
const activeId = ref('')
const opensUp = ref(false)
const menuHeight = ref(380)
const menuId = `preset-options-${useId()}`
const selected = computed(() => props.presets.find(preset => preset.id === props.modelValue))
const groups = computed(() => [
  { scope: 'public', title: '公共名单', items: props.presets.filter(p => p.scope === 'public' && p.name.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase())) },
  { scope: 'personal', title: '我的名单', items: props.presets.filter(p => p.scope === 'personal' && p.name.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase())) },
].filter(group => group.items.length))
const options = computed(() => groups.value.flatMap(group => group.items))
const optionId = (preset: Preset) => `${menuId}-${options.value.findIndex(option => option.id === preset.id)}`
const activeOptionId = computed(() => {
  const active = options.value.find(option => option.id === activeId.value)
  return active ? optionId(active) : undefined
})

function summary(preset: Preset) {
  if (preset.selection.match_mode !== 'union') return '部门交集名单'
  const departments = preset.selection.department_ids?.length ?? 0
  const people = new Set([...preset.selection.person_ids, ...preset.selection.extra_ids]).size
  return [departments ? `${departments} 个部门` : '', people ? `${people} 位指定人员` : ''].filter(Boolean).join(' · ') || '空名单'
}
function positionMenu() {
  if (!open.value || !trigger.value) return
  const rect = trigger.value.getBoundingClientRect()
  const bottomInset = window.matchMedia('(max-width:820px)').matches ? 80 : 12
  const below = window.innerHeight - rect.bottom - bottomInset
  const above = rect.top - 12
  opensUp.value = below < 260 && above > below
  menuHeight.value = Math.max(140, Math.min(380, (opensUp.value ? above : below) - 8))
}
async function showMenu(last = false) {
  if (props.disabled) return
  query.value = ''; open.value = true
  positionMenu()
  await nextTick()
  activeId.value = selected.value?.id ?? (last ? options.value.at(-1)?.id : options.value[0]?.id) ?? ''
  await nextTick()
  search.value?.focus({ preventScroll: true })
  scrollToActive()
}
async function closeMenu(restoreFocus = false) {
  open.value = false
  if (restoreFocus) { await nextTick(); trigger.value?.focus({ preventScroll: true }) }
}
function choose(preset: Preset) {
  if (props.disabled) return
  emit('update:modelValue', preset.id); emit('change')
  void closeMenu(true)
}
function previewList(preset: Preset) {
  if (props.disabled) return
  activeId.value = preset.id; previewPreset.value = preset
}
async function closePreview() {
  const id = previewPreset.value?.id
  previewPreset.value = null
  await nextTick()
  scrollToActive()
  const opener = [...(root.value?.querySelectorAll<HTMLButtonElement>('[data-preview-id]') ?? [])]
    .find(button => button.dataset.previewId === id) ?? trigger.value
  opener?.focus({ preventScroll: true })
}
function scrollToActive() {
  if (!activeOptionId.value) return
  root.value?.querySelector(`[id="${activeOptionId.value}"]`)?.scrollIntoView({ block: 'nearest' })
}
async function onSearchKey(event: KeyboardEvent) {
  if (event.key === 'Tab' && event.shiftKey) {
    event.preventDefault(); void closeMenu(true); return
  }
  if (event.key === 'Enter') {
    event.preventDefault()
    const preset = options.value.find(option => option.id === activeId.value)
    if (preset) choose(preset)
    return
  }
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
  // Keep Home / End available for moving the caret while entering a search.
  if (query.value && (event.key === 'Home' || event.key === 'End')) return
  event.preventDefault()
  const items = options.value
  if (!items.length) return
  const index = items.findIndex(option => option.id === activeId.value)
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1
    : event.key === 'ArrowDown' ? Math.min(index + 1, items.length - 1) : Math.max(index - 1, 0)
  activeId.value = items[next]!.id
  await nextTick(); scrollToActive()
}
function outside(event: PointerEvent) {
  if (previewPreset.value) return
  if (event.target instanceof Node && !root.value?.contains(event.target)) void closeMenu()
}
function focusOut(event: FocusEvent) {
  if (previewPreset.value) return
  if (event.relatedTarget instanceof Node && !root.value?.contains(event.relatedTarget)) void closeMenu()
}
watch(query, () => { activeId.value = options.value[0]?.id ?? '' })
watch(options, items => {
  if (!items.some(option => option.id === activeId.value)) activeId.value = items[0]?.id ?? ''
})
watch(() => props.disabled, disabled => { if (disabled) void closeMenu() })
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
  <div ref="root" class="preset-select" @focusout="focusOut" @keydown.esc.prevent.stop="closeMenu(true)">
    <button :id="id" ref="trigger" type="button" class="preset-trigger" :class="{ expanded: open }" role="combobox" aria-label="选择发送名单" aria-haspopup="grid" :aria-expanded="open" :aria-controls="menuId" :disabled="disabled" :title="selected?.name ?? placeholder" @click="open ? closeMenu(true) : showMenu()" @keydown.down.prevent="showMenu()" @keydown.up.prevent="showMenu(true)">
      <svg class="preset-trigger-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M9 6h11M9 12h11M9 18h11" /><path d="M4 6h.01M4 12h.01M4 18h.01" stroke-width="3" /></svg>
      <span :class="{ placeholder: !selected }">{{ selected?.name ?? placeholder }}</span>
      <svg class="preset-arrow" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m5 8 5 5 5-5" /></svg>
    </button>
    <div v-if="open" class="preset-menu" :class="{ 'opens-up': opensUp }" :style="{ maxHeight: `${menuHeight}px` }">
      <div class="preset-search">
        <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5" /><path d="m12 12 4 4" /></svg>
        <input ref="search" v-model="query" type="search" aria-label="搜索发送名单选项" placeholder="搜索名单" autocomplete="off" :aria-controls="menuId" :aria-activedescendant="activeOptionId" @keydown="onSearchKey">
      </div>
      <div :id="menuId" class="preset-options" role="grid" aria-label="发送名单选项" tabindex="-1">
        <div v-for="group in groups" :key="group.scope" class="preset-group" role="rowgroup" :aria-labelledby="`${menuId}-${group.scope}`">
          <div :id="`${menuId}-${group.scope}`" class="preset-group-title">{{ group.title }}<span>{{ group.items.length }}</span></div>
          <div v-for="preset in group.items" :key="preset.id" class="preset-row" :class="{ selected: modelValue === preset.id, active: activeId === preset.id }" role="row" @pointermove="activeId = preset.id">
            <button :id="optionId(preset)" type="button" class="preset-option" role="gridcell" :aria-label="`选择${preset.name}名单`" :aria-selected="modelValue === preset.id" tabindex="-1" @pointerdown.prevent @keydown="onSearchKey" @click="choose(preset)">
            <span class="preset-option-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><template v-if="group.scope === 'public'"><circle cx="9" cy="7" r="3" /><path d="M3 20v-2a6 6 0 0 1 12 0v2M16 4a3 3 0 0 1 0 6M18 14a5 5 0 0 1 3 4v2" /></template><template v-else><circle cx="12" cy="7" r="3" /><path d="M5 20v-2a7 7 0 0 1 14 0v2" /></template></svg></span>
            <span class="preset-option-text"><b>{{ preset.name }}</b><small>{{ summary(preset) }}</small></span>
            <svg v-if="modelValue === preset.id" class="preset-check" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m4 10 4 4 8-8" /></svg>
            </button>
            <span class="preset-preview-cell" role="gridcell"><button type="button" class="preset-preview" :data-preview-id="preset.id" :aria-label="`预览${preset.name}名单`" aria-haspopup="dialog" @click.stop="previewList(preset)"><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M2 10s3-5 8-5 8 5 8 5-3 5-8 5-8-5-8-5Z" /><circle cx="10" cy="10" r="2" /></svg><span>预览</span></button></span>
          </div>
        </div>
        <p v-if="!options.length" class="preset-no-results" role="status">{{ query ? '没有匹配的名单' : '暂无已保存名单' }}</p>
      </div>
    </div>
  </div>
  <Teleport to="body"><RecipientListPreview v-if="previewPreset" :preset="previewPreset" :directory="directory" @close="closePreview" /></Teleport>
</template>

<style scoped>
.preset-select{position:relative;flex:1;min-width:0}
.preset-trigger{display:flex;align-items:center;gap:10px;width:100%;height:40px;padding:8px 12px;text-align:left;font-family:var(--sans);font-size:var(--fs-sm)}
.preset-trigger.expanded{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent-soft)}
.preset-trigger>span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.preset-trigger .placeholder{color:var(--muted)}
.preset-trigger-icon{flex:none;width:16px;height:16px;color:var(--muted);stroke:currentColor;stroke-width:1.6;stroke-linecap:round}
.preset-arrow{width:14px;height:14px;flex:none;color:var(--muted);stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round;transition:transform .15s}
.expanded .preset-arrow{transform:rotate(180deg)}
.preset-menu{position:absolute;left:0;right:0;top:calc(100% + 6px);z-index:6;display:flex;flex-direction:column;border:1px solid var(--line);border-radius:var(--r-lg);background:var(--surface);box-shadow:0 8px 24px rgba(31,35,41,.1);overflow:hidden}
.preset-menu.opens-up{top:auto;bottom:calc(100% + 6px)}
.preset-search{display:flex;align-items:center;gap:8px;flex:none;padding:10px 12px;border-bottom:1px solid var(--line)}
.preset-search>svg{width:15px;height:15px;flex:none;color:var(--muted);stroke:currentColor;stroke-width:1.5;stroke-linecap:round}
.preset-search input{padding:4px 0;border:0;border-radius:0;background:transparent;font-size:var(--fs-sm);line-height:1.6}
.preset-search input:focus-visible{outline:none}
.preset-options{padding:6px;overflow:auto;overscroll-behavior:contain;min-height:0}
.preset-group+.preset-group{margin-top:4px;padding-top:4px;border-top:1px solid var(--line)}
.preset-group-title{display:flex;align-items:center;gap:8px;padding:6px 8px;font-size:var(--fs-xs);color:var(--muted);font-weight:500}
.preset-group-title>span{font-family:var(--mono);font-size:var(--fs-xs);color:var(--muted)}
.preset-row{display:flex;align-items:center;gap:4px;border-radius:var(--r-md)}
.preset-row.active{background:var(--surface-2)}
.preset-row.selected{background:var(--accent-soft)}
.preset-row.selected.active{background:rgba(217,119,87,.12)}
.preset-option{display:flex;align-items:center;gap:10px;flex:1;min-width:0;padding:10px 8px;border:0;background:transparent;text-align:left;font-family:var(--sans)}
.preset-preview-cell{flex:none;padding-right:6px}
.preset-preview{display:flex;align-items:center;gap:4px;padding:6px;border-color:transparent;background:transparent;color:var(--accent-deep);font-family:var(--sans);font-size:var(--fs-xs);white-space:nowrap}
.preset-preview:hover:not(:disabled){border-color:transparent;background:rgba(217,119,87,.1)}
.preset-preview svg{width:15px;height:15px;stroke:currentColor;stroke-width:1.4;stroke-linecap:round;stroke-linejoin:round}
.preset-option-icon{display:flex;align-items:center;justify-content:center;flex:none;width:30px;height:30px;border-radius:var(--r-md);background:var(--surface-2);color:var(--muted)}
.preset-option-icon svg{width:18px;height:18px;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
.selected .preset-option-icon{background:rgba(217,119,87,.1);color:var(--accent-deep)}
.preset-option-text{min-width:0;flex:1}
.preset-option-text b{display:block;font-size:var(--fs-sm);font-weight:600;line-height:1.6;overflow-wrap:anywhere}
.preset-option-text small{display:block;margin-top:2px;font-size:var(--fs-xs);font-weight:400;color:var(--muted);line-height:1.5}
.selected .preset-option-text b{color:var(--accent-deep)}
.preset-check{width:17px;height:17px;flex:none;color:var(--accent-deep);stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.preset-no-results{margin:0;padding:22px 10px;text-align:center;font-size:var(--fs-sm);color:var(--muted)}
@media(max-width:420px){.preset-select{position:static}}
@media(max-width:360px){.preset-trigger{gap:6px;padding:8px 10px}.preset-trigger-icon{display:none}}
</style>
