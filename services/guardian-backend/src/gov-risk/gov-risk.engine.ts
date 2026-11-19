import { createHash } from 'node:crypto';
import {
  CLUE_HINTS,
  CLUES,
  DEMANDS,
  MECHANISMS,
  SENSITIVITY,
  STATUS_LABELS,
  SYMPTOMS,
  VERIFY_STEPS,
  ruleClues,
  ruleDemands,
  ruleSymptoms,
} from './gov-risk.vocab';

/**
 * 工单系统性原因研判 —— 研判引擎(纯函数,不碰数据库和网络)。
 *
 * 输入是本地服务上传的脱敏工单(映射编号 GT-、去掉个人信息和地址的正文、部门类型、城市、场站编码 ST-),
 * 依次做:逐条机理标注 → 按现象归并成"系统性原因候选" → 算复发、扩散、敏感度并排序 → 候选复核 → 组装结果包。
 *
 * 两层候选:
 * - 现象级:同一现象的全部投诉(例如所有"电量偏高"),看它是否每月都在出现、关单后还在出现;
 * - 对象级:同一现象落在同一场站(本地算的 ST- 编码)或同一运营商上 ≥2 次,指向设备批次或运营方。
 * "已解决"不等于问题消失:工单状态和根因状态分开,候选标成已修复后同类再出现,记为复发。
 */

export const RESULT_SCHEMA = 'gov-risk/v2';
export const JUDGE_PROMPT_VERSION = 'judge-v2';
export const REVIEW_PROMPT_VERSION = 'review-v2';
export const JUDGE_BATCH = 6;
export const JUDGE_MAX_CHARS = 600;
export const REVIEW_TOP_N = 12;
export const OBSERVATION_DAYS = 60;
const REVIEW_MAX_EXCERPTS = 20;
const DAY_MS = 24 * 3600 * 1000;
const CN_OFFSET_MS = 8 * 3600 * 1000; // 中国不实行夏令时,按固定 +08:00 取自然月

export interface CaseText {
  description?: string;
  demand?: string;
  issue?: string;
  remark?: string;
}

/** 本地服务上传的一条脱敏工单(字段白名单见 gov-risk.validate.ts) */
export interface GovRiskCase {
  case_id: string;
  channel: string;
  created_at: string;
  closed_at: string | null;
  status: string;
  resolution: string;
  platform_risk: string;
  template_risk: string;
  business_line: string;
  dept_type: string;
  city: string;
  problem_path: string;
  station_code: string | null;
  user_key: string | null;
  text: CaseText;
}

export interface Judgment {
  symptoms: string[];
  primary_symptom: string;
  mechanisms: Array<{ code: string; confidence: number }>;
  clues: string[];
  objects: { operator: string; pile: string; stage: string[] };
  systemic_likelihood: '高' | '中' | '低';
  systemic_reason: string;
  demands: string[];
  summary: string;
  source: 'model' | 'rules';
  model?: string;
}

export interface ReferenceCase {
  id: string;
  title: string;
  symptom: string;
  mechanisms: string[];
  consequence?: string;
  summary?: string;
}

export interface FeedbackEntry {
  status: string;
  note?: string;
  updated_at?: string;
}

export interface Review {
  title: string;
  summary: string;
  mechanism_assessment: Array<{ code: string; likelihood: '高' | '中' | '低'; evidence: string }>;
  verification_steps: string[];
  owner: string;
  why_early: string;
  confidence: '高' | '中' | '低';
}

export interface CandidateStats {
  n: number;
  n_90d: number;
  n_prev_90d: number;
  months: Record<string, number>;
  active_months_6: number;
  first_month: string;
  last_month: string;
  resolved: number;
  open: number;
  after_first_close: number;
  recurring_after_close: boolean;
  channels: Record<string, number>;
  depts: Record<string, number>;
  cities: number;
  stations: number;
  template_l2_l4: number;
  platform_l1_l4: number;
  repeat_users: number;
  demands: Record<string, number>;
  systemic: Record<string, number>;
  mechanisms: Array<{ code: string; weight: number }>;
  clues: Array<{ code: string; n: number }>;
}

