import React, { useState } from 'react';
import { useApi, useInvalidate } from '../api/hooks';
import {
  Badge, Button, Card, Checkbox, ConfirmModal, Drawer, EmptyState, Input,
  Modal, Select, Skeleton, Table, TBody, TD, TH, THead, TR,
} from '../components/ui';
import {
  Clapperboard, Copy, ExternalLink, FolderSearch, Link2, Plus, RefreshCw, Users,
} from 'lucide-react';

/* Kho phim — series → tập → bài đăng (kênh × nền tảng).
   Trả lời 3 câu: video thuộc series nào, series thiếu tập nào so với nguồn,
   tập nào đã/chưa đăng lên từng kênh. */

// Raw fetch thay vì apiPost: cần đọc body.detail của FastAPI khi lỗi.
async function req(method: string, path: string, body?: any): Promise<any> {
  const res = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const b = await res.json().catch(() => ({}));
    // 405 (hoặc 404 trần không có detail) = request rơi vào mount tĩnh của SPA:
    // backend đang chạy bản cũ chưa nạp route Kho phim — UI tự mới vì được
    // serve thẳng từ đĩa, còn Python phải khởi động lại.
    if (res.status === 405 || (res.status === 404 && !b.detail)) {
      throw new Error(
        'Backend đang chạy bản cũ chưa có route Kho phim — tắt backend rồi chạy lại '
        + '`python run_backend.py`, sau đó thử lại.'
      );
    }
    throw new Error(b.detail || `HTTP ${res.status}`);
  }
  return res.json().catch(() => ({}));
}

const EP_BADGE: Record<string, { label: string; variant: 'green' | 'blue' | 'amber' | 'red' | 'purple' | 'neutral' }> = {
  planned: { label: 'Chưa dub', variant: 'neutral' },
  queued: { label: 'Chờ chạy', variant: 'blue' },
  processing: { label: 'Đang làm', variant: 'blue' },
  review: { label: 'Chờ duyệt', variant: 'amber' },
  exported: { label: 'Xong', variant: 'green' },
  failed: { label: 'Lỗi', variant: 'red' },
};

const PLATFORM_SHORT: Record<string, string> = {
  youtube: 'YT', tiktok: 'TT', facebook: 'FB', douyin: 'DY', other: '?',
};

function epBadge(status: string) {
  const cfg = EP_BADGE[status] || { label: status || '—', variant: 'neutral' as const };
  return <Badge variant={cfg.variant}>{cfg.label}</Badge>;
}

// ── Form series (tạo / sửa) ─────────────────────────────────────────────────
const SeriesFormModal: React.FC<{
  isOpen: boolean;
  initial: any | null;
  channels: any[];
  onClose: () => void;
  onSaved: (sid: string) => void;
}> = ({ isOpen, initial, channels, onClose, onSaved }) => {
  const [title, setTitle] = useState('');
  const [kind, setKind] = useState('series');
  const [channelId, setChannelId] = useState('');
  const [sourceUrl, setSourceUrl] = useState('');
  const [author, setAuthor] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  React.useEffect(() => {
    setTitle(initial?.title || '');
    setKind(initial?.kind || 'series');
    setChannelId(initial?.channel_id || '');
    setSourceUrl(initial?.source_url || '');
    setAuthor(initial?.source_author || '');
    setError('');
  }, [initial, isOpen]);

  async function save() {
    if (!title.trim()) { setError('Cần tên series.'); return; }
    setSaving(true); setError('');
    try {
      const body = {
        title: title.trim(), kind, channel_id: channelId,
        source_url: sourceUrl.trim(), source_author: author.trim(),
      };
      const saved = initial
        ? await req('PATCH', `/api/library/series/${initial.series_id}`, body)
        : await req('POST', '/api/library/series', body);
      onSaved(saved.series_id);
      onClose();
    } catch (e: any) { setError(e.message || 'Không lưu được'); }
    finally { setSaving(false); }
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={initial ? 'Sửa series' : 'Thêm series'}>
      <div className="space-y-3">
        <label className="text-sm block">
          <span className="mb-1 block opacity-70">Tên series (tiếng Việt)</span>
          <Input value={title} onChange={(e: any) => setTitle(e.target.value)} placeholder="Khỉ Đột Đỏ" />
        </label>
        <label className="text-sm block">
          <span className="mb-1 block opacity-70">Loại</span>
          <Select value={kind} onChange={(e: any) => setKind(e.target.value)}>
            <option value="series">Phim bộ — có số tập, so thiếu với nguồn</option>
            <option value="single">Video lẻ — thùng gom video 1 tập, không đánh số</option>
          </Select>
        </label>
        <label className="text-sm block">
          <span className="mb-1 block opacity-70">Kênh chủ</span>
          <Select value={channelId} onChange={(e: any) => setChannelId(e.target.value)}>
            <option value="">Chưa gắn kênh</option>
            {channels.map((c: any) => (
              <option key={c.channel_id} value={c.channel_id}>{c.name || c.channel_id}</option>
            ))}
          </Select>
        </label>
        <label className="text-sm block">
          <span className="mb-1 block opacity-70">
            Link nguồn — hợp tập Douyin hoặc Bilibili 合集/video nhiều phần (để quét & báo thiếu tập)
          </span>
          <Input value={sourceUrl} onChange={(e: any) => setSourceUrl(e.target.value)}
                 placeholder="douyin.com/collection/… · bilibili.com/video/BV… · space.bilibili.com/…?sid=…" />
        </label>
        <label className="text-sm block">
          <span className="mb-1 block opacity-70">Tác giả nguồn</span>
          <Input value={author} onChange={(e: any) => setAuthor(e.target.value)} placeholder="沙雕阿豪" />
        </label>
        {error && <div className="text-sm text-[var(--red)] font-semibold">{error}</div>}
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose}>Hủy</Button>
          <Button variant="primary" onClick={save} disabled={saving}>
            {saving ? 'Đang lưu…' : 'Lưu'}
          </Button>
        </div>
      </div>
    </Modal>
  );
};

