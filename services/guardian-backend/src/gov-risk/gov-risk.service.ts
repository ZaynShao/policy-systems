import { HttpStatus, Injectable, Logger, OnModuleInit, ServiceUnavailableException, UnauthorizedException } from '@nestjs/common';
import { createLlmClient, llmModel, resolveLlmChannel } from '../common/llm-client';
import { PrismaService } from '../prisma/prisma.service';
import { type ChatMessage, type StoredCase, runAnalysis } from './gov-risk.analysis';
import { CLUES, MECHANISMS, SYMPTOMS } from './gov-risk.vocab';
import { type GovRiskCase, type Judgment, type ReferenceCase, RESULT_SCHEMA } from './gov-risk.engine';
import {
  type FeedbackDoc,
  reject,
  validateCaseChunk,
  validateCaseIds,
  validateFeedback,
} from './gov-risk.validate';

/**
 * 工单系统性原因研判(个人工作台 pending-gov-risk 的后端)。
 *
 * 分工(2026-10-15 定):本地服务只做取数、脱敏和简单清洗,把脱敏工单分批传上来;
 * 研判(规则初筛、模型逐条标注、归并打分、候选复核)在这里跑,结果包给页面读。
 *
 * 两类调用方:
 * - 本地服务(内网 Mac):带 GOV_RISK_AGENT_TOKEN 调 /api/internal/gov-risk/*,上传脱敏工单、看研判进度、
 *   取结果包(本地拿映射表回查真实工单);鉴权在 JwtAuthGuard。
 * - 所有者本人:平台登录后调 /api/gov-risk/*,读结果包、下钻脱敏工单、写跟进记录、手动重跑;
 *   只认 GOV_RISK_OWNER_USERNAME。
 *
 * 日志只记条数、耗时、模型名和失败原因码,不记工单正文和模型回答。
 */

export interface RunRow {
  id: number;
  owner: string;
  trigger: string;
  status: string;
  progress: unknown;
  stats: unknown;
  error: string | null;
  createdAt: Date;
  startedAt: Date | null;
  finishedAt: Date | null;
}

export interface DatasetRow {
  uploadId: string;
  caseCount: number;
  meta: unknown;
  uploadedAt: Date;
}

export type RunPatch = Partial<Pick<RunRow, 'status' | 'progress' | 'stats' | 'error' | 'startedAt' | 'finishedAt'>>;

export interface GovRiskStore {
  upsertCases(owner: string, uploadId: string, cases: GovRiskCase[]): Promise<number>;
  countUpload(owner: string, uploadId: string): Promise<number>;
  /** 把这次上传当成完整快照:删掉不在快照里的旧工单,记下数据集信息 */
  finalizeUpload(owner: string, uploadId: string, caseCount: number, meta: unknown): Promise<{ removed: number; uploadedAt: Date }>;
  listCases(owner: string): Promise<StoredCase[]>;
  getCases(owner: string, ids: string[]): Promise<StoredCase[]>;
  saveJudgment(owner: string, caseId: string, key: string, judgment: Judgment): Promise<void>;
  getDataset(owner: string): Promise<DatasetRow | null>;
  /** 撤回:删工单、数据集、结果包和运行记录;所有者自己写的跟进记录保留 */
  purge(owner: string): Promise<{ cases: number; packages: number }>;
  createRun(owner: string, trigger: string): Promise<RunRow>;
  updateRun(id: number, patch: RunPatch): Promise<void>;
  getRun(id: number): Promise<RunRow | null>;
  latestRun(owner: string): Promise<RunRow | null>;
  /** 进程重启时把未跑完的运行标成中断 */
  interruptStaleRuns(): Promise<number>;
  packageHistory(owner: string, take: number): Promise<Array<{ payload: unknown; uploadedAt: Date }>>;
  savePackage(owner: string, schema: string, payload: unknown, sizeBytes: number, keep: number): Promise<{ id: number; uploadedAt: Date }>;
  getFeedback(owner: string): Promise<{ revision: number; payload: unknown; updatedAt: Date } | null>;
  /** revision 不匹配返回 null(乐观锁冲突) */
  putFeedback(owner: string, revision: number, payload: unknown, updatedBy: string): Promise<{ revision: number; updatedAt: Date } | null>;
}

