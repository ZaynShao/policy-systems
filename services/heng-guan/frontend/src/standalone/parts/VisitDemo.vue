<!--
  独立版演示外壳:原平台里,我的"新建拜访"弹窗挂在同事做的移动端拜访列表上(那一页不在本仓)。
  这里给一个最小的手机宽度框:一个"+ 新建拜访"按钮、本页新建的拜访列表,再加一段怎么演示的说明。
  弹窗本身(MobileVisitInputModal.vue)是我写的,原样使用。
-->
<script setup lang="ts">
import { onMounted, ref } from 'vue';
import MobileVisitInputModal from '@/views/visit/MobileVisitInputModal.vue';
import type { DemoApi, DemoVisit, VoiceSample } from './mock';
import { demoScript } from './speech';

const props = defineProps<{ api: DemoApi; samples: VoiceSample[] }>();
const open = ref(false);
const visits = ref<DemoVisit[]>([]);
const pick = ref(0);

function usePick(i: number) {
  pick.value = i;
  demoScript.value = props.samples[i]?.transcript ?? '';
}
onMounted(() => usePick(0));

function onCreated() {
  visits.value = props.api.visits();
}
function fmt(s: string) {
  return new Date(s).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}
</script>

<template>
  <div class="page-head">
    <div>
      <div class="page-title">移动端拜访录入</div>
      <div class="page-sub">一线同事在手机上新建拜访:可以手填,也可以先说一段话,由后端解析后自动填表</div>
    </div>
  </div>

  <div class="vd-grid">
    <section class="vd-phone" aria-label="手机宽度的拜访列表">
      <div class="vd-phone-head">
        <b>我的拜访</b>
        <button class="btn btn-primary" type="button" @click="open = true">+ 新建拜访</button>
      </div>
      <p v-if="!visits.length" class="vd-empty">还没有新建的拜访。点右上角「+ 新建拜访」试试。</p>
      <article v-for="v in visits" :key="v.id" class="vd-visit">
        <div class="vd-visit-top"><span class="pill pill-amber">{{ v.code }}</span><span class="tbl-time">计划 {{ fmt(v.plannedAt) }}</span></div>
        <div class="vd-visit-topic">{{ v.topic }}</div>
        <div class="tbl-meta">{{ v.region }}{{ v.orgName ? ' · ' + v.orgName : '' }}{{ v.contactName ? ' · ' + v.contactName : '' }}</div>
      </article>
    </section>

    <section class="card vd-help">
      <b>怎么演示</b>
      <ol>
        <li>点「+ 新建拜访」,打开录入弹窗(就是原来的弹窗)。</li>
        <li>演示版不录音:框里空着时点「开始说话」,会把下面选中的样例口述当作识别结果逐字打出来;等字出完,点「停止并识别」。</li>
        <li>解析要调大模型,演示版回放后端测试里录好的解析结果,表单自动填好。录制时的"今天"按 2026-06-12 算,所以样例一的计划时间是 6 月 13 日上午。</li>
        <li>也可以不用语音,直接手填表单,点「确认创建」;新建的拜访只记在本页,刷新就没了。</li>
      </ol>
      <div class="vd-samples" role="radiogroup" aria-label="演示用的口述">
        <label v-for="(s, i) in samples" :key="i" class="vd-sample" :class="{ on: pick === i }">
          <input type="radio" name="vd-sample" :checked="pick === i" @change="usePick(i)" />
          <span>
            <b>样例{{ i === 0 ? '一' : '二' }}</b>:{{ s.transcript }}
            <small>{{ s.note }}</small>
          </span>
        </label>
      </div>
      <p class="tbl-meta">样例里的机构名、"张处长"和 13800000000 都是后端测试里的示例,不是真实联系人;机构下拉、主拜访人是演示用的。</p>
    </section>
  </div>

  <MobileVisitInputModal :open="open" @close="open = false" @created="onCreated" />
</template>

<style scoped>
.vd-grid { display: grid; grid-template-columns: minmax(0, 390px) minmax(0, 1fr); gap: 16px; align-items: start; }
.vd-phone { background: var(--white); border: 1px solid var(--line); border-radius: 22px; padding: 14px; min-height: 420px; box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08); }
.vd-phone-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; color: var(--ink); }
.vd-empty { color: var(--ink-3); font-size: 13px; text-align: center; padding: 60px 12px; }
.vd-visit { border: 1px solid var(--line); border-radius: 12px; padding: 10px 12px; margin-bottom: 10px; }
.vd-visit-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.vd-visit-topic { margin: 6px 0 2px; font-size: 14px; font-weight: 600; color: var(--ink); }
.vd-help { padding: 16px 18px; font-size: 13px; line-height: 1.7; color: var(--ink-2); }
.vd-help ol { margin: 6px 0 12px; padding-left: 20px; }
.vd-samples { display: grid; gap: 8px; margin-bottom: 10px; }
.vd-sample { display: flex; gap: 8px; align-items: flex-start; border: 1px solid var(--line); border-radius: 10px; padding: 8px 10px; cursor: pointer; }
.vd-sample.on { border-color: var(--orange); background: var(--orange-soft); }
.vd-sample small { display: block; color: var(--ink-3); font-size: 11.5px; }
@media (max-width: 860px) {
  .vd-grid { grid-template-columns: 1fr; }
}
</style>
