<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Department, Person, Selection } from '../types'
import EmployeeAvatar from './EmployeeAvatar.vue'

const props = defineProps<{ modelValue: Selection; people: Person[]; departments: Department[]; title: string; allowAll?: boolean; autofocus?: boolean }>()
const coarsePointer = window.matchMedia('(pointer: coarse)').matches
const emit = defineEmits<{ 'update:modelValue': [value: Selection] }>()
const query = ref('')
const extraQuery = ref('')
const page = ref(1)
const usable = computed(() => props.people.filter(p => p.status === 'active'))
const matchesPath = (p: Person) => !props.modelValue.levels.some(l => l.length) || p.paths.some(path => props.modelValue.levels.every((ids, i) => !ids.length || ids.includes(path.ids[i] ?? '')))
const filtered = computed(() => usable.value.filter(p => matchesPath(p) && p.name.includes(query.value.trim())))
const visible = computed(() => filtered.value.slice((page.value - 1) * 30, page.value * 30))
watch(filtered, () => { page.value = Math.min(page.value, Math.max(1, Math.ceil(filtered.value.length / 30))) })
const extras = computed(() => usable.value.filter(p => extraQuery.value.trim() && p.name.includes(extraQuery.value.trim())).slice(0, 20))
const chosen = computed(() => {
  const ids = new Set(props.modelValue.extra_ids)
  if (props.modelValue.mode === 'all' && props.modelValue.levels.some(l => l.length)) usable.value.filter(matchesPath).forEach(p => ids.add(p.id))
  else usable.value.filter(p => matchesPath(p) && props.modelValue.person_ids.includes(p.id)).forEach(p => ids.add(p.id))
  return props.people.filter(p => ids.has(p.id))
})
const stale = computed(() => {
  const messages: string[] = []
  props.modelValue.levels.forEach((ids, i) => ids.forEach(id => { if (!props.departments.some(d => d.id === id && d.path_ids.length === i + 1)) messages.push('配置中的部门已失效或层级变化') }))
  const ids = props.modelValue.mode === 'all' ? props.modelValue.extra_ids : [...props.modelValue.person_ids, ...props.modelValue.extra_ids]
  ids.forEach(id => { const person = props.people.find(p => p.id === id); if (!person || person.status !== 'active') messages.push(`${person?.name ?? '原配置人员'}当前不可用`) ; else if (!props.modelValue.extra_ids.includes(id) && !matchesPath(person)) messages.push(`${person.name}已不符合部门范围`) })
  return [...new Set(messages)]
})

function update(next: Partial<Selection>) { emit('update:modelValue', { ...props.modelValue, ...next }) }
function options(level: number) {
  return props.departments.filter(d => d.path_ids.length === level + 1 && props.modelValue.levels.slice(0, level).every((ids, i) => !ids.length || ids.includes(d.path_ids[i] ?? '')))
    .sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
}
function changeLevel(level: number, event: Event) {
  const value = Array.from((event.target as HTMLSelectElement).selectedOptions).map(o => o.value)
  const levels = props.modelValue.levels.map(l => [...l]); levels[level] = value
  for (let i = level + 1; i < 3; i++) levels[i] = []
  page.value = 1
  update({ levels })
}
function toggle(id: string, extra = false) {
  const key = extra ? 'extra_ids' : 'person_ids'
  const ids = new Set(props.modelValue[key]); ids.has(id) ? ids.delete(id) : ids.add(id)
  update({ [key]: [...ids] })
}
function selectVisible() { update({ person_ids: [...new Set([...props.modelValue.person_ids, ...visible.value.map(p => p.id)])] }) }
</script>

