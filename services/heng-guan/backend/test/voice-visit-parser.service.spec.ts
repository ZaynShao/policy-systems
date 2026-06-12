import assert from 'assert/strict';
import { BadRequestException } from '@nestjs/common';
import { VoiceVisitParserService } from '../src/voice/voice-visit-parser.service';

async function testRejectsTooShortTranscript() {
  const service = new VoiceVisitParserService({} as any);

  await assert.rejects(
    () => service.parseVisitText({ transcript: '嗯', context: { today: '2026-06-12' } }),
    BadRequestException,
  );
}

async function testParsesVisitFieldsFromModelJson() {
  let messages: any;
  const deepseek: any = {
    chat: async (input: any) => {
      messages = input;
      return {
        content: '```json\n{"region":"四川","orgName":"四川省能源局","contactName":"张处长","contactDepart":"新能源处","contactPhone":"13800000000","topic":"储能新政落地口径沟通","goal":"确认申报时间表和白名单要求","plannedAt":"2026-06-13T09:30:00+08:00"}\n```',
      };
    },
  };
  const service = new VoiceVisitParserService(deepseek);

  const result = await service.parseVisitText({
    transcript: '明天上午去四川省能源局找张处长，聊储能新政落地口径，想确认申报时间表和白名单要求。',
    context: { today: '2026-06-12', currentRegion: '四川' },
  });

  assert.equal(result.transcript.includes('四川省能源局'), true);
  assert.equal(result.parsed.region, '四川');
  assert.equal(result.parsed.orgName, '四川省能源局');
  assert.equal(result.parsed.contactName, '张处长');
  assert.equal(result.parsed.contactDepart, '新能源处');
  assert.equal(result.parsed.contactPhone, '13800000000');
  assert.equal(result.parsed.topic, '储能新政落地口径沟通');
  assert.equal(result.parsed.goal, '确认申报时间表和白名单要求');
  assert.equal(result.parsed.plannedAt, '2026-06-13T01:30:00.000Z');
  assert.equal(messages[0].role, 'system');
  assert.equal(messages[1].content.includes('明天上午去四川省能源局'), true);
}

async function testDropsInvalidPhoneAndDate() {
  const deepseek: any = {
    chat: async () => ({
      content: '{"region":"北京","contactPhone":"12345","plannedAt":"下周见","topic":"政策沟通","goal":"确认口径"}',
    }),
  };
  const service = new VoiceVisitParserService(deepseek);

  const result = await service.parseVisitText({
    transcript: '下周去北京沟通政策口径',
    context: { today: '2026-06-12' },
  });

  assert.equal(result.parsed.region, '北京');
  assert.equal(result.parsed.contactPhone, null);
  assert.equal(result.parsed.plannedAt, null);
}

async function main() {
  await testRejectsTooShortTranscript();
  await testParsesVisitFieldsFromModelJson();
  await testDropsInvalidPhoneAndDate();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
