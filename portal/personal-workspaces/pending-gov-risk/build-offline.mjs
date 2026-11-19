#!/usr/bin/env node
// 独立版:把门户(总览 + 政诉预判)、演示入口(src/standalone/)和演示数据(demo/data/)打成一个 HTML 文件。
// 双击就能打开,不用联网、不用起服务;接口由演示入口里的替身回答,写操作只在页面内存里生效。
//
//   node portal/personal-workspaces/pending-gov-risk/build-offline.mjs [输出文件]
//
// 默认输出到仓库根目录的 dist/工单研判工作台-独立版.html(dist/ 不进仓库)。不放在本目录下:
// 个人工作台登记会校验目录里的每个 .html,这里只能有 index.html 一个页面(见 portal/tests/gov-risk-workbench.test.cjs)。
// 构建依赖与 build.mjs 一样借公共事务前端底座(services/heng-guan/frontend)的那一套,先在那里执行一次 `npm ci`。
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const srcDir = path.join(here, 'src');
const dataDir = path.join(here, 'demo', 'data');
const repoRoot = path.resolve(here, '../../..');
const hengDir = path.join(repoRoot, 'services/heng-guan/frontend');
const outFile = path.resolve(process.argv[2] || path.join(repoRoot, 'dist', '工单研判工作台-独立版.html'));

if (!fs.existsSync(path.join(hengDir, 'node_modules/vite'))) {
  console.error(`缺少构建依赖:先执行 npm ci --prefix ${path.relative(process.cwd(), hengDir) || hengDir}`);
  process.exit(2);
}
const hengRequire = createRequire(path.join(hengDir, 'package.json'));
function entry(name) {
  const pkgDir = path.join(hengDir, 'node_modules', name);
  const exp = JSON.parse(fs.readFileSync(path.join(pkgDir, 'package.json'), 'utf8')).exports?.['.'];
  const esm = typeof exp?.import === 'string' ? exp.import : exp?.import?.default;
  return esm ? path.join(pkgDir, esm) : hengRequire.resolve(name);
}
const { build } = await import(pathToFileURL(entry('vite')).href);
const vue = (await import(pathToFileURL(entry('@vitejs/plugin-vue')).href)).default;

// 裸包名(vue、axios…)从公共事务前端底座的 node_modules 解析,与 build.mjs 同一做法
const resolveFromHeng = {
  name: 'resolve-from-heng-frontend',
  enforce: 'pre',
  configResolved(config) { config.resolve.dedupe.length = 0; },
  async resolveId(source, importer, options) {
    if (!importer || source.startsWith('\0') || source.startsWith('.') || source.startsWith('/') || source.startsWith('@/')) return null;
    if (importer.startsWith(hengDir)) return null;
    return this.resolve(source, path.join(hengDir, 'package.json'), { ...options, skipSelf: true });
  },
};

// 演示数据(来历见 demo/data/README.md)
const readJson = (name) => JSON.parse(fs.readFileSync(path.join(dataDir, name), 'utf8'));
const result = readJson('result.json');
const cases = readJson('cases.json');
const feedback = readJson('feedback.json');
const p2 = (n) => String(n).padStart(2, '0');
const recorded = new Date(Date.parse(result.generatedAt) + 8 * 3600 * 1000); // 按北京时间写
const recordedAt = `${recorded.getUTCFullYear()}-${p2(recorded.getUTCMonth() + 1)}-${p2(recorded.getUTCDate())}`;
const data = { recorded_at: recordedAt, result, cases, feedback };

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'gov-risk-offline-'));
try {
  await build({
    configFile: false,
    root: srcDir,
    base: './',
    logLevel: 'warn',
    plugins: [resolveFromHeng, vue()],
    resolve: { alias: { '@': srcDir } },
    define: { 'process.env.NODE_ENV': JSON.stringify('production') },
    css: { postcss: { plugins: [] } },
    build: {
      outDir: tmp,
      emptyOutDir: true,
      reportCompressedSize: false,
      chunkSizeWarningLimit: 5000,
      cssCodeSplit: false,
      assetsInlineLimit: 100_000_000,
      rollupOptions: {
        input: path.join(srcDir, 'standalone', 'main.ts'),
        output: { inlineDynamicImports: true, entryFileNames: 'app.js', assetFileNames: 'app[extname]' },
      },
    },
  });
  const files = fs.readdirSync(tmp);
  if (files.some((f) => f !== 'app.js' && f !== 'app.css')) throw new Error(`单文件页面只能有 app.js、app.css,实际:${files.join('、')}`);
  // 内联进 <script>/<style> 时不能出现结束标签:JS 里改写成 "<\/script",JSON 里把 "<" 写成 <
  const js = fs.readFileSync(path.join(tmp, 'app.js'), 'utf8').replace(/<\/(script)/gi, '<\\/$1');
  const css = (fs.existsSync(path.join(tmp, 'app.css')) ? fs.readFileSync(path.join(tmp, 'app.css'), 'utf8') : '')
    .replace(/<\/(style)/gi, '<\\/$1');
  const json = JSON.stringify(data).replace(/</g, '\\u003c');
  const html = `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>工单研判工作台(演示)</title>
<style>
${css}
</style>
</head>
<body data-personal-workbench="pending-gov-risk">
<div id="app"><p class="boot-status" role="status" aria-live="polite">正在载入工单研判工作台演示版…</p></div>
<noscript>这个页面需要启用 JavaScript。演示数据是编的样例,不是真实工单。</noscript>
<script type="application/json" id="gov-risk-demo-data">${json}</script>
<script type="module">
${js}
</script>
</body>
</html>
`;
  fs.mkdirSync(path.dirname(outFile), { recursive: true });
  fs.writeFileSync(outFile, html);
  const pkg = result.package || {};
  console.log(`已写入 ${path.relative(process.cwd(), outFile) || outFile}(${(Buffer.byteLength(html) / 1024 / 1024).toFixed(1)} MB):`
    + `样例工单 ${cases.cases.length} 条,候选 ${(pkg.candidates || []).length} 个,${recordedAt} 录入`);
} finally {
  fs.rmSync(tmp, { recursive: true, force: true });
}
