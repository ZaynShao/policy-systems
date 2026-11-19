const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

// 我的工作台(个人工作台 pending-gov-risk,所有者 shaoziyuan)的页面约束。
// 门户是手写的 index.html + src/ 下 Vue 源码构建出的 assets/;子模块"政诉预判"(原工单系统性原因研判)
// 仍是原生脚本 gov-risk-app.mjs。约束:只读写平台同源接口、政诉预判不拼 innerHTML、不引外部资源、
// 不落浏览器存储、409 不覆盖、离开模块停轮询、导航与路由对得上、构建产物齐全。
const dir = path.resolve(__dirname, '..', 'personal-workspaces', 'pending-gov-risk');
const read = (name) => fs.readFileSync(path.join(dir, name), 'utf8');
const GOV = 'src/views/gov-risk/gov-risk-app.mjs';

function walk(rel) {
    const out = [];
    for (const entry of fs.readdirSync(path.join(dir, rel), { withFileTypes: true })) {
        const child = path.join(rel, entry.name);
        if (entry.isDirectory()) out.push(...walk(child));
        else out.push(child);
    }
    return out;
}

test('manifest 标明已确认的 shaoziyuan 账号,入口带工作台标识', () => {
    const manifest = JSON.parse(read('workbench.json'));
    assert.equal(manifest.type, 'personal-workbench');
    assert.equal(manifest.owner_account, 'PENDING_ACCOUNT');
    assert.equal(manifest.entry, 'index.html');
    assert.match(read('index.html'), /data-personal-workbench="pending-gov-risk"/);
    // 个人工作台登记会逐个校验目录里的 .html;门户只有这一个入口页,源码里不放 HTML 模板
    assert.deepEqual(walk('.').filter((f) => f.endsWith('.html')), ['index.html']);
});

test('政诉预判只调研判自己的后端,不拼 innerHTML,不落浏览器存储', () => {
    const app = read(GOV);
    const apis = [...app.matchAll(/['"](\/[a-z-]+\/api\/[^'"]*)['"]/g)].map((m) => m[1]);
    assert.deepEqual([...new Set(apis)], ['/guardian/api/gov-risk']);
    assert.doesNotMatch(app, /\.innerHTML\s*=|insertAdjacentHTML|document\.write/);
    assert.doesNotMatch(app, /localStorage|sessionStorage|indexedDB/);
    assert.match(app, /credentials: 'same-origin'/);
});

test('409 冲突时暂停保存并保留编辑,不自动覆盖', () => {
    const app = read(GOV);
    assert.match(app, /err\.status === 409/);
    assert.match(app, /state\.locked = true/);
    assert.match(app, /你的修改还在/);
});

test('研判跑完不冲掉没保存的跟进,下钻只按映射编号读', () => {
    const app = read(GOV);
    assert.match(app, /Object\.keys\(state\.dirty\)\.length/);
    assert.match(app, /'\/cases\?ids=' \+ encodeURIComponent/);
});

