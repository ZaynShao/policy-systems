// 这个文件原来是同事建的(拜访模块的前端接口),本仓只收我写的部分,其余是独立版的最小外壳。
// 我写的:语音解析的两个类型和 parseVoiceVisit 接口(原项目 PR 48 加的 18 行,原样搬来)。
// 标「外壳」的是独立版补的:我的移动端拜访录入弹窗还要用到机构、负责人、创建拜访这三个接口和两个类型,
// 原来都是同事写的;这里按原接口路径重写一个最小版本,只留弹窗用到的字段。
import { http } from './client'; // 外壳

// ── 外壳:目标机构(带联系人),弹窗的机构下拉和对接人下拉用
export interface OrgWithContacts {
  id: string;
  name: string;
  region: string;
  contacts: Array<{ id: string; name: string; title?: string }>;
}

// ── 外壳:可选的主拜访人
export interface Assignee {
  id: string;
  name: string;
  role: string;
  region?: string;
}

// ── 我写的(原项目 PR 48)
export interface ParsedVisitFields {
  region: string | null;
  orgName: string | null;
  contactName: string | null;
  contactDepart: string | null;
  contactPhone: string | null;
  topic: string | null;
  goal: string | null;
  plannedAt: string | null;
}

export interface VoiceVisitParseResponse {
  transcript: string;
  parsed: ParsedVisitFields;
}

export const visitApi = { // 外壳
  assignees: () => http.get<any, Assignee[]>('/visits/assignees'), // 外壳
  orgs: () => http.get<any, OrgWithContacts[]>('/orgs'), // 外壳
  create: (body: Record<string, unknown>) => http.post<any, { id: string; code: string }>('/visits', body), // 外壳
  // ── 我写的(原项目 PR 48)
  parseVoiceVisit: (body: { transcript: string; context?: { today?: string; currentRegion?: string | null; currentOrgName?: string | null } }) =>
    http.post<any, VoiceVisitParseResponse>('/voice/parse-visit-text', body),
}; // 外壳
