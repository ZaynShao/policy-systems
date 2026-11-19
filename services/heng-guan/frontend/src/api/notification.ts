import { http } from './client';

export interface NotificationItem {
  id: string;
  level: 'INFO' | 'WARN' | 'ERROR';
  title: string;
  body?: string | null;
  source: string;
  createdAt: string;
  readAt?: string | null;
  targetRole?: string | null;
  targetUserId?: string | null;
}

export interface NotificationListResult {
  items: NotificationItem[];
  unreadCount: number;
}

export const notificationApi = {
  list: (unreadOnly = false) =>
    http.get<any, NotificationListResult>('/notifications', { params: { unreadOnly } }),
  markRead: (id: string) => http.patch<any, NotificationItem>(`/notifications/${id}/read`),
};
