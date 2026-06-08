-- CreateEnum
CREATE TYPE "L1ReviewKind" AS ENUM ('gate', 'checkpoint', 'sweep', 'fetch_fail');

-- CreateTable
CREATE TABLE "L1ReviewQueue" (
    "id" TEXT NOT NULL,
    "dedupeKey" TEXT NOT NULL,
    "pipelineKind" "L1ReviewKind" NOT NULL,
    "pipelineRef" TEXT NOT NULL,
    "reason" TEXT,
    "suggestedAction" TEXT,
    "confidence" DOUBLE PRECISION,
    "evidence" TEXT,
    "channel" TEXT,
    "runLabel" TEXT,
    "aiNarration" TEXT,
    "aiNarratedAt" TIMESTAMP(3),
    "verdict" TEXT,
    "corrections" JSONB,
    "reviewer" TEXT,
    "note" TEXT,
    "verdictAt" TIMESTAMP(3),
    "syncedBack" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "L1ReviewQueue_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "L1ReviewQueue_dedupeKey_key" ON "L1ReviewQueue"("dedupeKey");

-- CreateIndex
CREATE INDEX "L1ReviewQueue_verdict_idx" ON "L1ReviewQueue"("verdict");

-- CreateIndex
CREATE INDEX "L1ReviewQueue_pipelineKind_idx" ON "L1ReviewQueue"("pipelineKind");
