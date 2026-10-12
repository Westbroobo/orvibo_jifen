<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { api } from '../api'
import { unionSelection } from '../types'
import type { Department, Person, Selection } from '../types'
import EmployeeAvatar from './EmployeeAvatar.vue'
import PeoplePicker from './PeoplePicker.vue'

const props = defineProps<{ modelValue: Selection; people: Person[]; departments: Department[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: Selection]; ready: [value: boolean] }>()
const departmentQuery = ref('')
const personQuery = ref('')
const level = ref(0)
const personPage = ref(1)
const resultPage = ref(1)
const resolved = ref<Person[]>([])
const warnings = ref<string[]>([])
const resolving = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
let sequence = 0
const isUnion = computed(() => props.modelValue.match_mode === 'union')
const departments = computed(() => props.departments.filter(d =>
  (!level.value || (level.value === 4 ? d.path_ids.length > 3 : d.path_ids.length === level.value)) &&
  d.path_names.join(' / ').includes(departmentQuery.value.trim()))
  .sort((a, b) => a.path_names.join('/').localeCompare(b.path_names.join('/'), 'zh-CN')))
const selectedDepartments = computed(() => (props.modelValue.department_ids ?? []).map(id => ({
  id, name: props.departments.find(d => d.id === id)?.path_names.join(' / ') ?? `失效部门 ${id}`,
})))
const people = computed(() => props.people.filter(p => p.status === 'active' && p.name.includes(personQuery.value.trim())))
const visiblePeople = computed(() => people.value.slice((personPage.value - 1) * 30, personPage.value * 30))
const specifiedIds = computed(() => [...new Set([...props.modelValue.person_ids, ...props.modelValue.extra_ids])])
const specifiedPeople = computed(() => specifiedIds.value.map(id => ({
  id, person: props.people.find(p => p.id === id),
})))
const visibleResult = computed(() => resolved.value.slice((resultPage.value - 1) * 50, resultPage.value * 50))
function update(next: Partial<Selection>) { emit('update:modelValue', { ...props.modelValue, ...next }) }
function toggleDepartment(id: string) {
  const ids = new Set(props.modelValue.department_ids)
  ids.has(id) ? ids.delete(id) : ids.add(id)
  update({ department_ids: [...ids] })
}
function togglePerson(id: string) {
  const ids = new Set(specifiedIds.value)
  ids.has(id) ? ids.delete(id) : ids.add(id)
  update({ person_ids: [...ids], extra_ids: [] })
}
watch([() => props.modelValue, () => props.people, () => props.departments], () => {
  clearTimeout(timer)
  const current = ++sequence
  resolving.value = true; emit('ready', false)
  timer = setTimeout(async () => {
    try {
      const result = await api<{ people: Person[]; warnings: string[] }>('/ranges/resolve', 'POST', props.modelValue)
      if (current !== sequence) return
      resolved.value = result.people; warnings.value = result.warnings; resultPage.value = 1
      emit('ready', result.people.length > 0 && result.warnings.length === 0)
    } catch (e) {
      if (current === sequence) { resolved.value = []; warnings.value = [e instanceof Error ? e.message : '名单解析失败'] }
    } finally { if (current === sequence) resolving.value = false }
  }, 150)
}, { immediate: true, deep: true })
onUnmounted(() => { ++sequence; clearTimeout(timer) })
</script>

