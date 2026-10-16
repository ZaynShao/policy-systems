import assert from 'node:assert/strict';
import { JwtAuthGuard } from '../src/common/guards/jwt-auth.guard';
import { classifyLlmError } from '../src/gov-risk/gov-risk.analysis';
import {
  type GovRiskCase,
  type Judgment,
  lastMonths,
  monthOf,
  parseJudgeBatch,
  shortCode,
  validateJudgment,
} from '../src/gov-risk/gov-risk.engine';
import {
  GovRiskService,
  SlidingWindowLimiter,
  type DatasetRow,
  type GovRiskCompletionClient,
  type GovRiskStore,
  type RunPatch,
  type RunRow,
} from '../src/gov-risk/gov-risk.service';
import { findPii, validateCaseChunk } from '../src/gov-risk/gov-risk.validate';
import { ruleSymptoms } from '../src/gov-risk/gov-risk.vocab';

const OWNER = 'zhangsan';
const TOKEN = 'a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4';
const DAY = 24 * 3600 * 1000;

class MemoryStore implements GovRiskStore {
  cases = new Map<string, { owner: string; record: GovRiskCase; uploadId: string; judgmentKey: string | null; judgment: Judgment | null }>();
  datasets = new Map<string, DatasetRow>();
  runs: RunRow[] = [];
  packages: Array<{ owner: string; payload: unknown; uploadedAt: Date }> = [];
  feedback = new Map<string, { revision: number; payload: unknown; updatedAt: Date }>();

  async upsertCases(owner: string, uploadId: string, cases: GovRiskCase[]) {
    for (const c of cases) {
      const old = this.cases.get(`${owner}|${c.case_id}`);
      this.cases.set(`${owner}|${c.case_id}`, { owner, record: c, uploadId, judgmentKey: old?.judgmentKey ?? null, judgment: old?.judgment ?? null });
    }
    return cases.length;
  }

  async countUpload(owner: string, uploadId: string) {
    return [...this.cases.values()].filter((c) => c.owner === owner && c.uploadId === uploadId).length;
  }

  async finalizeUpload(owner: string, uploadId: string, caseCount: number, meta: unknown) {
    let removed = 0;
    for (const [k, c] of this.cases) if (c.owner === owner && c.uploadId !== uploadId) { this.cases.delete(k); removed += 1; }
    const uploadedAt = new Date();
    this.datasets.set(owner, { uploadId, caseCount, meta, uploadedAt });
    return { removed, uploadedAt };
  }

  private mine(owner: string) {
    return [...this.cases.values()].filter((c) => c.owner === owner);
  }

  async listCases(owner: string) {
    return this.mine(owner).map((c) => ({ record: c.record, judgmentKey: c.judgmentKey, judgment: c.judgment }));
  }

  async getCases(owner: string, ids: string[]) {
    return this.mine(owner).filter((c) => ids.includes(c.record.case_id))
      .map((c) => ({ record: c.record, judgmentKey: c.judgmentKey, judgment: c.judgment }));
  }

  async saveJudgment(owner: string, caseId: string, key: string, judgment: Judgment) {
    const c = this.cases.get(`${owner}|${caseId}`);
    if (c) { c.judgmentKey = key; c.judgment = judgment; }
  }

  async getDataset(owner: string) {
    return this.datasets.get(owner) || null;
  }

  async purge(owner: string) {
    const cases = this.mine(owner).length;
    for (const [k, c] of this.cases) if (c.owner === owner) this.cases.delete(k);
    this.datasets.delete(owner);
    const packages = this.packages.filter((p) => p.owner === owner).length;
    this.packages = this.packages.filter((p) => p.owner !== owner);
    this.runs = this.runs.filter((r) => r.owner !== owner);
    return { cases, packages };
  }

  async createRun(owner: string, trigger: string) {
    const row: RunRow = {
      id: this.runs.length + 1, owner, trigger, status: 'queued', progress: {}, stats: null, error: null,
      createdAt: new Date(), startedAt: null, finishedAt: null,
    };
    this.runs.push(row);
    return row;
  }

