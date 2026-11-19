import assert from 'assert/strict';
import { BadRequestException } from '@nestjs/common';
import { L1ReviewService } from '../src/l1-review/l1-review.service';

async function testListBuildsPendingAndKindWhere() {
  let findManyArgs: any;
  const prisma: any = {
    l1ReviewQueue: {
      findMany: async (args: any) => {
        findManyArgs = args;
        return [];
      },
    },
  };
  const service = new L1ReviewService(prisma, {} as any);

  await service.list('gate', true);

  assert.deepEqual(findManyArgs.where, { verdict: null, pipelineKind: 'gate' });
  assert.deepEqual(findManyArgs.orderBy, { createdAt: 'asc' });
}

async function testSubmitVerdictWritesOnlyHumanReviewFields() {
  let updateArgs: any;
  const prisma: any = {
    l1ReviewQueue: {
      findUnique: async () => ({ id: 'Q1', pipelineKind: 'gate' }),
      update: async (args: any) => {
        updateArgs = args;
        return { id: args.where.id, ...args.data };
      },
    },
  };
  const service = new L1ReviewService(prisma, {} as any);

  await service.submitVerdict(
    'Q1',
    { verdict: 'pass', note: 'ok', corrections: { corrected_label: 'policy' } },
    { id: 'gloriahao', role: 'MANAGER' },
  );

  assert.deepEqual(updateArgs.where, { id: 'Q1' });
  assert.equal(updateArgs.data.verdict, 'pass');
  assert.equal(updateArgs.data.reviewer, 'gloriahao');
  assert.equal(updateArgs.data.note, 'ok');
  assert.deepEqual(updateArgs.data.corrections, { corrected_label: 'policy' });
  assert.ok(updateArgs.data.verdictAt instanceof Date);
  assert.equal('pipelineKind' in updateArgs.data, false);
  assert.equal('pipelineRef' in updateArgs.data, false);
  assert.equal('syncedBack' in updateArgs.data, false);
}

async function testSubmitVerdictRejectsInvalidVerdictAndDoesNotUpdate() {
  let updateCalled = false;
  const prisma: any = {
    l1ReviewQueue: {
      findUnique: async () => ({ id: 'Q1', pipelineKind: 'gate' }),
      update: async () => {
        updateCalled = true;
      },
    },
  };
  const service = new L1ReviewService(prisma, {} as any);

  await assert.rejects(
    () => service.submitVerdict('Q1', { verdict: 'promote' }, { id: 'gloriahao' }),
    BadRequestException,
  );
  assert.equal(updateCalled, false);
}

async function testNarrateWritesAiNarration() {
  let chatArgs: any;
  let updateArgs: any;
  const prisma: any = {
    l1ReviewQueue: {
      findUnique: async () => ({
        id: 'Q1',
        pipelineKind: 'gate',
        pipelineRef: 'channel-a',
        reason: 'uncertain',
        evidence: 'title/evidence',
        suggestedAction: 'pass',
        confidence: 0.7,
      }),
      update: async (args: any) => {
        updateArgs = args;
        return { id: args.where.id, ...args.data };
      },
    },
  };
  const deepseek: any = {
    chat: async (...args: any[]) => {
      chatArgs = args;
      return { content: '{"narration":"xx"}' };
    },
  };
  const service = new L1ReviewService(prisma, deepseek);

  await service.narrate('Q1');

  assert.deepEqual(chatArgs[1], { jsonMode: true, temperature: 0.3 });
  assert.equal(updateArgs.data.aiNarration, 'xx');
  assert.ok(updateArgs.data.aiNarratedAt instanceof Date);
}

async function main() {
  await testListBuildsPendingAndKindWhere();
  await testSubmitVerdictWritesOnlyHumanReviewFields();
  await testSubmitVerdictRejectsInvalidVerdictAndDoesNotUpdate();
  await testNarrateWritesAiNarration();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
