<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { l1ReviewApi, type L1ReviewItem } from '@/api/l1Review';
import { useToastStore } from '@/stores/toast';

const VERDICTS: Record<string, { value: string; label: string }[]> = {
  gate: [
    { value: 'pass', label: 'pass=当政策收' },
    { value: 'commentary', label: 'commentary=当评论收' },
    { value: 'reject', label: 'reject=弃' },
  ],
  checkpoint: [
    { value: 'promote', label: 'promote=提升去验证' },
    { value: 'drop', label: 'drop=移除候选' },
  ],
  sweep: [
    { value: 'confirm', label: 'confirm=确认误分类(挪走)' },
    { value: 'keep', label: 'keep=不动' },
  ],
  fetch_fail: [
    { value: 'retry', label: 'retry=换参数重抓' },
    { value: 'unfetchable', label: 'unfetchable=标记抓不了' },
    { value: 'drop', label: 'drop=跳过' },
  ],
};

const kindOptions = ['gate', 'checkpoint', 'sweep', 'fetch_fail'];
const toast = useToastStore();
const items = ref<L1ReviewItem[]>([]);
const kind = ref('');
const loading = ref(false);
const narrating = reactive<Record<string, boolean>>({});
const submitting = reactive<Record<string, boolean>>({});
const verdicts = reactive<Record<string, string>>({});
const notes = reactive<Record<string, string>>({});
const correctedLabels = reactive<Record<string, string>>({});
const retryParams = reactive<Record<string, string>>({});

const countText = computed(() => `${items.value.length} 条待判项`);

async function load() {
  loading.value = true;
  try {
    items.value = await l1ReviewApi.list(kind.value || undefined);
    items.value.forEach((item) => {
      if (!verdicts[item.id]) verdicts[item.id] = VERDICTS[item.pipelineKind]?.[0]?.value ?? '';
      if (!item.aiNarration) void narrate(item);
    });
  } catch (e: any) {
    toast.push(e.message || '加载失败', 'error');
  } finally {
    loading.value = false;
  }
}

async function narrate(item: L1ReviewItem) {
  if (item.aiNarration || narrating[item.id]) return;
  narrating[item.id] = true;
  try {
    const updated = await l1ReviewApi.narrate(item.id);
    item.aiNarration = updated.aiNarration;
    item.aiNarratedAt = updated.aiNarratedAt;
  } catch (e: any) {
    toast.push(e.message || 'AI 解读生成失败', 'error');
  } finally {
    narrating[item.id] = false;
  }
}

function buildCorrections(item: L1ReviewItem) {
  if (item.pipelineKind === 'gate' && correctedLabels[item.id]?.trim()) {
    return { corrected_label: correctedLabels[item.id].trim() };
  }
  if (item.pipelineKind === 'fetch_fail' && retryParams[item.id]?.trim()) {
    return { retry_params: JSON.parse(retryParams[item.id]) };
  }
  return undefined;
}

async function submit(item: L1ReviewItem) {
  const verdict = verdicts[item.id];
  if (!verdict) {
    toast.push('请选择裁决', 'warning');
    return;
  }
  submitting[item.id] = true;
  try {
    const corrections = buildCorrections(item);
    await l1ReviewApi.submitVerdict(item.id, {
      verdict,
      note: notes[item.id]?.trim() || undefined,
      corrections,
    });
    items.value = items.value.filter((x) => x.id !== item.id);
    toast.push('已提交裁决');
  } catch (e: any) {
    toast.push(e.message || '提交失败', 'error');
  } finally {
    submitting[item.id] = false;
  }
}

function kindText(value: string) {
  const map: Record<string, string> = {
    gate: '采集入口',
    checkpoint: '候选渠道',
    sweep: '误分类扫描',
    fetch_fail: '抓取失败',
  };
  return map[value] ?? value;
}

onMounted(load);
</script>

