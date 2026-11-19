# Runbook — 月刊产线首跑(MA0→MA3 选目,MA4→MA8 全链)

> 目的:用真实凭据跑一次月刊产线。**分两步走**——
> §2–§6 先只跑选目(`run_slate`),拿 `slate.json` 与人工 2026-06 选目对账,
> 这是 v4pro 质量评估的**第一个观测点**,不必等全链路;
> §7 选目对得上再跑全链(`run_monthly`),出 `final.md` + docx;§8 是 cron 交接。
> 对应 spec:`docs/WORKFLOW-policy-monthly-agent-v1.0.md` §10 / §11 / §12。

## 0. 为什么必须在 VPS 上跑(不能在 Mac 上跑)

2026-09-07 实测:把生产 vault 的 `0_raw/policies` rsync 到 macOS,**1653 篇只落地 195 篇**,
其余在 `mkstempat` 阶段报 `Illegal byte sequence` —— vault 里存在超长与异常编码的文件名,
macOS 无法创建。已知的乱码 RAW(UTF-8 被按 Latin-1 存)是同一类问题的另一面。

**结论**:L3 的"本地路线"只能用已有的本地热备 vault(它已经规避了这些文件名),
**不能新拉一份生产快照到 macOS**。要用生产数据,就在 VPS 上跑。

## 1. 前置

| 项 | 说明 |
|---|---|
| 代码 | 分支 `feature/policy-monthly-agent`。VPS 上**另开 scratch 克隆**,不要动生产 checkout |
| 凭据 | `OPENAI_API_KEY` / `OPENAI_BASE_URL`(DeepSeek 端点)。`OpenAICompatClient` 从这两个 env 读,与现有 `--judge-provider openai` 同一套 |
| 模型 | `--writer-model deepseek-v4-pro`。**不要改全局 `DEEPSEEK_MODEL`**——那会连带影响客户画像等其它 AI 功能 |
| 数据 | vault `/root/policy-vault`(**只读**)、消费层 `/root/policy-pipeline-state` |
| 写入 | 只写 `--out` 指定的工作区目录。**不写 vault、不改 cron、不碰生产 checkout** |

## 2. 先跑 dry-run(不花 token,验证取窗与去重)

```bash
cd /root/scratch/safety-platform/services/policy-pipeline
python3 -m scripts.l3_monthly.run_slate \
  --month 2026-06 \
  --vault /root/policy-vault \
  --state /root/policy-pipeline-state \
  --out /tmp/monthly_2026-06 \
  --dry-run
```

预期(本机对同一份 vault 的离线核算):`candidates` 434 左右、`shortlist` 245 左右。
数字明显对不上就先停,别往下跑。

## 3. 正式跑(会调用 v4pro,产生费用)

```bash
export OPENAI_BASE_URL=...     # DeepSeek 端点
export OPENAI_API_KEY=...      # 不要回显、不要进 git
cd /root/scratch/safety-platform/services/policy-pipeline
python3 -m scripts.l3_monthly.run_slate \
  --month 2026-06 \
  --vault /root/policy-vault \
  --state /root/policy-pipeline-state \
  --out /tmp/monthly_2026-06 \
  --writer-model deepseek-v4-pro \
  --writer-provider openai \
  --search-provider none \
  --concurrency 4
```

约 244 次 MA2 调用 + 1 次 MA3。

**时长:并发 4 时约 2 小时**——不是十几分钟。v4pro 是推理模型,2026-09-08 实测
单次约 100–140 秒(prompt 约 2800 token)。开着跑别等,跑完再看。并发可上调,
注意端点限流。

`--search-provider tavily` 需要 `TAVILY_API_KEY`,**生产 `.env` 里已有**,直接开。

跑完除 §4 那几样,还多一份 `usage.jsonl`:每次调用的 token(reasoning 单列)
与 finish_reason。**看两个数**:`truncated`(finish_reason=length)与 `empty`
(正文为空)——它们不为零就说明 token 预算不够,那一批调用是白花的。
汇总用 `python3 -c "from scripts.l3_monthly.usage import summarise; print(summarise('usage.jsonl'))"`。

## 4. 跑完把这几样发回来

