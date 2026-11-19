// 独立版外壳:原来的启动入口是同事写的(guardian 后端,同时还管静态页等),本仓没有。
// 这里只起研判这一个模块:接口都在 /api 下,全局挂登录守卫(common/guards/jwt-auth.guard.ts),
// 请求体放到 4MB(本地客户端按约 1MB 一批上传脱敏工单),端口从 PORT 读,默认 18097。
//
//   DATABASE_URL=… GOV_RISK_OWNER_USERNAME=… JWT_SECRET=… npm start
import 'reflect-metadata';
import { NestFactory } from '@nestjs/core';
import type { NestExpressApplication } from '@nestjs/platform-express';
import { AppModule } from './app.module';
import { JwtAuthGuard } from './common/guards/jwt-auth.guard';

export function configureApp(app: NestExpressApplication): NestExpressApplication {
  app.useBodyParser('json', { limit: '4mb' });
  app.setGlobalPrefix('api');
  app.useGlobalGuards(new JwtAuthGuard());
  return app;
}

async function bootstrap() {
  const app = configureApp(await NestFactory.create<NestExpressApplication>(AppModule));
  const port = Number(process.env.PORT || 18097);
  await app.listen(port);
  console.log(`工单研判后端已启动:http://localhost:${port}/api/gov-risk/`);
}

if (require.main === module) void bootstrap();
