<!--
  这个文件原来是同事建的(公共事务平台的"政策大盘"页),本仓只收我写的部分,其余是独立版的最小外壳。

  我写的(原项目 PR 124「政策大盘对齐 pipeline 的 L2」,原样搬来):
  - 清单和计数全走后端按 L2 主题编号、L1 区划代码算好的结果:省份抽屉里每个主题的条数/重要/战略、前 8 条政策;
  - 国家级政策单列:"全国政策"卡片、抽屉里的"全国"一栏(NATIONAL、nationalTotal、openNational);
  - 点政策看详情时按政策编号去知识库补发文机关、一句话解读、摘要、行动建议(knowledgeByPid、showPolicy);
  - 说明文字、政策条目里日期与层级、详情里地区与日期的取法、"全国政策"卡片的样式。
  没带的我写的行:移动端主题条里的"全国"按钮、说明里的"点击省份钻取到市/区"——它们依附于同事写的移动端布局和地图。

  外壳(独立版补的):行尾或块前标「外壳」的部分——主题勾选、时间窗口、页面数据加载、抽屉和详情弹层的壳子,
  都是按我那几段要用到的变量名重写的最小版本;原页面中间的地图(同事写的 PolicyMap.vue,要省市边界数据)
  换成了"按省份分布"列表,点一行打开该省的抽屉;"主题分析"原来跳到同事做的页面,独立版没有那一页,改成提示。
-->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'; // 外壳
import { useToastStore } from '@/stores/toast'; // 外壳
import {
  dashboardApi,
  type PolicyCoverageResp,
  type PolicyCoverageTopic,
  type PolicyCoveragePolicy,
} from '@/api/dashboard';
import type { PolicyKnowledgeItem, PolicyKnowledgeSource } from '@/api/dashboard'; // 外壳(原来从同事的 utils/policyTopicRelevance 引)

const NATIONAL = '全国';

// ── 外壳:页面状态(变量名照原页面,下面我写的几段要用)
const toast = useToastStore();
const WINDOWS = [30, 90, 180, 365];
const days = ref<number>(365);
const data = ref<PolicyCoverageResp | null>(null);
const loading = ref<boolean>(false);
const policyKnowledgeItems = ref<PolicyKnowledgeItem[]>([]);
const policyKnowledgeSource = ref<PolicyKnowledgeSource>({ policyCount: 0, themeCount: 0, loadedCount: 0 });
const checkedIds = ref(new Set<string>());
const drawerRegion = ref<string | null>(null);
const drawerOpen = ref<boolean>(false);
// 外壳:原平台用路由跳到同事做的"主题分析"页;独立版没有那一页,只提示原来会跳去哪
const router = {
  push: (to: { path: string; query: Record<string, string> }) =>
    toast.push(`独立版没有"主题分析"页(原平台会带着主题 ${to.query.topicId}${to.query.region ? '、地区 ' + to.query.region : ''} 跳到 ${to.path})`, 'info'),
};

interface SourcePolicyView {
  title: string;
  issuer: string;
  region: string;
  date: string;
  oneLiner: string;
  readingValue: string;
  summary: string;
  actions: string[];
}
const sourcePolicy = ref<SourcePolicyView | null>(null);

// pid → 知识库富字段:清单/计数都走后端 coverage(theme id 口径一致),详情面板按 pid 补全
const knowledgeByPid = computed(() => {
  const m = new Map<string, PolicyKnowledgeItem>();
  for (const it of policyKnowledgeItems.value) m.set(it.id, it);
  return m;
});

// ── 外壳:取后端算好的政策覆盖和详情要的知识库摘要;只列这个时间窗口里有政策的主题,默认全勾上
async function refresh() {
  loading.value = true;
  try {
    const [resp, knowledge] = await Promise.all([dashboardApi.policyCoverage(days.value), dashboardApi.knowledgePreview()]);
    policyKnowledgeItems.value = knowledge.items;
    policyKnowledgeSource.value = knowledge.source;
    const withPolicies = resp.topics.filter((t) => t.totalPolicies > 0);
    data.value = { window: resp.window, topics: withPolicies };
    checkedIds.value = new Set(withPolicies.map((t) => t.topicId));
  } catch (e: any) {
    toast.push(e?.message || '加载失败', 'error');
  } finally {
    loading.value = false;
  }
}
onMounted(refresh);