  async updateRun(id: number, patch: RunPatch) {
    const r = this.runs.find((x) => x.id === id);
    if (r) Object.assign(r, patch);
  }

  async getRun(id: number) {
    return this.runs.find((x) => x.id === id) || null;
  }

  async latestRun(owner: string) {
    return this.runs.filter((r) => r.owner === owner).slice(-1)[0] || null;
  }

  async interruptStaleRuns() {
    return 0;
  }

  async packageHistory(owner: string, take: number) {
    return this.packages.filter((p) => p.owner === owner).reverse().slice(0, take);
  }

  async savePackage(owner: string, _schema: string, payload: unknown, _size: number, keep: number) {
    this.packages.push({ owner, payload, uploadedAt: new Date(Date.now() + this.packages.length) });
    const mine = this.packages.filter((p) => p.owner === owner);
    if (mine.length > keep) this.packages.splice(this.packages.indexOf(mine[0]), 1);
    return { id: this.packages.length, uploadedAt: new Date() };
  }

  async getFeedback(owner: string) {
    return this.feedback.get(owner) || null;
  }

  async putFeedback(owner: string, revision: number, payload: unknown) {
    const cur = this.feedback.get(owner);
    if ((cur?.revision || 0) !== revision) return null;
    const next = { revision: revision + 1, payload, updatedAt: new Date() };
    this.feedback.set(owner, next);
    return { revision: next.revision, updatedAt: next.updatedAt };
  }
}

/** 假模型:按正文关键词给出逐条研判,复核返回固定结论;记录调用次数 */
class FakeModel implements GovRiskCompletionClient {
  calls = { judge: 0, review: 0 };
  attempts = 0;
  failWith: (Error & { status?: number }) | null = null;

  async create(input: { messages: Array<{ role: string; content: string }> }) {
    this.attempts += 1;
    if (this.failWith) throw this.failWith;
    const system = input.messages[0].content;
    const user = input.messages[1].content;
    if (system.includes('投诉根因分析员')) {
      this.calls.judge += 1;
      const results = user.split(/\n\n(?=case_id:)/u).map((block) => {
        const id = /case_id:(GT-[A-Z2-7]{8})/u.exec(block)?.[1];
        const energy = block.includes('电量');
        return {
          case_id: id,
          symptoms: energy ? ['S_ENERGY_HIGH', 'NOT_A_CODE'] : ['S_INVOICE'],
          mechanisms: energy ? [{ code: 'M_METER_FAULT', confidence: 0.6 }, { code: 'M_DATA_CROSSTALK', confidence: 0.3 }] : [{ code: 'M_UNKNOWN', confidence: 0 }],
          clues: block.includes('不是我的') ? ['C_NOT_MY_SESSION'] : [],
          objects: { operator: block.includes('星星') ? '星星充电' : '', pile: '', stage: ['计量'] },
          systemic_likelihood: energy ? '高' : '低',
          systemic_reason: '多人反映同一现象',
          demands: block.includes('曝光') ? ['曝光'] : [],
          summary: energy ? '用户反映充电电量明显偏高' : '发票问题',
        };
      });
      return { content: '```json\n' + JSON.stringify({ results }) + '\n```', model: 'reported-model' };
    }
    this.calls.review += 1;
    return {
      content: JSON.stringify({
        title: '电量偏高反复出现', summary: '多个月持续出现,疑似计量或串单', confidence: '中', owner: '设备运维',
        mechanism_assessment: [{ code: 'M_METER_FAULT', likelihood: '高', evidence: '集中在同一场站' }],
        verification_steps: ['核对涉事桩计量检定记录'], why_early: '已有舆情先例',
      }),
      model: 'reported-model',
    };
  }
}

function ago(days: number) {
  return new Date(Date.now() - days * DAY).toISOString();
}

