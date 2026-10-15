<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api'
import { statusLabels } from '../types'
import type { Directory, Grant, Permission, PermissionAuditItem, Person, RoleCatalog, RoleDefinition, User } from '../types'
import DirectorySync from './DirectorySync.vue'
import EmployeeAvatar from './EmployeeAvatar.vue'
import DepartmentTreeSelect from './DepartmentTreeSelect.vue'

const props = defineProps<{ directory: Directory; busy: boolean; user: User }>()
const emit = defineEmits<{ synced: []; changed: [] }>()
const tab = ref<'employees' | 'roles' | 'audit'>('employees')
const catalog = ref<RoleCatalog>({ items: [], permissions: [], departments: [], owner_notice: '' })
const loading = ref(false), saving = ref(false), error = ref(''), feedback = ref('')
const query = ref(''), departmentId = ref(''), role = ref(''), status = ref(''), page = ref(1)
const filtered = computed(() => props.directory.people.filter(p => p.name.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase()) &&
  (!departmentId.value || p.paths.some(path => path.ids.includes(departmentId.value))) && (!role.value || p.role === role.value) && (!status.value || p.status === status.value)))
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / 30)))
const visible = computed(() => filtered.value.slice((page.value - 1) * 30, page.value * 30))
watch([query, departmentId, role, status], () => { page.value = 1 })
watch(pages, value => { page.value = Math.min(page.value, value) })
const paths = (p: Person) => p.paths.map(path => path.names.join(' / ')).join('；') || '直属企业'
const roleName = (id: string) => catalog.value.items.find(r => r.id === id)?.name ?? id
const permissionName = (id: string) => catalog.value.permissions.find(p => p.id === id)?.name ?? id
const scopeName = (value?: string) => ({ own: '仅自己执行的', departments: '指定部门及下级', all: '全部' }[value ?? ''] ?? '')
const departmentName = (id: string) => catalog.value.departments.find(d => d.id === id)?.name ?? `失效部门（${id}）`
const employee = ref<Person | null>(null), grant = ref<Grant | null>(null)
const editingRole = ref<Partial<RoleDefinition> | null>(null), deletingRole = ref<RoleDefinition | null>(null)
const dialog = ref<HTMLElement | null>(null), modalError = ref('')
const modalOpen = computed(() => !!employee.value || !!editingRole.value || !!deletingRole.value)
const selectedRole = computed(() => catalog.value.items.find(r => r.id === grant.value?.role))
const auditItems = ref<PermissionAuditItem[]>([]), auditTotal = ref(0), auditPage = ref(1)
const root = ref<HTMLElement | null>(null), scroller = ref<HTMLElement | null>(null), tableHeight = ref(360)
let observer: ResizeObserver | undefined
let frame: number | undefined
function fitTable() {
  if (frame !== undefined) cancelAnimationFrame(frame)
  frame = requestAnimationFrame(() => {
    if (!scroller.value) return
    const footer = scroller.value.parentElement?.querySelector('footer')?.getBoundingClientRect().height ?? 56
    tableHeight.value = Math.max(160, Math.floor(window.innerHeight - scroller.value.getBoundingClientRect().top - footer - 20))
  })
}
watch([tab, page, filtered], async () => { await nextTick(); if (scroller.value) scroller.value.scrollTop = 0; fitTable() })
let request: AbortController | undefined
let auditSequence = 0
let opener: HTMLElement | null = null
async function loadRoles(signal?: AbortSignal) { catalog.value = await api<RoleCatalog>('/admin/roles', 'GET', undefined, signal) }
async function loadAudit(signal?: AbortSignal) {
  const sequence = ++auditSequence
  const data = await api<{ items: PermissionAuditItem[]; total: number }>('/admin/permission-audits?page=' + auditPage.value, 'GET', undefined, signal)
  if (sequence === auditSequence) { auditItems.value = data.items; auditTotal.value = data.total }
}
async function refresh() {
  request?.abort(); request = new AbortController(); loading.value = true; error.value = ''
  const pending = request
  try { await loadRoles(pending.signal); if (tab.value === 'audit') await loadAudit(pending.signal) }
  catch (e) { if (!pending.signal.aborted) error.value = e instanceof Error ? e.message : '加载失败' }
  finally { if (request === pending) loading.value = false }
}
async function changeTab(value: typeof tab.value) { tab.value = value; await refresh() }
async function editEmployee(person: Person) {
  modalError.value = ''; error.value = ''; loading.value = true
  try { grant.value = await api<Grant>(`/admin/people/${person.id}/authorization`); employee.value = person }
  catch (e) { error.value = e instanceof Error ? e.message : '加载失败' }
  finally { loading.value = false }
}
function selectDepartment(id: string) {
  if (id && grant.value) grant.value.ledger_department_ids = [...new Set([...grant.value.ledger_department_ids, id])]
}
function close() { if (saving.value) return; employee.value = null; grant.value = null; editingRole.value = null; deletingRole.value = null; modalError.value = '' }
watch(() => props.user.can_configure_roles, allowed => {
  if (!allowed && (editingRole.value || deletingRole.value || employee.value?.role === 'owner')) close()
})
async function save(fn: () => Promise<unknown>) {
  saving.value = true; modalError.value = ''; feedback.value = ''
  try { await fn(); saving.value = false; close(); await loadRoles(); emit('changed'); feedback.value = '已保存' }
  catch (e) { modalError.value = e instanceof Error ? e.message : '保存失败' }
  finally { saving.value = false }
}
function saveGrant() {
  if (!employee.value || !grant.value) return
  const data = grant.value
  if (data.ledger_scope === 'departments' && !data.ledger_department_ids.length) { modalError.value = '至少选择一个授权部门'; return }
  void save(() => api(`/admin/people/${employee.value!.id}/authorization`, 'PUT', data))
}
function editRole(role?: RoleDefinition) { modalError.value = ''; editingRole.value = role ? JSON.parse(JSON.stringify(role)) : { name: '', description: '', permissions: [] } }
function setPermission(permission: Permission, checked: boolean) {
  if (!editingRole.value) return
  const selected = new Set(editingRole.value.permissions ?? [])
  if (checked) {
    selected.add(permission)
    const required = catalog.value.permissions.find(p => p.id === permission)?.requires
    if (required) selected.add(required)
  } else {
    selected.delete(permission)
    catalog.value.permissions.filter(p => p.requires === permission).forEach(p => selected.delete(p.id))
  }
  editingRole.value.permissions = [...selected]
}
function saveRole() {
  const role = editingRole.value
  if (!role?.name?.trim()) { modalError.value = '请填写角色名称'; return }
  void save(() => api(role.id ? `/admin/roles/${role.id}` : '/admin/roles', role.id ? 'PUT' : 'POST', { name: role.name, description: role.description, permissions: role.permissions }))
}
function describe(snapshot: PermissionAuditItem['before']) {
  if (!snapshot) return '无'
  if (snapshot.permissions) return `${snapshot.name}；${snapshot.description || '无说明'}；${snapshot.permissions.map(permissionName).join('、') || '无功能权限'}`
  return [snapshot.role_name || roleName(snapshot.role || 'none'), snapshot.history_scope && `发送记录：${scopeName(snapshot.history_scope)}`,
    snapshot.ledger_scope && `积分明细：${scopeName(snapshot.ledger_scope)}`, snapshot.ledger_scope === 'departments' && snapshot.ledger_department_ids?.map(departmentName).join('、')].filter(Boolean).join('；')
}
function keydown(event: KeyboardEvent) {
  if (!modalOpen.value || (event.target instanceof Element && event.target.closest('.department-menu'))) return
  if (event.key === 'Escape') { event.stopImmediatePropagation(); close() }
  if (event.key === 'Tab' && dialog.value) {
    const controls = [...dialog.value.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]')].filter(el => el.getClientRects().length)
    const first = controls[0], last = controls.at(-1)
    if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.value)) { event.preventDefault(); last?.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
  }
}
watch(modalOpen, async open => {
  if (open) { opener = document.activeElement instanceof HTMLElement ? document.activeElement : null; await nextTick(); dialog.value?.focus() }
  else { await nextTick(); if (opener?.isConnected) opener.focus() }
})
onMounted(() => { void refresh(); window.addEventListener('keydown', keydown, true); window.addEventListener('resize', fitTable); observer = new ResizeObserver(fitTable); if (root.value) observer.observe(root.value); fitTable() })
onUnmounted(() => { request?.abort(); window.removeEventListener('keydown', keydown, true); window.removeEventListener('resize', fitTable); observer?.disconnect(); if (frame !== undefined) cancelAnimationFrame(frame) })
</script>

