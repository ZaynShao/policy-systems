# 政策大盘对齐工程层(L2)标准 — 设计

> 模块:heng(公共事务,政策大盘)· 状态:草案待评审(已消化 POP)· 作者:shaoziyuan · 日期:2026-06-28
> 原则(用户拍板 2026-06-28):**数据对齐以 pipeline 工程层(L2/L1)标准为基准,前端/heng-backend 一切可改。region 做"完整字段对应"。**
> 配套依据:中国行政区划规范参考(驾驶舱 `项目/safety-platform/参考-中国行政区划规范.md`);POP 仓 `ZaynShao/pop-policy-one-piece` 政策大盘设计(已消化,见 §2)。
> 编号:本文设计条用 `C#`,根因用 `G#`。

---

## 1. 背景与现状(已查证)

政策大盘 `/heng/dashboard/policy`(`PolicyDashboard.vue`)显示一组主题在各省的政策覆盖。**数据读的是 `KnowledgeEntry` 表**(不是 `Policy`):后端 `dashboard.service.ts` 的 `policyCoverage` 遍历 `AnalysisTopic`,对每个主题 `knowledgeCoverageByRegion` 把 `KnowledgeEntry` 按 `region` groupBy。`KnowledgeEntry` 由 heng `knowledge-sync`(`vault-parser.ts`)从 vault L1/business_view 投影,**活数据**(2026-06-28 实测 1260 条,今晨刚刷)。

### 1.1 已复现 bug
选「虚拟电厂」→ 点山东:地图 hover 显示"5 政策",钻取面板却显示「当前已选主题在该省暂无政策」。计数对、清单空。

### 1.2 根因:两处没对齐 L2/L1 标准

**(G1)region 全名 vs 简称不一致 + name 本身不可靠** —— 工程层 region 标准是 L1 结构化 `{level, code, name}`,**`code`(adcode)才是 canonical 键**,`name` 是展示文本且会被污染。前端却拿 `name` 当简称比:
- `PolicyMap.vue:327` 点击 `emit('select', toShortName(params.name))` → "山东"(简称)。
- `PolicyDashboard.vue:85` `topic.coverage.find(item => item.region === drawerRegion)` 严格相等:`"山东省" === "山东"` → 找不到 → 整行被 `Boolean(row.coverage)` 滤掉 → 假"暂无政策"。
- hover(`PolicyMap.vue:231`)用 `_short`(=raw region "山东省")自比自,侥幸匹配 → 显示 5。
- `PolicyDashboard.vue:145` 又用 `normalizePolicyRegion`(`=toShortName`)归一,与 `:85` 口径**自相矛盾**。

**(G2)theme 没接 L2 theme id** —— 工程层 theme 标准是 `theme id`(`themes_registry.yaml`)+ `business_view.themes`。
- `KnowledgeEntry.themes` **确实存了 L2 id**(`vault-parser.ts:281` `themes: asStringArray(bv.themes)`;山东虚拟电厂 = `["vpp_theme",...]`)。
- 但 `AnalysisTopic` 是另起的 6 主题(cuid 主键 + **中文 keywords**),`policyCoverageWhere` 用 `title/summary/... ILIKE '%虚拟电厂%'` 文本命中;其中虽有一条 `themes array_contains [token]`,但 token=中文、themes=id → **永不命中、形同虚设**。大盘实际走"关键词文本匹配",**忽略 L2 canonical theme 字段**。

### 1.3 region 实测形态(全量 1241 篇 L1,2026-06-28)

| 维度 | 实测 | 结论 |
|---|---|---|
| `level` 取值 | 省 874 / 国家 205 / 市 133 / 区 25 / 县 4(**中文**,非 enum) | 需映射到 country/province/city/district |
| `code`(adcode) | **present 1201(97%)/ absent 40**;前缀干净(11京/31沪/37鲁/44粤…),`00`=国家级≈194 | **adcode 是可靠匹配键** |
| `name` | 干净省名 823 / **污染或非省名 418(34%)** | **name 不可作匹配键** |

