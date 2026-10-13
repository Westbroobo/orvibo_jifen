<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { statusLabels } from '../types'
import type { Directory, Person, Role } from '../types'
import DirectorySync from './DirectorySync.vue'
import EmployeeAvatar from './EmployeeAvatar.vue'

const props = defineProps<{ directory: Directory; busy: boolean }>()
const emit = defineEmits<{ synced: []; 'change-role': [person: Person, event: Event] }>()
const query = ref('')
const role = ref<Role | ''>('')
const status = ref('')
const page = ref(1)
const panel = ref<HTMLElement | null>(null)
const scroller = ref<HTMLElement | null>(null)
const panelHeight = ref(480)
let resizeObserver: ResizeObserver | undefined
let resizeFrame: number | undefined
const pageSize = 30
const filtered = computed(() => props.directory.people.filter(person =>
  person.name.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase()) &&
  (!role.value || person.role === role.value) && (!status.value || person.status === status.value)))
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const visible = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const activeCount = computed(() => props.directory.people.filter(person => person.status === 'active').length)
const authorizedCount = computed(() => props.directory.people.filter(person => person.status === 'active' && person.role !== 'none').length)
const hasFilters = computed(() => !!query.value || !!role.value || !!status.value)
watch([query, role, status], () => { page.value = 1 })
watch(pages, value => { page.value = Math.min(page.value, value) })
watch([page, filtered], async () => {
  await nextTick()
  if (scroller.value) scroller.value.scrollTop = 0
})
function resetFilters() { query.value = ''; role.value = ''; status.value = '' }
function fitPanel() {
  if (!panel.value) return
  const fixedHeight = [...panel.value.children].filter(child => child !== scroller.value)
    .reduce((height, child) => height + child.getBoundingClientRect().height, 0)
  const top = panel.value.getBoundingClientRect().top + window.scrollY
  panelHeight.value = Math.floor(Math.max(fixedHeight + 162, window.innerHeight - top - 16))
}
function scheduleResize() {
  if (resizeFrame !== undefined) cancelAnimationFrame(resizeFrame)
  resizeFrame = requestAnimationFrame(fitPanel)
}
onMounted(() => {
  resizeObserver = new ResizeObserver(scheduleResize)
  const outerPage = panel.value?.closest('.page')
  if (outerPage) resizeObserver.observe(outerPage)
  if (panel.value) resizeObserver.observe(panel.value)
  window.addEventListener('resize', scheduleResize)
  scheduleResize()
})
onUnmounted(() => {
  resizeObserver?.disconnect()
  window.removeEventListener('resize', scheduleResize)
  if (resizeFrame !== undefined) cancelAnimationFrame(resizeFrame)
})
const paths = (person: Person) => person.paths.map(path => path.names.join(' / ')).join('；') || '直属企业'
</script>

