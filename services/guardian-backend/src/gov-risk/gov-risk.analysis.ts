import {
  type Candidate,
  type FeedbackEntry,
  type GovRiskCase,
  type Judgment,
  type ReferenceCase,
  type Review,
  JUDGE_BATCH,
  JUDGE_PROMPT_VERSION,
  REVIEW_PROMPT_VERSION,
  REVIEW_TOP_N,
  buildCandidates,
  buildPackage,
  extractJson,
  judgeKey,
  judgeSystemPrompt,
  judgeUserPrompt,
  ms,
  parseJudgeBatch,
  reviewKey,
  reviewSystemPrompt,
  reviewUserPrompt,
  rulesJudgment,
  validateJudgment,
  validateReview,
} from './gov-risk.engine';

/**
 * 一次研判运行:逐条标注(模型,按内容缓存)→ 归并打分 → 高分候选复核(模型)→ 结果包。
 *
 * 模型不可用时不中断:没标注到的工单退回规则兜底,结果包 method 里如实写明多少条是规则判的、
 * 通道坏在哪(欠费、凭证、超时),不冒充模型结论。凭证无效或欠费时立即熔断,后面不再白白请求;
 * 其他错误连续 3 批失败也熔断。每次最多新标注 maxJudge 条(最新的优先),其余下次再标。
 */

export interface ChatMessage {
  role: 'system' | 'user';
  content: string;
}

export interface StoredCase {
  record: GovRiskCase;
  judgmentKey: string | null;
  judgment: Judgment | null;
}

export interface AnalysisDeps {
  llmEnabled: boolean;
  complete(input: { purpose: 'judge' | 'review'; messages: ChatMessage[]; maxTokens: number }): Promise<{ content: string; model: string }>;
  saveJudgment(caseId: string, key: string, judgment: Judgment): Promise<void>;
  progress(p: Record<string, unknown>): Promise<void>;
  now(): number;
  maxJudge: number;
  concurrency?: number;
}

export interface AnalysisInput {
  rows: StoredCase[];
  feedback: Record<string, FeedbackEntry>;
  refs: ReferenceCase[];
  previousPackage: Record<string, unknown> | null;
  dataset: { uploaded_at: string | null; case_count: number };
  run: { id: number; trigger: string };
}

/** 熔断原因:再请求也不会好,继续调只会浪费时间 */
const FATAL = new Set(['ai_not_configured', 'ai_auth_invalid', 'ai_insufficient_balance']);

/** 模型通道失败 → 可行动的原因码(不含密钥和请求内容) */
export function classifyLlmError(error: unknown): string {
  const e = error as { status?: unknown; statusCode?: unknown; code?: unknown; message?: unknown };
  if (e?.code === 'ai_not_configured') return 'ai_not_configured';
  const status = Number(e?.status || e?.statusCode || 0);
  const text = `${e?.code || ''} ${e?.message || ''}`.toLowerCase();
  if (status === 401 || status === 403) return 'ai_auth_invalid';
  if (status === 402 || /insufficient.?balance/u.test(text)) return 'ai_insufficient_balance';
  if (/timeout|timedout|etimedout|abort/u.test(text)) return 'ai_timeout';
  if (status === 429) return 'ai_rate_limited';
  return 'ai_unavailable';
}

async function pool<T>(items: T[], size: number, fn: (item: T) => Promise<void>): Promise<void> {
  let next = 0;
  const workers = Array.from({ length: Math.min(size, items.length) }, async () => {
    while (next < items.length) {
      const item = items[next++];
      await fn(item);
    }
  });
  await Promise.all(workers);
}

function previousReviews(pkg: Record<string, unknown> | null): Map<string, Review> {
  const out = new Map<string, Review>();
  const list = pkg && Array.isArray(pkg.candidates) ? pkg.candidates : [];
  for (const c of list as Array<Record<string, unknown>>) {
    if (typeof c?.review_key === 'string' && c.review && typeof c.review === 'object') out.set(c.review_key, c.review as Review);
  }
  return out;
}

