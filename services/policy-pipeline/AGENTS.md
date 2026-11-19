# AGENTS.md · policy-pipeline service

本目录是政策分析 pipeline(L1 采集 / L2 派生 / vault→heng-pg 投影),是 safety-platform 的一个 service。
monorepo 级规则以仓根 `AGENTS.md` / `CLAUDE.md` 为准;本文件只列服务自有约定。

## 必读
- `SCHEMA.md` — vault 数据契约。本服务是生产者,持有 **canonical**;vault 仓(`energy-policy-analysis`)留镜像副本,改 SCHEMA 走 PR 时同步那份。
- `OPERATIONS.md` — 运营手册:cron 接线 / 部署 / 更新 / 回滚。
- `docs/runbooks/`(尤其 `s2-vps-cron.md`)— 部署照抄文本 + 验证命令。

## 红线
- **vault 是独立数据仓,不在本仓**:本服务读写的 vault 经 host 卷挂载(`/root/policy-vault`),raw 只增不删。
- **凭据全 env/CLI,零硬编码,绝不入 git**(vault 写 key / LLM key / heng-pg 凭据)。
- 改动走 **TDD**:新功能 / bugfix 先写失败测试(`tests/`,**mock 网络**,不打真网)再实现。
- **部署 / 生产写是 server-ops 红线,须 operator 亲手。**

## 测试
`pytest -q`(testpaths=tests)。
