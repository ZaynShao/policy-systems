<script setup lang="ts">
// 复制模块里会跳到没复制的公共事务页面(比如政策大盘点主题跳"政策分析")。
// 这些页面只有公共事务原版,直接带着原路径和参数打开原版,不在门户里留空白页。
// 用 replace:从原版点"后退"回到跳转前的子模块,而不是回到这里再被弹走。
import { computed, onMounted } from 'vue';
import { useRoute } from 'vue-router';

const route = useRoute();
const target = computed(() => '/heng' + (route.fullPath.startsWith('/') ? route.fullPath : '/' + route.fullPath));

onMounted(() => { location.replace(target.value); });
</script>

<template>
  <div class="card pw-fallback" role="status">
    <p>这个页面没有复制到个人工作台,正在打开公共事务原版…</p>
    <a class="btn btn-soft" :href="target">没有自动跳转就点这里</a>
  </div>
</template>

<style scoped>
.pw-fallback { padding: 40px 24px; text-align: center; color: var(--ink-3); }
.pw-fallback p { margin-bottom: 14px; }
</style>