// 外壳:勾上的主题
const selectedTopics = computed(() => (data.value?.topics ?? []).filter((t) => checkedIds.value.has(t.topicId)));

// 选中主题里的全国政策总数(C5:全国政策单列面板)
const nationalTotal = computed(() =>
  selectedTopics.value.reduce((s, t) => s + (t.national?.policyCount ?? 0), 0),
);

type CoverageLike = {
  region: string;
  policyCount: number;
  weight: number;
  majorCount: number;
  strategicCount: number;
  policies: PolicyCoveragePolicy[];
};

// 外壳:computed 的壳子、无地区时返回空、最后按条数排序这几行原来是同事写的;中间判全国、取覆盖的部分是我写的
const drawerTopicRows = computed(() => { // 外壳
  if (drawerRegion.value == null) return []; // 外壳
  const national = drawerRegion.value === NATIONAL;
  const rows = selectedTopics.value // 外壳
    .map((topic) => {
      let coverage: CoverageLike | undefined;
      if (national) {
        const n = topic.national;
        coverage = n && n.policyCount
          ? { region: NATIONAL, policyCount: n.policyCount, weight: n.policyCount, majorCount: n.majorCount, strategicCount: n.strategicCount, policies: n.policies }
          : undefined;
      } else {
        coverage = topic.coverage.find((item) => item.region === drawerRegion.value);
      }
      return { topic, coverage };
    })
    .filter((row): row is { topic: PolicyCoverageTopic; coverage: CoverageLike } => Boolean(row.coverage))
  return rows.sort((x, y) => y.coverage.policyCount - x.coverage.policyCount); // 外壳
}); // 外壳

// ── 外壳:主题勾选
function toggleTopic(id: string) {
  const next = new Set(checkedIds.value);
  if (!next.delete(id)) next.add(id);
  checkedIds.value = next;
}
function selectAll(on: boolean) {
  checkedIds.value = new Set(on ? (data.value?.topics ?? []).map((t) => t.topicId) : []);
}

// ── 外壳:代替地图的"按省份分布"——把已选主题在各省的条数并排列出来(同一篇政策挂几个主题就各算一次)
const provinceRows = computed(() => {
  const m = new Map<string, { region: string; adcode: string; total: number; hits: { topic: PolicyCoverageTopic; count: number }[] }>();
  for (const t of selectedTopics.value) {
    for (const c of t.coverage) {
      const row = m.get(c.region) ?? { region: c.region, adcode: c.adcode, total: 0, hits: [] };
      row.total += c.policyCount;
      row.hits.push({ topic: t, count: c.policyCount });
      m.set(c.region, row);
    }
  }
  return [...m.values()].sort((a, b) => b.total - a.total || a.adcode.localeCompare(b.adcode));
});
const maxProvinceTotal = computed(() => Math.max(1, ...provinceRows.value.map((r) => r.total)));
function openRegion(region: string) {
  sourcePolicy.value = null;
  drawerRegion.value = region;
  drawerOpen.value = true;
}

function openNational() {
  drawerRegion.value = NATIONAL;
  sourcePolicy.value = null;
  drawerOpen.value = true;
}

function goThemeAnalysis(topicId?: string) { // 外壳
  drawerOpen.value = false; // 外壳
  const region = drawerRegion.value && drawerRegion.value !== NATIONAL ? drawerRegion.value : '';
  router.push({ path: '/policy', query: { topicId: topicId ?? '', region } });
}

function showPolicy(policy: PolicyCoveragePolicy) {
  const rich = knowledgeByPid.value.get(policy.id);
  sourcePolicy.value = {
    title: policy.title,
    issuer: rich?.issuer ?? '',
    region: rich?.region ?? '',
    date: policy.issueDate || rich?.date || '',
    oneLiner: rich?.oneLiner ?? '',
    readingValue: rich?.readingValue ?? '',
    summary: rich?.summary ?? '',
    actions: rich?.actions ?? [],
  };
}
</script>

