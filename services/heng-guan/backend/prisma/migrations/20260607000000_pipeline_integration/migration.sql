-- AlterTable
ALTER TABLE "Policy" ADD COLUMN     "importanceOverride" "PolicyImportance",
ADD COLUMN     "pipelineImpact" TEXT,
ADD COLUMN     "pipelinePid" TEXT,
ADD COLUMN     "pipelineScores" JSONB,
ADD COLUMN     "pipelineThemes" JSONB,
ADD COLUMN     "pipelineVersion" INTEGER,
ADD COLUMN     "syncedAt" TIMESTAMP(3),
ADD COLUMN     "themeOverrides" JSONB;

-- CreateTable
CREATE TABLE "PolicySemanticRelation" (
    "id" TEXT NOT NULL,
    "fromPolicyId" TEXT NOT NULL,
    "toPolicyId" TEXT NOT NULL,
    "relationType" TEXT NOT NULL,
    "confidence" DOUBLE PRECISION,
    "evidence" TEXT,
    "pipelineVersion" INTEGER,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "PolicySemanticRelation_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ManualEntryRequest" (
    "id" TEXT NOT NULL,
    "submittedUrl" TEXT NOT NULL,
    "submittedTitle" TEXT,
    "submittedBy" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'checking',
    "resultPolicyId" TEXT,
    "feedbackId" TEXT,
    "note" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "ManualEntryRequest_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "L1FeedbackQueue" (
    "id" TEXT NOT NULL,
    "reportedUrl" TEXT NOT NULL,
    "reportedTitle" TEXT,
    "reportedBy" TEXT NOT NULL,
    "expectedChannel" TEXT,
    "l1ScanDate" TIMESTAMP(3),
    "status" TEXT NOT NULL DEFAULT 'pending',
    "reviewNote" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "L1FeedbackQueue_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "PolicySemanticRelation_fromPolicyId_idx" ON "PolicySemanticRelation"("fromPolicyId");

-- CreateIndex
CREATE INDEX "PolicySemanticRelation_toPolicyId_idx" ON "PolicySemanticRelation"("toPolicyId");

-- CreateIndex
CREATE UNIQUE INDEX "PolicySemanticRelation_fromPolicyId_toPolicyId_relationType_key" ON "PolicySemanticRelation"("fromPolicyId", "toPolicyId", "relationType");

-- CreateIndex
CREATE INDEX "ManualEntryRequest_status_idx" ON "ManualEntryRequest"("status");

-- CreateIndex
CREATE INDEX "L1FeedbackQueue_status_idx" ON "L1FeedbackQueue"("status");

-- CreateIndex
CREATE UNIQUE INDEX "Policy_pipelinePid_key" ON "Policy"("pipelinePid");

-- AddForeignKey
ALTER TABLE "PolicySemanticRelation" ADD CONSTRAINT "PolicySemanticRelation_fromPolicyId_fkey" FOREIGN KEY ("fromPolicyId") REFERENCES "Policy"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PolicySemanticRelation" ADD CONSTRAINT "PolicySemanticRelation_toPolicyId_fkey" FOREIGN KEY ("toPolicyId") REFERENCES "Policy"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ManualEntryRequest" ADD CONSTRAINT "ManualEntryRequest_resultPolicyId_fkey" FOREIGN KEY ("resultPolicyId") REFERENCES "Policy"("id") ON DELETE SET NULL ON UPDATE CASCADE;
