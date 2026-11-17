import assert from 'node:assert/strict'
import { test } from 'node:test'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer, nextTick } from 'vue'

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const cache = resolve(frontend, '../.cache/table-sync-component-tests')
mkdirSync(cache, { recursive: true })
const vueUrl = import.meta.resolve('vue')
const transpile = source => ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText
for (const name of ['api', 'types', 'tableSync']) {
  let source = transpile(readFileSync(resolve(frontend, `src/${name}.ts`), 'utf8'))
  source = source.replace(/from ['"]\.\/(types)['"]/g, 'from "./$1.mjs"')
  writeFileSync(resolve(cache, `${name}.mjs`), source)
}
const source = readFileSync(resolve(frontend, 'src/components/TableSyncPanel.vue'), 'utf8')
const descriptor = parse(source).descriptor
let compiled = compileScript(descriptor, { id: 'table-sync-regression', inlineTemplate: true, templateOptions: { compilerOptions: { hoistStatic: false } } }).content
const children = [...source.matchAll(/import (\w+) from '\.\/[^']+\.vue'/g)].map(match => match[1])
writeFileSync(resolve(cache, 'children.mjs'), `import { defineComponent, h } from ${JSON.stringify(vueUrl)};\n` + children.map(name =>
  `export const ${name} = defineComponent({ name: '${name}', inheritAttrs: false, setup(_, { attrs }) { return () => h('test-control', { ...attrs, 'data-component': '${name}' }) } });`,
).join('\n'))
compiled = compiled.replace(/from ['"]vue['"]/g, `from ${JSON.stringify(vueUrl)}`)
compiled = compiled.replace(/import (\w+) from '\.\/[^']+\.vue'/g, 'import { $1 } from "./children.mjs"')
compiled = compiled.replace(/from ['"]\.\.\/(api|types|tableSync)['"]/g, 'from "./$1.mjs"')
writeFileSync(resolve(cache, 'TableSyncPanel.mjs'), transpile(compiled))
const TableSyncPanel = (await import(pathToFileURL(resolve(cache, 'TableSyncPanel.mjs')).href)).default

class Element extends EventTarget {
  constructor(tag, text = '') { super(); this.tag = tag; this.tagName = tag.toUpperCase(); this.text = text; this.props = {}; this.children = []; this.parent = null; this.value = ''; this.style = {}; this.isConnected = true; this.selected = false; this.multiple = false }
  get options() { return this.children.filter(child => child.tag === 'option') }
  getAttribute(name) { return this.props[name] ?? null }
  setAttribute(name, value) { this.props[name] = value }
  removeAttribute(name) { delete this.props[name] }
  getRootNode() { return document }
  focus() { document.activeElement = this }
}
const renderer = createRenderer({
  createElement: tag => new Element(tag), createText: text => new Element('#text', text), createComment: text => new Element('#comment', text),
  setText: (node, text) => { node.text = text }, setElementText: (node, text) => { node.text = text; node.children = [] },
  patchProp: (node, key, _old, value) => { node.props[key] = value; if (key === 'value') { node.value = value; node._value = value } },
  parentNode: node => node.parent, nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1] ?? null,
  insert(node, parent, anchor = null) {
    if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1)
    const index = anchor ? parent.children.indexOf(anchor) : -1
    parent.children.splice(index < 0 ? parent.children.length : index, 0, node); node.parent = parent
  },
  remove(node) { if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1); node.parent = null },
})
const nodes = root => [root, ...root.children.flatMap(nodes)]
const text = node => node.text + node.children.map(text).join('')
const settle = async () => { for (let i = 0; i < 15; i++) { await Promise.resolve(); await nextTick() } }
const reply = data => ({ ok: true, status: 200, json: async () => data })
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
const copy = value => JSON.parse(JSON.stringify(value))
const selection = { match_mode: 'union', department_ids: [], levels: [[], [], []], mode: 'selected', person_ids: [], extra_ids: [] }
const taskFixture = {
  id: 'task-1', name: '战报推送名单', source_kind: 'selection', preset_id: null, selection,
  target_url: 'https://example.feishu.cn/base/base1?table=tbl1', base_token: 'base1', table_id: 'tbl1', table_name: '战报推送名单表',
  field_mapping: { department: 'fld-department', name: 'fld-name', user_id: 'fld-user' }, cron: '0 4 * * *', enabled: false,
  next_run_at: null, active_run_id: null, last_status: null, last_summary: null, last_run_at: null, config_version: 1,
  created_at: '2026-11-17T00:00:00Z', updated_at: '2026-11-17T00:00:00Z',
}
const emptySummary = { source: 0, target: 0, create: 0, update: 0, delete: 0, duplicate: 0, unchanged: 0 }

async function mount(t, overrides = {}) {
  t.mock.timers.enable({ apis: ['setTimeout', 'setInterval', 'Date'], now: 1_795_000_000_000 })
  const old = new Map(['window', 'document', 'Document', 'ShadowRoot', 'HTMLElement', 'fetch'].map(key => [key, globalThis[key]]))
  const body = new Element('body')
  globalThis.document = Object.assign(new EventTarget(), { body, activeElement: body, hidden: false })
  globalThis.Document = EventTarget; globalThis.ShadowRoot = class extends EventTarget {}
  globalThis.window = new EventTarget(); globalThis.HTMLElement = Element
  const state = {
    tasks: [copy(taskFixture)], runs: [], rows: [], logs: [], inspectionFields: [
      { id: 'fld-department', name: '部门', type: 1, writable: true },
      { id: 'fld-name', name: '姓名', type: 1, writable: true },
      { id: 'fld-user', name: 'user_id', type: 1, writable: true },
    ], ...overrides,
  }
  const requests = [], held = []
  globalThis.fetch = (url, options) => {
    const address = new URL(url, 'http://localhost'), path = address.pathname
    const request = { url, path, query: address.searchParams, method: options.method, body: options.body === undefined ? undefined : JSON.parse(options.body), signal: options.signal }
    requests.push(request)
    const waiting = held.find(item => !item.used && item.path === path && (!item.method || item.method === options.method))
    if (waiting) { waiting.used = true; waiting.request = request; return waiting.promise }
    if (path === '/api/table-sync/sources') return Promise.resolve(reply({
      presets: [
        { id: 'public', name: '公共名单', scope: 'public', can_edit: true, selection },
        { id: 'private', name: '私有名单', scope: 'personal', can_edit: true, selection },
      ], directory: { people: [], departments: [], last_sync_at: null, last_sync_error: null, sync_requested: false },
    }))
    if (path === '/api/table-sync/tasks' && options.method === 'GET') {
      const items = state.visibleTaskIds ? state.tasks.filter(task => state.visibleTaskIds.includes(task.id)) : state.tasks
      return Promise.resolve(reply({ items: copy(items), total: state.tasks.length, page: 1 }))
    }
    if (path === '/api/table-sync/tasks' && options.method === 'POST') {
      const task = { ...copy(taskFixture), ...request.body, id: 'task-new' }; state.tasks.push(task)
      return Promise.resolve(reply(copy(task)))
    }
    if (path.endsWith('/enabled')) {
      const task = state.tasks.find(item => path.includes(item.id)); Object.assign(task, request.body)
      task.next_run_at = task.enabled ? '2026-11-18T20:00:00Z' : null
      return Promise.resolve(reply(copy(task)))
    }
    if (/\/tasks\/[^/]+$/.test(path) && options.method === 'PUT') {
      const task = state.tasks.find(item => path.endsWith(item.id)); Object.assign(task, request.body)
      task.config_version++; return Promise.resolve(reply(copy(task)))
    }
    if (/\/tasks\/[^/]+$/.test(path) && options.method === 'GET') return Promise.resolve(reply(copy(state.tasks.find(task => path.endsWith(task.id)))))
    if (/\/tasks\/[^/]+$/.test(path) && options.method === 'DELETE') {
      state.tasks = state.tasks.filter(task => !path.endsWith(task.id)); return Promise.resolve(reply({ ok: true }))
    }
    if (path === '/api/table-sync/inspect') return Promise.resolve(reply({ base_token: 'base1', table_id: 'tbl1', table_name: '战报推送名单表', tables: [{ id: 'tbl1', name: '战报推送名单表' }], fields: state.inspectionFields }))
    if (path === '/api/table-sync/cron') return Promise.resolve(reply({ cron: request.body.cron.trim(), timezone: 'Asia/Shanghai', next_runs: ['2026-11-18T20:00:00Z'] }))
    if (/\/tasks\/[^/]+\/(preview|run)$/.test(path)) {
      const task = state.tasks.find(item => path.includes(item.id))
      const run = { id: 'run-' + (state.runs.length + 1), task_id: task.id, task_name: task.name, kind: path.endsWith('/preview') ? 'preview' : 'sync', trigger: 'manual', status: 'queued', actor_name: '管理员', scheduled_at: null, created_at: '2026-11-17T00:00:00Z', started_at: null, finished_at: null, summary: null, error: null }
      state.runs.unshift(run); task.active_run_id = run.id
      return Promise.resolve(reply(copy(run)))
    }
    if (path === '/api/table-sync/runs') {
      const items = state.runs.filter(run => (!request.query.get('task_id') || run.task_id === request.query.get('task_id')) &&
        (!request.query.get('kind') || run.kind === request.query.get('kind')) && (!request.query.get('status') || request.query.get('status') === 'all' || run.status === request.query.get('status')))
      return Promise.resolve(reply({ items: copy(items), total: items.length, page: Number(request.query.get('page') ?? 1) }))
    }
    if (/\/runs\/[^/]+\/rows$/.test(path)) {
      const items = state.rows.filter(row => request.query.get('action') === 'all' || row.action === request.query.get('action'))
      return Promise.resolve(reply({ items: copy(items), total: items.length, page: Number(request.query.get('page') ?? 1) }))
    }
    if (/\/runs\/[^/]+\/logs$/.test(path)) return Promise.resolve(reply({ items: copy(state.logs), total: state.logs.length, page: Number(request.query.get('page') ?? 1) }))
    if (/\/runs\/[^/]+$/.test(path)) return Promise.resolve(reply(copy(state.runs.find(run => path.endsWith(run.id)))))
    throw new Error(`Unexpected table-sync test request ${options.method} ${url}`)
  }
  const root = new Element('root'), app = renderer.createApp(TableSyncPanel)
  app.config.warnHandler = message => { throw new Error(message) }
  app.mount(root); await settle()
  let unmounted = false
  const unmount = async () => { if (!unmounted) { unmounted = true; app.unmount(); await settle() } }
  t.after(async () => { await unmount(); for (const [key, value] of old) { if (value === undefined) delete globalThis[key]; else globalThis[key] = value } })
  const find = predicate => { const found = nodes(root).filter(predicate); assert.equal(found.length, 1, 'Expected one rendered control'); return found[0] }
  const button = label => find(node => node.tag === 'button' && text(node) === label)
  const click = async label => { button(label).props.onClick(); await settle() }
  const field = id => find(node => node.props.id === id)
  const setField = async (id, value, eventName) => {
    const node = field(id); node.props['onUpdate:modelValue'](value)
    if (eventName && node.props[eventName]) node.props[eventName](new Event(eventName.slice(2).toLowerCase()))
    await settle()
  }
  const component = name => find(node => node.props['data-component'] === name)
  const select = label => find(node => node.tag === 'select' && node.props['aria-label'] === label)
  const changeSelect = async (label, value) => { const node = select(label); node.props['onUpdate:modelValue'](value); await node.props.onChange(); await settle() }
  const openTask = async () => { find(node => node.tag === 'button' && node.props.class?.includes('sync-task') && !node.props.class?.includes('sync-task-title')).props.onClick(); await settle() }
  const advance = async ms => { t.mock.timers.tick(ms); await settle() }
  return { root, requests, state, find, button, click, field, setField, component, select, changeSelect, openTask, advance, unmount,
    hold: (path, method) => { const item = { ...deferred(), path, method, used: false }; held.push(item); return item },
    result: data => reply(data), text: () => text(root),
  }
}

test('sync page loads its own sources and tasks without balances or remote inspection', async t => {
  const h = await mount(t)
  assert.deepEqual(h.requests.map(request => request.path), ['/api/table-sync/sources', '/api/table-sync/tasks'])
  await h.click('新建任务')
  await h.setField('sync-name', '新任务'); await h.setField('sync-url', 'https://example.feishu.cn/base/base1', 'onInput')
  await h.setField('sync-cron', '0 6 * * *', 'onInput'); await h.advance(5000)
  assert.equal(h.requests.filter(request => request.path === '/api/table-sync/inspect').length, 0)
  assert.equal(h.requests.filter(request => request.path === '/api/table-sync/cron').length, 0)
  assert.equal(h.requests.some(request => request.path.includes('balances')), false)
})

test('an empty task-only selection can be saved without creating a public preset', async t => {
  const h = await mount(t)
  await h.click('新建任务'); await h.setField('sync-name', '空名单同步')
  await h.setField('sync-url', taskFixture.target_url, 'onInput'); await h.click('读取目标表')
  assert.equal(h.button('保存任务').props.disabled, false)
  await h.find(node => node.tag === 'form').props.onSubmit(new Event('submit')); await settle()
  const saved = h.requests.find(request => request.path === '/api/table-sync/tasks' && request.method === 'POST')
  assert.deepEqual(saved.body.selection.person_ids, [])
  assert.equal(saved.body.source_kind, 'selection'); assert.equal(saved.body.preset_id, null)
  assert.equal(saved.body.cron, '0 4 * * *'); assert.equal(saved.body.enabled, undefined)
  assert.equal(h.state.tasks.at(-1).enabled, false)
  assert.equal(h.requests.some(request => request.path === '/api/presets'), false)
})

test('public source mode exposes only public presets and uses the selected reference', async t => {
  const h = await mount(t)
  await h.openTask()
  const radio = h.find(node => node.tag === 'input' && node.props.type === 'radio' && node.props.value === 'preset')
  radio.props['onUpdate:modelValue']('preset'); await settle()
  const picker = h.component('RecipientPresetSelect')
  assert.deepEqual(picker.props.presets.map(preset => preset.id), ['public'])
  picker.props['onUpdate:modelValue']('public'); await settle()
  await h.find(node => node.tag === 'form').props.onSubmit(new Event('submit')); await settle()
  const saved = h.requests.find(request => request.method === 'PUT')
  assert.equal(saved.body.source_kind, 'preset'); assert.equal(saved.body.preset_id, 'public')
  assert.equal(saved.body.config_version, 1)
})

test('field inspection offers writable text fields and leaves generated fields unmapped', async t => {
  const h = await mount(t)
  h.state.inspectionFields.push({ id: 'sequence', name: '序号', type: 1005, writable: false }, { id: 'formula', name: '计算', type: 1, writable: false })
  await h.openTask(); await h.click('读取目标表')
  const options = h.field('sync-field-name').options.map(node => node.value)
  assert.ok(options.includes('fld-name')); assert.equal(options.includes('sequence'), false); assert.equal(options.includes('formula'), false)
  await h.setField('sync-field-user_id', 'fld-name')
  assert.equal(h.button('保存任务').props.disabled, true)
})

test('turning automatic execution off still permits an independent manual run', async t => {
  const h = await mount(t)
  await h.openTask(); await h.click('开启定时'); await h.click('关闭定时')
  assert.equal(h.button('手动执行一次').props.disabled, false)
  await h.click('手动执行一次')
  assert.equal(h.state.tasks[0].enabled, false); assert.equal(h.state.tasks[0].cron, '0 4 * * *')
  assert.deepEqual(h.requests.filter(request => request.path.endsWith('/enabled')).map(request => request.body), [{ enabled: true }, { enabled: false }])
  assert.equal(h.requests.filter(request => request.path.endsWith('/run')).length, 1)
  await h.click('任务设置')
  assert.equal(h.find(node => node.tag === 'fieldset').props.disabled, false)
  assert.match(h.text(), /已有任务排队或执行中/)
})

test('preview is queued only on click and supports a valid empty source with deletions', async t => {
  const h = await mount(t)
  await h.openTask(); assert.equal(h.requests.some(request => request.path.endsWith('/preview')), false)
  await h.click('预览同步差异')
  const run = h.state.runs[0]; run.status = 'success'; run.summary = { ...emptySummary, target: 72, delete: 72 }
  h.state.tasks[0].active_run_id = null
  await h.click('刷新详情'); await h.advance(3000)
  assert.match(h.text(), /当前名单为 0 人；执行同步将删除目标表中 72 条记录/)
  assert.equal(h.button('手动执行一次').props.disabled, false)
  assert.equal(h.requests.filter(request => request.path.endsWith('/preview')).length, 1)
})

test('polling stays single flight and pauses while hidden', async t => {
  const h = await mount(t)
  await h.openTask(); await h.click('手动执行一次')
  const pending = h.hold('/api/table-sync/runs/run-1')
  await h.advance(3000)
  assert.ok(pending.used)
  const count = h.requests.length
  await h.advance(9000); assert.equal(h.requests.length, count)
  document.hidden = true
  pending.resolve(h.result(copy(h.state.runs[0]))); await settle()
  await h.advance(9000); assert.equal(h.requests.length, count)
  document.hidden = false; document.dispatchEvent(new Event('visibilitychange')); await settle()
  assert.ok(h.requests.length > count)
})

test('manual row filters cancel a pending poll and ignore its late result', async t => {
  const h = await mount(t)
  await h.openTask(); await h.click('预览同步差异')
  const pending = h.hold('/api/table-sync/runs/run-1/rows')
  await h.advance(3000)
  h.state.rows = [{ action: 'delete', user_id: 'u1', name: '最新人员', department: '研发' }]
  await h.changeSelect('筛选同步明细', 'delete')
  assert.equal(pending.request.signal.aborted, true)
  pending.resolve(h.result({ items: [{ action: 'create', user_id: 'old', name: '过期人员', department: '旧部门' }], total: 1, page: 1 })); await settle()
  assert.match(h.text(), /最新人员/); assert.equal(h.text().includes('过期人员'), false)
})

test('leaving sync page aborts pending reads and stops polling', async t => {
  const h = await mount(t)
  await h.openTask(); await h.click('手动执行一次')
  const pending = h.hold('/api/table-sync/runs/run-1')
  await h.advance(3000); await h.unmount()
  assert.equal(pending.request.signal.aborted, true)
  const count = h.requests.length
  pending.resolve(h.result(copy(h.state.runs[0]))); await settle(); await h.advance(9000)
  assert.equal(h.requests.length, count)
})

test('failure filtering queries the server and includes error logs', async t => {
  const h = await mount(t)
  await h.openTask(); await h.click('手动执行一次')
  h.state.runs[0].status = 'failed'; h.state.runs[0].error = '目标表缺少写入权限'
  h.state.logs = [{ id: 'event-1', level: 'error', stage: 'inspect', message: '字段检查失败', details: { code: 91403 }, created_at: '2026-11-17T01:00:00Z' }]
  await h.changeSelect('筛选执行状态', 'failed'); await h.click('刷新详情')
  assert.equal(h.requests.filter(request => request.path === '/api/table-sync/runs').at(-1).query.get('status'), 'failed')
  assert.match(h.text(), /目标表缺少写入权限/); assert.match(h.text(), /字段检查失败/)
})

test('all execution records remain accessible after a task was removed', async t => {
  const h = await mount(t)
  await h.openTask(); await h.click('手动执行一次')
  h.state.tasks = []; h.state.runs[0].status = 'success'
  await h.click('全部执行记录')
  const query = h.requests.filter(request => request.path === '/api/table-sync/runs').at(-1).query
  assert.equal(query.has('task_id'), false)
  assert.match(h.text(), /全部执行记录/); assert.match(h.text(), /手动执行/)
})

test('background task refresh preserves unsaved form edits', async t => {
  const task = { ...copy(taskFixture), active_run_id: 'external-run' }
  const h = await mount(t, { tasks: [task] })
  await h.openTask(); await h.setField('sync-name', '正在编辑的任务名称')
  await h.advance(3000)
  assert.equal(h.field('sync-name').value, '正在编辑的任务名称')
  assert.match(h.text(), /配置有改动，请先保存/)
})

test('a preset task with no inline selection can switch to a fresh task-only selection', async t => {
  const task = { ...copy(taskFixture), source_kind: 'preset', preset_id: 'public', selection: {} }
  const h = await mount(t, { tasks: [task] })
  await h.openTask()
  const radio = h.find(node => node.tag === 'input' && node.props.type === 'radio' && node.props.value === 'selection')
  radio.props['onUpdate:modelValue']('selection'); await settle()
  assert.deepEqual(h.component('RecipientRangeEditor').props.modelValue, selection)
})

test('a newer server config does not silently replace the editor version', async t => {
  const h = await mount(t)
  await h.openTask(); await h.setField('sync-name', '本地尚未保存')
  h.state.tasks[0].config_version = 2; h.state.tasks[0].name = '其他管理员已修改'
  await h.click('刷新')
  assert.equal(h.field('sync-name').value, '本地尚未保存')
  assert.equal(h.button('保存任务').props.disabled, true)
  assert.equal(h.button('手动执行一次').props.disabled, true)
  assert.match(h.text(), /任务配置已被其他管理员更新/)
  await h.openTask()
  assert.equal(h.field('sync-name').value, '其他管理员已修改')
  assert.equal(h.button('手动执行一次').props.disabled, false)
})

test('selected active tasks continue refreshing when outside the visible task page', async t => {
  const task = { ...copy(taskFixture), active_run_id: 'external-run' }
  const h = await mount(t, { tasks: [task] })
  await h.openTask(); h.state.visibleTaskIds = []
  await h.click('刷新')
  assert.equal(h.button('手动执行一次').props.disabled, true)
  h.state.tasks[0].active_run_id = null
  await h.advance(3000)
  assert.equal(h.button('手动执行一次').props.disabled, false)
  assert.ok(h.requests.some(request => request.path === '/api/table-sync/tasks/task-1'))
})

test('a delayed task poll cannot revert a completed automatic switch', async t => {
  const task = { ...copy(taskFixture), enabled: true, active_run_id: 'external-run' }
  const h = await mount(t, { tasks: [task] })
  await h.openTask()
  const pending = h.hold('/api/table-sync/tasks', 'GET')
  await h.advance(3000); await h.click('关闭定时')
  assert.equal(pending.request.signal.aborted, true)
  pending.resolve(h.result({ items: [task], total: 1, page: 1 })); await settle()
  assert.equal(h.button('开启定时').props['aria-checked'], false)
})

test('changing a saved target clears the previously displayed preview detail', async t => {
  const h = await mount(t)
  await h.openTask(); await h.click('预览同步差异')
  h.state.runs[0].status = 'success'; h.state.runs[0].summary = { ...emptySummary, target: 72, delete: 72 }
  h.state.tasks[0].active_run_id = null
  await h.click('刷新详情'); await h.click('任务设置')
  await h.setField('sync-url', 'https://example.feishu.cn/base/another?table=tbl2', 'onInput')
  await h.click('执行记录')
  assert.equal(h.text().includes('当前名单为 0 人；执行同步将删除目标表中 72 条记录'), false)
  assert.equal(h.button('手动执行一次').props.disabled, true)
})