export interface Candidate {
  id: string;
  level: 'symptom' | 'object';
  symptom: string;
  object_type: '场站' | '运营商' | null;
  object_code: string | null;
  object_label: string | null;
  score: number;
  band: '高' | '中' | '低';
  score_breakdown: Record<string, number>;
  stats: CandidateStats;
  reference_matches: Array<{ case_id: string; title: string; why: string }>;
  status: string;
  recurred_after_fix: number;
  observing_until: string | null;
  case_ids: string[];
  review?: Review | null;
  review_key?: string;
}

// ---------- 通用 ----------

const B32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

/** 稳定短码:sha256 后取 base32 前 n 位。候选编号要跨期稳定,所有者的跟进记录按它挂。 */
export function shortCode(prefix: string, msg: string, n = 6): string {
  const digest = createHash('sha256').update(msg, 'utf8').digest();
  let out = '';
  let value = 0;
  let bits = 0;
  for (const byte of digest) {
    value = ((value << 8) | byte) & 0xffff;
    bits += 8;
    while (bits >= 5 && out.length < n) {
      out += B32[(value >>> (bits - 5)) & 31];
      bits -= 5;
    }
    if (out.length >= n) break;
  }
  return prefix + out;
}

export function sha256(text: string): string {
  return createHash('sha256').update(text, 'utf8').digest('hex');
}

export function ms(iso: string | null | undefined): number {
  if (!iso) return 0;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? 0 : t;
}

export function monthOf(t: number): string {
  return t ? new Date(t + CN_OFFSET_MS).toISOString().slice(0, 7) : '';
}

/** 含当月在内往回数 k 个自然月,如 ["2026-10","2026-09",...] */
export function lastMonths(now: number, k: number): string[] {
  const d = new Date(now + CN_OFFSET_MS);
  let y = d.getUTCFullYear();
  let m = d.getUTCMonth() + 1;
  const out: string[] = [];
  for (let i = 0; i < k; i++) {
    out.push(`${y}-${String(m).padStart(2, '0')}`);
    if (m === 1) { y -= 1; m = 12; } else { m -= 1; }
  }
  return out;
}

function count<T extends string>(items: T[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const x of items) out[x] = (out[x] || 0) + 1;
  return out;
}

function sortedByCount(rec: Record<string, number>): Record<string, number> {
  return Object.fromEntries(Object.entries(rec).sort((a, b) => b[1] - a[1]));
}

function str(v: unknown, n: number): string {
  return String(v ?? '').slice(0, n);
}

function level3(v: unknown): '高' | '中' | '低' {
  return v === '高' || v === '中' || v === '低' ? v : '中';
}

/** 从模型输出里取第一个 JSON 对象;容忍 ```json 围栏和前后杂字。 */
export function extractJson(content: string): Record<string, unknown> | null {
  const m = /\{[\s\S]*\}/.exec(content || '');
  if (!m) return null;
  try {
    const v = JSON.parse(m[0]);
    return v && typeof v === 'object' && !Array.isArray(v) ? v : null;
  } catch {
    return null;
  }
}

// ---------- 逐条研判 ----------

const TEXT_LABELS: Array<[keyof CaseText, string]> = [
  ['description', '问题描述'], ['demand', '诉求'], ['issue', '存在的具体问题'], ['remark', '备注'],
];

export function analysisText(c: GovRiskCase): string {
  return TEXT_LABELS.filter(([k]) => c.text?.[k]).map(([k, label]) => `${label}:${c.text[k]}`).join('\n');
}

export function problemLeaf(c: GovRiskCase): string {
  const parts = (c.problem_path || '').split('/');
  return parts[parts.length - 1] || '';
}

export function judgeInput(c: GovRiskCase): string {
  return analysisText(c).slice(0, JUDGE_MAX_CHARS);
}

/** 内容和提示词版本都没变就复用上次的模型结论 */
export function judgeKey(c: GovRiskCase): string {
  return sha256(`${JUDGE_PROMPT_VERSION}|${judgeInput(c)}`);
}

function vocabLines(d: Record<string, string>): string {
  return Object.entries(d).map(([k, v]) => `${k}:${v}`).join('\n');
}

