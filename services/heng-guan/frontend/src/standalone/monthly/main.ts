// 独立版补的:月刊产线的离线演示入口(build-offline.mjs 打成单文件页面)。
// 先给接口装上替身(./mock.ts),再挂载我原来的月刊列表页和详情页(src/views/monthly/)。
// 数据是 data/ 下几期真实月刊的新版格式(来历见 data/README.md)。
import { createApp } from 'vue';
import { createPinia } from 'pinia';
import { createRouter, createWebHashHistory } from 'vue-router';
import type { MonthlyDetail } from '@/api/monthly';
import { readDemoData } from '@/standalone/shared/demo-data';
import MonthlyList from '@/views/monthly/MonthlyList.vue';
import MonthlyDetailPage from '@/views/monthly/MonthlyDetail.vue';
import App from './App.vue';
import { installMonthlyDemo } from './mock';

const issues = Object.values(readDemoData<Record<string, MonthlyDetail>>())
  .sort((a, b) => ((b.year ?? 0) * 100 + (b.month ?? 0)) - ((a.year ?? 0) * 100 + (a.month ?? 0)));
installMonthlyDemo(issues);

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/monthlies', component: MonthlyList },
    { path: '/monthlies/:id', component: MonthlyDetailPage },
    // 原平台上详情标题能跳到政策原文(/policy?openId=…),独立版没有那一页,一律回到列表
    { path: '/:rest(.*)*', redirect: '/monthlies' },
  ],
  scrollBehavior: () => ({ top: 0 }),
});

createApp(App, { issues: issues.map((m) => ({ id: m.id, label: `${m.year}年${m.month}月` })) })
  .use(createPinia())
  .use(router)
  .mount('#app');
