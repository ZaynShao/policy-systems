# WORKFLOW — 政策月刊 agent 产线 v1.0

> 编号命名空间:本文用 `MA0–MA9`(Monthly Agent 步骤)与 `PM1–PM4`(交付批次)。
> 两个前缀在 safety-platform 与 policy-pipeline 内均未被占用;每次出现就地展开含义。
> **不要**与 `business_strategy.yaml` 的信号编号(`F01-F07` 加油 / `C01-C14` 充电 / `P01-P15` 电力 / `X01-X03` 跨业务)混用。

## 0. 需求原话

> "目前 https://xiaojunengyuan.com/heng/monthlies 是早期产物,整体界面风格可以,但是里面产出的月刊是完全达不到要求的,因此要用月刊的 skill 的方式去做,月刊 skill 有个缺陷是业务需求是不准的,因此业务需求要参考已经掌握的公司战略相关的文档"

用户后续澄清(逐项确认):

- **每月 2 号自动出成稿**,前端只做展示;不设发布前的人工闸。
- 用平台现有 DeepSeek key 跑 **v4pro**;**v4pro 的出稿质量评估是本任务的一环**。
- **出稿不能是一次性提示词的暴力来回**,要按 agent 分步组装完成,步骤由实施方设计。
- 审计门(F/D)不过时:**自动返修;返修仍不过也照常发布**,但页面挂容错提示(说明因 AI 出稿某部分可能不够符合要求),并提供**修改意见栏**,人工意见整合后再过一轮。
- 取政策**除库内全量外,要再跑一轮 web search 做双保险**。

## 1. 背景与现状核实(origin/master `7fba9e6d`,2026-09-07 逐条读码核实)

### 1.1 现有 `/heng/monthlies` 的产线

`services/heng-guan/backend/src/monthly/monthly.service.ts` + `src/ai/prompts/monthly.ts`。核实结论:**问题不在提示词写得好不好,而在整条产线缺了月刊方法里最要命的三步**。

| # | 现状 | 后果 |
|---|---|---|
| 1 | 选目 = `KnowledgeEntry` 按 `importance` 取前 18(兜底 `Policy` 前 12),`monthly.service.ts:126-142` | 机器评分当选目。方法正本明确记载评分失准(2026-06 旗舰件 884 曾被打 2 分) |
| 2 | 喂给模型的只有标题/发文机关/`aiKeyPoints` JSON **截断 600 字符**,`prompts/monthly.ts:31` | **完全不喂 RAW 正文**。正文里每个数字、每条引文都无原文可回指,F 门在结构上无法执行,幻觉是必然而非偶然 |
| 3 | 业务口径写死在提示词:「公司主营:充电桩、储能、虚拟电厂、综合能源服务、网约车出行」,`prompts/monthly.ts` | 与战略正本冲突:业务线只有**加油/充电/电力**三条;**储能处于 hold**;虚拟电厂是电力线"供应链"项下抓手、非并列版块;"网约车出行"不是业务线。**这就是用户说的"业务需求不准"** |
| 4 | 输出 JSON 强制 `**加粗**`、`『』`、`tipBoxes`(启示 01/风险 01) | 这三样都在月刊 D 门硬禁清单上 |
| 5 | 一次 LLM 直出即入库 | 无 F 门(逐数字回指 RAW)、无 D 门(风格)、无返修 |

### 1.2 运行环境(SSH 只读核实)

**生产平台就跑在东京 VPS(`8.216.59.173`)上,vault 已在手边**——这是本设计成立的前提:

- `platform-heng-backend` 挂载含 `/root/policy-vault → /vault-mirror:ro`。
- `policy-pipeline` 容器(`/root/policy-pipeline-src/docker-compose.server.yml`)挂 `/root/policy-vault:/vault:ro` + `/root/policy-pipeline-state:/state`。
- `analysis_context.jsonl` 每日 03:30 重算(2026-09-07 03:30 已跑,551 KB)。
- **装包所需四样料(RAW / business_view / relations / analysis_context)只有 pipeline 容器四样齐全**;heng-backend 没挂 `/state`。
- vault 现况:政策 1653 篇、评论 3999 篇、business_view 1574 份。frontmatter date 分布 `2026-06` 196 / `2026-07` 132 / `2026-08` 114。
- **生产 `platform-heng-backend` 当前 `DEEPSEEK_MODEL=deepseek-chat`,不是 v4pro**(`.env.example:9` 写的是 `deepseek-v4-pro`,生产未采用)。

### 1.3 已有可复用零件

| 零件 | 位置 | 用途 |
|---|---|---|
| `strategy_profile.py` | `services/policy-pipeline/scripts/common/` | 战略画像加载器:`schema_version` 白名单 + `status: active` 校验 + `check_impact_keys()` 对账 + `render_for_impact_analysis()` 渲染。**配了却读不出来直接抛异常,不静默降级**。L2 themescore 与 policy-qa 已在用,月刊只是没接 |
| `business_strategy.yaml` | vault `_meta/framework/`(`profile_id: 2026-energy-strategy`,`effective_from: 2026-08-31`) | 战略正本:三业务线 + `decision_variables` + `relevance_rules` + 43 条信号 + `open_questions` |
| `build_month_pack.py` / `pack_lib.py` / `render_docx_clone.py` | 旧仓 `scripts/l3_render/`(412 行,**只在本机 main,未推任何远端**) | 装包与公文 docx 渲染 |
| `Monthly` / `MonthlyVersion` / `MonthlyPolicy` / `ChatSession` | heng `prisma/schema.prisma:1496` 起 | 月刊存储与版本;`version` 字段与版本表现成,正好承载"人工意见回炉出新版" |
| S2 cron 范式 | `services/policy-pipeline/docs/runbooks/s2-vps-cron.md` | `flock` 串行化 + `docker compose run --rm` + 失败告警;10:00 那条"pipeline 容器写 heng-pg"与本设计的投影同构 |

