-- CreateTable
CREATE TABLE "CommentarySignal" (
    "id" TEXT NOT NULL,
    "commentaryId" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "evidence" TEXT,
    "signalRole" TEXT,
    "confidence" DOUBLE PRECISION,
    "sourceAccount" TEXT,
    "businessTag" TEXT,
    "themeIds" JSONB,
    "relatedPolicyPids" JSONB,
    "sourcePath" TEXT,
    "pipelineVersion" INTEGER,
    "syncedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "CommentarySignal_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "CommentarySignal_commentaryId_key" ON "CommentarySignal"("commentaryId");

-- CreateIndex
CREATE INDEX "CommentarySignal_businessTag_idx" ON "CommentarySignal"("businessTag");

-- CreateIndex
CREATE INDEX "CommentarySignal_signalRole_idx" ON "CommentarySignal"("signalRole");
