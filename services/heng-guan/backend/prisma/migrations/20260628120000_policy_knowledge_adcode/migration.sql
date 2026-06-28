-- 政策大盘对齐 L2:把 L1 region.code(GB/T 2260 6位 adcode)带进库,作省级匹配键。
-- 加列均可空、非破坏性;旧逻辑不受影响。下次 pipeline run_sync / knowledge-sync 回填全量。
-- 回滚 SQL 见 PR 描述([DB-MIGRATION])。

-- AlterTable
ALTER TABLE "Policy" ADD COLUMN "adcode" TEXT;

-- AlterTable
ALTER TABLE "KnowledgeEntry" ADD COLUMN "adcode" TEXT;

-- CreateIndex
CREATE INDEX "Policy_adcode_idx" ON "Policy"("adcode");

-- CreateIndex
CREATE INDEX "KnowledgeEntry_adcode_idx" ON "KnowledgeEntry"("adcode");