export interface GovRiskCompletionClient {
  create(input: { messages: ChatMessage[]; maxTokens: number; temperature: number; model: string; timeoutMs: number }): Promise<{ content: string; model: string }>;
}

class OpenAIGovRiskClient implements GovRiskCompletionClient {
  async create(input: { messages: ChatMessage[]; maxTokens: number; temperature: number; model: string; timeoutMs: number }) {
    let client;
    try {
      client = createLlmClient();
    } catch {
      throw Object.assign(new Error('平台模型密钥未配置'), { code: 'ai_not_configured' });
    }
    const response = await client.chat.completions.create({
      model: input.model,
      messages: input.messages,
      max_tokens: input.maxTokens,
      temperature: input.temperature,
      response_format: { type: 'json_object' },
    }, { timeout: input.timeoutMs });
    return { content: response.choices[0]?.message?.content || '', model: response.model || input.model };
  }
}

/** 进程内滑动窗口限流;防 token 泄露后被拿去刷上传和模型额度。 */
export class SlidingWindowLimiter {
  private hits: number[] = [];

  constructor(private readonly limit: number, private readonly windowMs: number, private readonly now = () => Date.now()) {}

  take(): boolean {
    const t = this.now();
    this.hits = this.hits.filter((x) => t - x < this.windowMs);
    if (this.hits.length >= this.limit) return false;
    this.hits.push(t);
    return true;
  }
}

@Injectable()
export class PrismaGovRiskStore implements GovRiskStore {
  constructor(private readonly prisma: PrismaService) {}

  async upsertCases(owner: string, uploadId: string, cases: GovRiskCase[]) {
    await this.prisma.$transaction(cases.map((c) => this.prisma.govRiskCase.upsert({
      where: { owner_caseId: { owner, caseId: c.case_id } },
      create: { owner, caseId: c.case_id, channel: c.channel, occurredAt: new Date(c.created_at), payload: c as object, uploadId },
      update: { channel: c.channel, occurredAt: new Date(c.created_at), payload: c as object, uploadId },
    })));
    return cases.length;
  }

  async countUpload(owner: string, uploadId: string) {
    return this.prisma.govRiskCase.count({ where: { owner, uploadId } });
  }

  async finalizeUpload(owner: string, uploadId: string, caseCount: number, meta: unknown) {
    const [removed, dataset] = await this.prisma.$transaction([
      this.prisma.govRiskCase.deleteMany({ where: { owner, uploadId: { not: uploadId } } }),
      this.prisma.govRiskDataset.upsert({
        where: { owner },
        create: { owner, uploadId, caseCount, meta: meta as object },
        update: { uploadId, caseCount, meta: meta as object, uploadedAt: new Date() },
      }),
    ]);
    return { removed: removed.count, uploadedAt: dataset.uploadedAt };
  }

  private toStored(row: { payload: unknown; judgmentKey: string | null; judgment: unknown }): StoredCase {
    return { record: row.payload as GovRiskCase, judgmentKey: row.judgmentKey, judgment: (row.judgment as Judgment) || null };
  }

  async listCases(owner: string) {
    const rows = await this.prisma.govRiskCase.findMany({
      where: { owner }, orderBy: { occurredAt: 'asc' }, select: { payload: true, judgmentKey: true, judgment: true },
    });
    return rows.map((r) => this.toStored(r));
  }

  async getCases(owner: string, ids: string[]) {
    const rows = await this.prisma.govRiskCase.findMany({
      where: { owner, caseId: { in: ids } }, orderBy: { occurredAt: 'desc' },
      select: { payload: true, judgmentKey: true, judgment: true },
    });
    return rows.map((r) => this.toStored(r));
  }

  async saveJudgment(owner: string, caseId: string, key: string, judgment: Judgment) {
    await this.prisma.govRiskCase.updateMany({ where: { owner, caseId }, data: { judgmentKey: key, judgment: judgment as object } });
  }

  async getDataset(owner: string) {
    return this.prisma.govRiskDataset.findUnique({ where: { owner } });
  }

