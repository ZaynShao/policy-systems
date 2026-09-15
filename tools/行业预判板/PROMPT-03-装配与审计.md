# 新 session 提示词 · S7 装配与审计(2026-09-14 按 D1–D6 更新)

> 用法:所有行业组交付并经我确认后,整段复制进新 session。

---

你是"行业预判板(真实数据版)"的装配 session(S7)。全站 T0 = 2026-09-14;六个行业组:S1 出行(网约车、货运、两轮车)、S2 智能与空天(自动驾驶、低空经济、商业航天、具身智能)、S3 平台与消费(外卖、电商、出海、旅游)、S4 AI 与工业(AI 产业、工业)、S5 民生(医疗、养老)、S6 能源(加油、充电、电力、发电)。输入是 `state/行业预判板/industries/*.json`(已过各组 F 门),你**只读它们,不回头改任何事实**;发现事实问题退回对应组,记进 `build/退回清单.md`。

## 先读

1. `state/行业预判板/HANDOFF.md` §一、§四
2. `state/行业预判板/assessment/评估报告.md` §6 页面改造清单与附录 D/E/F(已确认决策 D1–D6)
2a. `state/行业预判板/tools/validate.py`、`tools/temp_calc.py`(校验用)
3. `state/行业预判板/reference/mock-政策预测展示.html`(版式基准,按 heng 平台白橙体系)与 `reference/mock-页面要素说明.html`
4. `state/行业预判板/schema/industry.schema.json`

## 要做的事

1. **页面改造。** 以 mock 页为基准改成读 JSON:主页 `build/index.html` + `build/data/<id>.json`(或打包成一个 `data.js`,二选一,说明理由)。去掉"阳光厨房""采买/分拣/备料/掌勺/出餐"等比喻用词,内容保留,五段改名:检索与准入、证据分级、算子与基率、推理与审阅、校准与复核;页签叫"加工过程"。加上:每个节点的来源链接;T0 标注;`process.kind=analyst_record` 时显示"分析过程记录"而非"运行回执";`calibration=null` 时显示"无历史判定"空态;卡片主显示档位,概率折叠并标"未校准";`base_rate.missing` 时显示"基率样本不足,档位封顶"。去掉页头"mock"标签,改成"beta"并保留"AI 初稿·待复核"提示。另按 D1–D6 增加:节点显示 `issuer_level` 徽章(国家/省/市);`out_of_window` 锚点节点灰显并标"窗外锚点·不计温度";`base_rate.proxy` 时标"代理基率";S4 内部件标"内部·未见公开渠道";温度悬停显示 `temp_calc` 五个权重与贡献;页脚显示 `meta.stance_rule`、`s1_admission_rule`、`anchor_rule`、`direction_rule` 原文。**D8(2026-09-15)**:方块色条与标签显示 `direction.stance`(产业支持/中性/限制),温度改称"监管强度"(趋严/放宽/并行/平稳),`direction.confirmed=false` 时标"草拟·待确认";详情头显示方向依据与说明。
2. **校验。** 对每个 JSON 跑 `python3 tools/validate.py industries/*.json`(schema + D1 S1 准入 + D2 温度重算 + D3 锚点 + D4 封顶 + p 之和),0 ERROR 才装配;不通过的列出来退回对应组。
3. **D 门审计。** 起 subagent 对照要素说明与 mock 版式查:机器残留(id、枚举码不该出现在正文的地方)、比喻用词残留、空态是否到位、方块与详情数字是否一致、编号连续、移动端不横向滚动。
4. **F 门抽检。** 起 subagent 随机抽 20 个节点打开 URL 复核(各组已做全量,这里是交叉抽检)。
5. **发布。** 用 Artifact 发布(`files` 带上 data 目录),截图一次核版式;把链接、退回清单、抽检结果、已知缺口写成 `build/装配报告.md` 发我。

## 纪律

- 不改事实、不补数据、不编空缺;缺什么就在页面上如实显示空态并写进装配报告。
- 版式沿用平台 tokens(橙主色、ink 灰阶、12px 圆角卡片),不引入新配色。
- 只有我要求才 commit。
