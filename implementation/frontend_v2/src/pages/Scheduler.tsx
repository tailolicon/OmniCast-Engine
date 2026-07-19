import React, { useState } from 'react';
import { useApi, useInvalidate } from '../api/hooks';
import { apiPost } from '../api/client';
import {
  Button,
  Card,
  Checkbox,
  Select,
  Table,
  THead,
  TBody,
  TR,
  TH,
  TD
} from '../components/ui';
import { Cpu, Calendar } from 'lucide-react';

export const Scheduler: React.FC = () => {
  const invalidate = useInvalidate();
  
  // Queries
  const { data: autoStatusData } = useApi<any>('/api/auto/status', { refetchInterval: 5000 });
  const { data: schedulerData } = useApi<any>('/api/scheduler');
  const { data: executionsData } = useApi<any>('/api/pipelines/executions', { refetchInterval: 10000 });
  const { data: errorsData } = useApi<any>('/api/errors');

  const autopilotEnabled = !!autoStatusData?.running;
  const schedulerEnabled = !!schedulerData?.enabled;
  const schedulerChannels = schedulerData?.channels || [];
  const executions = executionsData?.executions || [];
  const errors = errorsData?.errors || [];

  const [isTriggeringAuto, setIsTriggeringAuto] = useState(false);
  const [isUpdatingSched, setIsUpdatingSched] = useState(false);
  const [isTriggeringPipeline, setIsTriggeringPipeline] = useState(false);
  const [isClearingErrors, setIsClearingErrors] = useState(false);

  const handleTriggerAutopilot = async () => {
    if (autopilotEnabled) return;
    setIsTriggeringAuto(true);
    try {
      await apiPost('/api/auto/run');
      invalidate('/api/auto/status');
    } catch (e) {}
    finally { setIsTriggeringAuto(false); }
  };

  const handleToggleScheduler = async () => {
    setIsUpdatingSched(true);
    try {
      await apiPost(`/api/scheduler/toggle?enabled=${!schedulerEnabled ? 'true' : 'false'}`);
      invalidate('/api/scheduler');
    } catch (e) {}
    finally { setIsUpdatingSched(false); }
  };

  const handleTriggerPipeline = async () => {
    setIsTriggeringPipeline(true);
    try {
      await apiPost('/api/pipelines/run');
      invalidate('/api/pipelines/executions');
    } catch (e) {}
    finally { setIsTriggeringPipeline(false); }
  };

  const handleClearErrors = async () => {
    setIsClearingErrors(true);
    try {
      await apiPost('/api/errors/clear');
      invalidate('/api/errors');
    } catch (e) {}
    finally { setIsClearingErrors(false); }
  };

  const handleUpdateChannelSchedule = async (cid: string, params: Record<string, any>) => {
    try {
      const qs = Object.entries(params)
        .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
        .join('&');
      await apiPost(`/api/scheduler/channel/${cid}?${qs}`);
      invalidate('/api/scheduler');
    } catch (e) {}
  };

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h2 className="disp text-2xl font-extrabold text-[var(--heading)]" style={{ textShadow: '0 0 18px rgba(244,95,206,.30)' }}>Lịch & Tự động (Scheduler) <span className="text-[15px] tracking-[3px] text-[var(--accent)]" style={{ textShadow: '0 0 10px rgba(244,95,206,.65)' }}>⋆｡˚✧</span></h2>
          <p className="text-xs text-[var(--text2)]">Cấu hình chu kỳ sản xuất tự động 24/7 và điều hành hàng đợi autopilot</p>
        </div>
      </div>

      {/* Autopilot & Scheduler Master Controls */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Autopilot */}
        <Card className="flex flex-col justify-between">
          <div>
            <h3 className="font-semibold text-sm text-[var(--heading)] flex items-center gap-1.5">
              <Cpu size={16} className="text-[var(--blue)]" />
              <span>Hệ thống Autopilot</span>
            </h3>
            <p className="text-xs text-[var(--text2)] leading-relaxed mt-2">
              Autopilot tự động quét ngách, đề xuất chủ đề, tự tạo kịch bản, và tự render theo chu kỳ mà không cần tương tác của con người.
            </p>
            {autoStatusData?.running && (
              <div className="mt-3 p-2 bg-[var(--surface2)] rounded-[12px] border-[1.5px] border-[var(--border-soft)] max-h-40 overflow-y-auto font-mono text-[10px]">
                <div className="text-[var(--blue)] font-bold mb-1">
                  Đang chạy: Kênh {autoStatusData.channel_id || 'tất cả'} · Bước {autoStatusData.step || 'bắt đầu'}
                </div>
                {autoStatusData.logs?.map((l: string, idx: number) => (
                  <div key={idx} className="text-[var(--text2)] leading-relaxed">{l}</div>
                ))}
              </div>
            )}
          </div>
          <div className="pt-4 border-t border-[var(--border-soft)] mt-4 flex items-center justify-between gap-4">
            <span className={`text-[10px] font-extrabold px-2.5 py-0.5 rounded-full font-mono border-[1.5px] border-[var(--ink)] ${
              autopilotEnabled ? 'bg-[var(--blue)] text-white animate-pulse' : 'bg-[var(--surface2)] text-[var(--text2)]'
            }`}>
              {autopilotEnabled ? 'AUTO RUNNING' : 'AUTO IDLE'}
            </span>
            <Button
              variant={autopilotEnabled ? 'secondary' : 'primary'}
              onClick={handleTriggerAutopilot}
              disabled={isTriggeringAuto || autopilotEnabled}
              className="text-xs"
            >
              {autopilotEnabled ? 'Đang tự chạy...' : 'Kích hoạt Autopilot'}
            </Button>
          </div>
        </Card>

        {/* Scheduler Master */}
        <Card className="flex flex-col justify-between">
          <div>
            <h3 className="font-semibold text-sm text-[var(--heading)] flex items-center gap-1.5">
              <Calendar size={16} className="text-[var(--green)]" />
              <span>Scheduler Lịch đăng</span>
            </h3>
            <p className="text-xs text-[var(--text2)] leading-relaxed mt-2">
              Công tắc tổng kích hoạt hệ thống đăng tải video tự động lên YouTube/TikTok theo khung giờ vàng (Prime UTC hours) của các kênh.
            </p>
          </div>
          <div className="pt-4 border-t border-[var(--border-soft)] mt-4 flex items-center justify-between gap-4">
            <span className={`text-[10px] font-extrabold px-2.5 py-0.5 rounded-full font-mono border-[1.5px] border-[var(--ink)] ${
              schedulerEnabled ? 'bg-[var(--green)] text-white' : 'bg-[var(--surface2)] text-[var(--text2)]'
            }`}>
              Scheduler: {schedulerEnabled ? 'ON' : 'OFF'}
            </span>
            <Button
              variant={schedulerEnabled ? 'secondary' : 'primary'}
              onClick={handleToggleScheduler}
              disabled={isUpdatingSched}
              className="text-xs"
            >
              {schedulerEnabled ? 'Tắt Scheduler' : 'Bật Scheduler'}
            </Button>
          </div>
        </Card>
      </div>

      {/* Scheduler Details Table */}
      <Card className="!p-0 overflow-hidden">
        <div className="px-4 pt-4 pb-2 text-xs font-bold uppercase tracking-wider text-[var(--text3)]">Cấu hình lịch đăng kênh</div>
        {schedulerChannels.length === 0 ? (
          <div className="p-4 text-center text-xs text-[var(--text3)] italic">Không có dữ liệu kênh schedule.</div>
        ) : (
          <Table className="text-xs">
            <THead>
              <TR>
                <TH>Kênh</TH>
                <TH>Bật lịch</TH>
                <TH>Tần suất</TH>
                <TH>Giờ vàng (UTC)</TH>
                <TH>Shorts</TH>
                <TH>Tự đăng</TH>
                <TH>Lần cuối chạy</TH>
                <TH>Tuần này</TH>
              </TR>
            </THead>
            <TBody>
              {schedulerChannels.map((c: any) => (
                <TR key={c.channel_id}>
                  <TD className="!py-3">
                    <span className="font-semibold block text-[var(--heading)]">{c.name}</span>
                    <span className="text-[10px] text-[var(--text3)] font-mono">{c.channel_id}</span>
                  </TD>
                  <TD>
                    <Checkbox
                      checked={!!c.enabled}
                      onChange={(e: any) => handleUpdateChannelSchedule(c.channel_id, { enabled: e.target.checked })}
                    />
                  </TD>
                  <TD>
                    <Select
                      value={c.cadence}
                      onChange={(e: any) => handleUpdateChannelSchedule(c.channel_id, { cadence: e.target.value })}
                      className="!py-0.5 !text-xs !w-28"
                    >
                      <option value="daily">daily</option>
                      <option value="3x_weekly">3x_weekly</option>
                      <option value="twice_weekly">twice_weekly</option>
                      <option value="weekly">weekly</option>
                    </Select>
                  </TD>
                  <TD className="font-mono text-xs text-[var(--text2)]">
                    {(c.prime_hours || []).join(', ') || '—'}
                  </TD>
                  <TD>
                    <Checkbox
                      checked={!!c.shorts}
                      onChange={(e: any) => handleUpdateChannelSchedule(c.channel_id, { shorts: e.target.checked })}
                    />
                  </TD>
                  <TD>
                    <Checkbox
                      checked={!!c.upload}
                      onChange={(e: any) => handleUpdateChannelSchedule(c.channel_id, { upload: e.target.checked })}
                    />
                  </TD>
                  <TD className="font-mono text-xs text-[var(--text3)]">
                    {c.last_run || '—'}
                  </TD>
                  <TD className="font-mono text-xs text-[var(--text2)]">
                    {c.week_count || 0}/{(schedulerData?.cadence_map || {})[c.cadence] || '?'}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      {/* Kestra/Pipeline Executions & Errors */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-stretch">
        {/* Kestra Pipeline runs */}
        <Card className="xl:col-span-8 !p-0 overflow-hidden flex flex-col justify-between">
          <div>
            <div className="px-4 pt-4 pb-2 flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-[var(--text3)]">Lịch sử chạy Pipeline</span>
              <Button
                variant="primary"
                size="sm"
                onClick={handleTriggerPipeline}
                disabled={isTriggeringPipeline}
                className="text-xs !py-1"
              >
                Chạy chu kỳ Pipeline ngay
              </Button>
            </div>
            {executions.length === 0 ? (
              <div className="p-8 text-center text-xs text-[var(--text3)] italic">Chưa có lượt chạy pipeline nào.</div>
            ) : (
              <Table className="text-xs">
                <THead>
                  <TR>
                    <TH>Execution ID</TH>
                    <TH>Kênh</TH>
                    <TH>Trạng thái</TH>
                    <TH>Thời lượng</TH>
                    <TH>Lúc</TH>
                  </TR>
                </THead>
                <TBody>
                  {executions.map((ex: any) => (
                    <TR key={ex.execution_id}>
                      <TD className="font-mono text-[10px] text-[var(--blue)]">{ex.execution_id}</TD>
                      <TD className="font-semibold">{ex.channel_id || '—'}</TD>
                      <TD>
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-extrabold font-mono border-[1.5px] border-[var(--ink)] text-white ${
                          ex.status === 'success' ? 'bg-[var(--green)]' :
                          ex.status === 'running' ? 'bg-[var(--blue)] animate-pulse' :
                          'bg-[var(--red)]'
                        }`}>
                          {ex.status.toUpperCase()}
                        </span>
                      </TD>
                      <TD className="font-mono text-xs">{ex.duration_s ? `${ex.duration_s}s` : '—'}</TD>
                      <TD className="font-mono text-[10px] text-[var(--text3)]">{(ex.created_at || '').replace('T', ' ').slice(0, 19)}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </div>
        </Card>

        {/* Errors Log Buffer */}
        <Card className="xl:col-span-4 flex flex-col justify-between p-4">
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-[var(--text3)]">Buffer lỗi hệ thống</span>
              <Button
                variant="secondary"
                size="sm"
                onClick={handleClearErrors}
                disabled={isClearingErrors || errors.length === 0}
                className="text-[10px] !py-0.5 !px-2"
              >
                Xóa buffer
              </Button>
            </div>
            {errors.length === 0 ? (
              <div className="p-4 text-center text-xs text-[var(--text3)] italic">Trống (Hệ thống chạy bình thường)</div>
            ) : (
              <div className="space-y-2 max-h-60 overflow-y-auto p-2 bg-[var(--surface2)] border-[1.5px] border-[var(--border-soft)] rounded-[12px] font-mono text-[10px] text-[var(--red)]">
                {errors.map((err: any, idx: number) => (
                  <div key={idx} className="border-b border-[var(--border-soft)] pb-1.5 last:border-0 last:pb-0">
                    <div className="font-bold">[{err.timestamp}] {err.channel_id || 'system'}:</div>
                    <div className="break-all whitespace-pre-wrap">{err.message}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
};
