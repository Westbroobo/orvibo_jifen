import assert from 'node:assert/strict'
import { test } from 'node:test'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer, nextTick } from 'vue'

// Mount the real App template and setup code without a browser or new test dependencies.
// Child controls are event stubs; native-browser focus behavior remains a browser QA concern.
const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const cache = resolve(frontend, '../.cache/preview-component-tests')
mkdirSync(cache, { recursive: true })
const vueUrl = import.meta.resolve('vue')
const transpile = source => ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText
for (const name of ['api', 'types', 'roles', 'historyPresentation']) {
  writeFileSync(resolve(cache, `${name}.mjs`), transpile(readFileSync(resolve(frontend, `src/${name}.ts`), 'utf8')))
}
const source = readFileSync(resolve(frontend, 'src/App.vue'), 'utf8')
const { descriptor } = parse(source)
let compiled = compileScript(descriptor, { id: 'preview-regression', inlineTemplate: true }).content
const children = [...source.matchAll(/import (\w+) from '\.\/components\/[^']+\.vue'/g)].map(match => match[1])
writeFileSync(resolve(cache, 'children.mjs'), `import { defineComponent, h } from ${JSON.stringify(vueUrl)};\n` + children.map(name =>
  `export const ${name} = defineComponent({ name: '${name}', inheritAttrs: false, setup(_, { attrs, expose }) { expose({ focusClose() {} }); return () => h('test-control', { ...attrs, 'data-component': '${name}' }) } });`,
).join('\n'))
compiled = compiled.replace(/from ['"]vue['"]/g, `from ${JSON.stringify(vueUrl)}`)
// Exercise component lifecycle without CSS transition timers in the custom renderer.
compiled = compiled.replace(/\bTransition as _Transition\b/g, 'BaseTransition as _Transition')
compiled = compiled.replace(/import (\w+) from '\.\/components\/[^']+\.vue'/g, 'import { $1 } from "./children.mjs"')
compiled = compiled.replace(/from ['"]\.\/(api|types|roles)['"]/g, 'from "./$1.mjs"')
writeFileSync(resolve(cache, 'App.mjs'), transpile(compiled))
const App = (await import(pathToFileURL(resolve(cache, 'App.mjs')).href)).default
const dialogSource = readFileSync(resolve(frontend, 'src/components/BatchResultDialog.vue'), 'utf8')
const dialogDescriptor = parse(dialogSource).descriptor
let dialogCompiled = compileScript(dialogDescriptor, { id: 'delivery-filter-regression', inlineTemplate: true }).content
dialogCompiled = dialogCompiled.replace(/from ['"]vue['"]/g, `from ${JSON.stringify(vueUrl)}`)
dialogCompiled = dialogCompiled.replace(/from ['"]\.\.\/(types|historyPresentation)['"]/g, 'from "./$1.mjs"')
dialogCompiled = dialogCompiled.replace(/import EmployeeAvatar from '\.\/EmployeeAvatar.vue'/g, 'import { EmployeeAvatar } from "./children.mjs"')
writeFileSync(resolve(cache, 'BatchResultDialog.mjs'), transpile(dialogCompiled))
const BatchResultDialog = (await import(pathToFileURL(resolve(cache, 'BatchResultDialog.mjs')).href)).default

class Element extends EventTarget {
  constructor(tag, text = '') { super(); this.tag = tag; this.text = text; this.props = {}; this.children = []; this.parent = null; this.value = ''; this.style = {}; this.classList = { add() {}, remove() {} }; this.isConnected = true; this.scrollTop = 0 }
  getAttribute(name) { return this.props[name] ?? null }
  setAttribute(name, value) { this.props[name] = value }
  removeAttribute(name) { delete this.props[name] }
  focus() { document.activeElement = this }
  blur() { if (document.activeElement === this) document.activeElement = document.body }
  scrollIntoView() {}
  getBoundingClientRect() { return { top: 0 } }
}
const renderer = createRenderer({
  createElement: tag => new Element(tag),
  createText: text => new Element('#text', text),
  createComment: text => new Element('#comment', text),
  setText: (node, text) => { node.text = text },
  setElementText: (node, text) => { node.text = text; node.children = [] },
  patchProp: (node, key, _previous, value) => { node.props[key] = value },
  parentNode: node => node.parent,
  nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1] ?? null,
  insert(node, parent, anchor = null) {
    if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1)
    const index = anchor ? parent.children.indexOf(anchor) : -1
    parent.children.splice(index < 0 ? parent.children.length : index, 0, node); node.parent = parent
  },
  remove(node) { if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1); node.parent = null },
})
const people = [{ id: 'p1', open_id: 'ou_test_1', name: '张三', status: 'active', role: 'operator', avatar_url: '', paths: [] }]
const selection = { match_mode: 'union', department_ids: [], levels: [[], [], []], mode: 'selected', person_ids: ['p1'], extra_ids: [] }
const user = { ...people[0], csrf_token: 'test-only', role_name: '操作员', history_scope: 'own', ledger_scope: 'own', ledger_department_ids: [], permissions: ['adjustments.write', 'history.read'], can_access_system: true, can_manage: false, can_configure_roles: false, owner_notice: '', demo_mode: true }
const reply = (data, status = 200) => ({ ok: status < 400, status, json: async () => data })
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
const settle = async () => { for (let index = 0; index < 10; index++) { await Promise.resolve(); await nextTick() } }
const nodes = root => [root, ...root.children.flatMap(nodes)]
const text = node => node.text + node.children.map(text).join('')

async function mount(t) {
  t.mock.timers.enable({ apis: ['setTimeout', 'setInterval', 'Date'], now: 1_795_000_000_000 })
  const old = new Map(['window', 'document', 'location', 'HTMLElement', 'requestAnimationFrame', 'cancelAnimationFrame', 'fetch'].map(key => [key, globalThis[key]]))
  const body = new Element('body')
  globalThis.document = { body, activeElement: body }
  globalThis.window = Object.assign(new EventTarget(), { getComputedStyle: () => ({ transitionDelay: '0s', transitionDuration: '0s', animationDelay: '0s', animationDuration: '0s' }) })
  globalThis.location = { search: '', replace() { throw new Error('Unexpected login redirect') } }
  globalThis.HTMLElement = Element
  globalThis.requestAnimationFrame = callback => setTimeout(callback, 0)
  globalThis.cancelAnimationFrame = clearTimeout
  const previews = [], commits = [], detailRequests = [], retryRequests = [], dialogs = []
  let currentUser = user, identityReads = 0
  globalThis.fetch = (url, options) => {
    const path = url.split('?')[0]
    if (path === '/api/public-config') return Promise.resolve(reply({ demo_mode: true }))
    if (path === '/api/auth/me') { identityReads++; return Promise.resolve(reply(currentUser)) }
    if (path === '/api/directory') return Promise.resolve(reply({ people, departments: [], last_sync_at: null, last_sync_error: null, sync_requested: false }))
    if (path === '/api/balances') return Promise.resolve(reply({ month: '2026-11', totals: { p1: 60 }, versions: { p1: 0 } }))
    if (path === '/api/presets') return Promise.resolve(reply([{ id: 'preset', name: '测试名单', scope: 'personal', can_edit: true, selection }]))
    if (path === '/api/ranges/resolve') return Promise.resolve(reply({ people: JSON.parse(options.body).person_ids?.length ? people : [], warnings: [] }))
    if (path === '/api/adjustments/preview' || path === '/api/adjustments' && options.method === 'POST') {
      const pending = { ...deferred(), body: JSON.parse(options.body), signal: options.signal }
      ;(path.endsWith('/preview') ? previews : commits).push(pending)
      return pending.promise
    }
    if (path === '/api/adjustments') return Promise.resolve(reply({ items: [], total: 0, page: 1 }))
    if (path.startsWith('/api/adjustments/')) {
      const query = new URL(url, 'http://localhost').searchParams
      const filter = query.get('delivery_status') ?? 'all'
      const page = Number(query.get('page') ?? 1)
      detailRequests.push({ id: path.split('/').at(-1), filter, page })
      const statuses = retryRequests.length ? { sent: 519 } : { sent: 314, failed: 205 }
      return Promise.resolve(reply({
        id: path.split('/').at(-1), snapshot: { rows: [], recipients: people, message_count: 519, month: '2026-11', delta: 5, reason: '测试批次', operator_name: '张三' },
        scores: [], created_at: new Date(Date.now()).toISOString(), deliveries: [], statuses,
        total: filter === 'all' ? 519 : statuses[filter] ?? 0, page, delivery_status: filter,
        recall_statuses: {}, recall_available: 0, cancelled_scores: 0, can_recall: false, can_retry: true,
      }))
    }
    if (path.startsWith('/api/deliveries/') && path.endsWith('/retry')) { retryRequests.push(path); return Promise.resolve(reply({ ok: true })) }
    if (path === '/api/auth/logout') return Promise.resolve(reply({ ok: true }))
    throw new Error(`Unexpected test request ${url}`)
  }
  const root = new Element('root'), app = renderer.createApp(App)
  app.config.warnHandler = message => { throw new Error(message) }
  app.mount(root)
  t.after(async () => { dialogs.forEach(dialog => dialog.unmount()); app.unmount(); await settle(); for (const [key, value] of old) { if (value === undefined) delete globalThis[key]; else globalThis[key] = value } })
  await settle()
  const find = predicate => { const found = nodes(root).filter(predicate); assert.equal(found.length, 1, 'Expected one rendered control'); return found[0] }
  const component = name => find(node => node.props['data-component'] === name)
  const fieldset = () => find(node => node.tag === 'fieldset')
  const reason = () => find(node => node.props.id === 'reason')
  const input = async value => { reason().value = value; reason().dispatchEvent(new Event('input')); await settle() }
  const advance = async ms => { t.mock.timers.tick(ms); await settle() }
  component('PersonMultiSelect').props['onUpdate:modelValue'](['p1'])
  component('RecipientPresetSelect').props['onUpdate:modelValue']('preset')
  component('RecipientPresetSelect').props.onChange()
  await settle(); await advance(150)
  const complete = async (pending, overrides = {}) => {
    const body = pending.body
    const delta = body.operation === 'plus' ? body.points : -body.points
    const context = { person_name: '张三', person_open_id: 'ou_test_1', department: '研发', delta, total: body.overrides.p1 ?? 60 + delta, reason: body.reason, operator_name: '张三', month: '2026-11', time: '', operation: '加分' }
    pending.resolve(reply({ preview_token: `token-${body.reason}`, expires_at: new Date(Date.now() + 600000).toISOString(), month: '2026-11', delta, reason: body.reason, operator_name: '张三', recipients: people, message_count: 1, rows: [{ person: people[0], before_total: 60, final_total: context.total, override_total: body.overrides.p1 ?? null, balance_version: 0, context, card: { data: { template_id: 'test', template_version_name: '1', template_variable: { user_name: '张三', department: '研发', reason: body.reason, score: String(delta), total_score: String(context.total) } } } }], ...overrides }))
    await settle()
  }
  const mountDialog = (detail, props = {}) => {
    const root = new Element('dialog-root')
    const dialog = renderer.createApp(BatchResultDialog, { detail, busy: false, error: '', clock: Date.now(), confirmingRecall: false, ...props })
    dialog.mount(root); dialogs.push(dialog)
    return root
  }
  return { root, find, component, fieldset, reason, input, advance, previews, commits, complete, app, detailRequests, retryRequests, mountDialog,
    setUser: changes => { currentUser = { ...user, ...changes } }, get identityReads() { return identityReads } }
}

test('automatic preview keeps the form editable through loading and success', async t => {
  const h = await mount(t)
  h.reason().focus(); await h.input('提前完成项目')
  await h.advance(599); assert.equal(h.previews.length, 0)
  await h.advance(1); assert.equal(h.previews.length, 1)
  assert.equal(h.fieldset().props.disabled, false)
  assert.equal(document.activeElement, h.reason())
  assert.equal(h.find(node => node.props.class?.includes('form-submit')).props.disabled, true)
  const mobilePreview = h.find(node => node.props.class === 'mobile-actions').children.find(node => node.tag === 'button')
  assert.equal(mobilePreview.props.disabled, true)
  assert.equal(mobilePreview.props['aria-busy'], true)
  assert.equal(text(mobilePreview), '更新预览')
  assert.equal(text(h.find(node => node.props.class === 'preview-status')), '正在更新预览…')
  await h.complete(h.previews[0])
  assert.equal(h.fieldset().props.disabled, false)
  assert.equal(document.activeElement, h.reason())
  assert.equal(h.reason().value, '提前完成项目')
  assert.equal(h.component('CardPreview').props.context.reason, '提前完成项目')
})

test('preview controls and expanded recipients stay mounted throughout editing and refreshes', async t => {
  const h = await mount(t)
  const reason = h.reason()
  const card = h.component('CardPreview')
  const status = h.find(node => node.props.class?.includes('preview-status'))
  const details = h.find(node => node.props.class === 'preview-details')
  const recipients = nodes(details).find(node => node.tag === 'details')
  assert.ok(recipients)
  recipients.open = true
  const send = h.find(node => node.props.class?.includes('preview-send'))
  const mobile = h.find(node => node.props.class === 'mobile-actions').children.filter(node => node.tag === 'button')
  assert.equal(mobile.length, 2)
  const assertStable = () => {
    assert.equal(h.reason(), reason)
    assert.equal(h.component('CardPreview'), card)
    assert.equal(h.find(node => node.props.class?.includes('preview-status')), status)
    assert.equal(h.find(node => node.props.class === 'preview-details'), details)
    assert.equal(nodes(details).find(node => node.tag === 'details'), recipients)
    assert.equal(recipients.open, true)
    assert.equal(h.find(node => node.props.class?.includes('preview-send')), send)
    const currentMobile = h.find(node => node.props.class === 'mobile-actions').children.filter(node => node.tag === 'button')
    assert.equal(currentMobile.length, 2)
    assert.equal(currentMobile[0], mobile[0])
    assert.equal(currentMobile[1], mobile[1])
    assert.equal(h.fieldset().props.disabled, false)
    assert.equal(h.find(node => node.props.class?.includes('form-submit')).props.class.includes('busy'), false)
  }

  assert.equal(send.props.disabled, true)
  await h.input('第一次填写'); assertStable()
  await h.advance(600); assertStable()
  await h.complete(h.previews[0]); assertStable()
  assert.equal(send.props.disabled, false)

  await h.input('第一次填写后继续'); assertStable()
  assert.equal(send.props.disabled, true)
  await h.advance(600); const cancelled = h.previews[1]; assertStable()
  await h.input('最后一次填写'); assertStable()
  assert.equal(cancelled.signal.aborted, true)
  await h.advance(600); assertStable()
  await h.complete(cancelled); assertStable()
  assert.equal(send.props.disabled, true)
  h.previews[2].resolve(reply({ detail: '暂时生成失败' }, 503)); await settle(); assertStable()
  assert.equal(send.props.disabled, true)
  assert.equal(text(h.root).includes('暂时生成失败'), true)

  h.find(node => node.tag === 'form').props.onSubmit(new Event('submit', { cancelable: true }))
  await settle(); assertStable()
  await h.complete(h.previews[3]); assertStable()
  assert.equal(send.props.disabled, false)
  assert.equal(h.component('CardPreview').props.context.reason, '最后一次填写')
})

test('editing cancels an old request and ignores its late success and loading cleanup', async t => {
  const h = await mount(t)
  await h.input('旧原因'); await h.advance(600)
  const old = h.previews[0]
  await h.input('新原因'); assert.equal(old.signal.aborted, true)
  await h.advance(600); const current = h.previews[1]
  await h.complete(old)
  assert.equal(h.component('CardPreview').props.context.reason, '新原因')
  assert.equal(h.find(node => node.props.class?.includes('form-submit')).props.disabled, true)
  await h.complete(current)
  assert.equal(h.component('CardPreview').props.context.reason, '新原因')
  assert.equal(h.find(node => node.props.class?.includes('form-submit')).props.disabled, false)
})

test('late errors cannot replace the newest successful preview', async t => {
  const h = await mount(t)
  await h.input('旧原因'); await h.advance(600)
  await h.input('最终原因'); await h.advance(600)
  await h.complete(h.previews[1])
  h.previews[0].resolve(reply({ detail: '过时错误' }, 500)); await settle()
  assert.equal(h.component('CardPreview').props.context.reason, '最终原因')
  assert.equal(text(h.root).includes('过时错误'), false)
  assert.equal(h.fieldset().props.disabled, false)
})

test('preview failure stays local, preserves the draft and allows manual retry', async t => {
  const h = await mount(t)
  h.reason().focus(); await h.input('保留这段原因'); await h.advance(600)
  h.previews[0].resolve(reply({ detail: '服务暂时不可用' }, 503)); await settle()
  assert.equal(h.reason().value, '保留这段原因')
  assert.equal(h.fieldset().props.disabled, false)
  assert.equal(document.activeElement, h.reason())
  assert.equal(nodes(h.root).some(node => node.props.class === 'feedback error'), false)
  assert.equal(text(h.root).includes('服务暂时不可用'), true)
  h.find(node => node.tag === 'form').props.onSubmit(new Event('submit', { cancelable: true }))
  await settle(); assert.equal(h.previews.length, 2)
  await h.complete(h.previews[1])
  assert.equal(text(h.root).includes('服务暂时不可用'), false)
})

test('clearing a required field cancels the request without scheduling another', async t => {
  const h = await mount(t)
  await h.input('即将清空'); await h.advance(600)
  await h.input(''); assert.equal(h.previews[0].signal.aborted, true)
  await h.complete(h.previews[0]); await h.advance(2000)
  assert.equal(h.previews.length, 1)
  assert.equal(h.reason().value, '')
  assert.equal(h.find(node => node.props.class?.includes('preview-send')).props.disabled, true)
})

test('preview timeout is local, keeps the draft and does not retry automatically', async t => {
  const h = await mount(t)
  h.reason().focus(); await h.input('超时也保留这段原因'); await h.advance(600)
  h.previews[0].resolve(reply({ detail: '请求超时，操作结果待确认，请刷新查看。' }, 408)); await settle()
  const alert = h.find(node => node.props.role === 'alert' && text(node) === '预览生成超时，请重试。')
  assert.ok(nodes(h.find(node => node.props.class === 'panel preview-panel')).includes(alert))
  assert.equal(h.reason().value, '超时也保留这段原因')
  assert.equal(document.activeElement, h.reason())
  assert.equal(h.fieldset().props.disabled, false)
  assert.equal(nodes(h.root).some(node => node.props.class === 'feedback error'), false)
  await h.advance(30_000)
  assert.equal(h.previews.length, 1)
  assert.equal(h.find(node => node.props.class?.includes('form-submit')).props.disabled, false)
})

test('preview permission denial refreshes identity and prevents late results restoring access', async t => {
  const h = await mount(t)
  await h.input('旧请求'); await h.advance(600)
  const old = h.previews[0]
  await h.input('权限撤销时的请求'); await h.advance(600)
  h.setUser({ role: 'none', permissions: [], can_access_system: false })
  h.previews[1].resolve(reply({ detail: '无积分操作权限' }, 403)); await settle()
  assert.equal(h.identityReads, 2)
  assert.equal(old.signal.aborted, true)
  assert.equal(h.component('AccessDenied').props['data-component'], 'AccessDenied')
  await h.complete(old); await h.advance(2000)
  assert.equal(h.previews.length, 2)
  assert.equal(nodes(h.root).some(node => node.props['data-component'] === 'CardPreview'), false)
  assert.equal(nodes(h.root).some(node => node.props.class?.includes('preview-send')), false)
})

test('focusing the manual total pauses preview until blur', async t => {
  const h = await mount(t)
  await h.input('手动总分'); await h.advance(600)
  h.component('CardPreview').props.onEditingTotal(true); await settle()
  assert.equal(h.previews[0].signal.aborted, true)
  await h.complete(h.previews[0]); await h.advance(1000)
  assert.equal(h.previews.length, 1)
  h.component('CardPreview').props.onUpdateTotal('85'); await settle()
  h.component('CardPreview').props.onEditingTotal(false); await settle(); await h.advance(600)
  assert.equal(h.previews.length, 2)
  assert.equal(h.previews[1].body.overrides.p1, 85)
})

test('leaving cancels preview and returning schedules the preserved draft', async t => {
  const h = await mount(t)
  await h.input('切页保留'); await h.advance(600)
  h.find(node => node.tag === 'button' && text(node) === '操作手册').props.onClick(); await settle()
  assert.equal(h.previews[0].signal.aborted, true)
  await h.complete(h.previews[0]); await h.advance(2000)
  assert.equal(h.previews.length, 1)
  h.find(node => node.tag === 'button' && text(node) === '操作台').props.onClick(); await settle(); await h.advance(150); await h.advance(600)
  assert.equal(h.reason().value, '切页保留')
  assert.equal(h.previews.length, 2)
})

test('logging out cancels pending preview and prevents a late response restoring the editor', async t => {
  const h = await mount(t)
  await h.input('退出前的草稿'); await h.advance(600)
  h.find(node => node.props['aria-label'] === '退出登录').props.onClick(); await settle()
  assert.equal(h.previews[0].signal.aborted, true)
  await h.complete(h.previews[0]); await h.advance(2000)
  assert.equal(nodes(h.root).some(node => node.props['data-component'] === 'CardPreview'), false)
  assert.equal(text(h.root).includes('已退出登录'), true)
})

test('an expired preview cannot be confirmed for submission', async t => {
  const h = await mount(t)
  await h.input('已过期的预览'); await h.advance(600)
  await h.complete(h.previews[0], { expires_at: new Date(Date.now() - 60_000).toISOString() })
  assert.equal(h.find(node => node.props.class?.includes('preview-send')).props.disabled, true)
  assert.equal(text(h.root).includes('预览已过期'), true)
  assert.equal(h.commits.length, 0)
})

test('confirmed submission locks the form, deduplicates clicks and reuses its key on failure', async t => {
  const h = await mount(t)
  await h.input('确认同一笔'); await h.advance(600); await h.complete(h.previews[0])
  h.find(node => node.props.class?.includes('preview-send')).props.onClick(); await settle()
  const send = h.find(node => node.tag === 'button' && text(node) === '确认发送')
  send.props.onClick(); send.props.onClick(); await settle()
  assert.equal(h.commits.length, 1)
  assert.equal(h.fieldset().props.disabled, true)
  assert.equal(h.commits[0].body.preview_token, 'token-确认同一笔')
  const key = h.commits[0].body.idempotency_key
  assert.ok(key)
  h.commits[0].resolve(reply({ detail: '提交失败，请重试' }, 503)); await settle()
  assert.equal(h.fieldset().props.disabled, false)
  h.find(node => node.tag === 'button' && text(node) === '确认发送').props.onClick(); await settle()
  assert.equal(h.commits.length, 2)
  assert.equal(h.commits[1].body.idempotency_key, key)
  assert.equal(h.commits[1].body.preview_token, 'token-确认同一笔')
  h.commits[1].resolve(reply({ detail: '结束测试' }, 503)); await settle()
})

test('failed-result shortcut, pagination, refresh and retry preserve the server status filter', async t => {
  const h = await mount(t)
  await h.find(node => node.tag === 'button' && text(node) === '发送记录').props.onClick(); await settle()
  await h.component('SendingHistory').props.onFailed('batch-1'); await settle()
  assert.deepEqual(h.detailRequests.at(-1), { id: 'batch-1', filter: 'failed', page: 1 })
  assert.equal(h.component('BatchResultDialog').props.detail.delivery_status, 'failed')

  await h.component('BatchResultDialog').props.onChangePage(2); await settle()
  assert.deepEqual(h.detailRequests.at(-1), { id: 'batch-1', filter: 'failed', page: 2 })
  await h.component('BatchResultDialog').props.onRefresh(); await settle()
  assert.deepEqual(h.detailRequests.at(-1), { id: 'batch-1', filter: 'failed', page: 2 })
  await h.component('BatchResultDialog').props.onRetry('delivery-failed'); await settle()
  assert.deepEqual(h.retryRequests, ['/api/deliveries/delivery-failed/retry'])
  assert.deepEqual(h.detailRequests.at(-1), { id: 'batch-1', filter: 'failed', page: 2 })
  assert.equal(h.component('BatchResultDialog').props.detail.total, 0)
  assert.equal(h.component('BatchResultDialog').props.detail.delivery_status, 'failed')

  await h.component('BatchResultDialog').props.onChangeStatus('all'); await settle()
  assert.deepEqual(h.detailRequests.at(-1), { id: 'batch-1', filter: 'all', page: 1 })
  assert.equal(h.component('BatchResultDialog').props.detail.total, 519)
  h.component('BatchResultDialog').props.onClose(); await settle()
  await h.component('SendingHistory').props.onDetail('batch-2'); await settle()
  assert.deepEqual(h.detailRequests.at(-1), { id: 'batch-2', filter: 'all', page: 1 })
})

test('result dialog shows global status counts, filtered pagination and retry actions', async t => {
  const h = await mount(t)
  const detail = {
    id: 'batch-1', snapshot: { month: '2026-11', delta: 5, reason: '批量通知', operator_name: '张三', message_count: 519, recipients: people, rows: [{ person: people[0], final_total: 65, override_total: null }] },
    scores: [], created_at: new Date(Date.now()).toISOString(), statuses: { sent: 414, failed: 105 },
    delivery_status: 'failed', page: 2, total: 105, can_retry: true, can_recall: false, recall_available: 0, recall_statuses: {}, cancelled_scores: 0,
    deliveries: [{ id: 'delivery-failed', person_id: 'p1', recipient_name: '测试接收人', status: 'failed', attempts: 1, last_error: '发送失败原因', message_id: null, sent_at: null, recall_status: null, recall_error: null, recalled_at: null, recall_deadline: null, can_recall: false }],
  }
  const changed = [], retried = [], pages = []
  const root = h.mountDialog(detail, { onChangeStatus: value => changed.push(value), onRetry: value => retried.push(value), onChangePage: value => pages.push(value) })
  await settle()
  const filters = nodes(root).find(node => node.props['aria-label'] === '按发送状态筛选通知')
  const buttons = filters.children.filter(node => node.tag === 'button')
  assert.equal(buttons.length, 6)
  assert.equal(text(buttons[0]), '全部 519')
  assert.equal(text(buttons[1]), '发送失败 105')
  assert.equal(buttons[1].props['aria-pressed'], true)
  assert.ok(buttons.some(node => text(node) === '已发送 414'))
  buttons[0].props.onClick(); assert.deepEqual(changed, ['all'])
  assert.equal(text(root).includes('筛选结果 105 条'), true)
  assert.equal(text(root).includes('显示 101–105 / 105 条'), true)
  const retry = nodes(root).find(node => node.props['aria-label'] === '重试发送张三给测试接收人')
  assert.ok(retry)
  retry.props.onClick(); assert.deepEqual(retried, ['delivery-failed'])
  nodes(root).find(node => node.tag === 'button' && text(node) === '上一页').props.onClick()
  assert.deepEqual(pages, [1])

  const empty = h.mountDialog({ ...detail, page: 1, total: 0, deliveries: [], statuses: { sent: 519 } })
  await settle()
  assert.equal(text(empty).includes('暂无符合该状态的通知'), true)
  assert.equal(text(empty).includes('筛选结果 0 条'), true)
})