<template>
  <div class="range-editor">
    <template v-if="isUnion">
      <div>
        <div class="field-label">部门全员 <small>含下级部门，多个部门合并</small></div>
        <input v-model="departmentQuery" type="search" aria-label="搜索名单部门" placeholder="搜索部门或路径">
        <div class="level-tabs" role="group" aria-label="部门层级">
          <button v-for="(label, index) in ['全部', '一级', '二级', '三级', '更多']" :key="index" type="button" :class="{ active: level === index }" @click="level = index">{{ label }}</button>
        </div>
        <div class="options departments">
          <label v-for="department in departments" :key="department.id" class="range-option">
            <input type="checkbox" :checked="modelValue.department_ids?.includes(department.id)" @change="toggleDepartment(department.id)">
            <span><b>{{ department.name }}</b><small>{{ department.path_names.join(' / ') }}</small></span>
          </label>
          <p v-if="!departments.length" class="hint">暂无匹配部门</p>
        </div>
        <div v-if="selectedDepartments.length" class="chips"><span v-for="department in selectedDepartments" :key="department.id" class="chip" :title="department.name">{{ department.name }}<button type="button" :aria-label="`移除部门${department.name}`" @click="toggleDepartment(department.id)">×</button></span></div>
      </div>
      <div>
        <div class="field-label">指定人员 <small>与部门全员合并去重</small></div>
        <input v-model="personQuery" type="search" aria-label="搜索名单人员" placeholder="搜索姓名" @input="personPage = 1">
        <div class="options">
          <label v-for="person in visiblePeople" :key="person.id" class="range-option">
            <input type="checkbox" :checked="specifiedIds.includes(person.id)" @change="togglePerson(person.id)">
            <EmployeeAvatar :src="person.avatar_url" :name="person.name" size="small" />
            <span><b>{{ person.name }}</b><small>{{ person.paths.map(p => p.names.join(' / ')).join('；') || '直属企业' }}</small></span>
          </label>
          <p v-if="!visiblePeople.length" class="hint">暂无匹配人员</p>
        </div>
        <div v-if="people.length > 30" class="pagination"><button type="button" :disabled="personPage <= 1" @click="personPage--">上一页</button><small>{{ personPage }} / {{ Math.ceil(people.length / 30) }}</small><button type="button" :disabled="personPage * 30 >= people.length" @click="personPage++">下一页</button></div>
        <div v-if="specifiedPeople.length" class="chips"><span v-for="item in specifiedPeople" :key="item.id" class="chip"><EmployeeAvatar :src="item.person?.avatar_url" :name="item.person?.name ?? ''" size="tiny" />{{ item.person?.name ?? '失效人员' }}<button type="button" :aria-label="`移除人员${item.person?.name ?? item.id}`" @click="togglePerson(item.id)">×</button></span></div>
      </div>
    </template>
    <template v-else>
      <div class="legacy-notice"><span>此名单沿用原部门交集规则</span><button type="button" @click="emit('update:modelValue', unionSelection())">重新配置组合名单</button></div>
      <PeoplePicker :model-value="modelValue" :people="props.people" :departments="props.departments" title="原通知范围" allow-all @update:model-value="emit('update:modelValue', $event)" />
    </template>
    <div class="range-result" aria-live="polite">
      <strong>{{ resolving ? '正在匹配…' : `合并后 ${resolved.length} 人` }}</strong>
      <details v-if="resolved.length"><summary>查看名单</summary>
        <div class="result-people"><span v-for="person in visibleResult" :key="person.id" :title="person.paths.map(p => p.names.join(' / ')).join('；')"><EmployeeAvatar :src="person.avatar_url" :name="person.name" size="tiny" />{{ person.name }}</span></div>
        <div v-if="resolved.length > 50" class="pagination"><button type="button" :disabled="resultPage <= 1" @click="resultPage--">上一页</button><small>{{ resultPage }} / {{ Math.ceil(resolved.length / 50) }}</small><button type="button" :disabled="resultPage * 50 >= resolved.length" @click="resultPage++">下一页</button></div>
      </details>
      <p v-for="warning in warnings" :key="warning" class="error-text">{{ warning }}</p>
    </div>
  </div>
</template>

<style scoped>
.range-editor{display:grid;gap:22px}
.field-label small{font-family:var(--sans);margin-left:6px}
.level-tabs{display:flex;gap:6px;margin:8px 0;flex-wrap:wrap}
.level-tabs button{padding:4px 12px;font-size:var(--fs-xs);min-height:30px}
.level-tabs button.active{background:var(--accent-soft);border-color:var(--accent);color:var(--accent-deep)}
.options{max-height:220px;overflow:auto;border:1px solid var(--line);border-radius:var(--r-md);margin-top:8px}
.departments{max-height:190px}
.range-option{display:flex;align-items:center;gap:9px;padding:8px 12px;cursor:pointer;border-bottom:1px solid var(--line)}
.range-option:last-child{border-bottom:0}
.range-option:hover{background:var(--surface-2)}
.range-option span{min-width:0}
.range-option b{display:block;font-size:var(--fs-sm)}
.range-option small{display:block;color:var(--muted);font-size:var(--fs-xs);overflow-wrap:anywhere;line-height:1.5}
.range-result{border-top:1px solid var(--line);padding-top:16px;font-size:var(--fs-sm)}
.range-result details{margin-top:10px}
.result-people{display:flex;flex-wrap:wrap;gap:10px 16px;margin-top:12px}
.result-people span{display:flex;align-items:center;gap:6px}
.legacy-notice{display:flex;gap:12px;align-items:center;flex-wrap:wrap;font-size:var(--fs-xs);color:var(--muted)}
.legacy-notice button{font-size:var(--fs-xs);padding:5px 10px}
.chip{max-width:100%;overflow-wrap:anywhere}
</style>
