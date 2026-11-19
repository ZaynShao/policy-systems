<!-- 独立版外壳:导航里从公共事务复制的政策模块,以及其他没有的路径,都落到这里。
     原平台上这些页面是复制来的同事页面,或者直接跳回公共事务原版(shell/HengFallback.vue);独立版里都没有。 -->
<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import { navLabel } from './nav';

const route = useRoute();
const label = computed(() => navLabel(route.path));
</script>

<template>
  <div class="card pw-missing" role="status">
    <p class="pw-missing-title">{{ label ? `「${label}」不在独立版里` : '这个页面不在独立版里' }}</p>
    <p>原平台上这里是从公共事务复制的政策模块,或直接跳回公共事务原版;独立版只有我自己的「总览」和「政诉预判」。</p>
    <p class="pw-missing-actions">
      <router-link class="btn" to="/overview">回到总览</router-link>
      <router-link class="btn btn-soft" to="/gov-risk">打开政诉预判</router-link>
    </p>
  </div>
</template>

<style scoped>
.pw-missing { max-width: 640px; padding: 36px 28px; text-align: center; color: var(--ink-3); }
.pw-missing-title { margin-bottom: 8px; color: var(--ink); font-size: 16px; font-weight: 700; }
.pw-missing-actions { display: flex; justify-content: center; gap: 10px; margin-top: 18px; }
</style>
