<!-- 独立版演示外壳:顶部说明条 + 我写的政策解读页。说明条里的问题点了会填进输入框并发送。 -->
<script setup lang="ts">
import PolicyInterpretation from '@/views/policy/PolicyInterpretation.vue';

const props = defineProps<{ questions: string[]; recordedAt: string; policies: number }>();

function askInPage(q: string) {
  const box = document.querySelector<HTMLTextAreaElement>('textarea.input');
  const send = document.querySelector<HTMLButtonElement>('.composer .btn-primary');
  if (!box || !send) return;
  box.value = q;
  box.dispatchEvent(new Event('input', { bubbles: true }));
  requestAnimationFrame(() => send.click());
}
</script>

<template>
  <div class="qa-demo-bar">
    <b>演示版</b>
    <span v-if="props.recordedAt">回答是 {{ props.recordedAt }} 在测试站上真实问出来的（当时库里 {{ props.policies }} 件政策，未打开「结合公司业务分析」），这里按原来的节奏重放。</span>
    <span v-else>真实问答还没录入（测试站恢复后补录），现在提问只会收到一条说明。</span>
    <details v-if="props.questions.length">
      <summary>其余 {{ props.questions.length }} 个录过的问题</summary>
      <button v-for="q in props.questions" :key="q" type="button" @click="askInPage(q)">{{ q }}</button>
    </details>
  </div>
  <PolicyInterpretation />
</template>

<style scoped>
.qa-demo-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px; padding: 8px 16px; font-size: 12.5px; line-height: 1.6;
  color: #9a3412; background: #fff7ed; border-bottom: 1px solid #fdba74; }
.qa-demo-bar b { font-weight: 800; }
.qa-demo-bar details { flex-basis: 100%; }
.qa-demo-bar summary { cursor: pointer; }
.qa-demo-bar button { margin: 6px 6px 0 0; padding: 4px 10px; border: 1px solid #fdba74; border-radius: 999px; background: #fff; color: #9a3412;
  font: inherit; font-size: 12px; cursor: pointer; }
</style>
