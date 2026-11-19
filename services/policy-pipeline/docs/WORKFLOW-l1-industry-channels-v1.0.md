# WORKFLOW · L1 工信渠道补齐 v1.0

## 1. 需求澄清

- 目标用户:政策分析 pipeline 运营者与后续 L1/L2 维护者。
- 场景:新能源汽车、充换电、设备更新等政策常由省级工信厅/经信委/工信局/经信局发布,现有渠道目录没有规范的 `工信` 类型,导致渠道不能稳定进入 L1 扫描和 L2 attribution。
- 本轮范围:在 `services/policy-pipeline/` 内补齐省级 31 省工信类发现目标、registry 类型推断、expand oneshot 接入和对应单测。
- 明确排除:不采政策,不写 vault,不触发生产 cron,不 SSH 部署,不硬编码或打印 Tavily/Firecrawl/LLM/DB 凭据。

## 2. 成功标准

1. `province_industry_targets()` 生成 31 个省级目标,`channel_type=工信`,省级 `city_code` 为真实省级 adcode。
2. `province_targets_from_registry()` 对 `issuer_canonical` 含 `工业和信息化` / `工信` / `经信` 的省级域名推断为 `工信`,不再落 `政府网`。
3. `_institution_match()` 对 `工信` 不误杀域名未知路径下发现的 gov 域名;既有商务/市监/能源监管核验保持不变。
4. `scripts/_oneshot/expand_channels_l1.py` 的 `DISCOVER_LEVELS=industry` 能把工信目标纳入 discovery,并和 registry 目标按 `(province, channel_type)` 合并,已知域名优先。
5. 测试从 `services/policy-pipeline/` 跑 `python3 -m pytest` 通过。

## 3. 设计

- 在 `scripts/l1_collect/channel_discovery.py` 新增 `province_industry_targets()`,沿用 `province_energy_targets()` 的冷启动模式:不预设不可靠域名,由 Tavily + LLM + probe 找真实政策列表页。
- 工信类统一类型名为 `工信`;省经信委、工信局、经信局均归入该类型。
- registry 派生改两处:省级 channel type 推断为 `工信`;`seed_channel_registry.py` 对常见 `gxt/jxt/jxj/...` 省级域名派生工信/经信 issuer_canonical。本轮不直接生成或覆盖 vault `_meta/channel_registry.yaml`。
- `expand_channels_l1.py` 新增 `industry` level,将 registry 中已有工信域名与冷启动目标合并。合并规则保持原有模式:同省同类型时,已有 root_domain 的目标优先。

## 4. 验证计划

- 红测试:
  - `tests/l1_collect/test_channel_discovery.py` 覆盖 31 省工信目标、registry 工信推断、工信机构核验不误杀。
  - `tests/l1_collect/test_expand_channels_l1.py` 覆盖 `industry` level 合并和已知域名优先。
- 绿测试:
  - 先跑新增/受影响测试子集。
  - 最后跑 `python3 -m pytest` 全量。

## 5. 运行与同步

- 本轮不执行真实 `expand/probe --apply`;首跑需要 operator 带凭据在目标环境执行。
- 本轮只做了一条公开网页 probe 作为地面真值:江苏省工信厅 `https://gxt.jiangsu.gov.cn/col/col89736/index.html` 经 `probe_url` 返回 `ok 200 page_has_list_pattern=True`,已作为 `工信` verified 渠道写入 catalog。
- 建议首跑命令:

```bash
cd services/policy-pipeline
DISCOVER_LEVELS=industry python3 -m scripts._oneshot.expand_channels_l1
python3 -m scripts.l1_collect.channel_reprobe --only-types 工信 --apply
```

- 首跑后再执行 `scripts/l2_attribution/seed_channel_registry.py` 派生 registry 草稿,由 operator 人工处理 `needs_manual` 后写 vault。

## 6. 风险与回滚

- 风险:省级工信站点域名不统一,硬编码 `gxt.<province>.gov.cn` 会误导 discovery,所以本轮采用域名未知的冷启动目标。
- 风险:真实 discovery 依赖 Tavily/LLM/probe 网络质量,本轮单测只验证 deterministic 行为。
- 回滚:本轮代码只影响工信目标生成和 expand level;移除新增函数、推断分支和 tests 即可恢复。
