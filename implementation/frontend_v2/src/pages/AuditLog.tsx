import React, { useState } from 'react';
import { useApi } from '../api/hooks';
import { Card, Table, THead, TBody, TR, TH, TD, Badge, Skeleton, EmptyState } from '../components/ui';
import { ScrollText } from 'lucide-react';

// BS-4 — Audit log: merge approvals + usage + jobengine events into one read-only
// timeline (khi · ai · hành động · đối tượng · kết quả). No new backend — joins
// three existing GET endpoints client-side. Field access is defensive because the
// three payloads have slightly different shapes.

interface Row {
  ts: string;
  actor: string;       // operator name or "system"
  isSystem: boolean;
  action: string;
  target: string;
  result: string;
  ok: boolean | null;
}

function firstStr(...vals: any[]): string {
  for (const v of vals) if (v !== undefined && v !== null && String(v).trim()) return String(v);
  return '';
}

export const AuditLog: React.FC = () => {
  const { data: apprData, isLoading: l1 } = useApi<any>('/api/approvals');
  const { data: usageData, isLoading: l2 } = useApi<any>('/api/usage');
  const { data: jobsData, isLoading: l3 } = useApi<any>('/jobengine/api/v1/jobs', { refetchInterval: 10000 });
  const [q, setQ] = useState('');
  const [actorFilter, setActorFilter] = useState<'all' | 'operator' | 'system'>('all');

  const rows: Row[] = [];

  for (const a of (apprData?.approvals || [])) {
    const operator = firstStr(a.decided_by, a.operator, a.raw?.operator);
    const decision = firstStr(a.decision, a.status, 'chờ duyệt');
    rows.push({
      ts: firstStr(a.decided_at, a.updated_at, a.requested_at, a.created_at),
      actor: operator || 'system',
      isSystem: !operator,
      action: `Duyệt: ${decision}`,
      target: firstStr(a.title, a.video_id, a.channel_id, a.slug),
      result: firstStr(a.publish_error) ? 'Lỗi' : decision,
      ok: firstStr(a.publish_error) ? false : (decision === 'approve' || decision === 'approved' ? true : null),
    });
  }

  for (const u of (usageData?.usage || [])) {
    rows.push({
      ts: firstStr(u.created_at, u.time, u.ts),
      actor: 'system',
      isSystem: true,
      action: `Usage: ${firstStr(u.provider, u.kind, u.capability, 'call')}`,
      target: firstStr(u.model, u.channel_id, u.scope, u.video_id),
      result: u.cost_usd != null ? `$${Number(u.cost_usd).toFixed(4)}` : firstStr(u.units, ''),
      ok: null,
    });
  }

  const jobsList: any[] = Array.isArray(jobsData) ? jobsData : (jobsData?.jobs || []);
  for (const j of jobsList) {
    const status = firstStr(j.status, 'unknown');
    rows.push({
      ts: firstStr(j.updated_at, j.created_at, j.finished_at),
      actor: 'system',
      isSystem: true,
      action: `Job: ${firstStr(j.type, j.step, 'render')}`,
      target: firstStr(j.channel_id, j.job_id).slice(0, 24),
      result: status,
      ok: status === 'success' ? true : status === 'failed' ? false : null,
    });
  }

  const parsed = rows
    .map((r) => ({ ...r, t: Date.parse(r.ts) || 0 }))
    .filter((r) => actorFilter === 'all' || (actorFilter === 'system' ? r.isSystem : !r.isSystem))
    .filter((r) => !q || (r.actor + r.action + r.target + r.result).toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => b.t - a.t)
    .slice(0, 300);

  const loading = l1 || l2 || l3;

  return (
    <div className="space-y-4">
      <div>
        <h2 className="disp text-2xl font-extrabold text-[var(--heading)]" style={{ textShadow: '0 0 18px rgba(244,95,206,.30)' }}>
          Nhật ký kiểm toán <span className="text-[15px] tracking-[3px] text-[var(--accent)]" style={{ textShadow: '0 0 10px rgba(244,95,206,.65)' }}>⋆｡˚✧</span>
        </h2>
        <p className="text-xs text-[var(--text2)]">Gộp duyệt · usage · job — ai làm gì, khi nào, kết quả (read-only)</p>
      </div>

      <Card className="!p-4">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="🔍 Tìm actor/hành động/đối tượng…"
            className="flex-1 min-w-[200px] bg-[var(--surface)] border-2 border-[var(--ink)] focus:border-[var(--accent)] rounded-[10px] px-3 py-1.5 text-sm outline-none" />
          {(['all', 'operator', 'system'] as const).map((f) => (
            <button key={f} onClick={() => setActorFilter(f)}
              className={`px-3.5 py-1.5 rounded-full text-xs font-bold cursor-pointer border-2 transition-colors ${actorFilter === f ? 'bg-[var(--surface)] border-[var(--ink)] text-[var(--accent)]' : 'border-transparent text-[var(--text2)] hover:text-[var(--accent)]'}`}>
              {f === 'all' ? 'Tất cả' : f === 'operator' ? 'Người' : 'Hệ thống'}
            </button>
          ))}
          <span className="text-xs text-[var(--text3)] ml-auto">{parsed.length} dòng</span>
        </div>

        {loading ? <Skeleton h="200px" /> : parsed.length === 0 ? (
          <EmptyState icon={<ScrollText size={32} />} title="Chưa có sự kiện nào"
            desc="Nhật ký xuất hiện sau khi có duyệt, usage hoặc job chạy qua hệ thống." />
        ) : (
          <Table className="text-xs">
            <THead><TR><TH>Thời gian</TH><TH>Ai</TH><TH>Hành động</TH><TH>Đối tượng</TH><TH className="text-right">Kết quả</TH></TR></THead>
            <TBody>
              {parsed.map((r, i) => (
                <TR key={i}>
                  <TD className="font-mono text-[10px] text-[var(--text2)] whitespace-nowrap">{r.ts ? r.ts.replace('T', ' ').slice(0, 19) : '—'}</TD>
                  <TD><Badge variant={r.isSystem ? 'neutral' : 'purple'}>{r.actor}</Badge></TD>
                  <TD className="font-semibold">{r.action}</TD>
                  <TD className="max-w-[220px] truncate text-[var(--text2)]" title={r.target}>{r.target || '—'}</TD>
                  <TD className="text-right">
                    <span className={r.ok === true ? 'text-[var(--green)]' : r.ok === false ? 'text-[var(--red)]' : 'text-[var(--text2)]'}>{r.result || '—'}</span>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </div>
  );
};