### 1.4 取政策覆盖面核实(含 web 双保险实测)

**库内**:MA0 直接读 `0_raw/policies/*.md` 全量 1653 篇,库内是全覆盖的。

**web 双保险实测(2026-09-07,针对 2026-07/08)**——一轮就捞出两条真实漏采:

| web 查到的国家级文件 | 库内 |
|---|---|
| 新型能源体系"十五五"规划(发改能源〔2026〕884号)/ 新型电力系统(942号)/ 煤炭工业(979号)/ 石油天然气(1055号)/ 可再生能源(1067号)/ 国务院"十五五"碳达峰行动方案 | 全在 |
| 42 号令《可再生能源消费最低比重目标和可再生能源电力消纳责任权重制度实施办法》 | 在 |
| **《电力安全生产"十五五"行动计划》(2026-08-07,国家能源局)** | **缺** |
| **成品油"交易即开票"(国家税务总局 2026 年第 11 号公告,2026-11-01 全国加油站全覆盖)** | **缺**(`grep 交易即开票` 零命中;库内同名检索出来的全是商务局零售许可/年检类) |

第二条正是方法正本点名的**跨条线机关(税务、金融)系统性漏采**,且直接命中加油线两条 high 信号——`F02`(消费税稽查、发票与票据管理)与 `F05`(预付卡/加油卡/电子券/第三方支付监管),改的是商户合规成本与卡券载体,属决策变量级别。**这条实测结果本身就是 MA1b 必须进自动链路的证据。**

**另一处实测发现**:库内存在同一文件的多份副本(942 号有 3 个文件名变体、884 号有 2 个、42 号令有 2 个)。不去重会让选目重复计数与配额失真,故 MA1 必须含去重。

## 2. 目标

把 `/heng/monthlies` 的月刊产出,从「一次 LLM 直出」换成「**每步产物结构化、可机器校验、可单独重跑的 agent 分步产线**」,并让业务口径从**战略正本**加载而非写死在提示词里。前端视觉风格不动。

## 3. targetModule / allowedPaths 声明

```yaml
baseRef: origin/master
baseSha: 7fba9e6d592af4c0d3b8b74389b2fb9b1eac9e8e   # fetch 后记录 (origin/master, 2026-09-07)
targetModule: policy-pipeline (PM1/PM2/PM3) + heng (PM3 投影 / PM4 前端) + infra (PM1 一行 CI)
crossModule: true                                   # PM3 / PM4 写 heng,PR 须加 [CROSS-MODULE]
allowedPaths:
  # PM1 L3 迁入
  - services/policy-pipeline/scripts/l3_render/**
  - services/policy-pipeline/tests/l3_render/**
  - services/policy-pipeline/SCHEMA.md
  # PM2/PM3 agent 产线
  - services/policy-pipeline/scripts/l3_monthly/**
  # MA1b 搜索腿:给既有 Tavily 客户端加一个返回标题的方法(纯新增,向后兼容)
  - services/policy-pipeline/scripts/l1_collect/tavily_client.py
  - services/policy-pipeline/tests/l1_collect/test_tavily_client.py
  # MA2 业务口径:与既有 render_for_impact_analysis() 并列新增月刊版渲染(纯新增)
  - services/policy-pipeline/scripts/common/strategy_profile.py
  - services/policy-pipeline/tests/common/test_strategy_profile.py
  - services/policy-pipeline/tests/l3_monthly/**
  - services/policy-pipeline/docs/runbooks/policy-monthly-*.md
  - services/policy-pipeline/OPERATIONS.md
  # PM4 前端与库
  - services/heng-guan/backend/src/monthly/**
  - services/heng-guan/frontend/src/views/monthly/**
  - services/heng-guan/frontend/src/api/monthly.ts
  # PM4 实施时追加(2026-09-07):前端测试与 API 契约
  - services/heng-guan/frontend/test/monthly-*.test.mjs
  - contracts/heng-backend.openapi.json
  # CI(infra 模块,故 PM1 也须 [CROSS-MODULE])
  - .github/workflows/p0-gates.yml
  # 文档
  - docs/WORKFLOW-policy-monthly-agent-v1.0.md
forbiddenModules: [portal, guardian, kb, intel, report-system]
```

**不改**:`docker-compose.yml`(infra 模块)、全局 `DEEPSEEK_MODEL`、`services/heng-guan/backend/src/ai/deepseek.service.ts`、`0_raw/policies`(永不修改)。

> **越界检查**:两份报告中心 WORKFLOW 引用的 `audit_sop.py` 在 `/Users/didi/.claude/skills/safety-platform-guardrails/`,本机不存在。改用
> `git diff --name-only origin/master..HEAD` 逐条比对上面的 allowedPaths。

## 4. 范围与排除

