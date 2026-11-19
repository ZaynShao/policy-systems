# WORKFLOW 工单系统性原因研判个人工作台 v1.0

## 需求与验收

目标用户:滴滴能源公共事务 / 风险管理员(政诉工单平台 boss 的风险管理员)。

场景:提前发现**反复制造投诉、但还没被重视的系统性原因**。两个真实案例:
- 用户投诉充电度数过高并引发舆情、监管施压,事后查明是厂家设备电路老化;
- 设备流水号重复,新用户被关联到老用户的充电数据,显示电量和金额偏高。

两类问题用户感受到的都是"电量过高",过去都在单条投诉层面"已解决"就结束了。
历史数据佐证(2026-05-14 起 546 条政诉工单):度数/电量偏高 25 条,6–9 月每月 5–7 条,
全部"问题已解决",平台定级 24 条是 L5,正文零条提到设备或厂家。

风险口径:监管处罚、媒体曝光、消费者诉讼/索赔都算"进一步风险"。

验收:
- 工作台按"该提前处理的程度"列出系统性原因候选(现象级、同一场站/运营商级),
  显示按月出现情况、关单后是否仍出现、可能机理分布、鉴别线索、核查建议、与已知案例的相似;
- 每个候选可下钻到这类工单的脱敏原文和逐条研判("这类型下的工单有哪些");
- 所有者可在页面标注跟进状态(新发现 → 核查中 → 根因确认 → 整改中 → 已修复 → 观察期 → 关闭 / 误报),
  标成已修复后同类再出现,下次研判标"修复后复发";
- 公网不出现个人信息、真实工单号、地址/场站名、具体科室;回查原单靠本机映射表。

明确不做:平台侧不存原始工单;不改 KB 账号模块、不改个人工作台访问校验。

## 分工调整(2026-10-15)

用户决定本地与公网比重对调:**本地只做取数、脱敏和简单清洗;研判在平台上跑**。
平台因此存脱敏后的逐条工单(此前只存聚合结论包),页面可以下钻到脱敏原文。
细则:地址/场站名是能定位到投诉人的准标识,本地换成 `ST-` 编码,不上传;运营商是公司层面信息,
由平台模型从正文里识别后直接显示名称。

## 数据边界与链路

```
内网 Mac 本地服务(私有仓库 gov-ticket-risk,Python 标准库)
  取数(boss etron 只读接口,用户本人登录态)→ 解析模板 → 简单清洗(去重、合并空白、截断)
  → 脱敏(个人信息正则 + 全量人名/地址/科室词表 + 场站/路号样式)→ 字段白名单组装
  → 出本机复查(个人信息正则 + 全量禁用词,有残留整批不传)→ 分批上传(约 1MB/批,完整快照)
        │ x-gov-risk-agent-token
        ▼
nginx  location ^~ /guardian/api/internal/gov-risk/(auth_request off,刻意例外)
  → guardian 前端(server.js 路由 + 只在该前缀透传 token 头)
  → guardian-backend /api/internal/gov-risk/{cases,run,package}
        入库前再扫个人信息(命中整批 422)→ 收齐后排队研判(进程内单线程队列)
        研判:逐条标注(平台模型通道,按提示词版本+正文缓存)→ 归并打分 → 高分候选复核 → 结果包
                      /api/gov-risk/{package,run,runs,cases,feedback}(平台登录 + 所有者校验)
        ▲
个人工作台页面 portal/personal-workspaces/pending-gov-risk/(读结果、下钻、写跟进、手动重跑)
```

上传字段白名单(`gov-risk-cases/v1`):`case_id`(GT-,本地密钥 HMAC 短码)、`channel`(政诉/普通客诉/舆情)、
`created_at`/`closed_at`、`status`、`resolution`、`platform_risk`、`template_risk`、`business_line`、
`dept_type`(部门类型,不含具体科室)、`city`、`problem_path`、`station_code`(ST-)、`user_key`(U-,
只用于识别重复投诉人,页面不显示)、`text.{description,demand,issue,remark}`(脱敏正文)。

- 模型通道:复用 `llm-client` 的 `LLM_*`→`DEEPSEEK_*`;凭证无效或欠费立即熔断,其余错误连续 3 批熔断;
  没标到的工单按规则兜底,结果包 `method` 如实写明条数和熔断原因。每次最多新标 1200 条(最新优先)。
- 日志只记条数、耗时、模型名和失败原因码,不记工单正文和模型回答。
- 上传是完整快照:最后一批带 `final.case_count`,平台核对收齐才删掉不在快照里的旧工单并开始研判;
  中途断掉的上传不当快照。本地在条数不到平台现有一半时默认拒绝上传。
- 撤回:`DELETE /api/internal/gov-risk/cases {"confirm":"delete-all"}` 删工单、数据集、结果包和运行记录,
  保留所有者的跟进记录(本地 `python3 -m gtr forget-remote`)。

## 平台改动

