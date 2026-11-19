<!-- 独立版外壳:原来的侧栏是照公共事务侧栏改的(同事写的原件,配合平台的 platform-sidebar.js),本仓没有。
     这里按我写的 shell/nav.ts 画左侧导航:分组标题 + 副标题 + 条目;独立版里没有的页面(从公共事务复制的政策模块)
     照样列出,但标成"原平台",点进去会说明这个页面不在独立版里。 -->
<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router';
import { NAV_GROUPS, type NavItem } from './nav';

const route = useRoute();
const router = useRouter();

function isOn(item: NavItem) {
  return item.match.some((p) => route.path === p || route.path.startsWith(p + '/'));
}
function inStandalone(item: NavItem) {
  return router.resolve(item.to).name !== 'not-in-standalone';
}
</script>

<template>
  <aside class="pw-side" aria-label="我的工作台导航">
    <div class="pw-side-brand">
      <span class="pw-side-mark" aria-hidden="true">工</span>
      <span><strong>我的工作台</strong><small>政诉预判与政策工作</small></span>
    </div>
    <nav>
      <section v-for="g in NAV_GROUPS" :key="g.title" class="pw-side-group">
        <h2><span>{{ g.title }}</span><small>{{ g.note }}</small></h2>
        <ul>
          <li v-for="item in g.items" :key="item.to">
            <a
              :href="'#' + item.to"
              :class="{ active: isOn(item), off: !inStandalone(item) }"
              :aria-current="isOn(item) ? 'page' : undefined"
              :title="inStandalone(item) ? undefined : '从公共事务复制的个人版本,不在独立版里'"
              @click.prevent="router.push(item.to)"
            >
              <span class="pf-i" :class="'pf-i-' + item.icon" aria-hidden="true"></span>
              <span class="pw-side-text">{{ item.label }}</span>
              <small v-if="!inStandalone(item)" class="pw-side-tag">原平台</small>
            </a>
          </li>
        </ul>
      </section>
    </nav>
  </aside>
</template>

<style scoped>
.pw-side {
  position: sticky; top: 0; flex: 0 0 216px; align-self: flex-start;
  height: 100vh; overflow-y: auto; padding: 18px 12px 24px;
  border-right: 1px solid var(--line); background: var(--white);
}
.pw-side-brand { display: flex; align-items: center; gap: 10px; margin: 0 6px 18px; }
.pw-side-mark {
  display: inline-grid; place-items: center; width: 34px; height: 34px; border-radius: 10px;
  background: var(--orange); color: #fff; font-weight: 800; font-size: 15px;
}
.pw-side-brand strong { display: block; color: var(--ink); font-size: 14.5px; }
.pw-side-brand small { display: block; color: var(--ink-4); font-size: 11.5px; }
.pw-side-group { margin-bottom: 14px; }
.pw-side-group h2 { display: flex; align-items: baseline; gap: 6px; margin: 0 8px 6px; color: var(--ink-2); font-size: 12.5px; font-weight: 700; }
.pw-side-group h2 small { color: var(--ink-4); font-size: 11px; font-weight: 500; }
.pw-side-group ul { list-style: none; margin-left: 12px; padding-left: 8px; border-left: 1px solid var(--line); }
.pw-side-group a {
  display: flex; align-items: center; gap: 8px; height: 34px; padding: 0 10px; border-radius: 8px;
  color: var(--ink-2); font-size: 13px; font-weight: 560; text-decoration: none;
}
.pw-side-group a:hover { background: var(--bg-2); }
.pw-side-group a.active { background: var(--orange-soft); color: var(--orange-2); font-weight: 700; }
.pw-side-group a.off { color: var(--ink-4); }
.pw-side-group a:focus-visible { outline: 2px solid var(--orange); outline-offset: 1px; }
.pw-side-group .pf-i { font-size: 16px; opacity: .8; }
.pw-side-text { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pw-side-tag { flex: 0 0 auto; padding: 0 6px; border-radius: 999px; background: var(--bg-2); color: var(--ink-4); font-size: 10.5px; line-height: 18px; }
</style>
