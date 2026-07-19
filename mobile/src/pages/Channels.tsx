import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, type ChannelCard } from '../api';
import { Badge, Button, Card, ErrorBox, Spinner } from '../components/ui';
import { Fish } from '../components/PondScene';

/* Mỗi kênh = 1 con cá trong ao (concept 鱼塘) */
const FISH_COLORS = ['var(--fish-coral)', 'var(--fish-mustard)', 'var(--fish-blue)', 'var(--purple)', 'var(--green)', 'var(--amber)'];

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function LogViewer({ channelId }: { channelId: string }) {
  const log = useQuery({
    queryKey: ['log', channelId],
    queryFn: () => api.runLog(channelId),
    refetchInterval: 3000,
  });
  const events = log.data?.events ?? [];
  return (
    <div
      className="log-box mt-2 max-h-48 overflow-y-auto rounded-xl border-2 p-2"
      style={{ borderColor: 'var(--border-soft)', background: 'var(--surface2)', color: 'var(--text2)' }}
    >
      {events.length === 0 ? 'Chưa có log…' : events.slice(-40).map((e, i) => (
        <div key={i}>{String(e.msg ?? JSON.stringify(e))}</div>
      ))}
    </div>
  );
}

function ChannelRow({ ch, index }: { ch: ChannelCard; index: number }) {
  const qc = useQueryClient();
  const [showLog, setShowLog] = useState(false);
  const running = ch.status === 'running' || ch.status === 'active';
  const displayName = ch.name || ch.channel_id || '?';

  const run = useMutation({
    mutationFn: () => api.runChannel(ch.channel_id),
    onSettled: () => qc.invalidateQueries({ queryKey: ['channels'] }),
  });
  const cancel = useMutation({
    mutationFn: () => api.cancelRun(ch.channel_id),
    onSettled: () => qc.invalidateQueries({ queryKey: ['channels'] }),
  });

  return (
    <Card>
      <div className="flex items-center gap-3">
        <div
          className="sticker-sm flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden"
          style={{ background: 'var(--surface2)' }}
        >
          {ch.avatar_url
            ? <img src={ch.avatar_url} alt="" className="h-full w-full object-cover" />
            : <span className={running ? 'bob inline-flex' : 'inline-flex'}><Fish color={FISH_COLORS[index % FISH_COLORS.length]} size={32} /></span>}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate font-display font-bold" style={{ color: 'var(--heading)' }}>
            {displayName}
          </div>
          <div className="flex flex-wrap items-center gap-1.5 text-[11px]" style={{ color: 'var(--text2)' }}>
            {ch.niche && <span className="truncate">{ch.niche}</span>}
            {running ? <Badge tone="blue">đang chạy</Badge> : <Badge tone="muted">{ch.status || 'idle'}</Badge>}
            {ch.linked && <Badge tone="green">YT ✓</Badge>}
          </div>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
        {[
          ['Views', fmt(ch.total_views)],
          ['Subs', fmt(ch.subscribers)],
          ['Video', fmt(ch.video_count)],
        ].map(([label, val]) => (
          <div key={label} className="rounded-xl py-1.5" style={{ background: 'var(--surface2)' }}>
            <div className="stat-value text-base">{val}</div>
            <div className="text-[10px] font-semibold" style={{ color: 'var(--text3)' }}>{label}</div>
          </div>
        ))}
      </div>

      <div className="mt-3 flex gap-2">
        {running ? (
          <Button tone="red" small full disabled={cancel.isPending}
            onClick={() => window.confirm(`Hủy job của "${displayName}"?`) && cancel.mutate()}>
            ⛔ Hủy job
          </Button>
        ) : (
          <Button tone="green" small full disabled={run.isPending} onClick={() => run.mutate()}>
            ▶ Chạy pipeline
          </Button>
        )}
        <Button tone="purple" small onClick={() => setShowLog(v => !v)}>
          {showLog ? '▲' : '📜'} Log
        </Button>
      </div>
      {run.isError && <div className="mt-1 text-xs" style={{ color: 'var(--red)' }}>{(run.error as Error).message}</div>}
      {showLog && <LogViewer channelId={ch.channel_id} />}
    </Card>
  );
}

export function Channels() {
  const q = useQuery({ queryKey: ['channels'], queryFn: api.channelsOverview, refetchInterval: 10000 });

  if (q.isPending) return <Spinner />;
  if (q.isError) return <ErrorBox message={(q.error as Error).message} />;

  const t = q.data.totals;
  return (
    <div className="flex flex-col gap-3">
      <Card className="flex items-center justify-around text-center">
        {[
          ['📺', t.channels, 'kênh'],
          ['👀', fmt(t.views), 'views'],
          ['💚', fmt(t.subscribers), 'subs'],
          ['💰', `$${t.est_revenue_usd}`, 'doanh thu'],
        ].map(([icon, val, label]) => (
          <div key={String(label)}>
            <div className="text-sm">{icon}</div>
            <div className="stat-value text-lg">{val}</div>
            <div className="text-[10px] font-semibold" style={{ color: 'var(--text3)' }}>{label}</div>
          </div>
        ))}
      </Card>
      {q.data.channels.map((ch, i) => (
        <div key={ch.channel_id || i} className="rise" style={{ animationDelay: `${80 + i * 70}ms` }}>
          <ChannelRow ch={ch} index={i} />
        </div>
      ))}
      {q.data.channels.length === 0 && (
        <Card className="text-center text-sm" style={{ color: 'var(--text3)' }}>Chưa có kênh nào.</Card>
      )}
    </div>
  );
}
