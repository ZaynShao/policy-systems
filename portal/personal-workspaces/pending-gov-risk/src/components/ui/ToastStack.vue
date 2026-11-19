<!-- 独立版外壳:原来的提示条组件是同事写的,本仓没有;这里显示 stores/toast.ts 里的提示。 -->
<script setup lang="ts">
import { useToastStore } from '@/stores/toast';
const toast = useToastStore();
</script>

<template>
  <Teleport to="body">
    <div class="toast-stack" aria-live="polite">
      <div v-for="t in toast.list" :key="t.id" class="toast" :class="t.type" @click="toast.dismiss(t.id)">{{ t.text }}</div>
    </div>
  </Teleport>
</template>
