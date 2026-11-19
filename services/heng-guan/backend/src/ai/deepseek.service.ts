// 独立版外壳:原平台调大模型的 DeepseekService 是同事写的(账号、地址从平台配置读),不在本仓。
// 我的 L1 审核"AI 解读"和拜访语音解析只用它的 chat(消息, 选项) → { content } 这一个约定。
// 独立版没有接模型,调用会直接报错;测试里传入的是替身。
import { Injectable, ServiceUnavailableException } from '@nestjs/common';

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export interface ChatResult {
  content: string;
}

@Injectable()
export class DeepseekService {
  async chat(
    _messages: ChatMessage[],
    _opts: { temperature?: number; maxTokens?: number; jsonMode?: boolean } = {},
  ): Promise<ChatResult> {
    throw new ServiceUnavailableException('独立版没有接大模型');
  }
}
