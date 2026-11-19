// 独立版演示:政策问答服务的接口替身。不连后端,用内置的真实问答记录回答页面要调的两个接口:
// - GET  /policy-qa/v1/health:服务状态。演示版不带公司业务画像,所以「结合公司业务分析」是置灰的;
// - POST /policy-qa/v1/chat:按问题原文找录下来的那一轮,把当时的流式事件(计划、检索进度、逐段答复、核验、引用)
//   按原来的先后和间隔(加快一倍)重放;没录过的问题回一句说明。
import { policyQaBase } from '@/api/policy-qa';

export interface RecordedQa {
  question: string;
  asked_at: string;
  duration_ms: number;
  /** [相对开始的毫秒数, 事件名, 事件数据],与服务端 SSE 一一对应 */
  events: Array<[number, string, unknown]>;
}
export interface QaDemoData {
  health: Record<string, unknown>;
  qa: { recorded_at: string; source: string; items: RecordedQa[] };
}

const SPEED = 2;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const sse = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

function replay(events: Array<[number, string, unknown]>, signal?: AbortSignal | null): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    async start(ctrl) {
      let last = 0;
      for (const [t, ev, data] of events) {
        if (signal?.aborted) break;
        await sleep(Math.min(Math.max(0, t - last) / SPEED, 1500));
        last = t;
        ctrl.enqueue(enc.encode(sse(ev, data)));
      }
      ctrl.close();
    },
  });
}

function notRecorded(questions: string[]): Array<[number, string, unknown]> {
  const text = questions.length
    ? '这是离线演示版:只内置了下面这些在测试站上真实问过的问题和回答,别的问题离线没法现场回答。\n\n'
      + questions.map((q) => `- ${q}`).join('\n')
    : '这是离线演示版,还没有录入真实问答(测试站恢复后补录),离线没法现场回答。';
  return [[0, 'meta', { request_id: 'demo', history_truncated: false }], [300, 'delta', { text }],
    [400, 'done', { citations: [] }]];
}

export function installQaDemo(data: QaDemoData) {
  const byQuestion = new Map(data.qa.items.map((r) => [r.question.trim(), r]));
  const realFetch = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const path = url.replace(/^https?:\/\/[^/]+/, '');
    if (path.startsWith(`${policyQaBase}/v1/health`)) {
      return new Response(JSON.stringify(data.health), { headers: { 'Content-Type': 'application/json' } });
    }
    if (path.startsWith(`${policyQaBase}/v1/chat`)) {
      const body = JSON.parse(String(init?.body || '{}'));
      const lastUser = [...(body.messages || [])].reverse().find((m: { role: string }) => m.role === 'user');
      const rec = byQuestion.get(String(lastUser?.content || '').trim());
      const events = rec ? rec.events : notRecorded([...byQuestion.keys()]);
      return new Response(replay(events, init?.signal), { headers: { 'Content-Type': 'text/event-stream' } });
    }
    return realFetch(input, init);
  };
}
