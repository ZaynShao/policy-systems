<!--
  月刊列表页。这个文件原来是同事建的(原平台「政策分析」的列表页),本仓只收我写的部分,其余是独立版的最小外壳。

  我写的(原项目 PR 1185,原样照搬,下面标「我写的」):引入 monthly-content 的那几行,
  extractKeywords / summaryText / detailCount 三个函数(卡片的标签、摘要、篇数改走两套 schema 的共用判断),
  以及卡片上「政策详情」篇数那一格。
  外壳(独立版新写,下面标「外壳」):取列表、卡片排版。
  同事写的新建分析、月度/专题页签、引用政策数、状态标签等没有收。
-->
<script setup lang="ts">
// ── 外壳 ──────────────────────────────────────────────────────
import { onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { monthlyApi, type MonthlyListItem } from '@/api/monthly';
import { useToastStore } from '@/stores/toast';
// ── 我写的 ────────────────────────────────────────────────────
import {
  detailCount as contentDetailCount,
  extractKeywords as contentKeywords,
  summaryText as contentSummary,
} from './monthly-content';

// ── 外壳 ──────────────────────────────────────────────────────
const router = useRouter();
const toast = useToastStore();
const list = ref<MonthlyListItem[]>([]);
const loading = ref(false);
const EN_MONTH = ['', 'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];

async function load() {
  loading.value = true;
  try {
    list.value = (await monthlyApi.list()).filter((m) => m.type === 'MONTHLY');
  } catch (e: any) {
    toast.push(e?.message ?? '加载失败', 'error');
  } finally {
    loading.value = false;
  }
}
onMounted(load);

// ── 我写的 ────────────────────────────────────────────────────
// 关键词、摘要、篇数三处都必须分辨 schema：v2 没有 policyBlocks，
// 不分辨的话新刊的卡片会显示 0 政策详情、没有标签。判断逻辑在 monthly-content.ts，
// 那边能被 node --test 直接跑到。
function extractKeywords(m: MonthlyListItem) {
  return contentKeywords(m.content).slice(0, 6);
}

function summaryText(m: MonthlyListItem) {
  const ov = contentSummary(m.content);
  return ov.length > 240 ? ov.slice(0, 240) + '…' : ov;
}

function detailCount(m: MonthlyListItem) {
  return contentDetailCount(m.content);
}
</script>

<template>
  <!-- 外壳:页头与卡片 -->
  <div class="page-head">
    <div>
      <div class="page-title">政策月刊</div>
      <div class="page-sub">每月一期 · 新版月刊(monthly.v2)渲染</div>
    </div>
  </div>

  <div v-if="loading && !list.length" class="empty">加载中...</div>
  <div v-else-if="!list.length" class="empty">尚未生成</div>
  <div v-for="(m, i) in list" :key="m.id" class="monthly-card" :class="{ latest: i === 0 }"
       role="link" tabindex="0"
       @click="router.push(`/monthlies/${m.id}`)" @keydown.enter="router.push(`/monthlies/${m.id}`)">
    <div class="monthly-card-date">
      <div class="y">{{ m.year }}</div>
      <div class="m">{{ String(m.month ?? '').padStart(2, '0') }}</div>
      <div class="mtag">{{ EN_MONTH[m.month ?? 0] }}</div>
    </div>

    <div class="monthly-card-main">
      <div class="monthly-card-meta">
        <span class="pill" :class="i === 0 ? 'pill-amber' : 'pill-green'">{{ i === 0 ? '最新' : '已发布' }}</span>
        <span>{{ m.status === 'PUBLISHED' ? '已发布 · ' + (m.publishDate?.slice(0, 10) ?? '') : '草稿 · v' + m.version }}</span>
      </div>
      <div class="monthly-card-title">{{ m.title }}</div>
      <div class="monthly-card-summary">{{ summaryText(m) }}</div>
      <div class="monthly-card-tags">
        <span v-for="(kw, idx) in extractKeywords(m)" :key="kw" class="tag" :class="idx < 2 ? 'tag-orange' : ''">{{ kw }}</span>
      </div>
    </div>

    <div class="monthly-card-count">
        <div><strong style="color:var(--ink);font-size:18px;font-family:inherit">{{ detailCount(m) }}</strong><br />政策详情</div>
    </div>
  </div>
</template>
