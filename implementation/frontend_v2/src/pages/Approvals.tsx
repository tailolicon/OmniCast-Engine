import React, { useState } from 'react';
import { Link } from 'react-router';
import { useApi, useInvalidate } from '../api/hooks';
import { apiPost, getMediaUrl } from '../api/client';
import {
  Button,
  Card,
  Skeleton,
  EmptyState,
  Select,
  Checkbox,
  Badge,
  Modal
} from '../components/ui';
import { Film, Check, X, ShieldAlert, ExternalLink } from 'lucide-react';

/** Real per-video platform metrics for one approval (O8 rule: no fake numbers).
 *  A separate component so the hook call stays outside the .map() loop. */
const ApprovalMetrics: React.FC<{ channelId?: string; postId?: string }> = ({ channelId, postId }) => {
  const { data } = useApi<any>(channelId ? `/api/platforms/metrics?channel_id=${channelId}` : '');
  const metrics: any[] = data?.metrics || [];
  const m = metrics.find((x: any) => x.post_id === postId);
  if (!m) {
    return (
      <div className="pt-2 text-[10px] text-[var(--text3)]">
        Chưa có số liệu hiệu năng thật cho video này — xem tab{' '}
        <Link to="/analytics" className="text-[var(--blue)] hover:underline">Phân tích</Link> sau khi đồng bộ nền tảng.
      </div>
    );
  }
  const watchHrs = m.watch_time_seconds ? (m.watch_time_seconds / 3600).toFixed(2) : '0.00';
  return (
    <div className="pt-2">
      <span className="text-[10px] font-bold text-[var(--text2)] uppercase tracking-wider block mb-1">Hiệu năng kênh đăng tải</span>
      <div className="overflow-x-auto rounded-[12px] border-2 border-[var(--ink)] max-w-lg" style={{ boxShadow: 'var(--shadow-hard-sm)' }}>
        <table className="w-full text-left border-collapse text-[10px] font-mono">
          <thead>
            <tr className="bg-[var(--surface2)] border-b-2 border-[var(--ink)] text-[var(--text3)] uppercase">
              <th className="p-1 px-2 font-bold">Nền tảng</th>
              <th className="p-1 px-2 font-bold">Lượt xem</th>
              <th className="p-1 px-2 font-bold">Lượt thích</th>
              <th className="p-1 px-2 font-bold">Giờ xem</th>
              <th className="p-1 px-2 font-bold">Doanh thu</th>
            </tr>
          </thead>
          <tbody>
            <tr className="divide-y divide-[var(--border-soft)] text-[var(--text)]">
              <td className="p-1 px-2 font-semibold text-[var(--blue)] uppercase">{m.platform_id}</td>
              <td className="p-1 px-2">{(m.views || 0).toLocaleString()}</td>
              <td className="p-1 px-2">{(m.likes || 0).toLocaleString()}</td>
              <td className="p-1 px-2">{watchHrs}h</td>
              <td className="p-1 px-2 text-[var(--green-ink)]">${(m.revenue || 0).toFixed(2)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
};

const formatTimeAgo = (ts?: string) => {
  if (!ts) return 'vừa xong';
  try {
    const date = new Date(ts);
    const diffMs = Date.now() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'vừa xong';
    if (diffMins < 60) return `${diffMins} phút trước`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours} giờ trước`;
    return `${Math.floor(diffHours / 24)} ngày trước`;
  } catch (e) {
    return 'vừa xong';
  }
};

export const Approvals: React.FC = () => {
  const invalidate = useInvalidate();
  
  // Modal Control States
  const [approveItem, setApproveItem] = useState<any | null>(null);
  const [rejectItem, setRejectItem] = useState<any | null>(null);
  
  // Approve Modal States
  const [privacyStatus, setPrivacyStatus] = useState<string>('unlisted');
  const [isForce, setIsForce] = useState<boolean>(false);
  const [approveNote, setApproveNote] = useState<string>('');

  // Destinations toggle states
  const [uploadYouTube, setUploadYouTube] = useState<boolean>(true);
  const [uploadTikTok, setUploadTikTok] = useState<boolean>(false);
  const [uploadFacebook, setUploadFacebook] = useState<boolean>(false);

  // Reject Modal States
  const [rejectNote, setRejectNote] = useState<string>('');

  // V6 — bulk actions state
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkPrivacy, setBulkPrivacy] = useState<string>('unlisted');
  const [isBulkRunning, setIsBulkRunning] = useState(false);

  // Queries
  const { data: approvalsData, isLoading: isApprovalsLoading } = useApi<any>('/api/approvals');
  const approvals = approvalsData?.approvals || [];
  const pendingApprovals = approvals.filter((a: any) => a.status === 'waiting_approval' || a.status === 'pending');

  const toggleSelected = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const toggleSelectAll = () => {
    setSelectedIds((prev) =>
      prev.size === pendingApprovals.length ? new Set() : new Set(pendingApprovals.map((a: any) => a.approval_id))
    );
  };
  const handleBulkApprove = async () => {
    if (selectedIds.size === 0) return;
    setIsBulkRunning(true);
    try {
      for (const id of selectedIds) {
        try {
          await apiPost(`/api/approvals/${id}/approve`, {
            privacy_status: bulkPrivacy, force: false, note: 'Duyệt hàng loạt', operator: 'dashboard',
          });
        } catch (e) {}
      }
      invalidate('/api/approvals');
      setSelectedIds(new Set());
    } finally {
      setIsBulkRunning(false);
    }
  };

  // ── Approvals actions ──────────────────────────────────────────────────────
  const handleApprove = async () => {
    if (!approveItem) return;
    try {
      const dests = [];
      if (uploadYouTube) dests.push('youtube');
      if (uploadTikTok) dests.push('tiktok');
      if (uploadFacebook) dests.push('facebook');

      await apiPost(`/api/approvals/${approveItem.approval_id}/approve`, {
        privacy_status: privacyStatus,
        force: isForce,
        note: approveNote,
        operator: 'dashboard',
        destinations: dests
      });
      invalidate('/api/approvals');
      setApproveItem(null);
      setApproveNote('');
      setIsForce(false);
      setPrivacyStatus('unlisted');
      setUploadYouTube(true);
      setUploadTikTok(false);
      setUploadFacebook(false);
    } catch (e) {}
  };

  const handleReject = async () => {
    if (!rejectItem) return;
    try {
      await apiPost(`/api/approvals/${rejectItem.approval_id}/reject`, {
        note: rejectNote,
        operator: 'dashboard'
      });
      invalidate('/api/approvals');
      setRejectItem(null);
      setRejectNote('');
    } catch (e) {}
  };

  const isLoading = isApprovalsLoading;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h2 className="disp text-2xl font-extrabold text-[var(--heading)]" style={{ textShadow: '0 0 18px rgba(244,95,206,.30)' }}>Duyệt & Đăng <span className="text-[15px] tracking-[3px] text-[var(--accent)]" style={{ textShadow: '0 0 10px rgba(244,95,206,.65)' }}>⋆｡˚✧</span></h2>
          <p className="text-xs text-[var(--text2)]">Quản lý kiểm duyệt sản xuất và các kênh đăng tải</p>
        </div>
        <div className="flex gap-1 text-xs">
          <span className="px-3.5 py-1.5 rounded-full font-bold text-[var(--accent)] bg-[var(--surface)] border-2 border-[var(--ink)]" style={{ boxShadow: 'var(--shadow-hard-sm)' }}>
            Hàng đợi Duyệt ({approvals.length})
          </span>
        </div>
      </div>

      {/* V6 — bulk actions bar */}
      {pendingApprovals.length > 0 && (
        <div className="flex items-center gap-3 p-3 rounded-[14px] border-2 border-[var(--ink)] bg-[var(--surface)] flex-wrap" style={{ boxShadow: 'var(--shadow-hard-sm)' }}>
          <label className="flex items-center gap-2 text-xs font-semibold text-[var(--text2)] cursor-pointer">
            <Checkbox checked={selectedIds.size === pendingApprovals.length && pendingApprovals.length > 0} onChange={toggleSelectAll} />
            Chọn tất cả ({selectedIds.size}/{pendingApprovals.length})
          </label>
          {selectedIds.size > 0 && (
            <>
              <Select value={bulkPrivacy} onChange={(e) => setBulkPrivacy(e.target.value)} className="!py-1 text-xs w-32">
                <option value="private">Private</option>
                <option value="unlisted">Unlisted</option>
                <option value="public">Public</option>
              </Select>
              <Button variant="primary" size="sm" onClick={handleBulkApprove} disabled={isBulkRunning}>
                <Check size={12} />
                <span>{isBulkRunning ? 'Đang duyệt…' : `Duyệt hàng loạt (${selectedIds.size})`}</span>
              </Button>
            </>
          )}
        </div>
      )}

      {isLoading ? (
        <div className="space-y-4">
          <Skeleton h="120px" />
          <Skeleton h="120px" />
        </div>
      ) : (
        /* ── HÀNG ĐỢI DUYỆT LIST ─────────────────────────────────────────────── */
        <div className="space-y-4">
          {approvals.length === 0 ? (
            <EmptyState
              icon={<Film size={32} />}
              title="Chưa có video chờ duyệt"
              desc='Render xong một video rồi bấm "Gửi duyệt đăng" ở tab Sản xuất Video — video sẽ xuất hiện ở đây để bạn duyệt trước khi đăng.'
            />
          ) : (
            approvals.map((a: any) => {
              const thumbUrl = a.raw?.thumbnail_paths?.[0] ? getMediaUrl(a.raw.thumbnail_paths[0]) : '';
              const publishError = a.publish_error || a.raw?.publish_error;
              const ytVideoId = a.raw?.youtube_video_id;
              const isDryRun = !!a.raw?.dry_run;

              return (
                <Card key={a.approval_id} className="flex gap-5 max-md:flex-col items-start p-4 hover:border-[var(--border-hover)] transition-colors">
                  {/* Thumbnail */}
                  <div className="w-40 aspect-video rounded-[12px] overflow-hidden border-2 border-[var(--ink)] shrink-0 relative flex items-center justify-center" style={{ background: 'linear-gradient(135deg,#8db4ff,#b79cff)' }}>
                    {thumbUrl ? (
                      <img src={thumbUrl} className="w-full h-full object-cover" alt="Thumb" />
                    ) : (
                      <Film size={24} className="text-[var(--text3)]" />
                    )}
                    {a.raw?.duration_seconds && (
                      <span className="absolute bottom-1.5 right-1.5 bg-black/75 text-white font-mono text-[10px] px-1 rounded-sm">
                        {Math.floor(a.raw.duration_seconds / 60)}m {a.raw.duration_seconds % 60}s
                      </span>
                    )}
                  </div>
                  {/* Card Content */}
                  <div className="flex-1 space-y-2.5 w-full">
                    <div className="flex items-start justify-between flex-wrap gap-2">
                      <div>
                        <h4 className="font-semibold text-sm text-[var(--heading)] leading-snug">{a.title}</h4>
                        <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                          <Badge variant="blue">{a.platform_id === 'youtube' ? 'YouTube' : a.platform_id}</Badge>
                          {a.raw?.destinations?.map((d: string) => (
                            <Badge key={d} variant="purple">{d.toUpperCase()}</Badge>
                          ))}
                          {isDryRun && <Badge variant="neutral">DRY RUN</Badge>}
                          
                          {/* Risk Badge */}
                          {(() => {
                            const privacy = a.raw?.privacy_status || 'private';
                            const risk = isDryRun || privacy === 'private' ? 'low' : privacy === 'unlisted' ? 'medium' : 'high';
                            const riskConfig = {
                              low: { label: 'Rủi ro: Thấp', variant: 'green' as const },
                              medium: { label: 'Rủi ro: Vừa', variant: 'amber' as const },
                              high: { label: 'Rủi ro: Cao', variant: 'red' as const },
                            };
                            const rCfg = riskConfig[risk];
                            return <Badge variant={rCfg.variant}>{rCfg.label}</Badge>;
                          })()}

                          <span className="text-[11px] text-[var(--text2)] font-mono">{formatTimeAgo(a.created_at)}</span>
                        </div>
                      </div>
                      
                      {/* Action buttons */}
                      {(a.status === 'waiting_approval' || a.status === 'pending') && (
                        <div className="flex items-center gap-2">
                          <Checkbox checked={selectedIds.has(a.approval_id)} onChange={() => toggleSelected(a.approval_id)} />
                          <button
                            onClick={() => setApproveItem(a)}
                            className="disp inline-flex items-center gap-1.5 rounded-full border-2 border-[var(--ink)] px-4 py-1.5 text-xs font-bold text-white cursor-pointer"
                            style={{ background: 'linear-gradient(135deg,var(--green),var(--blue))', boxShadow: 'var(--shadow-hard-sm)' }}
                          >
                            <Check size={12} />
                            <span>Duyệt & Đăng</span>
                          </button>
                          <button
                            onClick={() => setRejectItem(a)}
                            className="disp inline-flex items-center gap-1.5 rounded-full border-2 border-[var(--ink)] px-4 py-1.5 text-xs font-bold text-[var(--red)] bg-[var(--red-soft)] cursor-pointer"
                            style={{ boxShadow: 'var(--shadow-hard-sm)' }}
                          >
                            <X size={12} />
                            <span>Từ chối</span>
                          </button>
                        </div>
                      )}
                    </div>

                    {/* Summary snippet */}
                    {a.summary && (
                      <p className="text-xs text-[var(--text2)] line-clamp-2 leading-relaxed">
                        {a.summary}
                      </p>
                    )}

                    {/* Platform performance — real data only (O8: cấm fake số liệu) */}
                    {(a.status === 'published' || ytVideoId) && (
                      <ApprovalMetrics channelId={a.channel_id} postId={ytVideoId} />
                    )}

                    {/* Published Link */}
                    {ytVideoId && (
                      <div className="pt-2">
                        <a
                          href={`https://youtu.be/${ytVideoId}`}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1.5 text-xs text-[var(--green)] font-bold hover:underline bg-[var(--green-soft)] px-2.5 py-1 rounded-full border-[1.5px] border-[var(--ink)]"
                          style={{ boxShadow: 'var(--shadow-hard-sm)' }}
                        >
                          <ExternalLink size={12} />
                          <span>Xem trên YouTube (ID: {ytVideoId})</span>
                        </a>
                      </div>
                    )}

                    {/* Publish Error Box */}
                    {publishError && (
                      <div className="p-3 bg-[var(--red-soft)] border-2 border-[var(--red)] rounded-[12px] flex items-start gap-2.5 text-xs text-[var(--red)]">
                        <ShieldAlert size={14} className="shrink-0 mt-0.5" />
                        <div>
                          <div className="font-semibold mb-0.5">Lỗi đăng tải</div>
                          <div className="font-mono leading-relaxed break-all">{publishError}</div>
                        </div>
                      </div>
                    )}
                  </div>
                </Card>
              );
            })
          )}
        </div>
      )}

      {/* ── APPROVE MODAL ─────────────────────────────────────────────────── */}
      <Modal
        isOpen={approveItem !== null}
        onClose={() => setApproveItem(null)}
        title="Duyệt đăng video"
      >
        <div className="space-y-4">
          <div className="space-y-1">
            <label className="text-xs font-semibold text-[var(--text2)] block">Chế độ hiển thị (Privacy)</label>
            <Select
              value={privacyStatus}
              onChange={(e) => setPrivacyStatus(e.target.value)}
            >
              <option value="unlisted">Unlisted (Mặc định)</option>
              <option value="private">Private (Riêng tư)</option>
              <option value="public">Public (Công khai)</option>
            </Select>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-[var(--text2)] block">Kênh đăng tải (Destinations)</label>
            <div className="space-y-1.5 p-3 bg-[var(--surface2)] border-[1.5px] border-[var(--border-soft)] rounded-[12px]">
              <div className="flex items-center gap-2">
                <Checkbox
                  id="dest-yt"
                  checked={uploadYouTube}
                  onChange={(e: any) => setUploadYouTube(e.target.checked)}
                />
                <label htmlFor="dest-yt" className="text-xs text-[var(--text)] font-semibold select-none cursor-pointer">
                  YouTube (Long/Shorts Feed)
                </label>
              </div>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="dest-tt"
                  checked={uploadTikTok}
                  onChange={(e: any) => setUploadTikTok(e.target.checked)}
                />
                <label htmlFor="dest-tt" className="text-xs text-[var(--text)] font-semibold select-none cursor-pointer">
                  TikTok (Shorts Feed)
                </label>
              </div>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="dest-fb"
                  checked={uploadFacebook}
                  onChange={(e: any) => setUploadFacebook(e.target.checked)}
                />
                <label htmlFor="dest-fb" className="text-xs text-[var(--text)] font-semibold select-none cursor-pointer">
                  Facebook Reels
                </label>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Checkbox
              id="force-check"
              checked={isForce}
              onChange={(e: any) => setIsForce(e.target.checked)}
            />
            <label htmlFor="force-check" className="text-xs text-[var(--text)] font-semibold select-none cursor-pointer">
              Bỏ qua các cảnh báo kiểm định (Force)
            </label>
          </div>

          <div className="space-y-1">
            <label className="text-xs font-semibold text-[var(--text2)] block">Ghi chú duyệt</label>
            <textarea
              value={approveNote}
              onChange={(e) => setApproveNote(e.target.value)}
              placeholder="Nhập ghi chú hoặc lý do duyệt đăng..."
              className="w-full px-3 py-2 bg-[var(--surface)] border-2 border-[var(--ink)] focus:border-[var(--accent)] focus:outline-hidden rounded-[10px] text-xs min-h-20 transition-colors text-[var(--text)]"
            />
          </div>

          <div className="flex items-center justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setApproveItem(null)}>Hủy</Button>
            <Button variant="primary" onClick={handleApprove}>Xác nhận Duyệt</Button>
          </div>
        </div>
      </Modal>

      {/* ── REJECT MODAL ──────────────────────────────────────────────────── */}
      <Modal
        isOpen={rejectItem !== null}
        onClose={() => setRejectItem(null)}
        title="Từ chối video"
      >
        <div className="space-y-4">
          <div className="space-y-1">
            <label className="text-xs font-semibold text-[var(--text2)] block">Lý do từ chối</label>
            <textarea
              value={rejectNote}
              onChange={(e) => setRejectNote(e.target.value)}
              placeholder="Nhập ghi chú hoặc lý do từ chối kịch bản/video này..."
              className="w-full px-3 py-2 bg-[var(--surface)] border-2 border-[var(--ink)] focus:border-[var(--accent)] focus:outline-hidden rounded-[10px] text-xs min-h-20 transition-colors text-[var(--text)]"
            />
          </div>

          <div className="flex items-center justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setRejectItem(null)}>Hủy</Button>
            <Button variant="danger" onClick={handleReject}>Từ chối</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};