  async purge(owner: string) {
    const [cases, , packages] = await this.prisma.$transaction([
      this.prisma.govRiskCase.deleteMany({ where: { owner } }),
      this.prisma.govRiskDataset.deleteMany({ where: { owner } }),
      this.prisma.govRiskPackage.deleteMany({ where: { owner } }),
      this.prisma.govRiskRun.deleteMany({ where: { owner } }),
    ]);
    return { cases: cases.count, packages: packages.count };
  }

  async createRun(owner: string, trigger: string) {
    const row = await this.prisma.govRiskRun.create({ data: { owner, trigger, status: 'queued' } });
    const old = await this.prisma.govRiskRun.findMany({ where: { owner }, orderBy: { id: 'desc' }, skip: 50, select: { id: true } });
    if (old.length) await this.prisma.govRiskRun.deleteMany({ where: { id: { in: old.map((o) => o.id) } } });
    return row;
  }

  async updateRun(id: number, patch: RunPatch) {
    await this.prisma.govRiskRun.updateMany({ where: { id }, data: patch as any });
  }

  async getRun(id: number) {
    return this.prisma.govRiskRun.findUnique({ where: { id } });
  }

  async latestRun(owner: string) {
    return this.prisma.govRiskRun.findFirst({ where: { owner }, orderBy: { id: 'desc' } });
  }

  async interruptStaleRuns() {
    const res = await this.prisma.govRiskRun.updateMany({
      where: { status: { in: ['queued', 'running'] } },
      data: { status: 'interrupted', finishedAt: new Date(), error: '平台服务重启,本次研判中断;请在页面重新研判' },
    });
    return res.count;
  }

  async packageHistory(owner: string, take: number) {
    return this.prisma.govRiskPackage.findMany({
      where: { owner }, orderBy: { uploadedAt: 'desc' }, take, select: { payload: true, uploadedAt: true },
    });
  }

  async savePackage(owner: string, schema: string, payload: unknown, sizeBytes: number, keep: number) {
    const row = await this.prisma.govRiskPackage.create({
      data: { owner, schema, payload: payload as object, sizeBytes }, select: { id: true, uploadedAt: true },
    });
    const old = await this.prisma.govRiskPackage.findMany({
      where: { owner }, orderBy: { uploadedAt: 'desc' }, skip: keep, select: { id: true },
    });
    if (old.length) await this.prisma.govRiskPackage.deleteMany({ where: { id: { in: old.map((o) => o.id) } } });
    return row;
  }

  async getFeedback(owner: string) {
    return this.prisma.govRiskFeedback.findUnique({ where: { owner } });
  }

  async putFeedback(owner: string, revision: number, payload: unknown, updatedBy: string) {
    if (revision === 0) {
      try {
        const row = await this.prisma.govRiskFeedback.create({
          data: { owner, revision: 1, payload: payload as object, updatedBy },
        });
        return { revision: row.revision, updatedAt: row.updatedAt };
      } catch {
        return null; // 已有记录:并发首次写入或页面拿的是旧 revision
      }
    }
    const res = await this.prisma.govRiskFeedback.updateMany({
      where: { owner, revision },
      data: { revision: { increment: 1 }, payload: payload as object, updatedBy },
    });
    if (res.count !== 1) return null;
    const row = await this.prisma.govRiskFeedback.findUnique({ where: { owner } });
    return row ? { revision: row.revision, updatedAt: row.updatedAt } : null;
  }
}

function publicRun(r: RunRow | null) {
  if (!r) return null;
  return {
    id: r.id, trigger: r.trigger, status: r.status, progress: r.progress ?? null, stats: r.stats ?? null, error: r.error,
    createdAt: r.createdAt.toISOString(), startedAt: r.startedAt?.toISOString() ?? null, finishedAt: r.finishedAt?.toISOString() ?? null,
  };
}

function publicDataset(d: DatasetRow | null) {
  if (!d) return null;
  const meta = (d.meta || {}) as Record<string, unknown>;
  return { uploadedAt: d.uploadedAt.toISOString(), caseCount: d.caseCount, dataWindow: meta.data_window ?? null, sources: meta.sources ?? [] };
}

