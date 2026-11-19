// 独立版外壳:原平台的 PrismaModule 是同事写的,这里只是让我的模块能照原样 import。
import { Global, Module } from '@nestjs/common';
import { PrismaService } from './prisma.service';

@Global()
@Module({
  providers: [PrismaService],
  exports: [PrismaService],
})
export class PrismaModule {}
