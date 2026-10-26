# WORKFLOW 邵子渊个人工作台小门户 v1.0

## 需求与验收

目标用户:`shaoziyuan`(个人工作台目录 `portal/personal-workspaces/pending-gov-risk/`,线上
`/personal-workspaces/pending-gov-risk/index.html`)。

用户原话要点(2026-10-26):

1. 把现有个人工作台做成一个小门户,左侧导航栏;
2. "工单系统性原因研判"改名"政诉预判",作为门户里的一个子模块;
3. 把自己在公共事务(`/heng/`)里动手开发过的模块 1:1 复制一份进来,成为这边的子模块,以后只在这里做个人版本;
4. 一个综合 dashboard,内容先由 AI 规划,后续用户再改。

验收:

- 打开工作台默认进入"总览"dashboard;左侧导航可切换到每个子模块,刷新后停留在当前模块(hash 路由);
- "政诉预判"保留原研判页全部功能(读结果、下钻、跟进保存、409 冲突保护、手动重跑、轮询),文案改名;
- 复制进来的模块外观和交互与公共事务原版一致,调用同一套后端接口、同一份数据;
- 复制模块里跳到"没复制的公共事务页面"(如政策分析)时,明确跳回公共事务原版,不出现空白页;
- 总览 dashboard 每张卡片独立读取真实接口,失败显示原因,不伪造数据;
- 桌面与窄屏(390px)都不溢出;本地真实浏览器验证。

明确不做:不复制后端(复制模块与公共事务共用数据,写操作会改到同一份数据);不改公共事务、账号、
nginx、个人工作台访问校验;不部署。

## 要复制哪些模块(按 git 提交作者 ZaynShao / didi@Zayn-Shao.local 核对)

| 公共事务导航 | 原文件 | 用户的主要提交 | 是否复制 |
|---|---|---|---|
| 工作台 · 政策大盘 | `views/dashboard/PolicyDashboard.vue` + `components/dashboard/PolicyMap.vue` | 6dd9b8fd 政策大盘对齐工程层 L2(+120/−91)、58744a95 / fa96f3ad 知识库数据源 | 复制 |
| 政策工作 · 政策解读 | `views/policy/PolicyInterpretation.vue` + `api/policy-qa.ts` | 496a3e7e 问答界面落到政策解读页(重写)、d7c05f0b、706be42c、7845eff1、ed2844d0 | 复制 |
| 政策工作 · 政策知识库 | `views/policy/PolicyKnowledgeBase.vue` + `api/knowledge.ts` | 970081e3 在线政策知识库(+256/−125) | 复制 |
| 政策工作 · 政策图谱 | `views/policy/PolicyGraph.vue` | 970081e3 新建、66f56d98 | 复制 |
| 政策工作 · 政策月刊 | `views/monthly/*` + `monthly-content.ts` | 2984742c 月刊 v2 渲染 + 容错提示条 + 修改意见栏 | 复制 |
| 管理配置 · 政策数据源 | `views/policy/ImportSettings.vue` + `api/crawler.ts` | f44ddcef 采集队列控制台、6ac6f1e2 / b449c510 / c02b636e / 76d5b037 / 17734765 批量导入 | 复制 |
| 管理配置 · 源质量审核 | `views/quality/L1ReviewQueue.vue` + `api/l1Review.ts` | a8c1fb1c 新建 | 复制 |
| 政策分析 | `views/policy/PolicyAnalysis.vue` | 只有 58744a95 的数据源切换(+23/−5) | 不复制,跳回原版 |
| 拜访清单(移动端语音录入) | `MobileVisitInputModal.vue` | fa3fd276 | 是拜访清单里的一个功能,不是独立模块,不复制 |
| 顶栏消息铃铛 | `TopBar.vue` | 876ea5f9 | 公共事务外壳,不复制 |

行业预判板(`portal/industry-board/`)也是用户写的,但在政策预判模块、不在公共事务里,本次不纳入。

## 方案

比较三条路线:

1. iframe 嵌公共事务原页面 —— 不是副本,以后无法"只在这里做个人版本",排除;
2. 把 Vue 页面手工改写成原生 JS —— 约 8000 行,1:1 还原风险高,以后改起来也不顺手,排除;
3. **在个人目录里放一份 Vue 源码副本,用 Vite 构建成静态文件提交** —— 复制的 `.vue/.ts` 与原版逐字一致,
   以后在副本上照常做 Vue 开发。采用。

### 目录

