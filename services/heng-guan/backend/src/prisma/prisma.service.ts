// 独立版外壳:原平台的 PrismaService 是同事写的(继承按整份表定义生成的 PrismaClient、负责连库),不在本仓。
// 我的模块只通过它读写这几张表:Notification、L1ReviewQueue、KnowledgeTheme、KnowledgeEntry
// (表定义见 prisma/schema.prisma 里我写的部分)。独立版只给出同名的类和这几个表的最小接口,
// 好让我的模块能单独编译、测试;测试里都是传入替身对象,不连数据库。
import { Injectable } from '@nestjs/common';

type Args = Record<string, any>;

/** 一张表在 Prisma 客户端里的读写方法(只列我的模块用到的) */
export interface TableDelegate<Row = any> {
  findMany(args?: Args): Promise<Row[]>;
  findUnique(args: Args): Promise<Row | null>;
  count(args?: Args): Promise<number>;
  update(args: Args): Promise<Row>;
}

/** 原来从 @prisma/client 引的查询条件类型;独立版只留政策大盘用到的一个 */
export namespace Prisma {
  export type KnowledgeEntryWhereInput = Record<string, unknown>;
}

@Injectable()
export class PrismaService {
  notification!: TableDelegate;
  l1ReviewQueue!: TableDelegate;
  knowledgeTheme!: TableDelegate<{ id: string; name: string; count: number }>;
  knowledgeEntry!: TableDelegate<{
    pid: string;
    title: string;
    region: string | null;
    regionLevel: string | null;
    adcode: string | null;
    importance: number;
    date: string | null;
  }>;
}
