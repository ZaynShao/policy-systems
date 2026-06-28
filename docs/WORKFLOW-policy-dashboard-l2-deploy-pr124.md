# 政策大盘对齐 L2(PR #124)上线 + adcode 回填 Handoff

> 配套 PR:[gloriahao0909/safety-platform#124](https://github.com/gloriahao0909/safety-platform/pull/124)(`[CROSS-MODULE][DB-MIGRATION]`)
> 设计正本:`docs/specs/2026-06-28-policy-dashboard-l2-alignment-design.md`
> 适用:heng 模块 owner / 部署人。**前提:PR #124 已 review 通过并 merge 到 master。**

---

## 0. TL;DR(三步)

1. **重建 heng**:`git pull` → 重建后端(`prisma db push` 自动加 `adcode` 列 + `nest build`)+ 重建前端(`VITE_BASE=/heng/ vite build`)。
2. **回填 adcode**:触发一次 **knowledge-sync**(大盘读 `KnowledgeEntry`,**必做**)+ 一次 **run_sync**(`Policy`,属地大盘,选做)。
3. **验证**:大盘选「虚拟电厂」点山东 → 应出 **5 条**;上海钻取出区级;全国政策面板有数;浙江+充电仍 0。

> ⚠️ **只重启后端不会回填**:`onModuleInit` 只注册 cron、不开机即同步。adcode 列加上后是空的,必须跑一次 sync 才有值。

---

## 1. 环境速查

| 项 | 值 |
|---|---|
| 生产 heng 主机 | `10.190.55.228`(见 `docs/DEPLOY-PER-MODULE.md`);活数据系统亦可经 `8.216.59.173` 访问 —— **以实际生产机为准** |
| 代码路径 | `/root/projects/safety-platform`(裸进程部署,见 `scripts/manage.sh`) |
| heng-backend | NestJS,端口 3000,产物 `dist/src/main.js` |
| heng-frontend | Vue 静态,部署到 nginx `.web/heng/` |
| heng DB | `127.0.0.1:5432/hengguan`(user `heng` / 密码 `guan`) |
| knowledge-sync cron | `KNOWLEDGE_SYNC_CRON`,默认 `0 0 3 * * *`(Asia/Shanghai 次日 03:00) |
| knowledge-sync vault | `KNOWLEDGE_VAULT_DIR`(未设则内部 vault);该 vault 的 L1 已含 `region.code` |

---

## 2. Step 1 — 重建 heng(应用 adcode 列 + 新代码)

按 `docs/DEPLOY-PER-MODULE.md` §3.3 的标准 heng 部署流程做即可,**本 PR 无额外构建步骤**,只需注意:

- **schema 应用方式 = `prisma db push --accept-data-loss`**(`scripts/manage.sh` `run_heng_prisma_db_push`)。`adcode` 是**可空、新增列 + 索引**,additive,`--accept-data-loss` 对它**无数据风险**。
  - 本项目走 `db push`,**不走** `prisma migrate deploy`;PR 里的 `prisma/migrations/20260628120000_policy_knowledge_adcode/migration.sql` 仅作 **DDL 记录/审计**,部署时由 `db push` 按 schema 自动加列。
- 后端必须重新 `nest build`(新 `dashboard.service` / `region-codes.ts` / `vault-parser`)。
- 前端必须 `VITE_BASE=/heng/ npx vite build` 后 `cp` 到 `.web/heng/`(漏 `VITE_BASE=/heng/` 会 chunk 404)。

参考命令(以仓内 SOP 为准):

```bash
ssh root@<生产机> 'cd /root/projects/safety-platform && git pull'
# 后端:install 流程内含 prisma generate + db push(加 adcode 列)+ nest build + 重启
ssh root@<生产机> 'cd /root/projects/safety-platform && ./scripts/manage.sh install'   # 或按 DEPLOY-PER-MODULE §3.3 手动重建后端+前端
```

**验证列已加**(任一只读连库方式):

```sql
SELECT table_name, column_name
FROM information_schema.columns
WHERE column_name = 'adcode' ORDER BY 1;   -- 应见 KnowledgeEntry.adcode / Policy.adcode
```

---

## 3. Step 2 — 回填 adcode

### 3a. KnowledgeEntry.adcode(大盘直接读,**必做**)

knowledge-sync 会重新解析 vault L1(已含 `region.code`),把 `adcode` 写进 `KnowledgeEntry`。触发其一:

- **手动(推荐,立即生效)**:用 **MANAGER 账号**触发同步(知识库页的「同步」按钮,或带认证调):
  ```
  POST /heng/api/knowledge/sync/run      # 需登录态 role=MANAGER,返回 202
  GET  /heng/api/knowledge/sync/status   # 轮询;看 lastSuccess.finishedAt 更新、syncing=false
  ```
- **或等 cron**:默认次日 `03:00`(Asia/Shanghai)自动跑一次。

> 不需要、也不应直接改库写 adcode —— 让 sync 从 vault 派生,保证口径一致。

### 3b. Policy.adcode(属地大盘 / Policy,选做)

大盘**不读** `Policy`,此步只为顺带对齐属地大盘(POP-B)。由 pipeline `run_sync` 投影(等 pipeline service tick,或手动):

```bash
DATABASE_URL='postgres://heng:guan@127.0.0.1:5432/hengguan' \
  python3 -m scripts.sync.run_sync \
  --vault '<energy-policy-analysis vault 检出路径>' \
  --state-dir state/service --pipeline-version 1
# 在 services/policy-pipeline/ 下执行
```

---

## 4. Step 3 — 验证

### 4a. 数据层(SQL,只读)

```sql
-- adcode 回填覆盖率(应 ≈ 97%,少量 L1 无 code 属正常)
SELECT count(*) FILTER (WHERE adcode IS NOT NULL) AS with_adcode, count(*) AS total
FROM "KnowledgeEntry";

-- 山东 虚拟电厂(370000* + themes 含 vpp_theme),近 1 年应有 5 条
SELECT pid, title, adcode
FROM "KnowledgeEntry"
WHERE "themes" @> '["vpp_theme"]' AND adcode LIKE '37%'
ORDER BY importance DESC;
```

### 4b. 大盘交互(浏览器,`/heng/dashboard/policy`)

- [ ] 选「虚拟电厂」→ 点**山东** → 钻取面板出 **5 条**(含《山东省促进虚拟电厂高质量发展方案》),不再「暂无政策」。
- [ ] 点**上海** → 钻取出**区级**(崇明区等),tooltip 显示真实计数。
- [ ] 右侧出现「**全国政策 N 条**」面板,点开是全国性政策清单。
- [ ] 回归:**浙江 + 充电基础设施 = 0**(真无数据,正常)。
- [ ] 主题列表 = registry 全量(当前 13 个),不再是旧 6 个。

---

## 5. 回滚

- **代码**:`git revert` PR #124 的 merge commit → 重建 heng(同 Step 1)。`dashboard.service` 回旧逻辑(关键词 + name groupby)。
- **adcode 列**:加列是**可空、非破坏性**。回滚代码后:
  - 留着空列**无害**(旧逻辑不读 adcode),推荐**不动**;
  - 如需彻底清除:
    ```sql
    DROP INDEX IF EXISTS "Policy_adcode_idx";
    DROP INDEX IF EXISTS "KnowledgeEntry_adcode_idx";
    ALTER TABLE "Policy" DROP COLUMN IF EXISTS "adcode";
    ALTER TABLE "KnowledgeEntry" DROP COLUMN IF EXISTS "adcode";
    ```
    > 注意:回滚后再跑 heng `db push` 会按当时 schema 同步;若 schema 已回退,列会被 db push 自动清掉。

---

## 6. 陷阱清单

- **重启 ≠ 回填**:加列后必须跑一次 knowledge-sync,否则 adcode 全空、大盘 region 解析退回 name 兜底(34% 不准)。
- **`VITE_BASE=/heng/`**:前端构建必带,否则 `/assets/...` 404、「公共事务打不开」。
- **后端重启 502**:`/heng/api/*` 短暂 502,刷新即恢复。
- **db push 语义**:同步到 schema.prisma;若线上库与 schema 有其他 drift,`--accept-data-loss` 可能动到那些 drift —— 与本 PR 无关,但部署人留意既有 SOP。
- **migration.sql 不参与部署**:本项目用 `db push`,迁移文件仅审计;别去手动 `prisma migrate deploy`。
