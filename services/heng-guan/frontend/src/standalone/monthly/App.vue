<!-- 独立版补的:演示页外壳(顶栏说明、在几期之间切换、页面容器)。原平台的门户外壳是同事的,不在本仓。 -->
<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import ToastHost from '@/standalone/shared/ToastHost.vue';

const props = defineProps<{ issues: Array<{ id: string; label: string }> }>();
const route = useRoute();
const current = computed(() => String(route.params.id ?? ''));
const span = computed(() => {
  const labels = props.issues.map((i) => i.label);
  return labels.length ? `${labels[labels.length - 1]}—${labels[0]}` : '';
});
</script>

<template>
  <header class="demo-bar">
    <div class="demo-bar-inner">
      <div class="demo-brand">
        <span class="demo-badge">演示版</span>
        <b>月刊产线</b>
        <span class="demo-sub">新版月刊渲染</span>
      </div>
      <nav class="demo-nav" aria-label="切换月刊">
        <RouterLink to="/monthlies" :class="{ on: !current }">全部</RouterLink>
        <RouterLink v-for="i in issues" :key="i.id" :to="`/monthlies/${i.id}`" :class="{ on: current === i.id }">
          {{ i.label }}
        </RouterLink>
      </nav>
    </div>
    <p class="demo-note">
      内置 {{ issues.length }} 期真实月刊({{ span }},终稿正文转成新版月刊格式);
      提交修改意见只记在本页,刷新即还原。
    </p>
  </header>
  <main class="demo-main">
    <RouterView />
  </main>
  <ToastHost />
</template>
