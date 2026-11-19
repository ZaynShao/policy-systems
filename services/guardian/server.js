'use strict';

/*
 * 这个文件原来是同事建的(guardian 前端服务,一万七千多行:静态页、改写 HTML、各业务接口的转发……),
 * 本仓只收我写的部分,其余是独立版的最小外壳。
 *
 * 我写的(原项目 PR 1525,原样,10 行里的 9 行):
 *   1. proxyToBackend 里,只在研判内部前缀下透传本地服务自己的请求头(注释 1 行 + 代码 3 行);
 *   2. handleApi 里,把研判的两个前缀转给 guardian-backend(注释 3 行 + 条件 2 行)。
 *      原来这两行条件接在同事的几条路由后面,剩下那 1 行改动只是把同事那行末尾的 ") {" 挪到我这两行之后,不收。
 * 外壳(独立版新写,标了「外壳」):一个只转发研判接口的小网关——收请求、读请求体,转给 guardian-backend
 * (地址从 GUARDIAN_BACKEND_URL 读,默认 http://127.0.0.1:18097),带上平台登录态(Cookie、Authorization);
 * 其余路径一律 404。原平台前面还有一层 nginx(去掉 /guardian 前缀、内部前缀免平台门禁),独立版没有。
 *
 *   GUARDIAN_BACKEND_URL=http://127.0.0.1:18097 PORT=8096 node services/guardian/server.js
 *
 * 传输层的约束见 test_gov_risk_transport.test.js。
 */

const http = require('node:http');

// 外壳
const BACKEND = new URL(process.env.GUARDIAN_BACKEND_URL || 'http://127.0.0.1:18097');
const MAX_BODY_BYTES = 4 * 1024 * 1024; // 本地客户端按约 1MB 一批上传,原平台 nginx 这层也是 4MB

function sendJson(res, status, body) { // 外壳
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(body));
}

function proxyToBackend(url, method, data, res, req) {
  // 外壳:目标地址与要带过去的头;平台登录态原样带上,鉴权在后端
  const fullPath = url;
  const opts = {
    protocol: BACKEND.protocol,
    hostname: BACKEND.hostname,
    port: BACKEND.port,
    path: fullPath,
    method,
    headers: { 'Content-Type': req.headers['content-type'] || 'application/json' },
  };
  for (const name of ['cookie', 'authorization']) {
    if (req.headers[name]) opts.headers[name] = req.headers[name];
  }
  // 工单系统性原因研判的本地服务(内网 Mac,无平台登录态)同理,只在自己的内部前缀下透传自己的头
  if (fullPath.startsWith('/api/internal/gov-risk/') && req.headers['x-gov-risk-agent-token']) {
    opts.headers['x-gov-risk-agent-token'] = req.headers['x-gov-risk-agent-token'];
  }
  // 外壳:转发并把后端的状态码和内容原样交回
  const upstream = http.request(opts, (answer) => {
    res.writeHead(answer.statusCode || 502, { 'Content-Type': answer.headers['content-type'] || 'application/json' });
    answer.pipe(res);
  });
  upstream.on('error', () => sendJson(res, 502, { reason: 'backend_unreachable', message: '研判后端连不上' }));
  if (data && data.length) upstream.write(data);
  upstream.end();
}

// 代理到 guardian-backend
async function handleApi(url, method, data, res, req) {
    // 外壳:同事原件里这个条件先列着别的几条后端路由(独立版没有),用 false 占位;下面两行条件是我加的,原样。
    //
    // /api/gov-risk/*(所有者本人,平台登录)与 /api/internal/gov-risk/*(本地服务,agent token)
    // 是个人工作台「工单系统性原因研判」的后端,同样由 guardian-backend 鉴权。
    if (false
        || url.startsWith('/api/gov-risk/')
        || url.startsWith('/api/internal/gov-risk/')) {
        proxyToBackend(url, method, data, res, req);
        return;
    }
    sendJson(res, 404, { reason: 'not_found', message: '独立版的网关只转发工单研判接口' }); // 外壳
}

// 外壳:收请求、读请求体(超过上限 413),交给 handleApi
function createServer() {
  return http.createServer((req, res) => {
    const chunks = [];
    let size = 0;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        sendJson(res, 413, { reason: 'payload_too_large', message: '请求体超过 4MB' });
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => {
      if (res.headersSent) return;
      handleApi(req.url || '/', req.method || 'GET', Buffer.concat(chunks), res, req)
        .catch(() => sendJson(res, 500, { reason: 'gateway_error', message: '网关出错' }));
    });
  });
}

if (require.main === module) {
  const port = Number(process.env.PORT || 8096);
  createServer().listen(port, () => console.log(`工单研判网关已启动:http://localhost:${port}/api/gov-risk/ → ${BACKEND.origin}`));
}

module.exports = { createServer };
