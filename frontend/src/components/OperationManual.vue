<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

const chapters = [
  { id: 'manual-scoring', number: '01', name: '加减分' },
  { id: 'manual-lists', number: '02', name: '发送名单' },
  { id: 'manual-records', number: '03', name: '记录查询' },
  { id: 'manual-recall', number: '04', name: '撤回重试' },
  { id: 'manual-permissions', number: '05', name: '权限同步' },
]
const content = ref<HTMLElement | null>(null)
const activeChapter = ref(chapters[0]!.id)
let observer: ResizeObserver | undefined
let frame: number | undefined
let anchorPosition: { id: string; top: number } | undefined

function updateChapter() {
  frame = undefined
  const scroller = content.value
  if (!scroller) return
  if (anchorPosition && Math.abs(scroller.scrollTop - anchorPosition.top) < 2) {
    activeChapter.value = anchorPosition.id
    return
  }
  anchorPosition = undefined
  const readingTop = scroller.getBoundingClientRect().top + 24
  let current = chapters[0]!.id
  for (const chapter of chapters) {
    const section = scroller.querySelector<HTMLElement>(`#${chapter.id}`)
    if (section && section.getBoundingClientRect().top <= readingTop) current = chapter.id
  }
  if (scroller.scrollTop > 0 && scroller.clientHeight + scroller.scrollTop >= scroller.scrollHeight - 2) current = chapters[chapters.length - 1]!.id
  activeChapter.value = current
}
function scheduleChapter() {
  if (frame === undefined) frame = requestAnimationFrame(updateChapter)
}
function jumpTo(id: string) {
  const scroller = content.value
  const section = scroller?.querySelector<HTMLElement>(`#${id}`)
  if (!scroller || !section) return
  scroller.scrollTo({ top: section.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop - 16, behavior: 'instant' })
  anchorPosition = { id, top: scroller.scrollTop }
  activeChapter.value = id
}
onMounted(() => {
  observer = new ResizeObserver(scheduleChapter)
  if (content.value) observer.observe(content.value)
})
onUnmounted(() => {
  observer?.disconnect()
  if (frame !== undefined) cancelAnimationFrame(frame)
})
</script>

