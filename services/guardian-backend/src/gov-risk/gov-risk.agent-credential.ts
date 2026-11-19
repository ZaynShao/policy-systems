// 工单研判本地客户端的设备密钥校验(独立版拆出来的单独文件)。
//
// 来历:原项目 PR 1635(2026-10-23)。那时研判后端已被同事从 guardian 迁到公共事务平台,我在同事迁移时建的
// services/heng-guan/backend/src/gov-risk/gov-risk.http.ts 里加了下面两个函数(sameText、isGovRiskAgentCredential,
// 连同 node:crypto 那一行 import,约 21 行),公共事务的登录守卫在研判内部前缀改用它判身份。
// 本仓没有公共事务后端,这里把我写的这几行原样拆出来,放在 guardian 研判模块旁边;guardian 登录守卫的外壳
// 照同样的接法调用它(见 ../common/guards/jwt-auth.guard.ts)。设计说明见 docs/WORKFLOW-gov-risk-device-key-v1.0.md,
// 测试见 test/gov-risk.agent-credential.spec.ts。
import { createHash, timingSafeEqual } from 'node:crypto';

function sameText(a: string, b: string): boolean {
  const left = Buffer.from(a, 'utf8');
  const right = Buffer.from(b, 'utf8');
  return left.length === right.length && timingSafeEqual(left, right);
}

/**
 * Local agent credential for the internal namespace: either the operator-issued shared
 * GOV_RISK_AGENT_TOKEN, or the device key the owner's Mac generated for itself. For the latter
 * the platform registers only its SHA-256 fingerprint (GOV_RISK_AGENT_KEY_SHA256), which is not
 * a secret and may live in reviewed configuration. Weak, missing or malformed values never match.
 */
export function isGovRiskAgentCredential(provided: string, isStrong: (secret: string) => boolean): boolean {
  if (!isStrong(provided)) return false;
  const shared = process.env.GOV_RISK_AGENT_TOKEN || '';
  if (isStrong(shared) && sameText(shared, provided)) return true;
  const fingerprint = (process.env.GOV_RISK_AGENT_KEY_SHA256 || '').trim().toLowerCase();
  return /^[0-9a-f]{64}$/.test(fingerprint)
    && sameText(createHash('sha256').update(provided, 'utf8').digest('hex'), fingerprint);
}
