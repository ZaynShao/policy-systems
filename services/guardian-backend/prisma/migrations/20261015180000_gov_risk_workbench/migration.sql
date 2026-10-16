-- 工单系统性原因研判(个人工作台 pending-gov-risk):本地上传的脱敏工单、研判运行、结果包、所有者跟进。
-- 五张新表,不改动任何已有表。
-- 回滚:DROP TABLE "gov_risk_feedback"; DROP TABLE "gov_risk_packages"; DROP TABLE "gov_risk_runs"; DROP TABLE "gov_risk_datasets"; DROP TABLE "gov_risk_cases";

-- CreateTable
CREATE TABLE IF NOT EXISTS "gov_risk_cases" (
    "id" SERIAL NOT NULL,
    "owner" VARCHAR(64) NOT NULL,
    "caseId" VARCHAR(16) NOT NULL,
    "channel" VARCHAR(16) NOT NULL,
    "occurredAt" TIMESTAMP(3) NOT NULL,
    "payload" JSONB NOT NULL,
    "judgmentKey" VARCHAR(64),
    "judgment" JSONB,
    "uploadId" VARCHAR(64) NOT NULL,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "gov_risk_cases_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE IF NOT EXISTS "gov_risk_datasets" (
    "owner" VARCHAR(64) NOT NULL,
    "uploadId" VARCHAR(64) NOT NULL,
    "caseCount" INTEGER NOT NULL,
    "meta" JSONB NOT NULL DEFAULT '{}',
    "uploadedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "gov_risk_datasets_pkey" PRIMARY KEY ("owner")
);

-- CreateTable
CREATE TABLE IF NOT EXISTS "gov_risk_runs" (
    "id" SERIAL NOT NULL,
    "owner" VARCHAR(64) NOT NULL,
    "trigger" VARCHAR(16) NOT NULL,
    "status" VARCHAR(16) NOT NULL,
    "progress" JSONB NOT NULL DEFAULT '{}',
    "stats" JSONB,
    "error" VARCHAR(500),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "startedAt" TIMESTAMP(3),
    "finishedAt" TIMESTAMP(3),

    CONSTRAINT "gov_risk_runs_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE IF NOT EXISTS "gov_risk_packages" (
    "id" SERIAL NOT NULL,
    "owner" VARCHAR(64) NOT NULL,
    "schema" VARCHAR(32) NOT NULL,
    "payload" JSONB NOT NULL,
    "sizeBytes" INTEGER NOT NULL,
    "uploadedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "gov_risk_packages_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE IF NOT EXISTS "gov_risk_feedback" (
    "owner" VARCHAR(64) NOT NULL,
    "revision" INTEGER NOT NULL DEFAULT 0,
    "payload" JSONB NOT NULL DEFAULT '{}',
    "updatedBy" VARCHAR(64),
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "gov_risk_feedback_pkey" PRIMARY KEY ("owner")
);

-- CreateIndex
CREATE INDEX IF NOT EXISTS "gov_risk_cases_owner_uploadId_idx" ON "gov_risk_cases"("owner", "uploadId");

-- CreateIndex
CREATE UNIQUE INDEX IF NOT EXISTS "gov_risk_cases_owner_caseId_key" ON "gov_risk_cases"("owner", "caseId");

-- CreateIndex
CREATE INDEX IF NOT EXISTS "gov_risk_runs_owner_id_idx" ON "gov_risk_runs"("owner", "id");

-- CreateIndex
CREATE INDEX IF NOT EXISTS "gov_risk_packages_owner_uploadedAt_idx" ON "gov_risk_packages"("owner", "uploadedAt");

