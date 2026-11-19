// 独立版外壳:原来的模型通道解析是同事写的(guardian 后端几个用 AI 的模块共用),本仓没有。
// 研判模块只用到下面三个函数,这里给最小替身,约定不变:
//   - 密钥、地址、模型名只从环境变量读:LLM_API_KEY、LLM_BASE_URL(可选,不配就用 openai 包的默认地址)、LLM_MODEL;
//   - 密钥和模型名要配齐才算配置了模型;没配齐时 createLlmClient 抛错,研判模块据此熔断(ai_not_configured),
//     全部工单按规则兜底,并在结果包里写明。
import OpenAI from 'openai';

export interface LlmChannel {
  apiKey: string;
  baseURL: string;
  model: string;
}

export function resolveLlmChannel(): LlmChannel {
  const model = (process.env.LLM_MODEL || '').trim();
  return {
    apiKey: model ? (process.env.LLM_API_KEY || '').trim() : '',
    baseURL: (process.env.LLM_BASE_URL || '').trim(),
    model,
  };
}

export function createLlmClient(): OpenAI {
  const ch = resolveLlmChannel();
  if (!ch.apiKey) throw new Error('LLM_API_KEY / LLM_MODEL 未配齐');
  return new OpenAI({ apiKey: ch.apiKey, ...(ch.baseURL ? { baseURL: ch.baseURL } : {}) });
}

export function llmModel(): string {
  return resolveLlmChannel().model;
}