`name` 污染样本:`天津市市场监督管理局`(发文机构混入)、`浦东新区`(裸区名、**无省前缀**)、`深圳市光明区`(地级市非 34 省级)、`全国`。**按全名前缀归省会在 34% 数据上翻车;adcode 前 2 位定省、前 4 位定市,对所有形态(直辖市/自治区/省直辖县级市/区县)都成立。**

### 1.4 adcode 丢失点(关键)
adcode 在 L1 frontmatter 有(`region.code`),但 heng 两个入库口都**只取 name+level、丢了 code**:
- `vault-parser.ts:172-173`(→ `KnowledgeEntry`,**大盘读这个**):`region: region.name` / `regionLevel: region.level`。
- `services/policy-pipeline/.../policy_mapper.py:71-72`(→ `Policy`,大盘不读):同样只 name+level。

→ 要让 region 稳,**必须在 `vault-parser` 把 `region.code` 带进 `KnowledgeEntry.adcode`([DB-MIGRATION],加可空列)**。`Policy.adcode` 是另一条线(属地大盘 / POP-B),本次不动(§4 注)。

---

## 2. POP 消化结论(`ZaynShao/pop-policy-one-piece`)

POP 是设计领先的同源前身(NestJS+React),只取其**设计逻辑**,不照搬代码(heng 是 NestJS+Vue)。

### 2.1 借鉴(adopt)
| POP 设计 | 出处 | 本 spec 采纳为 |
|---|---|---|
| **region 以 6 位 adcode 为主键**,前 2 位=省、前 4 位=市;`cityNameToCode` 用 `slice(0,2)` 前缀过滤 | `region.entity.ts` / `region-names.ts:81-89` | C2 adcode 解析规则 |
| **code→name / code→center 查表**,ECharts `series.name = regionCodeToName(code)`,匹配走 code 不走字符串相等 | `region-names.ts` / `region-centers.ts` | C2 前端 `regions.ts` 改 adcode 键 |
| **RegionLevel 枚举** country/province/city/district + 下钻按 `parentCode` | `region.entity.ts:13-18` | C3 形态分级(heng 用 adcode 前缀替代 parent 表,更轻) |
| **直辖市特殊处理**:省级 geojson 是区级、无整体 entry,硬编码 4 直辖市 | `geojson-cities.ts` | C3 上海→崇明区 钻取 |

### 2.2 不采纳(reject / N/A)—— 重要
| POP 设计 | 为什么不搬 |
|---|---|
| **theme→policy 用 mock**(`mockPolicyAnalysis` djb2 造数)+ `theme_coverage` 预计算落表 | heng 有**活数据** `KnowledgeEntry.themes` 可直接 id-join,**比 POP 的 mock 更强**;引预计算表反而要维护同步、易过期。**C1 保持实时 id-join,不建 coverage 表。** |
| **theme 是可 CRUD 的一等实体**(status/template/RBAC,central_ga 建主题) | heng 主题来自工程层 registry,用户已定"严格跟表走";`KnowledgeTheme` 表(=registry 投影)即只读来源,**无需 CRUD**。 |
| **RegionScope 枚举**(nationwide/all_provinces/specific) | 语义不错但非必需;L1 `level=国家` 已等价 nationwide。**可选增强,本次不引。** |
| **完整 RegionEntity 表 + parent 自引用** | heng 数据量/形态用 **adcode 前缀**即可解析省/市,无需新建区划主表。**保持简单。** |

**一句话:POP 在 region 结构化上领先(adcode 为键)→ 采纳;在 theme 匹配上反而是 mock/演示级 → heng 活数据更优,不退回。**

---

## 3. 目标

