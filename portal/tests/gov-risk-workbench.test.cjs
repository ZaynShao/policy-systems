const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

// 工单系统性原因研判(个人工作台 pending-gov-risk)的页面约束:
// 只读写自己的后端接口、不拼 innerHTML、不引外部资源、不落浏览器存储、目录归属可识别。
const dir = path.resolve(__dirname, '..', 'personal-workspaces', 'pending-gov-risk');
const read = (name) => fs.readFileSync(path.join(dir, name), 'utf8');

test('manifest 沿用待绑定工作台的占位约定', () => {
    const manifest = JSON.parse(read('workbench.json'));
    assert.equal(manifest.type, 'personal-workbench');
    assert.equal(manifest.owner_account, 'PENDING_ACCOUNT');
    assert.equal(manifest.entry, 'index.html');
    assert.match(read('index.html'), /data-personal-workbench="pending-gov-risk"/);
});

test('页面只调研判自己的后端,不拼 innerHTML,不落浏览器存储', () => {
    const app = read('app.js');
    const apis = [...app.matchAll(/['"](\/[a-z-]+\/api\/[^'"]*)['"]/g)].map((m) => m[1]);
    assert.deepEqual([...new Set(apis)], ['/guardian/api/gov-risk']);
    assert.doesNotMatch(app, /\.innerHTML\s*=|insertAdjacentHTML|document\.write/);
    assert.doesNotMatch(app, /localStorage|sessionStorage|indexedDB/);
    assert.match(app, /credentials: 'same-origin'/);
});

test('不引外部 CDN,资源都在平台或本目录', () => {
    const html = read('index.html');
    const refs = [...html.matchAll(/(?:src|href)="([^"]+)"/g)].map((m) => m[1]);
    for (const ref of refs) {
        assert.ok(ref.startsWith('/') || ref.startsWith('./'), `外部资源:${ref}`);
    }
    assert.doesNotMatch(read('style.css'), /@import|url\(\s*['"]?https?:/);
});

test('409 冲突时暂停保存并保留编辑,不自动覆盖', () => {
    const app = read('app.js');
    assert.match(app, /err\.status === 409/);
    assert.match(app, /state\.locked = true/);
    assert.match(app, /你的修改还在/);
});

test('研判跑完不冲掉没保存的跟进,离开页面停轮询,下钻只按映射编号读', () => {
    const app = read('app.js');
    assert.match(app, /Object\.keys\(state\.dirty\)\.length/);
    assert.match(app, /addEventListener\('pagehide', function \(\) \{\s*stopPoll\(\)/);
    assert.match(app, /'\/cases\?ids=' \+ encodeURIComponent/);
});
