# UI 美化实施计划(冷白基调 · 三批递进)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按已确认的设计规格把积分系统前端全面美化:冷白清爽基调、绿橙卡修正、动效质感、记分链路效率交互与移动端专项,分三批实施,每批独立验收。

**Architecture:** 纯前端改动(Vue 3 + Vite,630 行源码)。样式集中在 `frontend/src/style.css`(token / reset / 共享原语),组件私有样式移入各自 `<style scoped>`;交互逻辑改动集中在 `App.vue`、`PeoplePicker.vue`、`DirectorySync.vue`。不动后端、不加依赖、不改构建。

**Tech Stack:** Vue 3.5(script setup + TS)、Vite 7、原生 CSS 变量设计 token。

**规格文档:** [docs/superpowers/specs/2026-10-10-ui-beautify-design.md](../specs/2026-10-10-ui-beautify-design.md)

**验证方式说明:** 前端没有测试框架(无 vitest),本项目采用「构建 + 人工核对」验证:`npm run build` 包含 `vue-tsc` 类型检查,能抓住模板/类型错误;视觉与交互用本地演示模式逐屏核对。后端 40 个测试不受影响,无需运行。

```powershell
# 构建(每次代码改动后)
cd frontend; npm run build

# 本地演示模式(每批验收时,项目根目录)
py -3.13 scripts\start-local.py
# 浏览器打开 .env 中 PUBLIC_URL,登录后进入演示模式核对
```

**提交规范:** 每任务一次 `git add` + `git commit`,消息按任务给定;全部完成前不推送。

---

## 文件结构

| 文件 | 职责 | 变更 |
|------|------|------|
| `frontend/src/style.css` | 全局 token / reset / 共享原语 / 响应式 | 冷白 token、重写分区、死代码删除、后续追加动效与网格 |
| `frontend/src/components/CardPreview.vue` | 飞书卡片预览(绿橙实卡还原) | 绿橙修正版(scoped 样式重写) |
| `frontend/src/components/DirectorySync.vue` | 权限管理页同步设置 | `.sync-*` 样式归位 scoped |
| `frontend/src/components/PeoplePicker.vue` | 人员选择器(部门/搜索/勾选) | `.picker-*` 样式归位、折叠、autofocus |
| `frontend/src/App.vue` | 三页面 + 三弹窗 + 全部交互逻辑 | 第二批起逐任务修改 |
| `design.md` | 设计规格文档 | token 表更新为冷白 |

---

# 第一批:换肤纠偏

## Task 1:design.md token 表更新

**Files:**
- Modify: `design.md:19-53`(§2 颜色与字体表)、`design.md:114-118`(§6 克制原则)、`design.md:140-146`(§8 验收点)、`design.md:96-107`(§4.7 标题下加一行说明)

- [ ] **Step 1:替换 §2 颜色表与尺寸段**

将 `design.md` 中「### 颜色」表格(原 `#F4F1EA` 暖米体系)整体替换为:

```markdown
### 颜色

| Token | 值 | 用途 |
|-------|-----|------|
| `--bg` | `#F5F6F8` | 页面底色(冷白灰) |
| `--surface` | `#FFFFFF` | 卡片 / 输入面 |
| `--surface-2` | `#F0F1F4` | 次级面(浅灰块 / 卡片头) |
| `--text` | `#1F2329` | 主文字(深墨) |
| `--muted` | `#67707D` | 次要文字 |
| `--faint` | `#98A0AC` | 弱化文字 —— 仅用于 placeholder 与纯装饰 |
| `--line` | `#E3E6EB` | 边框 |
| `--accent` | `#D97757` | 主色(赤陶橙,保留) |
| `--accent-deep` | `#B5562F` | 主色深(激活态 / 按下态) |
| `--plus` | `#4A9D6A` | 加分语义色(边框/底色) |
| `--plus-ink` | `#3C8255` | 加分文字色 |
| `--minus` | `#C25B4E` | 扣分语义色 |
| `--minus-ink` | `#A94A3E` | 扣分文字色 |

新增语义 token:

| Token | 值 | 用途 |
|-------|-----|------|
| `--accent-soft` | `rgba(217,119,87,.07)` | 赤陶橙淡底(角色徽标 / 退出按钮 hover) |
| `--plus-soft` | `#EDF4EE` | 加分激活淡底 |
| `--minus-soft` | `#F4E7E4` | 扣分激活淡底 |
| `--overlay` | `rgba(20,24,32,.28)` | 弹窗背板 |
| `--shadow-soft` | `0 2px 6px rgba(31,35,41,.04)` | 唯一允许的极轻阴影 |
| `--card-plus` | `#22872d` | 实发卡片·加分绿(本地近似) |
| `--card-plus-dep` | `#35a454` | 实发卡片·加分部门块字色 |
| `--card-minus` | `#c65a00` | 实发卡片·扣分橙(原 `#ff9b20` 加深,修白字对比度) |
| `--card-minus-dep` | `#e77600` | 实发卡片·扣分部门块字色 |
```

- [ ] **Step 2:替换「### 尺寸」段**

```markdown
### 尺寸

- 圆角三档 `--r-sm/--r-md/--r-lg`:`4px / 6px / 8px`,8px 为上限
- 间距 4px 网格 `--sp-1/2/3/4/6`:`4 / 8 / 12 / 16 / 24px`
- 字号阶梯 `--fs-xs/sm/md/title/brand`:`11 / 12 / 13 / 18 / 21px`,全站最小 11px
- 数字一律 `font-variant-numeric: tabular-nums`
```

- [ ] **Step 3:§4.7 标题下加一行说明**

在 `### 4.7 飞书卡片 .fk-card` 标题正下方插入:

```markdown
> 已作废(2026-10-10):预览卡片改按绿橙实卡还原(修正版)实现,见 CardPreview.vue。本节的 .fk-card 样式已从 style.css 删除。
```

- [ ] **Step 4:§6 克制原则补一条**

在「✅」列表末尾追加:`✅ 全站最小字号 11px,弱化文字用 --muted(--faint 只用于 placeholder)`

- [ ] **Step 5:§8 验收点第一条改基调**

将 `- [ ] 页面底色为暖米 #F4F1EA,无渐变无光晕` 改为 `- [ ] 页面底色为冷白 #F5F6F8,无渐变无光晕`

- [ ] **Step 6:提交**

```bash
git add design.md
git commit -m "docs: 设计规格 token 更新为冷白基调并补充语义 token"
```

## Task 2:style.css :root 追加新 token(零视觉变化)

**Files:**
- Modify: `frontend/src/style.css:1`(:root 行)

- [ ] **Step 1:追加 token**

在 style.css 第 1 行,把结尾 `--mono:"Space Mono",ui-monospace,"SF Mono",Menlo,monospace;font-synthesis:none;color-scheme:light}` 替换为:

```css
--mono:"Space Mono",ui-monospace,"SF Mono",Menlo,monospace;--accent-soft:rgba(217,119,87,.07);--plus-soft:#EDF4EE;--minus-soft:#F4E7E4;--overlay:rgba(20,24,32,.28);--shadow-soft:0 2px 6px rgba(31,35,41,.04);--card-plus:#22872d;--card-plus-dep:#35a454;--card-minus:#c65a00;--card-minus-dep:#e77600;--r-sm:4px;--r-md:6px;--r-lg:8px;--sp-1:4px;--sp-2:8px;--sp-3:12px;--sp-4:16px;--sp-6:24px;--fs-xs:11px;--fs-sm:12px;--fs-md:13px;--fs-title:18px;--fs-brand:21px;font-synthesis:none;color-scheme:light}
```

- [ ] **Step 2:构建验证**

Run: `cd frontend; npm run build`
Expected: 构建通过,页面视觉零变化(新增 token 尚未被引用)

- [ ] **Step 3:提交**

```bash
git add frontend/src/style.css
git commit -m "style: :root 追加语义/尺寸 token(零视觉变化)"
```

## Task 3:CardPreview 绿橙修正版

**Files:**
- Modify: `frontend/src/components/CardPreview.vue:35-46`(`<style scoped>` 整块替换)

- [ ] **Step 1:替换 scoped 样式**

将 `<style scoped>...</style>` 整块(第 35-46 行)替换为:

```vue
<style scoped>
.card-preview-person{display:flex;align-items:center;gap:10px;margin-bottom:14px;font-size:var(--fs-md)}
.points-card{background:var(--card-plus);color:#fff;border-radius:var(--r-md);padding:16px 20px 26px;font-family:var(--sans);line-height:1.55;box-shadow:var(--shadow-soft);overflow-wrap:anywhere}
.points-card-minus{background:var(--card-minus)}
.points-card-top{display:grid;grid-template-columns:2fr 1fr;align-items:center;gap:8px;margin-bottom:14px;text-align:center;font-size:var(--fs-md)}
.points-card-top>strong{font-size:15px}.points-card-top>span{font-size:var(--fs-xs);font-weight:700;line-height:1.45}
.points-card-department{background:#fff;color:var(--card-plus-dep);padding:8px 12px;border-radius:var(--r-sm);font-size:16px;font-weight:700;text-align:center;white-space:pre-wrap}
.points-card-minus .points-card-department{color:var(--card-minus-dep)}
.points-card-person,.points-card-reason{color:#fff;font-size:14px;font-weight:700;text-align:center;margin:28px 8px 0;white-space:pre-wrap}
.points-card-scores{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:32px;text-align:center}
.points-card-scores span{display:block;font-size:var(--fs-xs);font-weight:700}
.points-card-scores strong{display:block;font-size:17px;margin-top:5px;font-family:var(--mono);font-weight:700;font-variant-numeric:tabular-nums}
.card-preview-meta{font-size:var(--fs-xs);color:var(--muted);margin:14px 0 0;line-height:1.8}
@media(max-width:420px){.points-card{padding:14px 14px 22px}.points-card-top>strong{font-size:14px}.points-card-department{font-size:14px}.points-card-person,.points-card-reason{font-size:var(--fs-md)}}
</style>
```

