import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { Badge, Card, ErrorBox, GoalBar, Spinner } from '../components/ui';

export function Budgets() {
  const budgets = useQuery({ queryKey: ['budgets'], queryFn: api.budgets, refetchInterval: 15000 });
  const usage = useQuery({ queryKey: ['usage'], queryFn: api.usage, refetchInterval: 15000 });

  if (budgets.isPending) return <Spinner />;
  if (budgets.isError) return <ErrorBox message={(budgets.error as Error).message} />;

  const totalSpent = budgets.data.usage_total_usd ?? 0;

  return (
    <div className="flex flex-col gap-3">
      <Card className="text-center">
        <div className="text-xs font-semibold" style={{ color: 'var(--text2)' }}>Tổng đã chi</div>
        <div className="stat-value text-4xl" style={{ color: 'var(--green-ink)' }}>
          ${totalSpent.toFixed(2)}
        </div>
        {usage.data && (
          <div className="mt-1 text-[11px]" style={{ color: 'var(--text3)' }}>
            {usage.data.usage.length} bản ghi usage
          </div>
        )}
      </Card>

      <div className="font-display font-bold" style={{ color: 'var(--heading)' }}>Hạn mức 💎</div>
      {budgets.data.budgets.length === 0 && (
        <Card className="text-sm" style={{ color: 'var(--text3)' }}>
          Chưa đặt hạn mức nào — đặt trong dashboard desktop.
        </Card>
      )}
      {budgets.data.budgets.map((b, i) => {
        const pct = b.limit_usd > 0 ? Math.min(100, (totalSpent / b.limit_usd) * 100) : 0;
        return (
          <Card key={i}>
            <div className="flex items-center justify-between">
              <div className="font-display font-bold" style={{ color: 'var(--heading)' }}>
                {b.scope}{b.scope_id !== 'default' ? ` · ${b.scope_id}` : ''}
              </div>
              <Badge tone={pct > 80 ? 'red' : 'green'}>${b.limit_usd.toFixed(0)}</Badge>
            </div>
            <div className="mt-3">
              <GoalBar pct={pct} danger={pct > 80} label={`$${totalSpent.toFixed(0)}/$${b.limit_usd.toFixed(0)}`} />
            </div>
          </Card>
        );
      })}
    </div>
  );
}
