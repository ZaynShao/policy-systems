<!--
  独立版演示外壳:原平台的顶栏、侧栏和路由都是同事写的,不在本仓。这里给一个最小外壳,
  顶栏挂我写的消息铃铛,导航切换我写的几块:L1 源质量审核、政策大盘(按 L2 主题与区划)、移动端拜访录入,外加一页说明。
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import NotificationBell from '@/components/layout/NotificationBell.vue';
import L1ReviewQueue from '@/views/quality/L1ReviewQueue.vue';
import PolicyDashboard from '@/views/dashboard/PolicyDashboard.vue';
import ToastHost from '../shared/ToastHost.vue';
import VisitDemo from './VisitDemo.vue';
import type { DemoApi, DemoData } from './mock';

const props = defineProps<{ data: DemoData; api: DemoApi }>();

const TABS = [
  { id: 'l1', label: 'L1 源质量审核' },
  { id: 'dashboard', label: '政策大盘' },
  { id: 'visit', label: '移动端拜访录入' },
  { id: 'about', label: '说明' },
] as const;
type TabId = (typeof TABS)[number]['id'];

function fromHash(): TabId {
  const h = location.hash.replace(/^#/, '');
  return (TABS.find((t) => t.id === h)?.id ?? 'l1') as TabId;
}
const tab = ref<TabId>(fromHash());
const onHash = () => { tab.value = fromHash(); };
onMounted(() => addEventListener('hashchange', onHash));
onBeforeUnmount(() => removeEventListener('hashchange', onHash));

const me = props.data['visit-directory'].me;
const meta = props.data.meta;
const l1Real = computed(() => props.data['l1-review'].filter((r) => r.runLabel !== '示意样例').length);
const l1Sample = computed(() => props.data['l1-review'].length - l1Real.value);
</script>

<template>
  <div class="ps-demo-bar" role="note">
    <b>演示版</b>
    <span>数据内置、不联网;裁决、已读、新建拜访只在本页生效,刷新即还原。数据来历见「说明」。</span>
  </div>

  <header class="ps-top">
    <div class="ps-brand">
      <span class="ps-brand-mark">公</span>
      <span><b>公共事务平台</b><small>政策功能 · 个人版</small></span>
    </div>
    <div class="ps-top-right">
      <span class="ps-user" :title="`${me.name} · 管理层`"><span class="ps-avatar">演</span><span class="ps-user-name">{{ me.name }} · 管理层</span></span>
      <NotificationBell />
    </div>
  </header>

  <div class="ps-body">
    <nav class="ps-nav" aria-label="功能">
      <a v-for="t in TABS" :key="t.id" :href="`#${t.id}`" :aria-current="tab === t.id ? 'page' : undefined">{{ t.label }}</a>
    </nav>

    <main class="ps-main">
      <L1ReviewQueue v-if="tab === 'l1'" />
      <PolicyDashboard v-else-if="tab === 'dashboard'" />
      <VisitDemo v-else-if="tab === 'visit'" :api="api" :samples="data['voice-samples']" />
      <section v-else class="ps-about">
        <div class="page-head">
          <div>
            <div class="page-title">说明</div>
            <div class="page-sub">公共事务平台(同事们的大平台)里,我加的几块功能的独立版</div>
          </div>
        </div>

        <div class="card">
          <h3>这里有什么</h3>
          <ul>
            <li><b>L1 源质量审核</b>(原项目 PR 17、49):pipeline 采集时机器拿不准的项(候选渠道、质量门低置信、误分类扫描、抓取失败)进审核池,同步到这里,管理员逐条看证据、裁决,结果回灌 pipeline。</li>
            <li><b>站内消息</b>(原项目 PR 16):右上角铃铛。政策库同步出错时 pipeline 会写一条消息,只对管理层显示,点一条标为已读。</li>
            <li><b>移动端拜访录入</b>(原项目 PR 48、74):手机上新建拜访,说一段话由后端解析成地区、机构、对接人、主题、目标、时间,自动填表。</li>
            <li><b>政策大盘对齐 L2</b>(原项目 PR 124):大盘主题改按 L2 主题编号命中,地区按 L1 区划代码归到省,国家级政策单列"全国"。</li>
          </ul>
          <p class="tbl-meta">页面里标"外壳"的部分(顶栏、导航、大盘的主题勾选与按省列表、拜访列表框等)是独立版补的;原平台的这些部分是同事写的,不收。</p>
        </div>

        <div class="card">
          <h3>演示数据从哪来</h3>
          <ul>
            <li><b>L1 审核池 {{ data['l1-review'].length }} 条</b>:{{ l1Real }} 条是真实的——本仓渠道清单里还挂着"候选"的渠道发现结果(2026-06-07、08 两轮),用 pipeline 里我写的进池、同步函数原样转成审核行;另 {{ l1Sample }} 条标着"示意样例",是按真实结构编的(本机没有质量门、误分类扫描、抓取失败这三类的真实待审项)。</li>
            <li><b>政策大盘</b>:本机政策库({{ meta.vault.committed_at }} 的版本,{{ meta.vault.knowledge_entries }} 条政策、{{ meta.vault.themes }} 个主题)按原平台知识库的口径取字段,再用我写的聚合函数算出 30 / 90 / 180 / 365 天四个窗口,{{ meta.recorded_at }} 录制。</li>
            <li><b>拜访语音解析</b>:要调大模型,演示版回放后端测试里两段口述的解析结果(用我写的解析服务跑出来的)。机构、主拜访人是演示用的。</li>
            <li><b>站内消息 {{ data.notifications.length }} 条</b>:按这些功能会发的消息编的(同步失败、待审提醒),不带人名。</li>
            <li><b>"AI 解读"</b>:原来调大模型生成;演示版没有接模型,改成按审核项字段拼的一段说明,并写明不是 AI 生成。</li>
          </ul>
        </div>
      </section>
    </main>
  </div>

  <ToastHost />
</template>

<style scoped>
.ps-demo-bar { display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; padding: 7px 16px; font-size: 12.5px; color: #9a3412; background: #fff7ed; border-bottom: 1px solid #fdba74; }
.ps-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 16px; background: var(--white); border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 40; }
.ps-brand { display: flex; align-items: center; gap: 10px; color: var(--ink); }
.ps-brand b { display: block; font-size: 15px; }
.ps-brand small { display: block; font-size: 11.5px; color: var(--ink-3); }
.ps-brand-mark { width: 32px; height: 32px; border-radius: 9px; background: var(--orange); color: #fff; display: grid; place-items: center; font-weight: 800; }
.ps-top-right { display: flex; align-items: center; gap: 14px; }
.ps-user { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: var(--ink-2); }
.ps-avatar { width: 28px; height: 28px; border-radius: 50%; background: var(--orange-soft); color: var(--orange-2); display: grid; place-items: center; font-weight: 700; font-size: 12px; }
.ps-body { display: grid; grid-template-columns: 188px minmax(0, 1fr); min-height: calc(100vh - 90px); }
.ps-nav { display: flex; flex-direction: column; gap: 4px; padding: 14px 10px; border-right: 1px solid var(--line); background: var(--white); }
.ps-nav a { padding: 9px 12px; border-radius: 8px; color: var(--ink-2); text-decoration: none; font-size: 13.5px; }
.ps-nav a:hover { background: var(--bg-2); }
.ps-nav a[aria-current='page'] { background: var(--orange-soft); color: var(--orange-2); font-weight: 700; }
.ps-main { padding: 18px 20px 40px; min-width: 0; }
.ps-about .card { padding: 16px 18px; margin-bottom: 14px; font-size: 13.5px; line-height: 1.75; color: var(--ink-2); }
.ps-about h3 { margin: 0 0 6px; font-size: 15px; color: var(--ink); }
.ps-about ul { margin: 0; padding-left: 20px; }
@media (max-width: 760px) {
  .ps-body { grid-template-columns: 1fr; }
  .ps-nav { flex-direction: row; overflow-x: auto; border-right: 0; border-bottom: 1px solid var(--line); padding: 8px 10px; }
  .ps-nav a { white-space: nowrap; }
  .ps-main { padding: 14px 16px 32px; }
  .ps-user-name { display: none; }
  .ps-brand small { display: none; }
}
</style>
