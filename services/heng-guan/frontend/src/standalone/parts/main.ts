// 独立版演示入口(离线单文件页面用,见 build-offline.mjs):先装好接口替身和"语音识别"替身,
// 再挂载演示外壳(App.vue),外壳里放我原来的几个页面和组件。
import { createApp } from 'vue';
import { createPinia } from 'pinia';
import { readDemoData } from '../shared/demo-data';
import { installDemoApi, type DemoData } from './mock';
import { installDemoSpeech } from './speech';
import App from './App.vue';

const data = readDemoData<DemoData>();
const api = installDemoApi(data);
installDemoSpeech();
document.title = '公共事务平台政策功能(演示)';
createApp(App, { data, api }).use(createPinia()).mount('#app');
