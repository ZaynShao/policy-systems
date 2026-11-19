// 独立版外壳:把 PrismaService 提供给研判模块(原平台由同事的公共模块提供)。
import { Global, Module } from '@nestjs/common';
import { PrismaService } from './prisma.service';

@Global()
@Module({
  providers: [PrismaService],
  exports: [PrismaService],
})
export class PrismaModule {}
