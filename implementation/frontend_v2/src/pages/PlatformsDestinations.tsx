import React from 'react';
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
  Badge
} from '../components/ui';

export const PlatformsDestinations: React.FC = () => {
  // Queries
  const { data: platformsData, isLoading: isPlatformsLoading } = useApi<any>('/api/platforms');
  const { data: destinationsData, isLoading: isDestinationsLoading } = useApi<any>('/api/destinations');

  const platforms = platformsData?.platforms || [];
  const destinations = destinationsData?.destinations || [];

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h2 className="disp text-2xl font-extrabold text-[var(--heading)]" style={{ textShadow: '0 0 18px rgba(244,95,206,.30)' }}>Nền tảng & Đích đăng <span className="text-[15px] tracking-[3px] text-[var(--accent)]" style={{ textShadow: '0 0 10px rgba(244,95,206,.65)' }}>⋆｡˚✧</span></h2>
          <p className="text-xs text-[var(--text2)]">Cấu hình luồng phân phối video và trạng thái kết nối các API adapter</p>
        </div>
      </div>

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
                      // Backend FormatSpec exposes `aspect_ratio` (singular), e.g. "16:9".
                      // Reading the non-existent `aspect_ratios` showed a wrong/empty value (S5).
                      const aspect = p.format_spec?.aspect_ratio || '—';
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
    </div>
  );
};
