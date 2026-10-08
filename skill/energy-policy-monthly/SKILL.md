---
name: energy-policy-monthly
description: 生产滴滴能源政策月刊——从政策库选目、装配证据包、写作、三路审计到公文 docx 排版的完整流程。当用户要做月刊/月报/政策分析、说"做X月的月刊""跑一遍政策分析""出这个月的能源政策报告"，或要对能源政策做面向加油/充电/电力业务的决策简报时，务必使用本 skill。用户提到政策库、vault、slate、bundle、政策速览、政策详情、落地综述这些说法时也应触发。即使用户只说"分析一下最近的能源政策"没提月刊，只要目标是产出给业务决策看的政策分析，也用本 skill。
---

# 能源政策月刊生产

把政策库里上千条原文，收敛成一份敢下结论的决策简报。两条硬约束：**事实零容错**（每个数字、文号、引文都要能回指原文，读者拿它做投资和合规决策）、**读者读得快**（8 月刊第一版被读者评"冗杂、机器腔"，返工一次；现在的字数预算和风格禁区就是那次返工定下的）。

## 流程总览

五步，顺序不能乱：①选目 → ②装配 → ③写作 → ④三路审计 → ⑤docx 排版。

中间有两个必停点：
- **选目后停**：把 `slate.json` 和 `选目说明.md` 给用户，等裁定（哪些降级、哪些剔除、有没有内部件、要不要补采）再装配。用户的裁定逐条记进 slate 的 note 和选目说明的"裁定记录"节。
- **终稿后发**：docx、final.md、终审裁决三件一起发。

动手前确认：做哪个月；政策库在哪、**先 `git pull` 到最新并看 HEAD 日期**（本机是 GitHub 克隆，不自动更新）；上期成品在哪；本期有没有通过非公开渠道拿到的文件。

## 动笔前必读的三份东西

1. **`<vault>/_meta/framework/business_strategy.yaml`（`status: active` 那份）**——业务口径的唯一权威，三板块 fuel / charging / power。几个直接影响选目和措辞的点：
   - `scope_absent` 是**材料空白，不是业务边界**。柴油、重卡、农村、高速、居住区私桩、V2G 这些维度出现时，写成"现有业务材料未见安排，是否跟进需业务方裁定"，**绝不能写成"公司不做""不在打法之内"**，也不能自动判低相关。
   - 电力线的 `province_filter` 是选目判据：落在已进入省和目标省的省级件，相关性显著更高。
   - 电力线不按"储能/虚拟电厂 vs 电力交易"二分，储能当前 hold；要二分按客户场景。写"电力业务项下储能项目"，不写"储能业务"。
   - 加油线决策变量是批发价、炼厂装车价；充电线只讲公共充电场站、乘用车。
2. **最近一期成品**——`references/example-2026-08.md` 是风格与篇幅基准（精简版），`example-2026-07.md` 看结构也可以。学版式和口径，不抄内容点。
3. **`references/editorial-rules.md`**——剔除范围、风格禁区、内部件规格、字数预算。

`_meta/framework/` 下的 `report_blueprint.yaml`、`factcheck_rules.yaml` 标了 TAINTED，里面的 12 章蓝图不是当前格式，不要用。

---

## ① 选目

窗口取「目标月 + 到出稿日」。扫描脚本会同时捞回"成文日在窗口前、本窗口才入库"的跨月件（打印时标 ↩），国家级旗舰文件几乎都是这样漏的（7 月的 45 号、8 月的 942/1055/979 号）：

```bash
python3 scripts/scan_window.py --vault <vault> --lo 2026-09-01 --hi 2026-10-08 --out scan/candidates.jsonl --print
```

**打分只是弱信号，编辑判断主导。** 逐条看标题，不按分数截断。打分层的固有毛病：旗舰五年规划可能无分、跨条线财税与执法件常 1-2 分、无关政务件混入候选。另外打分跨期不可比（2026-06-06 前回填件是另一模型，系统性高 1.3 分左右），只做月内横向参考，不做同比。打分缺失或失准的，编辑直接定分并在 slate 的 `editorial_score` 记理由。

判断标准只有一条：这件事会不会改变加油、充电、电力三条线的任何一个决策变量。

