// 独立版补的:离线演示页面的接口替身。不连后端,用内置的几期月刊回答月刊页要调的三个接口,
// 返回格式与原平台一致(经 src/api/client.ts 拆掉 { code, data } 外层)。
// - GET  /monthlies、/monthlies/:id —— 只读,数据来自 data/*.json;
// - POST /monthlies/:id/revision-note —— 按原后端里我写的规则(backend/src/monthly/monthly-v2.fragment.ts)
//   把意见记进 content.pendingNote,只存在本页内存里,刷新即还原。
import type { AxiosAdapter, AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import { http } from '@/api/client';
import type { MonthlyDetail } from '@/api/monthly';

const MAX_NOTE = 2000;

class DemoError extends Error {
  constructor(readonly code: number, message: string) { super(message); }
}

function reply(config: InternalAxiosRequestConfig, body: unknown): AxiosResponse {
  return { data: body, status: 200, statusText: 'OK', headers: {}, config };
}

export function installMonthlyDemo(items: MonthlyDetail[]) {
  const byId = new Map(items.map((m) => [m.id, JSON.parse(JSON.stringify(m)) as MonthlyDetail]));
  const copy = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
  const find = (id: string) => {
    const m = byId.get(decodeURIComponent(id));
    if (!m) throw new DemoError(404, '月刊不存在');
    return m;
  };

  function route(method: string, url: string, body: unknown): unknown {
    if (method === 'get' && url === '/monthlies') return copy([...byId.values()]);
    let m = /^\/monthlies\/([^/]+)$/.exec(url);
    if (method === 'get' && m) return copy(find(m[1]));
    m = /^\/monthlies\/([^/]+)\/revision-note$/.exec(url);
    if (method === 'post' && m) {
      const raw = (body as { note?: unknown } | null)?.note;
      const text = (typeof raw === 'string' ? raw : '').trim();
      if (!text) throw new DemoError(400, '修改意见不能为空');
      if (text.length > MAX_NOTE) throw new DemoError(400, `修改意见过长（上限 ${MAX_NOTE} 字）`);
      const monthly = find(m[1]);
      monthly.content = Object.assign(copy(monthly.content), {
        pendingNote: text,
        pendingNoteAt: new Date().toISOString(),
      });
      return { ok: true, pendingNote: text };
    }
    throw new DemoError(404, '演示版没有这个接口');
  }

  const adapter: AxiosAdapter = async (config) => {
    const url = (config.url ?? '').split('?')[0];
    const method = (config.method ?? 'get').toLowerCase();
    const body = typeof config.data === 'string' && config.data ? JSON.parse(config.data) : config.data;
    try {
      return reply(config, { code: 0, data: route(method, url, body) });
    } catch (e) {
      const err = e instanceof DemoError ? e : new DemoError(500, String((e as Error)?.message ?? e));
      return reply(config, { code: err.code, msg: err.message });
    }
  };
  http.defaults.adapter = adapter;
}