export function judgeSystemPrompt(): string {
  const clues = Object.fromEntries(Object.entries(CLUES).map(([k, v]) => [k, v.label]));
  return `你是滴滴充电/加油业务的投诉根因分析员。任务:读用户投诉(政府转办、客服进线或舆情),判断"现象"和"可能的系统性原因",用来提前发现会反复出现的问题。

背景:很多系统性问题在用户眼里表现相同。例如设备计量电路老化、设备流水号重复导致新用户看到老用户的充电数据,用户反馈出来都是"电量/金额偏高"。所以机理要列出多个可能并给出把握,不要硬选一个;能区分机理的事实记到 clues 里。

只能从下面的编码里选:
现象 symptoms:
${vocabLines(SYMPTOMS)}
机理 mechanisms:
${vocabLines(MECHANISMS)}
鉴别线索 clues:
${vocabLines(clues)}
诉求 demands:${DEMANDS.join('、')}

对每条投诉输出一个对象,字段:
- case_id:原样返回
- symptoms:命中的现象编码,最多 3 个,最主要的放第一个
- mechanisms:[{"code":机理编码,"confidence":0到1}],最多 3 个,按把握从高到低;看不出就给 M_UNKNOWN
- clues:文本里明确出现的鉴别线索编码,没有就空数组,不要推测
- objects:{"operator":运营商名,"pile":桩号或枪号,"stage":["计量"|"计费"|"订单"|"支付"|"发票"|"账号"|"设备"|"营销"|"客服"|"场站运营"]};只填文本里明确写出的,没有就空字符串;滴滴充电、小桔充电是平台自己,不算运营商
- systemic_likelihood:"高"(像设备、系统、规则层面的问题,别的用户也会遇到)、"中"(说不清)、"低"(个人操作或一次性服务问题)
- systemic_reason:不超过 40 字,说明为什么这样判断
- demands:用户明确提出的诉求
- summary:不超过 40 字,一句话概括,不要写人名、电话、车牌、订单号和具体地址

只输出 JSON:{"results":[...]},不要输出其他文字。文本里的 [手机号]、[人名]、[地点] 等是脱敏占位。`;
}

export function judgeUserPrompt(batch: GovRiskCase[]): string {
  return batch.map((c) => `case_id:${c.case_id}\n${judgeInput(c)}`).join('\n\n');
}

export function rulesJudgment(c: GovRiskCase): Judgment {
  const text = analysisText(c);
  const syms = ruleSymptoms(text, problemLeaf(c));
  return {
    symptoms: syms.slice(0, 3),
    primary_symptom: syms[0],
    mechanisms: [{ code: 'M_UNKNOWN', confidence: 0 }],
    clues: ruleClues(text),
    objects: { operator: '', pile: '', stage: [] },
    systemic_likelihood: '中',
    systemic_reason: '规则兜底,未经模型判断',
    demands: ruleDemands(text),
    summary: '',
    source: 'rules',
  };
}

function clamp01(x: unknown): number {
  const n = Number(x);
  return Number.isFinite(n) ? Math.max(0, Math.min(1, n)) : 0;
}