```
/tmp/monthly_2026-06/slate.json         # 选目结果(最要紧)
/tmp/monthly_2026-06/run_report.json    # 计数、修补记录、告警
/tmp/monthly_2026-06/judgments.jsonl    # 逐篇判定
/tmp/monthly_2026-06/llm_calls.jsonl    # token 与调用数,用于成本校准
```

`judgments.jsonl` 与 `slate.json` **不含凭据**;`llm_calls.jsonl` 只记 model / token 数 /
prompt 摘要哈希,也不含凭据与正文。

## 5. 中止情形与含义

| 退出信息 | 含义 | 处置 |
|---|---|---|
| `上游数据未就绪…analysis_context 已过期` | nightly 03:30 那轮没跑或跑挂了 | 先修上游,不要绕过闸 |
| `上游数据未就绪…战略画像不存在` | vault 的 `_meta/framework/business_strategy.yaml` 缺失 | 业务口径是相关性判据的唯一来源,缺件不得开跑 |
| `MA3 连续 N 次产不出合规 slate` | 选目失败 | 没有 slate 就没有可写的东西,硬停。把 `judgments.jsonl` 发回来看是不是判定层就坏了 |
| `run_report.warnings` 里有 `analysis_context 为空` | 生产上意味着 nightly 出了空结果 | 装包的 ac 段会整体降级为「无」,先查上游 |

## 6. 对账口径(拿回结果后我做)

- `slate.json` 的 `national_detail` vs 人工 2026-06 实际选目(4 篇国家级 / 2 篇地方 / 9 篇速览)
- `narrative` 是否说清三条业务线各自态势
- `run_report.slate_repairs` 有几条——修补越多说明模型越不守约束
- `judgments.jsonl` 里 `relevance=error` 的比例(输出稳定性)
- `usage.jsonl` 的 token 合计 → 校准 spec §11 的成本估算
  (`llm_calls.jsonl` **不记 token**,只记 prompt 哈希与输出字符数)

## 7. 全链跑(MA4→MA8:装包 → 写作 → 两道门 → 返修 → 组稿)

**先确认 §6 的选目对账过得去再跑这一步**——选目不对,后面写得再好也是白写。

```bash
cd /root/scratch/safety-platform/services/policy-pipeline
python3 -m scripts.l3_monthly.run_monthly \
  --month 2026-06 \
  --vault /root/policy-vault \
  --state /root/policy-pipeline-state \
  --out /tmp/monthly_2026-06 \
  --skip-slate \
  --writer-model deepseek-v4-pro \
  --writer-provider openai \
  --template-dir /root/scratch/monthly_template \
  --concurrency 4
```

- `--skip-slate` 复用 §3 已经跑出来的 `slate.json` 与 `judgments.jsonl`,
  **不重跑那两百多次判定**。加载时会跑一遍结构校验,不合法直接拒绝出稿。
- `--template-dir` 是**上期 docx 解包后的目录**(`unzip 能源政策月刊-2026-05.docx -d /root/scratch/monthly_template`)。
  不给这个参数就只出 `final.md` 不出 docx——公文版式靠克隆上期成品,凭空生成必然走样。
- `--style-sample` **本次不要传**。本机只有 2026-04 那一期,而它是退役原型版
  (两道门判 182 条,含 BLOCKER 级「乡村能源」内容污染)。VPS 上若有 2026-05/06 终稿的 md,
  可以传那个;传错样例等于把要修的病抄回来。

跑完发回来:

```
/tmp/monthly_2026-06/content.json    # monthly.v2 成稿结构(最要紧)
/tmp/monthly_2026-06/final.md        # 组稿结果
/tmp/monthly_2026-06/last_run.json   # 计数 / 返修轮数 / provenance
/tmp/monthly_2026-06/*.docx          # 公文成品
/tmp/monthly_2026-06/llm_calls.jsonl # token 与调用数,校准成本
```

**这一步不会因为门没过而失败**——那是设计口径:返修两轮仍不过,残留写进
`content.caveats`,文末加一行容错说明,照常出稿。`last_run.json` 的
`counts.caveats` 与 `caveat_locations` 就是本期"哪些地方可能不够符合要求"的清单。

### 全链的中止情形

| 退出信息 | 含义 | 处置 |
|---|---|---|
| `没有 slate.json` | `--skip-slate` 但工作区里没有选目产物 | 先跑 §3 |
| `slate.json 结构不合法,拒绝据此出稿` | slate 被手改过,或跨分区有重复 `policy_id` | 别绕过:重复 id 会让两篇详情共用一个素材包,而成稿看起来完全正常 |
| `读不到战略画像` | vault 的 `business_strategy.yaml` 缺失 | 业务口径是唯一真相源,缺件不得开跑 |