<template>
  <main ref="root" class="permissions-page" aria-label="权限管理" :style="{ '--table-height': `${tableHeight}px` }">
    <div :inert="modalOpen">
      <header class="permissions-heading"><h1 class="panel-title">权限管理</h1><button :disabled="loading || saving || busy" @click="refresh">{{ loading ? '加载中…' : '刷新' }}</button></header>
      <p v-if="catalog.owner_notice" class="setup-notice" role="status">{{ catalog.owner_notice }}</p>
      <p v-if="error" class="error-text" role="alert">{{ error }}</p><p v-if="feedback" class="saved" role="status">{{ feedback }}</p>
      <nav class="permission-tabs" aria-label="权限页签"><button :aria-current="tab === 'employees' ? 'page' : undefined" @click="changeTab('employees')">员工授权</button><button :aria-current="tab === 'roles' ? 'page' : undefined" @click="changeTab('roles')">角色配置</button><button :aria-current="tab === 'audit' ? 'page' : undefined" @click="changeTab('audit')">变更记录</button></nav>
      <template v-if="tab === 'employees'">
        <DirectorySync :busy="busy || saving" @synced="emit('synced')" />
        <section class="panel permissions-panel">
          <div class="section-heading"><h2>员工授权</h2><span>{{ filtered.length }} 人</span></div>
          <div class="permissions-filters"><input v-model="query" type="search" aria-label="搜索员工" placeholder="搜索姓名"><DepartmentTreeSelect v-model="departmentId" :departments="directory.departments" /><select v-model="role" aria-label="筛选角色"><option value="">全部角色</option><option v-for="item in catalog.items" :key="item.id" :value="item.id">{{ item.name }}</option></select><select v-model="status" aria-label="筛选员工状态"><option value="">全部状态</option><option v-for="(label, key) in { active: '在职', resigned: '离职', inactive: '不可用', unknown: '待核实' }" :key="key" :value="key">{{ label }}</option></select><button v-if="query || departmentId || role || status" @click="query = ''; departmentId = ''; role = ''; status = ''">重置</button></div>
          <div ref="scroller" class="permissions-table" tabindex="0" role="region" aria-label="员工授权列表"><table><thead><tr><th>序号</th><th>员工 / 部门</th><th>状态</th><th>角色</th><th>授权</th></tr></thead><tbody><tr v-for="(person, index) in visible" :key="person.id"><td class="index">{{ (page - 1) * 30 + index + 1 }}</td><td><div class="person"><EmployeeAvatar :src="person.avatar_url" :name="person.name" size="small" /><div><b>{{ person.name }}</b><small>{{ paths(person) }}</small></div></div></td><td><span :class="['employee-status', { active: person.status === 'active' }]">{{ statusLabels[person.status] }}</span></td><td><span class="role-badge" :class="{ management: ['owner', 'admin'].includes(person.role) }">{{ roleName(person.role) }}</span></td><td><button :disabled="loading || saving || busy || person.role === 'owner' && !user.can_configure_roles" :aria-label="`查看${person.name}授权`" @click="editEmployee(person)">查看 / 设置</button></td></tr><tr v-if="!visible.length"><td colspan="5" class="empty">没有匹配的员工</td></tr></tbody></table></div>
          <footer class="permissions-footer"><span>每人一个角色，查看范围独立设置</span><div class="pagination"><button :disabled="page <= 1" @click="page--">上一页</button><span>{{ page }} / {{ pages }}</span><button :disabled="page >= pages" @click="page++">下一页</button></div></footer>
        </section>
      </template>
      <section v-else-if="tab === 'roles'" class="panel role-panel"><div class="section-heading"><div><h2>角色与功能</h2><p>{{ user.can_configure_roles ? '修改后，使用该角色的员工立即生效。' : '角色定义由系统所有者维护。' }}</p></div><button v-if="user.can_configure_roles" class="primary-button" :disabled="loading || saving" @click="editRole()">新建角色</button></div>
        <div class="roles-grid"><article v-for="item in catalog.items" :key="item.id" class="role-card"><div class="role-heading"><h3>{{ item.name }}<small>{{ item.builtin ? '内置' : '自定义' }}</small></h3><span>{{ item.employee_count }} 人</span></div><p>{{ item.description }}</p><ul v-if="item.permissions.length"><li v-for="permission in catalog.permissions" :key="permission.id" :class="{ off: !item.permissions.includes(permission.id) }"><span aria-hidden="true">{{ item.permissions.includes(permission.id) ? '✓' : '—' }}</span>{{ permission.name }}</li></ul><p v-else class="hint">仅查看公共名单、维护个人名单</p><div v-if="['owner', 'admin'].includes(item.id)" class="management-note">{{ item.id === 'owner' ? '全部管理能力；可配置角色和任免所有者' : '员工授权、变更记录、公共名单、组织同步' }}</div><footer v-if="user.can_configure_roles && !['owner', 'none'].includes(item.id)"><button :disabled="loading || saving" :aria-label="`编辑${item.name}`" @click="editRole(item)">编辑</button><button v-if="!item.builtin" :disabled="!!item.employee_count || loading || saving" :title="item.employee_count ? '有员工使用，不能删除' : '删除角色'" @click="deletingRole = item">删除</button></footer></article></div>
      </section>
      <section v-else class="panel audit-panel"><div class="section-heading"><h2>权限变更记录</h2><span>共 {{ auditTotal }} 条</span></div><div ref="scroller" class="permissions-table" tabindex="0" role="region" aria-label="权限变更列表"><table><thead><tr><th>时间 / 操作者</th><th>对象</th><th>修改前</th><th>修改后</th></tr></thead><tbody><tr v-for="item in auditItems" :key="item.id"><td><time>{{ new Date(item.created_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) }}</time><small>{{ item.actor_name }}</small></td><td><b>{{ item.target_name }}</b><small>{{ item.event === 'role' ? '角色配置' : item.event === 'owner_init' ? '所有者初始化' : '员工授权' }}</small></td><td>{{ describe(item.before) }}</td><td>{{ describe(item.after) }}</td></tr><tr v-if="!auditItems.length"><td colspan="4" class="empty">暂无变更记录</td></tr></tbody></table></div><footer class="permissions-footer"><span>保留历史授权记录</span><div class="pagination"><button :disabled="loading || auditPage <= 1" @click="auditPage--; refresh()">上一页</button><span>{{ auditPage }} / {{ Math.max(1, Math.ceil(auditTotal / 20)) }}</span><button :disabled="loading || auditPage * 20 >= auditTotal" @click="auditPage++; refresh()">下一页</button></div></footer></section>
    </div>
    <Teleport to="body"><div v-if="modalOpen" class="modal-backdrop" @click.self="close"><section ref="dialog" class="panel modal authorization-modal" role="dialog" aria-modal="true" aria-labelledby="authorization-title" tabindex="-1">
      <template v-if="employee && grant"><div class="section-heading"><h2 id="authorization-title">{{ employee.name }} · 员工授权</h2><button :disabled="saving" aria-label="关闭授权设置" @click="close">×</button></div><form @submit.prevent="saveGrant"><fieldset :disabled="saving"><label>角色<select v-model="grant.role"><option v-for="item in catalog.items.filter(r => user.can_configure_roles || r.id !== 'owner')" :key="item.id" :value="item.id" :disabled="employee.status !== 'active' && item.id !== 'none'">{{ item.name }}</option></select></label><p class="capability-summary">{{ selectedRole?.permissions.map(permissionName).join('、') || '查看公共名单、维护个人名单' }}</p><div class="scope-fields"><label>发送记录范围<select v-model="grant.history_scope"><option value="own">仅自己执行的</option><option value="all">全部</option></select></label><label>积分明细范围<select v-model="grant.ledger_scope"><option value="own">仅自己执行的</option><option value="departments">指定部门及下级</option><option value="all">全部</option></select></label></div><div v-if="grant.ledger_scope === 'departments'" class="department-grant"><DepartmentTreeSelect model-value="" @update:model-value="selectDepartment" :allow-all="false" placeholder="选择授权部门" label="添加积分明细授权部门" :departments="catalog.departments.filter(d => !('active' in d) || d.active)" /><div class="chips"><span v-for="id in grant.ledger_department_ids" :key="id" class="chip">{{ departmentName(id) }}<button type="button" :aria-label="`移除${departmentName(id)}`" @click="grant.ledger_department_ids = grant.ledger_department_ids.filter(d => d !== id)">×</button></span></div><p class="hint">多个部门合并，包含下级；按记分时部门匹配。</p></div><p v-if="grant.role === 'owner'" class="hint">系统所有者固定拥有全部能力和全部记录查看范围。</p><p v-else class="hint">范围仅在角色具有对应查看权限时生效，切换角色不扩大范围。</p></fieldset><p v-if="modalError" class="error-text" role="alert">{{ modalError }}</p><div class="modal-actions"><button type="button" :disabled="saving" @click="close">取消</button><button type="submit" class="primary-button" :disabled="saving">{{ saving ? '保存中…' : '保存授权' }}</button></div></form></template>
      <template v-else-if="editingRole"><div class="section-heading"><h2 id="authorization-title">{{ editingRole.id ? '编辑角色' : '新建角色' }}</h2><button :disabled="saving" aria-label="关闭角色设置" @click="close">×</button></div><form @submit.prevent="saveRole"><fieldset :disabled="saving"><label>角色名称<input v-model="editingRole.name" maxlength="100" required :disabled="editingRole.builtin"></label><label>说明<textarea v-model="editingRole.description" maxlength="500" rows="2" /></label><div class="permission-checks"><label v-for="item in catalog.permissions" :key="item.id"><input type="checkbox" :checked="editingRole.permissions?.includes(item.id)" @change="setPermission(item.id, ($event.target as HTMLInputElement).checked)"><span>{{ item.name }}<small v-if="item.id === 'history.others'">还需记录可见及撤回 / 重试权限</small></span></label></div></fieldset><p v-if="modalError" class="error-text" role="alert">{{ modalError }}</p><div class="modal-actions"><button type="button" :disabled="saving" @click="close">取消</button><button type="submit" class="primary-button" :disabled="saving">{{ saving ? '保存中…' : '保存角色' }}</button></div></form></template>
      <template v-else-if="deletingRole"><h2 id="authorization-title">删除角色</h2><p>确认删除“{{ deletingRole.name }}”？</p><p v-if="modalError" class="error-text" role="alert">{{ modalError }}</p><div class="modal-actions"><button :disabled="saving" @click="close">取消</button><button class="primary-button" :disabled="saving" @click="save(() => api(`/admin/roles/${deletingRole!.id}`, 'DELETE'))">确认删除</button></div></template>
    </section></div></Teleport>
  </main>