<template>
  <!-- 外壳:页头与时间窗口 -->
  <div class="page-head">
    <div>
      <div class="page-title">政策大盘 · 按 L2 主题与区划</div>
      <div class="page-sub">主题按 L2 主题编号命中 · 地区按 L1 区划代码归省 · 全国政策单列(独立版把地图换成了按省列表)</div>
    </div>
    <label class="pd-window">
      时间窗口
      <select v-model.number="days" class="filter-select" @change="refresh">
        <option v-for="d in WINDOWS" :key="d" :value="d">{{ d === 365 ? '近一年' : `近 ${d} 天` }}</option>
      </select>
    </label>
  </div>

  <div v-if="loading && !data" class="card empty">加载中...</div>

  <div v-else class="pd-grid">
    <!-- 外壳:主题勾选 -->
    <section class="card pd-topics">
      <div class="pd-card-head">
        <span>主题 {{ selectedTopics.length }}/{{ data?.topics.length || 0 }}</span>
        <span class="pd-head-actions">
          <button class="link-btn" type="button" @click="selectAll(true)">全选</button>
          <button class="link-btn" type="button" @click="selectAll(false)">全不选</button>
        </span>
      </div>
      <p v-if="!data?.topics.length" class="tbl-meta">这个时间窗口里没有挂主题的政策</p>
      <label v-for="t in data?.topics || []" :key="t.topicId" class="pd-topic" :class="{ on: checkedIds.has(t.topicId) }">
        <input type="checkbox" :checked="checkedIds.has(t.topicId)" @change="toggleTopic(t.topicId)" />
        <i class="pd-dot" :style="{ background: t.color }"></i>
        <span class="pd-topic-name">{{ t.name }}</span>
        <span class="pd-topic-cnt">{{ t.totalPolicies }} 条 · 全国 {{ t.national.policyCount }} · {{ t.totalRegions }} 个省份</span>
      </label>
    </section>

    <!-- 外壳:代替地图的按省份分布 -->
    <section class="card pd-provinces">
      <div class="pd-card-head">
        <span>按省份分布</span>
        <span class="tbl-meta">点一行看该省各主题的政策</span>
      </div>
      <p v-if="!provinceRows.length" class="tbl-meta">已选主题在各省都没有政策</p>
      <button v-for="row in provinceRows" :key="row.region" class="pd-province" type="button" @click="openRegion(row.region)">
        <span class="pd-province-name">{{ row.region }}</span>
        <span class="pd-province-bar"><span :style="{ width: `${(row.total / maxProvinceTotal) * 100}%` }"></span></span>
        <span class="pd-province-total">{{ row.total }}</span>
        <span class="pd-province-hits">
          <span v-for="h in row.hits" :key="h.topic.topicId" class="pd-hit">
            <i class="pd-dot" :style="{ background: h.topic.color }"></i>{{ h.topic.name }} {{ h.count }}
          </span>
        </span>
      </button>
    </section>

    <div class="pd-side">
      <!-- C5：全国政策(不属任何单省)单列 -->
      <button v-if="nationalTotal" class="card national-card" @click="openNational">
        <span class="national-icon">🇨🇳</span>
        <span class="national-text">全国政策</span>
        <span class="national-cnt">{{ nationalTotal }} 条</span>
      </button>

      <!-- 外壳:说明卡片的壳子;里面三行文字是我写的 -->
      <section class="card pd-note">
        <b>说明</b><br />
        主题按工程层 theme id 精确命中，地区按 L1 adcode 归并到省级；知识库共 {{ policyKnowledgeSource.policyCount }} 条政策。<br />
        · 全国性政策见上方"全国政策"<br />
        · 时间窗口影响覆盖范围
      </section>
    </div>
  </div>

  <!-- 外壳:省份 / 全国抽屉的壳子;条数那一行、v-for 那一行、日期和层级两项是我写的 -->
  <div class="pd-overlay" :class="{ open: drawerOpen }" @click="drawerOpen = false"></div>
  <aside class="pd-drawer" :class="{ open: drawerOpen }" aria-label="该地区各主题的政策">
    <header class="pd-drawer-head">
      <span><span class="pill pill-amber">{{ drawerRegion }}</span> 各主题的政策</span>
      <button class="pd-close" type="button" aria-label="关闭" @click="drawerOpen = false">×</button>
    </header>
    <div class="pd-drawer-body">
      <p v-if="!drawerTopicRows.length" class="tbl-meta">已选主题在这里没有政策</p>
      <section v-for="row in drawerTopicRows" :key="row.topic.topicId" class="pd-block">
        <div class="pd-block-head">
          <i class="pd-dot" :style="{ background: row.topic.color }"></i>
          <div>
            <b>{{ row.topic.name }}</b>
            <div class="pd-block-meta">
                {{ row.coverage.policyCount }} 条 · 重要 {{ row.coverage.majorCount }} · 战略 {{ row.coverage.strategicCount }}
            </div>
          </div>
          <button class="link-btn" type="button" @click="goThemeAnalysis(row.topic.topicId)">主题分析</button>
        </div>
          <button
            v-for="policy in row.coverage.policies.slice(0, 8)"
            :key="policy.id"
            class="pd-policy"
            type="button"
            @click="showPolicy(policy)">
            <span class="pd-policy-title">{{ policy.title }}</span>
            <span class="pd-policy-meta">
              <span>重要性 {{ policy.importance }}</span><!-- 外壳 -->
              <span>{{ policy.issueDate || '-' }}</span>
              <span v-if="policy.regionLevel">{{ policy.regionLevel }}级</span>
            </span>
          </button>
      </section>
    </div>
  </aside>

  <!-- 外壳:政策详情弹层的壳子;地区、日期两项和"政策摘要"一行是我写的 -->
  <div v-if="sourcePolicy" class="pd-mask" @click.self="sourcePolicy = null">
    <article class="pd-detail">
      <header class="pd-detail-head">
        <h3>{{ sourcePolicy.title }}</h3>
        <button class="pd-close" type="button" aria-label="关闭" @click="sourcePolicy = null">×</button>
      </header>
      <div class="pd-detail-meta">
        <span>{{ sourcePolicy.issuer || '发文机关未知' }}</span>
        <span>{{ sourcePolicy.region || '未知地区' }}</span>
        <span>{{ sourcePolicy.date || '-' }}</span>
      </div>
      <dl class="pd-detail-body">
        <dt>一句话</dt>
        <dd>{{ sourcePolicy.oneLiner || '—' }}</dd>
        <template v-if="sourcePolicy.readingValue">
          <dt>阅读价值</dt>
          <dd>{{ sourcePolicy.readingValue }}</dd>
        </template>
        <dt>摘要</dt>
        <dd>
        <p>{{ sourcePolicy.summary || '暂无' }}</p>
        </dd>
        <template v-if="sourcePolicy.actions.length">
          <dt>行动建议</dt>
          <dd><ul><li v-for="(a, i) in sourcePolicy.actions" :key="i">{{ a }}</li></ul></dd>
        </template>
      </dl>
    </article>
  </div>