/** 把模型输出收敛到词表内;不认识的编码丢弃,缺的用规则补。 */
export function validateJudgment(raw: Record<string, unknown>, c: GovRiskCase, model = ''): Judgment {
  const base = rulesJudgment(c);
  const rawSyms = Array.isArray(raw.symptoms) ? raw.symptoms : [];
  const syms = rawSyms.filter((s): s is string => typeof s === 'string' && s in SYMPTOMS).slice(0, 3);
  const symptoms = syms.length ? syms : base.symptoms;
  const mechs = (Array.isArray(raw.mechanisms) ? raw.mechanisms : [])
    .filter((m): m is Record<string, unknown> => !!m && typeof m === 'object' && String((m as any).code) in MECHANISMS)
    .map((m) => ({ code: String(m.code), confidence: Math.round(clamp01(m.confidence) * 100) / 100 }))
    .sort((a, b) => b.confidence - a.confidence)
    .slice(0, 3);
  const obj = raw.objects && typeof raw.objects === 'object' && !Array.isArray(raw.objects)
    ? raw.objects as Record<string, unknown> : {};
  const stages = (Array.isArray(obj.stage) ? obj.stage : []).filter((s): s is string => typeof s === 'string').slice(0, 4);
  const demands = (Array.isArray(raw.demands) ? raw.demands : [])
    .filter((d): d is string => typeof d === 'string' && (DEMANDS as readonly string[]).includes(d));
  const clues = (Array.isArray(raw.clues) ? raw.clues : []).filter((x): x is string => typeof x === 'string' && x in CLUES);
  return {
    symptoms,
    primary_symptom: symptoms[0],
    mechanisms: mechs.length ? mechs : [{ code: 'M_UNKNOWN', confidence: 0 }],
    clues,
    objects: { operator: str(obj.operator, 40).trim(), pile: str(obj.pile, 40).trim(), stage: stages },
    systemic_likelihood: level3(raw.systemic_likelihood),
    systemic_reason: str(raw.systemic_reason, 80),
    demands: demands.length ? demands : base.demands,
    summary: str(raw.summary, 80),
    source: 'model',
    ...(model ? { model } : {}),
  };
}

/** 模型批量输出 → {case_id: 原始结果} */
export function parseJudgeBatch(content: string): Record<string, Record<string, unknown>> {
  const data = extractJson(content);
  const out: Record<string, Record<string, unknown>> = {};
  const results = data && Array.isArray(data.results) ? data.results : [];
  for (const r of results) {
    if (r && typeof r === 'object' && (r as any).case_id) out[String((r as any).case_id)] = r as Record<string, unknown>;
  }
  return out;
}

// ---------- 归并与打分 ----------

const STRONG_DEMANDS = new Set(['欺诈主张', '要求查处', '诉讼', '曝光']);
const REGULATORS = new Set(['市场监管', '个人信息保护', '网信', '税务', '交通运输', '公安']);
const CLOSED_STATES = new Set(['fixed', 'observing', 'closed']);
const ELEVATED = new Set(['L1', 'L2', 'L3', 'L4']);
const PLATFORM_SELF = /^(滴滴|小桔|滴滴充电|小桔充电|滴滴加油|小桔加油)$/;
export const WEIGHTS: Record<string, number> = {
  persistence: 25, volume: 15, spread: 10, sensitivity: 20, systemic: 15, escalation: 10, regulator: 5,
};

export function normObject(s: string): string {
  return (s || '').replace(/[\s()（）【】[\]·\-—_,，。]/g, '').slice(0, 30);
}

function band(score: number): '高' | '中' | '低' {
  return score >= 65 ? '高' : score >= 45 ? '中' : '低';
}

