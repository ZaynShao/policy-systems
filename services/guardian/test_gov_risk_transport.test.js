'use strict';

/**
 * 工单系统性原因研判(个人工作台 pending-gov-risk)的传输层。
 *
 * 本地服务跑在内网 Mac 上,没有平台登录态,经公网正规路径进平台要过三层:
 *   1. nginx:server 级 auth_request 会拦 /guardian/api/internal/gov-risk/*,需要单独的例外;
 *   2. guardian 前端:要把 /api/internal/gov-risk/* 与 /api/gov-risk/* 转给 guardian-backend;
 *   3. 前端代理默认只带 Cookie / Authorization,x-gov-risk-agent-token 必须透传,且只在内部前缀下透传。
 * 把本地服务直接指向后端端口测不出这三处(见倚天 2026-09-02 的教训),所以在这里钉住。
 */

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const serverSrc = fs.readFileSync(path.join(__dirname, 'server.js'), 'utf8');
// 独立版:平台的 nginx 配置是同事维护的公共配置,本仓没有;没有它时第三项跳过(见那一项的 skip 说明)。
const nginxPath = path.join(__dirname, '..', '..', 'nginx', 'default.conf');
const nginxConf = fs.existsSync(nginxPath) ? fs.readFileSync(nginxPath, 'utf8') : null;

function locationBlock(header) {
    const start = nginxConf.indexOf(`    location ${header} {`);
    assert.ok(start >= 0, `缺 location ${header}`);
    return nginxConf.slice(start, nginxConf.indexOf('\n    }', start));
}

test('guardian 前端把研判的两个前缀路由到后端', () => {
    const marker = '代理到 guardian-backend';
    const routeBlock = serverSrc.slice(serverSrc.indexOf(marker), serverSrc.indexOf(marker) + 1600);
    assert.match(routeBlock, /url\.startsWith\('\/api\/gov-risk\/'\)/u);
    assert.match(routeBlock, /url\.startsWith\('\/api\/internal\/gov-risk\/'\)/u);
    assert.match(routeBlock, /proxyToBackend/u);
});

test('前端代理只在内部前缀下透传 agent token 头', () => {
    const proxyFn = serverSrc.slice(
        serverSrc.indexOf('function proxyToBackend'),
        serverSrc.indexOf('function streamProxyToBackend'),
    );
    assert.match(
        proxyFn,
        /fullPath\.startsWith\('\/api\/internal\/gov-risk\/'\) && req\.headers\['x-gov-risk-agent-token'\]/u,
        '头只能在内部前缀下透传,丢了它后端一律 401',
    );
    const start = proxyFn.indexOf("if (fullPath.startsWith('/api/internal/gov-risk/')");
    const guarded = proxyFn.slice(start, proxyFn.indexOf('}', start) + 1);
    const outside = proxyFn.slice(0, start) + proxyFn.slice(start + guarded.length);
    assert.doesNotMatch(outside, /x-gov-risk-agent-token/u, '只有内部前缀那一处透传,别处不得转发这个头');
});

test('nginx 只给内部前缀开例外,页面接口继续走平台门禁', {
    skip: nginxConf === null && '独立版没有平台 nginx(nginx/default.conf 是同事维护的公共配置,不在本仓)',
}, () => {
    const block = locationBlock('^~ /guardian/api/internal/gov-risk/');
    assert.match(block, /auth_request off;/u);
    assert.match(block, /proxy_pass http:\/\/guardian:8096;/u);
    assert.match(block, /rewrite \^\/guardian\/\(\.\*\)\$ \/\$1 break;/u);
    const m = /client_max_body_size\s+(\d+)m;/u.exec(block);
    assert.ok(m && Number(m[1]) >= 4, '本地按约 1MB 一批上传脱敏工单,nginx 这层要留余量');
    assert.equal(nginxConf.indexOf('location ^~ /guardian/api/gov-risk/'), -1, '页面接口不能开例外');
    assert.doesNotMatch(nginxConf, /location \^~ \/guardian\/api\/internal\/ \{/u, '不能给整个 internal 前缀开例外');
});