### 4.1 范围
- L3 产线迁入 monorepo(装包 + 公文 docx 渲染 + 单测)。
- 新建 `scripts/l3_monthly/`:MA0–MA9 全链路。
- VPS cron 每月 2 号自动跑,产出投影进 heng-pg。
- heng 前端:新 content schema 渲染 + 容错提示条 + 修改意见栏。
- v4pro 出稿质量评估(2026-06 对标 + 07/08 实跑)。

### 4.2 排除
- **不改全局 `DEEPSEEK_MODEL`**:月刊链路自带 `--writer-model`,与现有 `--judge-model deepseek-v4-flash` 同范式。改全局会连带影响客户画像等其它 AI 功能。
- **不迁移存量旧月刊数据**:老 schema(`overview/quickList/policyBlocks/tipBoxes/summary`)的记录原样保留,靠 `content.schema` 版本字段分流渲染。
- **不动 `MONTHLY_CHAT_SYSTEM` 那条老 chat 链路的既有行为**:它让 LLM 直接改 JSON 字段(`target=policyBlock:02.focus`)、无 RAW 锚点。新的修改意见栏走 MA9,与它并存但不复用其提示词;老链路是否下线另作任务。
- 不接 L1 采集器的渠道扩容(MA1b 的缺口补采只调用既有采集入口,不新增渠道发现逻辑)。
- 不动生产 cron/`.env`/部署——出 handoff 由 operator 亲手执行。

## 5. 架构与运行位置

```
VPS cron (每月 2 号 04:00, flock 串行)
  └─ docker compose run --rm policy-pipeline
       python -m scripts.l3_monthly.run --month YYYY-MM \
              --vault /vault --state /state \
              --writer-model deepseek-v4-pro
          MA0 取窗 → MA1 粗筛去重 → MA1b web 双保险
          → MA2 逐篇判定 → MA3 选目 → MA4 装包
          → MA5 分块写作 → MA6 三路审计 → MA7 返修(≤2 轮)
          → MA8 组稿 + docx + 投影 heng-pg
                                    │
                        heng-pg Monthly/MonthlyVersion
                                    │
                    heng 前端 /monthlies 只读展示
                    (容错提示条 + 修改意见栏 → MA9 回炉)
```

**为什么跑在 pipeline 容器而不是 heng 后端**:① 装包要的四样料只有它四样齐全(heng 没挂 `/state`);② 装包与公文渲染已是 Python,搬进 NestJS 等于把 412 行重译成 TS;③ 与现有 10:00 投影 cron 同构,运维心智一致。

## 6. agent 分步 MA0–MA9(核心)

设计原则:**LLM 只出现在真需要判断的地方,机械活全部确定性代码**。每步产物落 `state/monthly_<YYYY-MM>/`(gitignored),可单独重跑。

| 步 | 执行者 | 输入 → 输出 | 设计理由 |
|---|---|---|---|
| **MA0 取窗 + 新鲜度闸** | 代码 | 月份 M → `candidates.jsonl` | frontmatter date 网撒 **[M-1, M+1]**(方法正本硬规则,对冲 date 字段常是生效/发布日的偏移)。闸:vault git HEAD、`analysis_context` 当日是否重算、business_view 覆盖率;不新鲜则告警并中止,**不静默降级** |
| **MA1 粗筛 + 去重 + 系列标记** | 代码 | → `shortlist.jsonl` | ① `pack_lib.is_noise()` 过噪声;② **去重**:文号相同**且标题核心相容**才硬合并(留 RAW 最长的一份),否则打 `docno_conflict`;文种相同且核心标题相等或互相包含 → 软标 `near_dup_group`,一份不丢;同 id 挂不同文件 → `id_collision`;③ **周期性系列标记**:抹掉数字与日期字样后同键且 ≥3 篇 → `series_group`(实测各期 13–15% 的 shortlist 是成品油调价这类系列),只标不删;④ business_view/analysis_context 只做**召回**不做排序定论 |
| **MA1b web 双保险** | 代码 + 搜索 | → `gap_report.json` | **两条腿,PM2-b 只实现腿 2**(理由见 §6.1)。腿 2(搜索,默认开):按战略画像里 `weight: high` 的信号 `what` 字段 + 月份构造查询,复用仓内既有 `l1_collect/tavily_client.py`(`_post` 可注入、无 key 时返回空,天然降级),搜到的条目按文号精确 + 核心标题相容与 vault 对账。腿 1(定向抓权威来源列表页):**不在 L3 实现**——见 §6.1 |
| **MA2 逐篇归属判定** | LLM×N,并发 | 每篇 RAW 头部(落款+文号+标题+正文前 N 字)+ 业务口径段 → `{level, issue_date_from_body, business_hits, decision_variables_touched, relevance, why, dq}` | **修"业务需求不准"就在这里**:口径由 `strategy_profile.render_*()` 从 `business_strategy.yaml` 渲染,不写死。短上下文、可并发、可重试、错一篇不毁全局 |
| **MA3 选目定调** | LLM×1 | MA2 的结构化结果(**不喂 RAW**)→ `slate.json` | 取代"按 importance 取前 18"。schema 沿用方法正本:`{month, narrative, sections:{national_detail[], local_detail[], roundup[], appendix[]}}`,每条 `{policy_id, title_hint, score, rank, why, dq}` |
| **MA4 装包** | 代码 | `build_month_pack.py --slate` → `pack/` + `INDEX.json` | 每政策一个 bundle:RAW(截断 9000 字符)+ business_view + analysis_context + 关系边 + 评论校准。**这是 F 门能成立的物理前提** |
| **MA5 分块写作** | LLM×~20 | 每块只喂**它自己那一个 bundle** | 见 §6.3 |
| **MA6 三路审计** | 2 路代码 + 1 路 LLM | → `audit.json`(每条 `{gate, severity, location, quote, expected}`) | 见 §6.4 |
| **MA7 返修** | LLM,只重写被点名段 | 段落原文 + 该段 bundle + 审计条目 → 新段落 | ≤2 轮,每轮后重跑 MA6。仍有残留 → 写进 `content.caveats`,**照常发布**(不扣住) |
| **MA8 组稿交付** | 代码 | `final.md` → `render_docx_clone.py` → docx;投影 heng-pg | 写 `state/last_run.json` |
| **MA9 人工意见回炉** | LLM | 页面修改意见 → 走 MA7 同一条链 → `version+1` | **人工意见也要过 F 门**:不能因为人说了就写进没有 RAW 支撑的话 |

