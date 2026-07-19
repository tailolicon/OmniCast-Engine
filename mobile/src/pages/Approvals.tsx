import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, type Approval } from '../api';
import { Badge, Button, Card, ErrorBox, Spinner } from '../components/ui';

function ApprovalRow({ a }: { a: Approval }) {
  const qc = useQueryClient();
  const decide = useMutation({
    mutationFn: (d: 'approve' | 'reject') => api.decideApproval(a.approval_id, d),
    onSettled: () => qc.invalidateQueries({ queryKey: ['approvals'] }),
  });

  return (
    <Card>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-display font-bold leading-snug" style={{ color: 'var(--heading)' }}>
            {a.title || a.video_id || a.approval_id}
          </div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {a.channel_id && <Badge tone="purple">{a.channel_id}</Badge>}
            {a.requested_at && (
              <span className="text-[10px]" style={{ color: 'var(--text3)' }}>
                {new Date(a.requested_at).toLocaleString('vi-VN')}
              </span>
            )}
          </div>
        </div>
        <span className="text-xl">💌</span>
      </div>
      {a.summary && (
        <p className="mt-2 text-xs leading-relaxed" style={{ color: 'var(--text2)' }}>{a.summary}</p>
      )}
      <div className="mt-3 flex gap-2">
        <Button tone="green" small full disabled={decide.isPending}
          onClick={() => window.confirm(`DUYỆT sẽ đăng video lên nền tảng. Tiếp tục?`) && decide.mutate('approve')}>
          ✅ Duyệt & đăng
        </Button>
        <Button tone="red" small full disabled={decide.isPending} onClick={() => decide.mutate('reject')}>
          ✖ Từ chối
        </Button>
      </div>
      {decide.isError && (
        <div className="mt-1 text-xs" style={{ color: 'var(--red)' }}>{(decide.error as Error).message}</div>
      )}
    </Card>
  );
}

export function Approvals() {
  const q = useQuery({ queryKey: ['approvals'], queryFn: api.approvals, refetchInterval: 8000 });

  if (q.isPending) return <Spinner />;
  if (q.isError) return <ErrorBox message={(q.error as Error).message} />;

  return (
    <div className="flex flex-col gap-3">
      {q.data.approvals.length === 0 ? (
        <Card className="py-8 text-center">
          <div className="bob inline-block text-4xl">🫧</div>
          <div className="mt-2 font-display font-bold" style={{ color: 'var(--heading)' }}>Không có gì chờ duyệt</div>
          <div className="text-xs" style={{ color: 'var(--text3)' }}>Video mới sẽ hiện ở đây trước khi đăng.</div>
        </Card>
      ) : (
        q.data.approvals.map((a, i) => (
          <div key={a.approval_id} className="rise" style={{ animationDelay: `${80 + i * 70}ms` }}>
            <ApprovalRow a={a} />
          </div>
        ))
      )}
    </div>
  );
}