// ── Quản lý kênh đăng (platform accounts) ───────────────────────────────────
const AccountsModal: React.FC<{
  isOpen: boolean;
  channels: any[];
  onClose: () => void;
}> = ({ isOpen, channels, onClose }) => {
  const invalidate = useInvalidate();
  const { data } = useApi<any>('/api/library/accounts', { enabled: isOpen });
  const accounts: any[] = data?.accounts || [];
  const [platform, setPlatform] = useState('youtube');
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [channelId, setChannelId] = useState('');
  const [externalId, setExternalId] = useState('');
  const [error, setError] = useState('');
  const [reconcile, setReconcile] = useState<any | null>(null);
  const [busy, setBusy] = useState('');

  async function add() {
    if (!name.trim()) { setError('Cần tên kênh.'); return; }
    setError('');
    try {
      await req('POST', '/api/library/accounts', {
        platform, name: name.trim(), url: url.trim(),
        channel_id: channelId, external_id: externalId.trim(),
      });
      setName(''); setUrl(''); setExternalId('');
      invalidate('/api/library/accounts');
      invalidate('/api/library/overview');
    } catch (e: any) { setError(e.message || 'Không thêm được'); }
  }

  async function remove(accountId: string) {
    try {
      await req('DELETE', `/api/library/accounts/${accountId}`);
      invalidate('/api/library/accounts');
      invalidate('/api/library/overview');
    } catch (e: any) { setError(e.message || 'Không xóa được'); }
  }

  async function runReconcile(accountId: string) {
    setBusy(accountId); setError(''); setReconcile(null);
    try {
      const r = await req('POST', `/api/library/accounts/${accountId}/reconcile-youtube`, {});
      setReconcile(r);
      invalidate('/api/library/overview');
    } catch (e: any) { setError(e.message || 'Đối soát thất bại'); }
    finally { setBusy(''); }
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Kênh đăng (YouTube / TikTok / Facebook)">
      <div className="space-y-4">
        {accounts.length === 0 ? (
          <p className="text-sm opacity-70">
            Chưa có kênh đăng nào. Thêm từng kênh bạn đang rải video lên — mỗi kênh
            trên mỗi nền tảng là một dòng.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <THead><TR><TH>Nền tảng</TH><TH>Tên</TH><TH>Kênh chủ</TH><TH>Thao tác</TH></TR></THead>
              <TBody>
                {accounts.map((a: any) => (
                  <TR key={a.account_id}>
                    <TD><Badge variant={a.platform === 'youtube' ? 'red' : a.platform === 'tiktok' ? 'purple' : 'blue'}>{PLATFORM_SHORT[a.platform] || a.platform}</Badge></TD>
                    <TD>
                      <div className="font-semibold">{a.name}</div>
                      {a.url && <a className="text-xs opacity-60 hover:opacity-100" href={a.url} target="_blank" rel="noreferrer">{a.url}</a>}
                    </TD>
                    <TD className="text-xs opacity-70">{a.channel_id || '—'}</TD>
                    <TD>
                      <div className="flex gap-1.5">
                        {a.platform === 'youtube' && (
                          <Button size="sm" variant="secondary" disabled={busy === a.account_id}
                                  onClick={() => runReconcile(a.account_id)}>
                            {busy === a.account_id ? 'Đang quét…' : 'Đối soát'}
                          </Button>
                        )}
                        <Button size="sm" variant="ghost" onClick={() => remove(a.account_id)}>Xóa</Button>
                      </div>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </div>
        )}

        {reconcile && (
          <div className="rounded-[10px] border-2 border-[var(--ink)] bg-[var(--green-soft)] p-3 text-sm">
            <div className="font-bold">
              Đối soát xong: {reconcile.uploads_scanned} video trên kênh — khớp {reconcile.matched}, đã tick {reconcile.posts_written}.
            </div>
            {(reconcile.unmatched || []).length > 0 && (
              <div className="mt-1 text-xs opacity-80">
                {reconcile.unmatched.length} video không khớp được (tick tay trong bảng tập):
                <ul className="list-disc ml-4 mt-1 max-h-32 overflow-y-auto">
                  {reconcile.unmatched.slice(0, 15).map((u: any) => (
                    <li key={u.video_id}>{u.title}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        <div className="rounded-[10px] border-2 border-[var(--border-soft)] p-3 space-y-2">
          <div className="text-sm font-bold">Thêm kênh đăng</div>
          <div className="grid grid-cols-2 gap-2">
            <Select value={platform} onChange={(e: any) => setPlatform(e.target.value)}>
              <option value="youtube">YouTube</option>
              <option value="tiktok">TikTok</option>
              <option value="facebook">Facebook</option>
              <option value="other">Khác</option>
            </Select>
            <Input value={name} onChange={(e: any) => setName(e.target.value)} placeholder="Tên kênh" />
            <Input value={url} onChange={(e: any) => setUrl(e.target.value)} placeholder="Link kênh (tùy chọn)" />
            <Select value={channelId} onChange={(e: any) => setChannelId(e.target.value)}>
              <option value="">Không gắn kênh chủ</option>
              {channels.map((c: any) => (
                <option key={c.channel_id} value={c.channel_id}>{c.name || c.channel_id}</option>
              ))}
            </Select>
            {platform === 'youtube' && (
              <Input className="col-span-2" value={externalId}
                     onChange={(e: any) => setExternalId(e.target.value)}
                     placeholder="YouTube channel id (UC…) — cần cho đối soát tự động" />
            )}
          </div>
          <div className="flex justify-end">
            <Button size="sm" variant="primary" onClick={add}><Plus size={14} className="mr-1" />Thêm</Button>
          </div>
        </div>

        {error && <div className="text-sm text-[var(--red)] font-semibold">{error}</div>}
      </div>
    </Modal>
  );
};

// ── Nhập kho (backfill) ─────────────────────────────────────────────────────
interface BFItem { include: boolean; ep_no: string; item: any; }
interface BFGroup {
  include: boolean; title: string; channel_id: string; series_id: string;
  author: string; source_url: string; items: BFItem[];
}

const BackfillModal: React.FC<{
  isOpen: boolean;
  channels: any[];
  onClose: () => void;
}> = ({ isOpen, channels, onClose }) => {
  const invalidate = useInvalidate();
  const [scanning, setScanning] = useState(false);
  const [scanInfo, setScanInfo] = useState<any | null>(null);
  const [groups, setGroups] = useState<BFGroup[]>([]);
  const [existingSeries, setExistingSeries] = useState<any[]>([]);
  const [committing, setCommitting] = useState(false);
  const [result, setResult] = useState<any | null>(null);
  const [error, setError] = useState('');

  async function scan() {
    setScanning(true); setError(''); setResult(null);
    try {
      const r = await req('POST', '/api/library/backfill/scan');
      setScanInfo({ total: r.total_items, already: r.already_in_library });
      setExistingSeries(r.existing_series || []);
      setGroups((r.groups || []).map((g: any): BFGroup => ({
        include: true,
        title: g.suggest_title || '',
        channel_id: g.suggest_channel_id || '',
        series_id: '',
        author: g.suggest_author || '',
        source_url: '',
        items: (g.items || []).map((i: any): BFItem => ({
          // Job rác (không tập, không file) mặc định bỏ qua.
          include: i.guessed_ep != null || i.video_exists,
          ep_no: i.guessed_ep != null ? String(i.guessed_ep) : '',
          item: i,
        })),
      })));
    } catch (e: any) { setError(e.message || 'Quét thất bại'); }
    finally { setScanning(false); }
  }

  function patchGroup(gi: number, patch: Partial<BFGroup>) {
    setGroups(gs => gs.map((g, i) => (i === gi ? { ...g, ...patch } : g)));
  }
  function patchItem(gi: number, ii: number, patch: Partial<BFItem>) {
    setGroups(gs => gs.map((g, i) => i !== gi ? g : {
      ...g, items: g.items.map((it, j) => (j === ii ? { ...it, ...patch } : it)),
    }));
  }

  async function commit() {
    setCommitting(true); setError('');
    try {
      const payload = {
        groups: groups
          .filter(g => g.include && g.items.some(i => i.include))
          .map(g => ({
            series: g.series_id
              ? { series_id: g.series_id }
              : {
                  title: g.title || 'Chưa rõ tên', channel_id: g.channel_id,
                  source_author: g.author, source_url: g.source_url,
                },
            episodes: g.items.filter(i => i.include).map(i => ({
              ep_no: i.ep_no.trim() === '' ? null : Number(i.ep_no),
              aweme_id: i.item.aweme_id, title: i.item.title,
              title_vi: i.item.title_vi, source_url: i.item.source_url,
              reup_job_id: i.item.reup_job_id, product_dir: i.item.product_dir,
              video_path: i.item.video_path,
              status: i.item.status_suggest || null,
            })),
          })),
      };
      const r = await req('POST', '/api/library/backfill/commit', payload);
      setResult(r);
      setGroups([]);
      invalidate('/api/library/overview');
    } catch (e: any) { setError(e.message || 'Nhập kho thất bại'); }
    finally { setCommitting(false); }
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Quét & nhập kho video tồn đọng">
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <p className="text-sm opacity-70 max-w-md">
            Quét vault + <span className="mono">output/products</span> + workspace reup,
            gom video theo tác giả và tên phim. Bạn duyệt lại rồi mới ghi vào kho.
          </p>
          <Button variant="primary" onClick={scan} disabled={scanning}>
            <FolderSearch size={15} className="mr-1" />
            {scanning ? 'Đang quét…' : 'Quét ngay'}
          </Button>
        </div>

        {scanInfo && (
          <div className="text-sm">
            Tìm thấy <strong>{scanInfo.total}</strong> video — <strong>{scanInfo.already}</strong> đã
            trong kho, còn lại {groups.reduce((n, g) => n + g.items.length, 0)} chờ phân loại.
          </div>
        )}

        {groups.map((g, gi) => (
          <div key={gi} className={`rounded-[12px] border-2 p-3 space-y-2 ${g.include ? 'border-[var(--ink)]' : 'border-[var(--border-soft)] opacity-60'}`}>
            <div className="flex items-center gap-2 flex-wrap">
              <Checkbox checked={g.include} onChange={(e: any) => patchGroup(gi, { include: e.target.checked })} />
              <Input className="flex-1 min-w-40" value={g.title}
                     onChange={(e: any) => patchGroup(gi, { title: e.target.value })}
                     placeholder="Tên series" />
              <Select className="w-44" value={g.series_id}
                      onChange={(e: any) => patchGroup(gi, { series_id: e.target.value })}>
                <option value="">➕ Tạo series mới</option>
                {existingSeries.map((s: any) => (
                  <option key={s.series_id} value={s.series_id}>Gộp vào: {s.title}</option>
                ))}
              </Select>
              {!g.series_id && (
                <Select className="w-40" value={g.channel_id}
                        onChange={(e: any) => patchGroup(gi, { channel_id: e.target.value })}>
                  <option value="">Chưa gắn kênh</option>
                  {channels.map((c: any) => (
                    <option key={c.channel_id} value={c.channel_id}>{c.name || c.channel_id}</option>
                  ))}
                </Select>
              )}
            </div>
            {g.author && <div className="text-xs opacity-60">Tác giả nguồn: {g.author}</div>}
            <div className="overflow-x-auto">
              <Table>
                <THead><TR><TH></TH><TH>Tập</TH><TH>Tiêu đề</TH><TH>File</TH><TH>Trạng thái</TH></TR></THead>
                <TBody>
                  {g.items.map((it, ii) => (
                    <TR key={it.item.key}>
                      <TD><Checkbox checked={it.include} onChange={(e: any) => patchItem(gi, ii, { include: e.target.checked })} /></TD>
                      <TD>
                        <Input className="w-16" value={it.ep_no} inputMode="numeric"
                               onChange={(e: any) => patchItem(gi, ii, { ep_no: e.target.value.replace(/[^0-9]/g, '') })}
                               placeholder="?" />
                      </TD>
                      <TD className="max-w-64">
                        <div className="truncate text-xs" title={it.item.title || it.item.title_vi}>
                          {it.item.title || it.item.title_vi || <span className="opacity-50">(không tiêu đề — job {it.item.reup_job_id || it.item.key})</span>}
                        </div>
                      </TD>
                      <TD>{it.item.video_exists ? '🎬' : '—'}</TD>
                      <TD>{epBadge(it.item.status_suggest)}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </div>
          </div>
        ))}

        {groups.length > 0 && (
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>Để sau</Button>
            <Button variant="primary" onClick={commit} disabled={committing}>
              {committing ? 'Đang ghi…' : 'Nhập kho các mục đã chọn'}
            </Button>
          </div>
        )}

        {result && (
          <div className="rounded-[10px] border-2 border-[var(--ink)] bg-[var(--green-soft)] p-3 text-sm space-y-1">
            <div className="font-bold">
              Đã nhập: {result.created_series?.length || 0} series mới,{' '}
              {result.created_episodes} tập mới, {result.updated_episodes} tập cập nhật.
            </div>
            {(result.conflicts || []).length > 0 && (
              <div className="text-xs">
                <div className="font-semibold text-[var(--red)]">Bỏ qua {result.conflicts.length} mục xung đột:</div>
                <ul className="list-disc ml-4 max-h-28 overflow-y-auto">
                  {result.conflicts.map((c: any, i: number) => (
                    <li key={i}>{c.reason} — tập {c.ep_no ?? '?'} {c.title || c.aweme_id || ''}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {error && <div className="text-sm text-[var(--red)] font-semibold">{error}</div>}
      </div>
    </Modal>
  );
};

// ── Trang chính ─────────────────────────────────────────────────────────────
export const SeriesLibrary: React.FC = () => {
  const invalidate = useInvalidate();
  const { data: overviewData, isLoading } = useApi<any>('/api/library/overview');
  const { data: channelsData } = useApi<any>('/api/channels');
  const channels: any[] = channelsData?.channels || [];
  const seriesRows: any[] = overviewData?.series || [];

  const [selected, setSelected] = useState('');
  const [showBackfill, setShowBackfill] = useState(false);
  const [showAccounts, setShowAccounts] = useState(false);
  const [seriesForm, setSeriesForm] = useState<{ open: boolean; initial: any | null }>({ open: false, initial: null });
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [postModal, setPostModal] = useState<any | null>(null);
  const [postUrl, setPostUrl] = useState('');
  const [syncMsg, setSyncMsg] = useState('');
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState('');
  const [newEp, setNewEp] = useState('');

  const detailPath = `/api/library/series/${selected}`;
  const { data: detail } = useApi<any>(detailPath, { enabled: !!selected });
  const episodes: any[] = detail?.episodes || [];
  const accounts: any[] = detail?.accounts || [];

  function refreshAll() {
    invalidate('/api/library/overview');
    if (selected) invalidate(detailPath);
  }

  async function syncSource() {
    setSyncing(true); setSyncMsg(''); setError('');
    try {
      const r = await req('POST', `/api/library/series/${selected}/sync-source`, {});
      setSyncMsg(`Nguồn có ${r.source_count} tập — thêm ${r.episodes_created}, cập nhật ${r.episodes_updated}${r.conflicts?.length ? `, ${r.conflicts.length} xung đột số tập` : ''}.`);
      refreshAll();
    } catch (e: any) { setError(e.message || 'Quét nguồn thất bại'); }
    finally { setSyncing(false); }
  }

  async function savePost() {
    if (!postModal) return;
    try {
      await req('PUT', `/api/library/episodes/${postModal.episode.episode_id}/posts/${postModal.account.account_id}`,
        { post_url: postUrl.trim() });
      setPostModal(null); setPostUrl('');
      refreshAll();
    } catch (e: any) { setError(e.message || 'Không đánh dấu được'); }
  }

  async function removePost() {
    if (!postModal) return;
    try {
      await req('DELETE', `/api/library/episodes/${postModal.episode.episode_id}/posts/${postModal.account.account_id}`);
      setPostModal(null); setPostUrl('');
      refreshAll();
    } catch (e: any) { setError(e.message || 'Không bỏ được'); }
  }

  async function addEpisode() {
    const n = Number(newEp);
    if (!n || n < 1) return;
    try {
      await req('POST', `/api/library/series/${selected}/episodes`, { ep_no: n });
      setNewEp('');
      refreshAll();
    } catch (e: any) { setError(e.message || 'Không thêm được tập'); }
  }

  async function deleteSeries() {
    try {
      await req('DELETE', `/api/library/series/${selected}`);
      setConfirmDelete(false); setSelected('');
      refreshAll();
    } catch (e: any) { setError(e.message || 'Không xóa được'); }
  }

  const selectedRow = seriesRows.find((s: any) => s.series_id === selected);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h2 className="disp text-2xl font-extrabold text-[var(--heading)]">Kho phim ⋆｡˚✧</h2>
          <p className="text-sm text-[var(--text2)]">
            Series → tập → bài đăng từng kênh. Thiếu tập nào so với nguồn, nhìn là thấy.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Button variant="secondary" onClick={() => setShowBackfill(true)}>
            <FolderSearch size={15} className="mr-1" />Quét nhập kho
          </Button>
          <Button variant="secondary" onClick={() => setShowAccounts(true)}>
            <Users size={15} className="mr-1" />Kênh đăng
          </Button>
          <Button variant="primary" onClick={() => setSeriesForm({ open: true, initial: null })}>
            <Plus size={15} className="mr-1" />Series
          </Button>
        </div>
      </div>

      {error && <div className="text-sm text-[var(--red)] font-semibold">{error}</div>}

      {isLoading ? (
        <div className="space-y-3"><Skeleton h="52px" /><Skeleton h="52px" /><Skeleton h="52px" /></div>
      ) : seriesRows.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Clapperboard size={32} />}
            title="Kho đang trống"
            desc="Quét nhập kho để gom mớ video đã dub từ trước, hoặc thêm series mới rồi tạo job reup gắn vào."
            actionLabel="Quét nhập kho ngay"
            onAction={() => setShowBackfill(true)}
          />
        </Card>
      ) : (
        <Card className="overflow-hidden p-0">
          <div className="overflow-x-auto">
            <Table>
              <THead>
                <TR>
                  <TH>Series</TH><TH>Kênh</TH><TH>Nguồn</TH><TH>Đã dub</TH><TH>Đã đăng</TH><TH>Tình trạng</TH>
                </TR>
              </THead>
              <TBody>
                {seriesRows.map((s: any) => (
                  <TR key={s.series_id} className="cursor-pointer h-12 hover:bg-[var(--accent-soft)]"
                      onClick={() => { setSelected(s.series_id); setSyncMsg(''); }}>
                    <TD>
                      <div className="font-bold text-[var(--heading)]">{s.title}</div>
                      <div className="text-[11px] opacity-60">
                        {s.title_source && s.title_source !== s.title ? `${s.title_source} · ` : ''}{s.source_author || ''}
                      </div>
                    </TD>
                    <TD className="text-xs">{s.channel_id || <span className="opacity-50">—</span>}</TD>
                    <TD className="text-xs">
                      {s.kind === 'single'
                        ? <Badge variant="purple">video lẻ</Badge>
                        : s.source_episode_count
                          ? `${s.source_episode_count} tập`
                          : <span className="opacity-50">chưa liên kết</span>}
                    </TD>
                    <TD>
                      <span className="font-bold">{s.ep_exported}</span>
                      <span className="opacity-60">
                        /{s.kind === 'single' ? s.ep_total : (s.source_episode_count || s.ep_total)}
                      </span>
                      {s.kind !== 'single' && s.missing_source > 0 && (
                        <span className="ml-2"><Badge variant="amber">thiếu {s.missing_source}</Badge></span>
                      )}
                    </TD>
                    <TD className="text-xs">
                      {['youtube', 'tiktok', 'facebook'].map(p => (
                        <span key={p} className="mr-2">
                          {PLATFORM_SHORT[p]} <strong>{(s.posted || {})[p] || 0}</strong>
                        </span>
                      ))}
                    </TD>
                    <TD>
                      <div className="flex gap-1 flex-wrap">
                        {s.ep_processing > 0 && <Badge variant="blue">{s.ep_processing} đang làm</Badge>}
                        {s.ep_review > 0 && <Badge variant="amber">{s.ep_review} chờ duyệt</Badge>}
                        {s.ep_failed > 0 && <Badge variant="red">{s.ep_failed} lỗi</Badge>}
                        {s.ep_processing === 0 && s.ep_review === 0 && s.ep_failed === 0 && (
                          <Badge variant="green">ổn</Badge>
                        )}
                      </div>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </div>
        </Card>
      )}

      {/* ── Chi tiết series ── */}
      <Drawer isOpen={!!selected} onClose={() => setSelected('')}
              title={detail?.series?.title || 'Chi tiết series'}>
        {detail && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2 text-xs font-mono">
              <div>Kênh chủ: <strong>{detail.series.channel_id || '—'}</strong></div>
              <div>Tác giả: <strong>{detail.series.source_author || '—'}</strong></div>
              <div>Nguồn: <strong>{detail.series.source_episode_count || '?'} tập</strong></div>
              <div>Quét lúc: <strong>{(detail.series.source_synced_at || '').slice(0, 16) || 'chưa'}</strong></div>
            </div>

            <div className="flex gap-2 flex-wrap">
              {detail.series.kind !== 'single' && (
                <Button size="sm" variant="secondary" onClick={syncSource}
                        disabled={syncing || !(detail.series.source_url || detail.series.source_mix_id)}>
                  <RefreshCw size={13} className="mr-1" />
                  {syncing ? 'Đang quét nguồn…' : 'Quét nguồn (đếm tập)'}
                </Button>
              )}
              <Button size="sm" variant="secondary"
                      onClick={() => setSeriesForm({ open: true, initial: detail.series })}>
                Sửa
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(true)}>Xóa</Button>
              {detail.series.source_url && (
                <a href={detail.series.source_url} target="_blank" rel="noreferrer"
                   className="inline-flex items-center text-xs opacity-70 hover:opacity-100 gap-1">
                  <ExternalLink size={12} />hợp tập nguồn
                </a>
              )}
            </div>
            {syncMsg && <div className="text-xs text-[var(--green-ink)] font-semibold">{syncMsg}</div>}
            {!accounts.length && (
              <div className="text-xs opacity-70">
                Chưa có kênh đăng nào để tick — thêm trong「Kênh đăng」ở trang chính.
              </div>
            )}

            <div className="overflow-x-auto">
              <Table>
                <THead>
                  <TR>
                    <TH>{detail.series.kind === 'single' ? 'Video' : 'Tập'}</TH><TH>Trạng thái</TH>
                    {accounts.map((a: any) => (
                      <TH key={a.account_id} title={a.name}>
                        {PLATFORM_SHORT[a.platform] || a.platform}·{a.name.slice(0, 8)}
                      </TH>
                    ))}
                    <TH></TH>
                  </TR>
                </THead>
                <TBody>
                  {episodes.map((e: any) => {
                    const postedBy: Record<string, any> = {};
                    (e.posts || []).forEach((p: any) => { postedBy[p.account_id] = p; });
                    return (
                      <TR key={e.episode_id}>
                        <TD>
                          {detail.series.kind === 'single' ? (
                            /* Video lẻ: số thứ tự chỉ là nội bộ — hiện tên video. */
                            <div className="font-bold max-w-44 truncate" title={e.title || e.title_vi}>
                              {e.title_vi || e.title || `#${e.ep_no}`}
                            </div>
                          ) : (
                            <>
                              <div className="font-bold">Tập {e.ep_no}</div>
                              <div className="text-[10px] opacity-60 max-w-40 truncate" title={e.title || e.title_vi}>
                                {e.title_vi || e.title}
                              </div>
                            </>
                          )}
                        </TD>
                        <TD>{epBadge(e.status)}</TD>
                        {accounts.map((a: any) => {
                          const p = postedBy[a.account_id];
                          return (
                            <TD key={a.account_id}>
                              <button
                                className={`w-8 h-8 rounded-[8px] border-2 border-[var(--ink)] font-bold cursor-pointer ${p ? 'bg-[var(--green)] text-white' : 'bg-[var(--surface2)] text-[var(--text3)]'}`}
                                title={p ? (p.post_url || 'Đã đăng') : 'Chưa đăng — bấm để đánh dấu'}
                                onClick={() => { setPostModal({ episode: e, account: a, post: p || null }); setPostUrl(p?.post_url || ''); }}
                              >
                                {p ? '✓' : '·'}
                              </button>
                            </TD>
                          );
                        })}
                        <TD>
                          {e.status === 'planned' && e.source_url ? (
                            <button
                              className="inline-flex items-center gap-1 text-xs opacity-70 hover:opacity-100 cursor-pointer"
                              title="Copy link nguồn để dán vào Reup"
                              onClick={() => navigator.clipboard?.writeText(e.source_url)}
                            >
                              <Copy size={12} />link
                            </button>
                          ) : e.video_path ? (
                            <span title={e.video_path}>🎬</span>
                          ) : null}
                        </TD>
                      </TR>
                    );
                  })}
                </TBody>
              </Table>
            </div>

            <div className="flex items-center gap-2">
              <Input className="w-24" value={newEp} inputMode="numeric" placeholder="Số tập"
                     onChange={(e: any) => setNewEp(e.target.value.replace(/[^0-9]/g, ''))} />
              <Button size="sm" variant="secondary" onClick={addEpisode} disabled={!newEp}>
                <Plus size={13} className="mr-1" />Thêm tập tay
              </Button>
              {detail.series.kind !== 'single' && selectedRow?.missing_source > 0 && (
                <span className="text-xs opacity-70">
                  Thiếu {selectedRow.missing_source} tập so với nguồn — tập「Chưa dub」có nút copy link để tạo job.
                </span>
              )}
            </div>
          </div>
        )}
      </Drawer>

      {/* ── Modal tick bài đăng ── */}
      <Modal isOpen={!!postModal} onClose={() => setPostModal(null)}
             title={postModal ? `Tập ${postModal.episode.ep_no} × ${postModal.account.name}` : ''}>
        {postModal && (
          <div className="space-y-3">
            {postModal.post ? (
              <>
                <div className="text-sm">
                  Đã đánh dấu đăng lúc {(postModal.post.posted_at || '').slice(0, 16) || '?'}
                  {postModal.post.source !== 'manual' && ` (nguồn: ${postModal.post.source})`}.
                </div>
                {postModal.post.post_url && (
                  <a className="inline-flex items-center gap-1 text-sm text-[var(--blue)] font-semibold"
                     href={postModal.post.post_url} target="_blank" rel="noreferrer">
                    <Link2 size={14} />Mở bài đăng
                  </a>
                )}
                <div className="flex justify-end gap-2">
                  <Button variant="ghost" onClick={() => setPostModal(null)}>Đóng</Button>
                  <Button variant="danger" onClick={removePost}>Bỏ đánh dấu</Button>
                </div>
              </>
            ) : (
              <>
                <label className="text-sm block">
                  <span className="mb-1 block opacity-70">Link bài đăng (tùy chọn)</span>
                  <Input value={postUrl} onChange={(e: any) => setPostUrl(e.target.value)}
                         placeholder="https://…" />
                </label>
                <div className="flex justify-end gap-2">
                  <Button variant="ghost" onClick={() => setPostModal(null)}>Hủy</Button>
                  <Button variant="primary" onClick={savePost}>Đánh dấu đã đăng</Button>
                </div>
              </>
            )}
          </div>
        )}
      </Modal>

      <ConfirmModal
        isOpen={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={deleteSeries}
        title="Xóa series này?"
        desc="Chỉ xóa dữ liệu quản lý (series/tập/dấu đăng). File video trên đĩa không bị đụng."
        confirmLabel="Xóa"
      />

      <SeriesFormModal
        isOpen={seriesForm.open}
        initial={seriesForm.initial}
        channels={channels}
        onClose={() => setSeriesForm({ open: false, initial: null })}
        onSaved={(sid) => { refreshAll(); setSelected(sid); }}
      />
      <AccountsModal isOpen={showAccounts} channels={channels} onClose={() => setShowAccounts(false)} />
      <BackfillModal isOpen={showBackfill} channels={channels} onClose={() => { setShowBackfill(false); refreshAll(); }} />
    </div>
  );
};

export default SeriesLibrary;
