import { BadGatewayException, BadRequestException, Injectable } from '@nestjs/common';
import { DeepseekService } from '../ai/deepseek.service';
import { ParsedVisitFields, ParseVisitTextDto, ParseVisitTextResponse } from './voice.dto';

const EMPTY_FIELDS: ParsedVisitFields = {
  region: null,
  orgName: null,
  contactName: null,
  contactDepart: null,
  contactPhone: null,
  topic: null,
  goal: null,
  plannedAt: null,
};

@Injectable()
export class VoiceVisitParserService {
  constructor(private readonly deepseek: DeepseekService) {}

  async parseVisitText(dto: ParseVisitTextDto): Promise<ParseVisitTextResponse> {
    const transcript = dto.transcript.trim();
    if (transcript.length < 2) throw new BadRequestException('语音文本太短，请重试或手填');

    const today = dto.context?.today || new Date().toISOString().slice(0, 10);
    const result = await this.deepseek.chat(
      [
        { role: 'system', content: this.buildSystemPrompt(today, dto.context?.currentRegion || null, dto.context?.currentOrgName || null) },
        { role: 'user', content: transcript },
      ],
      { temperature: 0.1, maxTokens: 1200, jsonMode: true },
    );

    return {
      transcript,
      parsed: this.normalize(this.extractJson(result.content)),
    };
  }

  private buildSystemPrompt(today: string, currentRegion: string | null, currentOrgName: string | null) {
    return `你是公共事务拜访创建助手。根据用户口述内容，抽取创建拜访计划所需字段。

今天日期：${today}
当前已选地区：${currentRegion || '无'}
当前已选机构：${currentOrgName || '无'}

只输出 JSON，不要解释。字段：
{
  "region": "地区，如 四川、北京、山东-济南；无法判断为 null",
  "orgName": "目标机构全称；无法判断为 null",
  "contactName": "对接人姓名或称呼；无法判断为 null",
  "contactDepart": "对接人部门；无法判断为 null",
  "contactPhone": "11 位手机号；无法判断为 null",
  "topic": "拜访主题，12-40 字；无法判断为 null",
  "goal": "拜访目标或期望产出，12-80 字；无法判断为 null",
  "plannedAt": "计划拜访时间，必须是 ISO 8601 字符串；无法判断为 null"
}

规则：
- 遇到“明天、下周、下午”等相对时间，基于今天日期换算。
- 用户未说年份时用今天所在年份。
- 不能臆造姓名、电话、地区、机构。
- 如果用户只说要沟通某事项，可把事项整理成 topic 和 goal。
- 输出必须是合法 JSON object。`;
  }

  private extractJson(content: string): Record<string, unknown> {
    const stripped = content
      .replace(/<think>[\s\S]*?<\/think>/g, '')
      .replace(/^```(?:json)?/i, '')
      .replace(/```$/i, '')
      .trim();
    const first = stripped.indexOf('{');
    const last = stripped.lastIndexOf('}');
    if (first < 0 || last <= first) throw new BadGatewayException('AI 返回格式错误');
    try {
      return JSON.parse(stripped.slice(first, last + 1));
    } catch {
      throw new BadGatewayException('AI 返回格式错误');
    }
  }

  private normalize(raw: Record<string, unknown>): ParsedVisitFields {
    return {
      ...EMPTY_FIELDS,
      region: cleanString(raw.region),
      orgName: cleanString(raw.orgName),
      contactName: cleanString(raw.contactName),
      contactDepart: cleanString(raw.contactDepart),
      contactPhone: cleanPhone(raw.contactPhone),
      topic: cleanString(raw.topic),
      goal: cleanString(raw.goal),
      plannedAt: cleanDate(raw.plannedAt),
    };
  }
}

function cleanString(v: unknown): string | null {
  if (typeof v !== 'string') return null;
  const t = v.trim();
  return t || null;
}

function cleanPhone(v: unknown): string | null {
  const t = cleanString(v);
  if (!t) return null;
  return /^\d{11}$/.test(t) ? t : null;
}

function cleanDate(v: unknown): string | null {
  const t = cleanString(v);
  if (!t) return null;
  const d = new Date(t);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}
