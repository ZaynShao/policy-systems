// 这个文件原来是同事建的(大盘模块的前端接口),本仓只收我写的部分,其余是独立版的最小外壳。
// 我写的(原项目 PR 124「政策大盘对齐 pipeline 的 L2」,原样搬来):政策覆盖结果里的单条政策类型、
// 省级条目的区划代码、全国单列、主题编号这几处。行尾标「外壳」的是原来同事写的字段或接口,这里按原约定重写;
// 同事的属地大盘(overview、byRegion)接口和类型一行不带。
import { http } from './client'; // 外壳

export interface PolicyCoveragePolicy {
  id: string;
  title: string;
  importance: string;
  issueDate: string;
  adcode: string;      // 政策 L1 adcode(供按市/区钻取)
  regionLevel: string; // 省/市/区/国家
}
export interface PolicyCoverageItem { // 外壳
  region: string;   // 省级全名(canonical key,与 geojson 对齐)
  adcode: string;   // 省级 adcode(XX0000)
  policyCount: number; // 外壳
  feedbackCount: number; // 外壳
  majorCount: number; // 外壳
  strategicCount: number; // 外壳
  weight: number; // 外壳
  policies: PolicyCoveragePolicy[];
}
export interface PolicyCoverageNational {
  policyCount: number;
  majorCount: number;
  strategicCount: number;
  policies: PolicyCoveragePolicy[];
}
export interface PolicyCoverageTopic { // 外壳
  topicId: string; // 外壳
  themeId: string;
  name: string; // 外壳
  description?: string; // 外壳
  isEnergy: boolean; // 外壳
  color: string; // 外壳
  keywords: string[]; // 外壳
  coverage: PolicyCoverageItem[]; // 外壳
  national: PolicyCoverageNational; // C5:全国政策单列
  totalPolicies: number; // 外壳
  totalRegions: number; // 外壳
} // 外壳
export interface PolicyCoverageResp { // 外壳
  window: { days: number; since: string }; // 外壳
  topics: PolicyCoverageTopic[]; // 外壳
} // 外壳

// ── 外壳:政策详情面板要的知识库摘要。原页面用同事写的知识库接口(api/knowledge.ts、utils/policyKnowledgeLoader.ts)
//    分页取全量条目,这里合成一个最小接口,字段名与原来的知识库条目一致,只留详情面板用到的。
export interface PolicyKnowledgeItem {
  id: string;
  title: string;
  issuer: string;
  region: string;
  date: string;
  oneLiner: string;
  readingValue: string;
  summary: string;
  actions: string[];
}
export interface PolicyKnowledgeSource {
  policyCount: number;
  themeCount: number;
  loadedCount: number;
}

export const dashboardApi = { // 外壳
  policyCoverage: (days = 365) => // 外壳
    http.get<any, PolicyCoverageResp>('/dashboard/policy-coverage', { params: { days } }), // 外壳
  knowledgePreview: () => // 外壳
    http.get<any, { items: PolicyKnowledgeItem[]; source: PolicyKnowledgeSource }>('/knowledge/preview'), // 外壳
}; // 外壳
