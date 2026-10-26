<script setup lang="ts">
// 门户外壳:平台顶栏由 /platform-nav.js 补上;左侧是自己的导航,右侧是子模块。
// 布局沿用公共事务 App.vue 的 .app / .sidebar / .main,复制进来的页面按原样落位。
import { onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import Sidebar from './shell/Sidebar.vue';
import ToastStack from './components/ui/ToastStack.vue';
import { NAV_GROUPS } from './shell/nav';

const route = useRoute();
const router = useRouter();
const narrow = window.matchMedia('(max-width: 768px)');
const isMobile = ref(narrow.matches);
function sync() { isMobile.value = narrow.matches; }
onMounted(() => narrow.addEventListener('change', sync));
onBeforeUnmount(() => narrow.removeEventListener('change', sync));

const flatNav = NAV_GROUPS.flatMap(g => g.items);
function isOn(match: string[]) { return match.some(p => route.path === p || route.path.startsWith(p + '/')); }
</script>

<template>
  <div class="app pw-app" :class="{ 'app-mobile': isMobile }">
    <Sidebar v-if="!isMobile" />
    <main class="main" :class="{ 'main-mobile': isMobile }">
      <nav v-if="isMobile" class="pw-mobile-nav" aria-label="我的工作台导航">
        <button
          v-for="item in flatNav"
          :key="item.to"
          type="button"
          :class="{ active: isOn(item.match) }"
          :aria-current="isOn(item.match) ? 'page' : undefined"
          @click="router.push(item.to)"
        ><span class="pf-i" :class="'pf-i-' + item.icon" aria-hidden="true"></span>{{ item.label }}</button>
      </nav>
      <router-view />
    </main>
  </div>
  <ToastStack />
</template>

<style scoped>
.pw-mobile-nav {
  display: flex;
  gap: 6px;
  margin: -2px -14px 14px;
  padding: 0 14px 10px;
  overflow-x: auto;
  border-bottom: 1px solid var(--line);
  scrollbar-width: none;
}
.pw-mobile-nav::-webkit-scrollbar { display: none; }
.pw-mobile-nav button {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 5px;
  height: 32px;
  padding: 0 11px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--white);
  color: var(--ink-2);
  font-size: 12.5px;
  font-weight: 560;
  white-space: nowrap;
  cursor: pointer;
}
.pw-mobile-nav button .pf-i { font-size: 15px; opacity: 0.7; }
.pw-mobile-nav button.active {
  border-color: var(--orange-border);
  background: var(--orange-soft);
  color: var(--orange-2);
  font-weight: 700;
}
.pw-mobile-nav button:focus-visible { outline: 2px solid var(--orange); outline-offset: 1px; }
</style>
