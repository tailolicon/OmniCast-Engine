import React, { useState, useEffect, useRef } from 'react';
import { useApi } from '../api/hooks';

/**
 * Progress dock (góc phải dưới) — hiện job đang chạy từ /api/pipeline.
 * ETA đếm ngược TỪNG GIÂY + thanh tiến độ chạy mượt (nội suy giữa các lần poll
 * theo vận tốc % thực đo được, không nhảy-rồi-đứng). Thời lượng trung bình của
 * các lần chạy trước lưu localStorage để ETA lần sau chuẩn hơn.
 */
interface Job {
  channel_id?: string; channel?: string; name?: string;
  stage?: string; phase?: string;
  progress_pct?: number; eta_seconds?: number | null;
}
interface PipelineResp { active_jobs?: Job[]; }

const PALETTE = [
  { color: '#ff6fd0', glow: 'rgba(255,111,208,.7)', g: 'linear-gradient(90deg,#ff9de0,#ff5fc4)' },
  { color: '#6fa8ff', glow: 'rgba(111,168,255,.7)', g: 'linear-gradient(90deg,#8fc2ff,#5f8bff)' },
  { color: '#b07cff', glow: 'rgba(176,124,255,.7)', g: 'linear-gradient(90deg,#c9a3ff,#9d5fff)' },
  { color: '#7de08a', glow: 'rgba(125,224,138,.7)', g: 'linear-gradient(90deg,#a9f0b0,#4fd86a)' },
  { color: '#ffb44d', glow: 'rgba(255,180,77,.7)', g: 'linear-gradient(90deg,#ffd08a,#ff9e2e)' },
];
const CHARMS = ['✿', '☾', '★', '✦', '❀'];

const jobKey = (j: Job) => String(j.channel_id || j.channel || j.name || 'job');
const fmtMMSS = (s: number) => {
  s = Math.max(0, Math.round(s));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};
const avgKey = (k: string) => `omni_avgdur_${k}`;
const getAvgDur = (k: string) => {
  const v = Number(localStorage.getItem(avgKey(k)));
  return v > 20 ? v : 180; // mặc định 3 phút khi chưa có lịch sử
};
const pushAvgDur = (k: string, dur: number) => {
  if (dur < 20 || dur > 3600) return;
  const prev = Number(localStorage.getItem(avgKey(k))) || dur;
  localStorage.setItem(avgKey(k), String(Math.round(prev * 0.6 + dur * 0.4))); // EMA
};

interface Meta { startAt: number; lastPct: number; lastPctAt: number; velocity: number; stage: string; stageAt: number } // velocity: %/s, per-stage