把政策大盘的 **theme 匹配** 与 **region 映射** 全改为以工程层 L2/L1 标准为准:
- theme:直连 L2 `theme id`(registry),去掉中文关键词映射这层脆弱点。
- region:把 L1 `code`(adcode)带进库,以 adcode 做省级归并与按形态钻取;`name` 仅作展示/兜底。

---

## 4. 设计

### C1 — 主题直连 L2 theme id(零 schema 改动)
- **主题来源**:大盘主题列表改读 `KnowledgeTheme` 表(= `themes_registry` 投影,id + name(zh) + aliases + count)。当前 registry 13 个 id:`v2g / vpp_theme / energy_storage_theme / gas_station_transition_theme / equipment_renewal_theme / green_power_trading_theme / charging_infra / power_market / carbon_market_theme / petroleum_retail_compliance / residential_charging / distribution_grid_opening / aggregator_access`。展示用 zh,匹配用 id。
- **匹配口径**:coverage 改为 `KnowledgeEntry.themes array_contains [<theme_id>]`,**删除** `title/summary/issuer/... ILIKE 关键词` 整套(`policyCoverageWhere` 重写为 theme-id + date + adcode 条件)。
- **AnalysisTopic 废弃**(§6①):大盘不再读它;`policyCoverageTokens` 删除。调色板按 theme 数扩展(13 色或按 hash 取色)。
- **影响**:命中从"关键词文本(含正文顺带提及,偏宽)"变为"canonical theme(偏准)",计数会变(见 C4)。

### C2 — region 以 adcode 为键的完整字段映射([DB-MIGRATION])
- **带 adcode 进库**:
  - `vault-parser.ts`:`VaultEntry` 加 `adcode: string|null`;`loadRawMeta` 从 `region.code` 取(对象形态:`region.code`)。
  - `KnowledgeEntry` schema 加 `adcode String?`([DB-MIGRATION],可空、加索引 `@@index([adcode])`);`knowledge-sync` 用 `...e` 透传,下次 sync 自动回填全量。
- **省级真值表**(前后端共用,取自《行政区划规范参考》§1):34 行 = `adcode2(前2位) / 全名 / 简称 / 中心点 / 形态(省|直辖市|自治区)`。前端 `utils/regions.ts` 由"简称表"扩成此表,**键用 adcode2**。
- **region → 省级 解析规则**(优先级):
  1. 有 adcode → `adcode.slice(0,2)` 查真值表定省级(最可靠)。`00` 前缀 / `level=国家` → **全国(不归任何单省)**,见 §6②。
  2. 无 adcode(40 条)→ `name` 最长前缀兜底匹配省全名;仍无 → 归"未知/全国"桶,不污染省级统计。
- **前端口径统一**:钻取/抽屉/hover/regionHits **全部归一到同一 region key = 省级全名**(由 adcode2 → 真值表全名得到,与 geojson 全名天然对齐);删除 `PolicyMap.vue:327` 的 `toShortName`,消除 `PolicyDashboard.vue:85`(严格相等)与 `:145`(normalize)的矛盾。匹配走 adcode/全名,不再做全名 vs 简称字符串相等。

### C3 — 钻取按行政区形态分级(adcode 前缀)
- **省级聚合上卷**:coverage 在省级 groupBy 时,把区县级 entry 按 `adcode.slice(0,2)` 上卷省级;省级地图数 = 该省(含下辖各级)命中总数。
- **第二级按形态**(《规范参考》§2.5,用 `adcode.slice(0,4)` 解析):普通省→地级市;**直辖市→市辖区**(上海点开出"崇明区"等,adcode 前缀 31);自治区→地级市+自治州+盟(内蒙古)+地区(西藏/新疆)。
- 现 `PolicyMap.vue:97` 的"确定性哈希散布到城市"是**演示假分布**,用真实 adcode 前 4 位的区县级 region 替代。
- 第二级在数据上可行(实测 市133+区25+县4=162 篇带市/区级 adcode)。

