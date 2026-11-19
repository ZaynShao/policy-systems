# 政策分析 Pipeline

## 独立版:装依赖、跑测试、看链路看板

> 这一节是独立版补的;下面从「能源政策分析项目的工程层」起是原来的说明,原样保留(里面的本机路径是原开发机上的)。

要 Python 3.10 以上。在本目录(`services/policy-pipeline`)下:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # 版本全部钉死;运行依赖与 constraints.txt 同版本
.venv/bin/python -m pytest                      # 全套 1,261 项,十几秒跑完
```

- **测试不联网**:`tests/conftest.py` 在测试期间把网络断掉——往外连、连本机代理、解析外网域名、连 Postgres 都直接报错,
  所以跑测试不会调到大模型、不会碰平台库;各项测试本来就用假连接。
- **有一项要读本机政策库**(`tests/l1_collect/test_channel_discovery.py` 的 `test_province_targets_from_registry`):
  它写死读原开发机上的 `~/Documents/Zayn Main/政策分析/_meta/channel_registry.yaml`。那里没有这份文件就跳过并写明原因;
  设 `VAULT=<政策库克隆目录>` 再跑就照常执行。原项目里也是这样,只在原开发机上能过。
- 2026-11-19 实测(Python 3.10.0):不设 `VAULT` 1,260 项通过、1 项跳过;设了 `VAULT` 1,261 项全过。
  原项目 GitHub 上的 CI 只挑其中 401 项跑(月刊产线、业务口径守卫等几组),全套没进过 CI。
- **链路看板**:`python3 dashboard/build.py` 生成一个双击就能打开的页面,看 L1 采集 → L2 分析 → 政策库 → 四个出口每段的件数、
  守恒巡检结果,政策库条目可搜可筛。说明见 `dashboard/README.md`,演示数据的来历见 `dashboard/data/README.md`。
- 服务器上的部署(`Dockerfile`、`docker-compose.server.yml`、cron)照旧,见 `OPERATIONS.md`;对外只读接口另有
  `docker/corpus.Dockerfile`(fastapi、uvicorn)。

---

能源政策分析项目的**工程层**。数据(政策 raw、派生产物)住在另一个仓:vault。

```
~/Documents/Zayn Main/政策分析/   ← vault(数据 + SCHEMA.md 副本)
~/dev/政策分析-pipeline/           ← 本仓(工程脚本 + SOP + 状态)
~/政策分析-legacy-archive/         ← 已废弃的旧脚本/产物(物理隔离)
```

## 当前阶段

聚焦 **L1 完整采集 + L2 高质量派生**,**L3 渲染(月报 / 决策卡片)不在本阶段范围**。
既存 vault `2_crystallized/_reports/` 历史月报作为数据保留,不再更新。

## 架构层

| 层 | 职责 | 落地 | 当前阶段 |
|---|---|---|---|
| **L1 采集** | 政策发现 / 抓取 / 入库 / 评论关联 | `scripts/l1_collect/` | ✓ 重点 |
| **L2 派生** | 实体 / 关系 / 评分 / 主题结晶 | `scripts/l2_derive/` | ✓ 重点 |
| L3 渲染 | 月报 / 决策卡片 | `scripts/l3_render/`(暂不维护) | — |

## 当前状态

> 详见 `state/STATUS.md`(由 `scripts/audit/dump_status.py` 自动生成)。

## 快速入门

按推荐阅读顺序:

1. **`SCHEMA.md`** — 数据契约。理解 vault 的字段定义。
2. **`CLAUDE.md`** — 反污染纪律。任何在本仓工作的 AI / 人 必读。
3. **`LESSONS.md`** — 建设期踩过的坑。新阶段开始前必读。
4. **`OPERATIONS.md`** — 当前生效的运营手册(SOP 合并版)。
5. **`CHANGELOG.md`** — 本仓的变更记录。

## 为什么分两个仓

历史项目数据与工程混在一个 repo,半年后积累了:
- 27 个 oneshot 脚本
- 11 个 staging 目录
- 30+ 散在 _meta 根的 candidate JSON
- 多份重复的 audit 文件夹
- README / CLAUDE 数字与实际严重不一致

根因是**工程演化污染数据 repo**。本次切分两仓,以 SCHEMA.md 为契约解耦,让两层独立演化。

详细推导见 `LESSONS.md` 与 `docs/`。

## 开发约束

- Oneshot 脚本只能进 `scripts/_oneshot/`,7 天内归档
- 中间产物只能进 `state/`,**不写 vault**
- 文档不引具体路径/脚本名/commit hash(详见 `CLAUDE.md` 反污染纪律)

## License / 性质

内部项目,不开源。
