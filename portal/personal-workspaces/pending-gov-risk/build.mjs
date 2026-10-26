#!/usr/bin/env node
// 构建"我的工作台":src/ 下的 Vue 源码 → 本目录的 assets/(index.js、index.css 和按页拆分的块)。
// 入口页 index.html 是手写的固定文件,只引 ./assets/index.js 和 ./assets/index.css,不由构建生成——
// 个人工作台登记会校验目录里的每个 .html,这里只保留这一个真正的页面。
//
//   node portal/personal-workspaces/pending-gov-risk/build.mjs           构建并替换已提交的产物
//   node portal/personal-workspaces/pending-gov-risk/build.mjs --check   只构建到临时目录,与已提交产物逐字比对
//   node portal/personal-workspaces/pending-gov-risk/build.mjs --typecheck   先跑 vue-tsc 再构建
//
// 依赖直接用公共事务前端(services/heng-guan/frontend)已锁定的那一套:副本本来就是从那里复制的,
// 版本跟着走,也不在个人目录里再放一份 package.json / lockfile。先在那里执行一次 `npm ci`。
//
// 个人目录由 nginx 直接静态托管,并且整目录 Cache-Control: no-store,所以产物文件名不带 hash,
// 每次构建文件名稳定、diff 可读。
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const srcDir = path.join(here, 'src');
const repoRoot = path.resolve(here, '../../..');
const hengDir = path.join(repoRoot, 'services/heng-guan/frontend');
const args = new Set(process.argv.slice(2));
const OUTPUTS = ['assets'];

if (!fs.existsSync(path.join(hengDir, 'node_modules/vite'))) {
  console.error(`缺少构建依赖:先执行 npm ci --prefix ${path.relative(process.cwd(), hengDir) || hengDir}`);
  process.exit(2);
}
const hengRequire = createRequire(path.join(hengDir, 'package.json'));
// 有 ESM 入口(package.json exports 的 import 条件)就用 ESM,避免 Vite 的 CJS 入口
function entry(name) {
  if (name.startsWith('/')) return name;
  const pkgDir = path.join(hengDir, 'node_modules', name);
  const exp = JSON.parse(fs.readFileSync(path.join(pkgDir, 'package.json'), 'utf8')).exports?.['.'];
  const esm = typeof exp?.import === 'string' ? exp.import : exp?.import?.default;
  return esm ? path.join(pkgDir, esm) : hengRequire.resolve(name);
}
const importFromHeng = async (name) => import(pathToFileURL(entry(name)).href);
const load = async (name) => (await importFromHeng(name)).default;

if (args.has('--typecheck')) {
  const tsc = spawnSync(process.execPath, [hengRequire.resolve('vue-tsc/bin/vue-tsc.js'), '--noEmit', '-p', path.join(here, 'tsconfig.json')],
    { stdio: 'inherit' });
  if (tsc.status !== 0) process.exit(tsc.status ?? 1);
}

const { build } = await importFromHeng('vite');
const vue = await load('@vitejs/plugin-vue');
const tailwindcss = await load('tailwindcss');
const autoprefixer = await load('autoprefixer');
const hengTailwind = await load(path.join(hengDir, 'tailwind.config.js'));

// src/ 不在公共事务目录下,裸包名(vue、echarts/core…)按"从公共事务源码里 import"来解析。
// plugin-vue 会把 vue 加进 resolve.dedupe,dedupe 的包 Vite 固定从 root(src/)找,这里清掉:
// 所有包都从同一个 node_modules 出,本来就只有一份。
const resolveFromHeng = {
  name: 'resolve-from-heng-frontend',
  enforce: 'pre',
  configResolved(config) { config.resolve.dedupe.length = 0; },
  async resolveId(source, importer, options) {
    if (!importer || source.startsWith('\0') || source.startsWith('.') || source.startsWith('/') || source.startsWith('@/')) return null;
    if (importer.startsWith(hengDir)) return null;
    return this.resolve(source, path.join(hengDir, 'src/main.ts'), { ...options, skipSelf: true });
  },
};

const outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'personal-portal-build-'));
try {
  await build({
    configFile: false,
    root: srcDir,
    base: './',
    logLevel: 'warn',
    plugins: [resolveFromHeng, vue()],
    resolve: { alias: { '@': srcDir } },
    css: {
      postcss: {
        plugins: [
          tailwindcss({ ...hengTailwind, content: [path.join(srcDir, '**/*.{vue,ts,js,html}')] }),
          autoprefixer(),
        ],
      },
    },
    build: {
      outDir,
      emptyOutDir: true,
      reportCompressedSize: false,
      chunkSizeWarningLimit: 1500,
      rollupOptions: {
        input: { index: path.join(srcDir, 'main.ts') },
        output: {
          entryFileNames: 'assets/[name].js',
          chunkFileNames: 'assets/[name].js',
          assetFileNames: 'assets/[name][extname]',
        },
      },
    },
  });

  if (args.has('--check')) {
    const diff = compare(outDir, here);
    if (diff.length) {
      console.error('已提交的构建产物与源码不一致,请重新执行 build.mjs 并一起提交:\n  ' + diff.join('\n  '));
      process.exit(1);
    }
    console.log('构建产物与源码一致');
  } else {
    for (const name of OUTPUTS) fs.rmSync(path.join(here, name), { recursive: true, force: true });
    fs.cpSync(path.join(outDir, 'assets'), path.join(here, 'assets'), { recursive: true });
    const files = fs.readdirSync(path.join(here, 'assets'));
    console.log(`已写入 assets/(${files.length} 个文件)`);
  }
} finally {
  fs.rmSync(outDir, { recursive: true, force: true });
}

function listFiles(root) {
  const out = [];
  for (const name of OUTPUTS) {
    const full = path.join(root, name);
    if (!fs.existsSync(full)) continue;
    if (fs.statSync(full).isFile()) { out.push(name); continue; }
    for (const entry of fs.readdirSync(full, { recursive: true })) {
      if (fs.statSync(path.join(full, entry)).isFile()) out.push(path.join(name, entry));
    }
  }
  return out.sort();
}

function compare(built, committed) {
  const a = listFiles(built), b = listFiles(committed);
  const diff = [];
  for (const f of new Set([...a, ...b])) {
    if (!a.includes(f)) diff.push('多余: ' + f);
    else if (!b.includes(f)) diff.push('缺少: ' + f);
    else if (!fs.readFileSync(path.join(built, f)).equals(fs.readFileSync(path.join(committed, f)))) diff.push('不同: ' + f);
  }
  return diff;
}
