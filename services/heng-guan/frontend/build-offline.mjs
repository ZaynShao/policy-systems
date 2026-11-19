#!/usr/bin/env node
// 独立版:把某个演示入口打成一个 HTML 文件,双击就能打开,不用联网、不用起服务。
//
//   node build-offline.mjs <页面> [输出文件]
//
// <页面> 是 src/standalone/ 下的目录名,里面要有:
//   main.ts     演示入口(先装好接口替身,再挂载我原来的页面)
//   page.json   { "title": "页面标题", "boot": "载入时的提示" }
//   data/*.json 演示数据(可选),打进页面后用 readDemoData() 读,键是文件名
//   theme.css   这个页面要的样式变量与基础样式(可选)
// 默认输出 dist/<页面>.html(dist/ 不进仓库)。先在本目录执行一次 `npm ci`。
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import vue from '@vitejs/plugin-vue';

const here = path.dirname(fileURLToPath(import.meta.url));
const srcDir = path.join(here, 'src');
const name = process.argv[2];
if (!name || !/^[\w-]+$/.test(name)) {
  console.error('用法: node build-offline.mjs <页面> [输出文件];<页面> 是 src/standalone/ 下的目录名');
  process.exit(2);
}
const pageDir = path.join(srcDir, 'standalone', name);
if (!fs.existsSync(path.join(pageDir, 'main.ts'))) throw new Error(`找不到 src/standalone/${name}/main.ts`);
const page = JSON.parse(fs.readFileSync(path.join(pageDir, 'page.json'), 'utf8'));
const outFile = path.resolve(process.argv[3] || path.join(here, 'dist', `${name}.html`));

const data = {};
const dataDir = path.join(pageDir, 'data');
if (fs.existsSync(dataDir)) {
  for (const f of fs.readdirSync(dataDir).filter((n) => n.endsWith('.json')).sort()) {
    data[f.slice(0, -5)] = JSON.parse(fs.readFileSync(path.join(dataDir, f), 'utf8'));
  }
}

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), `heng-offline-${name}-`));
try {
  await build({
    configFile: false,
    root: srcDir,
    base: './',
    logLevel: 'warn',
    plugins: [vue()],
    resolve: { alias: { '@': srcDir } },
    define: { 'process.env.NODE_ENV': JSON.stringify('production') },
    build: {
      outDir: tmp,
      emptyOutDir: true,
      reportCompressedSize: false,
      chunkSizeWarningLimit: 8000,
      cssCodeSplit: false,
      assetsInlineLimit: 100_000_000,
      rollupOptions: {
        input: path.join(pageDir, 'main.ts'),
        output: { inlineDynamicImports: true, entryFileNames: 'app.js', assetFileNames: 'app[extname]' },
      },
    },
  });
  const files = fs.readdirSync(tmp);
  if (files.some((f) => f !== 'app.js' && f !== 'app.css')) throw new Error(`单文件页面只能有 app.js、app.css,实际:${files.join('、')}`);
  // 内联进 <script>/<style> 时不能出现结束标签:JS 里改写成 "<\/script",JSON 里把 "<" 写成 <
  const js = fs.readFileSync(path.join(tmp, 'app.js'), 'utf8').replace(/<\/(script)/gi, '<\\/$1');
  const themeFile = path.join(pageDir, 'theme.css');
  const css = [fs.existsSync(themeFile) ? fs.readFileSync(themeFile, 'utf8') : '',
    fs.existsSync(path.join(tmp, 'app.css')) ? fs.readFileSync(path.join(tmp, 'app.css'), 'utf8') : '']
    .join('\n').replace(/<\/(style)/gi, '<\\/$1');
  const json = JSON.stringify(data).replace(/</g, '\\u003c');
  const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const html = `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(page.title)}</title>
<style>
${css}
</style>
</head>
<body>
<div id="app"><p class="boot-status" role="status" aria-live="polite">${esc(page.boot || '正在载入…')}</p></div>
<noscript>这个页面需要启用 JavaScript。</noscript>
<script type="application/json" id="demo-data">${json}</script>
<script type="module">
${js}
</script>
</body>
</html>
`;
  fs.mkdirSync(path.dirname(outFile), { recursive: true });
  fs.writeFileSync(outFile, html);
  console.log(`已写入 ${path.relative(process.cwd(), outFile) || outFile}(${(Buffer.byteLength(html) / 1024 / 1024).toFixed(1)} MB),演示数据 ${Object.keys(data).length} 份`);
} finally {
  fs.rmSync(tmp, { recursive: true, force: true });
}