let seq = 0;
function makeCase(overrides: Partial<GovRiskCase> = {}): GovRiskCase {
  seq += 1;
  return {
    case_id: shortCode('GT-', `case-${seq}`, 8),
    channel: '政诉', created_at: ago(10), closed_at: ago(5), status: '已处理', resolution: '问题已解决',
    platform_risk: 'L5', template_risk: 'L5', business_line: '充电', dept_type: '市场监管', city: '北京市',
    problem_path: '充电/计费/电量异常', station_code: null, user_key: null,
    text: { description: '充电电量明显偏高,与车辆显示不符', demand: '要求退款' },
    ...overrides,
  };
}

function chunk(cases: GovRiskCase[], index: number, total: number, uploadId = 'upload-0001', final?: Record<string, unknown>) {
  return {
    schema: 'gov-risk-cases/v1', upload_id: uploadId, chunk: { index, total }, cases,
    ...(final ? { final } : {}),
  };
}

function reasonOf(error: unknown): string {
  const response = (error as any)?.getResponse?.();
  return String(response?.reason || (error as Error)?.message || '');
}

async function rejectsReason(operation: Promise<unknown> | (() => unknown), reason: string) {
  if (typeof operation === 'function') {
    assert.throws(operation as () => unknown, (e: unknown) => reasonOf(e) === reason);
  } else {
    await assert.rejects(operation, (e: unknown) => reasonOf(e) === reason);
  }
}

function internalContext(token?: string) {
  return {
    switchToHttp: () => ({
      getRequest: () => ({
        originalUrl: '/api/internal/gov-risk/cases', url: '/api/internal/gov-risk/cases', method: 'PUT',
        headers: token ? { 'x-gov-risk-agent-token': token } : {},
      }),
    }),
  } as any;
}

