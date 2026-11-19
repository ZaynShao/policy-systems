<!--
  月刊详情页。这个文件原来是同事建的(原平台「政策月刊分析」的详情页),本仓只收我写的部分,其余是独立版的最小外壳。

  我写的(原项目 PR 1185,原样照搬,下面标「我写的」):
    - script 里引入 monthly-content 的那一行,和「monthly.v2」「修改意见回炉」两段;
    - template 里的「容错提示条」「新版月刊(monthly.v2)正文」两块(含修改意见栏),
      以及把老数据包成另一个分支的那一层(老数据注释、分支开头那一行和结尾的收口)。
  外壳(独立版新写,下面标「外壳」):取数 load()、页头与封面、老数据(v1)分支的最简显示。
  同事写的部分都没有收:页头按钮(历史版本、导出、发布)、右侧 AI 对话面板、老数据分支原来的完整排版
  (我在那一支里改过的两处 `?? ''` 随之不收)。原平台的全站样式也是同事的,独立版的样式见
  src/standalone/monthly/theme.css。
-->
<script setup lang="ts">
// ── 外壳 ──────────────────────────────────────────────────────
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { monthlyApi, type MonthlyDetail } from '@/api/monthly';
import { useToastStore } from '@/stores/toast';
// ── 我写的 ────────────────────────────────────────────────────
import { caveatBanner, detectSchema, normalizeV2, v2Chapters } from './monthly-content';

// ── 外壳 ──────────────────────────────────────────────────────
const route = useRoute();
const router = useRouter();
const toast = useToastStore();

