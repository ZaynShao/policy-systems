// 这个文件原来是同事建的(guardian 后端的根模块,挂着平台的各个业务模块),本仓只收我写的部分,其余是独立版的最小外壳。
// 我写的(原项目 PR 1525,原样,2 行):GovRiskModule 的 import 和在 imports 里的注册。
// 外壳:只挂数据库服务 PrismaModule(原平台由同事的公共模块提供)。
import { Module } from '@nestjs/common';
import { PrismaModule } from './prisma/prisma.module';
import { GovRiskModule } from './gov-risk/gov-risk.module';

@Module({
  imports: [
    PrismaModule,
    GovRiskModule,
  ],
})
export class AppModule {}
