# policy-qa · 政策问答助手(对内)

滴滴能源政策库的问答服务。回答两类问题:解读某份政策,以及"最近对某块业务影响大的政策有哪些"。
答题纪律沿用政策月刊那套(事实零容错):事实只锚政策原文,内部评分只当信号,附件里的数字不推算。

## 边界(先读这段)

- **对内服务,不是对外出口。** 使用者是加油/充电/电力业务的内部同事,与 business_view、月刊
  是同一受众,所以内部评估、影响分析、建议都可以出。这与 `policy-corpus` 那条对外只读语料
  API 的纪律不同(那条只出原文不出判断),**两者不要混淆**。将来若要给外团队用,必须降级成
  白名单投影,那是另一个项目。
- **本服务不写任何东西。** 不写 vault,不写 heng-pg。数据库连接是只读的,连接级还额外设了
  `default_transaction_read_only`。
- **本服务从不挂 vault 卷。** 生产数据面是 heng-pg 的每日投影;vault backend 只用于本地开发。
- **只对登录平台的用户开放。** 靠 nginx 的 server 级 auth_request 兜底(见「部署」段),
  不是靠本服务自己的令牌。部署后必须实测未登录访问进不去。

## 架构

```
vault ──(pipeline 每日 21:00 投影,本服务不参与)──▶ heng-pg
                                                    │ 只读
                                                    ▼
                     policy-qa: 4 个检索工具 ─ Pydantic AI tool-calling loop ─ DeepSeek
                                                    │ SSE
                                                    ▼
                                            自带单页 UI / 其他内部调用方
```

没有向量库、没有 embedding。库里约一千五百篇政策的元数据结构化程度很高(日期/区域/机关/
主题/评分/关系边),两类问题分别是**定位问题**和**结构化筛选 + 编辑判断问题**,
让模型多轮调用结构化检索工具比 embed-everything 更贴合数据。语义检索留到二期再说。

## 本地跑

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

vault backend(读本机 vault 克隆,不需要数据库):

```bash
POLICY_QA_DATA_BACKEND=vault \
POLICY_QA_VAULT_DIR="/path/to/policy-vault" \
POLICY_QA_ACCESS_TOKEN=dev-token \
DEEPSEEK_API_KEY=sk-xxx \
.venv/bin/uvicorn app.main:app --port 8741
```

浏览器开 `http://127.0.0.1:8741/`,填 `dev-token`。

pg backend(连 heng-pg 只读角色):

```bash
POLICY_QA_DATA_BACKEND=pg \
POLICY_QA_DATABASE_URL="postgresql://policy_qa_ro:***@127.0.0.1:5432/hengguan_staging" \
POLICY_QA_ACCESS_TOKEN=dev-token \
DEEPSEEK_API_KEY=sk-xxx \
.venv/bin/uvicorn app.main:app --port 8741
```

### 环境变量

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `POLICY_QA_DATA_BACKEND` | ✓ | — | `pg`(生产) / `vault`(本地开发) |
| `POLICY_QA_DATABASE_URL` | pg 时 ✓ | — | **只读角色**的 DSN |
| `POLICY_QA_VAULT_DIR` | vault 时 ✓ | — | 本机 vault 克隆路径 |
| `DEEPSEEK_API_KEY` | ✓ | — | 复用平台共享变量 |
| `DEEPSEEK_BASE_URL` | | `https://api.deepseek.com/v1` | |
| `POLICY_QA_MODEL` | | 回退 `DEEPSEEK_MODEL`,再回退 `deepseek-chat` | |
| `POLICY_QA_ACCESS_TOKEN` | 见右 | — | 静态 bearer。独立部署时必填;平台内部署可不填,改设下一行 |
| `POLICY_QA_TRUST_PLATFORM_AUTH` | 见右 | 关 | 设 `1` 表示鉴权由上游 nginx 的平台登录态完成,服务不再要 bearer。**它与上一行必须至少配一个,否则启动即失败** |
| `POLICY_QA_LOG_DIR` | | `./qa_logs` | 会话 jsonl |
| `POLICY_QA_MAX_TOOL_ROUNDS` | | `18` | 单次回答的工具调用上限;耗尽后工具停摆让模型收尾,不报错 |
| `POLICY_QA_PG_MAXCONN` | | `8` | 连接池大小,也是并发查询上限。模型一轮会并行发多个检索,超出的排队等待。调大前先看 heng-pg 还剩多少连接 |
| `POLICY_QA_REQUEST_TIMEOUT_S` | | `120` | |