## 8. cron 交接(**由用户亲手加,我不碰生产**)

spec §5 定的是每月 2 号 04:00,排在 03:30 `analysis_context` 重算之后。

**crontab 一条记录必须是一行**——它不认行尾反斜杠续行。所以把命令放进一个包装脚本,
cron 只调脚本。这样 `%` 也不用转义(`%` 只在 crontab 那一行里才有特殊含义)。

`/root/bin/policy-monthly.sh`(chmod 700,凭据在里面,**不进 git**):

```bash
#!/bin/bash
set -euo pipefail
export OPENAI_BASE_URL=...      # DeepSeek 端点
export OPENAI_API_KEY=...       # 只在这里给,不要写进全局 env
M=$(date -d 'last month' +%Y-%m)
cd /root/safety-platform/services/policy-pipeline
exec python3 -m scripts.l3_monthly.run_monthly \
  --month "$M" \
  --vault /root/policy-vault \
  --state /root/policy-pipeline-state \
  --out "/root/policy-pipeline-state/monthly_$M" \
  --writer-model deepseek-v4-pro --writer-provider openai \
  --template-dir /root/monthly_template
```

crontab 一行:

```cron
0 4 2 * * /root/bin/policy-monthly.sh >> /var/log/policy-monthly.log 2>&1
```

注意三点:

1. 脚本**不带 `--skip-slate`**——cron 要跑全链,从取窗开始。
2. **不要往 crontab 或全局 env 写 `DEEPSEEK_MODEL`**。凭据与模型只在这个脚本里给,
   改全局会连带影响客户画像等其它 AI 功能。
3. `date -d 'last month'` 在每月 2 号执行,拿到的正是上一个月,不会跨错月。

首次上 cron 前,先手工按 §7 跑一期看产物,再交给定时任务。

## 9. 投影到平台(前端靠这一步才看得到)

`run_monthly` 只出 `content.json` + `final.md` + docx,**不写库**。投影是单独一步:

```bash
cd /root/scratch/safety-platform/services/policy-pipeline
DATABASE_URL=... python3 -m scripts.l3_monthly.project_pg \
  --content /tmp/monthly_2026-06/content.json \
  --status PUBLISHED
```

- 先用 `--dry-run` 看一眼(它在碰任何游标之前就返回,不连库)。
- **同月重跑会更新同一行并 version+1**,不会新建一期;每次都留一行
  `MonthlyVersion`(changeNote 记「自动生成」)。
- `status` 默认 `PUBLISHED`——用户口径是每月 2 号自动出稿、前端直接展示。
  想先进审核态就传 `--status AUDITING`,不必改代码。
- 详情里的 `policyId` 会按 `Policy.pipelinePid` 映射成 heng 的 id,映射不到就留空
  (前端不渲染链接)。映射不到的多不多,是 L1 政策入库覆盖度的一个体感指标。

`DATABASE_URL` 与 `OPENAI_API_KEY` 一样,**只在这一行或包装脚本里给,不进 git**。

## 10. 人工修改意见回炉(MA9)

读者在页面「修改意见」栏提交后,意见落在 `Monthly.content.pendingNote`。回炉:

```bash
cd /root/scratch/safety-platform/services/policy-pipeline
DATABASE_URL=... OPENAI_API_KEY=... python3 -m scripts.l3_monthly.human_note \
  --month 2026-06 \
  --out /tmp/monthly_2026-06 \
  --vault /root/policy-vault \
  --writer-model deepseek-v4-pro
```

- 没有待回炉的意见时它直接返回,不花 token。
- 用的是 `--out/pack/` 里 **MA4 当初留下的那批素材**,不重新装包。所以
  **这一期的工作区目录不能删**,删了就只能重跑全链。
- **人工意见同样过三道门**。改写过不了 D/F/业务口径门就不采用、保留原文,
  并在 `caveats` 里记一条说明——不会因为「是人说的」就写进去。
- 跑完自动投影回库,`version+1`,`changeNote` 记意见原文。

可以挂进 cron 每天跑一次(它没有待办时是空转),也可以人工按需跑。
