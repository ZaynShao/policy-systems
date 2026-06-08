import assert from 'assert/strict';
import { ForbiddenException } from '@nestjs/common';
import { NotificationController } from '../src/notification/notification.controller';

async function testListRejectsNonManager() {
  const service: any = {
    list: async () => {
      throw new Error('service should not be called');
    },
  };
  const controller = new NotificationController(service);

  assert.throws(
    () => controller.list({ user: { role: 'OPERATOR' } }, 'true', '10'),
    ForbiddenException,
  );
}

async function testListCallsServiceForManager() {
  let call: any;
  const service: any = {
    list: async (role: string, userId: string | undefined, q: any) => {
      call = { role, userId, q };
      return { items: [], unreadCount: 0 };
    },
  };
  const controller = new NotificationController(service);

  const result = await controller.list({ user: { role: 'MANAGER', id: 'gloriahao' } }, 'true', '10');

  assert.deepEqual(result, { items: [], unreadCount: 0 });
  assert.deepEqual(call, { role: 'MANAGER', userId: 'gloriahao', q: { unreadOnly: true, limit: 10 } });
}

async function testReadRejectsNonManager() {
  const service: any = {
    markRead: async () => {
      throw new Error('service should not be called');
    },
  };
  const controller = new NotificationController(service);

  assert.throws(
    () => controller.read({ user: { role: 'FIELD_GA' } }, 'A'),
    ForbiddenException,
  );
}

async function testReadCallsServiceForManager() {
  let idSeen = '';
  const service: any = {
    markRead: async (id: string) => {
      idSeen = id;
      return { id, readAt: new Date() };
    },
  };
  const controller = new NotificationController(service);

  const result = await controller.read({ user: { role: 'MANAGER' } }, 'A');

  assert.equal(idSeen, 'A');
  assert.equal(result.id, 'A');
}

async function main() {
  await testListRejectsNonManager();
  await testListCallsServiceForManager();
  await testReadRejectsNonManager();
  await testReadCallsServiceForManager();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