```
portal/personal-workspaces/pending-gov-risk/
  index.html                 手写入口页,只引 ./assets/index.js 与 ./assets/index.css(目录里唯一的 .html)
  assets/                    构建产物(提交;nginx 已对本目录 no-store,文件名不带 hash)
  workbench.json             不改(见"风险与遗留":标题被登记脚本钉住)
  build.mjs  tsconfig.json   构建脚本:以 src/main.ts 为 JS 入口,复用公共事务前端已锁定的依赖,不新增 lockfile
  README.md                  开发、构建、模块来源
  src/
    main.ts App.vue router.ts styles/portal.css
    shell/                   门户外壳(左侧导航、回原版跳转)
    views/home/Overview.vue  综合 dashboard(新)
    views/gov-risk/          政诉预判(原 app.js → gov-risk-app.mjs,改成可挂载/卸载;原 style.css → gov-risk.css,全局规则收进 .gr-wrap)
    api/ components/ stores/ styles/ utils/ views/...   从 services/heng-guan/frontend/src 逐字复制,目录结构不变
```

### 复制时必须改的地方(其余逐字一致)

- `api/client.ts`、`utils/geojson.ts`:原版用 `import.meta.env.BASE_URL` 拼 `/heng/` 前缀;副本部署在个人目录,
  改为固定 `/heng`。地图底图直接读公共事务已部署的 `/heng/geojson/*`,不复制 4.3MB 静态数据。
- `views/monthly/MonthlyDetail.vue`:月刊 AI 对话的地址原版写成 `/api/v1/...`(在平台上会落到根路径),
  副本改用 `apiBase`。
- 路由:hash 模式;复制模块的路由路径保持与原版相同(`/dashboard/policy`、`/policy/knowledge` 等),
  原代码里的 `router.push` 不用改;没复制的路径(如 `/policy` 政策分析)统一由兜底路由跳回 `/heng` 原版。

### 门户与导航

左侧导航沿用公共事务侧栏的分组样式(平台 `platform-sidebar.css/js` 认这套 class):

- 工作台:总览
- 政诉工作:政诉预判
- 政策工作:政策大盘、政策解读、政策知识库、政策图谱、政策月刊
- 管理配置:政策数据源、源质量审核(后端按公共事务 MANAGER 权限校验,无权限时页面显示原因)

窄屏下侧栏改成顶部横向滚动导航。

### 总览 dashboard(第一版,用户后续再改)

全部读真实接口,每张卡片单独加载、单独报错:

| 卡片 | 接口 | 内容 |
|---|---|---|
| 政诉预判 | `/heng/api/v1/gov-risk/package`、`/feedback` | 高/中优先候选、修复后复发、关单后仍出现;最近研判状态;需要关注的前 5 个候选及跟进状态 |
| 政策知识库 | `/heng/api/v1/knowledge/stats`、`/knowledge/sync/status` | 政策数、高重要性、主题、关系;最近同步 |
| 政策月刊 | `/heng/api/v1/monthlies` | 最近几期与状态,草稿/审核中数量 |
| 源质量审核 | `/heng/api/v1/l1-review` | 待审核条数,按类型分布 |
| 采集队列 | `/heng/api/v1/crawler-rules/queue/status` | 积压、失败、最早待处理 |
| 政策解读服务 | `/policy-qa/v1/health` | 问答服务是否可用 |

顶部"今天要处理的事"由以上结果汇总(研判失败、修复后复发、待审核源、采集失败、未发布月刊),没有就写"暂无"。

### 构建与验证

- `node portal/personal-workspaces/pending-gov-risk/build.mjs`(需先在 `services/heng-guan/frontend` 执行 `npm ci`);
  `--check` 只构建到临时目录并与已提交产物比对。
- 不新增 CI job(避免公共事务依赖升级把个人目录的构建弄红而挡住别人的 PR);
  `portal/tests/gov-risk-workbench.test.cjs` 扩展为静态约束:清单、目录只有一个 .html、导航与路由、复制模块路由与原版同路径、
  只调平台同源接口、不引外部资源、入口产物齐全、409 与轮询停止。
- `.github/workflows/p0-gates.yml` 里原有的 `node --check …/pending-gov-risk/app.js` 改为检查新位置的 `gov-risk-app.mjs`
  (CI 用 Node 20,ESM 语法用 `.mjs` 才能稳定 `--check`)。这是 infra 文件,PR 标 `[CROSS-MODULE]`。