</template>

<style scoped>
.national-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  cursor: pointer;
  border: 1px solid var(--orange-soft-2, var(--line));
  background: linear-gradient(90deg, rgba(249, 115, 22, 0.08) 0%, transparent 100%);
  text-align: left;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.national-card:hover {
  border-color: var(--orange-2, #ea580c);
  box-shadow: 0 4px 14px rgba(249, 115, 22, 0.16);
}
.national-icon { font-size: 16px; }
.national-text { font-size: 13px; font-weight: 600; color: var(--ink-2); }
.national-cnt {
  margin-left: auto;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12.5px;
  color: var(--orange-2, #ea580c);
  font-weight: 700;
}

/* ── 外壳样式(独立版补的) ── */
.pd-window { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--ink-3); }
.pd-grid { display: grid; grid-template-columns: 250px minmax(0, 1fr) 260px; gap: 14px; align-items: start; }
.pd-card-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 10px; font-size: 13px; font-weight: 700; color: var(--ink-2); }
.pd-head-actions { display: flex; gap: 10px; }
.pd-topics, .pd-provinces { padding: 14px; }
.pd-topic { display: grid; grid-template-columns: auto auto 1fr; align-items: center; gap: 4px 8px; padding: 8px; border-radius: 8px; cursor: pointer; border: 1px solid transparent; }
.pd-topic.on { background: var(--bg-1); border-color: var(--line); }
.pd-topic-name { font-size: 13px; color: var(--ink); }
.pd-topic-cnt { grid-column: 3; font-size: 11.5px; color: var(--ink-3); }
.pd-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.pd-province { display: grid; grid-template-columns: 116px minmax(60px, 1fr) 40px; align-items: center; gap: 4px 10px; width: 100%; padding: 9px 8px; border: 0; border-bottom: 1px solid var(--line-2); background: none; font: inherit; color: inherit; text-align: left; cursor: pointer; }
.pd-province:hover { background: var(--bg-1); }
.pd-province-name { font-size: 13px; font-weight: 600; color: var(--ink); }
.pd-province-bar { height: 8px; border-radius: 4px; background: var(--bg-2); overflow: hidden; }
.pd-province-bar span { display: block; height: 100%; border-radius: 4px; background: var(--orange); }
.pd-province-total { font-size: 13px; font-weight: 700; color: var(--ink-2); text-align: right; font-variant-numeric: tabular-nums; }
.pd-province-hits { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 11.5px; color: var(--ink-3); }
.pd-hit { display: inline-flex; align-items: center; gap: 4px; }
.pd-side { display: flex; flex-direction: column; gap: 12px; }
.pd-note { padding: 14px 16px; font-size: 12px; color: var(--ink-3); line-height: 1.8; }
.pd-note b { color: var(--ink-2); }
.pd-overlay { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.32); opacity: 0; pointer-events: none; transition: opacity 0.2s; z-index: 60; }
.pd-overlay.open { opacity: 1; pointer-events: auto; }
.pd-drawer { position: fixed; top: 0; right: 0; bottom: 0; width: min(620px, 100vw); background: var(--white); box-shadow: -12px 0 32px rgba(15, 23, 42, 0.18); transform: translateX(105%); transition: transform 0.22s; z-index: 61; display: flex; flex-direction: column; }
.pd-drawer.open { transform: none; }
.pd-drawer-head { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; border-bottom: 1px solid var(--line); font-weight: 700; color: var(--ink); }
.pd-drawer-body { overflow: auto; padding: 14px 16px; display: grid; gap: 12px; align-content: start; }
.pd-close { width: 32px; height: 32px; border: 0; border-radius: 16px; background: var(--bg); color: var(--ink-2); font-size: 18px; cursor: pointer; flex-shrink: 0; }
.pd-block { border: 1px solid var(--line); border-radius: 10px; padding: 12px; }
.pd-block-head { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 10px; margin-bottom: 6px; color: var(--ink); }
.pd-block-meta { margin-top: 2px; font-size: 12px; color: var(--ink-3); }
.link-btn { border: 0; background: none; color: var(--orange-2); font: inherit; font-size: 12px; cursor: pointer; padding: 0; }
.pd-policy { display: block; width: 100%; text-align: left; border: 0; border-top: 1px solid var(--line-2); background: none; padding: 8px 2px; font: inherit; color: inherit; cursor: pointer; }
.pd-policy:hover { background: var(--bg-1); }
.pd-policy-title { display: block; font-size: 13px; color: var(--ink); line-height: 1.5; }
.pd-policy-meta { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 3px; font-size: 11.5px; color: var(--ink-3); }
.pd-mask { position: fixed; inset: 0; z-index: 70; background: rgba(15, 23, 42, 0.42); display: flex; align-items: center; justify-content: center; padding: 16px; }
.pd-detail { width: min(680px, 100%); max-height: 86vh; overflow: auto; background: var(--white); border-radius: 12px; padding: 18px 20px; box-shadow: var(--shadow-lg); }
.pd-detail-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.pd-detail-head h3 { margin: 0; font-size: 16px; line-height: 1.5; color: var(--ink); }
.pd-detail-meta { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 4px; font-size: 12px; color: var(--ink-3); }
.pd-detail-meta span { background: var(--bg-1); border-radius: 6px; padding: 2px 8px; }
.pd-detail-body { margin: 8px 0 0; }
.pd-detail-body dt { margin-top: 12px; font-size: 12px; font-weight: 700; color: var(--ink-2); }
.pd-detail-body dd { margin: 4px 0 0; font-size: 13px; line-height: 1.7; color: var(--ink); }
.pd-detail-body p { margin: 0; }
.pd-detail-body ul { margin: 0; padding-left: 20px; }
@media (max-width: 1100px) {
  .pd-grid { grid-template-columns: 1fr; }
}
@media (max-width: 520px) {
  .pd-province { grid-template-columns: 84px minmax(40px, 1fr) 36px; }
}
</style>
