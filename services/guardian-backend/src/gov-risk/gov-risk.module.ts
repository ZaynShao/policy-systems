import { Module } from '@nestjs/common';
import { GovRiskController, GovRiskInternalController } from './gov-risk.controller';
import { GovRiskService, PrismaGovRiskStore } from './gov-risk.service';

@Module({
  controllers: [GovRiskController, GovRiskInternalController],
  providers: [
    PrismaGovRiskStore,
    // 显式工厂:不依赖 emitDecoratorMetadata 推断构造参数(CI 以 transpile-only 跑 spec)
    { provide: GovRiskService, useFactory: (store: PrismaGovRiskStore) => new GovRiskService(store), inject: [PrismaGovRiskStore] },
  ],
})
export class GovRiskModule {}