## 接口

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/healthz` | 否 | 存活探针,不带数据 |
| GET | `/v1/health` | 是 | 后端类型、政策数、最新发布日/投影时间 |
| POST | `/v1/chat` | 是 | SSE 流式问答 |
| GET | `/` | 否 | 单页 UI。平台内部署时不要令牌;独立部署时收到 401 才提示输入 |

`POST /v1/chat` 请求体 `{"messages":[{"role":"user"|"assistant","content":"..."}]}`。
**服务端无会话状态**,历史由客户端每次全量带上。`role: "system"` 一律 400 ——
答题纪律全在服务端 system prompt 里,允许客户端覆盖等于没有纪律。

响应事件序列:

```
event: meta   data: {"request_id":"...","history_truncated":false}
event: tool   data: {"seq":1,"name":"search_policies","args_preview":"business_line=充电","args_full":"{\"business_line\":\"充电\"}","status":"start"}
event: tool   data: {"seq":1,"name":"search_policies","status":"done","result_chars":2317}
event: delta  data: {"text":"……"}
event: delta_reset  data: {}
event: done   data: {"citations":[...],"usage":{...}}
event: error  data: {"message":"..."}
```

`args_preview` 是给 UI 显示的一行摘要(60 字上限);`args_full` 是完整入参,
会话日志记的是它。别把两者搞反——排查故障时,决定成败的参数往往正好在被截掉的那段里。

`delta_reset` 的意思是「刚才发的 delta 不算数,清空重来」。模型在**还要接着调工具**的
轮次里也会输出文本,那是规划自语(实测:"我先做几轮并行检索…现在深挖几篇原文");
流式下当场分不出它和正式答复(`output_type` 是 str,任何文本都匹配输出模式,
`FinalResultEvent` 照样触发),但一旦本轮冒出工具调用就能确定。客户端收到它
必须清空当前这条回复已累积的文本。

流开始之后出错只能以 `error` 事件收尾(HTTP 状态码已经发出去了)。错误文本经过脱敏,
不回显异常细节。

## 启动自检(pg backend)

服务启动时核对 heng-pg 的 `"Policy"` 表有没有本服务要读的列(`sqlbuild.REQUIRED_POLICY_COLUMNS`),
缺了**直接不启动**,并把缺的列名打出来。

这是拿事故换来的:2026-08-18 上线当天,库里没有 `adcode` 列(heng 的 2026-06-28 迁移加的),
于是**每个带地区词的检索都失败**,而 `/v1/health` 一路绿灯——它只查 count 和两个 max,
根本碰不到那些列。用户看到的只有一句脱敏的"政策库暂时不可用"。

缺列多半意味着 `POLICY_QA_PG_DB` 指向的库落后于 heng 的 Prisma 迁移,或者干脆指错了库。

## 已知限制

1. **同一 pid 对应多份文件。** 2026-08-17 全库实测 14 组、覆盖 40 篇,pid 键控下 26 篇不可见。
   成因在 L1 的 id 生成:id 取文号尾号,而系列公告常引用同一个"常设授权文号"
   (例:江苏成品油 7 篇全部引 发改电〔2015〕10 号)。heng-pg 按 `pipelinePid` upsert,
   同组只存得下一篇。本服务只读,在命中时通过 `caveat` 告知用户,**修在 pipeline 侧,不在这里**。
   vault backend 建索引时实测计数;pg backend 拿到的是投影后结果,运行时发现不了,
   只能靠 `store/__init__.py` 里的 `COLLIDED_PIDS` 快照——快照会过时。
2. **业务线过滤排除了"未直接涉及"。** business_view 是逐业务线全填的,不相关也会写
   "未直接涉及。"而不是留空(全库 1989 条影响条目里 1276 条、64% 如此)。若按"值非空即命中",
   业务线过滤会有六成噪声。判据见 `NEGATIVE_IMPACT_PREFIXES`,只认开头,不做语义猜测。
3. **投影不 prune。** vault 里已 archive 的政策仍留在 heng-pg。生产 cutover 时 TRUNCATE
   重建会自然清掉;staging 上长期累积。
4. **少量未来日期。** 库里有 3 篇 issueDate 在今天之后(最远 2030-06-01),按日期倒序会排到最前。
5. **正文含采集噪声。** 部分 RAW 正文带网站导航、页眉页脚。本服务原样传给模型,不做去噪
   (去噪是 pipeline 的事)。
6. **部分正文有编码损伤**(UTF-8 被 latin-1 解码的残留)。原样保留,prompt 要求模型明示
   "编码损伤、引用受限",不猜原文。
7. **`issuer` 字段全库 38% 为空**(547/1440),机关往往只写在标题里。检索时 issuer 与 title
   任一命中即算,否则会静默漏掉三分之一的库,并诱导模型做出"库里没有某机关的文件"这种
   假全称否定。
8. **文号在库内常被抓错。** 元数据的 `docNumber` 有时抓成本件所引用的上位依据文件、
   或被本件废止的旧文件的文号(实测:浙江分时电价件的 `浙发改价格〔2024〕21号` 其实是
   被它废止的旧件)。prompt 里有专门规则要求模型识别并如实说明,不许拿发布年份去凑文号
   ——这条是真模型冒烟时抓到编造后补的。
9. **SQL 已在真 Postgres 上验过**(2026-08-18)。`tests/test_pg_integration.py` 按
   heng 的 Prisma schema 建表,把每种 WHERE 组合、详情/关系/评论三条路径都让服务器
   真解析一遍;默认跳过,设 `POLICY_QA_TEST_DATABASE_URL` 才跑,办法见
   `docs/dev-postgres.md`。**仍未覆盖的是真实数据的形状**——线上是 pipeline 投影出来的
   真行,fixture 只有四行手写数据,列里的脏值(乱码、超长正文、异常 JSON)测不到。

## 测试

```bash
.venv/bin/python -m pytest -q
```

全部零真网:模型用 pydantic-ai 的 `FunctionModel`,数据库用注入的 fake executor。
真模型冒烟是手动步骤,不进 CI。已跑过一轮(2026-08-17,vault backend + DeepSeek):
核心用例「最近对充电业务影响大的政策」正常作答,自行识破了两处元数据陷阱
(国家级文件被标成采集省份、文号抓成上位依据件),按规则跳过了成品油调价公告,
撞车 pid 的缺陷说明也如实转述。同轮抓到一处文号编造,已补 prompt 规则并复验通过。

`tests/test_store_contract.py` 覆盖两个 backend 的 **Python 侧**语义一致性
(业务线过滤、排序、limit/total、行→模型映射);SQL 侧过滤由 `test_sqlbuild.py` 覆盖结构与参数,
由 `test_vault_adapter.py` 覆盖语义。这个分工在契约测试文件头部有说明,别误读它的强度。

## 评测

`eval/` 下两层,详见 `eval/README.md`:

- **检索评测**(免费、确定性、进 pytest 门禁):golden 选目能不能被检索层捞出来。
  标准答案抄自 2026 年 7 月月刊的人工选目 14 篇。
- **答案评测**(要真 DeepSeek,手动跑):答题纪律回归,每条用例对应一个真踩过的坑。

```bash
python eval/retrieval.py "/path/to/policy-vault"      # 免费
python eval/answers.py                                 # 花钱
```

## 部署

平台内路径 `/policy-qa/`,鉴权走**平台登录态**:nginx 是 server 级
`auth_request /_platform_access_check` 默认保护一切,本服务的 location **刻意不写**
`auth_request off;`,因此只有登录平台的用户能访问,也不会进那份"公开例外"清单。

服务自身在这种部署下不再要 bearer(`POLICY_QA_TRUST_PLATFORM_AUTH=1`),
与 heng/kb 等内部服务同一信任模型:不对宿主机暴露端口,只在平台内网可达。
两者都不配会**启动即失败**,免得哪天漏配就裸奔。

服务挂在 `policy-qa` compose profile 下,**不参与日常自动部署**——平台部署用
`up -d --wait` 等健康状态,凭据没配好时自动拉起会拖垮整个部署。启用要显式带
`--profile policy-qa`。它在部署契约里登记为可选容器(`OPTIONAL_PROFILE_CONTAINERS`)。

照抄步骤见 `docs/runbook-deploy.md`(含只读角色 SQL)。**部署后必须验证未登录访问进不去**
——这个服务输出内部评分和业务建议,那一步是"只对内"的唯一保证。

## 不在本 PR 内

- 拜访管理(功能二)→ 归 heng 域,另立项