### C5 — 国家级/全国政策独立呈现(用户定 §7⑤)
- adcode 前缀 `00` / `level=国家`(205 篇,16.5%)= **全国政策**,不归任何单省、不进省级 choropleth。
- 大盘地图旁出**"全国 N 条"面板/徽标**(≈ POP `RegionScope.Nationwide`);点开列该主题的全国政策清单。
- `knowledgeCoverageByRegion` 把全国桶单列返回(`region: "全国"` 或独立字段),前端单独渲染。

### C4 — coverage 计数口径变化(必须评估)
- region:原按 `name` 原值 groupBy(区县级/污染名散开)→ 新按 adcode 上卷省级(省级数变全/变大,污染名归位)。
- theme:原关键词 ILIKE(偏宽)→ 新 theme-id 命中(偏准),多数主题命中数会变小。
- **交付前给新旧对比**:对几个代表主题×省跑新旧两套 SQL,列数字差异,经用户确认口径可接受再上(§6③已认可口径变严,仍出对比)。

---

## 5. 影响范围 / 改动清单

| 文件 | 改动 | 模块 |
|---|---|---|
| `services/policy-pipeline/scripts/sync/run_sync.py` | `collect_policy_rows` 从 `reg.get("code")` 取 adcode 入 core | pipeline(自有线) |
| `services/policy-pipeline/scripts/sync/policy_mapper.py` | `map_policy_row` 带 `adcode` 字段 | pipeline(自有线) |
| `services/policy-pipeline/scripts/sync/pg_writer.py` | `build_policy_upsert` INSERT/UPDATE 含 `adcode` 列 | pipeline(自有线) |
| `services/heng-guan/backend/src/knowledge/vault-parser.ts` | `VaultEntry` 加 `adcode`;`loadRawMeta` 取 `region.code` | heng-backend |
| `services/heng-guan/backend/prisma/schema.prisma` + 迁移 | `KnowledgeEntry` + `Policy` 各加 `adcode String?` + 索引 **[DB-MIGRATION]** | heng-backend |
| `services/heng-guan/backend/src/dashboard/dashboard.service.ts` | `policyCoverage`/`policyCoverageWhere`/`knowledgeCoverageByRegion` 重写:theme-id join + adcode 省级上卷 + 全国桶单列;删 `policyCoverageTokens`/AnalysisTopic 读取 | heng-backend |
| `services/heng-guan/backend/src/dashboard/region-codes.ts`(新) | 省级真值表(adcode2→全名/简称)+ `isNational`/`resolveProvince` 解析 | heng-backend |
| `services/heng-guan/frontend/src/api/dashboard.ts` | 类型加 `adcode`/`regionLevel`(policies)、`themeId`、`national` | heng-frontend |
| `services/heng-guan/frontend/src/views/dashboard/PolicyDashboard.vue` | region 全名匹配;抽屉清单改走后端 `coverage.policies`(与计数同源,详情按 pid 补全富字段);全国面板 | heng-frontend |
| `services/heng-guan/frontend/src/components/dashboard/PolicyMap.vue` | `regionHits`/`emit`/tooltip 全名口径;钻取按 geojson feature adcode 落真实市/区(替代假哈希) | heng-frontend |

> **实测后未改**:`regions.ts`(已含 `provinceByFullName`+adcode,够用)、`policyTopicRelevance.ts`(/policy 主题分析页共用,不动);故大盘 region 解析放后端 `region-codes.ts`,前端复用 geojson 全名。
> **范围(用户定 §7⑥ = KnowledgeEntry + Policy 都加 adcode)**:`Policy.adcode` 经 pipeline 写入,顺带对齐属地大盘(POP-B);本次大盘只读 `KnowledgeEntry`,`Policy` 侧为对齐附带(`overview()` 暂不改)。
> **AnalysisTopic 表结构**仅停用读取(`/analysis` API + `/policy` 页仍在用),**不删表**,避免破坏性迁移。
> **跨 owner**:pipeline(自有线)+ heng-backend + heng-frontend → 一个 **`[CROSS-MODULE]` + `[DB-MIGRATION]`** PR,@ heng 前后端两 owner(§7④)。

