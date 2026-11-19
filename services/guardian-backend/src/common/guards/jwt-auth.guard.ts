// 这个文件原来是同事建的(guardian 后端的平台统一登录守卫,还管着倚天、数据外发等别的内部接口),
// 本仓只收我写的部分,其余是独立版的最小外壳。
//
// 我写的(原项目 PR 1525,原样,12 行):internalTokenRules() 里"工单系统性原因研判"那一条规则,和 strongOrEmpty()。
// 外壳(独立版新写,标了「外壳」):
//   - 平台登录:Authorization: Bearer <JWT> 或同域 cookie `token`,HS256,密钥只从环境变量 JWT_SECRET 读,
//     JWT_SECRET 不够强时一律不认登录;成功后 req.user = { id, username, name, role }(研判只用 username);
//   - 内部前缀:请求头与期望值定长比较;研判内部前缀另外认设备密钥——照原项目 PR 1635 我在公共事务登录守卫里
//     的接法,调 ../../gov-risk/gov-risk.agent-credential 里的 isGovRiskAgentCredential;
//   - 强口令判断:至少 32 位,且不像占位值。
import { CanActivate, ExecutionContext, Injectable, UnauthorizedException } from '@nestjs/common';
import * as jwt from 'jsonwebtoken';
import { timingSafeEqual } from 'node:crypto';
import { isGovRiskAgentCredential } from '../../gov-risk/gov-risk.agent-credential';

@Injectable()
export class JwtAuthGuard implements CanActivate {
  // 外壳:登录用的密钥
  private readonly secret = process.env.JWT_SECRET || '';

  // 外壳:内部接口规则表(前缀 → 请求头 → 期望值),独立版只有研判这一条
  private internalTokenRules(): Array<{ prefix: string; headerName: string; expected: string }> {
    return [
      {
        // 工单系统性原因研判:内网 Mac 上的本地服务(无平台登录态)上传结论包、走模型通道。
        // 弱口令或未配置都按"永不匹配"处理,不在构造时抛错——这是个人工作台功能,
        // 配错只该让它自己不可用,不该拖垮整个后端启动。
        prefix: '/api/internal/gov-risk/',
        headerName: 'x-gov-risk-agent-token',
        expected: this.strongOrEmpty(process.env.GOV_RISK_AGENT_TOKEN || ''),
      },
    ];
  }

  private strongOrEmpty(secret: string): string {
    return this.hasStrongSecret(secret) ? secret : '';
  }

  // 外壳:先看内部前缀(只认各自的请求头,不认登录),其余接口一律要平台登录
  canActivate(context: ExecutionContext): boolean {
    const req: any = context.switchToHttp().getRequest();
    const url: string = req.originalUrl || req.url || '';
    for (const rule of this.internalTokenRules()) {
      if (!url.startsWith(rule.prefix)) continue;
      const provided = String(req.headers?.[rule.headerName] || '');
      if (provided && rule.expected && this.sameText(provided, rule.expected)) return true;
      if (rule.headerName === 'x-gov-risk-agent-token'
        && isGovRiskAgentCredential(provided, (secret) => this.hasStrongSecret(secret))) return true;
      throw new UnauthorizedException({ reason: 'gov_risk_agent_unauthorized', message: '内部服务身份校验失败' });
    }

    const token = this.extractToken(req);
    if (token && this.hasStrongSecret(this.secret)) {
      try {
        const payload: any = jwt.verify(token, this.secret, { algorithms: ['HS256'] });
        req.user = { id: payload.sub, username: payload.username || null, name: payload.real_name || null, role: payload.role };
        return true;
      } catch {
        // 签名不对、过期:按未登录处理
      }
    }
    throw new UnauthorizedException({ reason: 'login_required', message: '未登录或登录已过期' });
  }

  // 外壳:强口令 = 至少 32 位,且不含常见占位字样
  private hasStrongSecret(secret: string): boolean {
    if (!secret || secret.length < 32) return false;
    const lower = secret.toLowerCase();
    return !['placeholder', 'change', 'replace', 'example', 'default', 'please', 'dummy', 'sample'].some((w) => lower.includes(w));
  }

  // 外壳
  private sameText(a: string, b: string): boolean {
    const left = Buffer.from(a, 'utf8');
    const right = Buffer.from(b, 'utf8');
    return left.length === right.length && timingSafeEqual(left, right);
  }

  // 外壳
  private extractToken(req: any): string | null {
    const auth: string = req.headers?.authorization || '';
    if (auth.startsWith('Bearer ')) return auth.slice(7).trim() || null;
    const m = /(?:^|;\s*)token=([^;]+)/.exec(req.headers?.cookie || '');
    if (!m) return null;
    try {
      return decodeURIComponent(m[1]);
    } catch {
      return null;
    }
  }
}
