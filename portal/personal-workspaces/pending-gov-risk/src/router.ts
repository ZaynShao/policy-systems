import { createRouter, createWebHashHistory } from 'vue-router';
import { navLabel } from './shell/nav';

// 个人目录由 nginx 直接静态托管(try_files $uri,没有 SPA 回退),所以用 hash 路由。
//
// 独立版:只留我自己的两页(总览、政诉预判)。原来门户里还有从公共事务复制的政策模块(政策大盘、解读、知识库、
// 图谱、月刊、数据源、源质量审核),以及"没复制的公共事务页面跳回原版"(shell/HengFallback.vue),都依赖原平台,
// 不在本仓;左侧导航仍照 shell/nav.ts 列出它们,点进去统一显示"这个页面不在独立版里"。
export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/overview' },
    { path: '/overview', name: 'overview', component: () => import('@/views/home/Overview.vue') },
    { path: '/gov-risk', name: 'gov-risk', component: () => import('@/views/gov-risk/GovRisk.vue') },

    // 独立版外壳:其余路径(含导航里的复制模块)
    { path: '/:pathMatch(.*)*', name: 'not-in-standalone', component: () => import('@/shell/NotInStandalone.vue') },
  ],
});

router.afterEach((to) => {
  const label = navLabel(to.path);
  document.title = (label ? label + ' · ' : '') + '我的工作台';
});