### 6.1 MA1b 为什么只做搜索腿

原设计的腿 1 是"定向抓权威来源(发改委/能源局/税务总局)的当月公告列表页,与 vault 对账"。实现时核实:
`l1_collect/step2_scan._extract_list_items` 已经是通用的列表页抽取器,但它绑定 `Channel`
(city / province / city_code 三个区划字段),对"国家税务总局"这种非地理来源不合身;跨包导入
另一个包的私有函数也不干净。而若另写一个,就是**在 L3 里重造一遍 L1 的渠道机器**。

结论:**跨条线系统性漏采的根治在 L1 渠道注册表,不在 L3**。把国家税务总局这类非能源口来源
加进 L1 的 `channel_registry`,漏采就在源头堵住了,而不是每月出刊时补一遍。该项另开任务。

MA1b 因此只保留搜索腿——它已经足够抓住实测到的那条缺口(税务总局「交易即开票」公告)。
`gap_sources.yaml` 里保留 `directory_sources` 配置段作为扩展点,当前为空,读到非空时才走腿 1。

### 6.2 MA1b 的缺口处置(守"web 不进正文"铁律)

`gap_report.json` 每条:`{title, doc_no, issuer, url, in_vault: bool, matched_pid, signal_id}`。缺口两条出路:

1. **有官方 URL 且域名在 L1 采集白名单** → 调既有采集入口即时入库 → 拿到 RAW 后正常进 MA2,**可进正文**。
2. **抓不到 RAW** → **只进文末"已知未覆盖"脚注**,一句话点名,**不进正文**。

方法正本铁律:**web 只作 QA,其正文内容不得进稿**。腿 2 搜索结果永远只是"去哪里找",不是事实源。

### 6.3 MA5 分块写作的拆解(为什么不是一次成文)

- `MA5a` **每篇详情块** — 输入一个 bundle,输出【政策信息】【政策解读】【重点关注内容】【决策建议】四段;决策建议**只列 MA2 算出的 `business_hits`**,不写"X 业务无关"。
- `MA5b` **省级综述** — 输入 `local_detail` + `roundup` 的 bundle 摘要,出一段综述;**省级走综述,不与国家级并列**。
- `MA5c` **附录** — 国家级讲话/会议类信号。
- `MA5d` **速览表** — **纯代码拼**,**不过 LLM**(表格是最容易被编造的地方)。
  字段来源钉死:`issuer` / `docNo` / `date` 一律从 **RAW 正文的落款与文号**抽取(复用并扩展 `pack_lib.body_date_hints()`),
  **禁止回退 frontmatter**——frontmatter 的 `date` 常是生效/发布日、`region_name` 常是采集省份、`official_number` 可能抓到被废止件的号。
  抽不到就留空并记一条 `caveats`,**不许猜**。
- `MA5e` **概述 + 三大业务速判** — **最后写**,输入是已写完的各块(详情 + 省级综述 + 附录)而非 RAW,
  概述因此必然与正文一致。
  **业务速判的依据范围不能只算详情**:各期 shortlist 有 13–15% 是成品油调价这类周期性系列,
  它们按编辑口径进速览而不进详情,而它们恰恰全是加油线。只认详情的话,一个满是加油政策的月份
  会出一份「本月加油线没事」的月刊。故 `write_overview` 另收 `extra_hits`(速览/附录条目的
  `business_hits`),并对**反向漏报**(正文写了、速判没提)同样记 caveat。

上期终稿只作**版式样例**喂入,提示词内明令**只学版式、不抄内容点**(历史教训:退役原型"乡村能源"内容点曾被抄进新刊)。

### 6.4 MA6 三路审计的分工

| 门 | 执行者 | 判什么 |
|---|---|---|
| **D 门(风格)** | **纯正则,不花 LLM 钱** | 机器 token(`P_2026_*`、`*_theme`、`D1-D6`、rel-id、模型名)、`⭐`、`「」`、正文 `**`、机器承接关系表、过程性元信息(覆盖统计/方法论/URL 清单)、"不是…而是…"句式、对话口吻;行动标签须为 `[A 趁早行动][B 研究/跟进][C 跟踪][D 关注]`;评分须写"N分" |
| **F 门(事实)** | **代码定位 + LLM 判灰区** | 代码抽出稿内全部数字/文号/日期/引号引文 → 在对应 bundle 内做精确与近似匹配 → **只有匹配不上的才交 LLM 判是否等价表述**。绝大多数可代码判掉;模型答不出来维持原判(宁可多报不可放过) |
| **业务口径门(新增)** | **纯代码** | 只认**行首业务标签**,不见词就抓(2026-06 终稿里换电出现 11 次、虚拟电厂 12 次、储能 7 次,它们是**议题**不是业务线,见词就抓等于全篇误报)。查三条:`B-LINE` 业务线名须在画像三条内;`B-LABEL` 业务标签的括注里不得带已退役项(换电/国际化)、hold 项(储能)或材料空白维度(V2G 等);`B-NEGATIVE` 不写「X 业务:不相关」 |

