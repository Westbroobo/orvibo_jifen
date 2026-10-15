<script setup lang="ts">
import { computed } from 'vue'
import type { RoleCatalog, RoleDefinition } from '../types'

const props = defineProps<{ catalog: RoleCatalog; canConfigure: boolean; busy: boolean }>()
const emit = defineEmits<{ edit: [role?: RoleDefinition]; remove: [role: RoleDefinition] }>()
const roles = computed(() => props.catalog.items.filter(role => role.id !== 'owner'))
const groups = computed(() => [
  { id: 'score', name: '积分操作', ids: ['adjustments.write'] },
  { id: 'history', name: '发送管理', ids: ['history.read', 'history.recall', 'history.retry', 'history.others'] },
  { id: 'ledger', name: '积分明细', ids: ['ledgers.read', 'ledgers.export'] },
].map(group => ({ ...group, permissions: props.catalog.permissions.filter(permission => group.ids.includes(permission.id)) })).filter(group => group.permissions.length))
const editable = (role: RoleDefinition) => props.canConfigure && role.id !== 'none'
</script>

<template>
  <section class="panel role-configuration" aria-label="角色与功能">
    <header class="role-toolbar">
      <div><h2>角色与功能</h2><p>{{ canConfigure ? '按角色配置功能，查看范围在员工授权中设置。' : '查看各角色的功能权限。' }}</p></div>
      <button v-if="canConfigure" type="button" class="primary-button create-role" :disabled="busy" @click="emit('edit')"><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M10 4v12M4 10h12" /></svg>新建角色</button>
    </header>
    <div v-if="!roles.length" class="roles-empty" role="status">{{ busy ? '正在加载角色…' : '暂无角色' }}</div>
    <template v-else>
      <div class="role-matrix" tabindex="0" role="region" aria-label="角色权限对照表">
        <table :style="{ minWidth: `${252 + roles.length * 190}px` }">
          <colgroup><col class="group-col"><col class="feature-col"><col v-for="role in roles" :key="role.id"></colgroup>
          <thead><tr><th scope="col" colspan="2" class="feature-heading">功能权限<small>{{ catalog.permissions.length }} 项功能 · 按角色对照</small></th><th v-for="role in roles" :key="role.id" scope="col" class="role-column">
            <div class="role-title"><span>{{ role.name }}</span><small v-if="!role.builtin" class="role-kind">自定义</small></div>
            <span class="member-count"><b>{{ role.employee_count }}</b> 人使用</span>
            <p v-if="!role.builtin && role.description" class="role-description" :title="role.description">{{ role.description }}</p>
          </th></tr></thead>
          <tbody v-for="group in groups" :key="group.id" class="permission-section">
            <tr v-for="(permission, index) in group.permissions" :key="permission.id">
              <th v-if="index === 0" scope="rowgroup" :rowspan="group.permissions.length" class="group-cell"><span>{{ group.name }}</span></th>
              <th scope="row" class="feature-cell">{{ permission.name }}</th>
              <td v-for="role in roles" :key="role.id"><span :class="['permission-state', role.permissions.includes(permission.id) ? 'enabled' : 'disabled']" :aria-label="`${role.name}：${role.permissions.includes(permission.id) ? '已开启' : '未开启'}${permission.name}`"><svg v-if="role.permissions.includes(permission.id)" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m5 10 3 3 7-7" /></svg><span v-else aria-hidden="true">—</span></span></td>
            </tr>
          </tbody>
          <tbody><tr class="management-row"><th scope="row" colspan="2" class="merged-heading">固定管理能力</th><td v-for="role in roles" :key="role.id"><p v-if="role.id === 'admin'">员工授权、变更记录<br>公共名单、组织同步</p><span v-else class="no-management">—</span></td></tr></tbody>
          <tfoot><tr><th scope="row" colspan="2" class="merged-heading">角色设置</th><td v-for="role in roles" :key="role.id"><div v-if="editable(role)" class="role-actions"><button type="button" :disabled="busy" :aria-label="`编辑${role.name}`" @click="emit('edit', role)">编辑权限</button><button v-if="!role.builtin" type="button" class="delete-role" :disabled="busy || !!role.employee_count" :aria-label="`删除${role.name}`" :title="role.employee_count ? '有员工使用，不能删除' : undefined" @click="emit('remove', role)">删除</button></div><span v-else class="fixed-role">{{ role.id === 'none' ? '基础权限' : '仅查看' }}</span></td></tr></tfoot>
        </table>
      </div>
      <div class="mobile-roles">
        <article v-for="role in roles" :key="role.id" class="mobile-role">
          <header><div class="role-title"><h3>{{ role.name }}</h3><small v-if="!role.builtin" class="role-kind">自定义</small></div><span class="member-count"><b>{{ role.employee_count }}</b> 人使用</span></header>
          <p v-if="!role.builtin && role.description" class="role-description">{{ role.description }}</p>
          <section v-for="group in groups" :key="group.id" class="mobile-permission-group" :aria-label="group.name">
            <h4>{{ group.name }}</h4><ul><li v-for="permission in group.permissions" :key="permission.id" :class="{ off: !role.permissions.includes(permission.id) }"><svg v-if="role.permissions.includes(permission.id)" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m5 10 3 3 7-7" /></svg><span v-else class="disabled-mark" aria-hidden="true">—</span>{{ permission.name }}<span class="sr-only">{{ role.permissions.includes(permission.id) ? '已开启' : '未开启' }}</span></li></ul>
          </section>
          <p v-if="role.id === 'admin'" class="mobile-management">员工授权、变更记录、公共名单、组织同步</p>
          <footer v-if="editable(role)" class="role-actions"><button type="button" :disabled="busy" :aria-label="`编辑${role.name}`" @click="emit('edit', role)">编辑权限</button><button v-if="!role.builtin" type="button" class="delete-role" :disabled="busy || !!role.employee_count" :aria-label="`删除${role.name}`" :title="role.employee_count ? '有员工使用，不能删除' : undefined" @click="emit('remove', role)">删除</button></footer>
        </article>
      </div>
      <footer class="roles-baseline"><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M10 3 4 5v5c0 3 3 5 6 7 3-2 6-4 6-7V5Z" /><path d="m7 10 2 2 4-4" /></svg>全部在职员工均可查看公共名单、维护个人名单</footer>
    </template>
  </section>
