// 独立版外壳:原来的政策月刊接口是从公共事务复制来的同事文件,本仓没有。这里只留总览用到的列表接口和字段。
import { http } from './client';

export interface MonthlyListItem {
  id: string;
  title: string;
  status: string;
  coverDate?: string | null;
}

export const monthlyApi = {
  list: () => http.get<never, MonthlyListItem[]>('/monthlies'),
};