export async function runAnalysis(input: AnalysisInput, deps: AnalysisDeps) {
  const started = deps.now();
  const cases = input.rows.map((r) => r.record);
  const byId = new Map(cases.map((c) => [c.case_id, c]));
  const judgments = new Map<string, Judgment>();
  const errors: string[] = [];
  let breaker: string | null = deps.llmEnabled ? null : 'ai_not_configured';

  // ---- 逐条标注 ----
  const todo: GovRiskCase[] = [];
  let cached = 0;
  for (const row of input.rows) {
    if (row.judgment?.source === 'model' && row.judgmentKey === judgeKey(row.record)) {
      judgments.set(row.record.case_id, row.judgment);
      cached += 1;
    } else {
      todo.push(row.record);
    }
  }
  todo.sort((a, b) => ms(b.created_at) - ms(a.created_at)); // 额度先给最新的
  const budget = breaker ? [] : todo.slice(0, Math.max(0, deps.maxJudge));
  const batches: GovRiskCase[][] = [];
  for (let i = 0; i < budget.length; i += JUDGE_BATCH) batches.push(budget.slice(i, i + JUDGE_BATCH));
  let judgedNow = 0;
  let done = 0;
  let consecutive = 0;
  await deps.progress({ stage: 'judge', done: 0, total: budget.length });
  await pool(batches, deps.concurrency ?? 3, async (batch) => {
    let parsed: Record<string, Record<string, unknown>> = {};
    let model = '';
    if (!breaker) {
      try {
        const res = await deps.complete({
          purpose: 'judge',
          messages: [{ role: 'system', content: judgeSystemPrompt() }, { role: 'user', content: judgeUserPrompt(batch) }],
          maxTokens: 2000,
        });
        parsed = parseJudgeBatch(res.content);
        model = res.model;
        if (Object.keys(parsed).length) consecutive = 0;
        else {
          errors.push('ai_unparseable');
          consecutive += 1;
        }
      } catch (error) {
        const reason = classifyLlmError(error);
        errors.push(reason);
        consecutive += 1;
        if (FATAL.has(reason)) breaker = breaker || reason;
      }
      if (consecutive >= 3) breaker = breaker || 'too_many_failures';
    }
    for (const c of batch) {
      const raw = parsed[c.case_id];
      if (!raw) continue;
      const j = validateJudgment(raw, c, model);
      judgments.set(c.case_id, j);
      judgedNow += 1;
      await deps.saveJudgment(c.case_id, judgeKey(c), j);
    }
    done += batch.length;
    await deps.progress({ stage: 'judge', done, total: budget.length });
  });
  let byRules = 0;
  for (const c of cases) {
    if (!judgments.has(c.case_id)) {
      judgments.set(c.case_id, rulesJudgment(c));
      byRules += 1;
    }
  }

  // ---- 归并打分 ----
  const now = deps.now();
  const candidates: Candidate[] = buildCandidates(cases, judgments, input.feedback, input.refs, now);

  // ---- 候选复核 ----
  const prior = previousReviews(input.previousPackage);
  const targets = candidates.filter((c) => c.status !== 'dismissed' && c.symptom !== 'S_OTHER').slice(0, REVIEW_TOP_N);
  let reviewed = 0;
  let reviewCached = 0;
  let reviewFailed = 0;
  for (let i = 0; i < targets.length; i++) {
    const cand = targets[i];
    const members = cand.case_ids.map((id) => byId.get(id)).filter((c): c is GovRiskCase => !!c);
    const matched = input.refs.filter((r) => cand.reference_matches.some((m) => m.case_id === r.id));
    const prompt = reviewUserPrompt(cand, members, judgments, matched);
    cand.review_key = reviewKey(prompt);
    const hit = prior.get(cand.review_key);
    if (hit) {
      cand.review = hit;
      reviewCached += 1;
      continue;
    }
    if (breaker) {
      cand.review = null;
      continue;
    }
    try {
      const res = await deps.complete({
        purpose: 'review',
        messages: [{ role: 'system', content: reviewSystemPrompt() }, { role: 'user', content: prompt }],
        maxTokens: 1200,
      });
      cand.review = validateReview(extractJson(res.content));
      if (cand.review) reviewed += 1;
      else reviewFailed += 1;
    } catch (error) {
      const reason = classifyLlmError(error);
      errors.push(reason);
      reviewFailed += 1;
      cand.review = null;
      if (FATAL.has(reason)) breaker = breaker || reason;
    }
    await deps.progress({ stage: 'review', done: i + 1, total: targets.length });
  }

  const models = [...new Set([...judgments.values()].filter((j) => j.source === 'model' && j.model).map((j) => j.model as string))];
  const method = {
    judge_prompt: JUDGE_PROMPT_VERSION,
    review_prompt: REVIEW_PROMPT_VERSION,
    model: models[0] || null,
    models,
    judged_by_model: judgedNow + cached,
    judged_new: judgedNow,
    judged_cached: cached,
    judged_by_rules: byRules,
    judge_deferred: Math.max(0, todo.length - budget.length),
    reviewed: reviewed + reviewCached,
    review_failed: reviewFailed,
    breaker,
    errors: [...new Set(errors)].slice(0, 5),
  };
  const pkg = buildPackage({
    cases, judgments, candidates, refs: input.refs, method, now, dataset: input.dataset, run: input.run,
  });
  return {
    pkg,
    stats: { ...method, cases: cases.length, candidates: candidates.length, duration_ms: deps.now() - started },
  };
}
