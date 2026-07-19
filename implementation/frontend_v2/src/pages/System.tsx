import React, { useState, useEffect } from 'react';
import { useApi, useInvalidate } from '../api/hooks';
import { apiPost } from '../api/client';
import {
  Button, Card, CardHeader, CardTitle, CardSub, Skeleton, Input, Badge,
  Table, THead, TBody, TR, TH, TD, EmptyState, StatusTag
} from '../components/ui';
import {
  Shield, Cpu, RefreshCw, CheckCircle, AlertTriangle, Plug, Scale,
  ListChecks, Wallet, RotateCcw, KeyRound
} from 'lucide-react';

// --- Sub-tab: Providers (Capability registry + credential + test) ---
const ProvidersTab: React.FC = () => {
  const invalidate = useInvalidate();
  const { data: capData, isLoading } = useApi<any>('/api/capabilities');
  const { data: credData } = useApi<any>('/api/credentials');
  const { data: usageData } = useApi<any>('/api/usage');

  const capabilities: any[] = capData?.capabilities || [];
  const credentials: any[] = credData?.credentials || [];
  const usage: any[] = usageData?.usage || [];

  const [testing, setTesting] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, { ok: boolean; msg: string; at: string }>>({});
  const [formFor, setFormFor] = useState<string | null>(null);
  const [secret, setSecret] = useState('');
  const [accountId, setAccountId] = useState('default');
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  const byKind: Record<string, any[]> = {};
  for (const c of capabilities) (byKind[c.kind] = byKind[c.kind] || []).push(c);
  const kinds = Object.keys(byKind).sort();

  const hasCred = (pid: string) =>
    credentials.some((c) => c.provider === pid && (c.status || 'active') === 'active');
  const usageFor = (pid: string) => {
    const rows = usage.filter((u) => u.provider_id === pid);
    const cost = rows.reduce((s, u) => s + (Number(u.cost_usd) || 0), 0);
    return { count: rows.length, cost };
  };

  const runTest = async (kind: string, pid: string) => {
    const key = `${kind}:${pid}`;
    setTesting(key);
    try {
      const r = await apiPost<any>(`/api/capabilities/${encodeURIComponent(kind)}/${encodeURIComponent(pid)}/health`);
      setResults((prev) => ({
        ...prev,
        [key]: { ok: !!r.ok, msg: r.error || r.detail || (r.ok ? 'Kết nối OK' : 'Lỗi không rõ'), at: new Date().toLocaleTimeString() },
      }));
    } catch (e: any) {
      setResults((prev) => ({ ...prev, [key]: { ok: false, msg: String(e?.message || e), at: new Date().toLocaleTimeString() } }));
    } finally {
      setTesting(null);
    }
  };

  const saveCred = async (pid: string) => {
    setSaveMsg(null);
    try {
      await apiPost('/api/credentials', { provider: pid, account_id: accountId || 'default', secret, label: 'ui_v2' });
      setSaveMsg(`Đã lưu credential cho ${pid}`);
      setSecret('');
      setFormFor(null);
      invalidate('/api/credentials');
    } catch (e: any) {
      setSaveMsg(`Lỗi lưu credential: ${String(e?.message || e)}`);
    }
  };

  if (isLoading) return <div className="space-y-3"><Skeleton h="80px" /><Skeleton h="80px" /><Skeleton h="80px" /></div>;
  if (!capabilities.length) return (
    <EmptyState icon={<Plug size={32} />} title="Chưa có provider nào trong registry"
      desc="Registry nạp từ providers.manifest.yaml khi backend khởi động. Kiểm tra backend đã chạy đúng chưa." />
  );

  return (
    <div className="space-y-6">
      {saveMsg && (
        <div className="p-3 rounded-[12px] border-2 text-xs font-semibold bg-[var(--blue-soft)] border-[var(--blue)] text-[var(--blue)]">{saveMsg}</div>
      )}
      {kinds.map((kind) => (
        <div key={kind}>
          <div className="text-xs font-bold uppercase tracking-wide text-[var(--text3)] mb-2">{kind}</div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {byKind[kind].map((c) => {
              const key = `${kind}:${c.provider_id}`;
              const res = results[key];
              const u = usageFor(c.provider_id);
              const credOk = hasCred(c.provider_id);
              const requiresCred = !!(c.metadata && c.metadata.requires_credential);
              return (
                <Card key={c.capability_id} className="!p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="font-semibold text-sm text-[var(--heading)]">{c.provider_id}</div>
                      <div className="text-[11px] text-[var(--text3)] font-mono">{c.model_id || '—'}</div>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Badge variant={c.runtime === 'local' ? 'green' : c.runtime === 'browser' ? 'amber' : 'blue'}>{c.runtime}</Badge>
                      {requiresCred && (
                        <Badge variant={credOk ? 'green' : 'amber'}>{credOk ? 'Đã có key' : 'Chưa có key'}</Badge>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center justify-between mt-3 text-[11px] text-[var(--text2)]">
                    <span className="font-mono">${Number(c.cost_per_unit || 0).toFixed(4)}/unit · {u.count} usage · ${u.cost.toFixed(2)}</span>
                    <div className="flex items-center gap-2">
                      <Button variant="ghost" size="sm" onClick={() => { setFormFor(formFor === c.provider_id ? null : c.provider_id); setSecret(''); }}>
                        <KeyRound size={12} /> Key
                      </Button>
                      <Button variant="secondary" size="sm" disabled={testing === key} onClick={() => runTest(kind, c.provider_id)}>
                        <RefreshCw size={12} className={testing === key ? 'animate-spin' : ''} /> Test
                      </Button>
                    </div>
                  </div>
                  {res && (
                    <div className={`mt-2 p-2 rounded-[10px] border-2 text-[11px] flex items-center gap-2 ${
                      res.ok ? 'bg-[var(--green-soft)] border-[var(--green)] text-[var(--green)]'
                             : 'bg-[var(--red-soft)] border-[var(--red)] text-[var(--red)]'}`}>
                      {res.ok ? <CheckCircle size={12} /> : <AlertTriangle size={12} />}
                      <span className="break-all">{res.msg}</span>
                      <span className="ml-auto text-[var(--text3)] shrink-0">{res.at}</span>
                    </div>
                  )}
                  {formFor === c.provider_id && (
                    <div className="mt-3 pt-3 border-t-2 border-[var(--border-soft)] space-y-2">
                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <label className="text-[10px] font-semibold text-[var(--text2)]">Account ID</label>
                          <Input value={accountId} onChange={(e) => setAccountId(e.target.value)} placeholder="default" />
                        </div>
                        <div>
                          <label className="text-[10px] font-semibold text-[var(--text2)]">API key / secret</label>
                          <Input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder="sk-..." />
                        </div>
                      </div>
                      <div className="text-[10px] text-[var(--text3)]">
                        Secret được mã hóa trong vault, không hiển thị lại sau khi lưu. OAuth (YouTube): chạy
                        <code className="mx-1">scripts/youtube_authorize.py --channel &lt;id&gt;</code> thay vì nhập ở đây.
                      </div>
                      <div className="flex justify-end">
                        <Button variant="primary" size="sm" disabled={!secret} onClick={() => saveCred(c.provider_id)}>Lưu credential</Button>
                      </div>
                    </div>
                  )}
                </Card>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
};

// --- Sub-tab: Chinh sach (policy rules) ---
const PolicyTab: React.FC = () => {
  const invalidate = useInvalidate();
  const { data, isLoading } = useApi<any>('/api/policy');
  const [busy, setBusy] = useState<string | null>(null);

  const pending: any[] = data?.pending || [];
  const active: any[] = data?.active || [];
  const checks: any[] = data?.compliance_checks || [];
  const running = !!data?.policy_running;

  const act = async (ruleId: string, action: 'approve' | 'reject') => {
    setBusy(ruleId);
    try { await apiPost(`/api/policy/rules/${encodeURIComponent(ruleId)}/${action}`); invalidate('/api/policy'); }
    catch (e) {} finally { setBusy(null); }
  };
  const fetchNow = async () => {
    setBusy('__fetch__');
    try { await apiPost('/api/policy/fetch'); invalidate('/api/policy'); }
    catch (e) {} finally { setBusy(null); }
  };

  if (isLoading) return <div className="space-y-3"><Skeleton h="60px" /><Skeleton h="120px" /></div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="text-xs text-[var(--text2)]">
          Rules đang áp dụng được chèn vào prompt Writer + gate compliance trước khi đăng.
        </div>
        <Button variant="secondary" size="sm" onClick={fetchNow} disabled={busy === '__fetch__' || running}>
          <RefreshCw size={13} className={busy === '__fetch__' || running ? 'animate-spin' : ''} />
          {running ? 'Đang quét chính sách…' : 'Quét chính sách YouTube'}
        </Button>
      </div>

      {data?.last_scan && (
        <div className="p-3 bg-[var(--surface2)] border-[1.5px] border-[var(--border-soft)] rounded-[12px] text-xs flex flex-col gap-1">
          <div className="flex justify-between items-center text-[var(--text2)]">
            <span className="font-semibold text-[var(--text2)]">Lần quét chính sách gần nhất:</span>
            <span className="font-mono text-[var(--text3)]">
              {new Date(data.last_scan.last_scan_at).toLocaleString('vi-VN')}
            </span>
          </div>
          <div className="text-[var(--text)] font-semibold text-xs mt-1">
            Kết quả: <span className={data.last_scan.new_rules > 0 ? 'text-[var(--amber)] animate-pulse' : 'text-[var(--green)]'}>{data.last_scan.summary}</span>
          </div>
        </div>
      )}

      {pending.length > 0 && (
        <Card className="!p-4">
          <CardHeader className="!mb-3"><CardTitle>Rule mới chờ duyệt ({pending.length})</CardTitle>
            <CardSub>Policy watcher phát hiện thay đổi chính sách — duyệt để đưa vào gate</CardSub></CardHeader>
          <div className="space-y-2">
            {pending.map((r: any) => (
              <div key={r.rule_id || r.id} className="p-3 rounded-[12px] border-2 border-[var(--ink)] bg-[var(--amber-soft)] flex items-start justify-between gap-3">
                <div className="text-xs">
                  <div className="font-semibold text-[var(--heading)]">{r.title || r.rule_id || r.id}</div>
                  <div className="text-[var(--text2)] mt-0.5">{r.summary || r.description || ''}</div>
                </div>
                <div className="flex gap-2 shrink-0">
                  <Button variant="primary" size="sm" disabled={busy === (r.rule_id || r.id)} onClick={() => act(r.rule_id || r.id, 'approve')}>Duyệt</Button>
                  <Button variant="ghost" size="sm" disabled={busy === (r.rule_id || r.id)} onClick={() => act(r.rule_id || r.id, 'reject')}>Bỏ qua</Button>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Card className="!p-4">
          <CardHeader className="!mb-3"><CardTitle>Rules đang áp dụng ({active.length})</CardTitle></CardHeader>
          {active.length === 0 ? (
            <EmptyState icon={<Scale size={28} />} title="Chưa có rule động nào"
              desc="Bấm 'Quét chính sách YouTube' để fetch rules mới nhất vào vault." />
          ) : (
            <div className="space-y-1.5 max-h-80 overflow-y-auto pr-1">
              {active.map((r: any, i: number) => (
                <div key={i} className="p-2 rounded-[10px] bg-[var(--surface2)] text-[11px]">
                  <span className="font-semibold text-[var(--heading)]">{r.title || r.rule_id || `rule_${i}`}</span>
                  <span className="text-[var(--text2)] ml-2">{r.summary || r.description || ''}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
        <Card className="!p-4">
          <CardHeader className="!mb-3"><CardTitle>Gate cố định (ComplianceChecker)</CardTitle>
            <CardSub>Luôn chạy trước mọi lần đăng — không tắt được</CardSub></CardHeader>
          <div className="space-y-1.5">
            {checks.map((c: any) => (
              <div key={c.id} className="flex items-start gap-2 text-[11px] p-1.5">
                <CheckCircle size={12} className="text-[var(--green)] mt-0.5 shrink-0" />
                <div><span className="font-mono font-semibold">{c.id}</span>
                  <span className="text-[var(--text2)] ml-2">{c.desc}</span></div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
};

// --- Sub-tab: Jobs (JobEngine) ---
const JobsTab: React.FC = () => {
  const invalidate = useInvalidate();
  const { data: jobs, isLoading } = useApi<any[]>('/jobengine/api/v1/jobs', { refetchInterval: 5000 });
  const [retrying, setRetrying] = useState<string | null>(null);

  const list: any[] = Array.isArray(jobs) ? jobs : [];

  const retry = async (jobId: string) => {
    setRetrying(jobId);
    try { await apiPost(`/jobengine/api/v1/jobs/${encodeURIComponent(jobId)}/retry`); invalidate('/jobengine/api/v1/jobs'); }
    catch (e) {} finally { setRetrying(null); }
  };

  const mapStatus = (s: string): 'idle' | 'running' | 'success' | 'failed' =>
    s === 'running' ? 'running' : s === 'success' ? 'success' : s === 'failed' ? 'failed' : 'idle';

  if (isLoading) return <Skeleton h="200px" />;
  if (!list.length) return (
    <EmptyState icon={<ListChecks size={32} />} title="Chưa có job nào"
      desc="Job xuất hiện khi chạy render/pipeline qua JobEngine (checkpoint + slot GPU/CPU)." />
  );

  return (
    <Card className="!p-0 overflow-hidden">
      <Table className="text-xs">
        <THead><TR><TH>Job</TH><TH>Loại</TH><TH>Slot</TH><TH>Trạng thái</TH><TH>Tạo lúc</TH><TH>Lỗi</TH><TH className="text-right">Hành động</TH></TR></THead>
        <TBody>
          {list.map((j: any) => (
            <TR key={j.job_id}>
              <TD className="font-mono text-[10px]">{String(j.job_id).slice(0, 8)}</TD>
              <TD className="font-semibold">{j.type}</TD>
              <TD><Badge variant={j.resource_class === 'gpu' ? 'purple' : 'neutral'}>{j.resource_class}</Badge></TD>
              <TD><StatusTag status={mapStatus(j.status)} /></TD>
              <TD className="font-mono text-[10px] text-[var(--text2)]">{(j.created_at || '').replace('T', ' ').slice(0, 19)}</TD>
              <TD className="max-w-[260px] truncate text-[var(--red)]" title={j.error || ''}>{j.error || '—'}</TD>
              <TD className="text-right">
                {j.status === 'failed' && (
                  <Button variant="ghost" size="sm" disabled={retrying === j.job_id} onClick={() => retry(j.job_id)}>
                    <RotateCcw size={12} className={retrying === j.job_id ? 'animate-spin' : ''} /> Chạy lại
                  </Button>
                )}
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </Card>
  );
};

// --- Sub-tab: Ha tang (vault keys + infra that) ---
const InfraTab: React.FC = () => {
  const invalidate = useInvalidate();
  const [googleApiKey, setGoogleApiKey] = useState('');
  const [youtubeClientId, setYoutubeClientId] = useState('');
  const [youtubeClientSecret, setYoutubeClientSecret] = useState('');
  const [isHealthChecking, setIsHealthChecking] = useState(false);
  const [healthStatus, setHealthStatus] = useState<string | null>(null);

  const { data: vaultData, isLoading: isVaultLoading } = useApi<any>('/api/vault');
  const { data: infraData, isLoading: isInfraLoading } = useApi<any>('/api/infra');

  const db = infraData?.db || {};
  const redis = infraData?.redis || {};
  const workers: any[] = infraData?.workers || [];

  useEffect(() => {
    if (vaultData) {
      setGoogleApiKey(vaultData.google_api_key || '');
      setYoutubeClientId(vaultData.youtube_client_id || '');
      setYoutubeClientSecret(vaultData.youtube_client_secret || '');
    }
  }, [vaultData]);

  const handleSaveVault = async () => {
    try {
      await apiPost('/api/vault/save-all', {
        google_api_key: googleApiKey, youtube_client_id: youtubeClientId, youtube_client_secret: youtubeClientSecret,
      });
      invalidate('/api/vault');
    } catch (e) {}
  };
  const handleHealthCheck = async () => {
    setIsHealthChecking(true); setHealthStatus(null);
    try {
      const res = await apiPost<any>('/api/vault/health-check');
      setHealthStatus(res && res.status ? res.status : 'healthy');
      invalidate('/api/infra');
    } catch (e) { setHealthStatus('failed'); }
    finally { setIsHealthChecking(false); }
  };

  return (
    <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-stretch">
      <div className="xl:col-span-7 space-y-4">
        <Card className="flex flex-col justify-between h-full">
          <div>
            <CardHeader className="!mb-4">
              <div className="flex items-center gap-2"><Shield size={16} className="text-[var(--blue)]" /><CardTitle>Bảo mật API Keys (Vault)</CardTitle></div>
              <CardSub>Lưu trữ và mã hóa credentials Google Cloud & Gemini</CardSub>
            </CardHeader>
            {isVaultLoading ? (
              <div className="space-y-3"><Skeleton h="40px" /><Skeleton h="40px" /></div>
            ) : (
              <div className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-[var(--text2)]">Gemini / Google API Key</label>
                  <Input type="password" value={googleApiKey} onChange={(e) => setGoogleApiKey(e.target.value)} placeholder="AIzaSy..." />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-[var(--text2)]">YouTube Client ID (OAuth2)</label>
                  <Input value={youtubeClientId} onChange={(e) => setYoutubeClientId(e.target.value)} placeholder="*.apps.googleusercontent.com" />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-[var(--text2)]">YouTube Client Secret</label>
                  <Input type="password" value={youtubeClientSecret} onChange={(e) => setYoutubeClientSecret(e.target.value)} placeholder="GOCSPX-..." />
                </div>
              </div>
            )}
          </div>
          <div className="pt-4 border-t border-[var(--border-soft)] mt-6 flex items-center justify-between gap-3 flex-wrap">
            <Button variant="secondary" size="sm" onClick={handleHealthCheck} disabled={isHealthChecking}>
              <RefreshCw size={13} className={isHealthChecking ? 'animate-spin' : ''} /><span>Kiểm tra kết nối</span>
            </Button>
            <Button variant="primary" size="sm" onClick={handleSaveVault}>Lưu cấu hình</Button>
          </div>
        </Card>
      </div>

      <div className="xl:col-span-5 space-y-4">
        <Card className="h-full flex flex-col">
          <CardHeader className="!mb-4">
            <div className="flex items-center gap-2"><Cpu size={16} className="text-[var(--blue)]" /><CardTitle>Tình trạng hạ tầng</CardTitle></div>
            <CardSub>PostgreSQL · Redis · worker heartbeats (từ /api/infra)</CardSub>
          </CardHeader>
          {isInfraLoading ? (
            <div className="space-y-3"><Skeleton h="40px" /><Skeleton h="40px" /></div>
          ) : (
            <div className="space-y-4">
              {healthStatus && (
                <div className={`p-3 rounded-[12px] border-2 flex items-center gap-2.5 text-xs ${
                  healthStatus === 'healthy' || healthStatus === 'success'
                    ? 'bg-[var(--green-soft)] border-[var(--green)] text-[var(--green)]'
                    : 'bg-[var(--red-soft)] border-[var(--red)] text-[var(--red)]'}`}>
                  {healthStatus === 'healthy' || healthStatus === 'success' ? <CheckCircle size={14} /> : <AlertTriangle size={14} />}
                  <span className="font-semibold">{healthStatus === 'healthy' || healthStatus === 'success' ? 'Kết nối API hợp lệ' : 'Lỗi xác thực API Key'}</span>
                </div>
              )}
              <Table className="text-xs">
                <THead><TR><TH>Thành phần</TH><TH>Trạng thái</TH><TH>Chi tiết</TH></TR></THead>
                <TBody>
                  <TR>
                    <TD className="font-semibold">PostgreSQL</TD>
                    <TD><Badge variant={db.ok ? 'green' : 'red'}>{db.ok ? 'OK' : 'Lỗi'}</Badge></TD>
                    <TD className="font-mono text-[10px] max-w-[180px] truncate" title={db.error || ''}>{db.error || 'connected'}</TD>
                  </TR>
                  <TR>
                    <TD className="font-semibold">Redis</TD>
                    <TD><Badge variant={redis.ok ? 'green' : 'red'}>{redis.ok ? 'OK' : 'Lỗi'}</Badge></TD>
                    <TD className="font-mono text-[10px] max-w-[180px] truncate" title={redis.error || ''}>{redis.error || 'connected'}</TD>
                  </TR>
                  {workers.map((w: any, i: number) => (
                    <TR key={i}>
                      <TD className="font-semibold">{w.worker_id || `Worker ${i + 1}`}</TD>
                      <TD><Badge variant={w.status === 'healthy' ? 'green' : w.status === 'degraded' ? 'amber' : 'red'}>{w.status}</Badge></TD>
                      <TD className="font-mono text-[10px]">CPU {w.cpu_percent ?? '—'}% · RAM {w.ram_percent ?? '—'}%</TD>
                    </TR>
                  ))}
                  {workers.length === 0 && (
                    <TR><TD className="text-[var(--text3)]" colSpan={3}>Không có worker heartbeat (chạy single-machine — bình thường)</TD></TR>
                  )}
                </TBody>
              </Table>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
};

// --- Sub-tab: Chi phi (budgets + usage ledger) ---
const BudgetTab: React.FC = () => {
  const { data: budgetsData, isLoading } = useApi<any>('/api/budgets');
  const { data: usageData } = useApi<any>('/api/usage');
  const { data: quotaData } = useApi<any>('/api/quota', { refetchInterval: 60000 });

  const budgets: any[] = budgetsData?.budgets || [];
  const usageTotal = Number(budgetsData?.usage_total_usd || 0);
  const usage: any[] = (usageData?.usage || []).slice(0, 20);

  const qUsed = Number(quotaData?.used_units || 0);
  const qLimit = Number(quotaData?.limit_units || 10000);
  const qPct = qLimit ? Math.min(100, Math.round((qUsed / qLimit) * 100)) : 0;

  if (isLoading) return <Skeleton h="200px" />;

  return (
    <div className="space-y-6">
      {/* BS-1 — YouTube API quota today */}
      <Card className="!p-4">
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs text-[var(--text2)] font-semibold">Quota YouTube API hôm nay</div>
          <div className="text-[10px] text-[var(--text3)] font-mono">
            {quotaData?.uploads_today ?? 0} upload · reset {quotaData?.reset_hint || '00:00 PT'}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex-1 h-2 rounded-full bg-[var(--surface2)] overflow-hidden">
            <div className="h-full rounded-full" style={{ width: `${qPct}%`, background: qPct > 80 ? 'var(--red)' : qPct > 50 ? 'var(--amber)' : 'var(--green)' }} />
          </div>
          <span className="text-sm font-bold font-mono text-[var(--heading)]">{qUsed.toLocaleString()} / {qLimit.toLocaleString()}</span>
        </div>
        <div className="text-[10px] text-[var(--text3)] mt-1">{quotaData?.per_upload_units || 1600} units/upload · còn ~{Math.max(0, Math.floor((qLimit - qUsed) / (quotaData?.per_upload_units || 1600)))} upload</div>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="!p-4">
          <div className="text-xs text-[var(--text2)] font-semibold">Tổng chi đã ghi nhận</div>
          <div className="text-2xl font-bold font-mono text-[var(--heading)] mt-1">${usageTotal.toFixed(4)}</div>
          <div className="text-[10px] text-[var(--text3)] mt-1">{usageData?.total || 0} bản ghi usage</div>
        </Card>
        <Card className="!p-4 md:col-span-2">
          <div className="text-xs text-[var(--text2)] font-semibold mb-2">Budget guards ({budgets.length})</div>
          {budgets.length === 0 ? (
            <div className="text-[11px] text-[var(--text3)]">
              Chưa cấu hình budget nào — hệ thống dùng ngưỡng mặc định. Thêm qua API <code>POST /api/budgets</code> (scope global/campaign/channel).
            </div>
          ) : (
            <div className="space-y-1.5">
              {budgets.map((b: any, i: number) => (
                <div key={i} className="flex items-center justify-between text-[11px] p-2 rounded-[10px] bg-[var(--surface2)]">
                  <span className="font-semibold">{b.scope}{b.scope_id ? `:${b.scope_id}` : ''}</span>
                  <span className="font-mono">${Number(b.spent_usd ?? 0).toFixed(2)} / ${Number(b.limit_usd ?? 0).toFixed(2)}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card className="!p-0 overflow-hidden">
        <div className="px-4 pt-4 pb-2 text-xs font-semibold text-[var(--text2)]">Usage gần nhất (20)</div>
        {usage.length === 0 ? (
          <div className="p-4"><EmptyState icon={<Wallet size={28} />} title="Chưa có usage nào được ghi"
            desc="Số liệu xuất hiện sau lần chạy pipeline đầu tiên đi qua CapabilityBus." /></div>
        ) : (
          <Table className="text-xs">
            <THead><TR><TH>Provider</TH><TH>Capability</TH><TH>Scope</TH><TH className="text-right">Units</TH><TH className="text-right">USD</TH><TH>Lúc</TH></TR></THead>
            <TBody>
              {usage.map((u: any, i: number) => (
                <TR key={i}>
                  <TD className="font-semibold">{u.provider_id}</TD>
                  <TD>{u.capability}</TD>
                  <TD className="text-[var(--text2)]">{u.scope}{u.scope_id ? `:${u.scope_id}` : ''}</TD>
                  <TD className="text-right font-mono">{u.units}</TD>
                  <TD className="text-right font-mono">${Number(u.cost_usd || 0).toFixed(4)}</TD>
                  <TD className="font-mono text-[10px] text-[var(--text2)]">{(u.created_at || '').replace('T', ' ').slice(0, 19)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </div>
  );
};

// --- Trang He thong voi sub-tabs ---
const SUB_TABS = [
  { id: 'providers', label: 'Providers', icon: <Plug size={14} /> },
  { id: 'policy', label: 'Chính sách', icon: <Scale size={14} /> },
  { id: 'jobs', label: 'Jobs', icon: <ListChecks size={14} /> },
  { id: 'infra', label: 'Hạ tầng', icon: <Cpu size={14} /> },
  { id: 'budget', label: 'Chi phí', icon: <Wallet size={14} /> },
] as const;

export const System: React.FC = () => {
  const [sub, setSub] = useState<string>('providers');

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <h2 className="disp text-2xl font-extrabold text-[var(--heading)]" style={{ textShadow: '0 0 18px rgba(244,95,206,.30)' }}>Hệ thống <span className="text-[15px] tracking-[3px] text-[var(--accent)]" style={{ textShadow: '0 0 10px rgba(244,95,206,.65)' }}>⋆｡˚✧</span></h2>
          <p className="text-xs text-[var(--text2)] mb-3">Tự động hóa · Schedulers · Providers · Infrastructure</p>
        </div>
        <div className="flex gap-1">
          {SUB_TABS.map((t) => (
            <button key={t.id} onClick={() => setSub(t.id)}
              className={`flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-bold rounded-full border-2 transition-colors cursor-pointer ${
                sub === t.id
                  ? 'border-[var(--ink)] text-[var(--accent)] bg-[var(--surface)]'
                  : 'border-transparent text-[var(--text2)] hover:text-[var(--accent)]'}`}
              style={sub === t.id ? { boxShadow: 'var(--shadow-hard-sm)' } : undefined}>
              {t.icon}{t.label}
            </button>
          ))}
        </div>
      </div>

      {sub === 'providers' && <ProvidersTab />}
      {sub === 'policy' && <PolicyTab />}
      {sub === 'jobs' && <JobsTab />}
      {sub === 'infra' && <InfraTab />}
      {sub === 'budget' && <BudgetTab />}
    </div>
  );
};
