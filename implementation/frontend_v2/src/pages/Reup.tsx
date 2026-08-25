import React, { useState } from 'react';
import { useApi } from '../api/hooks';
import {
  Button, Card, CardHeader, CardTitle, CardSub, Badge, Input, Select,
  Table, THead, TBody, TR, TH, TD, Skeleton, EmptyState, Modal,
} from '../components/ui';
import { Download, AlertTriangle, CheckCircle2, RefreshCw, Check } from 'lucide-react';
import { ReupOverlayEditor } from './ReupOverlayEditor';

// Reup — tải video Douyin, dịch zh→vi có ngữ cảnh, lồng tiếng Việt, xuất.
// Backend: omnicast/api/reup_routes.py.
//
// Bố cục theo đúng vòng lặp thật của người dùng: gửi job → theo dõi bước →
// ĐỌC ĐỐI CHIẾU Trung/Việt → duyệt dòng bị gắn cờ → chạy tiếp. Khâu đối chiếu
// mới là khâu quan trọng, vì chủ kênh không đọc được tiếng Trung nên không thể
// tự biết bản dịch đúng hay sai nếu chỉ nhìn con số.

const STAGES = [
  'download', 'bootstrap', 'probe', 'extract_audio', 'asr', 'translate',
  'subtitles', 'tts', 'voice_track', 'mixdown', 'export',
] as const;

const STAGE_LABEL: Record<string, string> = {
  // The download runs before anything else and can take minutes on a big
  // video; leaving it out of this list is what made jobs look stuck at start.
  download: 'Tải video',
  bootstrap: 'Khởi tạo', probe: 'Metadata', extract_audio: 'Tách audio',
  asr: 'Nghe tiếng Trung', translate: 'Dịch sang Việt',
  subtitles: 'Phụ đề', tts: 'Lồng tiếng', voice_track: 'Ghép giọng',
  mixdown: 'Trộn tiếng', export: 'Xuất video',
};

type Tone = 'green' | 'blue' | 'amber' | 'red' | 'purple' | 'neutral';
const STATUS_TONE: Record<string, Tone> = {
  done: 'green', review: 'amber', failed: 'red', running: 'blue', pending: 'neutral',
};

// Mã lý do do semantic QC phát ra — dịch sang tiếng Việt để người duyệt biết
// PHẢI sửa gì thay vì đọc snake_case. Danh sách này lấy từ mã THẬT quan sát
// được trên một lượt chạy đầy đủ, không phải từ tài liệu (tên trong docs của
// repo gốc không khớp mã runtime).
const REASON_VI: Record<string, string> = {
  low_confidence_gate: 'Model tự nhận không chắc',
  pronoun_without_evidence: 'Chọn xưng hô chưa đủ căn cứ',
  unjustified_pronoun_insertion: 'Tự thêm xưng hô không có trong gốc',
  honorific_drift: 'Xưng hô không nhất quán',
  addressee_mismatch: 'Không khớp người nghe',
  ambiguous_term: 'Từ/tên đa nghĩa',
  technical_term_uncertainty: 'Thuật ngữ chuyên ngành chưa chắc',
  source_text_garbled: 'Câu gốc bị nhiễu',
  garbled_source_text: 'Câu gốc bị nhiễu',
  asr_error_suspected: 'Nghi ASR nghe nhầm',
  unjustified_addition: 'Thêm ý không có trong gốc',
  quantifier_drop: 'Mất lượng từ/số lượng',
  slot_pressure_shortened: 'Bị rút ngắn cho vừa thời lượng',
  subtitle_tts_divergence: 'Phụ đề khác lời đọc',
  tts_subtitle_divergence: 'Lời đọc khác phụ đề',
  tts_subtitle_expansion: 'Lời đọc dài hơn phụ đề',
  tts_subtitle_paraphrase_variance: 'Lời đọc diễn đạt khác phụ đề',
  tts_subtitle_minor_divergence: 'Lệch nhẹ phụ đề / lời đọc',
  tts_subtitle_minor_variance: 'Lệch nhẹ phụ đề / lời đọc',
};

