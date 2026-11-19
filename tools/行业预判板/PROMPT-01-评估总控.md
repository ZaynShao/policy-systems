# 新 session 提示词 · S0 评估总控

> 用法:整段复制进新 session。这一段只做评估,不做数据采集、不改页面。

---

你接手的是"行业预判板(真实数据版)"。先读交接材料,再做评估,评估完停下等我确认。**在我确认之前不要开始采集任何行业数据,也不要改页面。**

## 先读(按顺序)

1. `state/行业预判板/HANDOFF.md` —— 目标、现有资源、我的预评估、数据契约、分工建议、停点
2. `state/行业预判板/schema/industry.schema.json` 与 `schema/example.json` —— session 之间的数据契约
3. `state/行业预判板/reference/方法论实例-电力零售规则预测报告.md` —— 方法论的一次完整实例(证据分级、四算子、基率、H1/H2/H0、T0、回推核验)
4. `state/行业预判板/reference/mock-页面要素说明.html` 与 `reference/mock-政策预测展示.html` —— 页面要素与组成关系(mock)
5. monorepo `/Users/didi/dev/safety-platform` 的 `origin/master`(用 `git show origin/master:<path>` 读,不要 checkout,不要动在途分支):`services/policy-predict/app/forecast_profiles.py`、`app/analysis_operators.py`、`docs/PRD-policy-forecast-methodology-v2.0.md` 的 M4/M5/M6、`docs/policy-prediction-phase1/`(来源目录、卡片模板 v2、示例卡)
6. 记忆里的 `policy-vault-layer-contract`、`vault-data-traps`、`editorial-scope-rules`、`business-strategy-profile`、`policy-predict-demo-retail-rules`

## 评估要回答的问题(写成报告,存 `state/行业预判板/assessment/评估报告.md`)

1. **每个行业的数据可得性。** 19 个行业逐个填一张矩阵:政策库有没有覆盖(有则列 pid 数与代表件)、预测服务内置方向是否对应、官方来源在哪几个网站(列栏目 URL 并实际打开验证一次)、12 个月窗口内能不能凑到 3 条以上 S1 政策事实(抽 2 个非能源行业实测,不要推测)、基率样本能否找到 5 个、社会要素有没有带来源的材料。凑不齐的标红,这是停点。
2. **行业范围定义。** 对 HANDOFF §三.7 列的歧义行业(电力/发电、工业、医疗、养老、AI 产业/具身智能、出海/电商、旅游)各给一句范围定义和一句理由,列成表让我逐条确认。
3. **四个方法决策,给建议并说明代价:** ① 卡片主显示档位还是概率(预测服务第一阶段规定只用档位;9-14 实例用了概率);② "加工过程"用分析师过程记录还是要接预测服务的真实运行(后者需要 token 或管理员);③ 校准数据几乎为零时页面怎么呈现;④ 非能源行业的影响只写战略/政府事务/合规三维,还是需要我另给业务口径。
4. **分组与 session 数。** 复核 HANDOFF §五的分工,估每组的节点数与工作量,给出你建议的组数、每组行业、统一的 T0、以及每组 session 的产出验收标准。说明为什么这样分(上下文窗口、来源机关重叠、方法复用)。
5. **停点清单。** 把评估中发现的所有"只能用 mock 才能填满"的地方列出来,不要替我决定。
6. **页面改造清单。** 从 mock 页到真实页要改什么:读 JSON、去掉"阳光厨房/采买/分拣/备料/掌勺/出餐"用词(内容保留,改中性名)、空态、档位显示、来源链接、T0 标注等。只列清单,不改代码。

## 评估的纪律

- 事实以原文为准,frontmatter 不可信(机关、日期、文号都要回原文核)。
- 联网只用于验证来源可打开和抽样实测,不在评估阶段大规模采集。
- 不 SSH、不碰生产、不代登任何平台;需要服务器或 token 的事只写进停点。
- 中文为主,直接给结论,有不一致先指出。
- 评估报告写完后,**停下来**,把矩阵、范围定义表、四个决策建议、分组方案、停点清单发给我。我确认后再按 `PROMPT-02-行业组工作.md` 开行业组 session。
