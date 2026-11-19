// 独立版外壳:原来的采集规则接口是从公共事务复制来的同事文件,本仓没有。这里只留总览用到的队列状态接口和字段。
import { http } from './client';

export interface CrawlerQueueStatus {
  backlog: number;
  counts: { pending: number; processing: number; success: number; skipped: number; retryableFail: number; exhaustedFail: number };
  oldestPending?: { discoveredAt?: string | null } | null;
}

export const crawlerApi = {
  queueStatus: () => http.get<never, CrawlerQueueStatus>('/crawler-rules/queue/status'),
};
