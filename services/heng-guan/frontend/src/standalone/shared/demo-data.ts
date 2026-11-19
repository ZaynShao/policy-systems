// 离线页面里内置的演示数据:build-offline.mjs 把 src/standalone/<页面>/data/*.json 打进
// <script type="application/json" id="demo-data">,键是文件名(不带 .json)。
export function readDemoData<T = Record<string, unknown>>(): T {
  const el = document.getElementById('demo-data');
  if (!el?.textContent) throw new Error('缺少内置演示数据(#demo-data)');
  return JSON.parse(el.textContent) as T;
}