---

## 6. 验证方案

1. **山东 + 虚拟电厂**:钻取应出 5 条(含《山东省促进虚拟电厂高质量发展方案》2026-03-27)。
2. **直辖市**:上海 + 任意主题,钻取出**区级**(崇明区等),不报"暂无"。
3. **自治区**:内蒙古/广西/新疆,省级与下辖(含盟/州/地区)正确。
4. **省直辖县级市**:济源相关政策按 adcode 归到河南省。
5. **污染名归位**:`江苏省市场监督管理局`(320000)按 adcode 归江苏;`浦东新区`/`深圳市光明区` 按 adcode 归上海/广东。
6. **口径对比表**:新旧 coverage 数(theme-id vs 关键词;adcode 上卷 vs name 原值)对照,无异常缩水。
7. 浙江 + 充电基础设施仍为 0(真无数据,回归对照)。

### 6.1 已验证(2026-06-28 实现时)
- **pipeline pytest**:`tests/sync` 全绿(36 passed;policy_mapper/pg_writer/run_sync 带 adcode)。
- **迁移 up/down**:本地 throwaway postgres 跑通——加列+索引、可写带 adcode 行、回滚后 0 残留。
- **后端 `nest build`**:exit 0(theme-id join + adcode 上卷 + 全国桶通过类型检查)。
- **前端 `vue-tsc + vite build`**:exit 0。
- **C4 真数据口径对比**(对 vault 全量模拟新口径):
  - **虚拟电厂(vpp_theme)新口径**:命中 19 省 + 全国桶 6,省级合计 34;**★ 山东省 = 5 条**(含《山东省促进虚拟电厂高质量发展方案》),与用户 hover 的 5 一致 → 钻取不再"暂无政策"。旧口径(关键词 title 近似 + raw-name groupby)山东 raw 桶仅 2,且按污染名散开。
  - **充电基础设施(charging_infra)新口径**:命中 17 省 + 全国桶 8;山东 = 0(与浙江=0 同为真无数据,回归对照通过)。
- **未本地验证(需全栈 + 服务器活数据)**:浏览器端实际渲染、钻取上海→崇明区的地图交互。PR 描述给手动验证步骤;迁移 + 重新 knowledge-sync 后,KnowledgeEntry.adcode 回填即生效。

---

## 7. 开放问题

### 已定(2026-06-28 用户)
1. **AnalysisTopic** → **废弃**,主题直接用 `themes_registry`(经 `KnowledgeTheme` 表)。
2. **展示哪些主题** → **严格跟 registry 表走**;表扩展则大盘随之扩展(当前 13 个,调色板需随之扩展)。
3. **coverage 口径变严** → **认可**(实现时仍出新旧对比)。
4. **PR 拆分** → **一个 `[CROSS-MODULE]`(+`[DB-MIGRATION]`)PR @ heng 前后端两 owner**。

### 已定(消化 POP 后,2026-06-28 用户)
5. **国家级/全国政策(205 篇)** → **(a) 单独"全国 N 条"面板**(见 C5,≈ POP `RegionScope.Nationwide`)。
6. **adcode 迁移范围** → **`KnowledgeEntry` + `Policy` 都加 adcode**(顺带对齐属地大盘 POP-B);本次 PR 接受 [DB-MIGRATION]。

---

## 8. 回滚
- 前端部分:revert 对应 commit。
- 后端 coverage 逻辑:revert 即回旧口径(关键词 + name groupBy)。
- `KnowledgeEntry.adcode` 列:加列是**可空、非破坏性**;回滚保留空列或 `DROP COLUMN adcode`(附回滚 SQL)。`vault-parser` 改动 revert 后下次 sync 不再写 adcode,列留空不影响旧逻辑。
