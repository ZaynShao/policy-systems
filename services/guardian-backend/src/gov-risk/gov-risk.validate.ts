import { BadRequestException, HttpException, HttpStatus } from '@nestjs/common';
import type { FeedbackEntry, GovRiskCase, ReferenceCase } from './gov-risk.engine';
import { MECHANISMS, SYMPTOMS } from './gov-risk.vocab';

/**
 * 工单系统性原因研判 —— 入参校验与个人信息扫描。
 *
 * 本地服务在出本机前已经脱敏(去手机号、证件号、车牌、长编号、邮箱、链接、人名,地址/场站换成 ST- 编码)
 * 并按字段白名单组装。这里在公网再拦一道:字段白名单 + 个人信息样式扫描,命中就整批拒收,
 * 只回映射编号、路径和类型,不回显内容。人名、地址这类只有本地知道的禁用词,服务端无法替代那一道。
 */

export const CASES_SCHEMA = 'gov-risk-cases/v1';
export const MAX_CASES_PER_CHUNK = 500;
export const MAX_CHUNKS = 400;
export const MAX_TEXT_CHARS = 2000;
export const MAX_FEEDBACK_BYTES = 512 * 1024;
export const MAX_CASE_QUERY = 50;
export const FEEDBACK_STATUSES = [
  'new', 'investigating', 'confirmed', 'fixing', 'fixed', 'observing', 'dismissed', 'closed',
] as const;
export const CHANNELS = ['政诉', '普通客诉', '舆情'] as const;

export const CANDIDATE_ID = /^SC-[A-Z2-7]{6}$/;
export const CASE_ID = /^GT-[A-Z2-7]{8}$/;
const STATION_CODE = /^ST-[A-Z2-7]{6}$/;
const USER_KEY = /^U-[A-Z2-7]{10}$/;
const UPLOAD_ID = /^[A-Za-z0-9_-]{8,64}$/;
const MONTH = /^\d{4}-\d{2}$/;
const REF_ID = /^RC-[A-Za-z0-9_-]{1,20}$/;

const CASE_KEYS = new Set([
  'case_id', 'channel', 'created_at', 'closed_at', 'status', 'resolution', 'platform_risk', 'template_risk',
  'business_line', 'dept_type', 'city', 'problem_path', 'station_code', 'user_key', 'text',
]);
const TEXT_KEYS = new Set(['description', 'demand', 'issue', 'remark']);
const STRING_LIMITS: Record<string, number> = {
  status: 20, resolution: 40, platform_risk: 20, template_risk: 4, business_line: 10, dept_type: 12, city: 16,
  problem_path: 120,
};

const PII_PATTERNS: Array<[string, RegExp]> = [
  ['phone', /(?<!\d)1[3-9]\d{9}(?!\d)/],
  ['phone_masked', /(?<!\d)1[3-9]\d[*xX]{4}\d{4}(?!\d)/],
  ['id_card', /(?<!\d)\d{17}[\dXx](?!\d)/],
  ['plate', /[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼][A-HJ-NP-Z][\s·]?[A-HJ-NP-Z0-9]{4,5}/],
  ['long_number', /(?<![A-Za-z0-9])\d{8,}(?![A-Za-z0-9])/],
  ['email', /[\w.+-]+@[\w-]+\.[\w.-]+/],
  ['url', /https?:\/\/\S+|www\.\S+/],
];

export function reject(status: number, reason: string, message: string, extra: Record<string, unknown> = {}): never {
  throw new HttpException({ reason, message, ...extra }, status);
}

function bad(reason: string, message: string): never {
  throw new BadRequestException({ reason, message });
}

/** 递归找出含个人信息样式的字符串路径(只返回路径和类型,不回显内容)。 */
export function findPii(value: unknown, path = '', out: Array<{ path: string; kind: string }> = []) {
  if (out.length >= 20) return out;
  if (typeof value === 'string') {
    for (const [kind, rx] of PII_PATTERNS) {
      if (rx.test(value)) {
        out.push({ path: path || '$', kind });
        break;
      }
    }
  } else if (Array.isArray(value)) {
    value.forEach((v, i) => findPii(v, `${path}[${i}]`, out));
  } else if (value && typeof value === 'object') {
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      findPii(v, path ? `${path}.${k}` : k, out);
    }
  }
  return out;
}

