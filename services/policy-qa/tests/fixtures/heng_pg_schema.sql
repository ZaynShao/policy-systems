-- 按 services/heng-guan/backend/prisma/schema.prisma 复刻 policy-qa 会读到的部分。
-- Prisma 的 Json → jsonb,DateTime → timestamp(3),String → text。
CREATE TYPE "PolicyImportance" AS ENUM ('STRATEGIC', 'MAJOR', 'GENERAL', 'INFO');
CREATE TYPE "PolicySource" AS ENUM ('PIPELINE', 'MANUAL');
CREATE TYPE "InterpretStatus" AS ENUM ('PENDING', 'DONE');

CREATE TABLE "Policy" (
  "id"                 text PRIMARY KEY,
  "title"              text NOT NULL,
  "docNumber"          text,
  "issuer"             text NOT NULL,
  "issueDate"          timestamp(3) NOT NULL,
  "effectiveDate"      timestamp(3),
  "content"            text NOT NULL,
  "source"             "PolicySource" NOT NULL DEFAULT 'PIPELINE',
  "sourceUrl"          text,
  "contentHash"        text UNIQUE,
  "importance"         "PolicyImportance" NOT NULL DEFAULT 'GENERAL',
  "region"             text,
  "level"              text,
  "adcode"             text,
  "interpretStatus"    "InterpretStatus" NOT NULL DEFAULT 'PENDING',
  "createdAt"          timestamp(3) NOT NULL DEFAULT now(),
  "updatedAt"          timestamp(3) NOT NULL DEFAULT now(),
  "pipelinePid"        text UNIQUE,
  "pipelineVersion"    integer,
  "pipelineScores"     jsonb,
  "pipelineThemes"     jsonb,
  "pipelineImpact"     text,
  "syncedAt"           timestamp(3),
  "importanceOverride" "PolicyImportance",
  "themeOverrides"     jsonb
);

CREATE TABLE "PolicySemanticRelation" (
  "id"              text PRIMARY KEY,
  "fromPolicyId"    text NOT NULL REFERENCES "Policy"("id") ON DELETE CASCADE,
  "toPolicyId"      text NOT NULL REFERENCES "Policy"("id") ON DELETE CASCADE,
  "relationType"    text NOT NULL,
  "confidence"      double precision,
  "evidence"        text,
  "pipelineVersion" integer,
  "createdAt"       timestamp(3) NOT NULL DEFAULT now()
);

CREATE TABLE "CommentarySignal" (
  "id"                text PRIMARY KEY,
  "commentaryId"      text NOT NULL UNIQUE,
  "title"             text NOT NULL,
  "evidence"          text,
  "signalRole"        text,
  "confidence"        double precision,
  "sourceAccount"     text,
  "businessTag"       text,
  "themeIds"          jsonb,
  "relatedPolicyPids" jsonb,
  "sourcePath"        text,
  "pipelineVersion"   integer,
  "syncedAt"          timestamp(3),
  "createdAt"         timestamp(3) NOT NULL DEFAULT now()
);

INSERT INTO "Policy" (
  "id", "title", "docNumber", "issuer", "issueDate", "content", "sourceUrl",
  "importance", "region", "level", "adcode", "pipelinePid", "pipelineScores",
  "pipelineThemes", "pipelineImpact", "syncedAt"
) VALUES
(
  'c1', '关于加快充电基础设施建设的通知', '发改能源〔2026〕1号', '国家发展改革委',
  '2026-06-01 00:00:00', '正文一。要求2026年底前建成充电桩10万个。',
  'https://example.invalid/1', 'MAJOR', '全国', '国家', NULL, 'P_2026_NDRC_1',
  '{"D1": 4, "importance": 8}'::jsonb,
  '[{"id": "charging", "isPrimary": true}]'::jsonb,
  '{"充电": "直接利好充电业务。", "加油": "未直接涉及。"}',
  '2026-06-08 09:07:47.762'
),
(
  'c2', '浙江省分时电价机制通知', '浙发改价格〔2026〕21号', '',
  '2026-05-20 00:00:00', '正文二。峰谷价差扩大。',
  NULL, 'GENERAL', '浙江省', '省', '330000', 'P_2026_ZJ_21',
  NULL, NULL, '{"电力_储能_V2G_交易": "峰谷价差扩大利好储能。"}',
  '2026-06-08 09:07:47.762'
),
(
  'c3', '财政部 税务总局关于新能源车船税的公告', '财税〔2026〕7号', '',
  '2026-04-10 00:00:00', '正文三。', NULL, 'INFO', NULL, NULL, NULL,
  'P_2026_MOF_7', NULL, NULL, NULL, '2026-06-08 09:07:47.762'
),
-- 手工录入行:pipelinePid 为 null,所有查询都必须排除它
(
  'c4', '手工录入的政策', NULL, '某机关', '2026-07-01 00:00:00', '正文四.',
  NULL, 'INFO', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL
);

INSERT INTO "PolicySemanticRelation"
  ("id", "fromPolicyId", "toPolicyId", "relationType", "confidence", "evidence")
VALUES ('r1', 'c1', 'c2', 'references', 0.9, '证据句一。');

INSERT INTO "CommentarySignal"
  ("id", "commentaryId", "title", "evidence", "signalRole", "confidence",
   "sourceAccount", "businessTag", "relatedPolicyPids")
VALUES ('s1', 'CM_1', '评论一', '评论证据。', 'opportunity', 0.7,
        '某公众号', '充电', '["P_2026_NDRC_1"]'::jsonb);
