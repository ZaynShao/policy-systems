# 我的工作台(shaoziyuan)

线上入口:`/personal-workspaces/pending-gov-risk/index.html`(个人工作台,只对所有者开放)。

左侧导航的小门户,子模块:

| 导航 | 路由(hash) | 来源 |
|---|---|---|
| 工作台 · 总览 | `#/overview` | 新写:`src/views/home/Overview.vue`,各子模块关键数字和"今天要处理的事" |
| 政诉工作 · 政诉预判 | `#/gov-risk` | 原"工单系统性原因研判"页改名;逻辑仍是原生脚本 `src/views/gov-risk/gov-risk-app.mjs` |
| 政策大盘 / 政策解读 / 政策知识库 / 政策图谱 / 政策月刊 | `#/dashboard/policy` 等 | 从公共事务 `services/heng-guan/frontend/src` 复制的个人版本,目录结构与原版一致 |
| 政策数据源 / 源质量审核 | `#/policy/import`、`#/quality/l1-review` | 同上;后端按公共事务 MANAGER 权限校验 |

复制模块与公共事务**共用同一套后端和数据**(`/heng/api/v1/*`、`/policy-qa/*`):发布月刊、提交审核结论、
改采集规则都会改到公共事务里的同一份数据。复制模块里跳到没复制的页面(如政策分析 `/policy`)时,直接打开公共事务原版。

复制时只改了三处必须改的地方,其余与原版逐字一致(之后可以随意改成自己的版本):

- `src/api/client.ts`、`src/utils/geojson.ts`:前缀固定为 `/heng`(原版用 Vite base 拼);
- `src/views/monthly/MonthlyDetail.vue`:月刊 AI 对话地址改用 `apiBase`(原版写成 `/api/v1/...`,在平台上落到根路径)。

另有 `src/styles/portal.css`:把 `tokens.css` 里写在基础规则前面、实际不生效的移动端覆盖再放一次,窄屏不再横向溢出。

## 开发与构建

```bash
npm ci --prefix services/heng-guan/frontend          # 只需一次:构建复用公共事务前端已锁定的依赖
node portal/personal-workspaces/pending-gov-risk/build.mjs --typecheck   # vue-tsc + 构建,覆盖 assets/
node portal/personal-workspaces/pending-gov-risk/build.mjs --check       # 已提交的 assets/ 是否与源码一致
node --test portal/tests/gov-risk-workbench.test.cjs
```

- `index.html` 是手写的入口页,只引 `./assets/index.js` 和 `./assets/index.css`;产物文件名固定不带 hash
  (nginx 对个人目录整体 `no-store`),所以改源码后只需重新构建,把 `src/` 和 `assets/` 一起提交。
- 个人工作台登记会逐个校验目录里的 `.html`,目录里只保留 `index.html` 这一个页面,不要再放 HTML 模板。
- 平台顶栏由 `/platform-nav.js` 在正式/测试域名下补上,本地预览没有顶栏属正常。
- `src/` 里的 select 由公共事务的 `AppSelect` 组件或平台下拉接管;Vue 根节点里平台脚本不会自动接管原生 select,
  政诉预判里的下拉是 `gov-risk-app.mjs` 显式交给 `window.PlatformSelect` 的。