</template>

<style scoped>
.role-configuration{padding:0;overflow:hidden;box-shadow:var(--shadow-soft)}
.role-toolbar{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:18px 24px}
.role-toolbar>div{min-width:0}.role-toolbar h2{margin:0;font-size:15px}.role-toolbar p{margin:5px 0 0;font-size:var(--fs-sm);color:var(--muted);line-height:1.7}
.create-role{display:inline-flex;align-items:center;justify-content:center;gap:7px;flex:none;width:auto;white-space:nowrap;padding:9px 14px;font-family:var(--sans);font-size:var(--fs-sm)}
svg{width:18px;height:18px;flex:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
.role-matrix{overflow:auto;overscroll-behavior:contain}.role-matrix:focus-visible{outline-offset:-3px}.role-matrix table{width:100%;border-collapse:separate;border-spacing:0;table-layout:fixed;font-size:var(--fs-sm)}
.group-col{width:96px}.feature-col{width:156px}
.role-matrix th,.role-matrix td{height:43px;padding:8px 16px;border-top:1px solid var(--line);border-right:1px solid var(--line);vertical-align:middle}.role-matrix tr>:last-child{border-right:0}
.role-matrix th{font-weight:500;text-align:left}.role-matrix td{text-align:center}
.role-matrix .group-cell{position:sticky;left:0;z-index:2;padding:12px;text-align:center;background:#F7F8FA;color:var(--muted);font-size:var(--fs-xs);letter-spacing:.03em}
.role-matrix .feature-cell{position:sticky;left:96px;z-index:1;background:var(--surface);font-weight:500}
.role-matrix thead th{height:94px;padding:16px;background:#F0F2F5;vertical-align:middle}.role-matrix .feature-heading{position:sticky;left:0;z-index:3;padding-left:24px;font-size:var(--fs-sm);color:var(--muted)}.feature-heading>small{display:block;margin-top:7px;font-size:var(--fs-xs);font-weight:400;color:var(--muted)}
.role-matrix .role-column{text-align:center}.role-column .role-title{justify-content:center}.role-column .role-description{max-width:230px;margin:8px auto 0}
.role-title{display:flex;align-items:center;gap:8px;flex-wrap:wrap;color:var(--text);font-size:15px;font-weight:600;overflow-wrap:anywhere}.role-kind{border:1px solid var(--line);background:var(--surface);padding:0 5px;border-radius:4px;font-size:10px;font-weight:400;color:var(--muted);white-space:nowrap}
.member-count{display:inline-block;margin-top:8px;padding:2px 9px;border:1px solid var(--line);border-radius:20px;background:rgba(255,255,255,.75);font-size:var(--fs-xs);font-weight:400;color:var(--muted)}.member-count b{font-family:var(--mono);color:var(--text);font-weight:400}
.role-description{margin:6px 0 0;font-size:var(--fs-xs);font-weight:400;line-height:1.7;color:var(--muted);overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.permission-section+tbody tr:first-child>*{border-top-color:#CDD4DE}.permission-section tr:hover td,.permission-section tr:hover .feature-cell{background:#F9FAFC}
.permission-state{display:inline-flex;width:25px;height:25px;align-items:center;justify-content:center;border-radius:50%}.permission-state.enabled{background:var(--plus-soft);color:var(--plus-ink)}.permission-state.disabled{color:#A8AFB9}.permission-state svg{width:17px;height:17px;stroke-width:1.8}
.role-matrix .merged-heading{position:sticky;left:0;z-index:2;padding-left:24px;background:#F7F8FA;color:var(--muted);font-size:var(--fs-xs)}.management-row td{padding-top:12px;padding-bottom:12px;background:#FBFCFD}.management-row p{margin:0;font-size:var(--fs-xs);line-height:1.9;color:var(--muted)}.no-management{color:var(--faint)}.role-matrix tfoot td{height:65px;background:#FAFBFC}.fixed-role{display:inline-flex;align-items:center;min-height:35px;font-size:var(--fs-xs);color:var(--muted)}
.role-actions{display:flex;justify-content:center;gap:8px;flex-wrap:wrap}.role-actions button{font-family:var(--sans);font-size:var(--fs-sm);padding:7px 12px;border-color:var(--accent-deep);background:var(--accent-soft);color:var(--accent-deep);white-space:nowrap}.role-actions button:hover:not(:disabled){background:#F7E8E1}.role-actions .delete-role{border-color:var(--line);background:var(--surface);color:var(--muted)}.role-actions .delete-role:hover:not(:disabled){color:var(--minus-ink);border-color:var(--minus);background:var(--minus-soft)}
.roles-baseline{display:flex;align-items:center;justify-content:center;gap:8px;padding:13px 24px;border-top:1px solid var(--line);color:var(--muted);font-size:var(--fs-xs);background:#FAFBFC;text-align:center}.roles-baseline svg{color:var(--plus-ink);width:16px;height:16px}.roles-empty{padding:40px 24px;color:var(--muted);font-size:var(--fs-sm);text-align:center}
.mobile-roles{display:none}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:779px){.role-toolbar{padding:18px 16px;gap:12px;align-items:flex-start}.role-toolbar p{font-size:var(--fs-xs)}.create-role{padding:8px 10px}.role-matrix{display:none}.mobile-roles{display:grid;gap:14px;padding:0 16px 16px}.mobile-role{overflow:hidden;border:1px solid var(--line);border-radius:var(--r-lg)}.mobile-role header{padding:17px 16px;text-align:center;background:#F7F8FA;border-bottom:1px solid var(--line)}.mobile-role .role-title{justify-content:center}.mobile-role h3{margin:0;font-family:var(--sans);font-size:15px}.mobile-role .member-count{white-space:nowrap}.mobile-role .role-description{margin:12px 16px}.mobile-permission-group{margin:0 16px;padding:12px 0}.mobile-permission-group+.mobile-permission-group{border-top:1px solid var(--line)}.mobile-permission-group h4{margin:0 0 9px;font-size:10px;color:var(--muted);font-weight:500;letter-spacing:.04em}.mobile-role ul{display:grid;grid-template-columns:1fr 1fr;gap:12px 10px;padding:0;margin:0;list-style:none;font-size:var(--fs-sm)}.mobile-role li{display:flex;align-items:center;gap:5px}.mobile-role li svg{width:16px;height:16px;color:var(--plus-ink)}.mobile-role li.off{color:var(--faint)}.disabled-mark{width:16px;text-align:center;flex:none}.mobile-management{font-size:var(--fs-xs);color:var(--muted);background:var(--surface-2);padding:10px;border-radius:var(--r-sm);margin:0 16px 14px;text-align:center}.mobile-role .role-actions{justify-content:center;padding:12px 16px;border-top:1px solid var(--line);background:#FAFBFC}.roles-baseline{padding:12px 16px;align-items:flex-start}}
</style>