const detail = ref<MonthlyDetail | null>(null);
const loading = ref(false);
const EN_MONTH = ['', 'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];

async function load() {
  const id = String(route.params.id ?? '');
  loading.value = true;
  try {
    const got = await monthlyApi.detail(id);
    if (String(route.params.id ?? '') === id) detail.value = got;
  } catch (e: any) {
    detail.value = null;
    toast.push(e?.message ?? '加载失败', 'error');
  } finally {
    loading.value = false;
  }
}
onMounted(load);
// 独立版在几期之间切换时复用这个页面,换一期要重新取数
watch(() => route.params.id, (id) => { if (id) load(); });

// ── 我写的 ────────────────────────────────────────────────────
// ── monthly.v2 ────────────────────────────────────────────────
// 老数据(v1)不会重生成,两套 schema 要并存很久。判断与视图模型都在
// monthly-content.ts 里,那边能被 `node --test` 跑到;这里只做取值。
const isV2 = computed(() => detectSchema(detail.value?.content) === 'v2');
const v2 = computed(() => normalizeV2(detail.value?.content ?? {}));
const chapters = computed(() => v2Chapters(v2.value));
const banner = computed(() => caveatBanner(detail.value?.content));

function sectionBody(key: string): string {
  return v2.value.sections.find((s) => s.key === key)?.body ?? '';
}

function gotoLink(link: string) {
  if (link) router.push(link);
}

// ── 修改意见回炉 ──────────────────────────────────────────────
// 门没过的段落照常发布、挂容错提示,再由读者提意见回炉——这是产品口径,
// 不是降级。意见存进 content.pendingNote,产线下一轮读它并重过一遍门。
const noteDraft = ref('');
const savingNote = ref(false);

async function submitNote() {
  const note = noteDraft.value.trim();
  if (!note || !detail.value) return;
  savingNote.value = true;
  try {
    await monthlyApi.revisionNote(detail.value.id, note);
    noteDraft.value = '';
    await load();
    toast.push('修改意见已记录,将在下一轮回炉时处理');
  } catch (e: any) {
    toast.push(e?.message ?? '提交失败', 'error');
  } finally {
    savingNote.value = false;
  }
}
</script>

<template>
  <!-- 外壳:取数中 / 没有这一期 -->
  <div v-if="!detail" class="empty">{{ loading ? '加载中...' : '没有找到这一期月刊' }}</div>

  <template v-else>
    <!-- 外壳:页头 -->
    <div class="page-head">
      <div>
        <div class="page-title">{{ detail.title }}</div>
        <div class="page-sub">
          {{ detail.status === 'PUBLISHED' ? '已发布' : '草稿' }}
          <template v-if="detail.publishDate">· {{ detail.publishDate.slice(0, 10) }}</template>
          · v{{ detail.version }}
        </div>
      </div>
    </div>

    <div class="monthly-layout">
      <div class="monthly-doc">
        <!-- 外壳:封面 -->
        <div class="monthly-cover">
          <div class="monthly-cover-en">ENERGY POLICY MONTHLY · {{ EN_MONTH[detail.month ?? 0] }} {{ detail.year }}</div>
          <div class="monthly-cover-cn">能源政策月刊</div>
          <div class="monthly-cover-meta">
            {{ detail.year }} 年 {{ detail.month }} 月 · 编制单位 滴滴能源安全生态中心
            <template v-if="detail.publishDate">· 发布日期 {{ detail.publishDate.slice(0, 10) }}</template>
          </div>
        </div>

        <!-- ── 以下到老数据分支的开头是我写的 ── -->
        <!-- 容错提示条:门没过、返修两轮仍有残留时出现 -->
        <div v-if="banner.show" class="tip-box warn" style="margin-bottom:20px">
          <div class="tip-box-label"><span class="tb-icon">!</span>本期成稿说明</div>
          <p>{{ banner.text }}</p>
          <ul style="margin:8px 0 0;padding-left:18px">
            <li v-for="item in banner.items" :key="item.where">
              {{ item.where }}<template v-if="item.notes.length">：{{ item.notes.join('；') }}</template>
            </li>
          </ul>
        </div>

        <!-- ── monthly.v2 ── 正文是纯文字(D 门禁 markdown),故一律文本插值不用 v-html -->
        <template v-if="isV2">
          <div v-if="v2.narrative" class="monthly-overview" style="font-weight:600">{{ v2.narrative }}</div>

          <template v-for="ch in chapters" :key="ch.key">
            <div class="monthly-chapter">
              <div class="monthly-chapter-num">{{ ch.num }}</div>
              <h2>{{ ch.title }}</h2>
              <span class="ch-sub">{{ ch.sub }}</span>
            </div>

            <template v-if="ch.key === 'overview'">
              <div v-if="sectionBody('overview')" class="monthly-overview">{{ sectionBody('overview') }}</div>
              <div v-for="t in v2.businessTakes" :key="t.business" class="tip-box insight">
                <div class="tip-box-label"><span class="tb-icon">!</span>{{ t.business }}业务</div>
                <p>{{ t.text }}</p>
              </div>
            </template>

            <table v-else-if="ch.key === 'quickTable'" class="overview-table">
              <thead>
                <tr><th v-for="(h, i) in v2.quickTable.head" :key="h" :style="i === 0 ? 'width:80px' : ''">{{ h }}</th></tr>
              </thead>
              <tbody>
                <tr v-for="(row, i) in v2.quickTable.rows" :key="i">
                  <td v-for="(cell, j) in row" :key="j" :class="j === 0 ? 'col-cat' : ''">{{ cell }}</td>
                </tr>
              </tbody>
            </table>

            <template v-else-if="ch.key === 'details'">
              <div v-for="d in v2.details" :key="d.no" class="policy-block">
                <div class="policy-block-num">{{ d.no }}</div>
                <h3 :style="{ cursor: d.link ? 'pointer' : 'default' }"
                    :title="d.link ? '点击查看政策原文' : ''"
                    @click="gotoLink(d.link)">
                  {{ d.title }}
                  <span v-if="d.link" style="font-size:11px;color:var(--orange-2);margin-left:6px;font-weight:500">⇲ 查看原文</span>
                </h3>

                <div class="policy-section-tag info">【政策信息】</div>
                <div class="policy-content-text">{{ d.info }}</div>

                <div class="policy-section-tag content">【政策解读】</div>
                <div class="policy-content-text">{{ d.reading }}</div>

                <div class="policy-section-tag focus">【重点关注内容】</div>
                <div class="policy-content-text">{{ d.focus }}</div>

                <template v-if="d.advice.length">
                  <div class="policy-section-tag content">【决策建议】</div>
                  <div v-for="(a, ai) in d.advice" :key="ai" class="tip-box">
                    <div class="tip-box-label"><span class="tb-icon">!</span>{{ a.business }}业务 · {{ a.tag }}</div>
                    <p>{{ a.text }}</p>
                  </div>
                </template>
              </div>
            </template>

            <div v-else class="monthly-overview">{{ sectionBody(ch.key) }}</div>
          </template>

          <!-- 修改意见栏 -->
          <div style="margin-top:28px;padding:18px;border:1px solid var(--line);border-radius:10px;background:var(--white)">
            <div style="font-size:15px;font-weight:600;color:var(--ink);margin-bottom:6px">修改意见</div>
            <p style="font-size:12px;color:var(--ink-3);line-height:1.7;margin:0 0 10px">
              指出哪一段不对、应该怎么写。意见会连同原文与素材一起回炉重写,并重新过一遍审核门;
              没有原文依据的要求不会被写进稿子。
            </p>
            <textarea v-model="noteDraft" rows="4" placeholder="例如：详情 01 的政策解读把生效日写成了发文日，应以正文落款为准。"
              style="width:100%;box-sizing:border-box;padding:10px;border:1px solid var(--line);border-radius:8px;font-size:13px;line-height:1.7;resize:vertical"></textarea>
            <div style="margin-top:10px;display:flex;align-items:center;gap:12px">
              <button class="btn btn-primary" :disabled="!noteDraft.trim() || savingNote" @click="submitNote">
                {{ savingNote ? '提交中...' : '提交修改意见' }}
              </button>
              <span v-if="detail.content.pendingNote" style="font-size:12px;color:var(--ink-3)">
                已有待回炉的意见：{{ detail.content.pendingNote }}
              </span>
            </div>
          </div>
        </template>

        <!-- ── 老数据(v1)──────────────────────────────────── -->
        <template v-else>
        <!-- 外壳:老数据只做最简显示,原页面这一支的完整排版是同事写的,没有收 -->
        <div v-if="detail.content.overview" class="monthly-overview">{{ detail.content.overview }}</div>
        <table v-if="detail.content.quickList?.length" class="overview-table">
          <tbody>
            <tr v-for="(q, i) in detail.content.quickList" :key="i">
              <td class="col-cat">{{ q.category }}</td>
              <td>{{ q.policyTitle }}</td>
            </tr>
          </tbody>
        </table>
        <div v-for="block in (detail.content.policyBlocks ?? [])" :key="block.no" class="policy-block">
          <div class="policy-block-num">{{ block.no }}</div>
          <h3>{{ block.title }}</h3>
          <div v-if="block.info" class="policy-content-text">{{ block.info }}</div>
          <ul v-if="block.contentList?.length" class="policy-content-list">
            <li v-for="(item, idx) in block.contentList" :key="idx">{{ item }}</li>
          </ul>
          <div v-else-if="block.content" class="policy-content-text">{{ block.content }}</div>
          <div v-if="block.focus" class="policy-content-text">{{ block.focus }}</div>
        </div>
        <!-- 外壳到此;下一行老数据分支的收口是我写的 -->
        </template>
      </div>
    </div>
  </template>
</template>