**F 门的抽取口径(2026-09-07 实测校准)**:只认文号、带日的日期、第 N 条、
**带单位的阿拉伯数字**、引号里的短引文。中文数字("三大业务""一、概述""十余省")
不是事实断言,抽进来每期几十条假阳性,人看两次就不看了,这道门也就废了。
拿已交付的 2026-04 全文实测:抽出 61 条(日期 33 / 数字 24 / 条款号 2 / 引文 2),
**零中文数字误抽**。两处按真语料定的细节:

- **文号前缀没有分隔符**,正则只能贪婪地把前面的词一起吃进来(「依据发改能源〔…〕」)。
  与其放松正则(那会让「错改能源〔2026〕1067号」蒙混过关),不如按结构比:
  文号核心须原样出现,且素材里紧挨核心的那串汉字必须是稿内前缀的后缀。
- **本期自身的结构计数要给源**。「国家级 5 项 + 省级 8 项」回指的是本期选目而不是
  某份 RAW;不给源就每期误报几条,给了则数错的计数反而会被抓出来。

**事实源按段划分**:详情块**只认它自己那一个 bundle**——那正是分块写作的意义,
写第 1 篇时看不到第 5 篇的材料就编不出跨篇事实;概述与综述是从已写完的各块收上来的,
故以各块正文加结构计数为源。返修的「是否变好」把 F 门一并算进去,
免得风格改好了却把数字改错。

**两道代码门的实测校准(2026-09-07)**:对 2026-05 终稿、2026-06 终稿、2026-06 初稿三份真语料跑:

- **D 门三份全 0 条**——两份已交付终稿加一份人工 D 门审过的初稿,零误报;而两条正向模式(行动标签 11/17 处、评分「N分」3/4 处)正常命中。
- **业务口径门三份都命中同一条 `电力业务(储能·V2G·电力交易)`**,是**真阳性**:三份稿子都早于 2026-08-31 生效的画像,而新画像把储能定为 `hold`、V2G 列入 `scope_absent`(`open_questions` Q5 明写「现行口径把 V2G 列进电力业务线…本课程四段无任何依据」)。口径一变旧标签即过期——这门机械地抓住了「业务需求不准」这件事本身。

审计员也会错(拿 frontmatter 驳 RAW 落款、要求给 RAW 为空的政策写表行),故 `audit.json` 的每条都带 `location + quote`,MA7 只按条返修,不整篇重写。

**两道代码门按段跑,不按整篇跑**(`repair.audit_blocks`)。整篇跑只拿得到行号,行号对不上稿件结构,
MA7 就只能整篇重写——那会把已经过关的部分重新掷一次骰子。按段跑会不会漏?拿已交付的 2026-04
拆成 7 段实测:**整篇跑 94 条 / 按段跑 94 条,逐规则数目完全一致**,而按段跑每条都带得走定位。
可定位的最小段是:`overview` / `businessTakes[i].text` / `localRoundup` / `appendix` /
`details[NN].{info,reading,focus}` / `details[NN].advice[j].text`。

**返修不许把事情弄得更糟**:返修可能引入新违规,故按严重度加权分(BLOCKER 100 / MAJOR 10 / MINOR 1)
比一比,**不是严格变好就退回原文**——原文至少是带着完整上下文写出来的,这样也不会白烧掉一轮。

## 7. 数据契约

### 7.1 `content` 新 schema(存 `Monthly.content`)

```jsonc
{
  "schema": "monthly.v2",           // 老数据无此字段 → 前端走 v1 渲染分支
  "month": "2026-07",
  "narrative": "本月定调一句话",
  "overview": "概述正文",
  "businessTakes": [                 // 三大业务速判,顺序固定 加油/充电/电力
    { "business": "加油", "text": "..." }
  ],
  "quickTable": [                    // MA5d 代码生成
    { "no": "01", "policy_id": "P_...", "level": "国家级", "score": "5分", "title": "...",
      "issuer": "...", "date": "2026-07-23", "doc_no": "发改能源〔2026〕1067号" }
  ],
  "details": [
    { "no": "01", "policyId": "P_...", "title": "...",
      "info": "【政策信息】...", "reading": "【政策解读】...",
      "focus": "【重点关注内容】...",
      "advice": [ { "business": "充电", "tag": "B 研究/跟进", "text": "..." } ] }
  ],
  "localRoundup": "省级落地综述",
  "appendix": "附录",
  "uncovered": "已知未覆盖脚注(含 MA1b 抓不到 RAW 的缺口)",
  "caveats": [                       // MA5/MA7 残留 → 前端容错提示条
    { "gate": "F", "location": "details[03].reading", "note": "该段某数字未能回指原文" },
    { "gate": "D", "rule": "D-QUOTE", "severity": "MAJOR",
      "location": "details[01].reading", "note": "角括号须换成中文双引号(原文:「)" }
  ],
  "provenance": { "writerModel": "deepseek-v4-pro", "packSha": "...", "profileId": "2026-energy-strategy", "auditRounds": 2 }
  // 注:quickTable 与 caveats 的字段名以实现为准(`doc_no` 而非 `docNo`);
  // caveats 里 MA7 残留另带 `rule` / `severity`,MA5 侧删条产生的只有三字段。
}
```

