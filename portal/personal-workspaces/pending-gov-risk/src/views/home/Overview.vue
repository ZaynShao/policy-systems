<script setup lang="ts">
// 总览:把各子模块最要紧的数字放在一页。第一版由 AI 规划,用户后续再改。
// 每块数据单独读、单独报错,读不到就写原因,不拿示例数据填。
import { computed, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { http } from '@/api/client';
import { knowledgeApi, type KnowledgeStats, type SyncStatus } from '@/api/knowledge';
import { monthlyApi, type MonthlyListItem } from '@/api/monthly';
import { l1ReviewApi, type L1ReviewItem } from '@/api/l1Review';
import { crawlerApi, type CrawlerQueueStatus } from '@/api/crawler';
import { policyQaBase } from '@/api/policy-qa';
import { NAV_GROUPS } from '@/shell/nav';

type Load<T> = { state: 'loading' | 'ok' | 'error'; data: T | null; error: string };
function slot<T>(): Load<T> { return reactive({ state: 'loading', data: null, error: '' }) as Load<T>; }

// 政诉预判:结构见 services/heng-guan/backend/src/gov-risk(gov-risk/v2 结果包)
interface GovCandidate {
  id: string; band: '高' | '中' | '低'; score: number; level: string;
  symptom_label: string; object_type?: string; status?: string;
  review?: { title?: string } | null; recurred_after_fix?: number;
  stats?: { n?: number; n_90d?: number; recurring_after_close?: boolean };
}
interface GovRun { status: string; trigger?: string; finishedAt?: string | null; error?: string | null }
interface GovPackageResp {
  package: null | {
    generated_at?: string; data_window?: { from?: string; to?: string };
    kpi?: Record<string, number>; candidates?: GovCandidate[];
  };
  run: GovRun | null;
  dataset: { caseCount: number; uploadedAt: string } | null;
}
interface GovFeedback { data?: { candidates?: Record<string, { status?: string }> } }

const GOV_STATUS: Record<string, string> = {
  new: '新发现', investigating: '核查中', confirmed: '根因确认', fixing: '整改中',
  fixed: '已修复', observing: '观察期', dismissed: '误报', closed: '关闭',
};
const GOV_DONE = new Set(['fixed', 'observing', 'dismissed', 'closed']);
const RUN_STATUS: Record<string, string> = { queued: '排队中', running: '研判中', succeeded: '已完成', failed: '失败', interrupted: '已中断' };
const MONTHLY_STATUS: Record<string, { label: string; cls: string }> = {
  DRAFT: { label: '草稿', cls: 'pill-amber' }, AUDITING: { label: '审核中', cls: 'pill-blue' },
  PUBLISHED: { label: '已发布', cls: 'pill-green' }, ARCHIVED: { label: '已归档', cls: '' },
};
// 与 views/quality/L1ReviewQueue.vue 的叫法一致
const L1_KIND: Record<string, string> = { gate: '采集入口', checkpoint: '候选渠道', sweep: '误分类扫描', fetch_fail: '抓取失败' };

const router = useRouter();
const gov = slot<{ pkg: GovPackageResp; feedback: GovFeedback }>();
const kb = slot<{ stats: KnowledgeStats; sync: SyncStatus | null }>();
const monthly = slot<MonthlyListItem[]>();
const review = slot<L1ReviewItem[]>();
const queue = slot<CrawlerQueueStatus>();
const qa = slot<{ ok: boolean; detail: string }>();
const refreshedAt = ref('');
const refreshing = ref(false);

function reason(e: any): string {
  const status = e?.response?.status ?? e?.status;
  if (status === 403 || e?.reason === 'forbidden' || e?.reason === 'not_owner') return '当前账号没有这块数据的权限';
  if (e?.reason === 'owner_not_configured') return '平台还没配置政诉预判的所有者';
  return e?.message || '读取失败';
}

async function run<T>(target: Load<T>, fn: () => Promise<T>) {
  target.state = 'loading';
  target.error = '';
  try {
    target.data = await fn();
    target.state = 'ok';
  } catch (e) {
    target.data = null;
    target.error = reason(e);
    target.state = 'error';
  }
}

async function loadQa() {
  const resp = await fetch(`${policyQaBase}/v1/health`, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
  if (resp.status === 401) throw new Error('登录已失效');
  let body: any = null;
  try { body = await resp.json(); } catch { body = null; }
  const ok = resp.ok && body?.ok === true;
  const policies = typeof body?.policies === 'number' ? `可检索 ${body.policies.toLocaleString()} 篇政策` : '';
  return { ok, detail: ok ? policies : (body?.detail || `HTTP ${resp.status}`) };
}

async function refresh() {
  refreshing.value = true;
  await Promise.all([
    run(gov, async () => {
      const [pkg, feedback] = await Promise.all([
        http.get<never, GovPackageResp>('/gov-risk/package'),
        http.get<never, GovFeedback>('/gov-risk/feedback'),
      ]);
      return { pkg, feedback };
    }),
    run(kb, async () => {
      const [stats, sync] = await Promise.all([knowledgeApi.stats(), knowledgeApi.syncStatus().catch(() => null)]);
      return { stats, sync };
    }),
    run(monthly, () => monthlyApi.list()),
    run(review, () => l1ReviewApi.list()),
    run(queue, () => crawlerApi.queueStatus()),
    run(qa, loadQa),
  ]);
  refreshedAt.value = fmtTime(new Date().toISOString());
  refreshing.value = false;
}

function p2(n: number) { return n < 10 ? '0' + n : String(n); }
function fmtTime(iso?: string | null) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}`;
}

// ---- 政诉预判 ----
const govPkg = computed(() => gov.data?.pkg.package ?? null);
const govKpi = computed(() => govPkg.value?.kpi ?? {});
function govStatus(c: GovCandidate) {
  return gov.data?.feedback.data?.candidates?.[c.id]?.status || c.status || 'new';
}
function govTitle(c: GovCandidate) {
  return c.review?.title || c.symptom_label + (c.level === 'object' ? `(集中在同一${c.object_type || '对象'})` : '');
}
const govFocus = computed(() => (govPkg.value?.candidates ?? [])
  .filter(c => !GOV_DONE.has(govStatus(c)) || (c.recurred_after_fix ?? 0) > 0)
  .sort((a, b) => b.score - a.score)
  .slice(0, 5));
const govRunLine = computed(() => {
  const r = gov.data?.pkg.run;
  const d = gov.data?.pkg.dataset;
  const parts: string[] = [];
  if (d) parts.push(`平台数据 ${d.caseCount} 条脱敏工单,上传于 ${fmtTime(d.uploadedAt)}`);
  if (r) parts.push(r.status === 'succeeded' ? `最近研判 ${fmtTime(r.finishedAt)} 完成` : `最近研判${RUN_STATUS[r.status] || r.status}${r.error ? ':' + r.error : ''}`);
  return parts.join(' · ') || '平台上还没有工单数据';
});

// ---- 月刊 / 审核 / 队列 ----
const monthlyRecent = computed(() => [...(monthly.data ?? [])]
  .sort((a, b) => String(b.coverDate ?? '').localeCompare(String(a.coverDate ?? '')))
  .slice(0, 4));
const monthlyOpen = computed(() => (monthly.data ?? []).filter(m => m.status === 'DRAFT' || m.status === 'AUDITING').length);
const reviewByKind = computed(() => {
  const counts: Record<string, number> = {};
  for (const item of review.data ?? []) counts[item.pipelineKind] = (counts[item.pipelineKind] ?? 0) + 1;
  return Object.entries(counts).sort((a, b) => b[1] - a[1]);
});
const queueFailed = computed(() => (queue.data?.counts.retryableFail ?? 0) + (queue.data?.counts.exhaustedFail ?? 0));
const lastSync = computed(() => kb.data?.sync?.recent?.[0] ?? null);

// ---- 今天要处理的事:只由已读到的数据汇总 ----
interface Todo { text: string; to: string; tone: 'red' | 'amber' | 'blue' }
const todos = computed<Todo[]>(() => {
  const list: Todo[] = [];
  if (gov.state === 'ok') {
    const r = gov.data!.pkg.run;
    if (r && (r.status === 'failed' || r.status === 'interrupted')) list.push({ text: `政诉预判上次研判${RUN_STATUS[r.status]},需要重跑`, to: '/gov-risk', tone: 'red' });
    const fixAgain = govKpi.value.recurred_after_fix ?? 0;
    if (fixAgain) list.push({ text: `政诉预判有 ${fixAgain} 个已修复的问题又复发`, to: '/gov-risk', tone: 'red' });
    const untouchedHigh = (govPkg.value?.candidates ?? []).filter(c => c.band === '高' && govStatus(c) === 'new').length;
    if (untouchedHigh) list.push({ text: `${untouchedHigh} 个高优先政诉候选还没开始跟进`, to: '/gov-risk', tone: 'amber' });
  }
  if (review.state === 'ok' && review.data!.length) list.push({ text: `源质量审核待处理 ${review.data!.length} 条`, to: '/quality/l1-review', tone: 'amber' });
  if (queue.state === 'ok') {
    if (queue.data!.counts.exhaustedFail) list.push({ text: `采集队列有 ${queue.data!.counts.exhaustedFail} 条重试已用尽`, to: '/policy/import', tone: 'red' });
    else if (queueFailed.value) list.push({ text: `采集队列有 ${queueFailed.value} 条失败待重试`, to: '/policy/import', tone: 'amber' });
  }
  if (kb.state === 'ok' && lastSync.value?.status === 'FAILED') list.push({ text: '政策知识库最近一次同步失败', to: '/policy/import', tone: 'red' });
  if (monthly.state === 'ok' && monthlyOpen.value) list.push({ text: `${monthlyOpen.value} 期月刊未发布(草稿或审核中)`, to: '/monthlies', tone: 'blue' });
  if (qa.state === 'ok' && !qa.data!.ok) list.push({ text: `政策解读问答服务不可用:${qa.data!.detail}`, to: '/policy/interpretation', tone: 'red' });
  return list;
});
const allSettled = computed(() => [gov, kb, monthly, review, queue, qa].every(s => s.state !== 'loading'));
const failedSources = computed(() => [
  ['政诉预判', gov], ['政策知识库', kb], ['政策月刊', monthly], ['源质量审核', review], ['采集队列', queue], ['政策解读服务', qa],
].filter(([, s]) => (s as Load<unknown>).state === 'error').map(([name]) => name as string));

const shortcuts = NAV_GROUPS.flatMap(g => g.items.map(item => ({ ...item, group: g.title }))).filter(i => i.to !== '/overview');

onMounted(refresh);
</script>

<template>
  <div class="pw-overview">
    <div class="page-head">
      <div>
        <div class="page-title">总览</div>
        <div class="page-sub">政诉预判和政策工作的最新状态;数字都来自平台实时接口{{ refreshedAt ? ',更新于 ' + refreshedAt : '' }}</div>
      </div>
      <div class="page-actions">
        <button type="button" class="btn" :disabled="refreshing" @click="refresh">
          <span class="pf-i pf-i-refresh" aria-hidden="true"></span>{{ refreshing ? '正在刷新…' : '刷新' }}
        </button>
      </div>
    </div>

    <!-- 今天要处理的事 -->
    <section class="card pw-todo" aria-labelledby="pw-todo-title">
      <div class="card-head"><span class="card-title" id="pw-todo-title">今天要处理的事</span></div>
      <div class="pw-todo-body">
        <p v-if="!allSettled" class="pw-muted">正在汇总…</p>
        <template v-else>
          <button v-for="t in todos" :key="t.text" type="button" class="pw-todo-item" :class="'tone-' + t.tone" @click="router.push(t.to)">
            <span class="pw-dot" aria-hidden="true"></span><span>{{ t.text }}</span><span class="pw-go" aria-hidden="true">→</span>
          </button>
          <p v-if="!todos.length" class="pw-muted">暂无需要处理的事项。</p>
          <p v-if="failedSources.length" class="pw-muted pw-warn">{{ failedSources.join('、') }} 没读到,上面的汇总不含这几项。</p>
        </template>
      </div>
    </section>

    <!-- 关键数字 -->
    <div class="stat-grid pw-stats">
      <button type="button" class="stat-card pw-stat" @click="router.push('/gov-risk')">
        <div class="stat-label"><span class="stat-icon"><span class="pf-i pf-i-alert" aria-hidden="true"></span></span>高优先政诉候选</div>
        <template v-if="gov.state === 'ok' && govPkg">
          <div class="stat-value is-red">{{ govKpi.candidates_high ?? 0 }}</div>
          <div class="stat-delta">中优先 {{ govKpi.candidates_medium ?? 0 }} · 修复后复发 {{ govKpi.recurred_after_fix ?? 0 }}</div>
        </template>
        <div v-else class="stat-delta">{{ gov.state === 'loading' ? '读取中…' : gov.state === 'error' ? gov.error : '还没有研判结果' }}</div>
      </button>
      <button type="button" class="stat-card blue pw-stat" @click="router.push('/policy/knowledge')">
        <div class="stat-label"><span class="stat-icon"><span class="pf-i pf-i-knowledge" aria-hidden="true"></span></span>知识库政策</div>
        <template v-if="kb.state === 'ok'">
          <div class="stat-value">{{ kb.data!.stats.entryCount.toLocaleString() }}</div>
          <div class="stat-delta">高重要性 {{ kb.data!.stats.highImportanceCount }} · 主题 {{ kb.data!.stats.themeCount }} · 关系 {{ kb.data!.stats.relationCount.toLocaleString() }}</div>
        </template>
        <div v-else class="stat-delta">{{ kb.state === 'loading' ? '读取中…' : kb.error }}</div>
      </button>
      <button type="button" class="stat-card amber pw-stat" @click="router.push('/quality/l1-review')">
        <div class="stat-label"><span class="stat-icon"><span class="pf-i pf-i-check" aria-hidden="true"></span></span>待审核数据源</div>
        <template v-if="review.state === 'ok'">
          <div class="stat-value">{{ review.data!.length }}</div>
          <div class="stat-delta">{{ reviewByKind.map(([k, n]) => (L1_KIND[k] || k) + ' ' + n).join(' · ') || '没有待审核项' }}</div>
        </template>
        <div v-else class="stat-delta">{{ review.state === 'loading' ? '读取中…' : review.error }}</div>
      </button>
      <button type="button" class="stat-card purple pw-stat" @click="router.push('/policy/import')">
        <div class="stat-label"><span class="stat-icon"><span class="pf-i pf-i-datasource" aria-hidden="true"></span></span>采集队列积压</div>
        <template v-if="queue.state === 'ok'">
          <div class="stat-value">{{ queue.data!.backlog }}</div>
          <div class="stat-delta">处理中 {{ queue.data!.counts.processing }} · 失败 {{ queueFailed }}</div>
        </template>
        <div v-else class="stat-delta">{{ queue.state === 'loading' ? '读取中…' : queue.error }}</div>
      </button>
    </div>

    <div class="pw-grid">
      <!-- 政诉预判:需要关注 -->
      <section class="card pw-span" aria-labelledby="pw-gov-title">
        <div class="card-head">
          <span class="card-title" id="pw-gov-title">政诉预判 · 需要关注</span>
          <button type="button" class="action-link pw-link" @click="router.push('/gov-risk')">进入政诉预判 →</button>
        </div>
        <div class="pw-body">
          <p v-if="gov.state === 'loading'" class="pw-muted">读取中…</p>
          <p v-else-if="gov.state === 'error'" class="pw-muted pw-warn">{{ gov.error }}</p>
          <template v-else>
            <p class="pw-meta">{{ govRunLine }}</p>
            <p v-if="!govPkg" class="pw-muted">还没有研判结果。</p>
            <ol v-else-if="govFocus.length" class="pw-gov-list">
              <li v-for="c in govFocus" :key="c.id">
                <span class="pw-band" :class="'band-' + c.band">{{ c.band }} {{ c.score }}</span>
                <span class="pw-gov-title">{{ govTitle(c) }}</span>
                <span class="pill">{{ GOV_STATUS[govStatus(c)] || govStatus(c) }}</span>
                <span v-if="c.recurred_after_fix" class="pill pill-red">修复后复发 {{ c.recurred_after_fix }} 条</span>
                <span v-else-if="c.stats?.recurring_after_close" class="pill pill-amber">关单后仍在出现</span>
                <span class="pw-gov-n">{{ c.stats?.n ?? 0 }} 条 · 近 90 天 {{ c.stats?.n_90d ?? 0 }}</span>
              </li>
            </ol>
            <p v-else class="pw-muted">候选都已跟进完毕。</p>
          </template>
        </div>
      </section>

      <!-- 政策月刊 -->
      <section class="card" aria-labelledby="pw-monthly-title">
        <div class="card-head">
          <span class="card-title" id="pw-monthly-title">政策月刊</span>
          <button type="button" class="action-link pw-link" @click="router.push('/monthlies')">全部 →</button>
        </div>
        <div class="pw-body">
          <p v-if="monthly.state === 'loading'" class="pw-muted">读取中…</p>
          <p v-else-if="monthly.state === 'error'" class="pw-muted pw-warn">{{ monthly.error }}</p>
          <p v-else-if="!monthlyRecent.length" class="pw-muted">还没有月刊。</p>
          <ul v-else class="pw-rows">
            <li v-for="m in monthlyRecent" :key="m.id">
              <button type="button" class="pw-row-btn" @click="router.push(`/monthlies/${m.id}`)">
                <span class="pw-row-title">{{ m.title }}</span>
                <span class="pill" :class="MONTHLY_STATUS[m.status]?.cls">{{ MONTHLY_STATUS[m.status]?.label || m.status }}</span>
              </button>
            </li>
          </ul>
        </div>
      </section>

      <!-- 知识库与问答服务 -->
      <section class="card" aria-labelledby="pw-kb-title">
        <div class="card-head">
          <span class="card-title" id="pw-kb-title">知识库与解读服务</span>
          <button type="button" class="action-link pw-link" @click="router.push('/policy/graph')">政策图谱 →</button>
        </div>
        <div class="pw-body">
          <dl class="pw-dl">
            <dt>最近同步</dt>
            <dd v-if="kb.state === 'loading'">读取中…</dd>
            <dd v-else-if="kb.state === 'error'" class="pw-warn">{{ kb.error }}</dd>
            <dd v-else-if="lastSync">
              <span class="pill" :class="lastSync.status === 'SUCCESS' ? 'pill-green' : lastSync.status === 'FAILED' ? 'pill-red' : 'pill-blue'">
                {{ lastSync.status === 'SUCCESS' ? '成功' : lastSync.status === 'FAILED' ? '失败' : '同步中' }}
              </span>
              {{ fmtTime(lastSync.finishedAt || lastSync.startedAt) }}{{ lastSync.entryCount != null ? ` · ${lastSync.entryCount} 条` : '' }}
            </dd>
            <dd v-else-if="kb.data?.stats.lastSync">{{ fmtTime(kb.data.stats.lastSync.finishedAt || kb.data.stats.lastSync.startedAt) }}</dd>
            <dd v-else>还没有同步记录</dd>
            <dt>覆盖地区</dt>
            <dd>{{ kb.state === 'ok' ? kb.data!.stats.regionCount + ' 个' : '—' }}</dd>
            <dt>政策解读</dt>
            <dd v-if="qa.state === 'loading'">检查中…</dd>
            <dd v-else-if="qa.state === 'error'" class="pw-warn">{{ qa.error }}</dd>
            <dd v-else><span class="pill" :class="qa.data!.ok ? 'pill-green' : 'pill-red'">{{ qa.data!.ok ? '可用' : '不可用' }}</span> {{ qa.data!.detail }}</dd>
          </dl>
        </div>
      </section>

      <!-- 采集与审核 -->
      <section class="card" aria-labelledby="pw-queue-title">
        <div class="card-head">
          <span class="card-title" id="pw-queue-title">采集队列</span>
          <button type="button" class="action-link pw-link" @click="router.push('/policy/import')">政策数据源 →</button>
        </div>
        <div class="pw-body">
          <p v-if="queue.state === 'loading'" class="pw-muted">读取中…</p>
          <p v-else-if="queue.state === 'error'" class="pw-muted pw-warn">{{ queue.error }}</p>
          <template v-else>
            <dl class="pw-dl">
              <dt>待处理</dt><dd>{{ queue.data!.counts.pending }}</dd>
              <dt>成功 / 跳过</dt><dd>{{ queue.data!.counts.success }} / {{ queue.data!.counts.skipped }}</dd>
              <dt>可重试失败</dt><dd>{{ queue.data!.counts.retryableFail }}</dd>
              <dt>重试用尽</dt><dd :class="{ 'pw-warn': queue.data!.counts.exhaustedFail }">{{ queue.data!.counts.exhaustedFail }}</dd>
              <dt>最早待处理</dt><dd>{{ queue.data!.oldestPending ? fmtTime(queue.data!.oldestPending.discoveredAt) || '有' : '无' }}</dd>
            </dl>
          </template>
        </div>
      </section>
    </div>

    <!-- 快捷入口 -->
    <section class="card" aria-labelledby="pw-short-title">
      <div class="card-head"><span class="card-title" id="pw-short-title">子模块</span></div>
      <div class="pw-shortcuts">
        <button v-for="s in shortcuts" :key="s.to" type="button" class="pw-shortcut" @click="router.push(s.to)">
          <span class="pf-i" :class="'pf-i-' + s.icon" aria-hidden="true"></span>
          <span><strong>{{ s.label }}</strong><small>{{ s.group }}</small></span>
        </button>
      </div>
      <p class="pw-foot">政策大盘、解读、知识库、图谱、月刊、数据源、源质量审核是从公共事务复制的个人版本,与公共事务共用同一份数据。</p>
    </section>
  </div>
</template>

<style scoped>
.pw-overview { max-width: 1280px; }
.pw-muted { color: var(--ink-3); font-size: 12.5px; }
.pw-warn { color: var(--red); }
.pw-meta { margin-bottom: 10px; color: var(--ink-3); font-size: 12px; }
.pw-body { padding: 14px 18px 16px; }
.pw-link { border: 0; background: none; font-size: 12px; cursor: pointer; }

.pw-todo { margin-bottom: 18px; }
.pw-todo-body { display: grid; gap: 6px; padding: 12px 14px 14px; }
.pw-todo-item {
  display: flex; align-items: center; gap: 10px; width: 100%;
  padding: 9px 12px; border: 1px solid var(--line); border-radius: 8px;
  background: var(--white); color: var(--ink-2); font-size: 13px; text-align: left; cursor: pointer;
}
.pw-todo-item:hover { border-color: var(--orange-border); background: var(--orange-soft); }
.pw-todo-item:focus-visible, .pw-stat:focus-visible, .pw-shortcut:focus-visible, .pw-row-btn:focus-visible, .pw-link:focus-visible {
  outline: 2px solid var(--orange); outline-offset: 2px;
}
.pw-dot { flex: 0 0 8px; height: 8px; border-radius: 50%; background: var(--blue); }
.tone-red .pw-dot { background: var(--red); }
.tone-amber .pw-dot { background: var(--amber); }
.pw-go { margin-left: auto; color: var(--ink-4); }

/* tokens.css 的移动端 .stat-grid 覆盖写在基础规则前面、不生效,这里自己管列数 */
.pw-stats { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.pw-stat { min-width: 0; text-align: left; cursor: pointer; font: inherit; transition: border-color .15s, box-shadow .15s; }
.pw-stat:hover { border-color: var(--orange-border); box-shadow: var(--shadow-md); }
.stat-value.is-red { color: var(--red); }
.pw-stat .stat-delta { overflow-wrap: anywhere; }

.pw-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-bottom: 18px; }
.pw-span { grid-column: 1 / -1; }

.pw-gov-list { display: grid; gap: 8px; list-style: none; }
.pw-gov-list li {
  display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px;
  padding: 9px 12px; border: 1px solid var(--line-2); border-radius: 8px; background: var(--bg);
}
.pw-band { display: inline-flex; align-items: center; height: 22px; padding: 0 8px; border-radius: 6px; font-size: 11.5px; font-weight: 700; }
.band-高 { background: #fee2e2; color: #991b1b; }
.band-中 { background: #fef3c7; color: #92400e; }
.band-低 { background: var(--bg-2); color: var(--slate); }
.pw-gov-title { min-width: 0; flex: 1 1 260px; color: var(--ink); font-weight: 600; }
.pw-gov-n { color: var(--ink-3); font-size: 12px; }

.pw-rows { display: grid; gap: 4px; list-style: none; }
.pw-row-btn {
  display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%;
  padding: 8px 4px; border: 0; border-bottom: 1px solid var(--line-2); background: none; text-align: left; cursor: pointer;
}
.pw-row-btn:hover .pw-row-title { color: var(--orange-2); }
.pw-row-title { min-width: 0; overflow: hidden; color: var(--ink-2); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }

.pw-dl { display: grid; grid-template-columns: 84px minmax(0, 1fr); gap: 8px 10px; font-size: 13px; }
.pw-dl dt { color: var(--ink-3); }
.pw-dl dd { min-width: 0; color: var(--ink-2); overflow-wrap: anywhere; }

.pw-shortcuts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; padding: 14px 18px 4px; }
.pw-shortcut {
  display: flex; align-items: center; gap: 10px; padding: 12px; border: 1px solid var(--line); border-radius: 9px;
  background: var(--white); text-align: left; cursor: pointer;
}
.pw-shortcut:hover { border-color: var(--orange-border); background: var(--orange-soft); }
.pw-shortcut .pf-i { font-size: 20px; color: var(--orange-2); }
.pw-shortcut strong { display: block; color: var(--ink); font-size: 13px; }
.pw-shortcut small { display: block; color: var(--ink-4); font-size: 11px; }
.pw-foot { padding: 10px 18px 14px; color: var(--ink-4); font-size: 11.5px; }

@media (max-width: 1100px) {
  .pw-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .pw-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .pw-shortcuts { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 768px) {
  .pw-grid { grid-template-columns: minmax(0, 1fr); }
  .pw-shortcuts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
