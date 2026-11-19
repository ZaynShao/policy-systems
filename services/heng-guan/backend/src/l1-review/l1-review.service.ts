import { BadRequestException, Injectable, Logger, NotFoundException } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';
import { DeepseekService } from '../ai/deepseek.service';

export const VERDICTS: Record<string, string[]> = {
  gate: ['pass', 'commentary', 'reject'],
  checkpoint: ['promote', 'drop'],
  sweep: ['confirm', 'keep'],
  fetch_fail: ['retry', 'unfetchable', 'drop'],
};

const VERDICT_MEANINGS: Record<string, Record<string, string>> = {
  gate: { pass: '这条该当政策收', commentary: '该当评论收', reject: '弃' },
  checkpoint: { promote: '这个候选渠道提升去验证', drop: '移除' },
  sweep: { confirm: '确认是误分类(将挪走)', keep: '不动' },
  fetch_fail: { retry: '换参数重抓', unfetchable: '标记抓不了', drop: '跳过' },
};

@Injectable()
export class L1ReviewService {
  private readonly logger = new Logger(L1ReviewService.name);

  constructor(
    private prisma: PrismaService,
    private deepseek: DeepseekService,
  ) {}

  list(kind?: string, pendingOnly = true) {
    const where: any = {
      ...(pendingOnly ? { verdict: null } : {}),
      ...(kind ? { pipelineKind: kind } : {}),
    };
    return this.prisma.l1ReviewQueue.findMany({ where, orderBy: { createdAt: 'asc' } });
  }

  async narrate(id: string) {
    const row = await this.prisma.l1ReviewQueue.findUnique({ where: { id } });
    if (!row) throw new NotFoundException('审核项不存在');
    const kind = String(row.pipelineKind);
    const options = this.describeOptions(kind);
    const systemContent = '你是数据质量助理,给技术审阅人把一条"机器拿不准的源质量项"讲成人话。\n只解释、不替人做判断;不得编造证据外的信息。';
    const userPrompt = `这是一条进入人工审核池的项,kind=${row.pipelineKind}。
- 它指向:${row.pipelineRef}
- 机器为何拿不准(reason):${row.reason ?? ''}
- 证据(evidence):${row.evidence ?? ''}
- 机器倾向(suggested_action):${row.suggestedAction ?? ''},置信:${row.confidence ?? ''}
- 审阅选项:${options}
请输出 JSON:{"narration": "<=120字,说清三件事:这是什么、为什么进池、审阅人要在哪几个选项里判(列出该 kind 的 verdict 及含义)>"}。`;

    const result = await this.deepseek.chat(
      [
        { role: 'system', content: systemContent },
        { role: 'user', content: userPrompt },
      ],
      { jsonMode: true, temperature: 0.3 },
    );

    let parsed: any;
    try {
      parsed = JSON.parse(result.content);
    } catch (e) {
      this.logger.error('AI 输出 JSON 解析失败', result.content);
      throw new Error('AI 输出格式不合法');
    }

    return this.prisma.l1ReviewQueue.update({
      where: { id },
      data: { aiNarration: parsed.narration, aiNarratedAt: new Date() },
    });
  }

  async submitVerdict(id: string, body: { verdict: string; note?: string; corrections?: any }, reviewer: any) {
    const row = await this.prisma.l1ReviewQueue.findUnique({ where: { id } });
    if (!row) throw new NotFoundException('审核项不存在');
    const allowed = VERDICTS[String(row.pipelineKind)] ?? [];
    if (!allowed.includes(body.verdict)) {
      throw new BadRequestException('非法裁决');
    }
    return this.prisma.l1ReviewQueue.update({
      where: { id },
      data: {
        verdict: body.verdict,
        reviewer: typeof reviewer === 'string' ? reviewer : reviewer?.id,
        note: body.note,
        corrections: body.corrections,
        verdictAt: new Date(),
      },
    });
  }

  private describeOptions(kind: string) {
    const meanings = VERDICT_MEANINGS[kind] ?? {};
    return (VERDICTS[kind] ?? []).map((v) => `${v}=${meanings[v] ?? ''}`).join(' / ');
  }
}
