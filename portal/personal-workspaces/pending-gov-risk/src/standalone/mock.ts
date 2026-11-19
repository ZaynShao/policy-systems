// 独立版演示模式的接口替身:不连后端,用内置演示数据回答两页要调的接口,返回格式与原接口一致
// (接口约定见 docs/WORKFLOW-gov-risk-workbench-v1.0.md「接口契约」,规则照 services/guardian-backend/src/gov-risk)。
// - 政诉预判(原生脚本,用 fetch):/guardian/api/gov-risk/{package,run,runs,cases,feedback};
// - 总览(axios,前缀 /heng/api/v1):/gov-risk/{package,feedback} 读同一份数据;原平台的政策知识库、月刊、
//   源质量审核、采集队列和政策解读服务不在独立版里,一律回"独立版不含",总览会在对应卡片上写明没读到。
// 写操作(保存跟进、重新研判)照原接口的规则只记在本页内存里,刷新即还原。
// "重新研判"不重跑引擎(引擎是后端代码,页面里跑不了):沿用录入时的逐条研判和统计,只按本页的跟进状态重算
// 跟进相关的几项(状态、修复后复发、观察期、排序、高/中优先计数),相当于平台在数据没变时马上重跑一次。
import { AxiosError, type AxiosAdapter, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios';
import { http } from '@/api/client';

type Json = Record<string, any>;

export interface DemoData {
  recorded_at: string;
  /** GET /api/gov-risk/package 的返回 */
  result: Json;
  /** GET /api/gov-risk/cases 能读到的全部脱敏工单(含逐条研判) */
  cases: { cases: Json[] };
  /** GET /api/gov-risk/feedback 的初始状态 */
  feedback: { revision: number; data: { candidates: Record<string, Json> }; updatedAt: string | null };
}

const STATUSES = ['new', 'investigating', 'confirmed', 'fixing', 'fixed', 'observing', 'dismissed', 'closed'];
const CLOSED_STATES = new Set(['fixed', 'observing', 'closed']);
const CANDIDATE_ID = /^SC-[A-Z2-7]{6}$/;
const CASE_ID = /^GT-[A-Z2-7]{8}$/;
const MAX_CASE_QUERY = 50;
const MAX_FEEDBACK_BYTES = 512 * 1024;
const OBSERVATION_DAYS = 60;
const DAY_MS = 24 * 3600 * 1000;
const CN_OFFSET_MS = 8 * 3600 * 1000;

class DemoHttpError extends Error {
  constructor(readonly status: number, readonly reason: string, message: string) { super(message); }
}
function fail(status: number, reason: string, message: string): never {
  throw new DemoHttpError(status, reason, message);
}
const clone = <T>(x: T): T => JSON.parse(JSON.stringify(x));
const nowIso = () => new Date().toISOString();

// 与 gov-risk.validate.ts 的 validateFeedback 同样的规则
function validFeedback(body: unknown): { revision: number; data: { candidates: Record<string, Json> } } {
  const b = (body && typeof body === 'object' ? body : fail(400, 'gov_risk_feedback_invalid', '请求体必须是对象')) as Json;
  if (!Number.isInteger(b.revision) || b.revision < 0) fail(400, 'gov_risk_feedback_invalid', 'revision 必须是非负整数');
  if (!b.data || typeof b.data !== 'object' || Array.isArray(b.data)) fail(400, 'gov_risk_feedback_invalid', 'data 必须是对象');
  if (new Blob([JSON.stringify(b.data)]).size > MAX_FEEDBACK_BYTES) fail(413, 'gov_risk_feedback_too_large', '跟进记录过大');
  const raw = b.data.candidates;
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) fail(400, 'gov_risk_feedback_invalid', 'data.candidates 必须是对象');
  const entries = Object.entries(raw as Record<string, Json>);
  if (entries.length > 2000) fail(400, 'gov_risk_feedback_invalid', '跟进记录条数过多');
  const candidates: Record<string, Json> = {};
  for (const [id, v] of entries) {
    if (!CANDIDATE_ID.test(id)) fail(400, 'gov_risk_candidate_id_invalid', '候选编号格式不对');
    const item = (v || {}) as Json;
    const status = String(item.status || '');
    if (!STATUSES.includes(status)) fail(400, 'gov_risk_feedback_invalid', '跟进状态不在约定范围内');
    const note = typeof item.note === 'string' ? item.note.trim() : '';
    if (note.length > 500) fail(400, 'gov_risk_feedback_invalid', '备注不能超过 500 字');
    const updated = typeof item.updated_at === 'string' && !Number.isNaN(Date.parse(item.updated_at))
      ? new Date(item.updated_at).toISOString() : nowIso();
    candidates[id] = { status, note, updated_at: updated };
  }
  return { revision: b.revision, data: { candidates } };
}

