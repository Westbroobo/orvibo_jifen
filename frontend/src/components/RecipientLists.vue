<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { api } from '../api'
import { unionSelection } from '../types'
import type { Directory, Preset, Selection, User } from '../types'
import RecipientRangeEditor from './RecipientRangeEditor.vue'

const props = defineProps<{ presets: Preset[]; directory: Directory; user: User; loading?: boolean }>()
const emit = defineEmits<{ saved: [preset: Preset]; deleted: [id: string]; working: [value: boolean] }>()
const editing = ref(false)
const editingId = ref('')
const name = ref('')
const scope = ref<'personal' | 'public'>('personal')
const selection = ref<Selection>(unionSelection())
const rangeReady = ref(false)
const busy = ref(false)
const blocked = computed(() => busy.value || props.loading)
const error = ref('')
const notice = ref('')
const deleteConfirm = ref(false)
const query = ref('')
const editorPanel = ref<HTMLElement | null>(null)
const current = computed(() => props.presets.find(p => p.id === editingId.value))
const canEdit = computed(() => !editingId.value || !!current.value?.can_edit)
const groups = computed(() => [
  { scope: 'public', title: '公共名单', items: props.presets.filter(p => p.scope === 'public' && p.name.includes(query.value.trim())) },
  { scope: 'personal', title: '我的名单', items: props.presets.filter(p => p.scope === 'personal' && p.name.includes(query.value.trim())) },
])
async function begin(preset?: Preset, targetScope: 'personal' | 'public' = 'personal') {
  if (blocked.value) return
  editingId.value = preset?.id ?? ''; name.value = preset?.name ?? ''; scope.value = preset?.scope ?? targetScope
  selection.value = preset ? JSON.parse(JSON.stringify(preset.selection)) : unionSelection()
  editing.value = true; rangeReady.value = false; deleteConfirm.value = false; error.value = ''; notice.value = ''
  await nextTick()
  if (window.matchMedia('(max-width:820px)').matches) editorPanel.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
function close() { editing.value = false; deleteConfirm.value = false; error.value = '' }
async function save() {
  if (blocked.value || !canEdit.value || !rangeReady.value || !name.value.trim()) return
  busy.value = true; emit('working', true); error.value = ''; notice.value = ''
  try {
    const saved = await api<Preset>(editingId.value ? `/presets/${editingId.value}` : '/presets', editingId.value ? 'PUT' : 'POST', {
      name: name.value, scope: scope.value, selection: selection.value,
    })
    emit('saved', saved); editingId.value = saved.id; name.value = saved.name; notice.value = '名单已保存'; deleteConfirm.value = false
  } catch (e) { error.value = e instanceof Error ? e.message : '保存失败' }
  finally { busy.value = false; emit('working', false) }
}
async function remove() {
  if (blocked.value || !editingId.value || !canEdit.value) return
  busy.value = true; emit('working', true); error.value = ''
  try { await api(`/presets/${editingId.value}`, 'DELETE'); emit('deleted', editingId.value); close(); notice.value = '名单已删除' }
  catch (e) { error.value = e instanceof Error ? e.message : '删除失败' }
  finally { busy.value = false; emit('working', false) }
}
watch([name, selection], () => { notice.value = ''; deleteConfirm.value = false }, { deep: true })
function summary(preset: Preset) {
  if (preset.selection.match_mode !== 'union') return '原部门交集规则'
  const departments = preset.selection.department_ids?.length ?? 0
  const people = new Set([...preset.selection.person_ids, ...preset.selection.extra_ids]).size
  return [departments ? `${departments} 个部门` : '', people ? `${people} 位指定人员` : ''].filter(Boolean).join(' + ') || '空名单'
}
</script>

<template>
  <main class="lists-layout">
    <section class="panel list-sidebar" aria-label="发送名单列表">
      <div class="panel-head flex-head"><h1 class="panel-title">发送名单</h1><button type="button" class="primary-button" :disabled="blocked" @click="begin()">新建</button></div>
      <input v-model="query" type="search" aria-label="搜索发送名单" placeholder="搜索名单">
      <div v-for="group in groups" :key="group.scope" class="list-group">
        <div class="group-heading"><h2>{{ group.title }}</h2><button v-if="group.scope === 'public' && user.can_manage" type="button" :disabled="blocked" @click="begin(undefined, 'public')">＋ 新建公共名单</button></div>
        <button v-for="preset in group.items" :key="preset.id" type="button" class="list-item" :class="{ selected: editing && editingId === preset.id }" :disabled="blocked" @click="begin(preset)">
          <span><b>{{ preset.name }}</b><small>{{ summary(preset) }}</small></span><span class="item-arrow" aria-hidden="true">›</span>
        </button>
        <p v-if="!group.items.length" class="hint">{{ query ? '暂无匹配名单' : '暂无名单' }}</p>
      </div>
      <p v-if="notice && !editing" class="success-text" role="status">{{ notice }}</p>
    </section>
    <section ref="editorPanel" class="panel list-editor" aria-label="发送名单维护">
      <template v-if="editing">
        <div class="panel-head flex-head"><h2 class="panel-title">{{ editingId ? (canEdit ? '编辑名单' : '查看名单') : '新建名单' }}</h2><button type="button" :disabled="blocked" @click="close">关闭</button></div>
        <form @submit.prevent="save">
          <fieldset :disabled="blocked || !canEdit">
            <div class="list-basics">
              <div><label class="field-label" for="list-name">名单名称</label><input id="list-name" v-model="name" maxlength="100" placeholder="例如：研发通知名单" required></div>
              <div><label class="field-label" for="list-scope">可见范围</label><select v-if="!editingId && user.can_manage" id="list-scope" v-model="scope"><option value="personal">仅自己</option><option value="public">所有在职员工</option></select><div v-else id="list-scope" class="scope-label">{{ scope === 'public' ? '所有在职员工' : '仅自己' }}</div></div>
            </div>
            <RecipientRangeEditor v-model="selection" :people="directory.people" :departments="directory.departments" @ready="rangeReady = $event" />
          </fieldset>
          <p v-if="error" class="error-text" role="alert">{{ error }}</p><p v-if="notice" class="success-text" role="status">{{ notice }}</p>
          <div v-if="canEdit" class="editor-actions">
            <button class="primary-button" type="submit" :disabled="blocked || !name.trim() || !rangeReady">{{ busy ? '正在处理…' : '保存名单' }}</button>
            <button v-if="editingId && !deleteConfirm" class="delete-button" type="button" :disabled="blocked" @click="deleteConfirm = true">删除名单</button>
            <template v-if="deleteConfirm"><span>删除此名单？</span><button type="button" :disabled="blocked" @click="deleteConfirm = false">取消</button><button type="button" class="delete-button" :disabled="blocked" @click="remove">确认删除</button></template>
          </div>
        </form>
      </template>
      <div v-else class="list-empty"><h2>选择或新建发送名单</h2><p>组合部门全员和指定人员，自动合并去重。</p></div>
    </section>
  </main>
</template>

<style scoped>
.lists-layout{display:grid;grid-template-columns:320px minmax(0,1fr);align-items:start;gap:24px}
.list-sidebar .primary-button{padding:7px 14px;width:auto}
.list-group{margin-top:24px}
.group-heading{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:10px}
.group-heading h2{margin:0;font-size:var(--fs-sm);color:var(--muted);font-weight:500}
.group-heading button{padding:0;border:0;background:none;color:var(--accent-deep);font-size:var(--fs-xs)}
.list-item{display:flex;align-items:center;justify-content:space-between;text-align:left;width:100%;margin-top:8px;padding:12px;gap:12px}
.list-item.selected{border-color:var(--accent);background:var(--accent-soft)}
.list-item span{min-width:0}
.list-item b{display:block;font-size:var(--fs-sm);overflow-wrap:anywhere}
.list-item small{display:block;margin-top:4px;color:var(--muted);font-size:var(--fs-xs)}
.item-arrow{font-size:22px;color:var(--muted)}
.list-basics{display:grid;grid-template-columns:minmax(0,1fr) 145px;gap:14px;margin-bottom:24px}
.scope-label{padding:11px 0;font-size:var(--fs-sm);color:var(--muted)}
fieldset{padding:0;border:0;margin:0;min-width:0}
.editor-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:22px}
.editor-actions .primary-button{width:auto;min-width:130px}
.editor-actions span{font-size:var(--fs-xs);color:var(--muted)}
.delete-button{color:var(--minus-ink);margin-left:auto}
.success-text{color:var(--plus-ink);font-size:var(--fs-sm)}
.list-empty{text-align:center;padding:90px 0}
.list-empty h2{font-size:var(--fs-md);font-weight:500}
.list-empty p{font-size:var(--fs-sm);color:var(--muted)}
@media(max-width:820px){.lists-layout{grid-template-columns:1fr}.list-basics{grid-template-columns:minmax(0,1fr) 110px}.list-empty{padding:30px 0}}
</style>