export function candidateStats(members: GovRiskCase[], judgments: Map<string, Judgment>, now: number): CandidateStats {
  const created = members.map((c) => ms(c.created_at));
  const months = count(created.map(monthOf).filter(Boolean));
  const monthKeys = Object.keys(months).sort();
  const last6 = new Set(lastMonths(now, 6));
  const n90 = created.filter((t) => t >= now - 90 * DAY_MS).length;
  const nPrev = created.filter((t) => t >= now - 180 * DAY_MS && t < now - 90 * DAY_MS).length;
  const closes = members.filter((c) => c.closed_at && (c.resolution || '').includes('解决')).map((c) => ms(c.closed_at)).sort((a, b) => a - b);
  const afterClose = closes.length ? created.filter((t) => t > closes[0]).length : 0;
  const users = count(members.map((c) => c.user_key).filter((x): x is string => !!x));
  const mech: Record<string, number> = {};
  const clue: Record<string, number> = {};
  const dem: Record<string, number> = {};
  const sysl: Record<string, number> = {};
  for (const c of members) {
    const j = judgments.get(c.case_id);
    if (!j) continue;
    for (const m of j.mechanisms) mech[m.code] = (mech[m.code] || 0) + (m.confidence || 0);
    for (const x of j.clues) clue[x] = (clue[x] || 0) + 1;
    for (const d of j.demands) dem[d] = (dem[d] || 0) + 1;
    sysl[j.systemic_likelihood] = (sysl[j.systemic_likelihood] || 0) + 1;
  }
  const totalConf = Object.values(mech).reduce((a, b) => a + b, 0) || 1;
  return {
    n: members.length,
    n_90d: n90,
    n_prev_90d: nPrev,
    months: Object.fromEntries(monthKeys.map((k) => [k, months[k]])),
    active_months_6: [...last6].filter((m) => months[m]).length,
    first_month: monthKeys[0] || '',
    last_month: monthKeys[monthKeys.length - 1] || '',
    resolved: members.filter((c) => (c.resolution || '').includes('解决')).length,
    open: members.filter((c) => c.status && c.status !== '已处理').length,
    after_first_close: afterClose,
    recurring_after_close: afterClose >= 2,
    channels: count(members.map((c) => c.channel)),
    depts: sortedByCount(count(members.map((c) => c.dept_type || '未知'))),
    cities: new Set(members.map((c) => c.city).filter(Boolean)).size,
    stations: new Set(members.map((c) => c.station_code).filter(Boolean)).size,
    template_l2_l4: members.filter((c) => ELEVATED.has(c.template_risk)).length,
    platform_l1_l4: members.filter((c) => ELEVATED.has((c.platform_risk || '').slice(0, 2))).length,
    repeat_users: Object.values(users).filter((k) => k >= 2).length,
    demands: sortedByCount(dem),
    systemic: sysl,
    mechanisms: Object.entries(mech).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]).slice(0, 4)
      .map(([code, v]) => ({ code, weight: Math.round((v / totalConf) * 100) / 100 })),
    clues: Object.entries(clue).sort((a, b) => b[1] - a[1]).map(([code, n]) => ({ code, n })),
  };
}

function scoreOf(symptom: string, level: 'symptom' | 'object', st: CandidateStats, members: GovRiskCase[], judgments: Map<string, Judgment>) {
  const n = Math.max(st.n, 1);
  const strong = members.filter((c) => {
    const j = judgments.get(c.case_id);
    return (j?.demands || []).some((d) => STRONG_DEMANDS.has(d)) || ELEVATED.has(c.template_risk);
  }).length;
  const regulator = Object.entries(st.depts).filter(([k]) => REGULATORS.has(k)).reduce((a, [, v]) => a + v, 0);
  const parts: Record<string, number> = {
    persistence: st.active_months_6 / 6,
    volume: Math.min(1, Math.log2(1 + st.n_90d) / Math.log2(21)),
    spread: level === 'symptom' ? Math.min(1, Math.max(0, st.stations - 1) / 5) : Math.min(1, (st.n - 1) / 3),
    sensitivity: SENSITIVITY[symptom] ?? 0.3,
    systemic: ((st.systemic['高'] || 0) + 0.5 * (st.systemic['中'] || 0)) / n,
    escalation: Math.min(1, (strong / n) * 2),
    regulator: regulator / n,
  };
  const breakdown: Record<string, number> = {};
  let score = 0;
  for (const [k, v] of Object.entries(parts)) {
    breakdown[k] = Math.round(v * WEIGHTS[k] * 10) / 10;
    score += breakdown[k];
  }
  if (st.recurring_after_close) {
    breakdown.closed_but_recurring = 5;
    score += 5;
  }
  return { score: Math.min(100, Math.round(score)), breakdown };
}

function referenceMatches(symptom: string, st: CandidateStats, refs: ReferenceCase[]) {
  const top = new Set(st.mechanisms.slice(0, 3).map((m) => m.code));
  return refs.filter((r) => r.symptom === symptom).map((r) => {
    const why = [`现象相同:${SYMPTOMS[symptom] || symptom}`];
    const overlap = (r.mechanisms || []).filter((m) => top.has(m));
    if (overlap.length) why.push(`疑似机理重叠:${overlap.map((m) => (MECHANISMS[m] || m).split('(')[0]).join('、')}`);
    return { case_id: r.id, title: r.title || '', why: why.join(';') };
  });
}