function isObject(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === 'object' && !Array.isArray(v);
}

function isoOrNull(v: unknown, field: string, required: boolean): string | null {
  if (v === null || v === undefined || v === '') {
    if (required) bad('gov_risk_case_invalid', `${field} 必填`);
    return null;
  }
  if (typeof v !== 'string' || Number.isNaN(Date.parse(v))) bad('gov_risk_case_invalid', `${field} 必须是 ISO 时间`);
  return new Date(v).toISOString();
}

/** 一条脱敏工单 → 规整后的记录;字段白名单之外的一律拒收。 */
export function validateCase(raw: unknown): GovRiskCase {
  if (!isObject(raw)) bad('gov_risk_case_invalid', '工单必须是对象');
  const unknown = Object.keys(raw).filter((k) => !CASE_KEYS.has(k));
  if (unknown.length) bad('gov_risk_case_unknown_field', `出现未约定的字段:${unknown.slice(0, 5).join(',')}`);
  if (typeof raw.case_id !== 'string' || !CASE_ID.test(raw.case_id)) {
    // 映射编号必须是本地密钥算出的短码;原始工单号进不来
    bad('gov_risk_case_id_invalid', '映射编号格式不对');
  }
  if (!(CHANNELS as readonly string[]).includes(String(raw.channel))) bad('gov_risk_case_invalid', `channel 只能是 ${CHANNELS.join('、')}`);
  const strings: Record<string, string> = {};
  for (const [k, max] of Object.entries(STRING_LIMITS)) {
    const v = raw[k] ?? '';
    if (typeof v !== 'string' || v.length > max) bad('gov_risk_case_invalid', `${k} 必须是不超过 ${max} 字的字符串`);
    strings[k] = v.trim();
  }
  const station = raw.station_code ?? null;
  if (station !== null && (typeof station !== 'string' || !STATION_CODE.test(station))) bad('gov_risk_case_invalid', 'station_code 格式不对');
  const user = raw.user_key ?? null;
  if (user !== null && (typeof user !== 'string' || !USER_KEY.test(user))) bad('gov_risk_case_invalid', 'user_key 格式不对');
  const text = raw.text ?? {};
  if (!isObject(text)) bad('gov_risk_case_invalid', 'text 必须是对象');
  const cleanText: Record<string, string> = {};
  for (const [k, v] of Object.entries(text)) {
    if (!TEXT_KEYS.has(k)) bad('gov_risk_case_unknown_field', `text 出现未约定的字段:${k}`);
    if (typeof v !== 'string' || v.length > MAX_TEXT_CHARS) bad('gov_risk_case_invalid', `text.${k} 必须是不超过 ${MAX_TEXT_CHARS} 字的字符串`);
    if (v.trim()) cleanText[k] = v.trim();
  }
  return {
    case_id: raw.case_id as string,
    channel: String(raw.channel),
    created_at: isoOrNull(raw.created_at, 'created_at', true) as string,
    closed_at: isoOrNull(raw.closed_at, 'closed_at', false),
    status: strings.status,
    resolution: strings.resolution,
    platform_risk: strings.platform_risk,
    template_risk: strings.template_risk,
    business_line: strings.business_line,
    dept_type: strings.dept_type,
    city: strings.city,
    problem_path: strings.problem_path,
    station_code: station as string | null,
    user_key: user as string | null,
    text: cleanText,
  };
}