function ms(v: number) {
  const s = Math.floor(v / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

interface Job {
  job_id: string; source_url: string; status: string;
  aweme_id: string | null; title: string | null; title_vi: string | null;
  project_root: string | null;
  exported_video_path: string | null; review_pending: number; last_stage: string | null;
  /** Served URL for the finished video, built by the API — never derived here. */
  video_url?: string | null;
  created_at?: string | null; updated_at?: string | null;
  error?: string | null;
}

interface Segment {
  segment_id: string; index: number; start_ms: number; end_ms: number;
  source_text: string; subtitle_text: string; tts_text: string; speaker: string;
  needs_review: boolean; review_status: string;
  review_reason_codes: string[]; review_question: string;
}

/** "4 phút trước" — how long the current stage has been running. */
function sinceLabel(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 90) return `${Math.round(seconds)} giây`;
  const minutes = seconds / 60;
  return minutes < 90 ? `${Math.round(minutes)} phút` : `${(minutes / 60).toFixed(1)} giờ`;
}

/** Dải 11 bước, tô tới bước đang chạy. */
const StageRail: React.FC<{ current: string | null; status: string }> = ({ current, status }) => {
  const idx = current ? STAGES.indexOf(current as any) : -1;
  return (
    <div className="flex flex-wrap gap-1">
      {STAGES.map((s, i) => {
        const done = idx >= 0 && i < idx;
        const active = i === idx;
        const failed = active && status === 'failed';
        return (
          <span
            key={s}
            title={STAGE_LABEL[s]}
            className={
              'rounded px-1.5 py-0.5 text-[11px] leading-tight border ' +
              (failed ? 'bg-red-500/15 border-red-500/40 text-red-500'
                : active ? 'bg-blue-500/15 border-blue-500/40 text-blue-500'
                : done ? 'bg-green-500/10 border-green-500/30 text-green-600'
                : 'opacity-35 border-transparent')
            }
          >
            {STAGE_LABEL[s]}
          </span>
        );
      })}
    </div>
  );
};

/** Bảng đối chiếu Trung ↔ Việt, sửa + duyệt tại chỗ. */
const SegmentReview: React.FC<{ jobId: string }> = ({ jobId }) => {
  const [onlyReview, setOnlyReview] = useState(false);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string>('');

  const { data, isLoading, refetch } = useApi<any>(
    `/api/reup/jobs/${jobId}/segments${onlyReview ? '?only_review=true' : ''}`,
    { refetchInterval: 15000 },
  );
  const segments: Segment[] = data?.segments || [];

  async function approve(seg: Segment) {
    setBusy(seg.segment_id);
    try {
      await fetch(`/api/reup/jobs/${jobId}/segments/${seg.segment_id}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          approved_subtitle_text: edits[seg.segment_id] ?? seg.subtitle_text,
          approved_tts_text: edits[seg.segment_id] ?? seg.tts_text,
          approve: true,
        }),
      });
      refetch();
    } finally {
      setBusy('');
    }
  }

  if (isLoading) return <div className="space-y-2 p-4"><Skeleton className="h-8" /><Skeleton className="h-8" /></div>;
  if (!segments.length) {
    return <EmptyState title="Chưa có lời thoại" desc="Chạy tới bước “Nghe tiếng Trung” là sẽ có." />;
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 text-sm">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={onlyReview} onChange={e => setOnlyReview(e.target.checked)} />
          Chỉ hiện dòng cần duyệt
        </label>
        <span className="opacity-60">
          {data?.total} dòng · {data?.pending_review} chờ duyệt
        </span>
        <Button onClick={() => refetch()} className="ml-auto">
          <RefreshCw size={14} className="mr-1" /> Làm mới
        </Button>
      </div>

      <div className="max-h-[520px] overflow-y-auto">
        <Table>
          <THead>
            <TR><TH>#</TH><TH>Gốc (中文)</TH><TH>Bản dịch (Tiếng Việt)</TH><TH>Duyệt</TH></TR>
          </THead>
          <TBody>
            {segments.map(seg => (
              <TR key={seg.segment_id}>
                <TD className="whitespace-nowrap align-top text-xs opacity-60">
                  <div>{seg.index}</div>
                  <div>{ms(seg.start_ms)}</div>
                </TD>
                <TD className="align-top">
                  <div className="max-w-sm text-sm">{seg.source_text}</div>
                  {seg.speaker && (
                    <div className="mt-1 text-[11px] opacity-50">🗣 {seg.speaker}</div>
                  )}
                </TD>
                <TD className="align-top">
                  {seg.needs_review ? (
                    <textarea
                      className="w-full min-w-[280px] rounded border bg-transparent p-1.5 text-sm"
                      rows={2}
                      value={edits[seg.segment_id] ?? seg.subtitle_text}
                      onChange={e => setEdits({ ...edits, [seg.segment_id]: e.target.value })}
                    />
                  ) : (
                    <div className="max-w-sm text-sm">{seg.subtitle_text}</div>
                  )}
                  {!!seg.review_reason_codes.length && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {seg.review_reason_codes.map(code => (
                        <Badge key={code} variant="amber">{REASON_VI[code] || code}</Badge>
                      ))}
                    </div>
                  )}
                  {seg.review_question && (
                    <div className="mt-1 text-[11px] opacity-70">❓ {seg.review_question}</div>
                  )}
                </TD>
                <TD className="align-top">
                  {seg.needs_review ? (
                    <Button onClick={() => approve(seg)} disabled={busy === seg.segment_id}>
                      <Check size={14} className="mr-1" />
                      {busy === seg.segment_id ? '...' : 'Duyệt'}
                    </Button>
                  ) : (
                    <span className="flex items-center gap-1 text-xs opacity-45">
                      <CheckCircle2 size={13} /> ok
                    </span>
                  )}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </div>
    </div>
  );
};

/** Nhân vật + quan hệ mà bước dịch tự suy ra — nền tảng của việc chọn xưng hô. */
const ContextPanel: React.FC<{ jobId: string }> = ({ jobId }) => {
  const { data } = useApi<any>(`/api/reup/jobs/${jobId}/context`, { refetchInterval: 20000 });
  const characters = data?.characters || [];
  const relationships = data?.relationships || [];
  const scenes = data?.scenes || [];
  if (!characters.length && !relationships.length && !scenes.length) return null;

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
      <div>
        <div className="mb-1 text-xs font-medium uppercase opacity-60">Cảnh ({scenes.length})</div>
        <div className="max-h-40 space-y-1 overflow-y-auto text-xs">
          {scenes.map((s: any) => (
            <div key={s.scene_id} className="opacity-80">#{s.index} {s.summary}</div>
          ))}
        </div>
      </div>
      <div>
        <div className="mb-1 text-xs font-medium uppercase opacity-60">
          Nhân vật ({characters.length})
        </div>
        <div className="max-h-40 space-y-1 overflow-y-auto text-xs">
          {characters.map((c: any) => (
            <div key={c.character_key} className="opacity-80">
              {c.display_name || c.character_key}
              {c.notes && <span className="opacity-50"> — {c.notes}</span>}
            </div>
          ))}
        </div>
      </div>
      <div>
        <div className="mb-1 text-xs font-medium uppercase opacity-60">
          Xưng hô ({relationships.length})
        </div>
        <div className="max-h-40 space-y-1 overflow-y-auto text-xs">
          {relationships.map((r: any, i: number) => (
            <div key={i} className="opacity-80">
              {r.speaker} → {r.listener}
              {(r.speaker_pronoun || r.listener_pronoun) && (
                <span className="opacity-60"> · {r.speaker_pronoun}/{r.listener_pronoun}</span>
              )}
              {r.relation_type && <span className="opacity-45"> ({r.relation_type})</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

/** File job đã tạo ra — phụ đề, audio đã trộn, video xuất. */
const ArtifactList: React.FC<{ jobId: string }> = ({ jobId }) => {
  const { data } = useApi<any>(`/api/reup/jobs/${jobId}/artifacts`, { refetchInterval: 20000 });
  const artifacts = data?.artifacts || [];
  if (!artifacts.length) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {artifacts.map((a: any, i: number) => (
        <a
          key={i}
          href={a.url || '#'}
          target="_blank"
          rel="noreferrer"
          className="rounded border px-2 py-1 text-xs underline"
        >
          {a.label} · {a.size_bytes >= 1e6
            ? `${(a.size_bytes / 1e6).toFixed(1)} MB`
            : `${Math.max(1, Math.round(a.size_bytes / 1024))} KB`}
        </a>
      ))}
    </div>
  );
};

export const Reup: React.FC = () => {
  const [url, setUrl] = useState('');
  // Empty = whatever the project preset already carries. Default to a female
  // news-register voice: the closest thing available to the CapCut female tone.
  const [voice, setVoice] = useState('Mai Anh');
  const [backend, setBackend] = useState('claude-cli');
  // Run through to the finished video: the operator reviews at the END, on
  // the overlay editor, not mid-pipeline. Stopping after translation by
  // default meant every job halted and then failed the review gate.
  const [stopAfter, setStopAfter] = useState('');
  const [exportPreset, setExportPreset] = useState('youtube-16x9');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<string>('');
  const [force, setForce] = useState(true);
  const [channelId, setChannelId] = useState('');
  // Kho phim: gắn job vào series + số tập ngay lúc tạo, hết cảnh video mồ côi.
  const [seriesId, setSeriesId] = useState('');
  const [episodeNo, setEpisodeNo] = useState('');
  // Tạo series ngay tại form — khỏi phải chạy sang tab Kho phim rồi quay lại.
  const [newSeriesOpen, setNewSeriesOpen] = useState(false);
  const [nsTitle, setNsTitle] = useState('');
  const [nsKind, setNsKind] = useState('series');
  const [nsChannel, setNsChannel] = useState('');
  const [nsError, setNsError] = useState('');
  const [nsSaving, setNsSaving] = useState(false);

  const { data: channels } = useApi<any>('/api/channels');
  const { data: librarySeries, refetch: refetchSeries } = useApi<any>('/api/library/series');
  const selectedSeries = (librarySeries?.series || []).find((s: any) => s.series_id === seriesId);
  const isSingleBucket = selectedSeries?.kind === 'single';

  async function createSeriesInline() {
    if (!nsTitle.trim()) { setNsError('Cần tên series.'); return; }
    setNsSaving(true); setNsError('');
    try {
      const res = await fetch('/api/library/series', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: nsTitle.trim(), kind: nsKind, channel_id: nsChannel }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        // 405 = POST rơi vào mount tĩnh của SPA → backend đang chạy bản cũ
        // chưa có route Kho phim (UI tự mới vì serve từ đĩa, Python thì không).
        if (res.status === 405) {
          throw new Error(
            'Backend đang chạy bản cũ chưa có Kho phim — tắt backend rồi chạy lại '
            + '`python run_backend.py`, sau đó bấm lại.'
          );
        }
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      const created = await res.json();
      setNewSeriesOpen(false); setNsTitle('');
      await refetchSeries();
      setSeriesId(created.series_id);
      if (nsKind === 'single') setEpisodeNo('');
    } catch (e: any) {
      setNsError(e.message || 'Không tạo được series');
    } finally { setNsSaving(false); }
  }
  // One input, one queue: paste a link while something is running and it waits
  // its turn instead of competing for the same CPU, GPU and Douyin rate limit.
  const { data: queue, refetch: refetchQueue } = useApi<any>('/api/reup/queue', {
    refetchInterval: 4000,
  });
  const [queued, setQueued] = useState('');

  const { data: health } = useApi<any>('/api/reup/health', { refetchInterval: 30000 });
  const { data: voices } = useApi<any>('/api/reup/voices');
  const { data: jobsData, isLoading, refetch } = useApi<any>('/api/reup/jobs', {
    refetchInterval: 5000,
  });

  const jobs: Job[] = jobsData?.jobs || [];
  const checks = health?.checks || {};
  const activeJob = jobs.find(j => j.job_id === selected) || null;

  /** Re-run a stopped job on its existing workspace; finished stages are cached. */
  async function resumeJob(jobId: string) {
    setError('');
    try {
      const res = await fetch(`/api/reup/jobs/${jobId}/resume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // Carry the form's current engine choice: the usual reason a job needs
        // resuming is that the one it started with had no key.
        body: JSON.stringify({ translation_backend: backend, allow_pending_review: force }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
      refetch();
    } catch (e: any) {
      setError(e.message || 'Không chạy tiếp được');
    }
  }

  /** Ask the local backend to open the finished video, or reveal its folder. */
  async function openResult(jobId: string, target: 'file' | 'folder') {
    try {
      const res = await fetch(`/api/reup/jobs/${jobId}/open?target=${target}`, { method: 'POST' });
      if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
    } catch (e: any) {
      setError(e.message || 'Không mở được video');
    }
  }

  async function submit() {
    if (!url.trim()) { setError('Dán link Douyin hoặc Bilibili đã.'); return; }
    setSubmitting(true); setError('');
    try {
      const res = await fetch('/api/reup/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: url.trim(),
          // The dropdown picks a VieNeu voice, not a preset. Sending the voice
          // name as voice_preset_id made the runner reject every choice.
          voice_preset_id: 'vieneu-default-vi',
          voice_id: voice || null,
          export_preset_id: exportPreset,
          translation_backend: backend,
          stop_after: stopAfter || null,
          allow_pending_review: force,
          channel_id: channelId || null,
          series_id: seriesId || null,
          episode_no: episodeNo ? Number(episodeNo) : null,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      const waiting = (queue?.pending?.length || 0) + (queue?.running ? 1 : 0);
      setQueued(
        waiting > 0
          ? `Đã thêm vào hàng chờ — còn ${waiting} job trước nó.`
          : 'Đã nhận, bắt đầu chạy.'
      );
      setUrl('');
      // Thả link tập tiếp theo là chuyện thường — tự nhảy số tập lên 1.
      if (seriesId && episodeNo) setEpisodeNo(String(Number(episodeNo) + 1));
      refetch();
      refetchQueue();
    } catch (e: any) {
      setError(e.message || 'Không gửi được job');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Reup video Trung Quốc</h1>
          <p className="text-sm opacity-70">
            Douyin / Bilibili → nghe tiếng Trung → dịch có ngữ cảnh → lồng tiếng Việt → xuất
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(checks).map(([key, c]: any) => (
            <Badge key={key} variant={c.ok ? 'green' : 'red'}>
              {c.ok ? '✓' : '✗'} {key}
            </Badge>
          ))}
          {!Object.keys(checks).length && <Skeleton className="h-6 w-56" />}
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Job mới</CardTitle>
          <CardSub>
            Douyin: link share (v.douyin.com), link web, ?modal_id= · Bilibili nội địa:
            BV…, av…, b23.tv, video nhiều phần dùng ?p=N (SESSDATA để tải 1080p)
          </CardSub>
        </CardHeader>
        <div className="space-y-3 px-4 pb-4">
          <div className="flex gap-2">
            <Input
              value={url}
              onChange={(e: any) => setUrl(e.target.value)}
              placeholder="douyin.com/video/… · v.douyin.com/… · bilibili.com/video/BV… · b23.tv/…"
              className="flex-1"
            />
            <Button onClick={submit} disabled={submitting || !health?.ready}>
              <Download size={16} className="mr-1" />
              {submitting ? 'Đang gửi...' : 'Chạy'}
            </Button>
          </div>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
            <label className="text-sm">
              <span className="mb-1 block opacity-70">Giọng đọc</span>
              <Select value={voice} onChange={(e: any) => setVoice(e.target.value)}>
                {/* The empty value means "whatever the project preset says",
                    which is CapCut Cô Gái Hoạt Ngôn — labelling it VieNeu was
                    simply wrong once the preset switched engines. */}
                <option value="">
                  {voices ? 'Mặc định — CapCut · Cô Gái Hoạt Ngôn' : 'Đang tải danh sách giọng…'}
                </option>
                {/* Grouped by engine, and the value is the full `engine:voice`
                    spec — a bare name keeps the preset's engine, so CapCut
                    voices only reach CapCut when the prefix travels with them. */}
                {(voices?.groups || []).filter((g: any) => g.voices?.length).map((g: any) => (
                  <optgroup key={g.provider} label={`${g.name} (${g.voices.length})`}>
                    {g.voices.map((v: any) => (
                      <option key={v.spec} value={v.spec}>{v.id}{v.description ? ` — ${v.description}` : ''}</option>
                    ))}
                  </optgroup>
                ))}
              </Select>
            </label>
            <label className="text-sm">
              <span className="mb-1 block opacity-70">Engine dịch</span>
              <Select value={backend} onChange={(e: any) => setBackend(e.target.value)}>
                <option value="claude-cli">Claude Sonnet 5 CLI — không tốn API</option>
                <option value="groq">Groq — rẻ, rất nhanh</option>
                <option value="openai">OpenAI — cần API key</option>
              </Select>
            </label>
            <label className="text-sm">
              <span className="mb-1 block opacity-70">Định dạng xuất</span>
              <Select value={exportPreset} onChange={(e: any) => setExportPreset(e.target.value)}>
                <option value="youtube-16x9">YouTube 16:9</option>
                <option value="shorts-9x16">Shorts 9:16</option>
              </Select>
            </label>
            <label className="text-sm">
              {/* Binds the job to a channel so its logo, watermark and subtitle
                  style come from the channel instead of being re-entered. */}
              <span className="mb-1 block opacity-70">Kênh</span>
              <Select value={channelId} onChange={(e: any) => setChannelId(e.target.value)}>
                <option value="">Không gắn kênh</option>
                {(channels?.channels || []).map((c: any) => (
                  <option key={c.channel_id} value={c.channel_id}>
                    {c.name || c.channel_id}
                  </option>
                ))}
              </Select>
            </label>
            <label className="text-sm">
              <span className="mb-1 block opacity-70">Dừng sau bước</span>
              <Select value={stopAfter} onChange={(e: any) => setStopAfter(e.target.value)}>
                <option value="">Chạy hết</option>
                {STAGES.map(s => <option key={s} value={s}>{STAGE_LABEL[s]}</option>)}
              </Select>
            </label>
            <label className="text-sm">
              {/* Kho phim: video này là tập mấy của series nào. Bỏ trống series
                  thì hệ thống vẫn tự khớp theo aweme_id nếu series đã quét nguồn. */}
              <span className="mb-1 block opacity-70">Series (Kho phim)</span>
              <Select
                value={seriesId}
                onChange={(e: any) => {
                  const v = e.target.value;
                  if (v === '__new__') {
                    setNsChannel(channelId || '');
                    setNewSeriesOpen(true);
                    return; // giữ nguyên lựa chọn cũ tới khi tạo xong
                  }
                  setSeriesId(v);
                  const s = (librarySeries?.series || []).find((x: any) => x.series_id === v);
                  if (s?.kind === 'single') setEpisodeNo('');
                }}
              >
                <option value="">Không gắn series</option>
                <option value="__new__">➕ Tạo series mới…</option>
                {(librarySeries?.series || []).map((s: any) => (
                  <option key={s.series_id} value={s.series_id}>
                    {s.kind === 'single' ? `📁 ${s.title} (video lẻ)` : s.title}
                  </option>
                ))}
              </Select>
            </label>
            <label className="text-sm">
              <span className="mb-1 block opacity-70">Số tập</span>
              <Input
                value={episodeNo}
                inputMode="numeric"
                onChange={(e: any) => setEpisodeNo(e.target.value.replace(/[^0-9]/g, ''))}
                placeholder={isSingleBucket ? 'Video lẻ — tự xếp, khỏi đánh số' : 'Tự bắt từ tiêu đề nếu bỏ trống'}
                disabled={!seriesId || isSingleBucket}
              />
            </label>
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={force} onChange={e => setForce(e.target.checked)} />
            Lồng tiếng cả khi còn câu chưa duyệt
          </label>

          <p className="text-xs opacity-60">
            Mặc định dừng sau <strong>Dịch sang Việt</strong> để bạn đọc đối chiếu trước, và
            chặn lồng tiếng khi còn câu chưa duyệt — lồng tiếng cả video rồi mới phát hiện
            dịch sai thì phải làm lại TTS, track giọng và hai lượt ffmpeg.
          </p>

          {error && (
            <div className="flex items-center gap-2 text-sm text-red-500">
              <AlertTriangle size={15} /> {error}
            </div>
          )}
          {queued && !error && <div className="text-sm text-emerald-400">{queued}</div>}
          {(queue?.running || (queue?.pending?.length || 0) > 0) && (
            <div className="text-xs text-[var(--text2)]">
              Hàng chờ: {queue.running ? '1 job đang chạy' : 'trống'}
              {(queue.pending?.length || 0) > 0 && ` · ${queue.pending.length} link đang đợi`}
              {queue.attempt > 1 && ` · đang thử lại lần ${queue.attempt}`}
            </div>
          )}
        </div>
      </Card>

      <Modal isOpen={newSeriesOpen} onClose={() => setNewSeriesOpen(false)} title="Tạo series mới">
        <div className="space-y-3">
          <label className="text-sm block">
            <span className="mb-1 block opacity-70">Tên series</span>
            <Input value={nsTitle} onChange={(e: any) => setNsTitle(e.target.value)}
                   placeholder="Khỉ Đột Đỏ — hoặc 'Video lẻ kênh A'" />
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className="text-sm block">
              <span className="mb-1 block opacity-70">Loại</span>
              <Select value={nsKind} onChange={(e: any) => setNsKind(e.target.value)}>
                <option value="series">Phim bộ (nhiều tập)</option>
                <option value="single">Video lẻ (gom video 1 tập)</option>
              </Select>
            </label>
            <label className="text-sm block">
              <span className="mb-1 block opacity-70">Kênh chủ</span>
              <Select value={nsChannel} onChange={(e: any) => setNsChannel(e.target.value)}>
                <option value="">Chưa gắn kênh</option>
                {(channels?.channels || []).map((c: any) => (
                  <option key={c.channel_id} value={c.channel_id}>{c.name || c.channel_id}</option>
                ))}
              </Select>
            </label>
          </div>
          <p className="text-xs opacity-60">
            「Video lẻ」= thùng gom các video một tập: không cần đánh số, hệ thống tự xếp thứ tự,
            Kho phim hiển thị theo tên video.
          </p>
          {nsError && <div className="text-sm text-red-500">{nsError}</div>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setNewSeriesOpen(false)}>Hủy</Button>
            <Button variant="primary" onClick={createSeriesInline} disabled={nsSaving}>
              {nsSaving ? 'Đang tạo…' : 'Tạo & chọn'}
            </Button>
          </div>
        </div>
      </Modal>

      <Card>
        <CardHeader>
          <CardTitle>Job đã chạy</CardTitle>
          <CardSub>{jobs.length} job — bấm một dòng để xem bản dịch</CardSub>
        </CardHeader>
        {isLoading ? (
          <div className="space-y-2 p-4"><Skeleton className="h-8" /><Skeleton className="h-8" /></div>
        ) : !jobs.length ? (
          <EmptyState title="Chưa có job nào" desc="Dán link Douyin ở trên để bắt đầu." />
        ) : (
          <Table>
            <THead>
              <TR><TH>Video</TH><TH>Trạng thái</TH><TH>Tiến trình</TH><TH>Chờ duyệt</TH><TH>Kết quả</TH></TR>
            </THead>
            <TBody>
              {jobs.map(job => (
                <TR
                  key={job.job_id}
                  onClick={() => setSelected(job.job_id === selected ? '' : job.job_id)}
                  className={'cursor-pointer ' + (job.job_id === selected ? 'bg-[var(--purple-soft)]' : '')}
                >
                  <TD>
                    {/* Vietnamese title first — that is what gets published. */}
                    <div className="max-w-xs truncate font-medium">
                      {job.title_vi || job.title || job.source_url}
                    </div>
                    {job.title_vi && job.title && (
                      <div className="max-w-xs truncate text-xs opacity-45">{job.title}</div>
                    )}
                    <div className="text-xs opacity-50">{job.aweme_id || job.job_id}</div>
                  </TD>
                  <TD>
                    <Badge variant={STATUS_TONE[job.status] || 'neutral'}>{job.status}</Badge>
                    {/* A stage that takes minutes reads as a hang without this. */}
                    {job.status === 'failed' && job.error && (
                      <div className="mt-1 max-w-[22rem] text-[11px] leading-snug text-red-400">
                        {job.error.length > 160 ? job.error.slice(0, 160) + '…' : job.error}
                      </div>
                    )}
                    {job.status === 'running' && job.updated_at && (
                      <div className="mt-1 text-[11px] opacity-55 whitespace-nowrap">
                        {STAGE_LABEL[job.last_stage || ''] || job.last_stage} · {sinceLabel(job.updated_at)}
                      </div>
                    )}
                  </TD>
                  <TD><StageRail current={job.last_stage} status={job.status} /></TD>
                  <TD>
                    {job.review_pending > 0 ? (
                      <span className="flex items-center gap-1 whitespace-nowrap text-amber-500">
                        <AlertTriangle size={14} /> {job.review_pending}
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 opacity-45"><CheckCircle2 size={14} /></span>
                    )}
                  </TD>
                  <TD>
                    {/* Opens in the operator's own player / Explorer rather than
                        streaming 178 MB into a webview tab. The server resolves
                        the path — the browser never sees or sends one. */}
                    {/* A stopped job keeps its workspace, so picking it back up
                        skips the download, the ASR and the translation already
                        on disk. Starting over would throw all of that away. */}
                    {(job.status === 'failed' || job.status === 'review') && (
                      <button
                        className="mr-2 text-sm underline"
                        onClick={e => { e.stopPropagation(); resumeJob(job.job_id); }}
                      >
                        Chạy tiếp
                      </button>
                    )}
                    {job.video_url ? (
                      <div className="inline-flex items-center gap-2 whitespace-nowrap">
                        <button
                          className="text-sm underline"
                          onClick={e => { e.stopPropagation(); openResult(job.job_id, 'file'); }}
                        >
                          Xem video
                        </button>
                        <button
                          className="text-xs opacity-60 underline"
                          title="Mở thư mục chứa video"
                          onClick={e => { e.stopPropagation(); openResult(job.job_id, 'folder'); }}
                        >
                          Thư mục
                        </button>
                      </div>
                    ) : <span className="text-xs opacity-40">—</span>}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      {activeJob && (
        <Card>
          <CardHeader>
            <CardTitle>Đối chiếu bản dịch</CardTitle>
            <CardSub>{activeJob.title_vi || activeJob.title || activeJob.source_url}</CardSub>
          </CardHeader>
          <div className="space-y-4 px-4 pb-4">
            <ArtifactList jobId={activeJob.job_id} />
            <ReupOverlayEditor jobId={activeJob.job_id} />
            <ContextPanel jobId={activeJob.job_id} />
            <SegmentReview jobId={activeJob.job_id} />
          </div>
        </Card>
      )}
    </div>
  );
};