export function buildCandidates(
  cases: GovRiskCase[],
  judgments: Map<string, Judgment>,
  feedback: Record<string, FeedbackEntry>,
  refs: ReferenceCase[],
  now: number,
  observationDays = OBSERVATION_DAYS,
): Candidate[] {
  const bySymptom = new Map<string, GovRiskCase[]>();
  for (const c of cases) {
    const s = judgments.get(c.case_id)?.primary_symptom || 'S_OTHER';
    if (!bySymptom.has(s)) bySymptom.set(s, []);
    bySymptom.get(s)!.push(c);
  }
  const out: Candidate[] = [];

  const add = (level: 'symptom' | 'object', symptom: string, members: GovRiskCase[],
    objectType: '场站' | '运营商' | null = null, objectKey = '', objectLabel = '') => {
    const st = candidateStats(members, judgments, now);
    const { score, breakdown } = scoreOf(symptom, level, st, members, judgments);
    const id = shortCode('SC-', `${level}|${symptom}|${objectType || ''}|${objectKey}`);
    const objectCode = objectType === '场站' ? objectKey : objectType === '运营商' ? shortCode('OP-', objectKey) : null;
    const state = feedback[id] || ({} as FeedbackEntry);
    const status = state.status || 'new';
    let recurred = 0;
    let observingUntil: string | null = null;
    const since = ms(state.updated_at);
    if (CLOSED_STATES.has(status) && since) {
      recurred = members.filter((c) => ms(c.created_at) > since).length;
      observingUntil = new Date(since + observationDays * DAY_MS + CN_OFFSET_MS).toISOString().slice(0, 10);
    }
    out.push({
      id, level, symptom, object_type: objectType, object_code: objectCode,
      object_label: objectType === '运营商' ? objectLabel : null,
      score, band: band(score), score_breakdown: breakdown, stats: st,
      reference_matches: referenceMatches(symptom, st, refs),
      status, recurred_after_fix: recurred, observing_until: observingUntil,
      // 最新的在前,页面下钻按这个顺序分页读
      case_ids: [...members].sort((x, y) => ms(y.created_at) - ms(x.created_at) || x.case_id.localeCompare(y.case_id)).map((c) => c.case_id),
    });
  };

  for (const [symptom, members] of bySymptom) {
    add('symptom', symptom, members);
    const stations = new Map<string, GovRiskCase[]>();
    const operators = new Map<string, { label: string; members: GovRiskCase[] }>();
    for (const c of members) {
      if (c.station_code) {
        if (!stations.has(c.station_code)) stations.set(c.station_code, []);
        stations.get(c.station_code)!.push(c);
      }
      const op = (judgments.get(c.case_id)?.objects.operator || '').trim();
      const key = normObject(op);
      if (key && !PLATFORM_SELF.test(key)) {
        if (!operators.has(key)) operators.set(key, { label: op, members: [] });
        operators.get(key)!.members.push(c);
      }
    }
    for (const [code, ms2] of stations) if (ms2.length >= 2) add('object', symptom, ms2, '场站', code);
    for (const [key, g] of operators) if (g.members.length >= 2) add('object', symptom, g.members, '运营商', key, g.label);
  }

  for (const c of out) { // 与已知案例相似的往前排
    if (c.reference_matches.length) {
      c.score_breakdown.reference_case = 10;
      c.score = Math.min(100, c.score + 10);
      c.band = band(c.score);
    }
  }
  // 误报沉底;修复后复发的置顶;其余按分数
  out.sort((a, b) => Number(a.status === 'dismissed') - Number(b.status === 'dismissed')
    || b.recurred_after_fix - a.recurred_after_fix || b.score - a.score);
  return out;
}

// ---------- 候选复核 ----------

