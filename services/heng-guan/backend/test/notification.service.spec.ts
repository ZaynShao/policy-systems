import assert from 'assert/strict';
import { NotificationService } from '../src/notification/notification.service';

const broadcastVisible = {
  AND: [
    { targetUserId: null },
    { OR: [{ targetRole: null }, { targetRole: 'MANAGER' }] },
  ],
};

const gloriaVisible = {
  OR: [
    { targetUserId: 'gloriahao' },
    broadcastVisible,
  ],
};

async function testListUsesVisibleScopeAndUnreadCount() {
  let findManyArgs: any;
  let countArgs: any;
  const prisma: any = {
    notification: {
      findMany: async (args: any) => {
        findManyArgs = args;
        return [
          { id: 'A', targetRole: null, readAt: null, createdAt: new Date('2026-06-08T02:00:00Z') },
          { id: 'B', targetRole: 'MANAGER', readAt: new Date(), createdAt: new Date('2026-06-08T01:00:00Z') },
        ];
      },
      count: async (args: any) => {
        countArgs = args;
        return 1;
      },
    },
  };
  const service = new NotificationService(prisma);

  const result = await service.list('MANAGER', 'gloriahao', { limit: 50 });

  assert.deepEqual(result.items.map((i: any) => i.id).sort(), ['A', 'B']);
  assert.equal(result.unreadCount, 1);
  assert.deepEqual(findManyArgs.where, gloriaVisible);
  assert.deepEqual(findManyArgs.orderBy, { createdAt: 'desc' });
  assert.equal(findManyArgs.take, 50);
  assert.deepEqual(countArgs.where, {
    AND: [gloriaVisible, { readAt: null }],
  });
}

async function testListUnreadOnlyAddsReadAtFilter() {
  let findManyArgs: any;
  const prisma: any = {
    notification: {
      findMany: async (args: any) => {
        findManyArgs = args;
        return [];
      },
      count: async () => 0,
    },
  };
  const service = new NotificationService(prisma);

  await service.list('MANAGER', 'gloriahao', { unreadOnly: true, limit: 10 });

  assert.deepEqual(findManyArgs.where, {
    AND: [gloriaVisible, { readAt: null }],
  });
  assert.equal(findManyArgs.take, 10);
}

async function testListIncludesTargetUserBranchWhenUserIdPresent() {
  let findManyArgs: any;
  const prisma: any = {
    notification: {
      findMany: async (args: any) => {
        findManyArgs = args;
        return [];
      },
      count: async () => 0,
    },
  };
  const service = new NotificationService(prisma);

  await service.list('MANAGER', 'gloriahao', { limit: 50 });

  assert.deepEqual(findManyArgs.where, gloriaVisible);
}

async function testListUsesBroadcastOnlyWhenUserIdMissing() {
  let findManyArgs: any;
  const prisma: any = {
    notification: {
      findMany: async (args: any) => {
        findManyArgs = args;
        return [];
      },
      count: async () => 0,
    },
  };
  const service = new NotificationService(prisma);

  await service.list('MANAGER', undefined, { limit: 50 });

  assert.deepEqual(findManyArgs.where, broadcastVisible);
  assert.equal(JSON.stringify(findManyArgs.where).includes('undefined'), false);
}

async function testMarkReadSetsReadAt() {
  let updateArgs: any;
  const prisma: any = {
    notification: {
      update: async (args: any) => {
        updateArgs = args;
        return { id: args.where.id, readAt: args.data.readAt };
      },
    },
  };
  const service = new NotificationService(prisma);

  const result = await service.markRead('A');

  assert.deepEqual(updateArgs.where, { id: 'A' });
  assert.ok(updateArgs.data.readAt instanceof Date);
  assert.ok(result.readAt instanceof Date);
}

async function main() {
  await testListUsesVisibleScopeAndUnreadCount();
  await testListUnreadOnlyAddsReadAtFilter();
  await testListIncludesTargetUserBranchWhenUserIdPresent();
  await testListUsesBroadcastOnlyWhenUserIdMissing();
  await testMarkReadSetsReadAt();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