/** 下钻用:一条脱敏工单 + 它的逐条研判(不含 user_key 等只用于归并的字段) */
function publicCase(s: StoredCase) {
  const c = s.record;
  const j = s.judgment;
  return {
    case_id: c.case_id, channel: c.channel, created_at: c.created_at, closed_at: c.closed_at,
    status: c.status, resolution: c.resolution, dept_type: c.dept_type, city: c.city,
    business_line: c.business_line, problem_path: c.problem_path, station_code: c.station_code,
    template_risk: c.template_risk, text: c.text,
    judgment: j ? {
      source: j.source, summary: j.summary, systemic_likelihood: j.systemic_likelihood, systemic_reason: j.systemic_reason,
      symptoms: j.symptoms.map((x) => ({ code: x, label: SYMPTOMS[x] || x })),
      mechanisms: j.mechanisms.map((m) => ({ code: m.code, label: MECHANISMS[m.code] || m.code, confidence: m.confidence })),
      clues: j.clues.map((x) => ({ code: x, label: CLUES[x]?.label || x })),
      demands: j.demands, operator: j.objects?.operator || '',
    } : null,
  };
}

@Injectable()
export class GovRiskService implements OnModuleInit {
  private readonly logger = new Logger('GovRisk');
  private readonly uploadLimiter = new SlidingWindowLimiter(240, 60 * 60 * 1000);
  private readonly runLimiter = new SlidingWindowLimiter(12, 60 * 60 * 1000);
  private queue: Array<{ owner: string; id: number }> = [];
  private worker: Promise<void> | null = null;
  static readonly KEEP_PACKAGES = 30;
  static readonly MAX_JUDGE_PER_RUN = 1200;

  constructor(
    private readonly store: GovRiskStore,
    private readonly completion: GovRiskCompletionClient = new OpenAIGovRiskClient(),
    private readonly llmEnabled: () => boolean = () => !!resolveLlmChannel().apiKey,
  ) {}

  onModuleInit(): void {
    if (process.env.NODE_ENV === 'test') return;
    this.store.interruptStaleRuns()
      .then((n) => { if (n) this.logger.warn(`[启动自检] ${n} 次未跑完的研判标成中断`); })
      .catch((e) => this.logger.error(`[启动自检] 清理中断的研判失败: ${e?.message}`));
  }

  /** 工作台所有者的平台登录名;没配置时整个功能明确不可用,不假装就绪。 */
  owner(): string {
    const owner = (process.env.GOV_RISK_OWNER_USERNAME || '').trim().toLowerCase();
    if (!owner) {
      throw new ServiceUnavailableException({ reason: 'owner_not_configured', message: '未配置 GOV_RISK_OWNER_USERNAME' });
    }
    return owner;
  }

  /** 只有所有者本人能读写;sub 是数字 id,比对必须用 username(登录名)。 */
  assertOwner(user: { username?: string | null } | undefined): string {
    const owner = this.owner();
    if (!user?.username) throw new UnauthorizedException({ reason: 'login_required', message: '未登录或登录已过期' });
    if (user.username.toLowerCase() !== owner) {
      reject(HttpStatus.FORBIDDEN, 'not_owner', '这个工作台只对所有者开放');
    }
    return owner;
  }

  // ---------- 页面(所有者本人) ----------

  async getPackage(user: { username?: string | null } | undefined, internal = false) {
    const owner = internal ? this.owner() : this.assertOwner(user);
    const [rows, run, dataset] = await Promise.all([
      this.store.packageHistory(owner, 10), this.store.latestRun(owner), this.store.getDataset(owner),
    ]);
    return {
      package: rows[0]?.payload ?? null,
      generatedAt: rows[0]?.uploadedAt.toISOString() ?? null,
      history: rows.map((r) => {
        const p = (r.payload || {}) as Record<string, unknown>;
        return { generatedAt: r.uploadedAt.toISOString(), kpi: p.kpi || null, dataWindow: p.data_window || null };
      }),
      run: publicRun(run),
      dataset: publicDataset(dataset),
    };
  }