| 模块 | 文件 | 改动 |
|---|---|---|
| guardian-backend | `src/gov-risk/gov-risk.vocab.ts` | 现象/机理/鉴别线索词表与规则兜底(从本地服务移植) |
| guardian-backend | `src/gov-risk/gov-risk.engine.ts` | 研判引擎纯函数:逐条标注的提示词与校验、归并打分、复发与观察期、候选复核、结果包 |
| guardian-backend | `src/gov-risk/gov-risk.analysis.ts` | 一次研判运行:缓存、并发 3、单次额度、熔断、规则兜底 |
| guardian-backend | `src/gov-risk/gov-risk.validate.ts` | 上传批次字段白名单、映射编号格式、个人信息扫描(不回显内容)、跟进记录校验 |
| guardian-backend | `src/gov-risk/gov-risk.service.ts`、`controller.ts`、`module.ts`、`src/app.module.ts` | 上传/快照、研判队列(启动时把未跑完的标中断)、结果、下钻、跟进(revision 乐观锁)、撤回;限流:上传 240 次/小时、研判 12 次/小时 |
| guardian-backend | `src/common/guards/jwt-auth.guard.ts` | internalTokenRules 增加 `/api/internal/gov-risk/` → `x-gov-risk-agent-token` → `GOV_RISK_AGENT_TOKEN`;未配置或弱口令按永不匹配处理 |
| guardian-backend | `prisma/schema.prisma`、`prisma/migrations/20261015180000_gov_risk_workbench` | 新表 `gov_risk_cases`、`gov_risk_datasets`、`gov_risk_runs`、`gov_risk_packages`、`gov_risk_feedback`,不改已有表 |
| guardian | `server.js` | 两个前缀转给后端;token 头只在 `/api/internal/gov-risk/` 下透传 |
| infra | `nginx/default.conf`、`nginx/intel-shell-routes.test.cjs` | 内部前缀的刻意例外(4m 请求体);契约测试登记并钉住边界,页面接口不得开例外 |
| infra | `docker-compose.yml` | guardian-backend 增加 `GOV_RISK_OWNER_USERNAME`、`GOV_RISK_AGENT_TOKEN`、`GOV_RISK_LLM_TIMEOUT_MS` |
| infra | `.github/workflows/p0-gates.yml` | 登记 `test/gov-risk.spec.ts`、guardian 传输层测试、页面测试 |
| portal | `personal-workspaces/pending-gov-risk/*`、`tests/gov-risk-workbench.test.cjs` | 新页面(待绑定占位目录,`owner_account: PENDING_ACCOUNT`) |

升级 SQL:见迁移文件。回滚 SQL:
`DROP TABLE "gov_risk_feedback"; DROP TABLE "gov_risk_packages"; DROP TABLE "gov_risk_runs"; DROP TABLE "gov_risk_datasets"; DROP TABLE "gov_risk_cases";`

配置缺省行为:`GOV_RISK_OWNER_USERNAME` 为空 → 页面与上传接口 503 `owner_not_configured`;
`GOV_RISK_AGENT_TOKEN` 为空或弱口令 → 内部接口 401;模型密钥未配置 → 研判全部规则兜底并标明;都不影响其他模块。

上线配置:所有者登录名 `shaoziyuan`(2026-10-15 用户确认)→ `GOV_RISK_OWNER_USERNAME=shaoziyuan`;
`register_personal_workbench.py` 把该账号绑定到本目录。个人工作台每个账号只绑定一个入口,该账号若已绑定其他页面,
绑定会替换原入口,维护人先 dry-run 看 `before` 再 `--apply`。
建表:guardian-backend 容器启动时执行 `prisma db push`(不带 `--accept-data-loss`),五张新表只新增,重建容器即建好;
迁移文件用于从空库重建和 CI 的 drift 检查。

## 接口契约

本地服务(agent token):
- `PUT /api/internal/gov-risk/cases` `{schema:"gov-risk-cases/v1", upload_id, chunk:{index,total}, cases[≤500], final?}`
  → `{stored, final:false}`;最后一批 → `{stored, final:true, total, removed, uploadedAt, run, runSkipped}`。
  422 `gov_risk_case_contains_pii`(只回映射编号、路径和类型);409 `gov_risk_upload_incomplete`;429 限流。
- `DELETE /api/internal/gov-risk/cases` `{confirm:"delete-all"}` → `{deleted, cases, packages}`;研判进行中 409。
- `GET /api/internal/gov-risk/run` → `{run, dataset}`;`GET /api/internal/gov-risk/package` → 同页面版。