</template>

<style scoped>
.permissions-page{grid-template-columns:minmax(0,1fr)}.permissions-page>div{min-width:0}.permissions-filters>.department-select{min-width:0;flex:0 1 260px}
.permissions-page{display:grid;gap:16px}.permissions-heading,.section-heading,.role-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.permissions-heading{margin-bottom:14px}.permissions-heading h1{margin:0}.permission-tabs{display:flex;gap:6px;margin-bottom:16px;border-bottom:1px solid var(--line);padding-bottom:10px}.permission-tabs button{border:0;background:transparent;color:var(--muted);padding:10px 16px}.permission-tabs button[aria-current=page]{background:var(--accent-soft);color:var(--accent-deep);font-weight:600}.setup-notice{padding:12px 16px;background:var(--accent-soft);border-radius:var(--r-md);font-size:var(--fs-sm)}.saved{color:var(--plus-ink);font-size:var(--fs-sm)}.permissions-panel{padding:0;overflow:hidden;margin-top:16px}.section-heading{padding:18px 22px}.section-heading h2{margin:0;font-size:15px}.section-heading p{font-size:var(--fs-xs);color:var(--muted);margin:6px 0 0}.section-heading>span{font-size:var(--fs-xs);color:var(--muted)}.permissions-filters{display:flex;gap:8px;flex-wrap:wrap;padding:0 22px 18px}.permissions-filters>input{flex:1;min-width:140px}.permissions-filters>select{width:132px}.permissions-filters>*{max-width:100%}.permissions-table{overflow:auto;max-height:var(--table-height);min-height:160px;overscroll-behavior:contain;scrollbar-gutter:stable}.permissions-table table{border-collapse:collapse;width:100%;font-size:var(--fs-sm)}th{position:sticky;top:0;background:var(--surface-2);z-index:1;font-size:var(--fs-xs);color:var(--muted);text-align:left;white-space:nowrap}th,td{padding:13px 20px;border-bottom:1px solid var(--line)}td{vertical-align:middle}td.index{font-family:var(--mono);color:var(--muted);width:48px}.person{display:flex;align-items:center;gap:10px;min-width:220px}.person b{font-weight:600}.person small,td>small{display:block;color:var(--muted);font-size:var(--fs-xs);margin-top:4px;max-width:420px;overflow-wrap:anywhere}td button{white-space:nowrap;font-size:var(--fs-xs);padding:7px 10px}.employee-status,.role-badge{display:inline-block;white-space:nowrap;background:var(--surface-2);border-radius:var(--r-sm);padding:4px 8px;font-size:var(--fs-xs);color:var(--muted)}.employee-status.active{color:var(--plus-ink);background:var(--plus-soft)}.role-badge.management{color:var(--accent-deep);background:var(--accent-soft)}.permissions-footer{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;padding:14px 22px;color:var(--muted);font-size:var(--fs-xs)}.permissions-footer .pagination{margin:0}.empty{text-align:center;padding:48px;color:var(--muted)}.role-panel,.audit-panel{padding:0;overflow:hidden}.roles-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(245px,1fr));gap:14px;padding:0 22px 22px}.role-card{border:1px solid var(--line);border-radius:var(--r-md);padding:18px;display:flex;flex-direction:column}.role-heading h3{margin:0;font-size:15px}.role-heading small{font-size:10px;font-weight:400;color:var(--muted);margin-left:8px}.role-heading>span{font-size:var(--fs-xs);color:var(--muted);white-space:nowrap}.role-card>p{font-size:var(--fs-xs);color:var(--muted);line-height:1.7;min-height:40px}.role-card ul{padding:0;list-style:none;display:grid;gap:9px;margin:8px 0 18px;font-size:var(--fs-sm)}.role-card li{display:flex;gap:9px;color:var(--text)}.role-card li>span{color:var(--plus-ink)}.role-card li.off,.role-card li.off>span{color:var(--muted);opacity:.65}.management-note{padding:10px;background:var(--surface-2);font-size:var(--fs-xs);line-height:1.7;border-radius:var(--r-sm);margin-top:auto}.role-card footer{display:flex;gap:8px;margin-top:auto;padding-top:16px}.role-card footer button{font-size:var(--fs-xs)}.audit-panel .permissions-table{max-height:var(--table-height)}.audit-panel table{min-width:700px}.audit-panel td{max-width:320px;line-height:1.8;overflow-wrap:anywhere;vertical-align:top}.audit-panel time{white-space:nowrap;font-size:var(--fs-xs);font-family:var(--mono)}.authorization-modal{max-width:580px;max-height:90dvh;overflow:auto;padding:24px}.authorization-modal .section-heading{padding:0 0 18px}.authorization-modal .section-heading>button{padding:3px 10px;font-size:20px}.authorization-modal fieldset{border:0;padding:0;margin:0;min-width:0;display:grid;gap:16px}.authorization-modal label{display:grid;gap:8px;font-size:var(--fs-sm);font-weight:500}.authorization-modal input,.authorization-modal select,.authorization-modal textarea{font-weight:400}.capability-summary{margin:0;color:var(--muted);font-size:var(--fs-xs);line-height:1.8;background:var(--surface-2);padding:12px;border-radius:var(--r-md)}.scope-fields{display:grid;grid-template-columns:1fr 1fr;gap:12px}.permission-checks{display:grid;gap:8px}.permission-checks label{display:flex;gap:12px;align-items:center;padding:10px 12px;border:1px solid var(--line);border-radius:var(--r-md);cursor:pointer}.permission-checks input{width:16px;height:16px;accent-color:var(--accent-deep)}.permission-checks small{display:block;color:var(--muted);font-size:var(--fs-xs);margin-top:4px;font-weight:400}.department-grant{display:grid;gap:10px}.department-grant .chip button{background:transparent;border:0;padding:0 2px}.authorization-modal .hint{margin:0;line-height:1.8}.authorization-modal .modal-actions{margin-top:20px}
@media(max-width:640px){.permissions-heading{margin-bottom:10px}.permission-tabs{gap:0}.permission-tabs button{padding:10px 12px;flex:1}.section-heading{padding:16px}.permissions-filters{padding:0 16px 14px}.permissions-filters>input{flex-basis:100%}.permissions-filters>select{flex:1}.permissions-table{max-height:52dvh}.permissions-table table{min-width:650px}.permissions-footer{padding:12px 16px}.roles-grid{grid-template-columns:1fr;padding:0 16px 16px}.role-panel .section-heading{align-items:flex-start}.scope-fields{grid-template-columns:1fr}.authorization-modal{padding:20px;max-height:92dvh}.audit-panel .permissions-table{max-height:65dvh}}
</style>
