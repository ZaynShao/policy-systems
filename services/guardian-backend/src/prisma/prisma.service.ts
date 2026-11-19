// 独立版外壳:原来的 PrismaService 是同事写的(guardian 后端公共件),本仓没有。
// 这里给研判模块一个最小替身:就是 Prisma 客户端本身(表定义见 prisma/gov-risk.prisma)。
// 启动时不主动连库,第一次读写时 Prisma 自己连(DATABASE_URL);没配数据库也能起来,研判接口读写时才报错。
import { Injectable, OnModuleDestroy } from '@nestjs/common';
import { PrismaClient } from '@prisma/client';

@Injectable()
export class PrismaService extends PrismaClient implements OnModuleDestroy {
  async onModuleDestroy() {
    await this.$disconnect();
  }
}
