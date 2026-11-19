// 政策问答服务(policy-qa)客户端。
//
// 注意:它**不在** /heng/ 下 —— policy-qa 是平台里另一个服务,nginx 上是独立的
// `location /policy-qa/`。所以这里不能用 @/api/client 的 axios 实例(那个 baseURL
// 是 /heng/api/v1),要走绝对路径。
//
// 鉴权同样不归这里管:nginx 是 server 级 auth_request,登录态由平台统一校验,
// 前端不需要带任何令牌。

/** 统一部署时是 /policy-qa;本地开发由 vite proxy 转发到 nginx。 */
export const policyQaBase =
  ((import.meta as any).env?.VITE_POLICY_QA_BASE as string | undefined) || '/policy-qa';

export interface QaMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface QaCitation {
  pid: string;
  title: string;
  doc_number?: string | null;
  source_url?: string | null;
  /** 该政策的已知数据缺陷(如同一 pid 对应多份文件),非空时必须让用户看到 */
  caveat?: string | null;
}

export interface QaToolEvent {
  seq: number;
  name: string;
  args_preview?: string;
  status: 'start' | 'done';
  result_chars?: number;
}

/** 服务端在检索之前定的计划。展示它是为了让用户看得见"它打算怎么查"。 */
export interface QaPlan {
  kind: 'single_policy' | 'survey' | 'other';
  /** 主题内部 id(charging_infra 之类),排查用 */
  themes: string[];
  /** 同序的中文名,显示用。服务端查好一并下发,前端不硬编码分类体系 */
  theme_labels?: string[];
  business_lines: string[];
  keywords: string[];
  issuers: string[];
  note?: string;
}

/**
 * 事实核验结果。**只在发现问题时才会收到**。
 *
 * 服务端拿答案里的文号与引文回本轮检索到的材料做逐字比对,对不上的列在这里。
 * 它不改写答案,所以前端必须把这条显示出来 —— 不显示就等于这层核验没做。
 */
export interface QaVerify {
  checked: { doc_numbers: number; quotes: number };
  unsupported: Array<{ kind: 'doc_number' | 'quote'; text: string; hint: string }>;
}

export interface QaDone {
  citations: QaCitation[];
  usage?: { prompt_tokens?: number; completion_tokens?: number; tool_calls?: number };
}

/** 一次问答的可选项。字段留空 = 跟随服务端默认。 */
export interface QaChatOptions {
  /**
   * 是否结合公司业务分析。
   *
   * 留空(undefined)时**不发这个字段**,由服务端按"配了战略画像就开"决定;
   * 显式 false 则即使配了画像也只解读政策本身,不给业务判断。
   */
  useBusinessContext?: boolean;
}

/**
 * 服务端的业务框定能力。available=false 表示没配战略画像,
 * 此时那个勾选必须置灰 —— 让用户勾一个其实不生效的框,比不给这个框更糟:
 * 他会以为答案里已经带了业务判断。
 */
export interface QaBusinessContext {
  available: boolean;
  default_on: boolean;
  profile_id: string | null;
  effective_from: string | null;
}

/** 读服务端能力。任何失败都返回 null —— 调用方据此把勾选藏起来,不弹错。 */
export async function fetchQaBusinessContext(
  signal?: AbortSignal,
): Promise<QaBusinessContext | null> {
  try {
    const resp = await fetch(`${policyQaBase}/v1/health`, { signal });
    if (!resp.ok) return null;
    const body = await resp.json();
    const ctx = body?.business_context;
    return ctx && typeof ctx.available === 'boolean' ? (ctx as QaBusinessContext) : null;
  } catch {
    return null;
  }
}

export interface QaHandlers {
  onMeta?: (m: { request_id: string; history_truncated: boolean }) => void;
  onPlan?: (p: QaPlan) => void;
  onTool?: (t: QaToolEvent) => void;
  onDelta?: (text: string) => void;
  /** 本轮已显示的文本其实是模型的规划自语,前端应清空当前累积后重来 */
  onDeltaReset?: () => void;
  onVerify?: (v: QaVerify) => void;
  onDone?: (d: QaDone) => void;
  onError?: (message: string) => void;
}

/** 工具名 → 给人看的说法。UI 不该直接把内部工具名甩给业务同事。 */
export const TOOL_LABELS: Record<string, string> = {
  search_policies: '检索政策库',
  get_policy_fulltext: '读取政策原文',
  get_policy_relations: '查政策上下游关系',
  get_policy_commentary: '查行业解读',
};

export async function fetchQaHealth(): Promise<{ ok: boolean; policies?: number; latest_issue_date?: string }> {
  const resp = await fetch(`${policyQaBase}/v1/health`, { headers: { Accept: 'application/json' } });
  if (!resp.ok) throw new Error(`健康检查失败 ${resp.status}`);
  return resp.json();
}

/**
 * 发起一轮问答并按 SSE 流式回调。
 *
 * 服务端**不存会话**:每次要把完整历史带上(不含 system —— 答题纪律在服务端,
 * 客户端传 system 会被 400 拒掉)。
 */
export async function streamQaChat(
  messages: QaMessage[],
  handlers: QaHandlers,
  signal?: AbortSignal,
  options?: QaChatOptions,
): Promise<void> {
  let resp: Response;
  try {
    resp = await fetch(`${policyQaBase}/v1/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      // use_business_context 只在调用方明确给了才发。发 undefined 会被
      // JSON.stringify 丢掉,但显式写出来更清楚:留空 = 用服务端默认。
      body: JSON.stringify(
        options?.useBusinessContext === undefined
          ? { messages }
          : { messages, use_business_context: options.useBusinessContext },
      ),
      signal,
    });
  } catch (e: any) {
    if (e?.name === 'AbortError') return;
    handlers.onError?.('无法连接政策问答服务');
    return;
  }

  if (resp.status === 401 || resp.status === 403) {
    handlers.onError?.('登录态已失效，请重新登录平台后重试。');
    return;
  }
  if (!resp.ok || !resp.body) {
    handlers.onError?.(`请求失败（HTTP ${resp.status}）`);
    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      // SSE 按空行分帧;最后一段可能不完整,留到下一轮再拼
      const blocks = buf.split('\n\n');
      buf = blocks.pop() ?? '';
      for (const block of blocks) {
        let event = '';
        let data = '';
        for (const line of block.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim();
          else if (line.startsWith('data:')) data += line.slice(5).trim();
        }
        if (!data) continue;
        let parsed: any;
        try {
          parsed = JSON.parse(data);
        } catch {
          continue;
        }
        if (event === 'meta') handlers.onMeta?.(parsed);
        else if (event === 'plan') handlers.onPlan?.(parsed);
        else if (event === 'tool') handlers.onTool?.(parsed);
        else if (event === 'delta') handlers.onDelta?.(parsed.text ?? '');
        else if (event === 'delta_reset') handlers.onDeltaReset?.();
        else if (event === 'verify') handlers.onVerify?.(parsed);
        else if (event === 'done') handlers.onDone?.(parsed);
        else if (event === 'error') handlers.onError?.(parsed.message ?? '服务出错');
      }
    }
  } catch (e: any) {
    if (e?.name !== 'AbortError') handlers.onError?.('连接中断');
  }
}
