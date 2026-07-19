import React, { useState } from 'react';
import { useApi } from '../api/hooks';
import {
  Card,
  CardHeader,
  CardTitle,
  CardSub,
  Skeleton,
  EmptyState,
  Table,
  THead,
  TBody,
  TR,
  TH,
  TD,
  Select
} from '../components/ui';

export const Analytics: React.FC = () => {
  const [activeChannelId, setActiveChannelId] = useState<string>('');

  // Queries
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
  // I3 — join metrics → published ledger (post_id == youtube_video_id) → product
  // (title match) so each analytics row shows the script/product that made it.
  const { data: publishedData } = useApi<any>(
    activeChannelId ? `/api/published?channel_id=${activeChannelId}` : ''
  );
  const { data: productsData } = useApi<any>(
    activeChannelId ? `/api/products?channel_id=${activeChannelId}` : ''
  );

  const metrics = metricsData?.metrics || [];
  const published: any[] = publishedData?.published || [];
  const products: any[] = productsData?.products || [];
  const norm = (s: string) => (s || '').trim().toLowerCase();

  const sourceForMetric = (m: any) => {
    const pub = published.find((p) => p.youtube_video_id && p.youtube_video_id === m.post_id);
    if (!pub) return null;
    const product = products.find((p) => norm(p.title) === norm(pub.title));
    return { pub, product };
  };

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h2 className="disp text-2xl font-extrabold text-[var(--heading)]" style={{ textShadow: '0 0 18px rgba(244,95,206,.30)' }}>Phân tích Hiệu năng (Analytics) <span className="text-[15px] tracking-[3px] text-[var(--accent)]" style={{ textShadow: '0 0 10px rgba(244,95,206,.65)' }}>⋆｡˚✧</span></h2>
          <p className="text-xs text-[var(--text2)]">Theo dõi lượt xem, tương tác và doanh thu chính thức theo từng Video</p>
        </div>
      </div>

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
                <TH>Kịch bản / Sản phẩm</TH>
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
                const src = sourceForMetric(m);
                return (
                  <TR key={idx}>
                    <TD className="font-semibold text-[var(--heading)] font-mono">{m.post_id}</TD>
                    <TD className="max-w-[220px]">
                      {src?.pub ? (
                        <div>
                          <div className="truncate font-semibold text-[var(--text)]" title={src.pub.title}>{src.pub.title}</div>
                          {src.product && (
                            <div className="text-[10px] text-[var(--text2)] font-mono">
                              {src.product.score != null && `${src.product.score}pts`}
                              {src.product.niche && ` · ${src.product.niche}`}
                              {src.product.qa_ok === false && ' · QA WARN'}
                            </div>
                          )}
                        </div>
                      ) : (
                        <span className="text-[var(--text3)]">Không rõ nguồn</span>
                      )}
                    </TD>
                    <TD>
                      <span className="disp inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-extrabold text-white uppercase border-[1.5px] border-[var(--ink)] bg-[var(--red)]">{m.platform_id}</span>
                    </TD>
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
    </div>
  );
};
