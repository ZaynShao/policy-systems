// 独立版补的测试:把"公共事务平台政策功能"的离线演示页(src/standalone/parts/)真的打一遍包,
// 在 jsdom 里打开,按用户会做的顺序点一遍我写的几块——L1 源质量审核、消息铃铛、政策大盘、移动端拜访录入,
// 核对渲染和写操作的结果,并确认整页没有发出任何真正的网络请求、没有脚本报错。
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { JSDOM, VirtualConsole } from 'jsdom';

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

test('公共事务平台政策功能 · 离线演示页', async (t) => {
  const tmp = mkdtempSync(path.join(os.tmpdir(), 'heng-parts-test-'));
  const out = path.join(tmp, 'parts.html');
  try {
    execFileSync(process.execPath, ['build-offline.mjs', 'parts', out], { cwd: frontendRoot, stdio: 'pipe' });
    const html = readFileSync(out, 'utf8');
    const js = html.match(/<script type="module">\n([\s\S]*)\n<\/script>/)[1];
    // jsdom 不执行 module 脚本;打包结果里没有 import/export,按普通脚本执行即可
    const problems = [];
    const vc = new VirtualConsole();
    vc.on('jsdomError', (e) => problems.push(`jsdomError ${e.message}`));
    vc.on('error', (...a) => problems.push(`console.error ${a.join(' ')}`));
    vc.on('warn', (...a) => problems.push(`console.warn ${a.join(' ')}`));
    const dom = new JSDOM(html.replace(/<script type="module">[\s\S]*<\/script>/, ''), {
      url: 'file:///demo/parts.html', runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole: vc,
    });
    const { window } = dom;
    const requests = [];
    window.fetch = (u) => { requests.push(String(u)); return Promise.reject(new Error('离线页面不应联网')); };
    const XHR = window.XMLHttpRequest;
    window.XMLHttpRequest = class extends XHR { open(m, u, ...r) { requests.push(`${m} ${u}`); return super.open(m, u, ...r); } };

    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const $ = (s) => window.document.querySelector(s);
    const $$ = (s) => [...window.document.querySelectorAll(s)];
    const click = (el) => el.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    const text = (s) => ($(s)?.textContent || '').replace(/\s+/g, ' ').trim();
    const until = async (fn, ms = 4000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (fn()) return true; await sleep(25); } return false; };
    const go = (hash) => { window.location.hash = hash; window.dispatchEvent(new window.HashChangeEvent('hashchange')); };
    const choose = (sel, value) => { sel.value = value; sel.dispatchEvent(new window.Event('change', { bubbles: true })); };

    window.eval(js);

    await t.test('L1 源质量审核:列出待判项、裁决、按类型筛选', async () => {
      assert.ok(await until(() => $$('.review-card').length === 49), '应列出 49 条待判项');
      assert.ok(await until(() => $$('.ai-section p').every((p) => p.textContent.includes('不是 AI 生成'))), '"AI 解读"应写明不是 AI 生成');
      const ref = text('.review-card .review-ref');
      click($('.review-card .btn-primary'));
      assert.ok(await until(() => $$('.review-card').length === 48), '裁决后应移出待判');
      assert.ok(!$$('.review-card .review-ref').some((e) => e.textContent.trim() === ref));
      assert.match(text('.toast-host'), /已提交裁决/);
      choose($('.review-filter select'), 'gate');
      assert.ok(await until(() => $$('.review-card').length === 1 && $$('.correction-row input').length === 1), '质量门 1 条,带更正标签框');
      choose($('.review-filter select'), 'fetch_fail');
      assert.ok(await until(() => $$('.json-input').length === 1), '抓取失败项带重抓参数框');
      const ta = $('.json-input');
      ta.value = '{不是 JSON';
      ta.dispatchEvent(new window.Event('input', { bubbles: true }));
      click($('.review-card .btn-primary'));
      await sleep(150);
      assert.equal($$('.review-card').length, 1, '重抓参数写错时不应提交');
    });

    await t.test('消息铃铛:未读数、下拉、标为已读', async () => {
      assert.equal(text('.notification-dot'), '2');
      click($('.notification-btn'));
      assert.ok(await until(() => $$('.notification-item').length === 4));
      assert.equal($$('.notification-item.unread').length, 2);
      click($('.notification-item.unread'));
      assert.ok(await until(() => text('.notification-dot') === '1'));
      click(window.document.body);
      await sleep(30);
      assert.equal($('.notification-dropdown'), null, '点别处应收起');
    });

    await t.test('政策大盘:按省分布、全国单列、省份抽屉与政策详情', async () => {
      go('#dashboard');
      assert.ok(await until(() => $$('.pd-province').length > 0));
      assert.match(text('.national-card'), /全国政策\s*\d+ 条/);
      assert.match(text('.pd-note'), /知识库共 1805 条政策/);
      click($('.pd-province'));
      assert.ok(await until(() => $$('.pd-block').length > 0 && $$('.pd-policy').length > 0));
      click($('.pd-policy'));
      assert.ok(await until(() => !!$('.pd-detail h3')));
      click($('.pd-detail .pd-close'));
      click($('.national-card'));
      assert.ok(await until(() => text('.pd-drawer-head').includes('全国') && $$('.pd-block').length > 0));
    });

    await t.test('移动端拜访录入:样例口述 → 解析填表 → 新建', async () => {
      go('#visit');
      assert.ok(await until(() => !!$('.vd-phone')));
      click($('.vd-phone .btn-primary'));
      assert.ok(await until(() => !!$('.mi-panel')));
      assert.equal($('.mi-record').disabled, false, '演示版应能点「开始说话」');
      click($('.mi-record'));
      assert.ok(await until(() => !!$('.mi-recording')));
      assert.ok(await until(() => $('.mi-transcript').value.includes('白名单要求'), 4000), '样例口述应打完');
      click($('.mi-recording'));
      assert.ok(await until(() => $$('.mi-field input').some((i) => i.value === '四川省能源局')), '解析后应自动填表');
      const values = $$('.mi-field input, .mi-field textarea').map((i) => i.value);
      assert.ok(values.includes('储能新政落地口径沟通') && values.includes('13800000000'));
      click($('.mi-submit'));
      assert.ok(await until(() => $$('.vd-visit').length === 1));
      assert.match(text('.vd-visit'), /演示拜访-001/);
    });

    await t.test('整页不联网、不报错', () => {
      assert.deepEqual(requests, []);
      assert.deepEqual(problems, []);
    });
    window.close();
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});