export function createDemoApi(data: DemoData) {
  const recorded = clone(data.result);
  let view = clone(data.result);
  let feedback = clone(data.feedback);
  const caseById = new Map(data.cases.cases.map((c) => [c.case_id as string, c]));
  let pending: { run: Json; polls: number } | null = null;

  // 跟进相关的几项,规则同 gov-risk.engine.ts 的 buildCandidates / buildPackage
  function applyFeedback(base: Json): Json {
    const pkg = clone(base);
    const fb = feedback.data.candidates || {};
    for (const c of pkg.candidates as Json[]) {
      const state = fb[c.id] || {};
      const status = state.status || 'new';
      const since = Date.parse(state.updated_at || '') || 0;
      let recurred = 0;
      let until: string | null = null;
      if (CLOSED_STATES.has(status) && since) {
        recurred = (c.case_ids as string[]).filter((id) => Date.parse(caseById.get(id)?.created_at || '') > since).length;
        until = new Date(since + OBSERVATION_DAYS * DAY_MS + CN_OFFSET_MS).toISOString().slice(0, 10);
      }
      Object.assign(c, { status, recurred_after_fix: recurred, observing_until: until });
    }
    (pkg.candidates as Json[]).sort((a, b) => Number(a.status === 'dismissed') - Number(b.status === 'dismissed')
      || b.recurred_after_fix - a.recurred_after_fix || b.score - a.score);
    const active = (pkg.candidates as Json[]).filter((c) => c.status !== 'dismissed');
    pkg.kpi = {
      ...pkg.kpi,
      candidates_high: active.filter((c) => c.band === '高').length,
      candidates_medium: active.filter((c) => c.band === '中').length,
      recurred_after_fix: (pkg.candidates as Json[]).filter((c) => c.recurred_after_fix).length,
    };
    return pkg;
  }

  // 页面每 4 秒轮询一次:第一次看到"研判中",第二次完成(本机录入时没配模型,逐条研判那一步没有进度数字)
  function advance() {
    if (!pending) return;
    pending.polls += 1;
    const run = pending.run;
    if (pending.polls === 1) {
      Object.assign(run, { status: 'running', startedAt: nowIso(), progress: { stage: 'judge', done: 0, total: 0 } });
      return;
    }
    const t = nowIso();
    const pkg = applyFeedback(recorded.package);
    pkg.generated_at = t;
    pkg.run = { id: run.id, trigger: run.trigger };
    Object.assign(run, { status: 'succeeded', finishedAt: t, progress: { stage: 'done' }, stats: clone(recorded.run?.stats ?? null) });
    view = {
      ...view,
      package: pkg,
      generatedAt: t,
      history: [{ generatedAt: t, kpi: pkg.kpi, dataWindow: pkg.data_window }, ...(view.history || [])].slice(0, 10),
      run: clone(run),
    };
    pending = null;
  }

  function route(method: string, path: string, body: unknown): { status: number; body: Json } {
    const [p, query = ''] = path.split('?');
    if (method === 'GET' && p === '/package') return { status: 200, body: clone({ ...view, run: pending ? pending.run : view.run }) };
    if (method === 'GET' && p === '/run') {
      advance();
      return { status: 200, body: { run: clone(pending ? pending.run : view.run), dataset: clone(view.dataset) } };
    }
    if (method === 'POST' && p === '/runs') {
      if (!view.dataset) fail(409, 'no_dataset', '平台上还没有工单数据,先在本机上传');
      if (pending) return { status: 202, body: { run: clone(pending.run), queued: true } };
      const run = { id: Number(view.run?.id || 0) + 1, trigger: 'manual', status: 'queued', progress: {}, stats: null, error: null,
        createdAt: nowIso(), startedAt: null, finishedAt: null };
      pending = { run, polls: 0 };
      return { status: 202, body: { run: clone(run), queued: false } };
    }
    if (method === 'GET' && p === '/cases') {
      const raw = new URLSearchParams(query).get('ids') || '';
      const ids = [...new Set(raw.split(',').map((s) => s.trim()).filter(Boolean))];
      if (!ids.length || ids.length > MAX_CASE_QUERY || ids.some((id) => !CASE_ID.test(id))) {
        fail(400, 'gov_risk_case_query_invalid', `ids 需为 1 到 ${MAX_CASE_QUERY} 个映射编号,用逗号分隔`);
      }
      const cases = ids.map((id) => caseById.get(id)).filter((c): c is Json => !!c)
        .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
      return { status: 200, body: { cases: clone(cases) } };
    }
    if (method === 'GET' && p === '/feedback') return { status: 200, body: clone(feedback) };
    if (method === 'PUT' && p === '/feedback') {
      const next = validFeedback(body);
      if (next.revision !== feedback.revision) fail(409, 'revision_conflict', '跟进记录已在别处更新,请重新加载后再改');
      const t = nowIso();
      feedback = { revision: next.revision + 1, data: next.data, updatedAt: t };
      return { status: 200, body: { revision: feedback.revision, data: clone(next.data), updatedAt: t } };
    }
    fail(404, 'not_found', '没有这个接口');
  }

  function handle(method: string, path: string, body: unknown): { status: number; body: Json } {
    try {
      return route(method.toUpperCase(), path, body);
    } catch (e) {
      if (e instanceof DemoHttpError) return { status: e.status, body: { reason: e.reason, message: e.message } };
      throw e;
    }
  }

  return { handle };
}