<template>
  <main class="permissions-page" aria-label="权限管理">
    <header class="permissions-heading"><h1 class="panel-title">权限管理</h1><div class="permissions-overview"><span>在职 <b>{{ activeCount }}</b> 人</span><span>已授权 <b>{{ authorizedCount }}</b> 人</span></div></header>
    <DirectorySync :busy="busy" @synced="emit('synced')" />
    <section ref="panel" class="panel permissions-panel" :style="{ height: `${panelHeight}px` }" aria-labelledby="employee-permissions-title">
      <div class="permissions-table-heading"><h2 id="employee-permissions-title">员工权限</h2><span>共 {{ directory.people.length }} 人</span></div>
      <div class="permissions-filters">
        <div class="permissions-search"><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5" /><path d="m12 12 4 4" /></svg><input v-model="query" type="search" aria-label="权限管理搜索" placeholder="搜索姓名" autocomplete="off"></div>
        <select v-model="role" aria-label="筛选员工权限"><option value="">全部权限</option><option value="admin">管理员</option><option value="operator">操作员</option><option value="none">未授权</option></select>
        <select v-model="status" aria-label="筛选员工状态"><option value="">全部状态</option><option value="active">在职</option><option value="resigned">离职</option><option value="inactive">不可用</option><option value="unknown">待核实</option></select>
        <button v-if="hasFilters" type="button" class="permissions-reset" @click="resetFilters">重置</button>
      </div>
      <div ref="scroller" class="permissions-table" role="table" aria-label="员工权限列表" tabindex="0">
        <div role="rowgroup" class="permissions-table-head"><div role="row" class="permissions-row"><span role="columnheader">序号</span><span role="columnheader">员工 / 部门</span><span role="columnheader">人员状态</span><span role="columnheader">操作权限</span></div></div>
        <div role="rowgroup">
          <div v-for="(person, index) in visible" :key="person.id" class="permissions-row" role="row">
            <span class="permissions-index" role="cell">{{ (page - 1) * pageSize + index + 1 }}</span>
            <div class="permissions-person" role="cell"><EmployeeAvatar :src="person.avatar_url" :name="person.name" size="small" /><div><b>{{ person.name }}</b><small>{{ paths(person) }}</small></div></div>
            <div class="permissions-status" role="cell"><span :class="['employee-status', `status-${person.status}`]">{{ statusLabels[person.status] ?? '不可用' }}</span></div>
            <div class="permissions-role" role="cell"><select :value="person.role" :class="`role-${person.role}`" :aria-label="`${person.name}权限`" :disabled="busy || person.status !== 'active' && person.role === 'none'" @change="emit('change-role', person, $event)"><option value="none">未授权</option><option value="operator" :disabled="person.status !== 'active'">操作员</option><option value="admin" :disabled="person.status !== 'active'">管理员</option></select></div>
          </div>
          <div v-if="!visible.length" role="row"><div role="cell" aria-colspan="4"><div class="permissions-empty" role="status">{{ hasFilters ? '没有匹配的员工' : '暂无员工数据' }}<button v-if="hasFilters" type="button" @click="resetFilters">清除筛选</button></div></div></div>
        </div>
      </div>
      <footer v-if="filtered.length" class="permissions-footer"><span>显示 {{ (page - 1) * pageSize + 1 }}–{{ Math.min(page * pageSize, filtered.length) }} / {{ filtered.length }} 人</span><div v-if="pages > 1" class="pagination"><button type="button" :disabled="page <= 1" @click="page--">上一页</button><span>{{ page }} / {{ pages }}</span><button type="button" :disabled="page >= pages" @click="page++">下一页</button></div></footer>
    </section>
  </main>
</template>

