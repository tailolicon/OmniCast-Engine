import React, { useState } from 'react';
import { useApi, useInvalidate } from '../api/hooks';
import { apiPost } from '../api/client';
import {
  Button,
  Card,
  Skeleton,
  EmptyState,
  Input,
  Drawer,
  Badge,
  Modal,
  DataTable,
  Select,
  Checkbox,
  VoicePicker
} from '../components/ui';
import { Tv, Users, Plus, Compass } from 'lucide-react';

export const Channels: React.FC = () => {
  const invalidate = useInvalidate();
  const [activeSubTab, setActiveSubTab] = useState<'channels' | 'niches'>('channels');

  // Modal & Drawer State
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [editingChannel, setEditingChannel] = useState<any | null>(null);
  const [deletingChannelId, setDeletingChannelId] = useState<string | null>(null);

  // Form fields states for visual editing
  const [formName, setFormName] = useState('');
  const [formNiche, setFormNiche] = useState('');
  const [formVoice, setFormVoice] = useState('');
  const [formCadence, setFormCadence] = useState('daily');
  const [formEnabled, setFormEnabled] = useState(true);
  const [formShorts, setFormShorts] = useState(false);
  const [formUpload, setFormUpload] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // JSON Config editor states
  const [jsonConfig, setJsonConfig] = useState('');
  const [jsonError, setJsonError] = useState<string | null>(null);

  const handleSaveChannelConfig = async () => {
    if (!editingChannel) return;
    try {
      let parsed = {};
      try {
        parsed = JSON.parse(jsonConfig);
      } catch (e) {
        parsed = { ...editingChannel };
      }
      
      const updated = {
        ...parsed,
        name: formName,
        niche: formNiche,
        voice_profile: formVoice,
        cadence: formCadence,
        enabled: formEnabled,
        shorts: formShorts,
        upload: formUpload
      };
      
      const res = await fetch(`/api/channels/${editingChannel.channel_id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updated)
      }).then(r => r.json());

      if (res && res.status === 'updated') {
        invalidate('/api/channels');
        setEditingChannel(null);
        setJsonConfig('');
        setJsonError(null);
      } else {
        setJsonError(res.detail || 'Lỗi cập nhật cấu hình');
      }
    } catch (e: any) {
      setJsonError(e.message || 'Lỗi lưu cấu hình');
    }
  };

  // New Channel Form State
  const [newChannelId, setNewChannelId] = useState('');
  const [newChannelName, setNewChannelName] = useState('');
  const [newChannelNiche, setNewChannelNiche] = useState('');

  // Queries
  const { data: channelsData, isLoading: isChannelsLoading } = useApi<any>('/api/channels');
  const { data: nichesData, isLoading: isNichesLoading } = useApi<any>('/api/niches');
  const { data: statusForQuota } = useApi<any>('/api/status');
  const [showQuota, setShowQuota] = React.useState(false);
  const [nicheDetail, setNicheDetail] = React.useState<any>(null);
  const quota = React.useMemo(() => {
    const acts: any[] = statusForQuota?.recent_activity || [];
    const today = new Date().toISOString().slice(0, 10);
    const scans = acts.filter((a) =>
      String(a.channel_id || a.channel || '').includes('niche') &&
      String(a.ts || a.timestamp || '').startsWith(today)).length;
    const left = Math.max(0, 10000 - scans * 4300);
    return { scans, left, leftPct: Math.round(left / 100) };
  }, [statusForQuota]);

  const channels = channelsData?.channels || [];
  const niches = nichesData?.niches || [];

  // Actions
  const handleAddChannel = async () => {
    if (!newChannelId || !newChannelName) return;
    try {
      await apiPost('/api/channels', {
        channel_id: newChannelId,
        name: newChannelName,
        niche: newChannelNiche,
        enabled: true,
        cadence: 'daily',
        shorts: false,
        upload: false
      });
      invalidate('/api/channels');
      setIsAddModalOpen(false);
      setNewChannelId('');
      setNewChannelName('');
      setNewChannelNiche('');
    } catch (e) {}
  };

  const handleDeleteChannel = async () => {
    if (!deletingChannelId) return;
    try {
      // call DELETE /api/channels/{id}
      await fetch(`/api/channels/${deletingChannelId}`, { method: 'DELETE' });
      invalidate('/api/channels');
      setDeletingChannelId(null);
    } catch (e) {}
  };

  const handleRefreshStats = async (cid: string) => {
    try {
      await apiPost(`/api/channels/refresh-stats?channel_id=${cid}`);
      invalidate('/api/channels');
    } catch (e) {}
  };



  const isLoading = activeSubTab === 'channels' ? isChannelsLoading : isNichesLoading;

  return (
    <div className="space-y-6">
      {/* Sub-tab Switcher */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h2 className="disp text-2xl font-extrabold text-[var(--heading)]" style={{ textShadow: '0 0 18px rgba(244,95,206,.30)' }}>Kênh & Niche <span className="text-[15px] tracking-[3px] text-[var(--accent)]" style={{ textShadow: '0 0 10px rgba(244,95,206,.65)' }}>⋆｡˚✧</span></h2>
          <p className="text-xs text-[var(--text2)]">Quản lý định dạng phân phối và ngách nội dung</p>
        </div>
        <div className="flex gap-2">
          <div className="flex text-xs rounded-full border-2 border-[var(--ink)] bg-[var(--surface3)] p-[3px]" style={{ boxShadow: 'var(--shadow-hard-sm)' }}>
            <button
              onClick={() => setActiveSubTab('channels')}
              className={`disp px-3.5 py-1.5 rounded-full font-bold cursor-pointer transition-colors border-2 ${
                activeSubTab === 'channels'
                  ? 'bg-[var(--surface)] text-[var(--accent)] border-[var(--ink)]'
                  : 'border-transparent text-[var(--text2)] hover:text-[var(--accent)]'
              }`}
            >
              Danh sách Kênh
            </button>
            <button
              onClick={() => setActiveSubTab('niches')}
              className={`disp px-3.5 py-1.5 rounded-full font-bold cursor-pointer transition-colors border-2 ${
                activeSubTab === 'niches'
                  ? 'bg-[var(--surface)] text-[var(--accent)] border-[var(--ink)]'
                  : 'border-transparent text-[var(--text2)] hover:text-[var(--accent)]'
              }`}
            >
              Ý tưởng & Ngách
            </button>
          </div>
          {activeSubTab === 'channels' && (
            <Button variant="primary" size="sm" onClick={() => setIsAddModalOpen(true)}>
              <Plus size={14} />
              <span>Thêm Kênh</span>
            </Button>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          <Skeleton h="160px" />
          <Skeleton h="160px" />
        </div>
      ) : activeSubTab === 'channels' ? (
        /* ── SUB-TAB 1: CHANNEL LIST ────────────────────────────────────────── */
        <div className="space-y-4">
          {channels.length === 0 ? (
            <EmptyState
              icon={<Tv size={32} />}
              title="Chưa cấu hình kênh nào"
              desc="Bấm nút Thêm Kênh phía trên để cấu hình kênh sản xuất mới."
            />
          ) : (
            <DataTable
                data={channels}
                searchKey={(c: any) => `${c.name || ''} ${c.channel_id || ''} ${c.niche || ''}`}
                columns={[
                  {
                    header: 'Kênh',
                    accessor: (c: any) => (
                      <div className="py-1">
                        <span className="font-semibold block text-[var(--heading)]">{c.name}</span>
                        <span className="text-[10px] text-[var(--text3)] font-mono">{c.channel_id}</span>
                      </div>
                    )
                  },
                  {
                    header: 'Trạng thái',
                    accessor: (c: any) => (
                      <span title={c.enabled ? `Scheduler đang bật. Chạy theo tần suất ${c.cadence || 'daily'}.` : 'Scheduler cho kênh này đã bị tắt. Kênh sẽ không chạy tự động.'}>
                        <Badge variant={c.enabled ? 'green' : 'neutral'}>
                          {c.enabled ? 'Active' : 'Lịch tắt'}
                        </Badge>
                      </span>
                    )
                  },
                  {
                    header: 'Niche',
                    accessor: (c: any) => <span className="font-mono text-xs">{c.niche || '—'}</span>
                  },
                  {
                    header: 'Views',
                    accessor: (c: any) => <span className="font-mono text-xs text-[var(--text)]">{c.total_views?.toLocaleString() || 0}</span>
                  },
                  {
                    header: 'Subs',
                    accessor: (c: any) => <span className="font-mono text-xs text-[var(--text)]">{c.subscribers?.toLocaleString() || 0}</span>
                  },
                  {
                    header: 'Videos',
                    accessor: (c: any) => <span className="font-mono text-xs text-[var(--text)]">{c.video_count || 0}</span>
                  },
                  {
                    header: 'Doanh thu',
                    accessor: (c: any) => (
                      <span className="font-mono text-xs font-semibold text-[var(--green-ink)]">
                        {c.est_revenue_usd ? `$${c.est_revenue_usd.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '$0.00'}
                      </span>
                    )
                  },
                  {
                    header: 'Giọng đọc',
                    accessor: (c: any) => (
                      <span className="font-mono text-[10px] truncate max-w-[120px] block" title={c.voice_profile}>
                        {c.voice_profile ? (c.voice_profile.includes(':') ? c.voice_profile.split(':')[1] : c.voice_profile) : 'Mặc định'}
                      </span>
                    )
                  },
                  {
                    header: 'Tần suất',
                    accessor: (c: any) => <span className="font-mono text-xs">{c.cadence || 'daily'}</span>
                  }
                ]}
                actions={(c: any) => (
                  <div className="flex gap-1.5 justify-end">
                    <button
                      type="button"
                      onClick={() => {
                        setEditingChannel(c);
                        setJsonConfig(JSON.stringify(c, null, 2));
                        setFormName(c.name || '');
                        setFormNiche(c.niche || '');
                        setFormVoice(c.voice_profile || '');
                        setFormCadence(c.cadence || 'daily');
                        setFormEnabled(!!c.enabled);
                        setFormShorts(!!c.shorts);
                        setFormUpload(!!c.upload);
                        setShowAdvanced(false);
                      }}
                      className="px-2.5 py-1 bg-[var(--surface)] hover:bg-[var(--accent-soft)] border-[1.5px] border-[var(--ink)] text-[10px] rounded-full font-bold text-[var(--accent)] cursor-pointer"
                      style={{ boxShadow: 'var(--shadow-hard-sm)' }}
                    >
                      Sửa Config
                    </button>
                    <button
                      type="button"
                      onClick={() => handleRefreshStats(c.channel_id)}
                      className="px-2.5 py-1 bg-[var(--surface)] hover:bg-[var(--surface2)] border-[1.5px] border-[var(--ink)] text-[10px] rounded-full font-bold text-[var(--text2)] cursor-pointer"
                      style={{ boxShadow: 'var(--shadow-hard-sm)' }}
                      title="Intel Scan & Refresh Stats"
                    >
                      Intel Scan
                    </button>
                    <button
                      type="button"
                      onClick={() => setDeletingChannelId(c.channel_id)}
                      className="px-2.5 py-1 bg-[var(--red-soft)] hover:bg-[var(--red)] hover:text-white border-[1.5px] border-[var(--ink)] text-[10px] rounded-full font-bold text-[var(--red)] cursor-pointer transition-colors"
                      style={{ boxShadow: 'var(--shadow-hard-sm)' }}
                    >
                      Xóa
                    </button>
                  </div>
                )}
              />
          )}
        </div>
      ) : (
        /* ── SUB-TAB 2: NICHES SCANNER ───────────────────────────────────────── */
        <div className="space-y-4">
          <div className="flex items-center justify-between p-4 border-2 border-[var(--ink)] rounded-[18px] gap-4 flex-wrap" style={{ background: 'var(--surface-gradient)', boxShadow: 'var(--shadow-hard), var(--glow)' }}>
            <div>
              <h3 className="font-semibold text-sm text-[var(--heading)]">Quét ngách tự động</h3>
              <p className="text-xs text-[var(--text2)] mt-0.5">Quét xu hướng, lượng tìm kiếm và đề xuất các ngách nội dung tiềm năng cao</p>
            </div>
            <span className="relative" onMouseEnter={() => setShowQuota(true)} onMouseLeave={() => setShowQuota(false)}>
            {showQuota && (
              <div className="absolute right-0 bottom-full mb-2 w-[290px] p-3.5 rounded-[14px] z-50"
                   style={{ background: 'var(--surface)', border: '2px solid var(--ink)', boxShadow: 'var(--shadow-hard)' }}>
                <div className="flex items-center justify-between text-[11px] font-bold text-[var(--heading)]">
                  <span>YouTube API quota</span>
                  <span className="mono">Reset 07:00 sáng</span>
                </div>
                <div className="mt-2.5 flex items-center justify-between text-[11px]">
                  <span className="font-semibold text-[var(--text2)]">Hôm nay ({quota.scans} lần quét)</span>
                  <span className="mono font-bold text-[var(--heading)]">còn ~{quota.leftPct}%</span>
                </div>
                <div className="mt-1.5 h-2 rounded-full overflow-hidden" style={{ background: 'var(--surface3)' }}>
                  <div className="h-full rounded-full" style={{ width: `${quota.leftPct}%`, background: 'linear-gradient(90deg,#6fa8ff,#5f8bff)' }} />
                </div>
                <div className="mt-1.5 text-[10px] mono text-[var(--text3)]">
                  ≈ {quota.left.toLocaleString('vi')} / 10.000 units · mỗi lần quét ≈ 4.300
                </div>
              </div>
            )}
            <Button
              variant="primary"
              size="sm"
              onClick={async () => {
                await apiPost('/api/discover-niches');
                invalidate('/api/niches');
              }}
              className="text-xs"
            >
              <Compass size={14} />
              <span>Chạy quét ngách mới</span>
            </Button>
            </span>
          </div>

          {niches.length === 0 ? (
            <EmptyState
              icon={<Users size={32} />}
              title="Chưa quét ý tưởng ngách"
              desc="Bấm nút Quét ngách phía trên để hệ thống thu thập thông tin thị trường."
            />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {niches.map((n: any, idx: number) => {
                const name = n.niche_name || n.name || 'Ngách chưa đặt tên';
                const score = Number(n.total_score ?? n.score ?? 0);
                const isDup = !!n._duplicate_of;
                const mom = n.momentum;
                return (
                <Card key={idx} onClick={() => setNicheDetail(n)}
                      className={`space-y-2 cursor-pointer hover:border-[var(--accent)] transition-colors ${isDup ? 'opacity-55' : ''}`}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-bold text-sm text-[var(--heading)] truncate">{name}</span>
                    <span className="flex items-center gap-1.5 shrink-0">
                      {mom === 'rising' && <Badge variant="green">↑ tăng tốc {n.momentum_delta > 0 ? `+${n.momentum_delta}` : ''}</Badge>}
                      {mom === 'cooling' && <Badge variant="amber">↓ nguội {n.momentum_delta}</Badge>}
                      {mom === 'new' && <Badge variant="purple">mới</Badge>}
                      {isDup && <Badge variant="neutral">đã có trong kho</Badge>}
                      <Badge variant={score >= 85 ? 'green' : 'blue'}>{score} pts</Badge>
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-[10px] font-mono text-[var(--text3)]">
                    <span>{n.category || '—'}</span>
                    <span>· RPM ~${Number(n.estimated_rpm ?? 0).toFixed(0)}</span>
                    <span>· D{n.demand_score ?? '–'} G{n.gap_score ?? '–'} R{n.rpm_score ?? '–'} S{n.specificity_score ?? '–'}</span>
                  </div>
                  <p className="text-xs text-[var(--text2)] leading-relaxed">
                    {n.why_opportunity || n.audience_description || '—'}
                  </p>
                </Card>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ── NICHE DETAIL DRAWER ── */}
      <Drawer isOpen={nicheDetail !== null} onClose={() => setNicheDetail(null)}
              title={nicheDetail?.niche_name || 'Chi tiết ngách'}>
        {nicheDetail && (
          <div className="space-y-4 text-xs">
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge variant="blue">{nicheDetail.category}</Badge>
              <Badge variant="green">{nicheDetail.total_score} pts</Badge>
              <Badge variant="purple">RPM ~${Number(nicheDetail.estimated_rpm ?? 0).toFixed(0)}</Badge>
              {nicheDetail.momentum && <Badge variant={nicheDetail.momentum === 'rising' ? 'green' : 'amber'}>{nicheDetail.momentum}{nicheDetail.momentum_delta ? ` ${nicheDetail.momentum_delta > 0 ? '+' : ''}${nicheDetail.momentum_delta}` : ''}</Badge>}
              {nicheDetail._duplicate_of && <Badge variant="neutral">đã có trong kho</Badge>}
            </div>
            <div className="mono text-[11px] text-[var(--text3)]">Demand {nicheDetail.demand_score} · Gap {nicheDetail.gap_score} · RPM {nicheDetail.rpm_score} · Specificity {nicheDetail.specificity_score} · Thị trường {nicheDetail.market || 'US'}</div>
            {[['Vì sao là cơ hội', nicheDetail.why_opportunity],
              ['Khán giả', nicheDetail.audience_description]].map(([t, v]: any) => v && (
              <div key={t}><div className="font-bold text-[var(--heading)] mb-1">{t}</div>
                <p className="text-[var(--text2)] leading-relaxed">{v}</p></div>
            ))}
            {[['Nỗi đau khán giả', nicheDetail.pain_points],
              ['Chủ đề kích hoạt', nicheDetail.content_triggers],
              ['Tiêu đề đang nổ', nicheDetail.breakout_titles]].map(([t, arr]: any) => Array.isArray(arr) && arr.length > 0 && (
              <div key={t}><div className="font-bold text-[var(--heading)] mb-1">{t}</div>
                <ul className="list-disc pl-4 space-y-1 text-[var(--text2)]">{arr.slice(0, 6).map((x: any, i: number) => <li key={i}>{String(x)}</li>)}</ul></div>
            ))}
            {Array.isArray(nicheDetail.evidence) && nicheDetail.evidence.length > 0 && (
              <div><div className="font-bold text-[var(--heading)] mb-1">Kênh bằng chứng ({nicheDetail.evidence.length})</div>
                <div className="space-y-1.5">{nicheDetail.evidence.slice(0, 6).map((e: any, i: number) => (
                  <a key={i} href={e.channel_url} target="_blank" rel="noreferrer"
                     className="block p-2 rounded-[10px] border border-[var(--border-soft)] hover:border-[var(--accent)]">
                    <span className="font-semibold text-[var(--heading)]">{e.channel}</span>
                    <span className="mono text-[10px] text-[var(--text3)] ml-2">{Number(e.subs ?? e.subscribers ?? 0).toLocaleString('vi')} subs{e.outlier ? ` · outlier ×${e.outlier}` : ''}</span>
                  </a>))}</div></div>
            )}
            <div className="pt-2 border-t border-[var(--border-soft)] flex justify-end">
              <Button variant="primary" size="sm" onClick={async () => {
                await apiPost(`/api/vault/create-channel/${encodeURIComponent(nicheDetail.niche_id)}`);
                setNicheDetail(null);
                invalidate('/api/channels');
              }}>Tạo kênh từ ngách này</Button>
            </div>
          </div>
        )}
      </Drawer>

      {/* ── EDIT CHANNEL DRAWER (FORM-FIRST CONFIG EDITOR) ───────────────────────── */}
      <Drawer
        isOpen={editingChannel !== null}
        onClose={() => {
          setEditingChannel(null);
          setJsonConfig('');
          setJsonError(null);
        }}
        title={editingChannel ? `Cấu hình Kênh: ${editingChannel.name}` : 'Sửa Kênh'}
      >
        {editingChannel && (
          <div className="space-y-4 h-full flex flex-col justify-between pb-6 overflow-y-auto scrollbar-thin">
            <div className="space-y-4 flex-1">
              
              {/* Field 1: Name */}
              <div className="space-y-1">
                <label className="text-xs font-semibold text-[var(--text2)] block">Tên Kênh</label>
                <Input
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  placeholder="E.g., Kênh Tin tức AI"
                />
              </div>

              {/* Field 2: Niche */}
              <div className="space-y-1">
                <label className="text-xs font-semibold text-[var(--text2)] block">Ngách nội dung (Niche)</label>
                <Input
                  value={formNiche}
                  onChange={(e) => setFormNiche(e.target.value)}
                  placeholder="E.g., history, technology, finance..."
                />
              </div>

              {/* Field 3: Voice Picker */}
              <div className="space-y-1.5 p-3 bg-[var(--surface2)] border-[1.5px] border-[var(--border-soft)] rounded-[12px]">
                <label className="text-xs font-bold text-[var(--heading)] uppercase tracking-wider block mb-1">Giọng đọc & TTS</label>
                <VoicePicker
                  selectedVoice={formVoice}
                  onChange={setFormVoice}
                  channelId={editingChannel.channel_id}
                />
              </div>

              {/* Field 4: Cadence & Options */}
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div className="space-y-1">
                  <label className="font-semibold text-[var(--text2)] block">Tần suất</label>
                  <Select
                    value={formCadence}
                    onChange={(e) => setFormCadence(e.target.value)}
                  >
                    <option value="daily">daily (Hàng ngày)</option>
                    <option value="3x_weekly">3x_weekly (3 lần/tuần)</option>
                    <option value="twice_weekly">twice_weekly (2 lần/tuần)</option>
                    <option value="weekly">weekly (Hàng tuần)</option>
                  </Select>
                </div>
                
                <div className="space-y-2 pt-5">
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="edit-enabled"
                      checked={formEnabled}
                      onChange={(e: any) => setFormEnabled(e.target.checked)}
                    />
                    <label htmlFor="edit-enabled" className="font-semibold text-[var(--text)] select-none cursor-pointer">
                      Bật chạy Scheduler
                    </label>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 text-xs">
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="edit-shorts"
                    checked={formShorts}
                    onChange={(e: any) => setFormShorts(e.target.checked)}
                  />
                  <label htmlFor="edit-shorts" className="font-semibold text-[var(--text)] select-none cursor-pointer">
                    Shorts (9:16)
                  </label>
                </div>

                <div className="flex items-center gap-2">
                  <Checkbox
                    id="edit-upload"
                    checked={formUpload}
                    onChange={(e: any) => setFormUpload(e.target.checked)}
                  />
                  <label htmlFor="edit-upload" className="font-semibold text-[var(--text)] select-none cursor-pointer">
                    Tự động Đăng (Auto Upload)
                  </label>
                </div>
              </div>

              {/* Visual Subtitle Style Editor (V2) */}
              <div className="space-y-3 p-3 bg-[var(--surface2)] border-[1.5px] border-[var(--border-soft)] rounded-[12px]">
                <span className="text-xs font-bold text-[var(--heading)] uppercase tracking-wider block">Thiết lập Phụ đề nhanh</span>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="space-y-1">
                    <label className="font-semibold text-[var(--text2)] block">Preset màu</label>
                    <Select
                      value={(() => {
                        try {
                          return JSON.parse(jsonConfig).subtitle_style?.preset || '';
                        } catch(e) { return ''; }
                      })()}
                      onChange={(e) => {
                        try {
                          const parsed = JSON.parse(jsonConfig);
                          parsed.subtitle_style = parsed.subtitle_style || {};
                          parsed.subtitle_style.preset = e.target.value;
                          setJsonConfig(JSON.stringify(parsed, null, 2));
                        } catch(err) {}
                      }}
                    >
                      <option value="">Mặc định (Trắng)</option>
                      <option value="Classic Vàng">Classic Vàng</option>
                      <option value="Neon Hồng">Neon Hồng</option>
                      <option value="Neon Tím">Neon Tím</option>
                      <option value="Neon Đỏ">Neon Đỏ</option>
                      <option value="Neon Xanh">Neon Xanh</option>
                      <option value="Bạc Ánh Kim">Bạc Ánh Kim</option>
                      <option value="Ngọc Trai">Ngọc Trai</option>
                      <option value="Pastel Xanh">Pastel Xanh</option>
                      <option value="Pastel Hồng">Pastel Hồng</option>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <label className="font-semibold text-[var(--text2)] block">Hiệu ứng chữ</label>
                    <Select
                      value={(() => {
                        try {
                          return JSON.parse(jsonConfig).subtitle_style?.effect || '';
                        } catch(e) { return ''; }
                      })()}
                      onChange={(e) => {
                        try {
                          const parsed = JSON.parse(jsonConfig);
                          parsed.subtitle_style = parsed.subtitle_style || {};
                          parsed.subtitle_style.effect = e.target.value;
                          setJsonConfig(JSON.stringify(parsed, null, 2));
                        } catch(err) {}
                      }}
                    >
                      <option value="">Mặc định (Viền mảnh)</option>
                      <option value="Viền dày">Viền dày</option>
                      <option value="Viền kép">Viền kép</option>
                      <option value="Glow">Glow</option>
                      <option value="Shadow">Shadow</option>
                      <option value="Bóng mềm">Bóng mềm</option>
                      <option value="Chữ rỗng">Chữ rỗng</option>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <label className="font-semibold text-[var(--text2)] block">Font chữ</label>
                    <Select
                      value={(() => {
                        try {
                          return JSON.parse(jsonConfig).subtitle_style?.fontname || 'Arial';
                        } catch(e) { return 'Arial'; }
                      })()}
                      onChange={(e) => {
                        try {
                          const parsed = JSON.parse(jsonConfig);
                          parsed.subtitle_style = parsed.subtitle_style || {};
                          parsed.subtitle_style.fontname = e.target.value;
                          setJsonConfig(JSON.stringify(parsed, null, 2));
                        } catch(err) {}
                      }}
                    >
                      <option value="Arial">Arial</option>
                      <option value="Georgia">Georgia</option>
                      <option value="Impact">Impact</option>
                      <option value="Courier New">Courier New</option>
                      <option value="Times New Roman">Times New Roman</option>
                      <option value="Verdana">Verdana</option>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <label className="font-semibold text-[var(--text2)] block">Cỡ chữ</label>
                    <Input
                      type="number"
                      value={(() => {
                        try {
                          return JSON.parse(jsonConfig).subtitle_style?.fontsize || 54;
                        } catch(e) { return 54; }
                      })()}
                      onChange={(e) => {
                        try {
                          const parsed = JSON.parse(jsonConfig);
                          parsed.subtitle_style = parsed.subtitle_style || {};
                          parsed.subtitle_style.fontsize = parseInt(e.target.value) || 54;
                          setJsonConfig(JSON.stringify(parsed, null, 2));
                        } catch(err) {}
                      }}
                    />
                  </div>
                </div>
              </div>

              {/* Advanced collapsable section */}
              <div className="border-t border-[var(--border-soft)] pt-3 mt-3">
                <button
                  type="button"
                  onClick={() => setShowAdvanced(!showAdvanced)}
                  className="text-xs font-semibold text-[var(--text2)] hover:text-[var(--text)] flex items-center gap-1 cursor-pointer"
                >
                  {showAdvanced ? '▼' : '▶'} Cấu hình JSON nâng cao
                </button>
                {showAdvanced && (
                  <div className="mt-2 space-y-2">
                    <textarea
                      value={jsonConfig}
                      onChange={(e) => {
                        setJsonConfig(e.target.value);
                        setJsonError(null);
                      }}
                      className="w-full min-h-[250px] p-2.5 font-mono text-[10px] text-[var(--text)] border-2 border-[var(--ink)] rounded-[10px] focus:outline-hidden focus:border-[var(--accent)] resize-none"
                      style={{ background: 'var(--surface3)' }}
                    />
                    {jsonError && (
                      <div className="p-2 bg-[var(--red-soft)] border-2 border-[var(--red)] rounded-[10px] text-xs text-[var(--red)] font-semibold leading-relaxed">
                        Lỗi cú pháp: {jsonError}
                      </div>
                    )}
                  </div>
                )}
              </div>

            </div>

            <div className="flex items-center justify-end gap-2 pt-4 border-t-2 border-[var(--border-soft)] mt-4">
              <Button
                variant="ghost"
                onClick={() => {
                  setEditingChannel(null);
                  setJsonConfig('');
                  setJsonError(null);
                }}
              >
                Hủy
              </Button>
              <Button
                variant="primary"
                onClick={handleSaveChannelConfig}
              >
                Lưu cấu hình
              </Button>
            </div>
          </div>
        )}
      </Drawer>

      {/* ── ADD CHANNEL MODAL ──────────────────────────────────────────────── */}
      <Modal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        title="Thêm Kênh sản xuất mới"
      >
        <div className="space-y-4">
          <div className="space-y-1">
            <label className="text-xs font-semibold text-[var(--text2)] block">Mã kênh (Channel ID)</label>
            <Input
              value={newChannelId}
              onChange={(e) => setNewChannelId(e.target.value)}
              placeholder="E.g., code_niche, news_world..."
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-semibold text-[var(--text2)] block">Tên Kênh hiển thị</label>
            <Input
              value={newChannelName}
              onChange={(e) => setNewChannelName(e.target.value)}
              placeholder="E.g., Học Lập Trình 24h"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-semibold text-[var(--text2)] block">Niche (Ngách nội dung)</label>
            <Input
              value={newChannelNiche}
              onChange={(e) => setNewChannelNiche(e.target.value)}
              placeholder="E.g., programming"
            />
          </div>

          <div className="flex items-center justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setIsAddModalOpen(false)}>Hủy</Button>
            <Button variant="primary" onClick={handleAddChannel}>Thêm Kênh</Button>
          </div>
        </div>
      </Modal>

      {/* ── DELETE CHANNEL MODAL ───────────────────────────────────────────── */}
      <Modal
        isOpen={deletingChannelId !== null}
        onClose={() => setDeletingChannelId(null)}
        title="Xác nhận xóa kênh"
      >
        <div className="space-y-4">
          <p className="text-xs text-[var(--text2)] leading-relaxed">
            Bạn có chắc chắn muốn xóa kênh <span className="font-bold text-[var(--text)]">{deletingChannelId}</span>? Hành động này sẽ loại bỏ cấu hình và không thể hoàn tác.
          </p>
          <div className="flex items-center justify-end gap-2">
            <Button variant="ghost" onClick={() => setDeletingChannelId(null)}>Hủy</Button>
            <Button variant="danger" onClick={handleDeleteChannel}>Xóa kênh</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};