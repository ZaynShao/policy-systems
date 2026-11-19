// 月刊接口(前端)。这个文件原来是同事建的,本仓只收我写的部分,其余是独立版的最小外壳。
//
// 我写的(原项目 PR 1185,原样照搬,下面标「我写的」):新版月刊(monthly.v2)的类型 MonthlyV2Detail、MonthlyCaveat,
// MonthlyContent 里两套 schema 并存的字段,以及提交修改意见的 monthlyApi.revisionNote。
// 外壳(独立版新写,下面标「外壳」):页面要用到的其余类型的最小声明、monthlyApi.list / detail 两个读接口。
// 原文件里同事写的生成、发布、历史版本、AI 对话记录等没有收;MonthlyContent 里同事的两个老字段
// (technologyTrends、summary)也没有收。
import { http } from './client';

// ── 外壳 ──────────────────────────────────────────────────────
export type MonthlyType = 'MONTHLY' | 'TOPIC';
export type MonthlyStatus = 'DRAFT' | 'AUDITING' | 'PUBLISHED' | 'ARCHIVED';

/** 老数据(v1)的详情块。外壳只声明老数据分支用到的几项。 */
export interface MonthlyPolicyBlock {
  no: string;
  title: string;
  info?: string;
  content?: string;
  contentList?: string[];
  focus?: string;
}

// ── 我写的 ────────────────────────────────────────────────────
/** monthly.v2 的详情块。字段是**改名**不是加字段:reading 对应 v1 的 contentList。 */
export interface MonthlyV2Detail {
  no: string;
  /** 已投影为 heng 的 Policy.id;映射不到时是空串,前端就不给链接 */
  policyId?: string;
  /** pipeline 侧的原始 pid,只作溯源 */
  pipelinePid?: string;
  title: string;
  info: string;
  reading: string;
  focus: string;
  advice?: Array<{ business: string; tag: string; text: string }>;
}

export interface MonthlyCaveat {
  gate: string;
  rule?: string;
  severity?: string;
  location: string;
  note: string;
}

/**
 * 两套 schema 并存:老数据无 `schema` 字段走 v1,新产线出 `monthly.v2`。
 * 字段一律可选——已发布的历史刊不会重生成,两边都得渲染得出来。
 */
export interface MonthlyContent { // ← 这一行与末尾的花括号是外壳
  schema?: string;
  // ── v1 ──
  overview?: string;
  quickList?: Array<{ category: string; policyTitle: string }>;
  policyBlocks?: MonthlyPolicyBlock[];
  // ── v2 ──
  month?: string;
  narrative?: string;
  businessTakes?: Array<{ business: string; text: string }>;
  quickTable?: Array<{
    no: string; policy_id?: string; level?: string; score?: string;
    title: string; issuer?: string; date?: string; doc_no?: string;
  }>;
  details?: MonthlyV2Detail[];
  localRoundup?: string;
  appendix?: string;
  uncovered?: string;
  /** 门没过、返修两轮仍有残留的段落。非空时页面顶部出容错提示条。 */
  caveats?: MonthlyCaveat[];
  provenance?: {
    writerModel?: string; packSha?: string; profileId?: string; auditRounds?: number;
  };
  /** 读者提交的修改意见,等下一轮回炉;由产线消费后清空。 */
  pendingNote?: string;
}

// ── 外壳 ──────────────────────────────────────────────────────
export interface MonthlyListItem {
  id: string;
  type: MonthlyType;
  title: string;
  year?: number;
  month?: number;
  coverDate: string;
  publishDate?: string;
  status: MonthlyStatus;
  version: number;
  content: MonthlyContent;
}

export type MonthlyDetail = MonthlyListItem;

export const monthlyApi = {
  list: () => http.get<any, MonthlyListItem[]>('/monthlies'),
  detail: (id: string) => http.get<any, MonthlyDetail>(`/monthlies/${id}`),
  // ── 我写的 ──
  /** 提交人工修改意见。意见存进 content.pendingNote,由产线下一轮回炉时消费。 */
  revisionNote: (id: string, note: string) =>
    http.post<any, { ok: boolean; pendingNote: string }>(`/monthlies/${id}/revision-note`, { note }),
};
