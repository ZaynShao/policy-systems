// 独立版演示入口(离线单文件页面用,见 ../../build-offline.mjs):先装好演示数据、接口替身和顶部提示,再加载门户。
// 正式入口仍是 src/main.ts(由 index.html 引 assets/index.js),接原平台的接口。
import './setup';
import '../main';
