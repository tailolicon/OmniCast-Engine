import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { Badge, Button, Card, ErrorBox, Spinner, Stat } from '../components/ui';
import { RingGauge } from '../components/RingGauge';

export function Home() {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ['status'], queryFn: api.status, refetchInterval: 5000 });
  const sys = useQuery({ queryKey: ['system'], queryFn: api.systemState, refetchInterval: 4000 });

  const paused = sys.data?.data.paused ?? false;
  const toggle = useMutation({
    mutationFn: () => (paused ? api.resume() : api.pause()),
    onSettled: () => qc.invalidateQueries({ queryKey: ['system'] }),
  });

  if (status.isPending) return <Spinner />;
  if (status.isError) return <ErrorBox message={(status.error as Error).message} />;

  const k = status.data.kpis;
  const spendPct = k.daily_cap_usd > 0 ? Math.min(100, (k.daily_spend_usd / k.daily_cap_usd) * 100) : 0;

  return (
    <div className="flex flex-col gap-3">
      {/* Kill-switch */}
      <Card className="flex items-center justify-between gap-3">
        <div className="flex flex-col gap-1">
          <span className="font-display text-lg font-bold" style={{ color: 'var(--heading)' }}>
            {paused ? 'Pipeline đang TẠM DỪNG' : 'Pipeline đang chạy'}
          </span>
          <Badge tone={paused ? 'red' : 'green'}>
            <span className={`inline-block h-2 w-2 rounded-full pulse-dot`} style={{ background: 'currentColor' }} />
            {paused ? 'PAUSED' : 'LIVE'}
          </Badge>
        </div>
        <Button
          tone={paused ? 'green' : 'red'}
          disabled={toggle.isPending || sys.isPending}
          onClick={() => {
            if (paused || window.confirm('Tạm dừng toàn bộ pipeline?')) toggle.mutate();
          }}
        >
          {paused ? '▶ Chạy lại' : '⏸ Dừng'}
        </Button>
      </Card>

      {/* KPI */}
      <div className="grid grid-cols-2 gap-3">
        <Stat label="Kênh" value={k.total_channels} tone="purple" icon={<span>📺</span>} />
        <Stat label="Job đang chạy" value={k.active_runs} tone="blue" icon={<span>⚙️</span>} />
        <Stat label="Script duyệt hôm nay" value={k.scripts_approved_today} tone="green" icon={<span>✅</span>} />
        <Stat label="Niche tìm được" value={status.data.system.niches_discovered} tone="amber" icon={<span>🔎</span>} />
      </div>

      {/* Chi tiêu ngày — gauge bong bóng nước (màn "0%" bộ 鱼塘) */}
      <Card className="flex flex-col items-center py-5">
        <RingGauge pct={spendPct} danger={spendPct > 80}>
          <span className="stat-value text-4xl">{Math.round(spendPct)}%</span>
          <span className="text-[11px] font-semibold" style={{ color: 'var(--text3)' }}>ngân sách ngày</span>
        </RingGauge>
        <div className="mt-3 flex flex-col items-start gap-1 text-xs font-semibold" style={{ color: 'var(--text2)' }}>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: 'var(--green)' }} />
            Đã chi hôm nay: ${k.daily_spend_usd.toFixed(2)}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: 'var(--fish-coral)' }} />
            Hạn mức ngày: ${k.daily_cap_usd.toFixed(0)}
          </span>
        </div>
      </Card>

      {/* Hoạt động gần đây */}
      <Card>
        <div className="mb-2 font-display font-bold" style={{ color: 'var(--heading)' }}>Hoạt động gần đây ✨</div>
        {status.data.recent_activity.length === 0 && (
          <div className="text-sm" style={{ color: 'var(--text3)' }}>Chưa có hoạt động nào.</div>
        )}
        <div className="flex flex-col gap-2">
          {status.data.recent_activity.map((a, i) => (
            <div key={i} className="bubble px-3 py-2 text-xs">
              <span className="font-semibold" style={{ color: 'var(--text)' }}>
                {String(a.channel_id ?? a.channel ?? '—')}
              </span>{' '}
              <span style={{ color: 'var(--text2)' }}>
                {String(a.topic ?? a.title ?? a.status ?? '')}
              </span>
              {a.score !== undefined && <Badge tone="purple">{String(a.score)}đ</Badge>}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