短名单**必须回原文核文头**，frontmatter 全字段不可信（机关常是采集省份、date 可能是成文日、文号可能抓到侧栏、date 还见过误标成 01-01）：

```bash
python3 scripts/verify_head.py --vault <vault> --keys "售电公司管理办法" "分时电价"
python3 scripts/dump_raw.py --vault <vault> --kw "售电公司管理办法" --lines 60
```

看到 pid 与正文文号对不上（pid 错绑到正文引用的上位文件或页面侧栏另一份文件），顺手查那个"外来文号"指向的文件在不在库里，这往往是一条漏采线索。

**web 查漏**：用 `references/audit-prompts.md` 里的查漏提示词起一个后台 subagent，按机关扫一遍（重点是财税、海关、金融、工信、市监这些跨条线盲区）。结果回来后**先回库核**：库里其实有的（常见于日期误标）补进选目；库里没有的只进附录，不作正文事实源。

**非库内材料**两种，都不写进库：
- 内部件（用户提供）放 `internal/`，pid 用 `INTERNAL_<机关>_<年月>`，装配会提示"无 RAW"属预期，写作直接读原件。
- 补采件（用户裁定要补的公开材料，如答记者问）放 `supplement/`，带 frontmatter 记来源 URL 与抓取日，slate 里用 `supplement` 字段挂到对应政策。

然后写 `slate.json`（格式见 `references/slate-format.md`）和 `选目说明.md`（入选表、裁定请示、跨月与数据坑、下一步）。**到这里停，给用户看。**

---

## ② 装配

```bash
python3 scripts/pack_build.py --slate slate.json --vault <vault> --out pack/ \
    [--analysis-context scan/analysis_context_rebuilt.jsonl]
```

每件政策产出一个 bundle：RAW 去噪正文 + business_view + analysis_context + 关系边 + 评论节选。装配后**检查每个 bundle 的正文汉字数**，接近 0 的是"只有导航壳"的采集失败件，按漏采进附录，不要硬写。

**事实源边界**：可用 RAW 原文、business_view（仅信号）、analysis_context、关系边、评论校准、internal/、supplement/；禁用 summaries / opinions / classification / _extractions / market_intel；web 只做查漏和对观点。关系边只作线索，兄弟省份间的 cites_basis 常是共同引用样板文字触发的伪边。

`analysis_context.jsonl` 不在库里，可用归档的旧仓本地重建（在 `/Users/didi/policy pipeline/pipeline` 下，macOS 没有 `timeout` 命令，直接跑）：`python3 -m scripts.signal_context.run preview --vault <vault> --state <tmp>`，再 `python3 -m scripts.analysis_context.run preview --relations <vault>/1_extracted/relations/relations_canonical.jsonl --policy-context <tmp>/policy_context.jsonl --state <out>`。没有它也能装配。

---

## ③ 写作

**先通读所有 bundle 的 RAW 正文**，引文逐字准确，省略号跳接可以，改字不行。

结构照 `references/example-2026-08.md`：

```
一、概述           主线段落(≤4段) + 与公司三大业务的关联速判(3条)
二、政策速览        国家级表(打分|日期|文件|发文机关) + 地方表(日期|区域|文件|关键词|公司业务关注)
三、政策详情        (一)(二)… 每条:关键词 / 【政策信息】【政策解读】【重点关注内容】/ 决策建议
                   地方政策综述作最后一节:总起 → 单列一两件 → 其他地方政策合并速览
附录               值得提前关注的政策动向(含漏采件,≤9条)
```

**字数预算**（8 月刊返工后定的，写之前就按这个写，不要写长了再删）：正文汉字 9000 到 10000；概述每段不超过 220 字，不复述详情节里的数字；关联速判每条不超过三句；每件摘录不超过 5 条，印发对象概括写不逐字罗列；每条解读 2 到 4 点、每点 2 到 3 句。写完跑一遍精简自查（`references/audit-prompts.md` 末尾的脚本）：超 75 字的长句、禁词、机器残留。

**排序按打分从高到低，国家级在前**，速览表行序与详情节一致，地方表行序与地方综述叙述顺序一致。地方表日期统一用公开日。

**地方件合并成一节综述**，不与国家级并列展开。