<template>
  <div class="picker" role="group" :aria-label="title">
    <div class="field-label"><span class="prompt">&gt;</span> {{ title }} <span class="count">已选 {{ chosen.length }} 人</span></div>
    <details class="department-fold">
      <summary>按部门筛选<small v-if="modelValue.levels.flat().length"> 已选 {{ modelValue.levels.flat().length }} 个部门</small></summary>
      <div class="department-grid">
        <template v-for="level in 3" :key="level">
          <label v-if="options(level - 1).length">{{ ['一级部门', '二级部门', '三级部门'][level - 1] }}
            <select multiple :aria-label="`${title}${level}级部门`" :value="modelValue.levels[level - 1]" @change="changeLevel(level - 1, $event)">
              <option v-for="d in options(level - 1)" :key="d.id" :value="d.id">{{ d.name }}</option>
            </select>
          </label>
        </template>
      </div>
    </details>
    <div v-if="modelValue.levels.some(level => level.length)" class="picker-tools"><button class="text-button" type="button" @click="update({ levels: [[], [], []] }); page = 1">清除部门</button></div>
    <div v-if="allowAll" class="inline-options">
      <label><input type="radio" :name="title" :checked="modelValue.mode === 'selected'" @change="update({ mode: 'selected' })">逐人勾选</label>
      <label><input type="radio" :name="title" :checked="modelValue.mode === 'all'" @change="update({ mode: 'all' })">范围内全部人员</label>
    </div>
    <p v-if="modelValue.mode === 'all' && !modelValue.levels.some(l => l.length)" class="hint">请选择部门</p>
    <template v-if="modelValue.mode === 'selected'">
      <input v-model="query" type="search" :aria-label="`${title}姓名搜索`" placeholder="搜索姓名" :autofocus="autofocus && !coarsePointer" @input="page = 1">
      <div class="people-list">
        <label v-for="person in visible" :key="person.id" class="person-option">
          <input type="checkbox" :checked="modelValue.person_ids.includes(person.id)" @change="toggle(person.id)">
          <EmployeeAvatar :src="person.avatar_url" :name="person.name" size="small" />
          <span class="person-text"><b>{{ person.name }}</b><small>{{ person.paths.map(p => p.names.join(' / ')).join('；') || '直属企业' }}</small></span>
        </label>
        <p v-if="!visible.length" class="hint">暂无匹配人员</p>
      </div>
      <div v-if="visible.length" class="picker-tools"><button class="text-button" type="button" @click="selectVisible">全选本页</button><span v-if="filtered.length > 30" class="pagination"><button type="button" :disabled="page <= 1" @click="page--">上一页</button><small>{{ page }} / {{ Math.max(1, Math.ceil(filtered.length / 30)) }}</small><button type="button" :disabled="page * 30 >= filtered.length" @click="page++">下一页</button></span></div>
    </template>
    <details class="extra-picker">
      <summary>额外添加人员</summary>
      <input v-model="extraQuery" type="search" :aria-label="`${title}额外人员搜索`" placeholder="搜索全公司在职人员">
      <label v-for="person in extras" :key="person.id" class="person-option"><input type="checkbox" :checked="modelValue.extra_ids.includes(person.id)" @change="toggle(person.id, true)"><EmployeeAvatar :src="person.avatar_url" :name="person.name" size="small" /><span class="person-text"><b>{{ person.name }}</b><small>{{ person.paths.map(p => p.names.join(' / ')).join('；') }}</small></span></label>
    </details>
    <div v-if="chosen.length" class="chips"><span v-for="p in chosen" :key="p.id" class="chip"><EmployeeAvatar :src="p.avatar_url" :name="p.name" size="tiny" />{{ p.name }}<button type="button" :aria-label="`移除${p.name}`" :disabled="modelValue.mode === 'all' && !modelValue.extra_ids.includes(p.id)" @click="update({ person_ids: modelValue.person_ids.filter(id => id !== p.id), extra_ids: modelValue.extra_ids.filter(id => id !== p.id) })">×</button></span></div>
    <p v-for="message in stale" :key="message" class="error-text">{{ message }}。请更新配置或清除选择。</p>
    <button v-if="chosen.length || stale.length" class="text-button" type="button" @click="update({ person_ids: [], extra_ids: [], levels: [[], [], []], mode: 'selected' })">清空已选</button>
  </div>
</template>

<style scoped>
.department-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-bottom:10px}
.department-grid label{font-size:var(--fs-xs);color:var(--muted)}
.department-grid select{display:block;height:89px;padding:6px;font-size:12px;margin-top:4px}
.department-grid option{padding:3px 2px}
.picker-tools{display:flex;gap:10px;justify-content:space-between;align-items:center;margin:7px 0}
.picker-tools small{font-size:var(--fs-xs)}
.inline-options{display:flex;gap:20px;font-size:var(--fs-sm);margin:12px 0}
.inline-options label{display:flex;align-items:center;gap:6px}
.people-list{max-height:210px;overflow:auto;border:1px solid var(--line);border-radius:var(--r-md);margin-top:8px}
.person-option{display:flex;align-items:center;gap:9px;padding:9px 10px;cursor:pointer;border-bottom:1px solid var(--line);font-size:var(--fs-sm)}
.person-option:last-child{border-bottom:0}
.person-option:hover{background:var(--surface-2)}
.person-text{min-width:0}
.person-text b{display:block;font-size:var(--fs-sm)}
.person-text small{display:block;line-height:1.5;font-size:var(--fs-xs);overflow-wrap:anywhere;color:var(--muted)}
.picker-tools .pagination{margin:0}
.picker-tools .pagination button{padding:3px}
.extra-picker{border-top:1px solid var(--line);padding-top:8px;font-size:var(--fs-xs);color:var(--muted)}
details input{margin-top:8px}
.text-button{border:0;padding:2px 0;color:var(--accent-deep);background:transparent;font-size:var(--fs-xs)}
@media(max-width:420px){
  .department-grid{gap:5px}
  .department-grid select{font-size:var(--fs-xs)}
  .picker-tools .pagination{gap:3px}
  .picker-tools .pagination button{padding:3px}
}
.department-fold{margin-bottom:10px}
.department-fold summary{font-family:var(--mono);font-size:var(--fs-xs);color:var(--muted);margin-bottom:8px}
.department-fold summary small{font-size:var(--fs-xs)}
</style>
