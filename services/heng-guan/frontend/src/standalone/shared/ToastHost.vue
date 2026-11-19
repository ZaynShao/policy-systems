<!-- 独立版外壳:显示 src/stores/toast.ts 里的提示 -->
<script setup lang="ts">
import { useToastStore } from '@/stores/toast';
const toast = useToastStore();
</script>

<template>
  <div class="toast-host" aria-live="polite">
    <div v-for="t in toast.list" :key="t.id" class="toast" :class="t.type">{{ t.text }}</div>
  </div>
</template>

<style scoped>
.toast-host { position: fixed; top: 16px; right: 16px; z-index: 9999; display: grid; gap: 8px; max-width: min(360px, calc(100vw - 32px)); }
.toast { padding: 10px 14px; border-radius: 8px; font-size: 13px; color: #fff; background: #16a34a; box-shadow: 0 6px 18px rgba(15, 23, 42, .18); }
.toast.error { background: #dc2626; }
.toast.warning { background: #d97706; }
.toast.info { background: #2563eb; }
</style>
