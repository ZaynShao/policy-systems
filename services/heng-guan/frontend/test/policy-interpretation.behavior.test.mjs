// 政策解读页的**流式可见性**回归测试。
//
// 为什么值得单独一个测试:服务端 SSE 一直是好的(app 层实测首个 delta 比 done 早
// 2.6 秒),坏的是前端把 reply 建成裸对象再 push 进 ref 数组——Vue 把裸对象原样存
// 进数组、模板读取时才现包 proxy,于是 `reply.content += text` 改的是 raw、绕过
// setter,一次重渲染都不触发。表现是界面一直卡在「正在检索政策库…」,直到 send()
// 末尾 busy.value=false 才把整段答复抖出来。**看起来就像流式没做**,而且这种错
// 静默失败:类型对、事件对、网络对,只有肉眼能发现。所以断言必须落在
// 「流还没结束时,DOM 里已经能看到增量」这一点上。
import assert from 'node:assert/strict';
import { readFile, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { compileScript, parse } from '@vue/compiler-sfc';
import { JSDOM } from 'jsdom';
import ts from 'typescript';

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' });

for (const key of [
  'window',
  'document',
  'navigator',
  'Node',
  'Document',
  'DocumentFragment',
  'Element',
  'HTMLElement',
  'HTMLTextAreaElement',
  'HTMLButtonElement',
  'HTMLInputElement',
  'SVGElement',
  'Text',
  'Event',
  'InputEvent',
  'MouseEvent',
  'KeyboardEvent',
  'CompositionEvent',
]) {
  Object.defineProperty(globalThis, key, {
    configurable: true,
    value: dom.window[key],
    writable: true,
  });
}

const { createApp, h, nextTick } = await import('vue');

/** policy-qa 客户端替身。把 handlers 交给测试,并让"流结束"由测试决定何时发生。 */
const stubSource = `
export const TOOL_LABELS = { search_policies: '检索政策库', get_policy_fulltext: '读取政策原文' };
export function streamQaChat(messages, handlers, signal) {
  return new Promise((resolve) => {
    globalThis.__qaStub = { messages, handlers, signal, finish: resolve };
  });
}
`;
const stubPath = path.join(frontendRoot, `.qa-client-stub-${process.pid}.mjs`);
await writeFile(stubPath, stubSource, 'utf8');
const stubUrl = pathToFileURL(stubPath).href;

async function loadComponent(relativePath) {
  const filename = path.join(frontendRoot, relativePath);
  const source = await readFile(filename, 'utf8');
  const { descriptor, errors } = parse(source, { filename });
  assert.deepEqual(errors, [], `无法编译 ${relativePath}`);
  const compiled = compileScript(descriptor, {
    id: `behavior-${path.basename(relativePath, '.vue')}`,
    inlineTemplate: true,
  });
  let output = ts.transpileModule(compiled.content, {
    fileName: filename,
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  // 裸 node 没有 vite 的 @ 别名,把 policy-qa 客户端换成替身
  const before = output;
  output = output.replace(/(['"])@\/api\/policy-qa\1/g, JSON.stringify(stubUrl));
  assert.notEqual(output, before, '没找到 @/api/policy-qa 的导入,替身没接上');
  const artifact = path.join(
    frontendRoot,
    `.component-behavior-${path.basename(relativePath, '.vue')}-${process.pid}-${Date.now()}.mjs`,
  );
  await writeFile(artifact, output, 'utf8');
  try {
    return (await import(`${pathToFileURL(artifact).href}?v=${Date.now()}`)).default;
  } finally {
    await unlink(artifact);
  }
}

const PolicyInterpretation = await loadComponent('src/views/policy/PolicyInterpretation.vue');

test.after(() => unlink(stubPath).catch(() => {}));

async function flushUi() {
  await nextTick();
  await nextTick();
}

function mount() {
  const host = document.createElement('div');
  document.body.append(host);
  const app = createApp({ setup: () => () => h(PolicyInterpretation) });
  app.mount(host);
  return { app, host };
}

/** 走完"输入 → 点发送"的真实路径,拿到替身捕获的 handlers。 */
async function ask(host, question) {
  delete globalThis.__qaStub;
  const textarea = host.querySelector('textarea.input');
  assert.ok(textarea, '找不到输入框');
  textarea.value = question;
  textarea.dispatchEvent(new Event('input', { bubbles: true }));
  await flushUi();
  const send = host.querySelector('button.btn-primary');
  assert.ok(send && !send.disabled, '发送按钮应当可用');
  send.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  await flushUi();
  const stub = globalThis.__qaStub;
  assert.ok(stub, 'send() 应当调用 streamQaChat');
  return stub;
}

test('答复在流进行中就逐块显示,不是等 done 才整段出现', async () => {
  const { app, host } = mount();
  const stub = await ask(host, '充电基础设施有哪些国家级支持政策');

  // 还没有任何 delta:显示占位,不显示答复区
  assert.equal(host.querySelector('.answer'), null);
  assert.ok(host.querySelector('.thinking'), '首个 delta 之前应显示「正在检索政策库…」');

  stub.handlers.onDelta('国家层面主要有三类支持。');
  await flushUi();
  const first = host.querySelector('.answer');
  assert.ok(first, '收到第一个 delta 就必须渲染答复区——流还没结束');
  assert.match(first.textContent, /国家层面主要有三类支持。/);
  assert.equal(host.querySelector('.thinking'), null, '有正文后不该再显示占位');

  stub.handlers.onDelta('一是中央预算内投资。');
  await flushUi();
  assert.match(
    host.querySelector('.answer').textContent,
    /国家层面主要有三类支持。一是中央预算内投资。/,
    '第二个 delta 必须追加上去,而不是覆盖或丢失',
  );

  // 到这里 streamQaChat 的 promise 仍未 resolve:上面看到的全是"流进行中"的画面
  assert.ok(globalThis.__qaStub, '流应当仍在进行中');
  stub.finish();
  await flushUi();
  app.unmount();
});

test('检索计划与工具进度在流进行中就显示', async () => {
  const { app, host } = mount();
  const stub = await ask(host, '最近电力市场有什么新政策');

  stub.handlers.onPlan({
    kind: 'survey',
    themes: ['power_market'],
    theme_labels: ['电力市场'],
    business_lines: [],
    keywords: ['现货'],
    issuers: [],
    note: '',
  });
  await flushUi();
  assert.match(host.querySelector('.plan')?.textContent ?? '', /电力市场/, '检索计划应实时显示');

  stub.handlers.onTool({ seq: 1, name: 'search_policies', args_preview: '现货市场', status: 'start' });
  await flushUi();
  const tools = host.querySelector('.tools');
  assert.ok(tools, '工具进度应实时显示,而不是等流结束');
  assert.match(tools.textContent, /检索政策库/);
  assert.match(tools.textContent, /现货市场/);

  stub.handlers.onTool({ seq: 1, name: 'search_policies', status: 'done', result_chars: 120 });
  await flushUi();
  assert.ok(host.querySelector('.tool.done'), '工具完成状态应实时反映');

  stub.finish();
  await flushUi();
  app.unmount();
});

test('delta_reset 丢掉规划自语后,后续 delta 仍然逐块显示', async () => {
  const { app, host } = mount();
  const stub = await ask(host, '解读一下最新的储能政策');

  stub.handlers.onDelta('我先做几轮检索。');
  await flushUi();
  assert.match(host.querySelector('.answer').textContent, /我先做几轮检索。/);

  stub.handlers.onDeltaReset();
  await flushUi();
  assert.equal(host.querySelector('.answer'), null, 'reset 后已显示的自语必须消失');

  stub.handlers.onDelta('储能政策要点如下。');
  await flushUi();
  assert.match(
    host.querySelector('.answer').textContent,
    /^储能政策要点如下。$/,
    'reset 之后的正文要干净地重新累加',
  );

  stub.finish();
  await flushUi();
  app.unmount();
});