  async getRun(user: { username?: string | null } | undefined, internal = false) {
    const owner = internal ? this.owner() : this.assertOwner(user);
    const [run, dataset] = await Promise.all([this.store.latestRun(owner), this.store.getDataset(owner)]);
    return { run: publicRun(run), dataset: publicDataset(dataset) };
  }

  async requestRun(user: { username?: string | null } | undefined) {
    const owner = this.assertOwner(user);
    if (!(await this.store.getDataset(owner))) reject(HttpStatus.CONFLICT, 'no_dataset', '平台上还没有工单数据,先在本机上传');
    const waiting = this.queue.find((q) => q.owner === owner);
    if (waiting) return { run: publicRun(await this.store.getRun(waiting.id)), queued: true };
    if (!this.runLimiter.take()) reject(HttpStatus.TOO_MANY_REQUESTS, 'gov_risk_rate_limited', '研判过于频繁,请稍后再试');
    const run = await this.enqueue(owner, 'manual');
    return { run: publicRun(run), queued: false };
  }

  async getCases(user: { username?: string | null } | undefined, ids: unknown) {
    const owner = this.assertOwner(user);
    const rows = await this.store.getCases(owner, validateCaseIds(ids));
    return { cases: rows.map(publicCase) };
  }

  async getFeedback(user?: { username?: string | null }) {
    const owner = this.assertOwner(user);
    const row = await this.store.getFeedback(owner);
    if (!row) return { revision: 0, data: { candidates: {} } as FeedbackDoc, updatedAt: null };
    return { revision: row.revision, data: row.payload as FeedbackDoc, updatedAt: row.updatedAt.toISOString() };
  }

  async putFeedback(user: { username?: string | null } | undefined, body: unknown) {
    const owner = this.assertOwner(user);
    const { revision, data } = validateFeedback(body);
    const res = await this.store.putFeedback(owner, revision, data, String(user?.username || ''));
    if (!res) reject(HttpStatus.CONFLICT, 'revision_conflict', '跟进记录已在别处更新,请重新加载后再改');
    return { revision: res.revision, data, updatedAt: res.updatedAt.toISOString() };
  }

  // ---------- 本地服务(agent token) ----------

  async uploadCases(body: unknown) {
    const owner = this.owner();
    if (!this.uploadLimiter.take()) reject(HttpStatus.TOO_MANY_REQUESTS, 'gov_risk_rate_limited', '上传过于频繁');
    const chunk = validateCaseChunk(body);
    const stored = await this.store.upsertCases(owner, chunk.uploadId, chunk.cases);
    if (!chunk.final) return { stored, final: false };
    const received = await this.store.countUpload(owner, chunk.uploadId);
    if (received !== chunk.final.caseCount) {
      // 中途断过的上传不能当快照,否则会把没传到的旧工单删掉
      reject(HttpStatus.CONFLICT, 'gov_risk_upload_incomplete', `本次上传应有 ${chunk.final.caseCount} 条,平台只收到 ${received} 条,请重新上传`);
    }
    const meta = {
      data_window: chunk.final.dataWindow, sources: chunk.final.sources,
      reference_cases: chunk.final.referenceCases, client: chunk.final.client,
    };
    const { removed, uploadedAt } = await this.store.finalizeUpload(owner, chunk.uploadId, received, meta);
    this.logger.log(`脱敏工单已入库:${received} 条(删除不在快照里的 ${removed} 条)`);
    let run: RunRow | null = null;
    let runSkipped: string | null = null;
    const waiting = this.queue.find((q) => q.owner === owner);
    if (waiting) run = await this.store.getRun(waiting.id); // 已经排着一次,数据会在那次里读到
    else if (this.runLimiter.take()) run = await this.enqueue(owner, 'upload');
    else runSkipped = 'rate_limited';
    return { stored, final: true, total: received, removed, uploadedAt: uploadedAt.toISOString(), run: publicRun(run), runSkipped };
  }

  async purge(body: unknown) {
    const owner = this.owner();
    if ((body as { confirm?: unknown })?.confirm !== 'delete-all') {
      reject(HttpStatus.BAD_REQUEST, 'gov_risk_purge_unconfirmed', '撤回要带 {"confirm":"delete-all"}');
    }
    if (this.queue.length || this.worker) reject(HttpStatus.CONFLICT, 'gov_risk_run_active', '研判还在进行,结束后再撤回');
    const res = await this.store.purge(owner);
    this.logger.warn(`已撤回平台上的研判数据:工单 ${res.cases} 条、结果包 ${res.packages} 份`);
    return { deleted: true, ...res };
  }

