import React, { useState } from 'react';
import { useApi, useInvalidate } from '../api/hooks';
import { apiPost } from '../api/client';
import {
  KPI,
  Card,
  CardHeader,
  CardTitle,
  CardSub,
  Skeleton,
  EmptyState,
  Button,
  ConfirmModal,
  StatusTag
} from '../components/ui';
import { Play, Activity, Check, ShieldAlert, RefreshCw, Clock } from 'lucide-react';

// Formatter for elapsed seconds
const formatDur = (s?: number) => {
  if (s == null) return '—';
  if (s >= 60) {
    return `${Math.floor(s / 60)}m ${s % 60}s`;
  }
  return `${s}s`;
};

interface StepState {
  label: string;
  status: 'done' | 'active' | 'waiting' | 'error';
}

const getStepsState = (activeJob: any): StepState[] => {
  const steps: StepState[] = [
    { label: 'Discovery', status: 'waiting' },
    { label: 'Script', status: 'waiting' },
    { label: 'Render', status: 'waiting' },
    { label: 'Duyệt', status: 'waiting' },
  ];

  if (!activeJob) return steps;

  const stage = (activeJob.stage || activeJob.phase || '').toLowerCase();
  const jobStatus = (activeJob.status || '').toLowerCase();

  let currentStepIdx = -1;
  if (stage.includes('niche') || stage.includes('discover') || stage.includes('explore') || stage.includes('competitor')) {
    currentStepIdx = 0;
  } else if (stage.includes('script') || stage.includes('generate_script') || stage === 'waiting_edit') {
    currentStepIdx = 1;
  } else if (stage.includes('render') || stage.includes('image') || stage.includes('active')) {
    currentStepIdx = 2;
  } else if (stage.includes('publish') || stage.includes('upload') || stage.includes('approval')) {
    currentStepIdx = 3;
  }

  if (currentStepIdx === -1) {
    const pct = activeJob.progress_pct || 0;
    if (pct < 25) currentStepIdx = 0;
    else if (pct < 50) currentStepIdx = 1;
    else if (pct < 80) currentStepIdx = 2;
    else currentStepIdx = 3;
  }

  for (let i = 0; i < 4; i++) {
    if (i < currentStepIdx) {
      steps[i].status = 'done';
    } else if (i === currentStepIdx) {
      if (jobStatus === 'failed') {
        steps[i].status = 'error';
      } else {
        steps[i].status = 'active';
      }
    } else {
      steps[i].status = 'waiting';
    }
  }

  if (jobStatus === 'success') {
    steps.forEach(s => s.status = 'done');
  }

  return steps;
};