export const ProgressDock: React.FC = () => {
  const [open, setOpen] = useState(true);
  const [, setTick] = useState(0);
  const metaRef = useRef<Map<string, Meta>>(new Map());
  const { data } = useApi<PipelineResp>('/api/pipeline', { refetchInterval: 3000 });
  const jobs = data?.active_jobs || [];

  // Ticker 1s — ETA đếm ngược & thanh nội suy chạy đều
  useEffect(() => {
    if (jobs.length === 0) return;
    const t = setInterval(() => setTick((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, [jobs.length]);

  // Cập nhật meta khi có số % mới từ server + ghi nhận job hoàn tất
  useEffect(() => {
    const now = Date.now();
    const seen = new Set<string>();
    for (const j of jobs) {
      const k = jobKey(j);
      seen.add(k);
      const pct = Math.max(0, Math.min(100, j.progress_pct ?? 0));
      const m = metaRef.current.get(k);
      const st = String(j.stage || j.phase || '');
      if (!m) {
        metaRef.current.set(k, { startAt: now, lastPct: pct, lastPctAt: now, velocity: 100 / getAvgDur(k), stage: st, stageAt: now });
      } else if (st && st !== m.stage) {
        // Đổi khâu: lưu thời lượng khâu cũ (học per-stage) + reset vận tốc theo
        // lịch sử của khâu MỚI — hết cảnh ETA khâu trước áp sai cho khâu sau.
        pushAvgDur(`${k}:${m.stage}`, (now - m.stageAt) / 1000);
        m.stage = st; m.stageAt = now;
        m.velocity = 100 / getAvgDur(k); // nền: tốc độ trung bình cả job
        m.lastPct = pct; m.lastPctAt = now;
      } else if (pct !== m.lastPct) {
        const dt = (now - m.lastPctAt) / 1000;
        if (dt > 0.5 && pct > m.lastPct) {
          const v = (pct - m.lastPct) / dt;
          m.velocity = m.velocity * 0.5 + v * 0.5; // làm mượt vận tốc
        }
        m.lastPct = pct; m.lastPctAt = now;
      }
    }
    // job biến mất = xong → lưu thời lượng thật cho ETA lần sau
    for (const [k, m] of metaRef.current) {
      if (!seen.has(k)) {
        pushAvgDur(k, (Date.now() - m.startAt) / 1000);
        metaRef.current.delete(k);
      }
    }
  }, [data]);

  if (jobs.length === 0) return null;
  const now = Date.now();

  return (
    <div className="fixed bottom-5 right-5 z-40 w-[320px] rounded-[18px] overflow-hidden backdrop-blur-md"
      style={{ background: 'var(--glass)', border: '2px solid var(--ink)', boxShadow: 'var(--shadow-hard), var(--glow)' }}>
      <button onClick={() => setOpen(!open)} className="w-full flex items-center justify-between px-4 py-2.5 cursor-pointer"
        style={{ borderBottom: open ? '1.5px solid var(--border-soft)' : 'none' }}>
        <span className="disp text-sm font-extrabold text-[var(--heading)] flex items-center gap-2">
          <span style={{ color: 'var(--accent)', filter: 'drop-shadow(0 0 6px var(--accent-ring))' }}>✿</span>
          Mục tiêu đang chạy
        </span>
        <span className="flex items-center gap-2">
          <span className="text-[10px] font-bold text-[var(--text2)]">{jobs.length} đang chạy</span>
          <span className="text-[var(--text3)] transition-transform" style={{ transform: open ? 'rotate(0deg)' : 'rotate(180deg)' }}>▾</span>
        </span>
      </button>
      <div className="transition-all duration-300 overflow-hidden" style={{ maxHeight: open ? 300 : 0 }}>
        <div className="p-3 space-y-3">
          {jobs.map((j, i) => {
            const c = PALETTE[i % PALETTE.length];
            const k = jobKey(j);
            const m = metaRef.current.get(k);
            const serverPct = Math.max(0, Math.min(100, j.progress_pct ?? 0));
            // Nội suy: từ lần cập nhật cuối, bar tiếp tục chạy theo vận tốc đo được
            // (trần +6% giữa 2 lần poll để không vượt quá thực tế), luôn < 99.
            let pct = serverPct;
            let etaS: number | null = null;
            if (m) {
              const since = (now - m.lastPctAt) / 1000;
              pct = Math.min(m.lastPct + Math.min(m.velocity * since, 6), 99, Math.max(serverPct, m.lastPct));
              pct = Math.max(pct, serverPct);
              const v = Math.max(m.velocity, 0.05);
              etaS = (100 - pct) / v;
              const elapsed = (now - m.startAt) / 1000;
              const byAvg = Math.max(getAvgDur(k) - elapsed, 5);
              const stageAvg = Number(localStorage.getItem(`omni_avgdur_${k}:${m.stage}`)) || 0;
              if (stageAvg > 20) {
                // Có lịch sử riêng của khâu này → ETA khâu = avg − đã chạy trong khâu
                const stageElapsed = (now - m.stageAt) / 1000;
                etaS = Math.max(stageAvg - stageElapsed, 2);
              } else {
                etaS = pct < 8 ? byAvg : Math.min(etaS, byAvg * 3);
              }
            } else if (j.eta_seconds) etaS = j.eta_seconds;
            const title = j.name || j.channel || j.channel_id || 'Job';
            const stage = j.stage || j.phase || '';
            const elapsedS = m ? (now - m.startAt) / 1000 : 0;
            return (
              <div key={k}>
                <div className="flex items-center justify-between mb-1">
                  <span className="disp text-xs font-bold text-[var(--heading)] truncate pr-2">
                    <span style={{ color: c.color }}>{CHARMS[i % CHARMS.length]}</span> {title}
                  </span>
                  <span className="mono text-[10px] font-bold" style={{ color: c.color }}>{pct.toFixed(0)}%</span>
                </div>
                <div className="text-[10px] text-[var(--text3)] mb-1.5 truncate mono">
                  {stage} · đã chạy {fmtMMSS(elapsedS)}{etaS != null && ` · còn ~${fmtMMSS(etaS)}`}
                </div>
                <div className="relative h-2.5 rounded-full overflow-hidden" style={{ background: 'var(--surface3)' }}>
                  <div className="absolute left-0 top-0 h-full rounded-full"
                    style={{ width: `${pct}%`, background: c.g, transition: 'width 1s linear',
                             boxShadow: `0 0 10px 1px ${c.glow}, inset 0 1px 0 rgba(255,255,255,.4)` }} />
                  <span style={{ position: 'absolute', top: '50%', left: `${pct}%`, transform: 'translate(-50%,-50%)',
                                 fontSize: 15, color: c.color, filter: `drop-shadow(0 0 6px ${c.glow})`,
                                 pointerEvents: 'none', zIndex: 2, transition: 'left 1s linear' }}>✿</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export default ProgressDock;
