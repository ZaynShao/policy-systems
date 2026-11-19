// 独立版外壳:原平台的登录鉴权守卫是同事写的(校验平台统一登录、把账号放进 req.user),不在本仓。
// 我的接口只用到"挂上这个守卫、从 req.user 读账号和角色"这一约定。独立版没有登录体系,
// 这里只放行已经带着 req.user 的请求,其余一律拒绝。
import { CanActivate, ExecutionContext, Injectable, UnauthorizedException } from '@nestjs/common';

@Injectable()
export class JwtAuthGuard implements CanActivate {
  canActivate(context: ExecutionContext): boolean {
    const req = context.switchToHttp().getRequest();
    if (!req?.user) throw new UnauthorizedException('未登录');
    return true;
  }
}