const PipelineStepsChecklist: React.FC<{ activeJob: any }> = ({ activeJob }) => {
  const steps = getStepsState(activeJob);
  if (!activeJob) return null;

  return (
    <div className="flex items-center gap-3 p-3 border-2 border-[var(--ink)] rounded-[var(--radius-card)] overflow-x-auto scrollbar-none justify-between flex-wrap" style={{ background: 'var(--surface-gradient)', boxShadow: 'var(--shadow-hard-sm)' }}>
      <div className="flex items-center gap-2">
        <span className="text-[10px] uppercase font-bold tracking-wider text-[var(--text3)]">Pipeline ({activeJob.channel_id}):</span>
        <span className="text-xs font-semibold text-[var(--heading)] font-mono truncate max-w-[250px]" title={activeJob.current_topic || activeJob.topic}>
          {activeJob.current_topic || activeJob.topic || 'Đang xử lý...'}
        </span>
      </div>
      <div className="flex items-center gap-4 max-md:mt-2">
        {steps.map((s, idx) => {
          const statusConfig = {
            done: { icon: '✓', color: 'text-white font-bold', bg: 'bg-[var(--green)] border-[1.5px] border-[var(--ink)]' },
            active: { icon: '▶', color: 'text-white font-bold', bg: 'bg-[var(--accent)] border-[1.5px] border-[var(--ink)] animate-pulse' },
            waiting: { icon: '○', color: 'text-[var(--text3)]', bg: 'bg-[var(--surface2)] border-[1.5px] border-[var(--ink)]' },
            error: { icon: '✗', color: 'text-white font-bold', bg: 'bg-[var(--red)] border-[1.5px] border-[var(--ink)]' }
          };
          const cfg = statusConfig[s.status];
          return (
            <div key={idx} className="flex items-center gap-1.5 text-xs">
              <span className={`w-5 h-5 rounded-full flex items-center justify-center font-mono text-[10px] ${cfg.color} ${cfg.bg}`}>
                {cfg.icon}
              </span>
              <span className={`font-semibold ${s.status === 'active' ? 'text-[var(--heading)]' : 'text-[var(--text2)]'}`}>
                {idx + 1}. {s.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export const Dashboard: React.FC = () => {
  const invalidate = useInvalidate();
  const [restartChannelId, setRestartChannelId] = useState<string | null>(null);

  // Queries
  const { data: statusData, isLoading: isStatusLoading } = useApi<any>('/api/status');
  const { data: pipelineData, isLoading: isPipelineLoading } = useApi<any>('/api/pipeline');
  const { data: channelsData, isLoading: isChannelsLoading } = useApi<any>('/api/channels');
  const { data: errorsData, isLoading: isErrorsLoading } = useApi<any>('/api/errors?limit=30');
  const { data: overviewData } = useApi<any>('/api/channels/overview');

  // Channel helper resolver
  const chName = (id: string) => {
    const chs = channelsData?.channels || [];
    const c = chs.find((x: any) => x.channel_id === id);
    return c ? c.name : id;
  };

  // Calculations for KPIs
  const kpis = statusData?.kpis || {};
  const sys = statusData?.system || {};
  const activeJobs = pipelineData?.active_jobs || [];

  const spend = typeof kpis.daily_spend_usd === 'number' ? kpis.daily_spend_usd : 0;
  const cap = typeof kpis.daily_cap_usd === 'number' ? kpis.daily_cap_usd : 100;
  const spendPct = Math.min(100, Math.round((spend / (cap || 1)) * 100));

  const kRunning = kpis.active_runs != null ? kpis.active_runs : activeJobs.length;
  const kScripts = kpis.scripts_approved_today != null ? kpis.scripts_approved_today : 0;
  const kChannels = kpis.total_channels != null ? kpis.total_channels : (channelsData?.channels || []).length;
  const kNiches = sys.niches_discovered != null ? sys.niches_discovered : 0;

  // Process activities list
  const recentActivities = (statusData?.recent_activity || []).slice(0, 5).map((act: any) => ({
    ch: chName(act.channel_id),
    phase: act.phase || '',
    score: act.score ? act.score : null,
    status: act.status === 'completed' ? 'success' : act.status === 'failed' ? 'failed' : 'running',
  }));

  // Handle Restart Action
  const handleRestartPipeline = async () => {
    if (!restartChannelId) return;
    try {
      await apiPost(`/api/run/${restartChannelId}`);
      invalidate('/api/pipeline');
      invalidate('/api/status');
    } catch (e) {
      console.error(e);
    }
  };

  // Loading state
  const isLoading = isStatusLoading || isPipelineLoading || isChannelsLoading || isErrorsLoading;

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <Skeleton h="100px" />
          <Skeleton h="100px" />
          <Skeleton h="100px" />
          <Skeleton h="100px" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Skeleton h="200px" />
          <Skeleton h="200px" />
        </div>
        <Skeleton h="150px" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <h2 className="disp text-2xl font-extrabold text-[var(--heading)]" style={{ textShadow: '0 0 18px rgba(244,95,206,.30)' }}>
          Bảng điều khiển <span className="text-[15px] tracking-[3px] text-[var(--accent)]" style={{ textShadow: '0 0 10px rgba(244,95,206,.65)' }}>⋆｡˚✧</span>
        </h2>
        <p className="text-xs text-[var(--text2)]">Tổng quan hệ thống sản xuất nội dung OmniCast Engine</p>
      </div>

      {/* BS-3 Smart alert: spike in errors within the last hour */}
      {(() => {
        const errs: any[] = errorsData?.errors || [];
        const now = Date.now();
        const recent = errs.filter((e) => { const t = Date.parse(e.timestamp); return !!t && now - t < 3600000; });
        if (recent.length < 5) return null;
        return (
          <div className="flex items-center gap-3 p-3 rounded-xl border border-[var(--red)] bg-[var(--red-soft)] text-[var(--red)]">
            <ShieldAlert size={18} className="shrink-0" />
            <div className="text-sm font-semibold">Cảnh báo: {recent.length} lỗi trong 1 giờ qua — tỷ lệ lỗi tăng bất thường. Mở chuông lỗi hoặc tab Hệ thống để kiểm tra.</div>
          </div>
        );
      })()}

      {/* Active Pipelines step-checklist (UI-A) */}
      {activeJobs.length > 0 && (
        <div className="space-y-3">
          {activeJobs.map((job: any) => (
            <PipelineStepsChecklist key={job.job_id} activeJob={job} />
          ))}
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {/* KPI 1: Active pipelines */}
        <KPI
          label="Đang chạy"
          value={kRunning}
          icon={<Play size={16} className="text-[var(--amber)]" />}
          sub={
            <div className="flex items-center gap-1.5 text-xs text-[var(--text2)]">
              {kRunning > 0 && <span className="w-1.5 h-1.5 bg-[var(--amber)] rounded-full animate-ping"></span>}
              <span>{kRunning} pipeline active</span>
            </div>
          }
        />
        {/* KPI 2: Scripts generated today */}
        <KPI
          label="Script hôm nay"
          value={kScripts}
          icon={<Activity size={16} className="text-[var(--blue)]" />}
          sub={<span className="text-[var(--text2)]">chất lượng score ≥ 70</span>}
        />
        {/* KPI 3: Today's Spend */}
        <KPI
          label="Chi phí hôm nay"
          value={`$${spend.toFixed(2)}`}
          icon={<DollarSignIcon />}
          sub={
            <div className="space-y-1.5 w-full">
              <div className="h-1.5 bg-[var(--surface2)] rounded-full overflow-hidden w-full">
                <div className="h-full bg-[var(--amber)] rounded-full" style={{ width: `${spendPct}%` }} />
              </div>
              <div className="flex justify-between text-[10px] text-[var(--text2)]">
                <span>Spend limit: ${cap}</span>
                <span>{spendPct}%</span>
              </div>
            </div>
          }
        />
        {/* KPI 4: Channels count */}
        <KPI
          label="Kênh"
          value={kChannels}
          icon={<TvIcon />}
          sub={<span className="text-[var(--text2)]">{kNiches} ngách được phát hiện</span>}
        />
      </div>

      {/* Số liệu kênh thật (từ /api/channels/overview) */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Lượt xem YouTube (tổng)</CardTitle>
              <CardSub>Số thật từ YouTube Data API — cập nhật khi bấm "Cập nhật số liệu" ở tab Kênh</CardSub>
            </div>
          </CardHeader>
          <div>
            <div className="flex justify-between items-baseline">
              <span className="disp text-[26px] font-extrabold font-mono text-[var(--heading)]" style={{ textShadow: '0 0 14px rgba(168,119,255,.32)' }}>
                {Number(overviewData?.totals?.views || 0).toLocaleString()} views
              </span>
              <span className="text-xs text-[var(--text2)] font-mono">
                {overviewData?.totals?.videos || 0} video · {Number(overviewData?.totals?.subscribers || 0).toLocaleString()} sub
              </span>
            </div>
            {!(overviewData?.totals?.views) && (
              <div className="mt-3 text-[11px] text-[var(--text3)]">
                Chưa có lượt xem — biểu đồ theo ngày sẽ xuất hiện sau khi video đầu tiên được đăng và có dữ liệu analytics.
              </div>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Doanh thu ước tính</CardTitle>
              <CardSub>YouTube ước tính + affiliate đã ghi nhận — số thật, không dự phóng</CardSub>
            </div>
          </CardHeader>
          <div>
            <div className="flex justify-between items-baseline">
              <span className="disp text-[26px] font-extrabold font-mono text-[var(--green-ink)]" style={{ textShadow: '0 0 14px rgba(34,201,168,.35)' }}>
                ${Number(overviewData?.totals?.est_revenue_usd || 0).toFixed(2)}
              </span>
              <span className="text-xs text-[var(--text2)] font-mono">
                {overviewData?.totals?.linked || 0}/{overviewData?.totals?.channels || 0} kênh đã liên kết YouTube
              </span>
            </div>
            {!(overviewData?.totals?.est_revenue_usd) && (
              <div className="mt-3 text-[11px] text-[var(--text3)]">
                Chưa có doanh thu — cần video đăng public + bật kiếm tiền (xem tab Kiếm tiền → Readiness).
              </div>
            )}
          </div>
        </Card>
      </div>

      {/* Main Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Active Pipelines */}
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Pipeline đang chạy</CardTitle>
              <CardSub>Real-time job status</CardSub>
            </div>
          </CardHeader>
          
          {activeJobs.length === 0 ? (
            <EmptyState
              icon={<Play size={32} />}
              title="Không có pipeline nào đang chạy"
              desc='Bấm "Full Run Pipeline" ở tab Văn phòng hoặc chạy từng phase ở tab Kênh.'
            />
          ) : (
            <div className="divide-y divide-[var(--border-soft)] max-h-96 overflow-y-auto">
              {activeJobs.map((j: any, i: number) => {
                const stage = (j.phase || 'pipeline') + (j.current_topic ? ` · ${j.current_topic}` : '');
                const pct = typeof j.progress_pct === 'number' ? j.progress_pct : 0;
                const elapsed = formatDur(j.elapsed_seconds);
                const eta = j.eta_seconds != null ? `~${formatDur(j.eta_seconds)}` : '—';
                return (
                  <div key={i} className="py-3 first:pt-0 last:pb-0">
                    <div className="flex items-center justify-between gap-4 mb-2">
                      <div className="flex items-center gap-2">
                        <span className="w-1.5 h-1.5 bg-[var(--amber)] rounded-full animate-ping"></span>
                        <span className="font-semibold text-sm text-[var(--heading)]">{chName(j.channel_id)}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="!py-0.5 !px-2 border-[1.5px] border-[var(--ink)]"
                          onClick={() => setRestartChannelId(j.channel_id)}
                        >
                          <RefreshCw size={10} />
                          <span>Khởi động lại</span>
                        </Button>
                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-[var(--amber-soft)] text-[var(--amber)]">
                          <Clock size={10} />
                          {elapsed} · ETA {eta}
                        </span>
                      </div>
                    </div>
                    <div className="text-[var(--blue)] text-xs font-semibold mb-2">{stage}</div>
                    <div className="h-2 bg-[var(--surface2)] rounded-full overflow-hidden w-full">
                      <div className="h-full bg-[var(--blue)] rounded-full transition-all duration-300" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Card>

        {/* Recent Activities */}
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Hoạt động gần đây</CardTitle>
              <CardSub>Lịch sử chạy gần nhất</CardSub>
            </div>
          </CardHeader>
          
          {recentActivities.length === 0 ? (
            <EmptyState
              icon={<Activity size={32} />}
              title="Chưa có hoạt động nào"
              desc="Lịch sử chạy của hệ thống sẽ xuất hiện ở đây."
            />
          ) : (
            <div className="divide-y divide-[var(--border-soft)] max-h-96 overflow-y-auto">
              {recentActivities.map((act: any, i: number) => (
                <div key={i} className="flex items-center justify-between py-3 first:pt-0 last:pb-0">
                  <div>
                    <span className="font-semibold text-sm text-[var(--heading)]">{act.ch}</span>
                    <span className="text-[var(--text2)] text-xs ml-2 font-mono">{act.phase}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {act.score && (
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-[var(--blue-soft)] text-[var(--blue)]">
                        {act.score} pts
                      </span>
                    )}
                    <StatusTag status={act.status} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* Recent Errors Log */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Lỗi hệ thống gần đây</CardTitle>
            <CardSub>Lỗi ghi nhận từ các tiến trình của agent</CardSub>
          </div>
        </CardHeader>

        {(!errorsData || errorsData.errors === undefined || errorsData.errors.length === 0) ? (
          <EmptyState
            icon={<Check size={32} className="text-[var(--green)]" />}
            title="Không có lỗi nào"
            desc="Hệ thống đang chạy sạch."
          />
        ) : (
          <div className="border-2 border-[var(--ink)] rounded-[14px] p-4 font-mono text-xs text-[var(--text2)] max-h-60 overflow-y-auto space-y-2.5" style={{ background: 'var(--surface3)' }}>
            {errorsData.errors.map((err: any, idx: number) => (
              <div key={idx} className="flex gap-3 leading-relaxed border-b border-[var(--border-soft)] pb-2 last:border-b-0 last:pb-0">
                <span className="text-[var(--red)] shrink-0 font-bold flex items-center gap-1">
                  <ShieldAlert size={12} />
                  <span>[ERROR]</span>
                </span>
                <div className="flex-1">
                  <div className="flex items-center justify-between text-[var(--text3)] text-[10px] mb-0.5">
                    <span className="font-bold text-[var(--text2)]">{err.module || 'System'}</span>
                    <span>{err.timestamp}</span>
                  </div>
                  <div className="text-[var(--text)] break-all">{err.message}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Restart Pipeline Confirm Modal */}
      <ConfirmModal
        isOpen={restartChannelId !== null}
        onClose={() => setRestartChannelId(null)}
        onConfirm={handleRestartPipeline}
        title="Khởi động lại pipeline"
        desc="Khởi động lại pipeline cho kênh này từ đầu?"
      />
    </div>
  );
};

// Inline SVGs/Icons to remain completely dependency-free
const DollarSignIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-[var(--green)]">
    <line x1="12" y1="1" x2="12" y2="23"></line>
    <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path>
  </svg>
);

const TvIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-[var(--purple)]">
    <rect x="2" y="7" width="20" height="15" rx="2" ry="2"></rect>
    <polyline points="17 2 12 7 7 2"></polyline>
  </svg>
);