- 本地:Vite 产物 + 本地 mock 接口在真实 Chromium 里点每个模块,桌面 1440 与窄屏 390。

## 三轮自检

1. 用户原话:"1:1 复制"→ 源码逐字复制并保持原目录结构,只改部署前缀这类必须改的地方;"以后只在这里做个人版本"→
   副本是可继续开发的 Vue 源码,不是 iframe;"顺便改名"→ 页面标题、导航、文案改成政诉预判(登记标题见"风险与遗留")。
2. 产品事实:个人工作台目录由 nginx 直接静态托管、无构建步骤、同源带平台登录态,公共事务接口与政策问答接口都认这个登录态;
   复制模块共用公共事务数据,写操作(月刊发布、审核结论、采集任务)会改到同一份数据,README 和页面不掩盖这一点。
3. 交付:独立 worktree、`codex/personal-workspace-portal` 分支、PR 后盯 P0 Gates;不部署。

## 实施中发现并处理的问题

- 平台下拉 `platform-select.js` 刻意不接管 Vue 根节点里的原生 select,政诉预判挂进门户后筛选和跟进状态退回了系统下拉。
  改为在脱离文档时调用 `window.PlatformSelect.enhance` 再放回原位;切走模块时平台脚本按"节点被移除"自动回收菜单(已实测回收为 0)。
- `tokens.css` 的移动端覆盖写在基础规则之前不生效(公共事务原版同样如此),窄屏下统计卡挤成一排、知识库与月刊详情横向溢出。
  `src/styles/portal.css` 在其后原样再放一次,10 个路由在 390px 下均无横向溢出。
- 个人工作台登记脚本会逐个校验目录里的 `.html`(`tests/test_register_suwanyi_workbench.py` 钉住本目录 1 个页面),
  所以不用 Vite 的 HTML 模板,改为 JS 入口 + 手写入口页。
- 兜底跳转用 `location.replace`,从公共事务原版后退不会被反复弹回去。

## 风险与遗留

- **工作台登记标题未改**:`workbench.json` 的 title 被 `scripts/register-suwanyi-workbench.py`(TITLES / MANIFESTS)和生产绑定记录钉住为
  "工单系统性原因研判"。只改清单会让登记/巡检报 `reviewed_manifest_mismatch`。本次页面内所有可见名称已改为"政诉预判"/"我的工作台";
  平台个人工作台入口卡片上的登记标题需要单独一步:同时改清单与登记脚本,合并部署后由维护人跑登记工作流更新绑定标题。
- 复制模块里月刊的 `renderMd` 不转义 HTML 就 `v-html`(公共事务原版同样如此),月刊正文来自产线与 AI,风险低但存在,未在本次改动。
- 副本与原版之后会分叉:公共事务原版修的 bug 不会自动进副本。
- 构建产物入库,改源码后必须重新构建并一起提交;`build.mjs --check` 能发现漏构建。

## 验证记录(2026-10-26,本地)

- `build.mjs --typecheck`:vue-tsc 通过;`build.mjs --check`:两次构建逐字一致(37 个产物文件,约 1.6MB,其中地图 echarts 约 1.1MB 按需加载)。
- `node --test portal/tests/gov-risk-workbench.test.cjs`:11/11;`node --check gov-risk-app.mjs` 通过。
- `tests/test_register_suwanyi_workbench.py` 的登记用例通过(本目录仍是 1 个页面);`test_audit_personal_workbenches.py` 通过;
  portal 侧个人工作台相关测试(catalog / owner-isolation / onboarding / homepage-routing / topbar-icons)通过。
  本机没有 Docker,`test_personal_workbench_deployment.py` 与 Docker 模板用例无法在本地跑,以 CI 为准;
  `platform-select-coverage.test.cjs` 在 master 上就失败(policy-mcp.html、strategy-workbench.html),与本次无关且未纳入 CI。
- 真实 Chromium(本地静态服务 + 合成接口夹具,**不是生产数据**):10 个路由逐个打开无 JS 报错;1440 与 390 宽度无横向溢出;
  政诉预判筛选(平台下拉 + 键盘)、跟进保存(revision 3→4)、另一处先保存后本页 409 暂停保存且保留编辑、切走模块菜单回收为 0;
  总览在政诉/队列/问答接口失败时逐卡显示原因、"今天要处理的事"注明哪几项没读到;政策大盘跳"政策分析"时带参数打开公共事务原版。
- 未部署;生产平台顶栏、真实权限(MANAGER)和真实数据需合并部署后由所有者登录验证。
