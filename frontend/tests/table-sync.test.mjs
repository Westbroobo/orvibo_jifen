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
const children = [...source.matchAll(/import (\w+) from '\.\/[^']+\.vue'/g)].map(match => match[1]).concat('EmployeeAvatar')
writeFileSync(resolve(cache, 'children.mjs'), `import { defineComponent, h } from ${JSON.stringify(vueUrl)};\n` + children.map(name =>
  `export const ${name} = defineComponent({ name: '${name}', inheritAttrs: false, setup(_, { attrs }) { return () => h('test-control', { ...attrs, 'data-component': '${name}' }) } });`,
).join('\n'))
compiled = compiled.replace(/from ['"]vue['"]/g, `from ${JSON.stringify(vueUrl)}`)
compiled = compiled.replace(/import (\w+) from '\.\/[^']+\.vue'/g, 'import { $1 } from "./children.mjs"')
compiled = compiled.replace(/from ['"]\.\.\/(api|types|tableSync)['"]/g, 'from "./$1.mjs"')
writeFileSync(resolve(cache, 'TableSyncPanel.mjs'), transpile(compiled))
const TableSyncPanel = (await import(pathToFileURL(resolve(cache, 'TableSyncPanel.mjs')).href)).default
const rangeSource = readFileSync(resolve(frontend, 'src/components/RecipientListPreview.vue'), 'utf8')
let rangeCompiled = compileScript(parse(rangeSource).descriptor, { id: 'source-range-preview', inlineTemplate: true, templateOptions: { compilerOptions: { hoistStatic: false } } }).content
rangeCompiled = rangeCompiled.replace(/from ['"]vue['"]/g, `from ${JSON.stringify(vueUrl)}`)
rangeCompiled = rangeCompiled.replace(/from ['"]\.\.\/(api|types)['"]/g, 'from "./$1.mjs"')
rangeCompiled = rangeCompiled.replace(/import EmployeeAvatar from '\.\/EmployeeAvatar.vue'/g, 'import { EmployeeAvatar } from "./children.mjs"')
writeFileSync(resolve(cache, 'RecipientListPreview.mjs'), transpile(rangeCompiled))
const RangePreview = (await import(pathToFileURL(resolve(cache, 'RecipientListPreview.mjs')).href)).default

class Element extends EventTarget {
  constructor(tag, text = '') { super(); this.tag = tag; this.tagName = tag.toUpperCase(); this.text = text; this.props = {}; this.children = []; this.parent = null; this.value = ''; this.style = {}; this.isConnected = true; this.selected = false; this.multiple = false }
  get options() { return this.children.filter(child => child.tag === 'option') }
  getAttribute(name) { return this.props[name] ?? null }
  setAttribute(name, value) { this.props[name] = value }
  removeAttribute(name) { delete this.props[name] }
  getRootNode() { return document }
  focus() { document.activeElement = this }
  showModal() { this.props.open = true }
  close() { this.props.open = false }
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

async function mount(t, overrides = {}, rangeProps = null) {
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
    if (path === '/api/ranges/resolve') return Promise.resolve(reply({ people: [], warnings: [] }))
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
  const root = new Element('root'), app = rangeProps ? renderer.createApp(RangePreview, rangeProps) : renderer.createApp(TableSyncPanel)
  document.getElementById = id => nodes(root).find(node => node.props.id === id) ?? null
  app.config.warnHandler = message => { throw new Error(message) }
  app.mount(root); await settle()
  let unmounted = false
  const unmount = async () => { if (!unmounted) { unmounted = true; app.unmount(); await settle() } }
  t.after(async () => { await unmount(); for (const [key, value] of old) { if (value === undefined) delete globalThis[key]; else globalThis[key] = value } })
  const find = predicate => { const found = nodes(root).filter(predicate); assert.equal(found.length, 1, 'Expected one rendered control'); return found[0] }
  const button = label => find(node => node.tag === 'button' && text(node) === label)
  const ariaButton = label => find(node => node.tag === 'button' && node.props['aria-label'] === label)
  const clickAria = async label => { ariaButton(label).props.onClick(new Event('click')); await settle() }
  const taskRow = name => find(node => node.props.role === 'row' && nodes(node).some(child => child.tag === 'b' && text(child) === name))
  const click = async label => { button(label).props.onClick(new Event('click')); await settle() }
  const keydown = async (label, key) => {
    const tablist = find(node => node.props.role === 'tablist' && node.props['aria-label'] === label)
    const event = new Event('keydown', { cancelable: true }); Object.defineProperty(event, 'key', { value: key })
    for (const handler of [tablist.props.onKeydown].flat()) handler(event)
    await settle()
  }
  const field = id => find(node => node.props.id === id)
  const setField = async (id, value, eventName) => {
    const node = field(id); node.props['onUpdate:modelValue'](value)
    if (eventName && node.props[eventName]) node.props[eventName](new Event(eventName.slice(2).toLowerCase()))
    await settle()
  }
  const component = name => find(node => node.props['data-component'] === name)
  const select = label => find(node => node.tag === 'select' && node.props['aria-label'] === label)
  const changeSelect = async (label, value) => { const node = select(label); node.props['onUpdate:modelValue'](value); await node.props.onChange(); await settle() }
  const openTask = async (name = state.tasks[0].name) => {
    const back = nodes(root).find(node => node.tag === 'button' && text(node) === '返回任务列表')
    if (back) { back.props.onClick(); await settle() }
    nodes(taskRow(name)).find(node => node.tag === 'button' && node.props.class === 'sync-task').props.onClick(); await settle()
  }
  const advance = async ms => { t.mock.timers.tick(ms); await settle() }
  return { root, requests, state, find, button, ariaButton, click, clickAria, keydown, taskRow, field, setField, component, select, changeSelect, openTask, advance, unmount,
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
  assert.equal(h.button('保存并返回').props.disabled, false)
  await h.find(node => node.tag === 'form').props.onSubmit(new Event('submit')); await settle()
  const saved = h.requests.find(request => request.path === '/api/table-sync/tasks' && request.method === 'POST')
  assert.deepEqual(saved.body.selection.person_ids, [])
  assert.equal(saved.body.source_kind, 'selection'); assert.equal(saved.body.preset_id, null)
  assert.equal(saved.body.cron, '0 4 * * *'); assert.equal(saved.body.enabled, undefined)
  assert.equal(h.state.tasks.at(-1).enabled, false)
  assert.equal(h.requests.some(request => request.path === '/api/presets'), false)
  assert.equal(nodes(h.root).some(node => node.tag === 'form'), false)
  assert.match(text(h.taskRow('空名单同步')), /未开启定时/)
  assert.match(h.text(), /“空名单同步”已保存/)
  assert.equal(document.activeElement.props.id, 'sync-task-list')
  assert.equal(h.requests.some(request => request.path.endsWith('/run')), false)
})

test('saving an edited task waits for success before returning and prevents duplicate submissions', async t => {
  const h = await mount(t)
  await h.openTask(); await h.setField('sync-name', '更新后的同步任务')
  await h.clickAria('定时计划'); await h.setField('sync-cron', '0 9 * * *')
  const pending = h.hold('/api/table-sync/tasks/task-1', 'PUT')
  const form = h.find(node => node.tag === 'form')
  form.props.onSubmit(new Event('submit')); form.props.onSubmit(new Event('submit')); await settle()
  assert.equal(h.requests.filter(request => request.method === 'PUT').length, 1)
  assert.equal(h.button('正在保存…').props.disabled, true)
  assert.equal(h.ariaButton('定时计划').props['aria-selected'], true)
  const saved = { ...copy(taskFixture), name: '更新后的同步任务', cron: '0 9 * * *', config_version: 2 }
  Object.assign(h.state.tasks[0], saved)
  pending.resolve(h.result(copy(saved))); await settle()
  assert.equal(nodes(h.root).some(node => node.tag === 'form'), false)
  assert.match(text(h.taskRow(saved.name)), /0 9 \* \* \*/)
  assert.match(h.text(), /“更新后的同步任务”已保存/)
  assert.equal(document.activeElement.props.id, 'sync-task-list')
  assert.equal(h.text().includes('未保存的配置'), false)
  await h.openTask(saved.name)
  assert.equal(h.field('sync-cron').value, saved.cron)
  assert.equal(h.button('手动执行一次').props.disabled, false)
})

test('a failed save preserves the current section and complete draft for retry', async t => {
  const h = await mount(t)
  await h.openTask(); await h.setField('sync-name', '保存失败后保留的草稿')
  const chosen = { ...copy(selection), department_ids: ['department-1'], person_ids: ['person-1'] }
  h.component('RecipientRangeEditor').props['onUpdate:modelValue'](chosen); await settle()
  await h.clickAria('定时计划'); await h.setField('sync-cron', '0 9 * * *')
  const pending = h.hold('/api/table-sync/tasks/task-1', 'PUT')
  h.find(node => node.tag === 'form').props.onSubmit(new Event('submit')); await settle()
  pending.resolve({ ok: false, status: 500, json: async () => ({ detail: '保存失败，请重试' }) }); await settle()
  assert.equal(h.ariaButton('定时计划').props['aria-selected'], true)
  assert.equal(h.field('sync-name').value, '保存失败后保留的草稿')
  assert.equal(h.field('sync-cron').value, '0 9 * * *')
  assert.deepEqual(h.component('RecipientRangeEditor').props.modelValue, chosen)
  assert.match(h.text(), /保存失败，请重试/)
  assert.equal(h.button('保存并返回').props.disabled, false)
  assert.equal(h.text().includes('”已保存'), false)
  h.find(node => node.tag === 'form').props.onSubmit(new Event('submit')); await settle()
  assert.equal(nodes(h.root).some(node => node.tag === 'form'), false)
  assert.match(text(h.taskRow('保存失败后保留的草稿')), /0 9 \* \* \*/)
})

test('a failed list refresh after saving keeps the saved task visible and returns to the list', async t => {
  const h = await mount(t)
  await h.openTask(); await h.setField('sync-name', '已保存但列表刷新失败')
  const pending = h.hold('/api/table-sync/tasks', 'GET')
  h.find(node => node.tag === 'form').props.onSubmit(new Event('submit')); await settle()
  assert.equal(pending.used, true)
  assert.equal(nodes(h.root).some(node => node.tag === 'form'), false)
  assert.ok(h.taskRow('已保存但列表刷新失败'))
  pending.resolve({ ok: false, status: 500, json: async () => ({ detail: '暂时无法刷新列表' }) }); await settle()
  assert.match(h.text(), /“已保存但列表刷新失败”已保存/)
  assert.match(h.text(), /暂时无法刷新列表/)
  assert.ok(h.taskRow('已保存但列表刷新失败'))
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
  assert.equal(h.button('保存并返回').props.disabled, true)
})

test('configuration sections preserve selected people and fields without automatic inspection or writes', async t => {
  const h = await mount(t)
  await h.openTask(); await h.setField('sync-name', '分区中的配置草稿')
  const editor = h.component('RecipientRangeEditor')
  const chosen = { ...copy(selection), department_ids: ['department-1'], person_ids: ['person-1'], extra_ids: ['person-2'] }
  editor.props['onUpdate:modelValue'](chosen); await settle()
  const requestCount = h.requests.length
  await h.clickAria('目标多维表')
  await h.setField('sync-url', 'https://example.feishu.cn/base/another?table=tbl2', 'onInput')
  await h.setField('sync-field-name', 'target-name')
  await h.clickAria('定时计划'); await h.setField('sync-cron', '0 9 * * 1-5', 'onInput')
  await h.clickAria('人员来源')
  assert.equal(h.component('RecipientRangeEditor'), editor)
  assert.deepEqual(h.component('RecipientRangeEditor').props.modelValue, chosen)
  await h.clickAria('目标多维表')
  assert.equal(h.field('sync-url').value, 'https://example.feishu.cn/base/another?table=tbl2')
  assert.ok(h.field('sync-field-name').options.some(option => option.value === 'target-name'))
  await h.clickAria('定时计划')
  assert.equal(h.field('sync-cron').value, '0 9 * * 1-5')
  assert.equal(h.field('sync-name').value, '分区中的配置草稿')
  await h.advance(6000)
  assert.equal(h.requests.length, requestCount)
})

test('saving from a configuration section submits the complete source target and schedule together', async t => {
  const h = await mount(t)
  await h.click('新建任务'); await h.setField('sync-name', '完整分区配置')
  const chosen = { ...copy(selection), department_ids: ['department-1'], person_ids: ['person-1'], extra_ids: ['person-2'] }
  h.component('RecipientRangeEditor').props['onUpdate:modelValue'](chosen); await settle()
  await h.clickAria('目标多维表')
  await h.setField('sync-url', taskFixture.target_url, 'onInput'); await h.click('读取目标表')
  await h.clickAria('定时计划'); await h.setField('sync-cron', '0 9 * * 1-5', 'onInput')
  await h.clickAria('人员来源')
  assert.equal(h.button('保存并返回').props.disabled, false)
  await h.find(node => node.tag === 'form').props.onSubmit(new Event('submit')); await settle()
  const saves = h.requests.filter(request => request.path === '/api/table-sync/tasks' && request.method === 'POST')
  assert.equal(saves.length, 1)
  assert.deepEqual(saves[0].body, {
    name: '完整分区配置', source_kind: 'selection', preset_id: null, selection: chosen,
    target_url: taskFixture.target_url, table_id: 'tbl1', field_mapping: taskFixture.field_mapping, cron: '0 9 * * 1-5',
  })
  assert.equal(h.requests.filter(request => request.path === '/api/table-sync/inspect').length, 1)
  assert.equal(h.requests.some(request => request.path === '/api/table-sync/cron'), false)
})

test('configuration section keyboard navigation keeps focus and draft independent of page tabs', async t => {
  const h = await mount(t)
  await h.openTask(); await h.setField('sync-name', '键盘切换保留草稿')
  const editor = h.component('RecipientRangeEditor')
  const chosen = { ...copy(selection), person_ids: ['keyboard-person'] }
  editor.props['onUpdate:modelValue'](chosen); await settle()
  const requestCount = h.requests.length
  for (const [key, expected] of [['ArrowRight', '目标多维表'], ['End', '定时计划'], ['Home', '人员来源'], ['ArrowLeft', '定时计划'], ['ArrowLeft', '目标多维表']]) {
    await h.keydown('任务配置分区', key)
    assert.equal(h.ariaButton(expected).props['aria-selected'], true)
    assert.equal(document.activeElement, h.ariaButton(expected))
    assert.equal(h.button('同步任务').props['aria-selected'], true)
    assert.equal(h.button('执行记录').props['aria-selected'], false)
  }
  assert.equal(h.field('sync-name').value, '键盘切换保留草稿')
  assert.equal(h.component('RecipientRangeEditor'), editor)
  assert.deepEqual(h.component('RecipientRangeEditor').props.modelValue, chosen)
  assert.equal(h.requests.length, requestCount)
})

test('turning automatic execution off still permits an independent manual run', async t => {
  const h = await mount(t)
  await h.openTask(); await h.click('开启定时'); await h.click('关闭定时')
  assert.equal(h.button('手动执行一次').props.disabled, false)
  await h.click('手动执行一次')
  assert.equal(h.state.tasks[0].enabled, false); assert.equal(h.state.tasks[0].cron, '0 4 * * *')
  assert.deepEqual(h.requests.filter(request => request.path.endsWith('/enabled')).map(request => request.body), [{ enabled: true }, { enabled: false }])
  assert.equal(h.requests.filter(request => request.path.endsWith('/run')).length, 1)
  await h.click('同步任务')
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
  await h.click('同步任务')
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
  await h.click('全部任务')
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

test('switching page tabs preserves an unsaved task and keeps global history independent', async t => {
  const h = await mount(t)
  await h.openTask(); await h.setField('sync-name', '尚未保存的任务配置')
  assert.equal(h.requests.some(request => request.path === '/api/table-sync/runs'), false)
  await h.click('执行记录')
  assert.equal(h.button('执行记录').props['aria-selected'], true)
  assert.equal(h.requests.filter(request => request.path === '/api/table-sync/runs').at(-1).query.has('task_id'), false)
  await h.click('同步任务')
  assert.equal(h.field('sync-name').value, '尚未保存的任务配置')
  assert.equal(h.button('手动执行一次').props.disabled, true)
  await h.click('新建任务'); await h.click('放弃修改并继续'); await h.setField('sync-name', '新任务草稿')
  await h.click('执行记录'); await h.click('同步任务')
  assert.equal(h.field('sync-name').value, '新任务草稿')
})

test('task history can expand to all tasks without discarding the current configuration', async t => {
  const h = await mount(t)
  await h.openTask(); await h.setField('sync-cron', '0 9 * * *')
  await h.click('查看执行记录')
  assert.equal(h.requests.filter(request => request.path === '/api/table-sync/runs').at(-1).query.get('task_id'), 'task-1')
  await h.click('全部任务')
  assert.equal(h.requests.filter(request => request.path === '/api/table-sync/runs').at(-1).query.has('task_id'), false)
  await h.click('同步任务')
  assert.equal(h.field('sync-cron').value, '0 9 * * *')
})

test('returning to the overview keeps a draft and replacing it requires an explicit choice', async t => {
  const h = await mount(t)
  await h.openTask(); await h.setField('sync-name', '保留中的任务草稿')
  await h.click('返回任务列表')
  assert.match(h.text(), /未保存的配置：保留中的任务草稿/)
  await h.click('继续编辑')
  assert.equal(h.field('sync-name').value, '保留中的任务草稿')
  await h.click('新建任务'); await h.click('继续编辑')
  assert.equal(h.field('sync-name').value, '保留中的任务草稿')
  assert.equal(h.requests.some(request => request.method === 'POST' || request.method === 'PUT'), false)
  await h.click('新建任务'); await h.click('放弃修改并继续')
  assert.equal(h.field('sync-name').value, '')
  assert.equal(h.text().includes('查看执行记录'), false)
  assert.equal(h.requests.some(request => request.method === 'POST' || request.method === 'PUT'), false)
})

test('overview history opens the chosen task records while preserving an unrelated draft', async t => {
  const h = await mount(t)
  await h.click('新建任务'); await h.setField('sync-name', '新任务未保存草稿')
  await h.click('返回任务列表'); await h.click('查看记录')
  assert.equal(h.requests.filter(request => request.path === '/api/table-sync/runs').at(-1).query.get('task_id'), 'task-1')
  assert.equal(h.button('执行记录').props['aria-selected'], true)
  await h.click('同步任务'); await h.click('继续编辑')
  assert.equal(h.field('sync-name').value, '新任务未保存草稿')
  assert.equal(h.requests.some(request => request.method === 'POST' || request.method === 'PUT'), false)
})

test('viewing a task range uses saved selection and preserves an unrelated unsaved draft without requests', async t => {
  const savedSelection = { ...copy(selection), department_ids: ['saved-dept'], person_ids: ['saved-person'] }
  const h = await mount(t, { tasks: [{ ...copy(taskFixture), selection: savedSelection }] })
  await h.openTask(); await h.setField('sync-name', '仍在编辑的草稿')
  h.component('RecipientRangeEditor').props['onUpdate:modelValue']({ ...copy(selection), person_ids: ['unsaved-person'] }); await settle()
  await h.click('返回任务列表')
  const initialRequests = h.requests.length
  await h.clickAria(`查看名单范围：${taskFixture.name}`)
  const preview = h.component('RecipientListPreview')
  assert.deepEqual(preview.props.preset.selection, savedSelection)
  assert.equal(preview.props.preset.can_edit, false)
  assert.equal(preview.props['composition-only'], '')
  assert.equal(preview.props['scope-label'], '任务专属名单')
  assert.equal(h.requests.length, initialRequests)
  preview.props.onClose(); await settle()
  assert.equal(document.activeElement.props.id, 'sync-source-preview-task-1')
  await h.click('继续编辑')
  assert.equal(h.field('sync-name').value, '仍在编辑的草稿')
  assert.deepEqual(h.component('RecipientRangeEditor').props.modelValue.person_ids, ['unsaved-person'])
})

test('viewing a referenced public range uses the preset and explains a missing reference', async t => {
  const h = await mount(t, { tasks: [{ ...copy(taskFixture), source_kind: 'preset', preset_id: 'public', selection: {} }] })
  await h.clickAria(`查看名单范围：${taskFixture.name}`)
  const preview = h.component('RecipientListPreview')
  assert.deepEqual(preview.props.preset.selection, selection)
  assert.equal(preview.props['scope-label'], '公共名单 · 公共名单')
  preview.props.onClose(); await settle()
  h.state.tasks[0].preset_id = 'missing'
  await h.click('刷新'); await h.clickAria(`查看名单范围：${taskFixture.name}`)
  assert.match(h.text(), /引用的公共名单已不存在或未能加载/)
  assert.equal(nodes(h.root).some(node => node.props['data-component'] === 'RecipientListPreview'), false)
  assert.equal(h.requests.some(request => request.method === 'POST'), false)
})

test('the real range-only dialog shows department paths and specified people without resolving or enqueueing', async t => {
  const range = { ...copy(selection), department_ids: ['d1'], person_ids: ['p1'], extra_ids: ['p1', 'p2'] }
  const directory = { people: [
    { id: 'p1', name: '张三', status: 'active', paths: [], avatar_url: '' },
    { id: 'p2', name: '李四', status: 'resigned', paths: [], avatar_url: '' },
  ], departments: [{ id: 'd1', name: '研发组', path_ids: ['d0', 'd1'], path_names: ['技术中心', '研发组'] }] }
  let closed = false
  const h = await mount(t, {}, { preset: { id: 'range', name: '战报名单', scope: 'personal', can_edit: false, selection: range }, directory, compositionOnly: true, scopeLabel: '任务专属名单', onClose: () => { closed = true } })
  assert.match(h.text(), /名单范围/); assert.match(h.text(), /技术中心 \/ 研发组/)
  assert.match(h.text(), /部门全员/); assert.match(h.text(), /指定人员/)
  assert.match(h.text(), /张三/); assert.match(h.text(), /李四（离职）/)
  assert.equal((h.text().match(/张三/g) ?? []).length, 1)
  assert.equal(h.text().includes('正在匹配人员'), false)
  assert.equal(h.text().includes('位通知对象'), false)
  assert.equal(h.requests.length, 0)
  await h.clickAria('关闭名单范围')
  assert.equal(closed, true)
})

test('the regular list preview still resolves notification people by default', async t => {
  const h = await mount(t, {}, { preset: { id: 'regular', name: '原名单预览', scope: 'public', can_edit: false, selection: copy(selection) }, directory: { people: [], departments: [] } })
  assert.equal(h.requests.length, 1)
  assert.equal(h.requests[0].path, '/api/ranges/resolve')
  assert.match(h.text(), /名单预览/); assert.match(h.text(), /位通知对象/)
})

test('overview schedule switches update the next run independently of manual execution and cron', async t => {
  const h = await mount(t)
  const label = `${taskFixture.name}的定时执行开关`
  assert.equal(h.ariaButton(label).props.role, 'switch')
  assert.equal(h.ariaButton(label).props['aria-checked'], false)
  assert.match(text(h.taskRow(taskFixture.name)), /未开启定时/)
  await h.clickAria(label)
  assert.equal(h.ariaButton(label).props['aria-checked'], true)
  const time = nodes(h.taskRow(taskFixture.name)).find(node => node.tag === 'time')
  assert.equal(time.props.datetime, '2026-11-18T20:00:00Z')
  assert.ok(time.children.some(node => node.tag === 'span' && text(node) === '2026/11/19'))
  assert.ok(time.children.some(node => node.tag === 'small' && text(node) === '04:00:00'))
  await h.clickAria(label)
  assert.equal(h.ariaButton(label).props['aria-checked'], false)
  assert.match(text(h.taskRow(taskFixture.name)), /未开启定时/)
  assert.equal(h.ariaButton(`执行一次：${taskFixture.name}`).props.disabled, false)
  assert.equal(h.state.tasks[0].cron, '0 4 * * *')
  assert.equal(h.state.tasks[0].next_run_at, null)
  assert.deepEqual(h.requests.filter(request => request.path.endsWith('/enabled')).map(request => request.body), [{ enabled: true }, { enabled: false }])
  assert.equal(h.button('同步任务').props['aria-selected'], true)
  assert.equal(h.requests.some(request => request.path === '/api/table-sync/runs'), false)
})

test('scheduled rows refresh when due, throttle a stalled schedule and pause while hidden', async t => {
  const now = 1_795_000_000_000, due = new Date(now + 6000).toISOString()
  const h = await mount(t, { tasks: [{ ...copy(taskFixture), enabled: true, next_run_at: due }] })
  const taskReads = () => h.requests.filter(request => request.path === '/api/table-sync/tasks' && request.method === 'GET').length
  const initialReads = taskReads()
  await h.advance(3000)
  assert.equal(taskReads(), initialReads)
  const next = new Date(now + 120_000).toISOString()
  Object.assign(h.state.tasks[0], { next_run_at: next, last_status: 'success', last_run_at: due, active_run_id: null })
  await h.advance(3000)
  assert.equal(taskReads(), initialReads + 1)
  assert.ok(nodes(h.taskRow(taskFixture.name)).some(node => node.tag === 'time' && node.props.datetime === next))
  assert.match(text(h.taskRow(taskFixture.name)), /已完成/)
  assert.equal(h.ariaButton(`执行一次：${taskFixture.name}`).props.disabled, false)
  assert.equal(h.button('同步任务').props['aria-selected'], true)
  assert.equal(h.requests.some(request => request.path === '/api/table-sync/runs'), false)

  h.state.tasks[0].next_run_at = due
  await h.click('刷新')
  const stalledReads = taskReads()
  await h.advance(27000)
  assert.equal(taskReads(), stalledReads)
  document.hidden = true
  await h.advance(3000)
  assert.equal(taskReads(), stalledReads)
  document.hidden = false; document.dispatchEvent(new Event('visibilitychange')); await settle()
  assert.equal(taskReads(), stalledReads + 1)
  await h.advance(27000)
  assert.equal(taskReads(), stalledReads + 1)
  h.state.tasks[0].next_run_at = next
  await h.advance(3000)
  assert.equal(taskReads(), stalledReads + 2)
  assert.ok(nodes(h.taskRow(taskFixture.name)).some(node => node.tag === 'time' && node.props.datetime === next))
})

test('overview execution stays on the list and deduplicates submitting and active runs', async t => {
  const h = await mount(t)
  const label = `执行一次：${taskFixture.name}`
  const pending = h.hold('/api/table-sync/tasks/task-1/run', 'POST')
  const action = h.ariaButton(label)
  action.props.onClick(); action.props.onClick(); await settle()
  assert.equal(pending.used, true)
  assert.equal(h.ariaButton(label).props.disabled, true)
  assert.equal(text(h.ariaButton(label)), '正在提交…')
  const run = { id: 'run-queued', task_id: 'task-1', task_name: taskFixture.name, kind: 'sync', trigger: 'manual', status: 'queued', actor_name: '管理员', created_at: '2026-11-17T00:00:00Z', started_at: null, finished_at: null, summary: null, error: null }
  h.state.tasks[0].active_run_id = run.id; h.state.runs.push(run)
  pending.resolve(h.result(copy(run))); await settle()
  assert.equal(h.ariaButton(label).props.disabled, true)
  h.ariaButton(label).props.onClick(); await settle()
  assert.equal(h.requests.filter(request => request.path.endsWith('/run')).length, 1)
  assert.equal(h.button('同步任务').props['aria-selected'], true)
  assert.equal(h.requests.some(request => request.path === '/api/table-sync/runs'), false)
  assert.equal(h.state.tasks[0].enabled, false)
  assert.equal(h.state.tasks[0].cron, '0 4 * * *')
})

test('row actions on another task preserve the current unsaved editor configuration', async t => {
  const second = { ...copy(taskFixture), id: 'task-2', name: '客服名单同步', table_id: 'tbl2' }
  const h = await mount(t, { tasks: [copy(taskFixture), second] })
  await h.openTask(); await h.setField('sync-name', '正在编辑但尚未保存')
  await h.setField('sync-cron', '0 9 * * *'); await h.click('返回任务列表')
  await h.clickAria(`${second.name}的定时执行开关`)
  await h.clickAria(`执行一次：${second.name}`)
  assert.equal(h.button('同步任务').props['aria-selected'], true)
  assert.deepEqual(h.requests.filter(request => request.method === 'POST' && request.path.endsWith('/run')).map(request => request.path), ['/api/table-sync/tasks/task-2/run'])
  await h.click('继续编辑')
  assert.equal(h.field('sync-name').value, '正在编辑但尚未保存')
  assert.equal(h.field('sync-cron').value, '0 9 * * *')
  assert.equal(h.button('手动执行一次').props.disabled, true)
  assert.equal(h.state.tasks[0].enabled, false)
  assert.equal(h.state.tasks[0].active_run_id, null)
})

test('overview execution cannot bypass dirty or stale configuration checks for the edited task', async t => {
  const h = await mount(t)
  const label = `执行一次：${taskFixture.name}`
  await h.openTask(); await h.setField('sync-cron', '0 9 * * *'); await h.click('返回任务列表')
  assert.equal(h.ariaButton(label).props.disabled, true)
  assert.match(h.text(), /先保存/)
  h.ariaButton(label).props.onClick(); await settle()
  assert.equal(h.requests.some(request => request.path.endsWith('/run')), false)
  await h.openTask(); await h.click('放弃修改并继续')
  h.state.tasks[0].config_version = 2
  await h.click('刷新'); await h.click('返回任务列表')
  assert.equal(h.ariaButton(label).props.disabled, true)
  h.ariaButton(label).props.onClick(); await settle()
  assert.equal(h.requests.some(request => request.path.endsWith('/run')), false)
})

test('failed row operations preserve server state and display the error on the affected task', async t => {
  const h = await mount(t)
  const switchLabel = `${taskFixture.name}的定时执行开关`, runLabel = `执行一次：${taskFixture.name}`
  const toggle = h.hold('/api/table-sync/tasks/task-1/enabled', 'PATCH')
  await h.clickAria(switchLabel)
  toggle.resolve({ ok: false, status: 500, json: async () => ({ detail: '保存定时状态失败' }) }); await settle()
  assert.equal(h.ariaButton(switchLabel).props['aria-checked'], false)
  assert.match(text(h.taskRow(taskFixture.name)), /保存定时状态失败/)
  assert.match(text(h.taskRow(taskFixture.name)), /未开启定时/)
  const execution = h.hold('/api/table-sync/tasks/task-1/run', 'POST')
  await h.clickAria(runLabel)
  execution.resolve({ ok: false, status: 500, json: async () => ({ detail: '提交执行失败' }) }); await settle()
  assert.equal(h.ariaButton(runLabel).props.disabled, false)
  assert.match(text(h.taskRow(taskFixture.name)), /提交执行失败/)
  assert.equal(h.state.tasks[0].enabled, false)
  assert.equal(h.state.tasks[0].active_run_id, null)
  assert.equal(h.button('同步任务').props['aria-selected'], true)
})

test('late polling cannot undo a successful row schedule change or execution', async t => {
  const other = { ...copy(taskFixture), id: 'task-2', name: '其他执行中的任务', active_run_id: 'external-run' }
  const h = await mount(t, { tasks: [copy(taskFixture), other] })
  const staleBeforeToggle = copy(h.state.tasks)
  const togglePoll = h.hold('/api/table-sync/tasks', 'GET')
  await h.advance(3000); await h.clickAria(`${taskFixture.name}的定时执行开关`)
  assert.equal(togglePoll.request.signal.aborted, true)
  togglePoll.resolve(h.result({ items: staleBeforeToggle, total: 2, page: 1 })); await settle()
  assert.equal(h.ariaButton(`${taskFixture.name}的定时执行开关`).props['aria-checked'], true)
  const staleBeforeRun = copy(h.state.tasks)
  const runPoll = h.hold('/api/table-sync/tasks', 'GET')
  await h.advance(3000); await h.clickAria(`执行一次：${taskFixture.name}`)
  assert.equal(runPoll.request.signal.aborted, true)
  runPoll.resolve(h.result({ items: staleBeforeRun, total: 2, page: 1 })); await settle()
  assert.equal(h.ariaButton(`执行一次：${taskFixture.name}`).props.disabled, true)
  assert.equal(h.ariaButton(`${taskFixture.name}的定时执行开关`).props['aria-checked'], true)
  assert.equal(h.requests.filter(request => request.path.endsWith('/run')).length, 1)
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
  assert.equal(h.button('保存并返回').props.disabled, true)
  assert.equal(h.button('手动执行一次').props.disabled, true)
  assert.match(h.text(), /任务配置已被其他管理员更新/)
  await h.openTask(); await h.click('放弃修改并继续')
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
  await h.click('刷新详情'); await h.click('同步任务')
  await h.setField('sync-url', 'https://example.feishu.cn/base/another?table=tbl2', 'onInput')
  await h.click('执行记录')
  assert.equal(h.text().includes('当前名单为 0 人；执行同步将删除目标表中 72 条记录'), false)
  await h.click('同步任务')
  assert.equal(h.button('手动执行一次').props.disabled, true)
})