<template>
  <main class="manual" aria-labelledby="manual-title">
    <header class="manual-header">
      <h1 id="manual-title"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 5C9 3 6 3 3 4v15c3-1 6-1 9 1 3-2 6-2 9-1V4c-3-1-6-1-9 1Zm0 0v15M6 8h3M15 8h3" /></svg>操作手册</h1>
      <nav class="manual-index" aria-label="手册目录">
        <a v-for="chapter in chapters" :key="chapter.id" :href="`#${chapter.id}`" :aria-current="activeChapter === chapter.id ? 'location' : undefined" @click.prevent="jumpTo(chapter.id)"><span>{{ chapter.number }}</span>{{ chapter.name }}</a>
      </nav>
    </header>

    <div ref="content" class="manual-content" role="region" aria-label="手册正文" tabindex="0" @scroll.passive="scheduleChapter">
    <section id="manual-scoring" class="panel manual-section" aria-labelledby="manual-scoring-title">
      <div class="section-heading"><span class="section-number">01</span><h2 id="manual-scoring-title">加减分</h2></div>
      <ol class="quick-steps">
        <li><span class="step-number">1</span><h3>选员工</h3><p>搜索姓名，可选多人；每人总分独立计算。</p></li>
        <li><span class="step-number">2</span><h3>填分值和原因</h3><p>选加分或扣分，输入正整数，原因必填。多人共用分值和原因。</p></li>
        <li><span class="step-number">3</span><h3>选通知对象</h3><p>选已存名单或临时选人；需要通知本人时也要选入。</p></li>
        <li><span class="step-number">4</span><h3>预览并发送</h3><p>核对卡片、总分及接收人数，点击“核对并发送”确认。</p></li>
      </ol>
      <div class="score-guide">
        <div><h3>自动总分</h3><p>本月上一笔总分 + 本次加减分。按北京时间，每月从 <strong>60 分</strong>开始。</p><div class="score-example"><span>首次加 5 分</span><strong>60 + 5 = 65</strong></div></div>
        <div><h3>手动覆盖</h3><p>直接改卡片的“当前总分”，作为本次最终分数，<strong>不再额外加减</strong>，填 0 有效。“恢复自动”取消覆盖。</p><div class="score-example"><span>覆盖为 85 后，再加 3 分</span><strong>85 + 3 = 88</strong></div></div>
      </div>
      <div class="manual-notes"><p><b>卡片数量</b>记分人数 × 通知人数，例如 2 × 10 = 20 条。</p><p><b>预览更新</b>修改内容、预览过期或数据变化后，更新预览再发送。</p></div>
    </section>

    <section id="manual-lists" class="panel manual-section" aria-labelledby="manual-lists-title">
      <div class="section-heading"><span class="section-number">02</span><h2 id="manual-lists-title">发送名单</h2></div>
      <dl class="list-guide">
        <div><dt>组合人员</dt><dd>多个部门（含下级）＋指定人员，合并去重。</dd></div>
        <div><dt>预览保存</dt><dd>核对名单组成与人员，命名保存；发送时直接选用，也可临时调整。</dd></div>
        <div><dt>个人与公共</dt><dd>个人名单仅自己可见；公共名单大家可用，由管理员维护。</dd></div>
      </dl>
      <p class="section-note">名单按最新通讯录匹配人员；出现失效提示时，先检查名单。</p>
    </section>

    <section id="manual-records" class="panel manual-section" aria-labelledby="manual-records-title">
      <div class="section-heading"><span class="section-number">03</span><h2 id="manual-records-title">记录查询</h2></div>
      <div class="record-guide">
        <div class="record-card"><div class="record-heading"><h3>发送记录</h3><span>一次操作一行</span></div><p>查看整批记分和通知结果，处理撤回及失败重试。</p><div class="record-example">一次给 3 人记分<strong>1 行发送记录</strong></div></div>
        <div class="record-card"><div class="record-heading"><h3>积分明细</h3><span>一人一笔一行</span></div><p>按月份、姓名、历史部门、加扣分及有效状态筛选。</p><div class="record-example">一次给 3 人记分<strong>3 行积分明细</strong></div></div>
      </div>
      <div class="manual-notes"><p><b>统计与导出</b>覆盖全部筛选结果，合计不含作废记录；导出需对应权限。</p><p><b>前后总分</b>显示记账时的数值，人工改分标记“手动覆盖”。</p></div>
    </section>

    <section id="manual-recall" class="panel manual-section" aria-labelledby="manual-recall-title">
      <div class="section-heading"><span class="section-number">04</span><h2 id="manual-recall-title">撤回与重试</h2></div>
      <div class="action-guide">
        <div><h3>通知失败 → 重试通知</h3><p>在发送结果中重试失败通知。<strong>发送失败不影响积分，重试不重复记分。</strong></p></div>
        <div><h3>内容有误 → 整批撤回</h3><p>在发送记录申请撤回，处理 24 小时内可撤回的卡片。</p></div>
      </div>
      <p class="recall-rule"><strong>积分作废规则</strong>每位员工的全部通知撤回成功后，才作废该员工本笔记分并重算本月总分；部分撤回成功仍有效。</p>
    </section>

    <section id="manual-permissions" class="panel manual-section" aria-labelledby="manual-permissions-title">
      <div class="section-heading"><span class="section-number">05</span><h2 id="manual-permissions-title">权限与同步</h2></div>
      <div class="action-guide">
        <div><h3>权限管理</h3><p>员工授权设置角色和查看范围；角色配置查看功能权限；变更记录追溯授权调整。</p></div>
        <div><h3>通讯录同步</h3><p>管理员可手动同步，或设置同步时间与频率；页面显示下次同步时间。</p></div>
      </div>
      <p class="section-note">功能与可见数据以账号权限为准，需开通或调整请联系<strong>数据支持组</strong>。</p>
    </section>
    </div>
  </main>
</template>