**`caveats` 非空时**,前端在稿件顶部渲染容错提示条,文案大意:本期部分内容由 AI 生成,下列部分可能不够符合要求,敬请谅解;并列出 `location`。

### 7.2 中间产物落点

`state/monthly_<YYYY-MM>/`(gitignored):`candidates.jsonl` / `shortlist.jsonl` / `gap_report.json` / `judgments.jsonl` / `slate.json` / `pack/` / `draft/*.md` / `audit.json` / `final.md` / `*.docx`。**vault 内不建任何中间产物。**

## 8. 业务口径的唯一来源

月刊侧新增 `render_for_monthly(profile)`(与既有 `render_for_impact_analysis()` 并列,同一 `strategy_profile.py`)。与 pass2 渲染的差别:月刊既要判**要不要写这篇**(需要信号清单)也要判**怎么写影响**(需要 decision_variables),故月刊版渲染 `weight ∈ {high, suppress}` 的信号 + 三条业务线的 `decision_variables` + `relevance_rules` + `open_questions` 的 topic 列表。

硬规则(代码后校验,不靠模型自觉):

- `absent_is_not_low`:落在 `scope_absent` 维度的政策一律出 `需人工裁定`,**不得判 low**。
- `core_test`:相关性 = 是否改变 `decision_variables` 里的任何一个数;仅与公司判断同向而不改变任何在做的动作 = 不相关。
- `early_signal`:征求意见稿/规则修订预告**不因未生效而降权**。
- 定量目标(增长 >40%、份额 35% 等)在画像里全标"数字待核",**不得进稿**。

`check_impact_keys()` 在链路启动时对账;画像 `status != active` 或 `schema_version` 不在白名单 → **抛异常中止**,不静默用错口径把整期写一遍。

## 9. 容错与人工意见回炉(MA9)

1. MA7 两轮返修后仍有残留 → 照常投影发布,`content.caveats` 非空。
2. 前端顶部渲染容错提示条 + 修改意见栏。
3. 人提交意见 → 触发 MA9:意见 + 相关段落 + 该段 bundle → 重写 → 重过 MA6 → `Monthly.content` 换成新内容、`version+1`,同时写一行
   `MonthlyVersion{version: n, content: 新内容, changeNote: 人工意见原文}`。
   **不需新建表、不需 DB 迁移**:`changeNote` 与 `content`(JSON 列)都是现成字段。
   首次自动生成也写 `version: 1, changeNote: "自动生成"`,版本历史因此完整可回溯。
4. **人工意见同样过 F 门**;若意见要求写入无 RAW 支撑的内容,返修结果中该点不写入,并在 `caveats` 记一条说明。

## 10. 交付批次

| 批 | 内容 | 模块 | PR 标签 |
|---|---|---|---|
| **PM1** | L3 迁入 monorepo:`l3_render/` 4 脚本 + 测试 + slate schema + `SCHEMA.md` §7 + P0 Gates 纳入 `tests/l3_render` | policy-pipeline + infra | `[CROSS-MODULE]` |
| **PM2** | MA0/MA1/MA1b/MA2/MA3 + MA6 的两道代码门(选目链路,不含写作) | policy-pipeline | — |
| **PM3** | MA4/MA5/MA7/MA8 + cron + 投影 heng-pg | policy-pipeline + heng | `[CROSS-MODULE]` |
| **PM4** | 前端:v2 schema 渲染 + 容错提示条 + 修改意见栏(MA9) | heng 前后端 | `[CROSS-MODULE]` |

每批独立可验证、独立 PR。PM2 跑完就能拿 `slate.json` 与人工 6 月选目对账——**质量评估的第一个观测点在 PM2 就出现,不必等全链路**。

## 11. v4pro 出稿质量评估

金标准 = 已交付的 **2026-06 终稿**(人写、过了 F/D 门)。

| 期 | 有金标准 | 观测指标 |
|---|---|---|
| 2026-06 | 有 | ① 选目重合度(MA3 `slate` vs 人工 6 月实际选目);② F 门首轮通过率;③ D 门首轮违禁项数;④ 返修轮数;⑤ token 与成本;⑥ **去标识盲评**(两稿去掉出处交用户判) |
| 2026-07 | 无 | 门通过率 + 盲评 + MA1b 缺口数(实测已知至少 2 条) |
| 2026-08 | 无 | 同上 |

产出评估报告 **HTML**(自包含,落 `docs/`)。

**成本估算(2026-09-07 实测口径,替代先前的拍脑袋估算)**:

| 项 | 实测/推算 |
|---|---|
| 业务口径段(`render_for_monthly` 输出) | 2670 字符 ≈ **1335 token**,34 条信号(27 high + 7 suppress) |
| MA2 候选量 | 2026-06 245 篇 / 2026-07 261 篇 / 2026-08 170 篇(去噪去重后) |
| MA2 单篇 user 段 | RAW 头部约 1500 token + 标题 |
| MA2 总输入 | 261 × (1335 + 1500) ≈ **74 万 token**;**口径段放 system 段**使前缀逐字相同,吃上服务端前缀缓存后这 35 万可大幅折价 |
| MA3 单次输入 | **实测 12–19K token**(2026-06 17.7K / 07 19.0K / 08 12.5K),一次调用放得下 |
| MA5a system 段 | **实测 1900 token**(体例 565 + 口径 1335),跨篇逐字相同可吃前缀缓存 |
| MA5a user 段 | **实测**真 bundle 中位 2157 token、最大 5658 |
| MA5a 一期 10 篇 | **实测总输入 49.6K token,其中 19K 是可缓存的重复前缀** |
| MA5b / MA5e system | **实测 1536 / 1627 token**;MA5b user(5 条真摘要)183 token |
| MA5d 速览表 | **0 token**(纯代码) |
| MA6 两道代码门 | **0 token**(纯正则与词表) |
| MA7 返修 | 每轮 = 命中段数 × (段文本 + 该段 bundle);实测一份老稿 7 段全中,两轮封顶 ≤14 次调用 |

**2026-09-08 首跑前实测(生产端点,真 vault 数据)——以下取代先前的待核项**:

| 项 | 实测 |
|---|---|
| 端点提供的模型 | 只有 `deepseek-v4-flash` / `deepseek-v4-pro` / `deepseek-v4-flash-vision-exp` 三个 |
| 生产配的 `deepseek-chat` | **不在列表里**,被网关静默解析成 `deepseek-v4-flash`(响应里 `model` 字段自报) |
| **v4pro 是推理模型** | 判定任务实测推理 token **min 1291 / 中位 1558 / max 2564**,而正文只有约 50 token |
| max_tokens 不够时的表现 | **不是截断正文,而是推理吃光预算、正文返回空串**(`finish_reason: length`) |
| 单次延迟 | **约 100–140 秒**(prompt 约 2800 token) |
| 官方单价(每 1M,off-peak/peak) | v4pro 输入命中缓存 $0.022/$0.044、未命中 $0.66/$1.32、**输出 $1.98/$3.96**;v4-flash 是其 1/3 |
| 推理计费 | 推理 token 计在 `completion_tokens` 里,**按输出价计费** |

**由此定的两件事**:

1. `budget.py` 一处集中定义各步预算(判定/短 JSON 4000、选目 8000、写作 6000、
   返修 5000),重试时翻倍。**预算是给推理留的,不是给正文留的**——
   原来 `judge_one` 给 800,实测直接返回空串,而它一期要跑 244 次。
2. `usage.jsonl` 记每次调用的 token(reasoning 单列)与 finish_reason。
   共用的 `llm_calls.jsonl` **不记 token**,拿它校准成本这条原来是写错的。

**时长估算**:MA2 一期 244 次 × 约 120 秒 ÷ 并发 4 ≈ **2 小时**。放在每月 2 号
04:00 的 cron 里没问题,但不适合交互式等待;并发可上调,注意端点限流。

`deepseek.service.ts` 里写死的 `0.0014 / 0.0028 ¥/1K` 是老 deepseek-chat 价,
**对 v4pro 偏低约一个量级**;平台上按那两个常数算出的 `aiCostCny` 会失真
(月刊不受影响,它自己记 token)。

**为什么口径段放 system**:一期要判两百多篇,口径段每篇都要带。放 user 段等于把同一段口径重复付费两百遍;放 system 段让整个前缀逐字相同,前缀缓存才可能命中。`test_judge_system_prefix_is_identical_across_candidates` 把这条钉住。

## 12. 验证方式

- **PM1**:`cd services/policy-pipeline && python3 -m pytest tests/l3_render/` 全绿(本机 24 passed);
  **回归证据**:用 2026-06 的 `final.md` + 模板 `能源政策月刊-2026-04(2).docx` 跑重构后的 `render()`,
  产出的 `word/document.xml` 与已交付的 2026-06 成品**逐字节一致**(33780 bytes)。
  **全量 pipeline 套件本机跑不了**:本机 `python3` 是 3.9.6,而仓内代码用 PEP 604(`str | None`),
  真实运行时是 `python:3.12-slim`;`pyproject.toml` 的 `requires-python = ">=3.9"` 与实际不符(既有问题,非本任务引入)。
  全量验证走 P0 Gates(CI 用 3.11/3.12)。
- **PM2**:对 2026-06 跑 MA0–MA3,`slate.json` 通过 schema 校验与配额校验;去重用例(942/884/42号令三组已知重复)有红测。
- **PM3**(已完成):本地 vault + 真画像 + 真 RAW,写作用可注入的假 client 跑通 MA4→MA8——
  4 个 bundle → 2 篇详情 → 速览 2 行 → 三条业务速判按画像顺序 → 25163 字节 docx;
  `final.md` 过两道门 **0 条**;docx 解 zip 验 `[Content_Types].xml` 在首位、文头与表格块都在。
  **v4pro 真跑仍需 operator 带凭据在 VPS 上做**(本地无生产数据,见 §13.8)。
- **PM4**:前端 v1/v2 双 schema 渲染快照;`caveats` 非空时提示条出现;修改意见提交产生 `version+1`。
- **越界**:`git diff --name-only origin/master..HEAD` 逐条比对 §3 allowedPaths。

## 13. 已知限制与风险