export function validateReferenceCases(raw: unknown): ReferenceCase[] {
  if (raw === undefined || raw === null) return [];
  if (!Array.isArray(raw) || raw.length > 50) bad('gov_risk_reference_invalid', 'reference_cases 必须是不超过 50 项的数组');
  return raw.map((r) => {
    if (!isObject(r) || typeof r.id !== 'string' || !REF_ID.test(r.id)) bad('gov_risk_reference_invalid', '案例编号格式不对(RC-…)');
    if (!(String(r.symptom) in SYMPTOMS)) bad('gov_risk_reference_invalid', '案例现象不在词表内');
    const mechs = Array.isArray(r.mechanisms) ? r.mechanisms : [];
    if (mechs.length > 3 || mechs.some((m) => !(String(m) in MECHANISMS))) bad('gov_risk_reference_invalid', '案例机理不在词表内');
    const s = (v: unknown, n: number, field: string) => {
      if (v !== undefined && typeof v !== 'string') bad('gov_risk_reference_invalid', `${field} 必须是字符串`);
      if (String(v ?? '').length > n) bad('gov_risk_reference_invalid', `${field} 不能超过 ${n} 字`);
      return String(v ?? '').trim();
    };
    return {
      id: r.id, title: s(r.title, 60, 'title'), symptom: String(r.symptom), mechanisms: mechs.map(String),
      consequence: s(r.consequence, 60, 'consequence'), summary: s(r.summary, 300, 'summary'),
    };
  });
}

export interface UploadFinal {
  caseCount: number;
  dataWindow: { from: string; to: string } | null;
  sources: Array<{ channel: string; n: number }>;
  referenceCases: ReferenceCase[];
  client: string;
}

export interface CaseChunk {
  uploadId: string;
  index: number;
  total: number;
  cases: GovRiskCase[];
  final: UploadFinal | null;
}

/**
 * 分批上传的一批。最后一批带 final(总条数、数据范围、来源、对标案例),
 * 平台核对总条数后才把这次上传当成完整快照:不在快照里的旧工单删除,然后开始研判。
 */
export function validateCaseChunk(body: unknown): CaseChunk {
  if (!isObject(body)) bad('gov_risk_upload_invalid', '请求体必须是 JSON 对象');
  if (body.schema !== CASES_SCHEMA) bad('gov_risk_schema_mismatch', `只接受 ${CASES_SCHEMA}`);
  const known = new Set(['schema', 'upload_id', 'chunk', 'cases', 'final']);
  const unknown = Object.keys(body).filter((k) => !known.has(k));
  if (unknown.length) bad('gov_risk_upload_unknown_field', `出现未约定的字段:${unknown.slice(0, 5).join(',')}`);
  if (typeof body.upload_id !== 'string' || !UPLOAD_ID.test(body.upload_id)) bad('gov_risk_upload_invalid', 'upload_id 格式不对');
  const chunk = isObject(body.chunk) ? body.chunk : {};
  const index = Number(chunk.index);
  const total = Number(chunk.total);
  if (!Number.isInteger(total) || total < 1 || total > MAX_CHUNKS || !Number.isInteger(index) || index < 0 || index >= total) {
    bad('gov_risk_upload_invalid', 'chunk.index / chunk.total 不对');
  }
  const last = index === total - 1;
  if (!Array.isArray(body.cases) || body.cases.length > MAX_CASES_PER_CHUNK || (!body.cases.length && !last)) {
    bad('gov_risk_upload_invalid', `cases 必须是 1 到 ${MAX_CASES_PER_CHUNK} 条的数组`);
  }
  const cases = (body.cases as unknown[]).map(validateCase);
  const ids = new Set(cases.map((c) => c.case_id));
  if (ids.size !== cases.length) bad('gov_risk_upload_invalid', '同一批里有重复的映射编号');

  let final: UploadFinal | null = null;
  if (last) {
    const f = body.final;
    if (!isObject(f)) bad('gov_risk_upload_invalid', '最后一批必须带 final');
    const caseCount = Number(f.case_count);
    if (!Number.isInteger(caseCount) || caseCount < 0 || caseCount > MAX_CASES_PER_CHUNK * MAX_CHUNKS) {
      bad('gov_risk_upload_invalid', 'final.case_count 不对');
    }
    let dataWindow: UploadFinal['dataWindow'] = null;
    if (f.data_window !== undefined && f.data_window !== null) {
      const w = f.data_window as Record<string, unknown>;
      if (!isObject(w) || !MONTH.test(String(w.from)) || !MONTH.test(String(w.to))) bad('gov_risk_upload_invalid', 'final.data_window 格式不对');
      dataWindow = { from: String(w.from), to: String(w.to) };
    }
    const sources = Array.isArray(f.sources) ? f.sources : [];
    if (sources.length > 10 || sources.some((s) => !isObject(s) || !(CHANNELS as readonly string[]).includes(String(s.channel))
      || !Number.isInteger(Number(s.n)))) {
      bad('gov_risk_upload_invalid', 'final.sources 格式不对');
    }
    final = {
      caseCount,
      dataWindow,
      sources: sources.map((s) => ({ channel: String((s as any).channel), n: Number((s as any).n) })),
      referenceCases: validateReferenceCases(f.reference_cases),
      client: String(f.client ?? '').slice(0, 40),
    };
  } else if (body.final !== undefined) {
    bad('gov_risk_upload_invalid', '只有最后一批能带 final');
  }

  const hits: Array<{ case_id: string; path: string; kind: string }> = [];
  for (const c of cases) {
    for (const h of findPii(c)) hits.push({ case_id: c.case_id, ...h });
    if (hits.length >= 5) break;
  }
  if (final) for (const h of findPii(final.referenceCases)) hits.push({ case_id: '', path: `reference_cases${h.path}`, kind: h.kind });
  if (hits.length) {
    reject(HttpStatus.UNPROCESSABLE_ENTITY, 'gov_risk_case_contains_pii', '工单里出现个人信息样式的内容,整批拒收', {
      findings: hits.slice(0, 5),
    });
  }
  return { uploadId: body.upload_id as string, index, total, cases, final };
}

