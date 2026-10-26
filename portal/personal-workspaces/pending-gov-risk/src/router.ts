import { createRouter, createWebHashHistory } from 'vue-router';
import { navLabel } from './shell/nav';

// 个人目录由 nginx 直接静态托管(try_files $uri,没有 SPA 回退),所以用 hash 路由。
// 复制模块的路径与公共事务原版一致,原代码里的 router.push 原样可用。
export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/overview' },
    { path: '/overview', name: 'overview', component: () => import('@/views/home/Overview.vue') },
    { path: '/gov-risk', name: 'gov-risk', component: () => import('@/views/gov-risk/GovRisk.vue') },

    // ↓ 从公共事务复制的模块(services/heng-guan/frontend/src/router/index.ts 同名路由)
    { path: '/dashboard/policy', name: 'policy-dashboard', component: () => import('@/views/dashboard/PolicyDashboard.vue') },
    { path: '/policy/interpretation', name: 'policy-interpretation', component: () => import('@/views/policy/PolicyInterpretation.vue') },
    { path: '/policy/knowledge', name: 'policy-knowledge', component: () => import('@/views/policy/PolicyKnowledgeBase.vue') },
    { path: '/policy/graph', name: 'policy-graph', component: () => import('@/views/policy/PolicyGraph.vue') },
    { path: '/monthlies', name: 'monthly-list', component: () => import('@/views/monthly/MonthlyList.vue') },
    { path: '/monthlies/:id', name: 'monthly-detail', component: () => import('@/views/monthly/MonthlyDetail.vue') },
    { path: '/policy/import', name: 'policy-import', component: () => import('@/views/policy/ImportSettings.vue') },
    { path: '/quality/l1-review', name: 'l1-review', component: () => import('@/views/quality/L1ReviewQueue.vue') },

    // 没复制的公共事务页面(如政策分析 /policy)跳回原版
    { path: '/:pathMatch(.*)*', name: 'heng-fallback', component: () => import('@/shell/HengFallback.vue') },
  ],
});

router.afterEach((to) => {
  const label = navLabel(to.path);
  document.title = (label ? label + ' · ' : '') + '我的工作台';
});
