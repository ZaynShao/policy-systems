// 这个文件原来是同事建的(guardian 后端的启动冒烟测试,还测静态页、表格解析、上传上限等),
// 本仓只收我写的部分,其余是独立版的最小外壳。
// 我写的(原项目 PR 1525,原样,8 行):研判的页面接口要登录、内部接口只认 agent token 的两条检查。
// 外壳(独立版新写):按 src/main.ts 的配置把应用起在随机端口上,不连数据库。
import assert from 'node:assert/strict';
import { AddressInfo } from 'node:net';
import { NestFactory } from '@nestjs/core';
import type { NestExpressApplication } from '@nestjs/platform-express';

process.env.NODE_ENV = 'test';
delete process.env.GOV_RISK_AGENT_TOKEN;
delete process.env.GOV_RISK_AGENT_KEY_SHA256;

async function main() {
  const [{ AppModule }, { configureApp }] = await Promise.all([import('../src/app.module'), import('../src/main')]);
  const app = configureApp(await NestFactory.create<NestExpressApplication>(AppModule, { logger: false }));
  try {
    await app.listen(0, '127.0.0.1');
    const address = app.getHttpServer().address() as AddressInfo;
    const base = `http://127.0.0.1:${address.port}`;

    // 工单系统性原因研判:页面接口要登录;内部接口只认 agent token,不认登录也不认空 token
    const govRiskPage = await fetch(`${base}/api/gov-risk/package`);
    assert.equal(govRiskPage.status, 401, 'gov-risk owner routes must require a JWT');
    const govRiskInternal = await fetch(`${base}/api/internal/gov-risk/cases`, {
      method: 'PUT', headers: { 'content-type': 'application/json' }, body: '{}',
    });
    assert.equal(govRiskInternal.status, 401, 'gov-risk internal routes must require the agent token');

    console.log('nest runtime smoke passed');
  } finally {
    await app.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