要点:扣分橙走 `--card-minus`(#c65a00,对比度达标);分数数字改等宽 + `tabular-nums`;字体栈统一 `var(--sans)`;元信息 10px → 11px、`--faint` → `--muted`。

- [ ] **Step 2:构建验证**

Run: `cd frontend; npm run build`
Expected: 通过

- [ ] **Step 3:演示模式核对**

Run: `py -3.13 scripts\start-local.py`(项目根目录),浏览器打开 PUBLIC_URL 进入演示模式:
- 加分预览卡片为绿色 #22872d,数字等宽;切到「扣分」后卡片为 #c65a00(不再是亮橙 #ff9b20)

- [ ] **Step 4:提交**

```bash
git add frontend/src/components/CardPreview.vue
git commit -m "style: 预览卡片绿橙修正版(对比度/等宽数字/字体栈)"
```

## Task 4:DirectorySync 样式归位 scoped

**Files:**
- Modify: `frontend/src/components/DirectorySync.vue`(末尾追加 `<style scoped>`)

- [ ] **Step 1:追加 scoped 样式**

在 `DirectorySync.vue` 文件末尾(`</template>` 之后)追加:

```vue
<style scoped>
.sync-heading{gap:12px;flex-wrap:wrap;margin-bottom:14px}
.sync-heading .panel-title{margin:0}
.sync-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.sync-actions button{white-space:nowrap;font-size:var(--fs-xs)}
.sync-status{display:flex;gap:5px 24px;flex-wrap:wrap;margin-bottom:16px;color:var(--muted);font-size:var(--fs-xs)}
.sync-state{color:var(--accent-deep)}
.sync-settings{border:1px solid var(--line);border-radius:var(--r-md);background:var(--surface-2);padding:14px 16px;margin-bottom:16px}
.sync-toggle{display:flex;align-items:center;gap:7px;font-size:var(--fs-sm);margin-bottom:12px}
.sync-fields{display:flex;align-items:flex-end;gap:12px 20px;flex-wrap:wrap}
.sync-fields>label{font-size:var(--fs-xs);color:var(--muted)}
.sync-fields input{margin-top:5px}
.sync-interval{display:flex;align-items:center;gap:8px;font-size:var(--fs-sm);height:41px;margin-top:5px}
.sync-interval input{width:75px;margin:0}
.sync-fields>label>input{display:block;width:150px}
.sync-fields .sync-actions{padding-bottom:3px}
.sync-save{color:var(--accent-deep);border-color:var(--accent)}
</style>
```

注意:`.sync-interval input{width:75px}` 去掉了原来的 `!important` —— scoped 选择器特异性更高,足以覆盖全局 `width:100%`;`.sync-status` 的 `--faint` 已改 `--muted`。

- [ ] **Step 2:构建验证**

Run: `cd frontend; npm run build`
Expected: 通过;此时全局 style.css 中仍有旧 `.sync-*` 规则,scoped 版特异性更高而生效,视觉不变(Task 6 会删除全局旧规则)

- [ ] **Step 3:提交**

```bash
git add frontend/src/components/DirectorySync.vue
git commit -m "style: DirectorySync 样式归位 scoped"
```

## Task 5:PeoplePicker 样式归位 scoped

**Files:**
- Modify: `frontend/src/components/PeoplePicker.vue`(末尾追加 `<style scoped>`)

- [ ] **Step 1:追加 scoped 样式**

在 `PeoplePicker.vue` 文件末尾追加:

```vue
<style scoped>
.department-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-bottom:10px}
.department-grid label{font-size:var(--fs-xs);color:var(--muted)}
.department-grid select{display:block;height:89px;padding:6px;font-size:var(--fs-xs);margin-top:4px}
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
</style>
```

注意:`.chips/.chip` **不移** —— App.vue 预览面板「通知名单」也在用;`summary{cursor:pointer}` 也留在全局(App.vue 的通知名单 details 在用)。原 10px 全部改为 `var(--fs-xs)`(11px),弱化色改 `--muted`。

- [ ] **Step 2:构建验证**

Run: `cd frontend; npm run build`
Expected: 通过,视觉不变

- [ ] **Step 3:提交**

```bash
git add frontend/src/components/PeoplePicker.vue
git commit -m "style: PeoplePicker 样式归位 scoped"
```

## Task 6:style.css 全量重写(冷白基调 · 清理 · 修正)

**Files:**
- Modify: `frontend/src/style.css`(整文件重写)

- [ ] **Step 1:用以下完整内容重写 style.css**

```css
/* ========== 设计 Token ========== */
:root{--bg:#F5F6F8;--surface:#FFFFFF;--surface-2:#F0F1F4;--text:#1F2329;--muted:#67707D;--faint:#98A0AC;--line:#E3E6EB;--accent:#D97757;--accent-deep:#B5562F;--plus:#4A9D6A;--plus-ink:#3C8255;--minus:#C25B4E;--minus-ink:#A94A3E;--accent-soft:rgba(217,119,87,.07);--plus-soft:#EDF4EE;--minus-soft:#F4E7E4;--overlay:rgba(20,24,32,.28);--shadow-soft:0 2px 6px rgba(31,35,41,.04);--card-plus:#22872d;--card-plus-dep:#35a454;--card-minus:#c65a00;--card-minus-dep:#e77600;--r-sm:4px;--r-md:6px;--r-lg:8px;--sp-1:4px;--sp-2:8px;--sp-3:12px;--sp-4:16px;--sp-6:24px;--fs-xs:11px;--fs-sm:12px;--fs-md:13px;--fs-title:18px;--fs-brand:21px;--serif:"Noto Serif SC",STSong,"Songti SC",serif;--sans:"Noto Sans SC",-apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif;--mono:"Space Mono",ui-monospace,"SF Mono",Menlo,monospace;font-synthesis:none;color-scheme:light}

/* ========== Reset 与基础 ========== */
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);line-height:1.65;-webkit-font-smoothing:antialiased}
button,input,select,textarea{font:inherit;color:inherit}
button,a,input,select,textarea{outline-offset:3px}
button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,summary:focus-visible{outline:2px solid var(--accent)}
button{border:1px solid var(--line);border-radius:var(--r-md);background:var(--surface);padding:7px 12px;font-family:var(--mono);font-size:var(--fs-sm);cursor:pointer}
button:hover:not(:disabled){border-color:var(--accent-deep)}
button:disabled{opacity:.45;cursor:not-allowed}
a{color:inherit;text-decoration:none}
input:not([type=checkbox],[type=radio]),textarea,select{width:100%;min-width:0;border:1px solid var(--line);background:var(--surface);border-radius:var(--r-md);padding:9px 11px;font-size:var(--fs-md)}
input[type=checkbox],input[type=radio]{accent-color:var(--accent);flex:none;width:15px;height:15px;margin:0}
textarea{resize:vertical;line-height:1.6}
select{cursor:pointer}
small{font-size:var(--fs-xs)}
h1,h2{font-family:var(--serif)}
p{margin:8px 0 12px}
fieldset{border:0;padding:0;margin:0;min-width:0}
fieldset:disabled{opacity:.7}

/* ========== 布局骨架 ========== */
.page{max-width:1140px;margin:auto;padding:0 24px 48px}
.topbar{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:23px 0;border-bottom:1px solid var(--line);margin-bottom:22px}
.brand{display:inline-flex;align-items:center;gap:12px;font-family:var(--serif);font-size:var(--fs-brand);font-weight:700;white-space:nowrap;min-width:0}
.brand-logo{display:block;flex:none;width:36px;height:36px}
.topbar-right{display:flex;align-items:center;gap:18px;flex-wrap:wrap;justify-content:flex-end;margin-left:auto;max-width:100%}
.navigation{display:flex;gap:6px;align-items:center;margin:0 0 24px}
.navigation button{border-color:transparent;background:transparent;padding:8px 15px;color:var(--muted)}
.navigation button.active{background:var(--surface-2);border-color:var(--line);color:var(--text)}
.navigation>span{margin-left:auto;color:var(--muted);font-size:var(--fs-xs)}
.layout{display:grid;grid-template-columns:1.1fr .9fr;gap:24px;align-items:start}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-lg);padding:24px;min-width:0}
.panel-head{margin-bottom:22px}
.panel-title{font-size:var(--fs-title);margin:0 0 4px;font-weight:700}
.panel-sub{font-size:var(--fs-sm);color:var(--muted);margin:0}
.flex-head{display:flex;align-items:center;justify-content:space-between;gap:12px}
.flex-head>button{white-space:nowrap}
.empty-preview-logo{opacity:.65}

/* ========== 操作台 ========== */
.op-form{display:flex;flex-direction:column;gap:20px}
.field-label{display:block;font-family:var(--mono);font-size:var(--fs-xs);color:var(--muted);margin-bottom:9px;letter-spacing:.02em}
.field-label .prompt{margin-right:5px}
.field-label small{margin-left:5px}
.count{float:right;font-family:var(--sans);letter-spacing:0}
.prompt{color:var(--accent)}
.f-seg{display:flex;gap:8px}
.opt{flex:1;padding:11px;font-size:var(--fs-md);font-weight:700;color:var(--muted)}
.opt.plus.active{background:var(--plus-soft);border-color:var(--plus);color:var(--plus-ink)}
.opt.minus.active{background:var(--minus-soft);border-color:var(--minus);color:var(--minus-ink)}
.plus-text{color:var(--plus-ink)}
.minus-text{color:var(--minus-ink)}
.f-points{display:flex;align-items:center;gap:8px;font-family:var(--mono);font-size:32px}
.f-points input{border:0;background:transparent;padding:0;font-size:36px;width:135px;font-family:var(--mono);font-weight:700}
.f-points input::-webkit-inner-spin-button{appearance:none}
.unit{font-size:var(--fs-md);color:var(--muted)}
.stepper{display:flex;gap:8px;margin-left:auto}
.stepper button{height:36px;width:36px;padding:0;font-size:16px}
.balance-row{display:flex;align-items:center;gap:10px;border-bottom:1px solid var(--line);padding:9px 0;font-size:var(--fs-sm);flex-wrap:wrap}
.balance-row>div{flex:1;min-width:120px}
.balance-line{margin-left:12px;color:var(--muted);font-family:var(--mono);font-size:var(--fs-sm)}
.manual-toggle{display:flex;align-items:center;gap:5px;font-size:var(--fs-xs);color:var(--muted)}
input.override-input{width:90px;font-family:var(--mono);padding:5px}
.hint{font-size:var(--fs-xs);color:var(--muted);line-height:1.7}
.section-divider{height:1px;background:var(--line);margin:2px 0}
.preset-actions{display:flex;gap:6px;margin-top:8px}
.preset-actions input{flex:1}
.preset-actions button{white-space:nowrap;padding:5px 8px}
.send-summary{font-size:var(--fs-sm);color:var(--muted);border-top:1px solid var(--line);padding-top:14px}
.send-summary b{font-family:var(--mono);font-weight:700;color:var(--text)}
.primary-button{display:block;text-align:center;border:0;border-radius:var(--r-md);background:var(--accent);color:white;padding:13px 16px;font-family:var(--mono);font-size:var(--fs-md);font-weight:700;width:100%;cursor:pointer}
.primary-button:hover:not(:disabled){background:var(--accent-deep)}
.preview-panel{position:sticky;top:22px}
.preview-panel>select{margin-bottom:16px}
.empty-preview{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:250px;border:1px dashed var(--line);border-radius:var(--r-md);color:var(--muted);font-size:var(--fs-sm);text-align:center}
.preview-details{margin:20px 0;font-size:var(--fs-sm);color:var(--muted)}
.preview-details details{margin:10px 0}
.preview-details details p{font-size:var(--fs-xs);overflow-wrap:anywhere}

/* ========== 发送记录 ========== */
.empty-state{padding:55px 0;text-align:center;color:var(--muted);font-size:var(--fs-md)}
.history-entry{display:flex;align-items:center;gap:24px;border-top:1px solid var(--line)}
.history-entry .history-item{flex:1;min-width:0;border-top:0}
.history-actions{display:flex;align-items:center;gap:8px;flex:none}
.history-actions button{white-space:nowrap;font-size:var(--fs-xs)}
.history-item{display:block;width:100%;text-align:left;border:0;border-top:1px solid var(--line);border-radius:0;background:transparent;padding:17px 0;font-family:var(--sans);font-size:var(--fs-sm)}
.history-item>div{display:flex;justify-content:space-between;gap:10px}
.history-item p{color:var(--muted);overflow-wrap:anywhere}
.signed-number{font-family:var(--mono);white-space:nowrap}
.recall-button{color:var(--accent-deep);border-color:var(--accent)}
.recall-toolbar{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin:12px 0}
.recall-toolbar p{margin:0}
.cancelled-text{color:var(--minus-ink)}

/* ========== 权限管理 ========== */
.admin-table{margin-top:18px}
.admin-row{display:flex;align-items:center;gap:18px;border-bottom:1px solid var(--line);padding:12px 0;font-size:var(--fs-sm)}
.admin-row>div{flex:1;min-width:0}
.admin-row small{display:block;font-size:var(--fs-xs);overflow-wrap:anywhere;color:var(--muted)}
.admin-row>span{font-size:var(--fs-xs);white-space:nowrap;color:var(--muted)}
.admin-row select{width:110px;font-size:var(--fs-xs)}

/* ========== 弹窗 ========== */
.modal-backdrop{position:fixed;inset:0;z-index:10;background:var(--overlay);display:flex;align-items:center;justify-content:center;padding:20px}
.modal{width:480px;max-width:100%;max-height:88vh;overflow:auto;font-size:var(--fs-md)}
.wide-modal{width:780px}
.modal-actions{display:flex;gap:10px;margin-top:20px}
.modal-actions>button{flex:1}
.confirm-total{display:flex;align-items:center;gap:10px;border-bottom:1px solid var(--line);padding:8px 0;font-size:var(--fs-sm)}
.confirm-total b{margin-left:auto;font-family:var(--mono)}
.delivery-row{display:flex;align-items:center;gap:12px;border-top:1px solid var(--line);padding:10px 0;font-size:var(--fs-xs)}
.delivery-row>div{flex:1;min-width:0}
.delivery-row small{display:block;font-family:var(--mono);font-size:var(--fs-xs);overflow-wrap:anywhere}
.delivery-row>span{white-space:nowrap;color:var(--muted)}
.delivery-row>button{white-space:nowrap}
.delivery-row .error-text{margin:5px 0 0}
.recall-confirmation{z-index:20}
.score-results{display:grid;gap:10px;margin:20px 0}
.score-result{padding:14px 16px;border:1px solid var(--line);border-radius:var(--r-lg);background:var(--surface-2)}
.score-person{display:flex;align-items:center;gap:8px;min-width:0;font-size:var(--fs-sm)}
.score-person>b{overflow-wrap:anywhere}
.score-state{margin-left:auto;flex:none;padding:2px 7px;border-radius:var(--r-sm);background:var(--plus-soft);color:var(--plus-ink);font-size:var(--fs-xs)}
.score-state.cancelled{background:var(--minus-soft);color:var(--minus-ink)}
.score-values{display:flex;gap:8px 20px;flex-wrap:wrap;margin-top:10px;color:var(--muted);font-size:var(--fs-xs)}
.score-values b{color:var(--text);font-family:var(--mono);font-size:14px}
.score-result>small{display:block;margin-top:6px}

/* ========== 顶栏账号 ========== */
.account-panel{display:flex;align-items:center;max-width:100%;padding:8px 8px 8px 10px;border:1px solid var(--line);border-radius:var(--r-lg);background:var(--surface);box-shadow:var(--shadow-soft)}
.account-identity{display:flex;align-items:center;gap:10px;min-width:0;padding-right:16px}
.account-details{display:flex;flex-direction:column;align-items:flex-start;gap:4px;min-width:0}
.account-name{max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:var(--fs-md);line-height:1.25;font-weight:600}
.account-role{padding:1px 6px;border-radius:var(--r-sm);background:var(--accent-soft);color:var(--accent-deep);font-size:var(--fs-xs);line-height:1.5;white-space:nowrap}
.account-actions{flex:none;border-left:1px solid var(--line);padding-left:8px}
.logout-button{display:flex;align-items:center;justify-content:center;gap:5px;border:0;background:transparent;padding:8px 9px;border-radius:var(--r-md);color:var(--muted);font-family:var(--sans);font-size:var(--fs-xs);transition:background .15s,color .15s}
.logout-button:hover:not(:disabled){background:var(--accent-soft);color:var(--accent-deep)}
.logout-button svg{flex:none}

/* ========== 提示反馈 ========== */
.feedback{padding:11px 15px;border:1px solid var(--line);background:var(--surface-2);border-radius:var(--r-md);font-size:var(--fs-sm);margin-bottom:16px;display:flex;align-items:center;justify-content:space-between}
.feedback.error{border-color:var(--minus);color:var(--minus-ink)}
.feedback button{border:0;background:transparent;padding:0}
.error-text{color:var(--minus-ink);font-size:var(--fs-xs);overflow-wrap:anywhere}
.demo-banner{font-size:var(--fs-xs);color:var(--muted);padding-bottom:15px}
.login-panel{max-width:560px;margin:70px auto;padding:40px}
.login-panel h1{font-size:27px;line-height:1.5;margin:16px 0}
.login-panel p{color:var(--muted);font-size:var(--fs-md);margin:15px 0 26px}
.login-panel>button{width:100%;margin-top:12px}
.eyebrow{font-size:var(--fs-xs);font-family:var(--mono);color:var(--accent-deep);letter-spacing:.15em}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0 5px}
.chip{display:flex;align-items:center;gap:6px;background:var(--surface-2);border:1px solid var(--line);padding:2px 8px;border-radius:var(--r-md);font-size:var(--fs-xs)}
.chip button{border:0;padding:0;background:transparent;font-size:13px}
.pagination{display:flex;align-items:center;justify-content:flex-end;gap:8px;margin-top:14px;flex-wrap:wrap}
.pagination button{padding:4px 7px;font-size:var(--fs-xs)}
b,button,input{font-variant-numeric:tabular-nums}

/* ========== 响应式 ========== */
@media(max-width:820px){
  .layout{grid-template-columns:1fr}
  .preview-panel{position:static}
  .page{padding:0 16px 30px}
  .topbar{flex-wrap:wrap}
  .brand{font-size:18px;gap:10px}
  .brand-logo{width:32px;height:32px}
  .topbar-right{gap:8px}
  .panel{padding:20px}
  .login-panel{margin:35px auto;padding:28px}
  .modal-backdrop{padding:12px}
  .modal{max-height:92vh}
}
@media(max-width:640px){
  .history-entry{flex-wrap:wrap;gap:0}
  .history-entry .history-item{flex-basis:100%;padding-bottom:10px}
  .history-actions{width:100%;justify-content:flex-end;margin:0 0 16px}
  .delivery-row{flex-wrap:wrap;gap:8px}
  .delivery-row>div{flex-basis:100%}
  .delivery-row>span{margin-right:auto}
  .delivery-row>small{max-width:none}
  .recall-toolbar{align-items:flex-start;flex-direction:column}
  .topbar{row-gap:16px}
  .topbar-right{max-width:100%}
  .account-panel{padding:7px 7px 7px 9px}
  .account-identity{padding-right:12px}
  .account-name{max-width:180px;font-size:var(--fs-sm)}
  .logout-button{padding:8px}
}
@media(max-width:420px){
  .navigation{gap:0;flex-wrap:wrap}
  .navigation>span{width:100%;margin:9px 0 0}
  .admin-row{gap:8px}
  .admin-row select{width:92px}
  .modal-actions{flex-direction:column}
  .f-points input{width:105px}
  .preset-actions{flex-wrap:wrap}
  .preset-actions input{flex-basis:100%}
  .brand{font-size:16px;gap:9px}
  .brand-logo{width:30px;height:30px}
}
```

已删除(全站零引用):`.fk-card/.fk-head/.fk-body/.fk-amount/.fk-reason/.fk-divider/.fk-row/.fk-meta/.fk-title/.bot-tag/.total-number/.foot/.dot/.big`;已移除已归位组件的样式(`.sync-*`、`.department-grid`、`.picker-tools`、`.inline-options`、`.people-list`、`.person-option`、`.person-text`、`.extra-picker`、`.text-button`)及其媒体覆盖。`!important` 全部清零(靠源顺序与 `input.override-input` 更高特异性)。全部 9-10px 上调 11px;文本弱化色 `--faint` → `--muted`;圆角 10px → 8px、头像 8px 覆盖删除;品牌字重 900 → 700(只打包了 700)。

- [ ] **Step 2:构建验证**

Run: `cd frontend; npm run build`
Expected: 通过

- [ ] **Step 3:第一批验收 · 演示模式逐屏核对**

Run: `py -3.13 scripts\start-local.py`,浏览器打开 PUBLIC_URL,核对:

| 屏幕 | 检查点 |
|------|--------|
| 全局 | 底色为冷白 #F5F6F8,无暖米残留;卡片白底;无渐变无辉光 |
| 操作台 | 加分/扣分激活态淡绿/淡红;分值大数字等宽;翻页/状态字不小于 11px |
| 发送记录 | 状态小字 11px;撤回按钮橙色描边 |
| 权限管理 | 同步设置展开样式完整(scoped 生效);搜索与表格正常 |
| 三弹窗 | 背板冷灰半透明;面板 8px 圆角 |
| 窄屏(开发者工具 420/640/820px) | 单列堆叠正常,无横向滚动 |

- [ ] **Step 4:提交**

```bash
git add frontend/src/style.css
git commit -m "style: 冷白基调重写 style.css(清理死代码/!important 清零/字号对比度圆角修正)"
```

---

# 第二批:动效与质感

## Task 7:动效基线(过渡 + 按下态 + 行悬停)

**Files:**
- Modify: `frontend/src/style.css`(Reset 区之后追加;.history-item 微调)

- [ ] **Step 1:追加过渡与按下态规则**

在 `fieldset:disabled{opacity:.7}` 行之后追加:

```css
button,.person-option,.chip,.opt,.navigation button{transition:background-color .12s,border-color .12s,color .12s}
button:active:not(:disabled){transform:translateY(1px)}
.primary-button:active:not(:disabled){background:var(--accent-deep)}
.opt,.f-points input,.balance-line b,.signed-number{transition:color .15s}
```

- [ ] **Step 2:history-item 行悬停**

把 `.history-item{display:block;width:100%;text-align:left;border:0;border-top:1px solid var(--line);border-radius:0;background:transparent;padding:17px 0;font-family:var(--sans);font-size:var(--fs-sm)}` 改为:

```css
.history-item{display:block;width:100%;text-align:left;border:0;border-top:1px solid var(--line);border-radius:0;background:transparent;padding:17px 10px;margin:0 -10px;font-family:var(--sans);font-size:var(--fs-sm)}
.history-item:hover:not(:disabled){background:var(--surface-2)}
```

- [ ] **Step 3:构建验证**

Run: `cd frontend; npm run build`
Expected: 通过

- [ ] **Step 4:提交**

```bash
git add frontend/src/style.css
git commit -m "style: 全站 0.12s 过渡基线、按下态与记录行悬停反馈"
```

## Task 8:进行中状态反馈(spinner + 呼吸)

**Files:**
- Modify: `frontend/src/style.css`(追加)
- Modify: `frontend/src/App.vue:237,268,298`(三处 busy 按钮加 :class)
- Modify: `frontend/src/components/DirectorySync.vue:98`(sync-state 加 pulse)

- [ ] **Step 1:style.css 追加动画**

在「提示反馈」分区末尾追加:

```css
@keyframes spin{to{transform:rotate(360deg)}}
.primary-button.busy::before{content:'';display:inline-block;width:12px;height:12px;border:2px solid rgba(255,255,255,.45);border-top-color:#fff;border-radius:50%;margin-right:8px;animation:spin .7s linear infinite;vertical-align:-2px}
@keyframes breathe{50%{opacity:.55}}
.pulse{animation:breathe 1.6s ease-in-out infinite}
```

- [ ] **Step 2:App.vue 三处 busy 按钮加绑定**

三处分别把 `class="primary-button"` 改为 `class="primary-button" :class="{ busy }"`:

1. 操作台更新预览按钮(第 237 行)
2. 确认发送弹窗「确认发送」按钮(第 268 行)
3. 确认撤回弹窗「确认撤回」按钮(第 298 行)

- [ ] **Step 3:DirectorySync 同步状态加呼吸**

把 `<span v-if="running || queued || recovering" class="sync-state">` 改为 `<span v-if="running || queued || recovering" class="sync-state pulse">`

- [ ] **Step 4:构建验证**

Run: `cd frontend; npm run build`
Expected: 通过

- [ ] **Step 5:提交**

```bash
git add frontend/src/style.css frontend/src/App.vue frontend/src/components/DirectorySync.vue
git commit -m "feat: 提交按钮细线 spinner 与轮询态呼吸动画"
```

## Task 9:弹窗过渡

**Files:**
- Modify: `frontend/src/App.vue`(三个弹窗包 Transition)
- Modify: `frontend/src/style.css`(追加过渡类)

- [ ] **Step 1:确认发送弹窗包 Transition**

把 `<div v-if="confirmation && preview" class="modal-backdrop" @click.self="!busy && (confirmation = false)">` 改为:

```html
<Transition name="modal">
  <div v-if="confirmation && preview" class="modal-backdrop" @click.self="!busy && (confirmation = false)">
```

其对应闭合标签由 `</section></div>`(第 268 行行尾)改为 `</section></div></Transition>`

- [ ] **Step 2:发送结果弹窗包 Transition**

把 `<div v-if="detail" class="modal-backdrop" @click.self="!busy && closeDetail()">` 改为:

```html
<Transition name="modal">
  <div v-if="detail" class="modal-backdrop" @click.self="!busy && closeDetail()">
```

其对应闭合标签在第 289-290 行(该弹窗以含「刷新」按钮的 `.pagination` 结尾,上方即为发送结果弹窗):把

```html
    </section>
  </div>
```

改为:

```html
    </section>
  </div>
</Transition>
```

- [ ] **Step 3:确认撤回弹窗包 Transition**

把 `<div v-if="recallConfirmation" class="modal-backdrop recall-confirmation" @click.self="!busy && (recallConfirmation = null)">` 改为:

```html
<Transition name="modal">
  <div v-if="recallConfirmation" class="modal-backdrop recall-confirmation" @click.self="!busy && (recallConfirmation = null)">
```

其对应闭合标签在第 299-300 行(前一行是 `.modal-actions` 的闭合,上方即为确认撤回弹窗):把

```html
    </section>
  </div>
```

改为:

```html
    </section>
  </div>
</Transition>
```

- [ ] **Step 4:style.css 追加过渡类**

在「弹窗」分区追加:

```css
.modal-enter-active,.modal-leave-active{transition:opacity .15s}
.modal-enter-active .modal,.modal-leave-active .modal{transition:opacity .15s,transform .15s}
.modal-enter-from,.modal-leave-to{opacity:0}
.modal-enter-from .modal,.modal-leave-to .modal{opacity:0;transform:translateY(8px)}
```

- [ ] **Step 5:构建验证**

Run: `cd frontend; npm run build`
Expected: 通过(vue-tsc 校验 Transition 包裹合法)

- [ ] **Step 6:提交**

```bash
git add frontend/src/App.vue frontend/src/style.css
git commit -m "feat: 三个弹窗 0.15s 淡入上移过渡"
```

## Task 10:等宽全局 · 间距网格 · 信息分区

**Files:**
- Modify: `frontend/src/style.css`(tabular 提升、网格归位、分区新类)
- Modify: `frontend/src/App.vue`(历史状态行合并、权限表头、原因框、宽模态分区)

- [ ] **Step 1:等宽数字提升到 body 级**

把 `b,button,input{font-variant-numeric:tabular-nums}` 整行删除,并在 `body{...}` 规则末尾(`-webkit-font-smoothing:antialiased` 后)追加 `;font-variant-numeric:tabular-nums`

- [ ] **Step 2:时间戳/页次走等宽字体**

在「发送记录」分区追加:

```css
.history-item small,.delivery-row small,.pagination small{font-family:var(--mono)}
```

- [ ] **Step 3:间距归入 4px 网格**

逐行修改(旧 → 新):

| 旧 | 新 |
|----|-----|
| `button{border:1px solid var(--line);...padding:7px 12px;...}` | padding 改 `8px 12px` |
| `input:not([type=checkbox],[type=radio]),textarea,select{...padding:9px 11px;...}` | padding 改 `8px 12px` |
| `.topbar{...padding:23px 0;...margin-bottom:22px}` | `padding:24px 0`、`margin-bottom:24px` |
| `.history-item{...padding:17px 10px;...}` | `padding:16px 10px` |
| `.op-form{display:flex;flex-direction:column;gap:20px}` | `gap:16px` |
| `.field-label{...margin-bottom:9px;...}` | `margin-bottom:8px` |
| `.score-state{...padding:2px 7px;...}` | `padding:2px 8px` |
| `.score-result{padding:14px 16px;...}` | `padding:16px` |
| `.balance-row{...padding:9px 0;...}` | `padding:8px 0` |

- [ ] **Step 4:App.vue 历史状态行合并**

脚本区 `resultSummary` 函数之后追加:

```ts
const historyStatusParts = (item: HistoryItem) => {
  const parts: { text: string; error: boolean }[] = []
  const add = (text: string, error = false) => parts.push({ text, error })
  if (item.statuses.failed) add(`发送失败 ${item.statuses.failed}`, true)
  if (item.statuses.review) add(`待核实 ${item.statuses.review}`, true)
  if (item.recall_statuses?.recalled) add(`已撤回 ${item.recall_statuses.recalled}`)
  if (item.cancelled_scores) add(`已作废 ${item.cancelled_scores} 笔记分`, true)
  if (item.recall_statuses?.pending || item.recall_statuses?.recalling) add(`撤回处理中 ${(item.recall_statuses.pending ?? 0) + (item.recall_statuses.recalling ?? 0)}`)
  if (item.recall_statuses?.failed) add(`撤回失败 ${item.recall_statuses.failed}`, true)
  if (item.recall_statuses?.review) add(`撤回待核实 ${item.recall_statuses.review}`, true)
  return parts
}
```

模板中历史条目里的 8 个 `<small>` 状态行(第 252-259 行:`<small>{{ timeLabel(...) }}...已发送</small>` 及后面 7 个 v-if small)替换为:

```html
<small>{{ timeLabel(item.created_at) }} · {{ item.operator_name }} · {{ item.statuses.sent ?? 0 }} / {{ item.message_count }} 已发送</small>
<p v-if="historyStatusParts(item).length" class="status-line"><template v-for="(part, index) in historyStatusParts(item)" :key="index"><span v-if="index"> · </span><span :class="{ 'error-text': part.error }">{{ part.text }}</span></template></p>
```

style.css「发送记录」分区追加:

```css
.status-line{display:block;margin:4px 0 0;font-size:var(--fs-xs);color:var(--muted)}
```

- [ ] **Step 5:权限表列头**

App.vue 权限管理区,`<input v-model="adminQuery" ...>` 之后、`.admin-table` 之前插入:

```html
<div class="admin-head"><span>姓名</span><span>状态</span><span>权限</span></div>
```

style.css「权限管理」分区修改两处:

把 `.admin-row>span{font-size:var(--fs-xs);white-space:nowrap;color:var(--muted)}` 改为:

```css
.admin-row>span{width:64px;text-align:center;font-size:var(--fs-xs);white-space:nowrap;color:var(--muted)}
```

追加:

```css
.admin-head{display:flex;gap:18px;margin:14px 0 6px;padding-left:46px;font-family:var(--mono);font-size:var(--fs-xs);color:var(--muted)}
.admin-head>span:first-child{flex:1;min-width:0}
.admin-head>span:nth-child(2){width:64px;text-align:center}
.admin-head>span:last-child{width:110px}
```

- [ ] **Step 6:确认弹窗原因框**

App.vue 确认发送弹窗中 `<p>{{ preview.reason }}</p>`(第 268 行内,`<p>{{ preview.rows.length }} 人...` 之后的那行)改为:

```html
<p class="reason-box">{{ preview.reason }}</p>
```

style.css「弹窗」分区追加:

```css
.reason-box{padding:10px 12px;border:1px solid var(--line);border-radius:var(--r-md);background:var(--surface-2);max-height:160px;overflow:auto;font-size:var(--fs-md)}
```

- [ ] **Step 7:宽模态分区标题 + message_id 全宽折行**

App.vue 发送结果弹窗中,`.score-results` 之前插入 `<div class="modal-section-title">逐人积分状态</div>`,`.deliveries` 之前插入 `<div class="modal-section-title">通知明细</div>`。

style.css「弹窗」分区追加:

```css
.modal-section-title{font-family:var(--mono);font-size:var(--fs-xs);color:var(--muted);margin:18px 0 8px}
```

删除 640px 媒体查询中的 `.delivery-row>small{max-width:none}` 行——在桌面端也允许全宽折行(直接把该规则移出媒体查询:在「弹窗」分区追加 `.delivery-row>small{max-width:none;text-align:left}`,并从 640px 块中删除旧行)。

- [ ] **Step 8:构建验证**

Run: `cd frontend; npm run build`
Expected: 通过

- [ ] **Step 9:演示模式核对**

Run: `py -3.13 scripts\start-local.py`;检查:发送记录状态合并为一行、权限页有列头且对齐、确认弹窗原因在浅灰框中、发送结果弹窗有分区标题。

- [ ] **Step 10:提交**

```bash
git add frontend/src/App.vue frontend/src/style.css
git commit -m "style: 等宽数字全局化、4px 间距网格与信息分区"
```

---

# 第三批:效率交互 + 移动端

## Task 11:防抖自动预览 + 一键发送(保留兜底)

**Files:**
- Modify: `frontend/src/App.vue`(watch 改写、makePreview 守卫、onUnmounted 清理)

- [ ] **Step 1:改写作废 watch 为防抖自动预览**

把:

```ts
watch([targets, recipients, operation, points, reason, manual, overrides], () => { preview.value = null; confirmation.value = false; idempotency.value = '' }, { deep: true })
```

替换为:

```ts
let previewTimer: ReturnType<typeof setTimeout> | undefined
const previewReady = computed(() => !busy.value && selectedPeople.value.length > 0 && reason.value.trim().length > 0 && resolvedRecipients.value.length > 0 && !recipientWarnings.value.length)
watch([targets, recipients, operation, points, reason, manual, overrides, resolvedRecipients, recipientWarnings], () => {
  clearTimeout(previewTimer)
  if (!previewReady.value) { preview.value = null; confirmation.value = false; idempotency.value = ''; return }
  previewTimer = setTimeout(() => { void makePreview() }, 600)
}, { deep: true })
```

- [ ] **Step 2:makePreview 加守卫**

把 `async function makePreview() {` 开头改为:

```ts
async function makePreview() {
  if (busy.value) return
  if (!selectedPeople.value.length || !reason.value.trim() || !resolvedRecipients.value.length || recipientWarnings.value.length) return
```

(函数体其余不变;`action` 内部已有 busy 防重入,自动路径不会与手动路径打架)

- [ ] **Step 3:onUnmounted 清理定时器**

把 `onUnmounted(() => { clearInterval(timer); clearTimeout(resolveTimer) })` 改为:

```ts
onUnmounted(() => { clearInterval(timer); clearTimeout(resolveTimer); clearTimeout(previewTimer) })
```

- [ ] **Step 4:构建验证**

Run: `cd frontend; npm run build`
Expected: 通过

- [ ] **Step 5:演示模式核对(交互)**

Run: `py -3.13 scripts\start-local.py`;核对:
1. 选人 + 填原因后约 0.6s,预览面板自动出现卡片(未点「更新预览」)
2. 清空原因 → 预览立即消失;重填 → 再次自动出现
3. 改分值 → 预览短暂消失后自动刷新
4. 预览面板「核对并发送」→ 确认弹窗 →「确认发送」全程 3 步完成(流程文案不动:表单按钮仍叫「更新预览」作兜底,面板按钮仍叫「核对并发送」)

- [ ] **Step 6:提交**

```bash
git add frontend/src/App.vue
git commit -m "feat: 表单防抖自动预览,发送路径从 6 步压缩到 3 步"
```

## Task 12:通知范围同记分对象 + 记分对象全员模式

**Files:**
- Modify: `frontend/src/App.vue`(mirror 勾选、targetIds all 分支、模板)

- [ ] **Step 1:脚本区追加镜像状态与同步**

`const manual = ref...` 附近追加:

```ts
const mirrorRecipients = ref(false)
```

watch 区追加:

```ts
watch([targets, mirrorRecipients], () => {
  if (mirrorRecipients.value) recipients.value = JSON.parse(JSON.stringify(targets.value))
}, { deep: true })
```

- [ ] **Step 2:targetIds 计算属性补 all 分支**

把现有 `targetIds` computed 整段替换为:

```ts
const targetIds = computed(() => {
  const ids = new Set<string>()
  for (const p of directory.value.people) {
    if (p.status !== 'active') continue
    const matchesPath = !targets.value.levels.some(l => l.length) || p.paths.some(path => targets.value.levels.every((idsAt, i) => !idsAt.length || idsAt.includes(path.ids[i] ?? '')))
    if (targets.value.mode === 'all') { if (matchesPath) ids.add(p.id) }
    else if (targets.value.person_ids.includes(p.id) && matchesPath) ids.add(p.id)
  }
  targets.value.extra_ids.forEach(id => ids.add(id))
  return [...ids]
})
```

- [ ] **Step 3:模板给记分对象选人器传 allow-all 并加镜像勾选**

`<PeoplePicker v-model="targets" :people="directory.people" :departments="directory.departments" title="记分对象" />` 改为:

```html
<PeoplePicker v-model="targets" :people="directory.people" :departments="directory.departments" title="记分对象" allow-all />
```

在「发送配置」select 与 `<div class="preset-actions">...` 所在 div 之后、第二个 PeoplePicker 之前插入:

```html
<label class="mirror-toggle"><input type="checkbox" v-model="mirrorRecipients">通知范围同记分对象</label>
```

并把第二个 PeoplePicker 改为条件渲染:

```html
<PeoplePicker v-if="!mirrorRecipients" v-model="recipients" :people="directory.people" :departments="directory.departments" title="通知范围" allow-all />
```

- [ ] **Step 4:style.css 追加镜像勾选样式**

在「操作台」分区追加:

```css
.mirror-toggle{display:flex;align-items:center;gap:7px;font-size:var(--fs-sm)}
```

- [ ] **Step 5:构建验证**

Run: `cd frontend; npm run build`
Expected: 通过

- [ ] **Step 6:演示模式核对**

1. 勾选「通知范围同记分对象」→ 第二个选人器消失,通知对象数与记分对象同步
2. 记分对象选人器出现「范围内全部人员」单选;选一个部门 + 全员模式 → 最终总分列出该部门全部在职人员
3. 取消勾选 → 通知范围选人器恢复

- [ ] **Step 7:提交**

```bash
git add frontend/src/App.vue frontend/src/style.css
git commit -m "feat: 通知范围可镜像记分对象,记分对象支持全员模式"
```

## Task 13:表单分区 + 通知范围默认折叠

**Files:**
- Modify: `frontend/src/App.vue`(操作台模板重构)
- Modify: `frontend/src/style.css`(分区与折叠样式)

- [ ] **Step 1:模板重构 op-form 为两个分区**

将 `<fieldset class="op-form" :disabled="busy">` 到对应 `</fieldset>` 之间(第 226-238 行)整体替换为:

```html
<fieldset class="op-form" :disabled="busy">
  <div class="form-section">
    <div class="section-title"><span class="prompt">&gt;</span> 记分</div>
    <PeoplePicker v-model="targets" :people="directory.people" :departments="directory.departments" title="记分对象" allow-all />
    <div><div class="field-label"><span class="prompt">&gt;</span> 操作类型</div><div class="f-seg"><button type="button" class="opt plus" :class="{ active: operation === 'plus' }" @click="operation = 'plus'">＋ 加分</button><button type="button" class="opt minus" :class="{ active: operation === 'minus' }" @click="operation = 'minus'">－ 扣分</button></div></div>
    <div><label class="field-label" for="points"><span class="prompt">&gt;</span> 每人分值</label><div class="f-points"><span :class="operation === 'plus' ? 'plus-text' : 'minus-text'">{{ operation === 'plus' ? '+' : '−' }}</span><input id="points" v-model.number="points" type="number" min="1" step="1" :class="operation === 'plus' ? 'plus-text' : 'minus-text'"><span class="unit">分</span><div class="stepper"><button type="button" aria-label="减少分值" @click="points = Math.max(1, points - 1)">−</button><button type="button" aria-label="增加分值" @click="points++">＋</button></div></div></div>
    <div><label class="field-label" for="reason"><span class="prompt">&gt;</span> 原因 <small>必填</small></label><textarea id="reason" v-model="reason" maxlength="2000" rows="3" placeholder="填写原因"></textarea></div>
    <div v-if="selectedPeople.length"><div class="field-label"><span class="prompt">&gt;</span> 最终总分</div><div v-for="person in selectedPeople" :key="person.id" class="balance-row" role="group" :aria-label="`${person.name}总分`"><EmployeeAvatar :src="person.avatar_url" :name="person.name" size="small" /><div><b>{{ person.name }}</b><span class="balance-line">{{ totals[person.id] ?? 60 }} → <b :class="operation === 'plus' ? 'plus-text' : 'minus-text'">{{ manual[person.id] ? overrides[person.id] : (totals[person.id] ?? 60) + delta }}</b></span></div><label class="manual-toggle"><input type="checkbox" :checked="manual[person.id] ?? false" @change="toggleManual(person, ($event.target as HTMLInputElement).checked)">手动总分</label><input v-if="manual[person.id]" v-model.number="overrides[person.id]" class="override-input" type="number" step="1" :aria-label="`${person.name}最终总分`"></div><p v-if="selectedPeople.some(person => manual[person.id])" class="hint">手动总分已包含本次加减。</p></div>
  </div>
  <div class="form-section">
    <div class="section-title"><span class="prompt">&gt;</span> 发送配置</div>
    <div><div class="field-label"><span class="prompt">&gt;</span> 个人发送配置</div><select v-model="presetId" aria-label="选择个人发送配置" @change="loadPreset"><option value="">临时范围</option><option v-for="preset in presets" :key="preset.id" :value="preset.id">{{ preset.name }}</option></select><div class="preset-actions"><input v-model="presetName" aria-label="发送配置名称" placeholder="配置名称"><button type="button" :disabled="!presetName.trim()" @click="savePreset">{{ presetId ? '更新' : '保存' }}</button><button v-if="presetId" type="button" @click="deletePreset">删除</button></div></div>
    <label class="mirror-toggle"><input type="checkbox" v-model="mirrorRecipients">通知范围同记分对象</label>
    <details v-if="!mirrorRecipients" class="recipient-fold" :open="!!recipientWarnings.length">
      <summary><span class="prompt">&gt;</span> 通知范围 <b>{{ resolvedRecipients.length }}</b> 人<small v-if="recipientWarnings.length"> · 存在冲突</small></summary>
      <PeoplePicker v-model="recipients" :people="directory.people" :departments="directory.departments" title="通知范围" allow-all />
    </details>
    <p v-for="warning in recipientWarnings" :key="warning" class="error-text">{{ warning }}</p>
  </div>
  <div class="send-summary"><b>{{ selectedPeople.length }}</b> 位记分对象 · <b>{{ resolvedRecipients.length }}</b> 位通知对象 · <b>{{ selectedPeople.length * resolvedRecipients.length }}</b> 条卡片</div>
  <button class="primary-button" :class="{ busy }" :disabled="busy || !selectedPeople.length || !reason.trim() || !resolvedRecipients.length || !!recipientWarnings.length" @click="makePreview">{{ busy ? '正在处理…' : '更新预览' }}</button>
</fieldset>
```

(原 `section-divider` 由分区间距取代,已删除)

- [ ] **Step 2:style.css 分区与折叠样式**

把 `.op-form{display:flex;flex-direction:column;gap:16px}` 改为 `gap:24px`,并追加:

```css
.form-section{display:flex;flex-direction:column;gap:20px}
.section-title{font-family:var(--mono);font-size:var(--fs-xs);color:var(--muted);letter-spacing:.02em}
.recipient-fold{border-top:1px solid var(--line);padding-top:8px}
.recipient-fold summary{display:flex;align-items:center;gap:5px;font-family:var(--mono);font-size:var(--fs-xs);color:var(--muted);margin-bottom:8px}
.recipient-fold summary b{font-family:var(--mono);font-weight:700;color:var(--text)}
.recipient-fold summary small{font-size:var(--fs-xs)}
```

删除 `.section-divider` 规则(模板已不再使用)。

- [ ] **Step 3:构建验证**

Run: `cd frontend; npm run build`
Expected: 通过

- [ ] **Step 4:演示模式核对**

1. 操作台分为「记分 / 发送配置」两个分区,各带等宽小标题
2. 通知范围默认折叠为「通知范围 N 人」摘要行;点击展开选人器
3. 存在范围警告时折叠区自动展开
4. 首屏高度明显下降(桌面一屏内能看到发送摘要)

- [ ] **Step 5:提交**

```bash
git add frontend/src/App.vue frontend/src/style.css
git commit -m "feat: 操作台表单分区,通知范围默认折叠"
```

## Task 14:部门筛选折叠 + 空层级隐藏 + 搜索自动聚焦

**Files:**
- Modify: `frontend/src/components/PeoplePicker.vue`(props、模板、样式)

- [ ] **Step 1:props 加 autofocus 并计算触屏判断**

把 `const props = defineProps<{ modelValue: Selection; people: Person[]; departments: Department[]; title: string; allowAll?: boolean }>()` 改为:

```ts
const props = defineProps<{ modelValue: Selection; people: Person[]; departments: Department[]; title: string; allowAll?: boolean; autofocus?: boolean }>()
const coarsePointer = window.matchMedia('(pointer: coarse)').matches
```

同时在 App.vue 给记分对象选人器启用自动聚焦:把 `<PeoplePicker v-model="targets" :people="directory.people" :departments="directory.departments" title="记分对象" allow-all />` 改为:

```html
<PeoplePicker v-model="targets" :people="directory.people" :departments="directory.departments" title="记分对象" allow-all autofocus />
```

- [ ] **Step 2:模板包折叠 + 空层级隐藏 + 自动聚焦**

把:

```html
<div class="department-grid">
  <label v-for="level in 3" :key="level">{{ ['一级部门', '二级部门', '三级部门'][level - 1] }}
    <select multiple :aria-label="`${title}${level}级部门`" :value="modelValue.levels[level - 1]" @change="changeLevel(level - 1, $event)">
      <option v-for="d in options(level - 1)" :key="d.id" :value="d.id">{{ d.name }}</option>
    </select>
  </label>
</div>
```

替换为:

```html
<details class="department-fold">
  <summary>按部门筛选<small v-if="modelValue.levels.flat().length"> 已选 {{ modelValue.levels.flat().length }} 个部门</small></summary>
  <div class="department-grid">
    <label v-for="level in 3" :key="level" v-if="options(level - 1).length">{{ ['一级部门', '二级部门', '三级部门'][level - 1] }}
      <select multiple :aria-label="`${title}${level}级部门`" :value="modelValue.levels[level - 1]" @change="changeLevel(level - 1, $event)">
        <option v-for="d in options(level - 1)" :key="d.id" :value="d.id">{{ d.name }}</option>
      </select>
    </label>
  </div>
</details>
```

搜索框 `<input v-model="query" type="search" :aria-label="`${title}姓名搜索`" placeholder="搜索姓名" @input="page = 1">` 改为:

```html
<input v-model="query" type="search" :aria-label="`${title}姓名搜索`" placeholder="搜索姓名" :autofocus="autofocus && !coarsePointer" @input="page = 1">
```

- [ ] **Step 3:scoped 样式追加折叠样式与字号**

在 `<style scoped>` 中追加:

```css
.department-fold{margin-bottom:10px}
.department-fold summary{font-family:var(--mono);font-size:var(--fs-xs);color:var(--muted);margin-bottom:8px}
.department-fold summary small{font-size:var(--fs-xs)}
```

并把 `.department-grid select{...font-size:var(--fs-xs)...}` 的 `font-size` 改为 `12px`。

- [ ] **Step 4:构建验证**

Run: `cd frontend; npm run build`
Expected: 通过

- [ ] **Step 5:演示模式核对**

1. 记分对象区不再直接显示三个部门下拉,改为「按部门筛选」折叠行
2. 进入页面(桌面)光标自动落在姓名搜索框,直接打字
3. 手机浏览器打开时不自动弹键盘
4. 只有一级部门时,二三级空下拉不再渲染

- [ ] **Step 6:提交**

```bash
git add frontend/src/components/PeoplePicker.vue
git commit -m "feat: 部门筛选折叠、空层级隐藏与搜索自动聚焦"
```

## Task 15:快捷分值 + 最近原因 chips

**Files:**
- Modify: `frontend/src/App.vue`(脚本 + 模板)
- Modify: `frontend/src/style.css`(chips 样式)

- [ ] **Step 1:脚本区追加 chips 逻辑**

在 `const reason = ref('')` 附近追加:

```ts
const pointQuick = [1, 2, 5, 10, 20]
function stepPoints(step: number, event: MouseEvent) { points.value = Math.max(1, points.value + (event.shiftKey ? 5 : 1) * step) }
function loadRecentReasons(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem('recentReasons') ?? '[]')
    return Array.isArray(raw) ? raw.filter((item: unknown): item is string => typeof item === 'string').slice(0, 5) : []
  } catch { return [] }
}
const recentReasons = ref<string[]>(loadRecentReasons())
function rememberReason(value: string) {
  const trimmed = value.trim()
  if (!trimmed) return
  recentReasons.value = [trimmed, ...recentReasons.value.filter(item => item !== trimmed)].slice(0, 5)
  try { localStorage.setItem('recentReasons', JSON.stringify(recentReasons.value)) } catch { /* 存储不可用时静默 */ }
}
```

- [ ] **Step 2:commit() 记录原因**

在 `commit` 函数中,把:

```ts
confirmation.value = false; preview.value = null; targets.value = emptySelection(); manual.value = {}; overrides.value = {}; reason.value = ''
```

改为:

```ts
confirmation.value = false; preview.value = null; targets.value = emptySelection(); manual.value = {}; overrides.value = {}; rememberReason(reason.value); reason.value = ''
```

- [ ] **Step 3:模板改步进与追加 chips**

步进按钮两个 `@click` 改为:

```html
<button type="button" aria-label="减少分值" @click="stepPoints(-1, $event)">−</button>
<button type="button" aria-label="增加分值" @click="stepPoints(1, $event)">＋</button>
```

分值输入 div(`</div></div></div>` 结束前,即 `.f-points` 闭合之后)追加:

```html
<div class="point-quick"><button v-for="value in pointQuick" :key="value" type="button" :class="{ active: points === value }" @click="points = value">{{ value }}</button></div>
```

原因 textarea 之后追加:

```html
<div v-if="recentReasons.length" class="reason-quick"><button v-for="item in recentReasons" :key="item" type="button" :title="item" @click="reason = item">{{ item }}</button></div>
```

- [ ] **Step 4:style.css 追加 chips 样式**

在「操作台」分区追加:

```css
.point-quick{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.point-quick button{flex:none;padding:4px 10px;font-size:var(--fs-sm)}
.point-quick button.active{border-color:var(--accent);color:var(--accent-deep);background:var(--accent-soft)}
.reason-quick{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.reason-quick button{flex:none;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:4px 10px;font-size:var(--fs-xs);font-family:var(--sans);background:var(--surface-2)}
.reason-quick button:hover:not(:disabled){border-color:var(--accent)}
```

- [ ] **Step 5:构建验证**

Run: `cd frontend; npm run build`
Expected: 通过

- [ ] **Step 6:演示模式核对**

1. 分值下出现 1/2/5/10/20 chips,单击赋值,当前值高亮
2. Shift + 点步进按钮按 5 进位
3. 发送一笔记分后,原因 chips 出现该原因;再次点击即填入

- [ ] **Step 7:提交**

```bash
git add frontend/src/App.vue frontend/src/style.css
git commit -m "feat: 快捷分值 chips 与最近原因记忆"
```

## Task 16:导航清理 · 禁用原因提示 · 成功条自动消失 · 历史加载态

**Files:**
- Modify: `frontend/src/App.vue`(脚本 + 模板)
- Modify: `frontend/src/style.css`(成功条样式)

- [ ] **Step 1:导航移除硬编码基础分**

把 `<span>{{ month }} · 基础分 60</span>` 改为 `<span>{{ month }}</span>`

- [ ] **Step 2:脚本区追加 submitHint 与 notice 自动消失**

`import { computed, onMounted, onUnmounted, ref, watch } from 'vue'` 改为 `import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'`

脚本区追加:

```ts
const recipientsPending = computed(() => (recipients.value.person_ids.length > 0 || recipients.value.extra_ids.length > 0 || recipients.value.levels.some(l => l.length)) && !resolvedRecipients.value.length)
const submitHint = computed(() => {
  if (busy.value) return '正在处理…'
  if (!selectedPeople.value.length) return '请先选择记分对象'
  if (!reason.value.trim()) return '请填写原因'
  if (recipientWarnings.value.length) return '通知范围存在冲突,请先处理'
  if (recipientsPending.value) return '正在解析通知范围…'
  if (!resolvedRecipients.value.length) return '请选择通知范围'
  return ''
})
const noticeBar = ref<HTMLElement | null>(null)
const noticePaused = ref(false)
let noticeTimer: ReturnType<typeof setTimeout> | undefined
watch(notice, async (value) => {
  clearTimeout(noticeTimer)
  if (!value) return
  await nextTick()
  noticeBar.value?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  if (!noticePaused.value) noticeTimer = setTimeout(() => { notice.value = '' }, 5000)
})
function pauseNotice() { noticePaused.value = true; clearTimeout(noticeTimer) }
function resumeNotice() { noticePaused.value = false; if (notice.value) noticeTimer = setTimeout(() => { notice.value = '' }, 5000) }
```

onUnmounted 追加 `clearTimeout(noticeTimer)`。

- [ ] **Step 3:模板改 notice 条与按钮下提示**

把 `<div v-if="notice" class="feedback" role="status">{{ notice }}</div>` 改为:

```html
<div v-if="notice" ref="noticeBar" class="feedback success" role="status" @mouseenter="pauseNotice" @mouseleave="resumeNotice">{{ notice }}<button aria-label="关闭提示" @click="notice = ''">×</button></div>
```

在操作台表单「更新预览」按钮之后追加:

```html
<p v-if="submitHint" class="hint submit-hint" aria-live="polite">{{ submitHint }}</p>
```

- [ ] **Step 4:历史加载态**

脚本区 `const history = ref...` 附近追加 `const loadingHistory = ref(false)`,并把 `loadHistory` 改为:

```ts
async function loadHistory() {
  loadingHistory.value = true
  try {
    const result = await api<{ items: HistoryItem[]; total: number }>('/adjustments?page=' + historyPage.value)
    const balances = await api<Balances>('/balances')
    history.value = result.items; historyTotal.value = result.total; applyBalances(balances)
  } finally { loadingHistory.value = false }
}
```

模板把 `<div v-if="!history.length" class="empty-state">还没有操作记录。</div>` 改为:

```html
<div v-if="loadingHistory" class="empty-state">加载中…</div>
<div v-else-if="!history.length" class="empty-state">还没有操作记录。</div>
```

- [ ] **Step 5:style.css 成功条与提示样式**

在「提示反馈」分区追加:

```css
.feedback.success{border-color:var(--plus);color:var(--plus-ink)}
.submit-hint{margin:8px 0 0}
```

- [ ] **Step 6:构建验证**

Run: `cd frontend; npm run build`
Expected: 通过

- [ ] **Step 7:演示模式核对**

1. 导航右侧只显示月份
2. 打开操作台不选人:按钮下方显示「请先选择记分对象」,随条件变化实时更新
3. 保存配置等成功提示 5 秒后自动消失,悬停时暂停,可手动 × 关闭
4. 切到发送记录:网络慢时先显示「加载中…」再出数据

- [ ] **Step 8:提交**

```bash
git add frontend/src/App.vue frontend/src/style.css
git commit -m "feat: 禁用原因可见、成功提示自动消失与历史加载态"
```

## Task 17:键盘操作(Esc / 聚焦 / Enter / type 修正)

**Files:**
- Modify: `frontend/src/App.vue`(键盘处理、聚焦、form 包裹、按钮 type)

- [ ] **Step 1:脚本区 Esc 处理与聚焦**

`const clock = ref(Date.now())` 附近追加:

```ts
const confirmSend = ref<HTMLButtonElement | null>(null)
const recallSend = ref<HTMLButtonElement | null>(null)
const detailClose = ref<HTMLButtonElement | null>(null)
```

`action` 函数之后追加:

```ts
function onKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape' || busy.value) return
  if (recallConfirmation.value) recallConfirmation.value = null
  else if (detail.value) closeDetail()
  else if (confirmation.value) confirmation.value = false
}
watch(confirmation, async (value) => { if (value) { await nextTick(); confirmSend.value?.focus() } })
watch(recallConfirmation, async (value) => { if (value) { await nextTick(); recallSend.value?.focus() } })
watch(detail, async (value) => { if (value) { await nextTick(); detailClose.value?.focus() } })
```

`onMounted` 内追加 `window.addEventListener('keydown', onKeydown)`,onUnmounted 内追加 `window.removeEventListener('keydown', onKeydown)`。

- [ ] **Step 2:模板三处按钮加 ref**

1. 确认发送弹窗:「确认发送」按钮加 `ref="confirmSend"`
2. 确认撤回弹窗:「确认撤回」按钮加 `ref="recallSend"`
3. 发送结果弹窗:关闭按钮加 `ref="detailClose"`

- [ ] **Step 3:op-form 包 form + 按钮 type 修正**

`<fieldset class="op-form" :disabled="busy">` 改为:

```html
<form class="op-form" @submit.prevent="makePreview"><fieldset class="op-form-body" :disabled="busy">
```

对应 `</fieldset>`(「更新预览」按钮之后)改为 `</fieldset></form>`

「更新预览」按钮 `<button class="primary-button" :class="{ busy }" :disabled="busy || !selectedPeople.length || !reason.trim() || !resolvedRecipients.length || !!recipientWarnings.length" @click="makePreview">` 改为:

```html
<button class="primary-button" :class="{ busy }" type="submit" :disabled="busy || !selectedPeople.length || !reason.trim() || !resolvedRecipients.length || !!recipientWarnings.length">
```

(去掉 `@click` —— 表单 submit 触发;makePreview 已有守卫,Enter 空表单不会误发)

- [ ] **Step 4:style.css 分区样式跟随**

`.op-form{display:flex;flex-direction:column;gap:24px}` 之后追加:

```css
.op-form-body{display:flex;flex-direction:column;gap:24px}
```

- [ ] **Step 5:构建验证**

Run: `cd frontend; npm run build`
Expected: 通过

- [ ] **Step 6:演示模式核对**

1. 打开确认发送弹窗,主按钮已聚焦,直接按 Enter 提交
2. 三个弹窗均可用 Esc 关闭;撤回确认在发送结果之上时,Esc 先关撤回
3. 表单内(分值/配置名称)按 Enter 触发预览更新
4. 所有「保存/更新/删除」等非提交按钮点击行为不变(它们本就有 `type="button"`;PeoplePicker 内按钮已全部有 `type="button"`)

- [ ] **Step 7:提交**

```bash
git add frontend/src/App.vue frontend/src/style.css
git commit -m "feat: 键盘操作(Esc 关闭、自动聚焦、Enter 提交)"
```

## Task 18:移动端专项(底部操作栏 · 触控目标 · 总分网格)

**Files:**
- Modify: `frontend/src/App.vue`(模板:底部操作栏、按钮加类名)
- Modify: `frontend/src/style.css`(底栏、触控、balance-row 网格)
- Modify: `frontend/src/components/PeoplePicker.vue`(翻页按钮触控)

- [ ] **Step 1:App.vue 按钮加类名**

「更新预览」按钮 `class="primary-button"` 改为 `class="primary-button form-submit"`;预览面板「核对并发送」按钮 `class="primary-button"` 改为 `class="primary-button preview-send"`。

- [ ] **Step 2:App.vue 模板底部追加移动操作栏**

`</template>` 之前的最后一个元素(确认撤回弹窗 Transition 之后)追加:

```html
<div class="mobile-actions">
  <button v-if="!preview" type="button" :disabled="busy || !selectedPeople.length || !reason.trim() || !resolvedRecipients.length || !!recipientWarnings.length" @click="makePreview">{{ busy ? '正在处理…' : '更新预览' }}</button>
  <button v-else class="primary-button" type="button" :disabled="busy || !validPreview" @click="confirmation = true">核对并发送</button>
</div>
```

- [ ] **Step 3:style.css 底部操作栏 + 触控目标 + 总分网格**

在「响应式」分区追加:

```css
.mobile-actions{display:none}
@media(max-width:820px){
  .mobile-actions{display:flex;position:fixed;left:0;right:0;bottom:0;gap:8px;padding:10px 16px calc(10px + env(safe-area-inset-bottom,0px));background:var(--surface);border-top:1px solid var(--line);z-index:8}
  .mobile-actions>button{flex:1}
  .mobile-actions .primary-button{width:auto;padding:12px 16px}
  .form-submit,.preview-send{display:none}
  .page{padding-bottom:96px}
}
```

触控目标:`.pagination button{padding:4px 7px;font-size:var(--fs-xs)}` 改为 `padding:5px 10px`(≥28px 高)。

总分两行网格:把 `.balance-row{display:flex;align-items:center;gap:10px;border-bottom:1px solid var(--line);padding:8px 0;font-size:var(--fs-sm);flex-wrap:wrap}` 改为:

```css
.balance-row{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:8px 10px;border-bottom:1px solid var(--line);padding:8px 0;font-size:var(--fs-sm)}
```

`.balance-row>div{flex:1;min-width:120px}` 改为 `.balance-row>div{min-width:0}`;

`.manual-toggle{display:flex;align-items:center;gap:5px;font-size:var(--fs-xs);color:var(--muted)}` 改为:

```css
.manual-toggle{grid-column:2;grid-row:2;justify-self:end;display:flex;align-items:center;gap:5px;font-size:var(--fs-xs);color:var(--muted)}
```

`input.override-input{width:90px;font-family:var(--mono);padding:5px}` 改为:

```css
input.override-input{grid-column:3;grid-row:2;width:90px;font-family:var(--mono);padding:5px}
```

- [ ] **Step 4:PeoplePicker 翻页按钮触控(420px 覆盖)**

把 scoped 样式中 `@media(max-width:420px)` 块内的 `.picker-tools .pagination button{padding:3px}` 改为 `padding:5px 10px`。

- [ ] **Step 5:构建验证**

Run: `cd frontend; npm run build`
Expected: 通过

- [ ] **Step 6:第三批验收 · 演示模式逐屏核对(桌面 + 移动视口)**

Run: `py -3.13 scripts\start-local.py`;用开发者工具切换 375px / 768px / 桌面宽度:

| 检查点 | 桌面 | 移动 |
|--------|------|------|
| 单人记分(选人 → 填原因 → 核对并发送 → 确认发送)≤3 步 | ✓ | ✓ |
| 记分链路可全程键盘(Esc/Enter/聚焦) | ✓ | — |
| 底部固定操作栏出现且不遮内容(安全区) | — | ✓ |
| 总分行姓名与数字对齐、手动总分在第二行 | ✓ | ✓ |
| 翻页/撤回等小按钮触控区 ≥28px | — | ✓ |
| 部门筛选折叠、通知范围折叠在窄屏正常 | ✓ | ✓ |

- [ ] **Step 7:提交**

```bash
git add frontend/src/App.vue frontend/src/style.css frontend/src/components/PeoplePicker.vue
git commit -m "feat: 移动端底部操作栏、触控目标与总分网格对齐"
```

---

## 收尾

- [ ] **最终构建**:`cd frontend; npm run build` 通过,无 TS 报错
- [ ] **全屏走查**:桌面 + 375px 各走一遍三个页面与三弹窗,对照规格 §8 实施红线确认未破坏(语义色纪律、无障碍基线、预览 5 分钟校验、提交后智能重置、头像回退、空态)
- [ ] **确认无遗漏**:对照规格 §4/§5/§6 逐条勾选;§7「不做/延后」六项未实现属预期
