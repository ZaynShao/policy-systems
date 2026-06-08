import assert from 'assert/strict';
import { ForbiddenException } from '@nestjs/common';
import { L1ReviewController } from '../src/l1-review/l1-review.controller';

async function testListRejectsNonManager() {
  const service: any = {
    list: async () => {
      throw new Error('service should not be called');
    },
  };
  const controller = new L1ReviewController(service);

  assert.throws(
    () => controller.list({ user: { role: 'OPERATOR' } }, 'gate', 'true'),
    ForbiddenException,
  );
}

async function testNarrateRejectsNonManager() {
  const service: any = {
    narrate: async () => {
      throw new Error('service should not be called');
    },
  };
  const controller = new L1ReviewController(service);

  assert.throws(
    () => controller.narrate({ user: { role: 'FIELD_GA' } }, 'Q1'),
    ForbiddenException,
  );
}

async function testSubmitVerdictRejectsNonManager() {
  const service: any = {
    submitVerdict: async () => {
      throw new Error('service should not be called');
    },
  };
  const controller = new L1ReviewController(service);

  assert.throws(
    () => controller.verdict({ user: { role: 'OPERATOR' } }, 'Q1', { verdict: 'pass' }),
    ForbiddenException,
  );
}

async function testManagerDelegatesToService() {
  const calls: any[] = [];
  const service: any = {
    list: async (kind: string | undefined, pendingOnly: boolean) => {
      calls.push(['list', kind, pendingOnly]);
      return [];
    },
    narrate: async (id: string) => {
      calls.push(['narrate', id]);
      return { id };
    },
    submitVerdict: async (id: string, body: any, reviewer: any) => {
      calls.push(['verdict', id, body, reviewer]);
      return { id, ...body };
    },
  };
  const controller = new L1ReviewController(service);
  const req = { user: { id: 'gloriahao', role: 'MANAGER' } };

  assert.deepEqual(await controller.list(req, 'gate', 'false'), []);
  assert.deepEqual(await controller.narrate(req, 'Q1'), { id: 'Q1' });
  assert.deepEqual(await controller.verdict(req, 'Q1', { verdict: 'pass' }), { id: 'Q1', verdict: 'pass' });

  assert.deepEqual(calls, [
    ['list', 'gate', false],
    ['narrate', 'Q1'],
    ['verdict', 'Q1', { verdict: 'pass' }, req.user],
  ]);
}

async function main() {
  await testListRejectsNonManager();
  await testNarrateRejectsNonManager();
  await testSubmitVerdictRejectsNonManager();
  await testManagerDelegatesToService();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
