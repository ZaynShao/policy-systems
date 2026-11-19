// 独立版外壳:原来的政策知识库接口是从公共事务复制来的同事文件,本仓没有。这里只留总览用到的两个读接口和字段。
import { http } from './client';

export interface KnowledgeStats {
  entryCount: number;
  highImportanceCount: number;
  themeCount: number;
  relationCount: number;
  regionCount: number;
  lastSync?: { startedAt?: string | null; finishedAt?: string | null } | null;
}

export interface SyncStatus {
  recent: Array<{ status: string; startedAt?: string | null; finishedAt?: string | null; entryCount?: number | null }>;
}

export const knowledgeApi = {
  stats: () => http.get<never, KnowledgeStats>('/knowledge/stats'),
  syncStatus: () => http.get<never, SyncStatus>('/knowledge/sync/status'),
};