  // ---------- 研判运行 ----------

  /** 测试和排障用:等当前排队的研判全部跑完 */
  whenIdle(): Promise<void> {
    return this.worker || Promise.resolve();
  }

  private async enqueue(owner: string, trigger: string): Promise<RunRow> {
    const run = await this.store.createRun(owner, trigger);
    this.queue.push({ owner, id: run.id });
    if (!this.worker) {
      this.worker = new Promise<void>((resolve) => setImmediate(resolve))
        .then(() => this.drain())
        .finally(() => { this.worker = null; });
    }
    return run;
  }

  private async drain(): Promise<void> {
    while (this.queue.length) {
      const next = this.queue[0];
      try {
        await this.execute(next.owner, next.id);
      } catch (e) {
        this.logger.error(`[研判] #${next.id} 异常: ${(e as Error)?.message}`);
      } finally {
        this.queue.shift();
      }
    }
  }

  private async execute(owner: string, runId: number): Promise<void> {
    await this.store.updateRun(runId, { status: 'running', startedAt: new Date(), progress: { stage: 'load' } });
    try {
      const [rows, dataset, feedback, history] = await Promise.all([
        this.store.listCases(owner), this.store.getDataset(owner), this.store.getFeedback(owner), this.store.packageHistory(owner, 1),
      ]);
      const meta = (dataset?.meta || {}) as { reference_cases?: ReferenceCase[] };
      const run = await this.store.getRun(runId);
      const timeoutMs = Math.max(1000, Number(process.env.GOV_RISK_LLM_TIMEOUT_MS || 120000));
      const result = await runAnalysis({
        rows,
        feedback: ((feedback?.payload || {}) as FeedbackDoc).candidates || {},
        refs: meta.reference_cases || [],
        previousPackage: (history[0]?.payload as Record<string, unknown>) || null,
        dataset: { uploaded_at: dataset?.uploadedAt.toISOString() ?? null, case_count: rows.length },
        run: { id: runId, trigger: run?.trigger || '' },
      }, {
        llmEnabled: this.llmEnabled(),
        complete: async ({ purpose, messages, maxTokens }) => {
          const started = Date.now();
          const res = await this.completion.create({ messages, maxTokens, temperature: 0.1, model: llmModel(), timeoutMs });
          const chars = messages.reduce((n, m) => n + m.content.length, 0);
          this.logger.log(`模型调用:purpose=${purpose} 输入 ${chars} 字 耗时 ${Date.now() - started}ms 模型 ${res.model}`);
          return res;
        },
        saveJudgment: (caseId, key, j) => this.store.saveJudgment(owner, caseId, key, j),
        progress: (p) => this.store.updateRun(runId, { progress: p }),
        now: () => Date.now(),
        maxJudge: GovRiskService.MAX_JUDGE_PER_RUN,
      });
      const sizeBytes = Buffer.byteLength(JSON.stringify(result.pkg), 'utf8');
      await this.store.savePackage(owner, RESULT_SCHEMA, result.pkg, sizeBytes, GovRiskService.KEEP_PACKAGES);
      await this.store.updateRun(runId, { status: 'succeeded', finishedAt: new Date(), stats: result.stats, progress: { stage: 'done' } });
      const s = result.stats;
      this.logger.log(`[研判] #${runId} 完成:${s.cases} 条,模型 ${s.judged_by_model}(新 ${s.judged_new})、规则 ${s.judged_by_rules},`
        + `候选 ${s.candidates} 个,复核 ${s.reviewed} 个${s.breaker ? `,熔断 ${s.breaker}` : ''},耗时 ${s.duration_ms}ms`);
    } catch (e) {
      await this.store.updateRun(runId, { status: 'failed', finishedAt: new Date(), error: String((e as Error)?.message || e).slice(0, 300) });
      throw e;
    }
  }
}