所有者(平台登录;非所有者 403 `not_owner`,未登录 401):
- `GET /api/gov-risk/package` → `{package, generatedAt, history[≤10], run, dataset}`;`package.schema = gov-risk/v2`。
- `GET /api/gov-risk/run` → `{run:{id,trigger,status,progress,stats,error,...}, dataset}`;页面研判中每 4 秒轮询。
- `POST /api/gov-risk/runs` → 202 `{run, queued}`;没有数据 409 `no_dataset`。
- `GET /api/gov-risk/cases?ids=GT-…,GT-…`(≤50)→ `{cases:[脱敏记录 + 逐条研判]}`,不含 `user_key`。
- `GET|PUT /api/gov-risk/feedback` → `{revision, data:{candidates:{SC-xxxxxx:{status,note,updated_at}}}, updatedAt}`;旧 revision → 409。

## 三轮自检

1. 用户原意:本地脱敏和简单清洗后在公网研判(2026-10-15 调整);按"现象先行、多渠道合看、已解决不等于消失"设计;
   模型走平台 API key;公网不落个人信息,回查原单靠本机映射表。
2. 产品事实:个人工作台访问校验在 KB 模块,改它是跨模块;页面接口走平台登录 + 后端所有者校验,
   只有本地服务的内部前缀开 nginx 例外,做法与倚天 Mac Agent 一致。
3. 交付可行:迁移只新增表;配置缺省时功能明确不可用而非假就绪;研判异步、可重跑、可中断恢复;
   模型欠费时退回规则并如实标注;上传快照有完整性核对和缩水保护。

## 验证与进度(2026-10-15)

已完成并本地通过:
- `npx ts-node test/gov-risk.spec.ts`:引擎小件、上传校验与个人信息拒收(不回显)、所有者 503/403/401、
  分批上传与快照删除、断掉的上传不当快照、合成数据完整研判(候选、对象级、复核、对标案例)、下钻、
  乐观锁、手动重跑复用缓存、修复后复发置顶、欠费熔断、未配置模型、撤回、token 校验;
- `npm run build`、`npx tsc --noEmit -p tsconfig.spec.json`、`npx ts-node test/nest-runtime.smoke.ts`;
- `node --test services/guardian/test_gov_risk_transport.test.js`、`bash scripts/check-nginx-contracts.sh`、
  `node --test portal/tests/gov-risk-workbench.test.cjs`;
- 本地服务 `/usr/bin/python3 -m unittest tests.test_pipeline` 17 项(Python 3.9 与 3.10,合成数据);
- 端到端实测:用仓库里的 GovRiskService(内存存储 + 假模型)起模拟平台,本地服务对 40 条合成工单
  `prepare → upload --wait → report → lookup → forget-remote → 重新上传`,页面在桌面与 375px 宽检查了
  候选卡、筛选、下钻、保存跟进、409 冲突横幅、手动重跑与自动刷新、未保存跟进时不自动替换、空状态,控制台无报错;
- `bash scripts/pr-preflight.sh` 通过(已变基到最新 master);本机临时 Postgres 15 上迁移链从空库重建无漂移,
  CI「Guardian backend spec suites」28 条全过,真实 `PrismaGovRiskStore` 跑通上传→研判→重跑→快照删除→撤回;
- 本地服务已推到私有仓库 `ZaynShao/gov-ticket-risk`。

截图佐证在 `docs/evidence/gov-risk-workbench/`(合成数据、模拟平台:仓库里的 GovRiskService + 内存存储 + 假模型,不是生产):
`desktop-overview.jpg`、`desktop-drilldown.jpg`、`desktop-conflict.jpg`、`mobile-overview.jpg`、`mobile-drilldown.jpg`。

未完成(断点续做按顺序):
1. PR(`[CROSS-MODULE][DB-MIGRATION]`,分支 `feature/guardian-gov-risk-workbench`)的 P0 Gates 跑到全绿,最多自修 3 轮。
2. 真实数据:用户 `python3 -m gtr login`(复制 cURL)→ `fetch` → `prepare`,核对 `outgoing.json` 的脱敏效果。
3. 上线(维护人):合并后 `deploy-manual.yml`;生产 `.env` 配 `GOV_RISK_OWNER_USERNAME=shaoziyuan`、
   `GOV_RISK_AGENT_TOKEN`(`openssl rand -hex 32`),重建 guardian-backend;`register_personal_workbench.py` 登记目录;
   确认共享 DeepSeek 通道余额(2026-09-09 曾 402)。然后本地 `gtr token` → `upload --wait`。

待确认:正式目录名(绑定后把 `pending-gov-risk` 换成绑定标识);千帆普通客诉的数据入口;舆情来源。

## 剩余风险

- 地址/场站名按地址字段和样式识别,是尽力而为:正文里写法特殊的场站名可能漏遮,样式匹配也会多遮几个字;
- 模型通道是共享 DeepSeek 账户,欠费时研判退回规则兜底(结果包 method 里如实标注);
- 机理是根据投诉文本推断的待核查假设,页面方法说明已写明,最终以订单、设备数据核查为准;
- 研判队列在进程内,guardian-backend 重启会中断正在跑的研判(启动时标成中断,页面可重跑);
- 脱敏工单存在公网服务器上,这是 2026-10-15 的分工决定;撤回命令可一次删除。
