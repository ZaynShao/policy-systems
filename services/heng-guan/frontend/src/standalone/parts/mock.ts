// 独立版演示模式的接口替身:离线页面不连后端,给 http(src/api/client.ts)装一个 axios 适配器,
// 按我写的后端接口的规则,用内置演示数据回答(数据来历见 ./data/README.md)。
// - 站内消息:可见范围、未读数、标为已读,照 backend/src/notification/notification.service.ts;
// - L1 源质量审核:待判列表、裁决(按类型校验裁决选项),照 backend/src/l1-review/l1-review.service.ts;
//   "AI 解读"要调大模型,演示版没有接,改成按审核项字段拼一段说明,并写明不是 AI 生成;
// - 政策大盘:回放用我写的聚合函数跑本机政策库录下的结果(30/90/180/365 天四个窗口);
// - 拜访语音解析:要调大模型,演示版只回放后端测试里两段口述的解析结果;机构、负责人、新建拜访是演示用的。
// 所有写操作只记在本页内存里,刷新即还原。
import { AxiosError, type AxiosAdapter, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios';
import { http } from '@/api/client';
import type { L1ReviewItem } from '@/api/l1Review';
import type { NotificationItem } from '@/api/notification';
import type { PolicyCoverageResp, PolicyKnowledgeItem, PolicyKnowledgeSource } from '@/api/dashboard';
import type { Assignee, OrgWithContacts, VoiceVisitParseResponse } from '@/api/visit';
import type { CurrentUser } from '@/stores/user';

export type L1Row = L1ReviewItem & {
  dedupeKey: string;
  corrections?: unknown;
  reviewer?: string | null;
  note?: string | null;
  verdictAt?: string | null;
  syncedBack?: boolean;
};

export interface VoiceSample {
  note: string;
  recordedToday: string;
  modelReply: string;
  transcript: string;
  response: VoiceVisitParseResponse;
}

export interface DemoVisit {
  id: string;
  code: string;
  region: string;
  orgName?: string;
  contactName?: string;
  topic: string;
  goal: string;
  plannedAt: string;
  mainAssigneeId: string;
  createdAt: string;
}

export interface DemoData {
  meta: { recorded_at: string; vault: { commit: string; committed_at: string; knowledge_entries: number; themes: number } };
  'l1-review': L1Row[];
  notifications: NotificationItem[];
  'dashboard-coverage': Record<string, PolicyCoverageResp>;
  'dashboard-knowledge': { source: PolicyKnowledgeSource; items: PolicyKnowledgeItem[] };
  'voice-samples': VoiceSample[];
  'visit-directory': { me: CurrentUser; assignees: Assignee[]; orgs: OrgWithContacts[] };
}

// 与后端 l1-review.service.ts 的 VERDICTS / VERDICT_MEANINGS 一致
const VERDICTS: Record<string, string[]> = {
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
const KIND_TEXT: Record<string, string> = { gate: '采集入口质量门', checkpoint: '候选渠道', sweep: '误分类扫描', fetch_fail: '抓取失败' };
// pipeline 进池时写的原因代码 → 大白话(依据 services/policy-pipeline 里进池的几处代码)
const REASON_TEXT: Record<string, string> = {
  discovery_candidate_unverified: '渠道发现找到了这个站点,但列表页探测或机构核验没通过,机器拿不准它是不是该机构的真列表页',
  low_conf: '质量门判断"是不是正式政策"时置信度不够',
  title_commentary_marker: '标题里有"政策解读"一类字样,疑似把解读当成政策收了',
  fetch_error_after_retry: '重试之后仍然抓取失败',
};
export const NARRATION_NOTE = '〔演示版没有接大模型:这段是按审核项字段拼的说明,不是 AI 生成〕';

function demoNarration(row: L1Row): string {
  const kind = String(row.pipelineKind);
  const options = (VERDICTS[kind] ?? []).map((v) => `${v}=${VERDICT_MEANINGS[kind]?.[v] ?? ''}`).join(' / ');
  const reason = REASON_TEXT[row.reason ?? ''] ?? row.reason ?? '未写原因';
  return `这是一条「${KIND_TEXT[kind] ?? kind}」项,指向 ${row.pipelineRef}。进池原因:${reason}。`
    + `机器倾向 ${row.suggestedAction ?? '无'}。审阅人在这几个裁决里选:${options}。${NARRATION_NOTE}`;
}

// 与后端一样,时间存成 ISO 字符串
const nowIso = () => new Date().toISOString();

class DemoHttpError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}
function fail(status: number, message: string): never {
  throw new DemoHttpError(status, message);
}

function parseBody(config: InternalAxiosRequestConfig): any {
  const d = config.data;
  if (typeof d !== 'string') return d ?? {};
  try { return JSON.parse(d); } catch { return {}; }
}

export interface DemoApi {
  visits: () => DemoVisit[];
}

export function installDemoApi(data: DemoData): DemoApi {
  const me = data['visit-directory'].me;
  const notifications = data.notifications.map((n) => ({ ...n }));
  const l1 = data['l1-review'].map((r) => ({ ...r }));
  const coverage = data['dashboard-coverage'];
  const visits: DemoVisit[] = [];

  function visibleNotifications() {
    // 与 NotificationService.list 一致:定向给本人的 + 广播里不限角色或限本角色的
    return notifications.filter((n) => n.targetUserId === me.id
      || (n.targetUserId == null && (n.targetRole == null || n.targetRole === me.role)));
  }

  function route(method: string, url: string, params: any, body: any): unknown {
    let m: RegExpExecArray | null;
    if (method === 'get' && url === '/workbench/whoami') return me;

    if (method === 'get' && url === '/notifications') {
      const unreadOnly = String(params?.unreadOnly) === 'true';
      const limit = params?.limit ? Number(params.limit) : 50;
      const visible = visibleNotifications();
      const items = visible
        .filter((n) => !unreadOnly || !n.readAt)
        .sort((a, b) => (a.createdAt < b.createdAt ? 1 : a.createdAt > b.createdAt ? -1 : 0))
        .slice(0, limit)
        .map((n) => ({ ...n }));
      return { items, unreadCount: visible.filter((n) => !n.readAt).length };
    }
    if (method === 'patch' && (m = /^\/notifications\/([^/]+)\/read$/.exec(url))) {
      const n = notifications.find((x) => x.id === decodeURIComponent(m![1]));
      if (!n) fail(404, '消息不存在');
      n.readAt = nowIso();
      return { ...n };
    }

    if (method === 'get' && url === '/l1-review') {
      const pendingOnly = String(params?.pending) !== 'false';
      const kind = params?.kind || '';
      return l1
        .filter((r) => (!pendingOnly || r.verdict == null) && (!kind || r.pipelineKind === kind))
        .sort((a, b) => (a.createdAt < b.createdAt ? -1 : a.createdAt > b.createdAt ? 1 : 0))
        .map((r) => ({ ...r }));
    }
    if (method === 'post' && (m = /^\/l1-review\/([^/]+)\/narrate$/.exec(url))) {
      const row = l1.find((r) => r.id === decodeURIComponent(m![1]));
      if (!row) fail(404, '审核项不存在');
      row.aiNarration = demoNarration(row);
      row.aiNarratedAt = nowIso();
      return { ...row };
    }
    if (method === 'patch' && (m = /^\/l1-review\/([^/]+)\/verdict$/.exec(url))) {
      const row = l1.find((r) => r.id === decodeURIComponent(m![1]));
      if (!row) fail(404, '审核项不存在');
      if (!(VERDICTS[String(row.pipelineKind)] ?? []).includes(body?.verdict)) fail(400, '非法裁决');
      Object.assign(row, { verdict: body.verdict, reviewer: me.id, note: body.note, corrections: body.corrections, verdictAt: nowIso() });
      return { ...row };
    }

    if (method === 'get' && url === '/dashboard/policy-coverage') {
      return coverage[String(Number(params?.days) || 365)] ?? coverage['365'];
    }
    if (method === 'get' && url === '/knowledge/preview') return data['dashboard-knowledge'];

    if (method === 'get' && url === '/orgs') return data['visit-directory'].orgs;
    if (method === 'get' && url === '/visits/assignees') return data['visit-directory'].assignees;
    if (method === 'post' && url === '/voice/parse-visit-text') {
      const transcript = String(body?.transcript ?? '').trim();
      if (transcript.length < 2) fail(400, '语音文本太短，请重试或手填');
      const hit = data['voice-samples'].find((s) => s.transcript === transcript);
      if (!hit) fail(502, '演示版没有接大模型,只能回放后端测试里录好的两段口述的解析结果;这段话可以直接手填表单');
      return hit.response;
    }
    if (method === 'post' && url === '/visits') {
      for (const k of ['region', 'topic', 'goal', 'plannedAt', 'mainAssigneeId']) {
        if (!String(body?.[k] ?? '').trim()) fail(400, '地区 / 拜访主题 / 拜访目标 / 计划时间 / 主拜访人 必填');
      }
      const v: DemoVisit = {
        id: `demo-visit-${visits.length + 1}`,
        code: `演示拜访-${String(visits.length + 1).padStart(3, '0')}`,
        region: body.region, orgName: body.orgName, contactName: body.contactName,
        topic: body.topic, goal: body.goal, plannedAt: body.plannedAt, mainAssigneeId: body.mainAssigneeId,
        createdAt: nowIso(),
      };
      visits.unshift(v);
      return { ...v };
    }
    fail(404, `演示版没有这个接口:${method.toUpperCase()} ${url}`);
  }

  const adapter: AxiosAdapter = async (config) => {
    const method = (config.method || 'get').toLowerCase();
    const url = (config.url || '').split('?')[0];
    const reply = (status: number, payload: unknown): AxiosResponse => ({ data: payload, status, statusText: String(status), headers: {}, config });
    try {
      const result = route(method, url, config.params, parseBody(config));
      return reply(200, { code: 0, data: result });
    } catch (e) {
      const status = e instanceof DemoHttpError ? e.status : 500;
      const msg = e instanceof Error ? e.message : String(e);
      const response = reply(status, { code: status, msg });
      throw new AxiosError(msg, status >= 500 ? AxiosError.ERR_BAD_RESPONSE : AxiosError.ERR_BAD_REQUEST, config, null, response);
    }
  };
  http.defaults.adapter = adapter;

  return { visits: () => visits.map((v) => ({ ...v })) };
}
