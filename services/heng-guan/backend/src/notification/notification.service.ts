import { Injectable } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';

@Injectable()
export class NotificationService {
  constructor(private prisma: PrismaService) {}

  async list(role: string, userId: string | undefined, q: { unreadOnly?: boolean; limit?: number }) {
    // 广播消息：targetUserId 为空，按角色可见
    const broadcast = { AND: [{ targetUserId: null }, { OR: [{ targetRole: null }, { targetRole: role as any }] }] };
    // 个人定向：targetUserId == 当前登录人平台账号。
    // ⚠ userId 为 undefined 时绝不能拼 { targetUserId: undefined }（Prisma 会丢弃该条件→匹配全部，导致定向消息泄漏给所有人）
    const visible = userId
      ? { OR: [{ targetUserId: userId }, broadcast] }
      : broadcast;
    const where = q.unreadOnly ? { AND: [visible, { readAt: null }] } : visible;
    const [items, unreadCount] = await Promise.all([
      this.prisma.notification.findMany({ where, orderBy: { createdAt: 'desc' }, take: q.limit ?? 50 }),
      this.prisma.notification.count({ where: { AND: [visible, { readAt: null }] } }),
    ]);
    return { items, unreadCount };
  }

  markRead(id: string) {
    return this.prisma.notification.update({ where: { id }, data: { readAt: new Date() } });
  }
}