<style scoped>
.permissions-page{display:grid;gap:16px}
.permissions-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:4px 0}
.permissions-heading .panel-title{margin:0}
.permissions-overview{display:flex;gap:16px;font-size:var(--fs-sm);color:var(--muted)}
.permissions-overview b{font-family:var(--mono);color:var(--text);margin:0 3px}
.permissions-panel{display:flex;flex-direction:column;min-height:0;padding:0;overflow:hidden}
.permissions-table-heading,.permissions-filters,.permissions-footer{flex:none}
.permissions-table{flex:1;min-height:0;overflow:auto;overscroll-behavior:contain;scrollbar-gutter:stable;scroll-padding-top:40px}
.permissions-table:focus-visible{outline-offset:-2px}
.permissions-table-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:20px 24px 0}
.permissions-table-heading h2{font-family:var(--sans);font-size:14px;font-weight:600;margin:0}
.permissions-table-heading>span{font-size:var(--fs-xs);color:var(--muted)}
.permissions-filters{display:flex;align-items:center;gap:10px;padding:16px 24px 20px;flex-wrap:wrap}
.permissions-search{display:flex;align-items:center;gap:8px;flex:1;min-width:180px;border:1px solid var(--control-line);border-radius:var(--r-md);padding:0 12px;background:var(--surface)}
.permissions-search:focus-within{border-color:var(--accent-deep);box-shadow:0 0 0 2px var(--accent-soft)}
.permissions-search svg{width:16px;height:16px;flex:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;color:var(--muted)}
.permissions-search input{border:0;background:transparent;padding:9px 0;font-size:var(--fs-sm);height:38px}
.permissions-search input:focus-visible{outline:none}
.permissions-filters>select{flex:none;width:130px;height:40px;border-color:var(--control-line);font-size:var(--fs-sm)}
.permissions-reset{height:40px;padding:8px 12px}
.permissions-row{display:grid;grid-template-columns:40px minmax(0,1fr) 100px 136px;align-items:center;gap:20px;padding:13px 24px;border-top:1px solid var(--line);font-size:var(--fs-sm)}
.permissions-index{font-family:var(--mono);font-variant-numeric:tabular-nums;color:var(--muted);text-align:center}
.permissions-table-head{position:sticky;top:0;z-index:1;background:var(--surface-2)}
.permissions-table-head .permissions-row{padding-top:10px;padding-bottom:10px;font-size:var(--fs-xs);color:var(--muted);font-weight:600}
.permissions-table-head [role=columnheader]:first-child,.permissions-table-head [role=columnheader]:nth-child(3){text-align:center}
.permissions-table-head [role=columnheader]:last-child{padding-left:12px}
.permissions-row:has(.permissions-person):hover{background:#FAFBFC}
.permissions-person{display:flex;align-items:center;gap:12px;min-width:0}
.permissions-person>div{min-width:0;flex:1}
.permissions-person b{display:block;font-weight:600;overflow-wrap:anywhere}
.permissions-person small{display:block;margin-top:3px;font-size:var(--fs-xs);color:var(--muted);overflow-wrap:anywhere;line-height:1.6}
.permissions-status{display:flex;justify-content:center}
.employee-status{display:inline-flex;align-items:center;gap:5px;border-radius:var(--r-sm);padding:3px 8px;background:var(--surface-2);color:var(--muted);font-size:var(--fs-xs);white-space:nowrap}
.employee-status::before{content:'';width:5px;height:5px;flex:none;border-radius:50%;background:currentColor}
.status-active{background:var(--plus-soft);color:var(--plus-ink)}
.status-unknown{background:var(--accent-soft);color:var(--accent-deep)}
.permissions-role select{width:100%;padding:8px 12px;border-color:var(--control-line);font-size:var(--fs-sm);font-weight:500}
.permissions-role .role-admin{border-color:var(--accent-deep);background:#FCF0EB;color:var(--accent-deep)}
.permissions-role .role-operator{border-color:#7B9584;background:var(--plus-soft);color:var(--plus-ink)}
.permissions-role select:disabled{background:var(--surface-2);border-color:var(--line);color:var(--muted);cursor:not-allowed}
.permissions-footer{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;border-top:1px solid var(--line);padding:14px 24px;font-size:var(--fs-xs);color:var(--muted)}
.permissions-footer .pagination{margin:0}
.permissions-empty{display:flex;flex-direction:column;align-items:center;gap:12px;padding:48px 20px;color:var(--muted);font-size:var(--fs-sm)}
@media(max-width:640px){.permissions-heading{align-items:flex-start;flex-direction:column;gap:6px}.permissions-table-heading{padding:18px 16px 0}.permissions-filters{padding:14px 16px 16px;gap:8px}.permissions-search{flex-basis:100%;min-width:0}.permissions-filters>select{flex:1;min-width:0;width:auto}.permissions-table-head{display:none}.permissions-row{grid-template-columns:24px minmax(0,1fr) 120px;gap:12px;padding:14px 16px}.permissions-index{grid-column:1;grid-row:1 / span 2;align-self:start;padding-top:3px}.permissions-person{grid-column:2 / -1;align-items:flex-start;gap:10px}.permissions-status{grid-column:2;justify-content:flex-start}.permissions-role{grid-column:3}.permissions-footer{padding:14px 16px}}
@media(max-width:360px){.permissions-row{grid-template-columns:24px minmax(0,1fr) 106px}.permissions-overview{gap:12px}}
</style>
