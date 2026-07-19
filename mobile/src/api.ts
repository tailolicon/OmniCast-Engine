/** API client — base URL cấu hình được (backend FastAPI port 8767 trong LAN). */

const KEY = 'omnicast.server';

export function getBaseUrl(): string {
  return localStorage.getItem(KEY) ?? '';
}

export function setBaseUrl(url: string): void {
  localStorage.setItem(KEY, url.trim().replace(/\/+$/, ''));
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getBaseUrl()}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`HTTP ${res.status}${text ? ` — ${text.slice(0, 180)}` : ''}`);
  }
  return res.json() as Promise<T>;
}

const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });

/* ── Response types (khớp server.py) ── */

export interface StatusResponse {
  timestamp: string;
  system: { status: string; channels_total: number; active_jobs: number; niches_discovered: number };
  kpis: {
    scripts_approved_today: number;
    active_runs: number;
    daily_spend_usd: number;
    daily_cap_usd: number;
    total_channels: number;
  };
  recent_activity: Array<Record<string, unknown>>;
}

export interface Envelope<T> {
  data: T;
  source: string;
  fetched_at: string;
}

export interface SystemState {
  paused: boolean;
  paused_since: string | null;
  redis_available: boolean;
}

export interface ChannelCard {
  channel_id: string;
  name: string;
  niche?: string;
  status?: string;
  linked: boolean;
  avatar_url?: string;
  total_views: number;
  video_count: number;
  subscribers: number;
  est_revenue_usd: number;
  [k: string]: unknown;
}

export interface ChannelsOverview {
  totals: {
    channels: number;
    views: number;
    videos: number;
    subscribers: number;
    est_revenue_usd: number;
    linked: number;
  };
  channels: ChannelCard[];
}

export interface Approval {
  approval_id: string;
  job_id?: string;
  channel_id?: string;
  video_id?: string;
  title?: string;
  summary?: string;
  status: string;
  requested_at?: string;
  [k: string]: unknown;
}

export interface Budget {
  scope: string;
  scope_id: string;
  limit_usd: number;
  [k: string]: unknown;
}

export interface LogEvent {
  type?: string;
  msg?: string;
  ts?: string;
  [k: string]: unknown;
}

/* ── Endpoints ── */

export const api = {
  status: () => request<StatusResponse>('/api/status'),
  systemState: () => request<Envelope<SystemState>>('/api/system/state'),
  pause: () => post('/api/system/pause', { operator: 'mobile' }),
  resume: () => post('/api/system/resume', { operator: 'mobile' }),

  channelsOverview: () => request<ChannelsOverview>('/api/channels/overview'),
  runChannel: (id: string) => post<{ status: string }>(`/api/run/${id}`),
  cancelRun: (id: string) => post<{ status: string }>(`/api/run/${id}/cancel`),
  runLog: (id: string) => request<{ events: LogEvent[] }>(`/api/run/${id}/log`),

  approvals: () => request<{ approvals: Approval[]; total: number }>('/api/approvals'),
  decideApproval: (id: string, decision: 'approve' | 'reject') =>
    post(`/api/approvals/${id}/${decision}`, {}),

  budgets: () => request<{ budgets: Budget[]; usage_total_usd: number }>('/api/budgets'),
  usage: () => request<{ usage: Array<Record<string, unknown>>; cost_usd: number }>('/api/usage'),
};
