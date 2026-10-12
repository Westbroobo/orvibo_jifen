<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { Person } from '../types'
import EmployeeAvatar from './EmployeeAvatar.vue'

const props = defineProps<{ modelValue: string[]; people: Person[] }>()
const emit = defineEmits<{ 'update:modelValue': [ids: string[]] }>()
const root = ref<HTMLElement | null>(null)
const query = ref('')
const open = ref(false)
const page = ref(1)
const selectedIds = computed(() => new Set(props.modelValue))
const matches = computed(() => props.people.filter(p => p.status === 'active' && p.name.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase())))
const visible = computed(() => matches.value.slice((page.value - 1) * 20, page.value * 20))
const chosen = computed(() => [...selectedIds.value].map(id => ({ id, person: props.people.find(p => p.id === id) })))
watch(matches, () => { page.value = Math.min(page.value, Math.max(1, Math.ceil(matches.value.length / 20))) })
function toggle(id: string) {
  const ids = new Set(props.modelValue)
  ids.has(id) ? ids.delete(id) : ids.add(id)
  emit('update:modelValue', [...ids])
}
function outside(event: PointerEvent) { if (event.target instanceof Node && !root.value?.contains(event.target)) open.value = false }
function closeOnBlur(event: FocusEvent) {
  // A label click briefly blurs the search before focusing its checkbox.
  // Pointer clicks outside are handled separately; keep that activation intact.
  if (event.relatedTarget instanceof Node && !root.value?.contains(event.relatedTarget)) open.value = false
}
onMounted(() => document.addEventListener('pointerdown', outside))
onUnmounted(() => document.removeEventListener('pointerdown', outside))
</script>

<template>
  <div ref="root" class="person-select" role="group" aria-label="加减分对象" @focusout="closeOnBlur" @keydown.esc.prevent.stop="open = false">
    <div class="field-label"><span class="prompt">&gt;</span> 加减分对象 <span class="count">已选 {{ selectedIds.size }} 人</span></div>
    <div class="search-wrap">
      <input v-model="query" type="search" aria-label="加减分对象姓名搜索" placeholder="搜索姓名，可选多人" :aria-expanded="open" aria-controls="target-person-options" autocomplete="off" @focus="open = true" @input="page = 1; open = true" @keydown.down.prevent="open = true">
      <div v-if="open" id="target-person-options" class="person-options" role="group" aria-label="候选人员">
        <div class="option-list">
          <label v-for="person in visible" :key="person.id" class="person-option" :class="{ selected: selectedIds.has(person.id) }">
            <input type="checkbox" :checked="selectedIds.has(person.id)" @change="toggle(person.id)">
            <EmployeeAvatar :src="person.avatar_url" :name="person.name" size="small" />
            <span class="person-text"><b>{{ person.name }}</b><small>{{ person.paths.map(path => path.names.join(' / ')).join('；') || '直属企业' }}</small></span>
          </label>
          <p v-if="!visible.length" class="hint empty-result">暂无匹配人员</p>
        </div>
        <div v-if="matches.length > 20" class="pagination"><button type="button" :disabled="page <= 1" @click="page--">上一页</button><small>{{ page }} / {{ Math.ceil(matches.length / 20) }}</small><button type="button" :disabled="page * 20 >= matches.length" @click="page++">下一页</button></div>
      </div>
    </div>
    <div v-if="chosen.length" class="selected-row">
      <div class="chips"><span v-for="item in chosen" :key="item.id" class="chip" :class="{ unavailable: !item.person || item.person.status !== 'active' }" :title="item.person?.paths.map(path => path.names.join(' / ')).join('；')"><EmployeeAvatar :src="item.person?.avatar_url" :name="item.person?.name ?? '未知人员'" size="tiny" />{{ item.person?.name ?? '失效人员' }}<button type="button" :aria-label="`移除${item.person?.name ?? '失效人员'}`" @click="toggle(item.id)">×</button></span></div>
      <button class="clear-button" type="button" @click="emit('update:modelValue', [])">清空</button>
    </div>
  </div>
</template>

<style scoped>
.person-select{min-width:0}
.search-wrap{position:relative}
.person-options{position:absolute;top:calc(100% + 6px);left:0;right:0;z-index:4;border:1px solid var(--line);border-radius:var(--r-md);background:var(--surface);box-shadow:0 6px 18px rgba(31,35,41,.09);overflow:hidden}
.option-list{max-height:240px;overflow:auto}
.person-option{display:flex;align-items:center;gap:9px;padding:8px 12px;cursor:pointer;border-bottom:1px solid var(--line)}
.person-option:last-child{border-bottom:0}
.person-option:hover,.person-option.selected{background:var(--accent-soft)}
.person-text{min-width:0}
.person-text b{display:block;font-size:var(--fs-sm)}
.person-text small{display:block;color:var(--muted);font-size:var(--fs-xs);overflow-wrap:anywhere;line-height:1.5}
.pagination{margin:0;padding:8px;border-top:1px solid var(--line)}
.empty-result{padding:8px 12px}
.selected-row{display:flex;align-items:start;gap:8px;margin-top:10px}
.selected-row .chips{margin:0;flex:1;min-width:0}
.chip{max-width:100%;overflow-wrap:anywhere}
.chip.unavailable{color:var(--minus-ink);background:var(--minus-soft)}
.clear-button{padding:4px 0;border:0;background:none;color:var(--muted);font-size:var(--fs-xs);white-space:nowrap}
</style>
