import { http } from './client';

export interface L1ReviewItem {
  id: string;
  pipelineKind: 'gate' | 'checkpoint' | 'sweep' | 'fetch_fail';
  pipelineRef: string;
  reason?: string | null;
  suggestedAction?: string | null;
  confidence?: number | null;
  evidence?: string | null;
  channel?: string | null;
  runLabel?: string | null;
  aiNarration?: string | null;
  aiNarratedAt?: string | null;
  verdict?: string | null;
  createdAt: string;
}

export const l1ReviewApi = {
  list: (kind?: string) => http.get<any, L1ReviewItem[]>('/l1-review', { params: { kind, pending: true } }),
  narrate: (id: string) => http.post<any, L1ReviewItem>(`/l1-review/${id}/narrate`),
  submitVerdict: (id: string, body: { verdict: string; note?: string; corrections?: any }) =>
    http.patch<any, L1ReviewItem>(`/l1-review/${id}/verdict`, body),
};