const NOT_HERE: Array<[string, string]> = [
  ['/knowledge', '政策知识库'], ['/monthlies', '政策月刊'], ['/l1-review', '源质量审核'], ['/crawler-rules', '采集队列'],
];
const notInStandalone = (what: string) => `独立版不含这块(原平台的${what})`;

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** 装上接口替身:政诉预判的 fetch、总览的 axios。 */
export function installDemo(data: DemoData) {
  const api = createDemoApi(data);
  const GOV = '/guardian/api/gov-risk';

  const realFetch = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : 'href' in input ? input.href : input.url;
    if (url.startsWith(GOV + '/')) {
      await wait(120);
      const method = init?.method || (typeof input === 'object' && 'method' in input ? input.method : 'GET');
      const body = typeof init?.body === 'string' && init.body ? JSON.parse(init.body) : undefined;
      const res = api.handle(method, url.slice(GOV.length), body);
      return new Response(JSON.stringify(res.body), { status: res.status, headers: { 'Content-Type': 'application/json' } });
    }
    if (url.startsWith('/policy-qa/')) throw new TypeError(notInStandalone('政策解读问答服务'));
    return realFetch(input, init);
  };

  const adapter: AxiosAdapter = async (config: InternalAxiosRequestConfig) => {
    await wait(120);
    const url = config.url || '';
    const respond = (status: number, body: Json): AxiosResponse => ({ data: body, status, statusText: String(status), headers: {}, config, request: {} });
    if (url.startsWith('/gov-risk/')) {
      const query = config.params ? '?' + new URLSearchParams(config.params as Record<string, string>).toString() : '';
      const body = typeof config.data === 'string' && config.data ? JSON.parse(config.data) : config.data;
      const res = api.handle(config.method || 'get', url.slice('/gov-risk'.length) + query, body);
      if (res.status < 400) return respond(res.status, res.body);
      throw new AxiosError(res.body.message, String(res.status), config, null, respond(res.status, res.body));
    }
    const what = NOT_HERE.find(([prefix]) => url.startsWith(prefix))?.[1] || '这个接口';
    throw new AxiosError(notInStandalone(what), 'ERR_NOT_IN_STANDALONE', config, null, respond(404, { msg: notInStandalone(what) }));
  };
  http.defaults.adapter = adapter;
  return api;
}