test('离开页面或切走模块都停轮询,卸载后迟到的响应不再续轮询', () => {
    const app = read(GOV);
    assert.match(app, /function release\(\) \{\s*stopPoll\(\)/);
    assert.match(app, /addEventListener\('pagehide', release\)/);
    assert.match(app, /function schedulePoll\(\) \{\s*stopPoll\(\);\s*if \(disposed\) return;/);
    assert.match(app, /return function dispose\(\) \{\s*disposed = true;\s*window\.removeEventListener\('pagehide', release\);/);
    const vue = read('src/views/gov-risk/GovRisk.vue');
    assert.match(vue, /onBeforeUnmount\(\(\) => \{ dispose\?\.\(\)/);
});

test('政诉预判的下拉交给平台下拉组件(Vue 根节点里平台脚本不会自动接管)', () => {
    const app = read(GOV);
    assert.match(app, /window\.PlatformSelect/);
    assert.match(app, /\['f-band', 'f-status', 'f-level'\]\.forEach\(function \(id\) \{ platformSelect\(\$\(id\)\); \}\)/);
    assert.match(app, /var selBox = platformSelect\(sel\);/);
});

test('改名:页面与导航都叫政诉预判', () => {
    assert.match(read('src/views/gov-risk/GovRisk.vue'), /<h1>政诉预判<\/h1>/);
    assert.match(read('src/shell/nav.ts'), /label: '政诉预判'/);
    for (const file of walk('src').filter((f) => /\.(vue|ts|html)$/.test(f))) {
        assert.doesNotMatch(read(file), /工单系统性原因研判/, file);
    }
});

// 独立版:从公共事务复制的政策模块不在本仓,路由只留总览、政诉预判;导航照旧列出复制模块,点进去落到兜底页
test('左侧导航的每一项都有去处:我自己的两页有路由,复制模块落到"不在独立版里"', () => {
    const nav = read('src/shell/nav.ts');
    const router = read('src/router.ts');
    const routes = new Set([...router.matchAll(/path: '([^']+)'/g)].map((m) => m[1]));
    const targets = [...nav.matchAll(/to: '([^']+)'/g)].map((m) => m[1]);
    assert.deepEqual(targets, ['/overview', '/gov-risk', '/dashboard/policy', '/policy/interpretation', '/policy/knowledge',
        '/policy/graph', '/monthlies', '/policy/import', '/quality/l1-review']);
    for (const to of targets.slice(0, 2)) assert.ok(routes.has(to), `导航 ${to} 没有路由`);
    for (const to of targets.slice(2)) assert.ok(!routes.has(to), `${to} 是复制模块,独立版里不该有路由`);
    assert.match(router, /path: '\/:pathMatch\(\.\*\)\*'.*NotInStandalone/);
    assert.match(read('src/shell/NotInStandalone.vue'), /不在独立版里/);
});

// 独立版:复制来的 geojson.ts、MonthlyDetail.vue 不在本仓,那两条断言去掉;接口客户端(独立版外壳)前缀不变
test('只走平台同源接口:接口客户端的前缀固定为 /heng', () => {
    assert.match(read('src/api/client.ts'), /export const apiBase = '\/heng\/api\/v1';/);
    for (const file of walk('src').filter((f) => /\.(vue|ts|mjs)$/.test(f))) {
        assert.doesNotMatch(read(file), /fetch\(\s*['"`]https?:/, file);
    }
});

test('不引外部 CDN,资源都在平台或本目录;构建产物齐全', () => {
    const html = read('index.html');
    const refs = [...html.matchAll(/(?:src|href)="([^"]+)"/g)].map((m) => m[1]);
    for (const ref of refs) {
        assert.ok(ref.startsWith('/') || ref.startsWith('./'), `外部资源:${ref}`);
    }
    assert.match(html, /<script type="module" src="\.\/assets\/index\.js"><\/script>/);
    assert.match(html, /<link rel="stylesheet" href="\.\/assets\/index\.css">/);
    const assets = walk('assets');
    assert.ok(assets.includes(path.join('assets', 'index.js')) && assets.includes(path.join('assets', 'index.css')), '缺少入口产物');
    assert.ok(assets.length > 0, '缺少构建产物,先运行 build.mjs');
    for (const file of assets.filter((f) => f.endsWith('.js'))) {
        for (const m of read(file).matchAll(/(?:from|import\()\s*"\.\/([A-Za-z0-9_.-]+\.js)"/g)) {
            assert.ok(fs.existsSync(path.join(dir, 'assets', m[1])), `${file} 引用的 ${m[1]} 不存在`);
        }
    }
    for (const file of [...assets.filter((f) => f.endsWith('.css')), ...walk('src').filter((f) => f.endsWith('.css'))]) {
        assert.doesNotMatch(read(file), /@import\s+(url\()?['"]?https?:|url\(\s*['"]?https?:/, file);
    }
});

test('新写的门户代码不落浏览器存储', () => {
    for (const file of ['src/App.vue', 'src/main.ts', 'src/router.ts', 'src/shell/Sidebar.vue', 'src/shell/nav.ts',
        'src/shell/HengFallback.vue', 'src/views/home/Overview.vue', 'src/views/gov-risk/GovRisk.vue',
        // 独立版补的:兜底页和离线演示入口(写操作只记在页面内存里)
        'src/shell/NotInStandalone.vue', 'src/standalone/main.ts', 'src/standalone/setup.ts', 'src/standalone/mock.ts']) {
        assert.doesNotMatch(read(file), /localStorage|sessionStorage|indexedDB/, file);
    }
});

// 独立版:离线演示页面用的是编的样例工单(用户定的红线),页面上要写明;内置数据不能出现个人信息样式
test('离线演示:页面写明演示数据是编的,内置样例工单不含个人信息样式', () => {
    assert.match(read('src/standalone/setup.ts'), /演示数据是编的样例,不是真实工单/);
    assert.match(read('demo/data/README.md'), /工单是编的/);
    const pii = [
        ['手机号', /(?<!\d)1[3-9]\d{9}(?!\d)|(?<!\d)1[3-9]\d[*xX]{4}\d{4}(?!\d)/],
        ['证件号', /(?<!\d)\d{17}[\dXx](?!\d)/],
        ['车牌', /[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼][A-HJ-NP-Z][\s·]?[A-HJ-NP-Z0-9]{4,5}/],
        ['长编号', /(?<![A-Za-z0-9])\d{8,}(?![A-Za-z0-9])/],
        ['邮箱', /[\w.+-]+@[\w-]+\.[\w.-]+/],
        ['链接', /https?:\/\/\S+|www\.\S+/],
        ['称呼', /[\u4e00-\u9fa5](先生|女士|小姐|师傅)/],
    ];
    const { cases } = JSON.parse(read('demo/data/cases.json'));
    assert.ok(cases.length >= 500, '演示工单数量级要像真的(约 560 条)');
    const result = JSON.parse(read('demo/data/result.json'));
    const texts = cases.flatMap((c) => Object.values(c.text || {}))
        .concat(result.package.reference_cases.flatMap((r) => [r.title, r.summary]));
    for (const t of texts) {
        for (const [kind, rx] of pii) assert.doesNotMatch(t, rx, `演示数据里出现${kind}样式:${t.slice(0, 20)}…`);
    }
    for (const c of cases) {
        assert.match(c.case_id, /^GT-[A-Z2-7]{8}$/);
        assert.ok(c.station_code === null || /^ST-[A-Z2-7]{6}$/.test(c.station_code), c.case_id);
        assert.equal('user_key' in c, false, '下钻工单不带 user_key');
    }
});