1. **PM1 源文件只在本机、未推任何远端**(旧仓 `205ada0` docx 渲染器、`866a68f` skill)。迁移从本机搬,不是从远端拉;搬完旧仓那两个 commit 不再是唯一副本。
2. **生产模型不是 v4pro**:`platform-heng-backend` 现跑 `deepseek-chat`。本链路自带 `--writer-model`,不依赖也不修改全局 env;但 **v4pro 的 API 可用性与单价需 operator 用生产 key 实测**。
3. **MA1b 腿 2 的搜索出口**:实现复用了仓内既有的 `l1_collect/tavily_client.py`,
   CLI 为 `--search-provider tavily|none`(`none` 时返回空,链路不阻塞)。
   腿 1(定向抓权威来源列表页)按 §6.1 **不在 L3 实现**。
   **2026-09-08 核实:生产 `.env` 里有 `TAVILY_API_KEY`,首跑可直接开 tavily,
   不必降级成 none。**
4. **`scope_absent` 的连锁效应**:画像把柴油/重卡/农村/高速/V2G 全记为材料空白,MA2 会把这些一律标"需人工裁定"。若某月这类政策多,`roundup` 会变长而 `detail` 变薄。这是**画像的真实状态**,不是 bug;需人工裁定的量本身就是给业务方的信号。
5. **既有 1546 篇按四版块打的分与三版块新分不同口径**(`business_strategy.yaml` `known_conflicts` 记载)。月刊只把 business_view 当召回信号、不当排序定论,故不受此影响;但 MA1 的召回率会受历史打分口径影响,评估时需注意。
6. **cron 时刻**:定 04:00 是为了排在 03:30 `analysis_context` 重算之后。若当月 2 号 03:30 那轮失败,MA0 新鲜度闸会中止本轮并告警——**宁可不出,不出错稿**。
7. **`--style-sample` 是 VPS 专用**:全盘检索确认本机只有 2026-04 那一期,而它是退役原型版
   (两道门判 182 条,含 BLOCKER 级「乡村能源」内容污染,恰落在「三大业务速判」那一段)。
   **它不能当版式样例喂**。PM2-d 校准用过的 2026-05/06 终稿只在 VPS 上,故本地路线不传该参数。
8. **本地跑不出生产数据**:把生产 vault 的 `0_raw/policies` rsync 到 macOS,1653 篇只落地 195 篇
   (超长与异常编码的文件名建不出来)。L3 的本地路线只能用本地热备 vault,质量首跑必须在 VPS 上。
9. **渲染器里业务线名写死**(`render_docx_clone.classify_line` 认 `加油业务|充电业务|电力业务`)。
   那份代码对已交付终稿做过逐字节校验,故**不动它**;改为加一条测试:画像里的业务线若有一条
   渲染器不认就红——让口径走散变响,而不是让业务速判静静掉回正文排版。
10. **L1 抽取会把站点导航当正文**:实测 168 篇 RAW 里 23% 的字符是 URL 与图片占位;
   `P_2026_GD_FGW_8a3b29d9` 去掉 URL 后只剩 586 字符且**全是导航菜单**。L3 侧只做止血
   (`pack_lib.strip_web_chrome()`,只清喂给模型的摘录、不动 vault RAW),根因在 L1,另开任务。
11. **老 chat 链路并存**:`MONTHLY_CHAT_SYSTEM` 那条无锚点改 JSON 的链路本期不动,与 MA9 并存。两条路都能改稿会造成口径不一,建议 PM4 之后另作任务下线老链路。

## 14. 自检

**第一轮 — 对照用户原话**:
- 用月刊 skill 的方式做 → §6 MA0–MA9 即五步产线的工程化 ✓
- 业务需求参考公司战略文档 → §8 口径唯一来源 = `business_strategy.yaml`,且列了现有写死口径的四处错 ✓
- 每月 2 号自动出成稿、前端只展示 → §5 cron + §10 PM3/PM4 ✓
- 用平台现有 key 跑 v4pro → §3 不改全局 env,链路自带 `--writer-model`;§13.2 标出生产现跑 deepseek-chat ✓
- 不是一次性提示词暴力来回、按 agent 分步 → §6.2 MA5 拆五个写作单元,每块只喂一个 bundle ✓
- v4pro 质量评估是一环 → §11 ✓
- 门不过要容错提示 + 修改意见栏再过一轮 → §9 MA9 ✓
- 取政策含库里 + web 双保险 → §1.4 实测 + §6 MA1b + §6.1 缺口处置 ✓

**第二轮 — 对照真实代码/环境**:
- 装包四样料齐全性:仅 pipeline 容器满足(SSH 核实挂载)✓
- `strategy_profile.py` 确有 `render_for_impact_analysis()` 与 `check_impact_keys()`,月刊新增并列渲染函数而非改既有 ✓
- `Monthly.version` + `MonthlyVersion{version, content, changeNote}` 全部现成,MA9 **不需新建表、不需迁移**——`changeNote` 正好存人工意见原文,`content` 是 JSON 列不需改 schema。故 PM4 无 `[DB-MIGRATION]` ✓
- `pack_lib.is_noise()` / `pick_record()` 现成可用;去重是**新增**能力(既有 `pick_record` 只解决同 id 撞车,解决不了不同文件名的重复采集)✓
- allowedPaths 不含 `docker-compose.yml`,故 heng 不新挂 `/state`——这正是选 pipeline 容器的另一个理由 ✓
