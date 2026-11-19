// 独立版演示入口(离线单文件页面用,见 ../../../build-offline.mjs):先装接口替身,再挂我写的政策解读页。
import { createApp } from 'vue';
import { createPinia } from 'pinia';
import { readDemoData } from '../shared/demo-data';
import { installQaDemo, type QaDemoData } from './mock';
import App from './App.vue';

const data = readDemoData<QaDemoData>();
installQaDemo(data);
const SUGGESTED = new Set([
  '最近对充电业务影响大的政策有哪些？', '最近电力市场方面有什么新政策？', '解读一下最新的储能相关政策', '上海市今年出台了哪些充电相关的文件？',
]);
const others = data.qa.items.map((r) => r.question).filter((q) => !SUGGESTED.has(q));
createApp(App, { questions: others, recordedAt: data.qa.recorded_at, policies: Number(data.health.policies) || 0 })
  .use(createPinia())
  .mount('#app');
