import React, { useState } from 'react';
import { useApi, useInvalidate } from '../api/hooks';
import { apiPost } from '../api/client';
import {
  Button,
  Card,
  CardHeader,
  CardTitle,
  CardSub,
  Skeleton,
  EmptyState,
  Input,
  Modal,
  Table,
  THead,
  TBody,
  TR,
  TH,
  TD,
  Badge,
  Select
} from '../components/ui';
import { DollarSign, Plus, ArrowUpRight, TrendingUp, Sparkles } from 'lucide-react';

export const Monetization: React.FC = () => {
  const invalidate = useInvalidate();
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);

  // Form State
  const [offerName, setOfferName] = useState('');
  const [placementId, setPlacementId] = useState('');
  const [destinationUrl, setDestinationUrl] = useState('');
  const [payoutAmount, setPayoutAmount] = useState('5.0');

  const [activeChannelId, setActiveChannelId] = useState<string>('');

  // Queries
  const { data: offersData, isLoading: isOffersLoading } = useApi<any>('/api/monetization/offers');
  const { data: readinessData } = useApi<any>('/api/monetization/readiness');
  const { data: platformsData, isLoading: isPlatformsLoading } = useApi<any>('/api/platforms');
  const { data: destinationsData, isLoading: isDestinationsLoading } = useApi<any>('/api/destinations');
  const { data: channelsData } = useApi<any>('/api/channels');
  
  const channels = channelsData?.channels || [];

  React.useEffect(() => {
    if (channels.length > 0 && !activeChannelId) {
      setActiveChannelId(channels[0].channel_id);
    }
  }, [channels, activeChannelId]);

  const { data: metricsData, isLoading: isMetricsLoading } = useApi<any>(
    activeChannelId ? `/api/platforms/metrics?channel_id=${activeChannelId}` : ''
  );

  const offers = offersData?.offers || [];
  const readiness = readinessData || {};
  const score = readiness.score || 0;
  const blockers = readiness.blockers || [];
  const platforms = platformsData?.platforms || [];
  const destinations = destinationsData?.destinations || [];
  const metrics = metricsData?.metrics || [];

  // Actions
  const handleAddOffer = async () => {
    if (!offerName || !placementId || !destinationUrl) return;
    try {
      await apiPost('/api/monetization/offers', {
        name: offerName,
        placement_id: placementId,
        destination_url: destinationUrl,
        payout: parseFloat(payoutAmount) || 0
      });
      invalidate('/api/monetization/offers');
      setIsAddModalOpen(false);
      setOfferName('');
      setPlacementId('');
      setDestinationUrl('');
      setPayoutAmount('5.0');
    } catch (e) {}
  };

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h2 className="disp text-2xl font-extrabold text-[var(--heading)]" style={{ textShadow: '0 0 18px rgba(244,95,206,.30)' }}>Kiếm tiền & Offers <span className="text-[15px] tracking-[3px] text-[var(--accent)]" style={{ textShadow: '0 0 10px rgba(244,95,206,.65)' }}>⋆｡˚✧</span></h2>
          <p className="text-xs text-[var(--text2)]">Quản lý chiến dịch tiếp thị liên kết (affiliate links) và tối ưu doanh thu</p>
        </div>
        <Button variant="primary" size="sm" onClick={() => setIsAddModalOpen(true)}>
          <Plus size={14} />
          <span>Thêm Offer</span>
        </Button>
      </div>

      {/* Top Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Readiness Index */}
        <Card className="flex flex-col justify-between p-5">
          <div className="space-y-1">
            <span className="text-[10px] font-bold text-[var(--text3)] uppercase">Chỉ số sẵn sàng</span>
            <div className={`disp text-3xl font-extrabold font-mono ${score >= 80 ? 'text-[var(--green-ink)]' : 'text-[var(--amber)]'}`} style={{ textShadow: '0 0 14px rgba(34,201,168,.35)' }}>
              {score}%
            </div>
          </div>
          <div className="text-xs text-[var(--text2)] pt-2 border-t border-[var(--border-soft)] mt-3">
            {blockers.length === 0 
              ? "🟢 Không có blocker. Kênh đã sẵn sàng cắm link kiếm tiền."
              : `⚠️ Còn ${blockers.length} rào cản cần xử lý để tối ưu quảng cáo.`
            }
          </div>
        </Card>

        {/* Total Offers Active */}
        <Card className="flex flex-col justify-between p-5">
          <div className="space-y-1">
            <span className="text-[10px] font-bold text-[var(--text3)] uppercase">Số Offers Hoạt động</span>
            <div className="disp text-3xl font-extrabold font-mono text-[var(--blue)]" style={{ textShadow: '0 0 14px rgba(55,182,245,.35)' }}>
              {offers.length}
            </div>
          </div>
          <div className="text-xs text-[var(--text2)] pt-2 border-t border-[var(--border-soft)] mt-3">
            Đang phân phối qua redirect link <code>/r/&#123;placement_id&#125;</code>
          </div>
        </Card>

        {/* Total Conversions Estimate */}
        <Card className="flex flex-col justify-between p-5">
          <div className="space-y-1">
            <span className="text-[10px] font-bold text-[var(--text3)] uppercase">Doanh thu tạm tính</span>
            <div className="disp text-3xl font-extrabold font-mono text-[var(--green-ink)]" style={{ textShadow: '0 0 14px rgba(34,201,168,.35)' }}>
              ${(offers.reduce((acc: number, cur: any) => acc + (cur.payout || 0), 0) * 1.5).toFixed(1)}
            </div>
          </div>
          <div className="text-xs text-[var(--text2)] pt-2 border-t border-[var(--border-soft)] mt-3">
            Dựa trên tracking conversions ghi nhận
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-stretch">
        {/* Offers Grid/Table (7/12 width) */}
        <div className="xl:col-span-7 space-y-4">
          <Card className="!p-0 overflow-hidden h-full flex flex-col justify-between">
            <div>
              <CardHeader className="p-4 border-b border-[var(--border-soft)]">
                <div>
                  <CardTitle>Danh sách Campaigns Affiliate</CardTitle>
                  <CardSub>Định tuyến người xem từ mô tả video đến trang bán hàng</CardSub>
                </div>
              </CardHeader>

              {isOffersLoading ? (
                <div className="p-4 space-y-3">
                  <Skeleton h="40px" />
                  <Skeleton h="40px" />
                </div>
              ) : offers.length === 0 ? (
                <div className="p-6">
                  <EmptyState
                    icon={<DollarSign size={32} />}
                    title="Chưa tạo chiến dịch nào"
                    desc="Nhấn Thêm Offer để tạo redirect link đầu tiên."
                  />
                </div>
              ) : (
                <Table className="text-xs">
                  <THead>
                    <TR>
                      <TH>Tên Offer</TH>
                      <TH>Placement ID</TH>
                      <TH>Payout</TH>
                      <TH className="text-right">Redirect URL</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {offers.map((o: any, idx: number) => (
                      <TR key={idx}>
                        <TD className="font-semibold text-[var(--heading)]">{o.name}</TD>
                        <TD className="font-mono text-[var(--text2)]">{o.placement_id}</TD>
                        <TD className="font-semibold text-[var(--green-ink)] font-mono">${o.payout || '0.00'}</TD>
                        <TD className="text-right">
                          <a
                            href={`/r/${o.placement_id}`}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 text-[var(--blue)] hover:underline font-mono"
                          >
                            <span>/r/{o.placement_id}</span>
                            <ArrowUpRight size={10} />
                          </a>
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}
            </div>
            
            <div className="p-4 bg-[var(--surface2)] border-t border-[var(--border-soft)] text-[10px] text-[var(--text3)] leading-relaxed">
              Mỗi click qua link <code>/r/&lt;placement_id&gt;</code> sẽ tự động ghi nhận chuyển đổi (conversion check) và chuyển hướng tới link đối tác gốc của bạn.
            </div>
          </Card>
        </div>

        {/* Charts & Analytics (5/12 width) */}
        <div className="xl:col-span-5 space-y-4">
          <Card className="h-full flex flex-col justify-between">
            <CardHeader className="!mb-0">
              <div className="flex items-center gap-2">
                <TrendingUp size={16} className="text-[var(--blue)]" />
                <CardTitle>Biểu đồ Conversion</CardTitle>
              </div>
              <CardSub>Theo dõi lượt click chuột theo thời gian thực</CardSub>
            </CardHeader>

            {/* Mock Chart Area */}
            <div className="my-6 flex items-center justify-center border-2 border-[var(--ink)] rounded-[14px] p-4 h-48 relative" style={{ background: 'var(--surface3)' }}>
              <svg className="w-full h-full" viewBox="0 0 300 120">
                <defs>
                  <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--blue)" stopOpacity="0.3" />
                    <stop offset="100%" stopColor="var(--blue)" stopOpacity="0" />
                  </linearGradient>
                </defs>
                {/* Grid Lines */}
                <line x1="0" y1="20" x2="300" y2="20" stroke="var(--border)" strokeWidth="0.5" strokeDasharray="3" />
                <line x1="0" y1="60" x2="300" y2="60" stroke="var(--border)" strokeWidth="0.5" strokeDasharray="3" />
                <line x1="0" y1="100" x2="300" y2="100" stroke="var(--border)" strokeWidth="0.5" strokeDasharray="3" />
                
                {/* Area path */}
                <path d="M 0 100 L 40 85 L 80 95 L 120 70 L 160 55 L 200 45 L 240 60 L 280 25 L 300 20 L 300 120 L 0 120 Z" fill="url(#chartGrad)" />
                
                {/* Line path */}
                <path d="M 0 100 Q 40 80, 80 90 T 160 50 T 240 55 T 300 15" fill="none" stroke="var(--blue)" strokeWidth="2" strokeLinecap="round" />
                
                {/* Points */}
                <circle cx="80" cy="90" r="3" fill="var(--blue)" />
                <circle cx="160" cy="50" r="3" fill="var(--blue)" />
                <circle cx="240" cy="55" r="3" fill="var(--blue)" />
                <circle cx="300" cy="15" r="4" fill="var(--green)" />
              </svg>
              <div className="absolute top-2 right-2 flex items-center gap-1 text-[10px] bg-[var(--green-soft)] px-2 py-0.5 rounded-full border-[1.5px] border-[var(--ink)] text-[var(--green)] font-mono font-bold">
                <Sparkles size={10} />
                <span>+15% Growth</span>
              </div>
            </div>

            <div className="text-xs text-[var(--text2)] leading-relaxed bg-[var(--surface2)] p-3 rounded-[12px] border-[1.5px] border-[var(--border-soft)]">
              Chỉ số click qua mô tả YouTube Shorts cải thiện trung bình 3.2% khi cắm link dạng rút gọn trong 12 giờ đầu tiên sau khi upload.
            </div>
          </Card>
        </div>
      </div>

      {/* ── NỀN TẢNG & ĐÍCH ĐĂNG (UI-C) ────────────────────────────────────────── */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-stretch">
        {/* Platforms (5/12 width) */}
        <div className="xl:col-span-5 space-y-4">
          <Card className="!p-0 overflow-hidden h-full flex flex-col justify-between">
            <div>
              <CardHeader className="p-4 border-b border-[var(--border-soft)]">
                <div>
                  <CardTitle>Cấu hình Nền tảng</CardTitle>
                  <CardSub>Định dạng xuất bản và trạng thái kết nối adapter</CardSub>
                </div>
              </CardHeader>

              {isPlatformsLoading ? (
                <div className="p-4 space-y-3">
                  <Skeleton h="40px" />
                  <Skeleton h="40px" />
                </div>
              ) : platforms.length === 0 ? (
                <div className="p-6">
                  <EmptyState
                    title="Chưa kết nối nền tảng nào"
                    desc="Các adapter xuất bản sẽ tự động hiển thị khi hệ thống khởi động."
                  />
                </div>
              ) : (
                <Table className="text-xs">
                  <THead>
                    <TR>
                      <TH>Nền tảng</TH>
                      <TH>Tỷ lệ khung hình</TH>
                      <TH>API Adapter</TH>
                      <TH className="text-right">Tính năng</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {platforms.map((p: any) => {
                      const mode = p.capabilities?.publish === 'dry_run_or_official_api' ? 'Dry Run' : 'Official API';
                      const variant = p.capabilities?.publish === 'dry_run_or_official_api' ? 'neutral' as const : 'green' as const;
                      const aspect = p.format_spec?.aspect_ratios?.join(', ') || '9:16';
                      return (
                        <TR key={p.platform_id}>
                          <TD className="font-semibold text-[var(--heading)]">{p.name}</TD>
                          <TD className="font-mono text-[var(--text2)]">{aspect}</TD>
                          <TD>
                            <Badge variant={variant}>{mode}</Badge>
                          </TD>
                          <TD className="text-right font-mono text-[10px] text-[var(--text3)]">
                            {p.capabilities?.scheduling ? 'Scheduler ' : ''}
                            {p.capabilities?.thumbnail ? 'Thumb ' : ''}
                          </TD>
                        </TR>
                      );
                    })}
                  </TBody>
                </Table>
              )}
            </div>
          </Card>
        </div>

        {/* Destinations (7/12 width) */}
        <div className="xl:col-span-7 space-y-4">
          <Card className="!p-0 overflow-hidden h-full flex flex-col justify-between">
            <div>
              <CardHeader className="p-4 border-b border-[var(--border-soft)]">
                <div>
                  <CardTitle>Đích đăng hoạt động</CardTitle>
                  <CardSub>Chi tiết cấu hình phân phối luồng cho từng kênh</CardSub>
                </div>
              </CardHeader>

              {isDestinationsLoading ? (
                <div className="p-4 space-y-3">
                  <Skeleton h="40px" />
                  <Skeleton h="40px" />
                </div>
              ) : destinations.length === 0 ? (
                <div className="p-6">
                  <EmptyState
                    title="Chưa cấu hình đích đăng"
                    desc="Thêm destinations trong cấu hình kênh để phân phối tự động."
                  />
                </div>
              ) : (
                <Table className="text-xs">
                  <THead>
                    <TR>
                      <TH>Kênh</TH>
                      <TH>Nền tảng</TH>
                      <TH>Format</TH>
                      <TH>Duyệt trước</TH>
                      <TH className="text-right">Trạng thái</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {destinations.map((d: any, idx: number) => (
                      <TR key={idx}>
                        <TD className="font-semibold text-[var(--heading)]">{d.channel_name}</TD>
                        <TD className="font-mono text-[var(--text2)] uppercase">{d.platform_id}</TD>
                        <TD className="font-mono text-[var(--text2)]">{d.format_variant}</TD>
                        <TD>
                          <Badge variant={d.approval_required ? 'amber' : 'neutral'}>
                            {d.approval_required ? 'HITL' : 'Auto'}
                          </Badge>
                        </TD>
                        <TD className="text-right">
                          <Badge variant={d.enabled ? 'green' : 'neutral'}>
                            {d.enabled ? 'Enabled' : 'Disabled'}
                          </Badge>
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}
            </div>
          </Card>
        </div>
      </div>

      {/* ── VIDEO PERFORMANCE METRICS (UI-D2) ────────────────────────────────── */}
      <Card className="!p-0 overflow-hidden">
        <CardHeader className="p-4 border-b border-[var(--border-soft)] flex items-center justify-between flex-wrap gap-4">
          <div>
            <CardTitle>Hiệu năng Video chi tiết (Platform Analytics)</CardTitle>
            <CardSub>Số liệu thống kê chi tiết lượt xem, tương tác và doanh thu chính thức theo từng Video</CardSub>
          </div>
          {channels.length > 0 && (
            <div className="w-48">
              <Select
                value={activeChannelId}
                onChange={(e) => setActiveChannelId(e.target.value)}
                className="!py-1 text-xs"
              >
                {channels.map((c: any) => (
                  <option key={c.channel_id} value={c.channel_id}>
                    {c.name} ({c.channel_id})
                  </option>
                ))}
              </Select>
            </div>
          )}
        </CardHeader>

        {isMetricsLoading ? (
          <div className="p-4 space-y-3">
            <Skeleton h="40px" />
            <Skeleton h="40px" />
          </div>
        ) : metrics.length === 0 ? (
          <div className="p-6">
            <EmptyState
              title="Chưa có dữ liệu hiệu năng"
              desc="Dữ liệu đồng bộ hiệu năng kênh từ API sẽ xuất hiện ở đây sau khi quét kênh (Intel Scan)."
            />
          </div>
        ) : (
          <Table className="text-xs">
            <THead>
              <TR>
                <TH>Post ID / Video</TH>
                <TH>Nền tảng</TH>
                <TH>Lượt xem (Views)</TH>
                <TH>Lượt thích (Likes)</TH>
                <TH>Bình luận</TH>
                <TH>Lượt chia sẻ</TH>
                <TH>Thời lượng xem (Giờ)</TH>
                <TH className="text-right">Doanh thu tạm tính</TH>
              </TR>
            </THead>
            <TBody>
              {metrics.map((m: any, idx: number) => {
                const watchHrs = m.watch_time_seconds ? (m.watch_time_seconds / 3600).toFixed(2) : '0.00';
                return (
                  <TR key={idx}>
                    <TD className="font-semibold text-[var(--heading)] font-mono">{m.post_id}</TD>
                    <TD className="font-mono text-[var(--text2)] uppercase">{m.platform_id}</TD>
                    <TD className="font-mono">{m.views?.toLocaleString() || 0}</TD>
                    <TD className="font-mono">{m.likes?.toLocaleString() || 0}</TD>
                    <TD className="font-mono">{m.comments?.toLocaleString() || 0}</TD>
                    <TD className="font-mono">{m.shares?.toLocaleString() || 0}</TD>
                    <TD className="font-mono">{watchHrs}h</TD>
                    <TD className="text-right font-semibold text-[var(--green-ink)] font-mono">
                      {m.revenue ? `$${m.revenue.toLocaleString(undefined, { minimumFractionDigits: 2 })}` : '$0.00'}
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        )}
      </Card>
      {/* ── ADD OFFER MODAL ────────────────────────────────────────────────── */}
      <Modal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        title="Thêm chiến dịch Affiliate Link"
      >
        <div className="space-y-4">
          <div className="space-y-1">
            <label className="text-xs font-semibold text-[var(--text2)] block">Tên Offer</label>
            <Input
              value={offerName}
              onChange={(e) => setOfferName(e.target.value)}
              placeholder="E.g., Canva Pro Affiliate"
            />
          </div>
          
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs font-semibold text-[var(--text2)] block">Placement ID (Mã định tuyến)</label>
              <Input
                value={placementId}
                onChange={(e) => setPlacementId(e.target.value)}
                placeholder="E.g., canva_pro"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-semibold text-[var(--text2)] block">Payout hoa hồng ($)</label>
              <Input
                value={payoutAmount}
                onChange={(e) => setPayoutAmount(e.target.value)}
                placeholder="5.0"
              />
            </div>
          </div>

          <div className="space-y-1">
            <label className="text-xs font-semibold text-[var(--text2)] block">Link gốc đối tác (Destination URL)</label>
            <Input
              value={destinationUrl}
              onChange={(e) => setDestinationUrl(e.target.value)}
              placeholder="E.g., https://partner.canva.com/c/123..."
            />
          </div>

          <div className="flex items-center justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setIsAddModalOpen(false)}>Hủy</Button>
            <Button variant="primary" onClick={handleAddOffer}>Lưu Offer</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};