export function reviewSystemPrompt(): string {
  return `你是滴滴充电/加油业务的系统性风险分析员。给你一组"同一现象"的用户投诉(已脱敏)和统计,判断背后是否有系统性原因、值不值得在引发舆情或监管压力之前处理。

已知教训:设备计量电路老化、设备流水号重复导致新用户看到老用户的充电数据,用户反馈出来都是"电量/金额偏高";这类问题过去在单条投诉层面"已解决"就结束了,后来某一单碰上舆情才被重视。所以要看:是否每月都在出现、关单后是否还在出现、是否集中在同一场站或同一类设备、能区分不同机理的线索是什么。

机理编码:
${vocabLines(MECHANISMS)}

只输出 JSON,字段:
- title:不超过 20 字,概括这一类系统性原因
- summary:不超过 120 字,说明现象、规模和走势、最可能的原因
- mechanism_assessment:[{"code":机理编码,"likelihood":"高"|"中"|"低","evidence":"不超过 50 字的依据"}],最多 3 个
- verification_steps:最多 4 条,每条不超过 40 字,写清先查什么数据、比对什么
- owner:建议牵头方,如 设备运维、运营商管理、订单系统研发、计费配置、营销、客服
- why_early:不超过 80 字,为什么现在就该处理
- confidence:"高"|"中"|"低"

硬性要求:不要写人名、电话、车牌、订单号、具体地址;场站用"某场站""部分设备"这类概括说法。`;
}

export function reviewUserPrompt(cand: Candidate, members: GovRiskCase[], judgments: Map<string, Judgment>, refs: ReferenceCase[]): string {
  const st = cand.stats;
  const where = cand.level === 'object'
    ? `;集中在同一${cand.object_type}${cand.object_type === '运营商' && cand.object_label ? `(${cand.object_label})` : ''}` : '';
  const lines = [
    `现象:${SYMPTOMS[cand.symptom] || cand.symptom}${where}`,
    `投诉 ${st.n} 条,近 90 天 ${st.n_90d} 条(此前 90 天 ${st.n_prev_90d} 条);近 6 个月有 ${st.active_months_6} 个月出现;按月:${JSON.stringify(st.months)}`,
    `已解决关单 ${st.resolved} 条,首次关单后又新增 ${st.after_first_close} 条;涉及 ${st.stations} 个场站、${st.cities} 个城市`,
    `来源部门:${JSON.stringify(st.depts)};用户诉求:${JSON.stringify(st.demands)};来源渠道:${JSON.stringify(st.channels)}`,
    `逐条研判的机理分布:${st.mechanisms.map((m) => `${m.code} ${m.weight}`).join(';')}`,
    `鉴别线索:${st.clues.map((x) => `${CLUES[x.code]?.label || x.code} ${x.n} 条`).join(';') || '无'}`,
  ];
  if (refs.length) lines.push(`已知案例:${refs.map((r) => `${r.title}(${r.consequence || ''})`).join(';')}`);
  lines.push('投诉摘要:');
  const ordered = [...members].sort((a, b) => ms(b.created_at) - ms(a.created_at)).slice(0, REVIEW_MAX_EXCERPTS);
  for (const c of ordered) lines.push(`- ${judgments.get(c.case_id)?.summary || judgeInput(c).slice(0, 160)}`);
  return lines.join('\n');
}

export function reviewKey(userPrompt: string): string {
  return sha256(`${REVIEW_PROMPT_VERSION}|${userPrompt}`);
}

export function validateReview(raw: Record<string, unknown> | null): Review | null {
  if (!raw) return null;
  const assess = (Array.isArray(raw.mechanism_assessment) ? raw.mechanism_assessment : [])
    .filter((a): a is Record<string, unknown> => !!a && typeof a === 'object' && String((a as any).code) in MECHANISMS)
    .slice(0, 3)
    .map((a) => ({ code: String(a.code), likelihood: level3(a.likelihood), evidence: str(a.evidence, 80) }));
  const steps = (Array.isArray(raw.verification_steps) ? raw.verification_steps : []).filter(Boolean).slice(0, 4).map((x) => str(x, 60));
  const review: Review = {
    title: str(raw.title, 30), summary: str(raw.summary, 200), mechanism_assessment: assess,
    verification_steps: steps, owner: str(raw.owner, 30), why_early: str(raw.why_early, 120),
    confidence: level3(raw.confidence),
  };
  return review.title || review.summary ? review : null;
}

// ---------- 结果包 ----------

