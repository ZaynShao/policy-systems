// 设备密钥校验的测试(独立版拆出来的单独文件,被测的是 src/gov-risk/gov-risk.agent-credential.ts)。
//
// 来历:原项目 PR 1635 我在同事建的 services/heng-guan/backend/test/gov-risk.http.spec.ts 里加的设备密钥用例
// (+25 −2)。那段用例挂在同事写的公共事务接口测试脚手架上(起整套公共事务应用、假账号服务、请求助手),本仓没有。
// 这里收的是:createHash 的 import、开头清掉 GOV_RISK_AGENT_KEY_SHA256 的一行,和下面 ↓↑ 之间的设备密钥用例
// (同一把设备密钥、同样的指纹登记写法、同样的拒绝清单、与共享口令共存),只改了两处:
//   - 接口路径从公共事务的 /api/v1/… 换成 guardian 的 /api/…(6 行);
//   - 去掉"设备认证不去调账号服务"那一条断言(那是公共事务守卫特有的,guardian 守卫不调账号服务)。
// ↓↑ 之间设共享口令的那一行是原文件的上下文,为了用例连贯一起保留。另外 2 行改在同事脚手架上
// (环境变量快照清单里加了一个变量名、结尾的通过提示多了半句),随脚手架一起不收。
// 外壳(独立版新写):两个只回 {ok:true} 的替身接口挂在 guardian 登录守卫后面,request / reason 两个请求助手;
// 另外直接测一遍 isGovRiskAgentCredential。
import 'reflect-metadata';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { AddressInfo } from 'node:net';
import { Controller, Get, Module } from '@nestjs/common';
import { NestFactory } from '@nestjs/core';
import { JwtAuthGuard } from '../src/common/guards/jwt-auth.guard';
import { isGovRiskAgentCredential } from '../src/gov-risk/gov-risk.agent-credential';

const AGENT_TOKEN = 'a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4';

// 外壳:替身接口,只看守卫放不放行
@Controller('internal/gov-risk')
class InternalStub {
  @Get('package')
  pkg() { return { ok: true }; }
}

@Controller('gov-risk')
class PageStub {
  @Get('package')
  pkg() { return { ok: true }; }
}

@Module({ controllers: [InternalStub, PageStub] })
class StubModule {}

async function main() {
  process.env.NODE_ENV = 'test';
  process.env.JWT_SECRET = 'f'.repeat(16) + '0123456789abcdef';
  delete process.env.GOV_RISK_AGENT_TOKEN;
  delete process.env.GOV_RISK_AGENT_KEY_SHA256;

  // ---- 函数本身 ----
  const strong = (s: string) => s.length >= 32;
  const key = '5d'.repeat(32);
  const fp = createHash('sha256').update(key).digest('hex');
  assert.equal(isGovRiskAgentCredential(key, strong), false, '没登记指纹、没配共享口令:不认');
  process.env.GOV_RISK_AGENT_KEY_SHA256 = fp;
  assert.equal(isGovRiskAgentCredential(key, strong), true, '登记了指纹:认这把设备密钥');
  assert.equal(isGovRiskAgentCredential(fp, strong), false, '指纹本身不能冒充密钥');
  assert.equal(isGovRiskAgentCredential(key, () => false), false, '弱密钥一律不认');
  delete process.env.GOV_RISK_AGENT_KEY_SHA256;
  process.env.GOV_RISK_AGENT_TOKEN = AGENT_TOKEN;
  assert.equal(isGovRiskAgentCredential(AGENT_TOKEN, strong), true, '共享口令照常可用');
  delete process.env.GOV_RISK_AGENT_TOKEN;

  // ---- 经登录守卫走一遍接口(外壳:起应用、请求助手) ----
  const app = await NestFactory.create(StubModule, { logger: false });
  app.setGlobalPrefix('api');
  app.useGlobalGuards(new JwtAuthGuard());
  await app.listen(0, '127.0.0.1');
  const base = `http://127.0.0.1:${(app.getHttpServer().address() as AddressInfo).port}`;
  const agentHeaders = { 'x-gov-risk-agent-token': AGENT_TOKEN };
  const request = (path: string, headers: Record<string, string> = {}) => fetch(base + path, { headers });
  const reason = async (response: Response, status: number, expected?: string) => {
    assert.equal(response.status, status);
    if (expected) assert.equal(((await response.json()) as { reason?: string }).reason, expected);
  };

  try {
    // ↓ 原项目 PR 1635 我写的用例(路径换成 guardian 的 /api/…)
    // Device key: the owner's Mac generates it and the platform registers only its SHA-256 fingerprint.
    const DEVICE_KEY = '5d'.repeat(32);
    const deviceHeaders = { 'x-gov-risk-agent-token': DEVICE_KEY };
    const fingerprint = createHash('sha256').update(DEVICE_KEY).digest('hex');
    delete process.env.GOV_RISK_AGENT_TOKEN;
    process.env.GOV_RISK_AGENT_KEY_SHA256 = ` ${fingerprint.toUpperCase()} `;
    assert.equal((await request('/api/internal/gov-risk/package', deviceHeaders)).status, 200, 'registered device key works without a shared token');
    for (const provided of [AGENT_TOKEN, 'a1'.repeat(32), fingerprint]) {
      await reason(await request('/api/internal/gov-risk/package', { 'x-gov-risk-agent-token': provided }), 401, 'gov_risk_agent_unauthorized');
    }
    for (const [registered, provided] of [['', DEVICE_KEY], ['not-a-fingerprint', DEVICE_KEY],
      [createHash('sha256').update('short-device-key').digest('hex'), 'short-device-key']]) {
      process.env.GOV_RISK_AGENT_KEY_SHA256 = registered;
      await reason(await request('/api/internal/gov-risk/package', { 'x-gov-risk-agent-token': provided }), 401, 'gov_risk_agent_unauthorized');
    }
    process.env.GOV_RISK_AGENT_KEY_SHA256 = fingerprint;
    await reason(await request('/api/gov-risk/package', deviceHeaders), 401, 'login_required');
    process.env.GOV_RISK_AGENT_TOKEN = AGENT_TOKEN;
    assert.equal((await request('/api/internal/gov-risk/package', agentHeaders)).status, 200, 'shared token keeps working beside a device fingerprint');
    assert.equal((await request('/api/internal/gov-risk/package', deviceHeaders)).status, 200);
    delete process.env.GOV_RISK_AGENT_KEY_SHA256;
    // ↑
    console.log('gov-risk agent credential tests passed');
  } finally {
    await app.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