export function validateCaseIds(raw: unknown): string[] {
  const ids = String(raw ?? '').split(',').map((s) => s.trim()).filter(Boolean);
  if (!ids.length || ids.length > MAX_CASE_QUERY || ids.some((id) => !CASE_ID.test(id))) {
    bad('gov_risk_case_query_invalid', `ids 需为 1 到 ${MAX_CASE_QUERY} 个映射编号,用逗号分隔`);
  }
  return [...new Set(ids)];
}

export interface FeedbackDoc {
  candidates: Record<string, FeedbackEntry>;
}

export function validateFeedback(body: unknown): { revision: number; data: FeedbackDoc } {
  if (!body || typeof body !== 'object') bad('gov_risk_feedback_invalid', '请求体必须是对象');
  const { revision, data } = body as { revision?: unknown; data?: unknown };
  if (!Number.isInteger(revision) || (revision as number) < 0) bad('gov_risk_feedback_invalid', 'revision 必须是非负整数');
  if (!data || typeof data !== 'object' || Array.isArray(data)) bad('gov_risk_feedback_invalid', 'data 必须是对象');
  if (Buffer.byteLength(JSON.stringify(data), 'utf8') > MAX_FEEDBACK_BYTES) {
    reject(HttpStatus.PAYLOAD_TOO_LARGE, 'gov_risk_feedback_too_large', '跟进记录过大');
  }
  const raw = (data as { candidates?: unknown }).candidates;
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) bad('gov_risk_feedback_invalid', 'data.candidates 必须是对象');
  const entries = Object.entries(raw as Record<string, unknown>);
  if (entries.length > 2000) bad('gov_risk_feedback_invalid', '跟进记录条数过多');
  const candidates: FeedbackDoc['candidates'] = {};
  for (const [id, v] of entries) {
    if (!CANDIDATE_ID.test(id)) bad('gov_risk_candidate_id_invalid', '候选编号格式不对');
    const item = (v || {}) as Record<string, unknown>;
    const status = String(item.status || '');
    if (!(FEEDBACK_STATUSES as readonly string[]).includes(status)) bad('gov_risk_feedback_invalid', '跟进状态不在约定范围内');
    const note = typeof item.note === 'string' ? item.note.trim() : '';
    if (note.length > 500) bad('gov_risk_feedback_invalid', '备注不能超过 500 字');
    const updated = typeof item.updated_at === 'string' && !Number.isNaN(Date.parse(item.updated_at))
      ? new Date(item.updated_at).toISOString() : new Date().toISOString();
    candidates[id] = { status, note, updated_at: updated };
  }
  return { revision: revision as number, data: { candidates } };
}