内容与风格纪律全在 `references/editorial-rules.md`，最容易踩的：
- 剔除油价变动类内容（调价、幅度、批零价差）；油品消费达峰、绿色燃料替代、加油站税负保留。
- 决策建议只写相关业务，不写"X 业务无关"。
- 无机器残留：政策 id、主题码、维度码、⭐、直角引号、加粗星号、"采集/数据侧/vault"一律不进正文；也不要"本刊核查发现""扫描""缺项补回"这类过程性措辞。
- **去机器腔**：不用"三点判断""含义有四层"这种框架句开头；不用"共同指向""外部前提""锚点""底盘""读数""筹码""就此定型""不再只是…而是…"这类比喻和套话；一句话说一件事，长句按句号拆开。
- 内部件要明确呈现渠道价值；纪要类内部件不点名个人、只写到处室、数字全标"据交流"。
- 承接关系写成自然句；敢下结论，不堆"可能""或许"。
- 封面发布日期写实际出稿日，再出稿就改日期。

---

## ④ 三路审计

并行三个后台 subagent，提示词模板在 `references/audit-prompts.md`，照抄改路径即可：

- **F 门（事实）**——逐条把数字、日期、文号、机关、引文与 bundle / internal / supplement 比对，重点盯缺席性断言（"首次""未见""第一次"）、比例的分母对象、引文漏字、把口头口径写成"文件规定"、把通稿的话写成规划原文。
- **D 门（风格结构）**——对照上期成品查结构、排序、机器残留、业务边界（尤其 scope_absent 写法）、地方件越级、解读是否只是复述、抄上期判断句。
- **web QA**——查漏项 + 对观点 + 核稿件的缺席性断言是否仍成立。

三份回来后做**终审裁决**，写到 `audit/终审裁决.md`：每条 FAIL/WARN 一行，裁决（改/加限定/保留并记理由）与处置。FAIL 必改；WARN 逐条判断。审计员说"事实源里找不到"的数字，先回库原文核一遍再定，别急着删。审计发现的漏项如果库里其实有，补进正文；库里没有的进附录。

---

## ⑤ docx 排版

```bash
python3 scripts/render_docx.py --md draft/final.md --out "draft/【2026年9月】滴滴能源政策月刊.docx" \
    --ym "2026年9月" --pub "2026年10月9日"
```

版式参数写死在脚本里（来源见 `references/docx-format.md`）：A4 四边 2cm、正文宽 9639dxa、章节头 800/8839 橙块表格、政策标题级底纹加粗竖标、正文四号 1.5 倍行距。出稿后按 `docx-format.md` 末尾的自查脚本核：正文宽、markdown 残留、章节头 gridCol、详情节顺序。

出稿后把 docx、final.md、终审裁决.md 一起发给用户。改稿再出时，上一版留档为 `final_v1_<日期>.md`。

---

## 工作目录约定

```
state/<YYYY-MM>月刊/
  slate.json  选目说明.md
  scan/        candidates.jsonl、verify 输出、重建的 analysis_context
  pack/        bundle 与 INDEX.md
  internal/    内部件原件(+ 扫描件转写稿)
  supplement/  编辑裁定补采的公开材料
  draft/       draft.md → final.md → docx;旧版 final_v1_<日期>.md
  audit/       F门报告.md D门报告.md webQA报告.md 终审裁决.md
```

## 附带资源

- `scripts/` — scan_window（含跨月捞回）、verify_head、dump_raw、pack_build、render_docx、common（乱码还原、拆行文号拼接）
- `references/example-2026-08.md` — 当前风格与篇幅基准（精简版成品）
- `references/example-2026-07.md` — 结构参考（含 7 件国家级的长版）
- `references/editorial-rules.md` — 内容纪律、风格禁区、字数预算、内部件规格
- `references/audit-prompts.md` — web 查漏、F 门、D 门、web QA 四份 subagent 提示词模板，终审裁决模板，精简自查脚本
- `references/slate-format.md` — slate.json 字段说明
- `references/data-traps.md` — 政策库已知数据坑（逐期累积）
- `references/docx-format.md` — 版式参数及实测来源
- `assets/版式基准-2026-05.docx` — 版式基准