async function main() {
  process.env.NODE_ENV = 'test';
  process.env.LLM_MODEL = 'configured-model';
  const me = { username: OWNER };

  // ---- 引擎小件 ----
  assert.match(shortCode('SC-', 'x'), /^SC-[A-Z2-7]{6}$/);
  assert.equal(shortCode('SC-', 'x'), shortCode('SC-', 'x')); // 跨期稳定,跟进记录才挂得住
  assert.equal(monthOf(Date.parse('2026-05-31T16:30:00Z')), '2026-06'); // 按北京时间取月
  assert.deepEqual(lastMonths(Date.parse('2026-02-10T00:00:00Z'), 3), ['2026-02', '2026-01', '2025-12']);
  assert.equal(ruleSymptoms('充电度数明显偏高,要求退款', '电量异常')[0], 'S_ENERGY_HIGH'); // 诉求不盖过现象
  const sample = makeCase();
  const j = validateJudgment({ symptoms: ['BAD'], mechanisms: [{ code: 'M_FAKE', confidence: 3 }], systemic_likelihood: '极高' }, sample);
  assert.equal(j.primary_symptom, 'S_ENERGY_HIGH'); // 模型给的编码不在词表 → 用规则补
  assert.deepEqual(j.mechanisms, [{ code: 'M_UNKNOWN', confidence: 0 }]);
  assert.equal(j.systemic_likelihood, '中');
  assert.deepEqual(Object.keys(parseJudgeBatch('前言```json\n{"results":[{"case_id":"GT-AAAAAAAA"}]}\n```')), ['GT-AAAAAAAA']);
  assert.equal(classifyLlmError(Object.assign(new Error('Insufficient Balance'), { status: 402 })), 'ai_insufficient_balance');
  assert.equal(classifyLlmError(Object.assign(new Error('Request timed out'), { code: 'ETIMEDOUT' })), 'ai_timeout');
  assert.equal(classifyLlmError(Object.assign(new Error('x'), { status: 401 })), 'ai_auth_invalid');

  // ---- 上传校验:字段白名单、映射编号、个人信息拒收(不回显内容) ----
  const ok = validateCaseChunk(chunk([makeCase()], 0, 2));
  assert.equal(ok.final, null);
  await rejectsReason(() => validateCaseChunk({ ...chunk([makeCase()], 0, 1), final: undefined }), 'gov_risk_upload_invalid');
  await rejectsReason(() => validateCaseChunk(chunk([makeCase()], 0, 2, 'upload-0001', { case_count: 1 })), 'gov_risk_upload_invalid');
  await rejectsReason(() => validateCaseChunk(chunk([{ ...makeCase(), phone: '1' } as any], 0, 2)), 'gov_risk_case_unknown_field');
  await rejectsReason(() => validateCaseChunk(chunk([makeCase({ case_id: '1792033973' })], 0, 2)), 'gov_risk_case_id_invalid');
  await rejectsReason(() => validateCaseChunk(chunk([makeCase({ channel: '其他' })], 0, 2)), 'gov_risk_case_invalid');
  const dup = makeCase();
  await rejectsReason(() => validateCaseChunk(chunk([dup, dup], 0, 2)), 'gov_risk_upload_invalid');
  await rejectsReason(() => validateCaseChunk(chunk([makeCase()], 0, 1, 'upload-0001', {
    case_count: 1, reference_cases: [{ id: 'RC-1', title: 'x', symptom: 'S_FAKE', mechanisms: [] }],
  })), 'gov_risk_reference_invalid');
  for (const leak of ['联系电话13812345678', '手机 138****5678', '车牌京A12345', '订单号123456789012', 'https://boss.example/x', 'a@b.com']) {
    try {
      validateCaseChunk(chunk([makeCase({ text: { description: `用户称${leak}` } })], 0, 2));
      assert.fail(`应拒收:${leak}`);
    } catch (e) {
      assert.equal(reasonOf(e), 'gov_risk_case_contains_pii');
      assert.doesNotMatch(JSON.stringify((e as any).getResponse()), /1381234|5678|A12345|123456789012|boss\.example|a@b/u, '拒收原因不回显内容');
    }
  }
  assert.deepEqual(findPii({ a: ['ok', { b: '证件 11010119900101123X' }] }), [{ path: 'a[1].b', kind: 'id_card' }]);
  assert.deepEqual(findPii(makeCase()), []); // 映射编号、ISO 时间、场站编码不算个人信息

  // ---- 所有者校验:未配置 → 503;非本人 → 403;未登录 → 401 ----
  const store = new MemoryStore();
  const model = new FakeModel();
  const service = new GovRiskService(store, model, () => true);
  delete process.env.GOV_RISK_OWNER_USERNAME;
  await rejectsReason(service.getPackage(me), 'owner_not_configured');
  await rejectsReason(service.uploadCases(chunk([makeCase()], 0, 1)), 'owner_not_configured');
  process.env.GOV_RISK_OWNER_USERNAME = 'ZhangSan'; // 大小写不敏感
  await rejectsReason(service.getPackage({ username: 'lisi' }), 'not_owner');
  await rejectsReason(service.getPackage(undefined), 'login_required');
  await rejectsReason(service.requestRun(me), 'no_dataset');

  // ---- 合成数据:同一场站电量偏高每月都有、关单后仍在出现;另有少量发票问题 ----
  const energy = [5, 35, 65, 95, 125, 155, 20, 50].map((d, i) => makeCase({
    created_at: ago(d), closed_at: ago(d - 2),
    station_code: i < 4 ? 'ST-AAAAAA' : 'ST-BBBBBB',
    text: { description: `充电电量明显偏高${i % 2 ? ',星星充电的桩' : ''}${i === 3 ? ',这不是我的订单' : ''}`, demand: i === 0 ? '要求曝光' : '要求退款' },
  }));
  const invoices = [3, 40, 80].map((d) => makeCase({
    created_at: ago(d), problem_path: '充电/发票/发票', text: { description: '开不了发票' }, dept_type: '税务',
  }));
  const all = [...energy, ...invoices];
  const final = {
    case_count: all.length, data_window: { from: '2026-04', to: '2026-10' }, sources: [{ channel: '政诉', n: all.length }],
    reference_cases: [{ id: 'RC-1', title: '充电度数过高引发舆情', symptom: 'S_ENERGY_HIGH', mechanisms: ['M_METER_FAULT'], consequence: '舆情+监管施压', summary: '设备电路老化' }],
    client: 'gtr/2',
  };

  // 中途断过的上传不当快照,不删旧数据也不研判
  const stray = [makeCase(), makeCase()];
  await rejectsReason(service.uploadCases(chunk(stray, 1, 2, 'upload-broken', { case_count: 5 })), 'gov_risk_upload_incomplete');
  assert.equal(store.runs.length, 0);

  const first = await service.uploadCases(chunk(all.slice(0, 6), 0, 2));
  assert.deepEqual(first, { stored: 6, final: false });
  const done = await service.uploadCases(chunk(all.slice(6), 1, 2, 'upload-0001', final));
  assert.equal(done.final, true);
  assert.equal(done.total, all.length);
  assert.equal(done.removed, stray.length); // 断掉的那次上传留下的工单不在本次快照里,删掉
  assert.ok(done.run && done.run.status === 'queued');
  await service.whenIdle();

  const view = await service.getPackage(me);
  const pkg = view.package as any;
  assert.equal(pkg.schema, 'gov-risk/v2');
  assert.equal(view.run?.status, 'succeeded');
  assert.equal(view.dataset?.caseCount, all.length);
  assert.equal(pkg.method.judged_by_model, all.length);
  assert.equal(pkg.method.judged_by_rules, 0);
  assert.equal(pkg.method.model, 'reported-model'); // 记通道自报的真实模型名
  assert.equal(model.calls.judge, Math.ceil(all.length / 6));
  const top = pkg.candidates.find((c: any) => c.level === 'symptom' && c.symptom === 'S_ENERGY_HIGH');
  assert.equal(top.band, '高');
  assert.ok(top.stats.recurring_after_close, '关单后仍在出现');
  assert.equal(top.stats.stations, 2);
  assert.equal(top.reference_matches[0].case_id, 'RC-1');
  assert.equal(top.review.title, '电量偏高反复出现');
  assert.ok(top.clues.some((c: any) => c.code === 'C_NOT_MY_SESSION'));
  const station = pkg.candidates.find((c: any) => c.object_type === '场站' && c.object_code === 'ST-AAAAAA');
  assert.ok(station && station.case_ids.length === 4, '同一场站 ≥2 条成对象级候选');
  const operator = pkg.candidates.find((c: any) => c.object_type === '运营商');
  assert.equal(operator?.object_label, '星星充电');
  assert.ok(pkg.overview.matrix.some((x: any) => x.symptom === 'S_INVOICE' && x.dept_type === '税务' && x.n === 3));

  // ---- 下钻:只给脱敏记录与逐条研判 ----
  const drill = await service.getCases(me, top.case_ids.slice(0, 3).join(','));
  assert.equal(drill.cases.length, 3);
  assert.equal(drill.cases[0].judgment?.symptoms[0].code, 'S_ENERGY_HIGH');
  assert.equal('user_key' in drill.cases[0], false);
  await rejectsReason(service.getCases(me, '1792033973'), 'gov_risk_case_query_invalid');

  // ---- 跟进:乐观锁;标成已修复后同类再出现记复发 ----
  const saved = await service.putFeedback(me, {
    revision: 0, data: { candidates: { [top.id]: { status: 'fixed', note: ' 已换桩 ', updated_at: ago(30) } } },
  });
  assert.equal(saved.revision, 1);
  assert.equal(saved.data.candidates[top.id].note, '已换桩');
  await rejectsReason(service.putFeedback(me, { revision: 0, data: { candidates: {} } }), 'revision_conflict');
  await rejectsReason(service.putFeedback(me, { revision: 1, data: { candidates: { [top.id]: { status: 'done' } } } }), 'gov_risk_feedback_invalid');
  await rejectsReason(service.putFeedback(me, { revision: 1, data: { candidates: { 'bad-id': { status: 'new' } } } }), 'gov_risk_candidate_id_invalid');

  // ---- 手动重跑:正文没变就复用逐条研判,不再调模型 ----
  const judgeCalls = model.calls.judge;
  const rerun = await service.requestRun(me);
  assert.equal(rerun.queued, false);
  await service.whenIdle();
  assert.equal(model.calls.judge, judgeCalls);
  const again = (await service.getPackage(me)).package as any;
  assert.equal(again.method.judged_cached, all.length);
  const fixed = again.candidates.find((c: any) => c.id === top.id);
  assert.equal(fixed.status, 'fixed');
  assert.equal(fixed.recurred_after_fix, 2); // 30 天前标已修复,之后又来了 2 条(5 天前、20 天前)
  assert.ok(fixed.observing_until);
  assert.equal(again.candidates[0].id, top.id, '修复后复发的候选置顶');

  // ---- 模型通道欠费:立即熔断,全部规则兜底,结果包如实标注 ----
  const brokeModel = new FakeModel();
  brokeModel.failWith = Object.assign(new Error('Insufficient Balance'), { status: 402 });
  const broke = new GovRiskService(new MemoryStore(), brokeModel, () => true);
  const fresh = [makeCase(), makeCase(), makeCase(), makeCase(), makeCase(), makeCase(), makeCase()];
  await broke.uploadCases(chunk(fresh, 0, 1, 'upload-0002', { case_count: fresh.length }));
  await broke.whenIdle();
  const brokePkg = (await broke.getPackage(me)).package as any;
  assert.equal(brokePkg.method.breaker, 'ai_insufficient_balance');
  assert.equal(brokePkg.method.judged_by_rules, fresh.length);
  assert.ok(brokePkg.method.errors.includes('ai_insufficient_balance'));
  assert.ok(brokeModel.attempts <= 2, '熔断后不再请求(并发中的批次除外),也不做复核');

  // ---- 没配模型密钥:不请求,全部规则兜底 ----
  const offline = new GovRiskService(new MemoryStore(), new FakeModel(), () => false);
  await offline.uploadCases(chunk([makeCase()], 0, 1, 'upload-0003', { case_count: 1 }));
  await offline.whenIdle();
  const offPkg = (await offline.getPackage(me)).package as any;
  assert.equal(offPkg.method.breaker, 'ai_not_configured');
  assert.equal(offPkg.method.judged_by_rules, 1);

  // ---- 撤回:要显式确认;删工单与结果包,保留跟进记录 ----
  await rejectsReason(service.purge({}), 'gov_risk_purge_unconfirmed');
  const purged = await service.purge({ confirm: 'delete-all' });
  assert.equal(purged.cases, all.length);
  assert.equal((await service.getPackage(me)).package, null);
  assert.equal((await service.getFeedback(me)).revision, 1);

  // ---- 限流 ----
  let t = 0;
  const limiter = new SlidingWindowLimiter(2, 1000, () => t);
  assert.equal(limiter.take(), true);
  assert.equal(limiter.take(), true);
  assert.equal(limiter.take(), false);
  t = 1001;
  assert.equal(limiter.take(), true);

  // ---- 内部 token:对的放行,错的、未配置的、弱口令都拒 ----
  process.env.GOV_RISK_AGENT_TOKEN = TOKEN;
  assert.equal(new JwtAuthGuard().canActivate(internalContext(TOKEN)), true);
  assert.throws(() => new JwtAuthGuard().canActivate(internalContext('wrong-token')), (e: unknown) => (e as any)?.getStatus?.() === 401);
  assert.throws(() => new JwtAuthGuard().canActivate(internalContext()), (e: unknown) => (e as any)?.getStatus?.() === 401);
  process.env.GOV_RISK_AGENT_TOKEN = 'placeholder-placeholder-placeholder-123';
  assert.throws(() => new JwtAuthGuard().canActivate(internalContext('placeholder-placeholder-placeholder-123')),
    (e: unknown) => (e as any)?.getStatus?.() === 401);
  delete process.env.GOV_RISK_AGENT_TOKEN;
  assert.throws(() => new JwtAuthGuard().canActivate(internalContext(TOKEN)), (e: unknown) => (e as any)?.getStatus?.() === 401);

  console.log('gov-risk service tests passed');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