<style scoped>
.manual{display:flex;flex-direction:column;min-height:0;overflow:hidden;border:1px solid var(--line);border-radius:var(--r-lg);background:var(--surface);font-size:var(--fs-md)}
.manual-content{display:flex;flex-direction:column;gap:16px;flex:1;min-height:0;overflow-y:auto;overscroll-behavior:contain;scrollbar-gutter:stable;padding:16px;background:var(--bg)}
.manual-content:focus-visible{outline:2px solid var(--accent);outline-offset:-3px}
.manual-content>.manual-section{flex:none}
.manual h1,.manual h2,.manual h3,.manual p{margin:0}
.manual h1{display:flex;align-items:center;gap:10px;flex:none;font-size:20px;line-height:1.5;white-space:nowrap}
.manual h1 svg{width:22px;height:22px;stroke:var(--accent-deep);stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
.manual h2{font-size:17px;line-height:1.5}
.manual h3{font-size:var(--fs-md);font-weight:700;line-height:1.65}
.manual p,.manual dd{line-height:1.85;color:var(--muted)}
.manual strong{color:var(--text);font-weight:600}
.manual-header{flex:none;display:flex;align-items:center;gap:28px;padding:14px 20px;border-bottom:1px solid var(--line);background:var(--surface)}
.manual-index{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:4px;flex:1;min-width:0;padding-left:20px;border-left:1px solid var(--line)}
.manual-index a{display:flex;align-items:center;justify-content:center;gap:6px;padding:9px 6px;border-radius:var(--r-md);font-weight:600;font-size:var(--fs-sm);white-space:nowrap;color:var(--muted);transition:color .12s,background-color .12s}
.manual-index a:hover{color:var(--accent-deep);background:var(--surface-2)}
.manual-index a[aria-current=location]{color:var(--accent-deep);background:var(--accent-soft);box-shadow:inset 0 -2px var(--accent)}
.manual-index a span{font-family:var(--mono);font-size:10px;opacity:.7}
.section-heading{display:flex;align-items:center;gap:10px;margin-bottom:18px}
.section-number{display:grid;place-items:center;width:28px;height:28px;flex:none;border-radius:var(--r-md);background:var(--accent-soft);color:var(--accent-deep);font-family:var(--mono);font-size:var(--fs-sm)}
.quick-steps{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;list-style:none;margin:0;padding:0}
.quick-steps li{min-width:0;position:relative;padding:16px;border:1px solid var(--line);border-radius:var(--r-md)}
.step-number{display:grid;place-items:center;width:24px;height:24px;margin-bottom:10px;border-radius:50%;background:var(--accent-soft);color:var(--accent-deep);font-family:var(--mono);font-size:11px}
.quick-steps p{margin-top:6px}
.score-guide{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px;margin-top:18px;padding:18px;border:1px solid var(--line);border-radius:var(--r-md);background:var(--bg)}
.score-guide>div+div{border-left:1px solid var(--line);padding-left:24px}
.score-guide p{margin-top:6px}
.score-example{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px 14px;margin-top:10px;color:var(--muted);font-size:var(--fs-sm)}
.score-example strong{font-family:var(--mono);color:var(--accent-deep);white-space:nowrap}
.manual-notes{display:grid;gap:7px;margin-top:18px;padding-top:14px;border-top:1px solid var(--line);font-size:var(--fs-sm)}
.manual-notes b{display:inline-block;margin-right:12px;color:var(--text);font-weight:600}
.manual .section-note{margin-top:16px;padding-top:13px;border-top:1px solid var(--line);font-size:var(--fs-sm)}
.section-note strong{margin:0 3px}
.list-guide{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:24px;margin:0}
.list-guide>div+div{border-left:1px solid var(--line);padding-left:24px}
.list-guide dt{font-weight:600;margin-bottom:6px}
.list-guide dd{margin:0}
.record-guide,.action-guide{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}
.record-card{padding:16px 18px;border:1px solid var(--line);border-radius:var(--r-md)}
.record-heading{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:8px}
.record-heading>span{background:var(--surface-2);padding:3px 8px;border-radius:var(--r-sm);font-size:var(--fs-xs);color:var(--muted)}
.record-example{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;padding-top:12px;margin-top:12px;border-top:1px dashed var(--line);font-size:var(--fs-sm);color:var(--muted)}
.record-example strong{color:var(--accent-deep)}
.action-guide>div{padding-left:14px;border-left:2px solid var(--line)}
.action-guide p{margin-top:6px}
.manual .recall-rule{display:grid;grid-template-columns:104px minmax(0,1fr);gap:12px;margin-top:18px;padding:14px 16px;border-radius:var(--r-md);background:var(--accent-soft);font-size:var(--fs-sm)}
.recall-rule strong{color:var(--accent-deep)}
@media(max-width:1200px){.manual-header{gap:18px}.manual-index{padding-left:14px}.manual-index a{gap:4px}}
@media(max-width:820px){.manual-header{flex-direction:column;align-items:stretch;gap:12px;padding:14px 16px}.manual-index{padding-left:0;border-left:0}.quick-steps{grid-template-columns:repeat(2,minmax(0,1fr))}.list-guide{gap:16px}.list-guide>div+div{padding-left:16px}}
@media(max-width:600px){.manual-content{gap:14px;padding:10px}.manual h1{font-size:18px;gap:8px}.manual h1 svg{width:20px;height:20px}.manual .panel{padding:16px}.manual-index{gap:3px}.manual-index a{padding:8px 2px;font-size:11px}.manual-index a span{display:none}.list-guide,.record-guide,.action-guide,.score-guide{grid-template-columns:minmax(0,1fr);gap:16px}.list-guide>div+div{border-left:0;border-top:1px solid var(--line);padding-left:0;padding-top:14px}.list-guide>div{display:grid;grid-template-columns:72px minmax(0,1fr);gap:10px}.list-guide dt{margin:0}.score-guide{padding:16px}.score-guide>div+div{border-left:0;border-top:1px solid var(--line);padding-left:0;padding-top:16px}.record-card{padding:14px}.section-heading{margin-bottom:16px}.manual .recall-rule{grid-template-columns:minmax(0,1fr);gap:5px}.quick-steps{gap:10px}.quick-steps li{padding:12px}.quick-steps h3{font-size:12px}.quick-steps p{font-size:var(--fs-sm)}.step-number{margin-bottom:7px}.manual-notes b{margin-right:8px}}
</style>
