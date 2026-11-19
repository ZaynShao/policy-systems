// 独立版外壳:原来的入口是照公共事务前端的入口改的(同事写的原件,全局样式 tokens.css、tailwind.css 也是同事的),本仓没有。
// 这里只做三件事:装上 pinia(提示条用)和路由,载入最小样式 styles/shell.css,再载入我自己的 styles/portal.css。
import { createApp } from 'vue';
import { createPinia } from 'pinia';
import App from './App.vue';
import { router } from './router';
import './styles/shell.css';
import './styles/portal.css';

const app = createApp(App);
app.use(createPinia());
app.use(router);
void router.isReady().then(() => app.mount('#app'));
