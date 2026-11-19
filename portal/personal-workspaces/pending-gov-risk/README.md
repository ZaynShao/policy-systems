# 我的工作台(shaoziyuan)· 工单研判工作台

原平台入口:`/personal-workspaces/pending-gov-risk/index.html`(个人工作台,只对所有者开放)。

左侧导航的小门户,子模块:

| 导航 | 路由(hash) | 来源 | 独立版 |
|---|---|---|---|
| 工作台 · 总览 | `#/overview` | `src/views/home/Overview.vue`,各子模块关键数字和"今天要处理的事" | 有 |
| 政诉工作 · 政诉预判 | `#/gov-risk` | 原"工单系统性原因研判"页改名;逻辑仍是原生脚本 `src/views/gov-risk/gov-risk-app.mjs` | 有 |
| 政策大盘 / 政策解读 / 政策知识库 / 政策图谱 / 政策月刊 | `#/dashboard/policy` 等 | 原平台上是从公共事务复制的个人版本 | 没有 |
| 政策数据源 / 源质量审核 | `#/policy/import`、`#/quality/l1-review` | 同上 | 没有 |

## 独立版(本仓)

本仓只收我自己的提交,所以门户里只有我自己的两页:**总览**和**政诉预判**。

- 从公共事务复制来的政策模块是同事的页面,不在本仓;左侧导航(`src/shell/nav.ts`)照旧列出它们,标"原平台",
  点进去显示"这个页面不在独立版里"(`src/shell/NotInStandalone.vue`)。没复制的公共事务页面跳回原版的
  `src/shell/HengFallback.vue` 也依赖原平台,独立版不再挂路由。
- 总览里政策知识库、月刊、源质量审核、采集队列、政策解读服务几块读的是原平台的数据,独立版里会写明"独立版不含这块"。
- 政诉预判的接口前缀用我原来写的 guardian 前缀 `/guardian/api/gov-risk`(后来同事把研判后端迁到公共事务、改成
  `/heng/api/v1/gov-risk`,独立版不收这处改动);后端就是本仓的 `services/guardian-backend/src/gov-risk/`。
- 原来照同事原件改的入口、接口客户端、侧栏、提示条、全局样式(`tokens.css`、tailwind)都不在本仓,换成新写的最小外壳:
  `src/main.ts`、`src/api/client.ts`、`src/shell/Sidebar.vue`、`src/components/ui/ToastStack.vue`、`src/stores/toast.ts`、
  `src/styles/shell.css`;总览要用的三个接口文件 `src/api/knowledge.ts`、`monthly.ts`、`crawler.ts` 也是外壳,只留用到的字段。
  每个外壳文件开头都写了来历。
- 构建不再经过 tailwind(只有复制来的同事页面用它,我的两页不用)。
- `src/standalone/`、`demo/data/`、`build-offline.mjs` 是独立版的离线演示:演示数据是**编的样例工单**,
  研判结果是用我的研判引擎在本机算出来的,来历见 `demo/data/README.md`。

## 开发与构建

```bash
npm ci --prefix services/heng-guan/frontend          # 只需一次:构建借用公共事务前端底座锁定的依赖
node portal/personal-workspaces/pending-gov-risk/build.mjs --typecheck   # vue-tsc + 构建,覆盖 assets/
node portal/personal-workspaces/pending-gov-risk/build.mjs --check       # 已提交的 assets/ 是否与源码一致
node --test portal/tests/gov-risk-workbench.test.cjs
node portal/personal-workspaces/pending-gov-risk/build-offline.mjs       # 离线单文件页面 → dist/工单研判工作台-独立版.html
```

- `index.html` 是手写的入口页,只引 `./assets/index.js` 和 `./assets/index.css`;产物文件名固定不带 hash
  (nginx 对个人目录整体 `no-store`),所以改源码后只需重新构建,把 `src/` 和 `assets/` 一起提交。
- 个人工作台登记会逐个校验目录里的 `.html`,目录里只保留 `index.html` 这一个页面,不要再放 HTML 模板;
  离线页面因此输出到仓库根目录的 `dist/`。
- 平台顶栏由 `/platform-nav.js` 在正式/测试域名下补上,本地预览没有顶栏属正常;入口页里引的 `/platform-*.css|js` 是原平台的公共件。
- 政诉预判里的下拉是 `gov-risk-app.mjs` 显式交给 `window.PlatformSelect` 的;没有平台脚本时保留原生下拉。

离线页面双击就能打开,不用联网;顶部有一条醒目提示"演示数据是编的样例,不是真实工单"。
在页面里改跟进状态、写备注、重新研判都只在本页内存里生效,刷新即还原。

## 后端(services/guardian-backend)

```bash
cd services/guardian-backend
npm ci            # 依赖锁到原项目当时装的同一版本,装完自动按 prisma/gov-risk.prisma 生成数据库客户端
npm test          # 类型检查 + 研判测试 + 设备密钥测试 + 启动冒烟
npm run build && DATABASE_URL=… GOV_RISK_OWNER_USERNAME=… JWT_SECRET=… npm start
```

数据表只有研判的 5 张(`prisma/gov-risk.prisma`,建表 SQL 见 `prisma/migrations/`);口令、密钥只从环境变量读:
`JWT_SECRET`(平台登录)、`GOV_RISK_AGENT_TOKEN` 或 `GOV_RISK_AGENT_KEY_SHA256`(本机客户端,见 `docs/WORKFLOW-gov-risk-device-key-v1.0.md`)、
`LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL`(可选,不配就全部按规则兜底)。
`services/guardian/server.js` 是转发研判接口的小网关(原平台 guardian 前端里我写的两处转发规则 + 最小外壳)。
