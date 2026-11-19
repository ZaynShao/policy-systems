# WORKFLOW-policy-predict-industry-board-v1.0

## 1. 需求澄清

- 目标用户：政策预判模块的公共事务、合规、战略研究用户。
- 使用场景：在 `policy-predict.html` 左侧导航新增「行业预判板」页签，按行业陈列 19 个行业的监管走向预判（真实政策数据版，证据冻结 T0 = 2026-09-14），点开看预测卡、证据链、推理过程与加工过程。
- 范围：只做前端接入。板子本身是 policy pipeline 仓 `state/行业预判板/` 产出的静态页面（`index.html` + `data.js`），本仓只放生成物与挂载点。
- 明确不做：不接预测服务 API、不新增后端接口、不改权限体系（沿用 `policy_predict.view`）、不改其它视图、不重做视觉。
- 验收标准：
  - 侧栏主菜单在「政策预测」之后出现「行业预判板」；`#view=industryBoard` 可深链；默认落地仍是机构档案。
  - 视图内以同源 iframe 加载 `./industry-board/index.html`，首次进入视图才加载（900 KB 数据不拖慢其它视图），高度跟随内容、不出现双滚动条。
  - 板子在 iframe 内隐藏自带的平台页签条，只保留内容；「在新窗口打开」可单独浏览。
  - 板子 19 个行业数据过契约校验（`validate.py`），页面无 mock/比喻用词残留。

## 2. 工作流与设计

- 设计读法：沿用 mock 版式与 heng 平台白橙 tokens，不引入新配色；iframe 边框与圆角对齐 `.panel`。
- 前端结构：
  - `portal/policy-predict.html`：侧栏按钮 `data-view="industryBoard"`、`#industryBoardModule` 区块（head + iframe + 兜底文案）、`switchModule` 白名单加 `industryBoard`、`mountIndustryBoard()` 首次进入时把 `data-src` 写入 `src`，`syncIndustryBoardHeight()` 用同源 `contentDocument.scrollHeight` + MutationObserver 跟随高度。
  - `portal/industry-board/index.html`、`data.js`、`README.md`：生成物。由 policy pipeline 仓 `state/行业预判板/tools/export_portal.py` 导出（先跑 `build_data.py` → `validate.py` 19/19 过再打包；`data.js` 带 `?v=<打包时间>` 绕过 5 分钟静态缓存）。页面检测 `window.self !== window.top` 时加 `embedded` 类隐藏平台页签条。
- 为什么用 iframe 而不是并入页面：`policy-predict.html` 已 440 KB，板子有 `.kpi/.tag/.pill/.tile` 等通用类名，并入要全量改名；iframe 同源、零样式冲突、板子与 Artifact 版保持同一份文件。
- nginx：`location /` 直接服务 `portal/`，子目录静态文件走 `try_files`；portal 根不做顶栏 sub_filter，iframe 内不会再注入一套顶栏；`X-Frame-Options SAMEORIGIN` 允许同源嵌入；`auth_request` 对 iframe 请求同样生效（同源带 cookie）。
- 同步/部署计划：生产 compose 把 `./portal` 只读挂进 nginx 容器，合并后服务器 `git pull` 即生效，不需要重建镜像。未收到远端发布要求，不执行远端部署。
- 风险：
  - 数据刷新靠人工重新导出并提交；`README.md` 写明命令。
  - 板子里的概率为分析师主观概率、未校准；18/19 行业没有历史判定，页面按空态显示。

## 3. 自检

- 对照用户原话：「在左侧 tab 页下新增 tab 页」——新增的是侧栏页签而非顶栏模块；放在主菜单「政策预测」之后。
- 对照真实产品形态：单文件 portal 页面，最小改动是加一个视图 + 一个静态子目录。
- 对照交付可行性：不引入新依赖、不改权限、`tests/test_policy_predict_industry_board.py` 与 `portal/tests/module-default-landing.test.cjs` 覆盖侧栏顺序、白名单、iframe 懒加载、生成物完整性。

## 4. 当前状态

- 2026-09-15：首版接入。板子数据 T0 = 2026-09-14，19 行业 410 节点、51 张预测卡、已判定卡 1 张（电力）。
- 2026-09-15：口径调整（D8 双轴）。用户反馈自动驾驶/电力/出海是国家支持的产业却显示"收紧风险"；根因是温度量的是规则与执法密度，不是产业方向。改为两轴：色条与标签是「产业方向」（支持/中性/限制，分析师依据国家级方向性文件判定并回链，当前为草拟待确认），温度改称「监管强度」（趋严/放宽/并行/平稳）。同时按现口径复核了自动驾驶强标线、电力国办 4 号、出海对外投资线的推力，电力范围放宽为"电力市场"。生成物重新导出（v=202609150115）。