<template>
  <div class="page-head review-head">
    <div>
      <div class="page-title">L1 源质量审核</div>
      <div class="page-sub">AI 只辅助解释，真实证据与裁决选项并列展示，人工裁决后回灌 pipeline。</div>
    </div>
    <div class="review-count">{{ countText }}</div>
  </div>

  <div class="card review-filter">
    <div class="filter-bar">
      <select v-model="kind" class="filter-select" @change="load">
        <option value="">全部类型</option>
        <option v-for="k in kindOptions" :key="k" :value="k">{{ kindText(k) }}</option>
      </select>
      <button class="btn" :disabled="loading" @click="load">{{ loading ? '加载中...' : '刷新' }}</button>
    </div>
  </div>

  <div v-if="loading && !items.length" class="card empty">加载中...</div>
  <div v-else-if="!items.length" class="card empty">暂无待判项</div>

  <div v-else class="review-list">
    <div v-for="item in items" :key="item.id" class="card review-card">
      <div class="review-card-head">
        <div>
          <div class="review-meta">
            <span class="pill pill-amber">{{ kindText(item.pipelineKind) }}</span>
            <span v-if="item.runLabel" class="tbl-time">{{ item.runLabel }}</span>
            <span class="tbl-time">{{ new Date(item.createdAt).toLocaleString() }}</span>
          </div>
          <div class="review-ref">{{ item.pipelineRef }}</div>
        </div>
      </div>

      <section class="review-section ai-section">
        <div class="section-title">AI 解读</div>
        <p v-if="item.aiNarration">{{ item.aiNarration }}</p>
        <p v-else class="tbl-meta">{{ narrating[item.id] ? 'AI 解读生成中…' : '等待生成 AI 解读' }}</p>
      </section>

      <details class="review-section evidence-section" open>
        <summary>真证据</summary>
        <div class="evidence-grid">
          <div><span>pipelineRef</span><strong>{{ item.pipelineRef }}</strong></div>
          <div><span>reason</span><strong>{{ item.reason || '-' }}</strong></div>
          <div><span>suggestedAction</span><strong>{{ item.suggestedAction || '-' }}</strong></div>
          <div><span>confidence</span><strong>{{ item.confidence ?? '-' }}</strong></div>
          <div><span>channel</span><strong>{{ item.channel || '-' }}</strong></div>
          <div class="evidence-full"><span>evidence</span><strong>{{ item.evidence || '-' }}</strong></div>
        </div>
      </details>

      <div class="verdict-row">
        <select v-model="verdicts[item.id]" class="filter-select">
          <option v-for="v in VERDICTS[item.pipelineKind]" :key="v.value" :value="v.value">{{ v.label }}</option>
        </select>
        <input v-model="notes[item.id]" class="note-input" placeholder="备注（可选）" />
      </div>

      <div v-if="item.pipelineKind === 'gate'" class="correction-row">
        <input v-model="correctedLabels[item.id]" class="note-input" placeholder="corrected_label（可选）" />
      </div>
      <div v-else-if="item.pipelineKind === 'fetch_fail'" class="correction-row">
        <textarea v-model="retryParams[item.id]" class="json-input" placeholder='retry_params JSON（可选），例如 {"timeout":30}' />
      </div>

      <div class="card-actions">
        <button class="btn btn-primary" :disabled="submitting[item.id]" @click="submit(item)">
          {{ submitting[item.id] ? '提交中...' : '提交' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.review-head { align-items: center; }
.review-count { color: var(--ink-3); font-size: 13px; }
.review-filter { margin-bottom: 14px; }
.review-list { display: grid; gap: 14px; }
.review-card { padding: 16px; }
.review-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.review-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  color: var(--ink-3);
  font-size: 12px;
}
.review-ref {
  margin-top: 8px;
  font-size: 16px;
  font-weight: 700;
  color: var(--ink-1);
  word-break: break-all;
}
.review-section {
  border: 1px solid var(--line-2);
  border-radius: 8px;
  padding: 12px;
  margin-top: 10px;
}
.section-title,
.evidence-section summary {
  font-size: 13px;
  font-weight: 700;
  color: var(--ink-2);
}
.ai-section p {
  margin: 8px 0 0;
  line-height: 1.7;
}
.evidence-section summary { cursor: pointer; }
.evidence-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}
.evidence-grid div {
  background: var(--bg-1);
  border-radius: 6px;
  padding: 10px;
  min-width: 0;
}
.evidence-grid span {
  display: block;
  color: var(--ink-3);
  font-size: 12px;
  margin-bottom: 6px;
}
.evidence-grid strong {
  display: block;
  color: var(--ink-1);
  font-size: 13px;
  font-weight: 600;
  white-space: pre-wrap;
  word-break: break-word;
}
.evidence-full { grid-column: 1 / -1; }
.verdict-row,
.correction-row {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 10px;
  margin-top: 12px;
}
.correction-row { grid-template-columns: minmax(0, 1fr); }
.note-input,
.json-input {
  width: 100%;
  border: 1px solid var(--line-2);
  border-radius: 6px;
  padding: 8px 10px;
  font: inherit;
}
.json-input {
  min-height: 72px;
  resize: vertical;
}
.card-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
@media (max-width: 760px) {
  .evidence-grid,
  .verdict-row {
    grid-template-columns: 1fr;
  }
}
</style>