function publicCandidate(c: Candidate) {
  return {
    id: c.id, level: c.level, object_type: c.object_type, object_code: c.object_code, object_label: c.object_label,
    symptom: c.symptom, symptom_label: SYMPTOMS[c.symptom] || c.symptom,
    score: c.score, band: c.band, score_breakdown: c.score_breakdown,
    status: c.status, recurred_after_fix: c.recurred_after_fix, observing_until: c.observing_until,
    stats: c.stats,
    mechanisms: c.stats.mechanisms.map((m) => ({ code: m.code, label: MECHANISMS[m.code] || m.code, weight: m.weight })),
    clues: c.stats.clues.map((x) => ({
      code: x.code, label: CLUES[x.code]?.label || x.code, n: x.n,
      points_to: (CLUE_HINTS[x.code] || []).map((h) => MECHANISMS[h] || h),
    })),
    verify_steps: c.stats.mechanisms.slice(0, 3).filter((m) => VERIFY_STEPS[m.code])
      .map((m) => ({ code: m.code, step: VERIFY_STEPS[m.code] })),
    review: c.review || null,
    review_key: c.review_key || null,
    reference_matches: c.reference_matches,
    case_ids: c.case_ids,
  };
}

export interface PackageInput {
  cases: GovRiskCase[];
  judgments: Map<string, Judgment>;
  candidates: Candidate[];
  refs: ReferenceCase[];
  method: Record<string, unknown>;
  now: number;
  dataset: { uploaded_at: string | null; case_count: number };
  run: { id: number; trigger: string };
}

export function buildPackage(input: PackageInput): Record<string, unknown> {
  const { cases, judgments, candidates, refs, method, now } = input;
  const created = cases.map((c) => ms(c.created_at)).filter(Boolean).sort((a, b) => a - b);
  const active = candidates.filter((c) => c.status !== 'dismissed');
  const openIds = new Set(cases.filter((c) => c.status && c.status !== '已处理').map((c) => c.case_id));
  const cells = new Map<string, { symptom: string; dept_type: string; n: number }>();
  const trend = new Map<string, { n: number; systemic_high: number }>();
  for (const c of cases) {
    const j = judgments.get(c.case_id);
    const sym = j?.primary_symptom || 'S_OTHER';
    const dept = c.dept_type || '未知';
    const key = `${sym}|${dept}`;
    if (!cells.has(key)) cells.set(key, { symptom: sym, dept_type: dept, n: 0 });
    cells.get(key)!.n += 1;
    const month = monthOf(ms(c.created_at));
    if (!month) continue;
    if (!trend.has(month)) trend.set(month, { n: 0, systemic_high: 0 });
    const t = trend.get(month)!;
    t.n += 1;
    if (j?.systemic_likelihood === '高') t.systemic_high += 1;
  }
  return {
    schema: RESULT_SCHEMA,
    generated_at: new Date(now).toISOString(),
    data_window: { from: monthOf(created[0] || 0), to: monthOf(created[created.length - 1] || 0) },
    sources: Object.entries(count(cases.map((c) => c.channel))).map(([channel, n]) => ({ channel, n })),
    dataset: input.dataset,
    run: input.run,
    method,
    kpi: {
      cases: cases.length,
      candidates_high: active.filter((c) => c.band === '高').length,
      candidates_medium: active.filter((c) => c.band === '中').length,
      recurring_after_close_high: candidates.filter((c) => c.band === '高' && c.stats.recurring_after_close).length,
      recurred_after_fix: candidates.filter((c) => c.recurred_after_fix).length,
      open_cases_in_high: new Set(candidates.filter((c) => c.band === '高').flatMap((c) => c.case_ids).filter((id) => openIds.has(id))).size,
    },
    candidates: candidates.filter((c) => c.symptom !== 'S_OTHER' || c.band !== '低').map(publicCandidate),
    overview: {
      matrix: [...cells.values()].sort((a, b) => a.symptom.localeCompare(b.symptom) || a.dept_type.localeCompare(b.dept_type))
        .map((x) => ({ ...x, symptom_label: SYMPTOMS[x.symptom] || x.symptom })),
      trend: [...trend.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([month, v]) => ({ month, ...v })),
    },
    reference_cases: refs.map((r) => ({
      id: r.id, title: r.title, symptom: r.symptom, mechanisms: r.mechanisms, consequence: r.consequence || '', summary: r.summary || '',
    })),
    vocab: { symptoms: SYMPTOMS, mechanisms: MECHANISMS, status: STATUS_LABELS },
  };
}
