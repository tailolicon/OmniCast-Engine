import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Card, CardHeader, CardTitle, CardSub, Input, Select } from '../components/ui';
import { Plus, Trash2, Save, Eye, RotateCcw, Film } from 'lucide-react';

// Overlay editor — hide the source's burned-in Chinese text, brand the frame,
// and set the Vietnamese subtitle size, all positioned against a real still.
//
// Geometry is stored as fractions of the frame (0–1), never pixels: the same
// boxes then hold whether the job exports 16:9 or a 9:16 short, and the editor
// can show the frame at whatever size fits the screen.

type CoverMode = 'blur' | 'pixelate' | 'box';

interface Cover {
  x: number; y: number; width: number; height: number;
  mode: CoverMode; strength: number; opacity: number; label: string;
}
interface Logo {
  path: string; position: string; scale: number; opacity: number;
  margin: number; enabled: boolean;
}
interface Roaming {
  path: string; text: string; scale: number; opacity: number;
  travel: number; font_size: number; font_file: string; enabled: boolean;
}
interface SubtitleStyle {
  font_size: number; outline: number; shadow: number;
  margin_v: number; margin_l: number; margin_r: number;
  alignment: number; font_name: string;
}

// libass falls back to a 384x288 reference when the ASS declares no PlayRes,
// so margins are in that space — not video pixels.
const ASS_W = 384, ASS_H = 288;

/** Where the current anchor + margins put the subtitle, as frame fractions. */
function subtitleBox(s: SubtitleStyle): { x: number; y: number } {
  const col = (s.alignment - 1) % 3;          // 0 left, 1 centre, 2 right
  const row = Math.floor((s.alignment - 1) / 3); // 0 bottom, 1 middle, 2 top
  const x = col === 0 ? s.margin_l / ASS_W
    : col === 2 ? 1 - s.margin_r / ASS_W
    : 0.5;
  const y = row === 0 ? 1 - s.margin_v / ASS_H
    : row === 2 ? s.margin_v / ASS_H
    : 0.5;
  return { x, y };
}

/** Inverse: a dropped point becomes the nearest anchor plus offsets. */
function anchorFromPoint(x: number, y: number): Partial<SubtitleStyle> {
  const col = x < 1 / 3 ? 0 : x < 2 / 3 ? 1 : 2;
  const bottom = y >= 2 / 3, top = y < 1 / 3;
  const alignment = (bottom ? 1 : top ? 7 : 4) + col;
  return {
    alignment,
    margin_v: Math.round(bottom ? (1 - y) * ASS_H : top ? y * ASS_H : 0),
    margin_l: col === 0 ? Math.round(x * ASS_W) : 10,
    margin_r: col === 2 ? Math.round((1 - x) * ASS_W) : 10,
  };
}
interface Overlays {
  covers: Cover[]; logo: Logo; roaming: Roaming; subtitle: SubtitleStyle;
}

const NEW_COVER: Cover = {
  x: 0.3, y: 0.82, width: 0.4, height: 0.12,
  mode: 'blur', strength: 14, opacity: 1, label: 'Vùng che',
};

/** A new box, stepped away from the ones already there.
 *
 * Dropping every new region at the same coordinates hides it exactly behind
 * the previous one, so the button looks broken — you get a second box, you
 * just cannot see or grab it. */
function nextCover(existing: Cover[]): Cover {
  const step = 0.04 * existing.length;
  return {
    ...NEW_COVER,
    x: Math.min(0.95 - NEW_COVER.width, NEW_COVER.x + step),
    y: Math.max(0.02, NEW_COVER.y - step),
    label: `Vùng che ${existing.length + 1}`,
  };
}

const MODE_LABEL: Record<CoverMode, string> = {
  blur: 'Làm mờ', pixelate: 'Vỡ hạt', box: 'Hộp đặc',
};

type DragState =
  | { kind: 'move'; index: number; dx: number; dy: number }
  | { kind: 'resize'; index: number }
  | { kind: 'subtitle'; index: number; dx: number; dy: number }
  | null;

export const ReupOverlayEditor: React.FC<{ jobId: string }> = ({ jobId }) => {
  const [overlays, setOverlays] = useState<Overlays | null>(null);
  const [selected, setSelected] = useState(0);
  const [frameTime, setFrameTime] = useState(5);
  const [duration, setDuration] = useState(0);
  const [preview, setPreview] = useState<string>('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [exported, setExported] = useState('');
  const [channel, setChannel] = useState('');
  const [note, setNote] = useState('');
  const [gpu, setGpu] = useState(true);
  const stageRef = useRef<HTMLDivElement>(null);
  // The marker's font size is a ratio of the frame height, so it needs the
  // stage's real pixel height — and that changes with the window.
  const [stageH, setStageH] = useState(0);
  const dragRef = useRef<DragState>(null);

  useEffect(() => {
    fetch(`/api/reup/jobs/${jobId}/overlays`)
      .then(r => r.json())
      .then(d => {
        setOverlays(d.overlays);
        setDuration((d.video?.duration_ms || 0) / 1000);
        setChannel(d.channel_has_defaults ? d.channel_id : '');
      })
      .catch(e => setError(String(e)));
  }, [jobId]);

  const frameUrl = `/api/reup/jobs/${jobId}/frame?t=${frameTime}`;

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const measure = () => setStageH(stage.getBoundingClientRect().height);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(stage);
    return () => observer.disconnect();
  }, [overlays]);

  /** Pointer position as a fraction of the stage, clamped to it. */
  const fractionAt = useCallback((e: React.PointerEvent | PointerEvent) => {
    const box = stageRef.current?.getBoundingClientRect();
    if (!box) return { x: 0, y: 0 };
    return {
      x: Math.min(1, Math.max(0, (e.clientX - box.left) / box.width)),
      y: Math.min(1, Math.max(0, (e.clientY - box.top) / box.height)),
    };
  }, []);

  useEffect(() => {
    function onMove(e: PointerEvent) {
      const drag = dragRef.current;
      if (!drag || !overlays) return;
      const at = fractionAt(e);
      if (drag.kind === 'subtitle') {
        setOverlays(prev => prev && {
          ...prev,
          subtitle: { ...prev.subtitle, ...anchorFromPoint(at.x, at.y) },
        });
        return;
      }
      setOverlays(prev => {
        if (!prev) return prev;
        const covers = prev.covers.map((c, i) => {
          if (i !== drag.index) return c;
          if (drag.kind === 'move') {
            return {
              ...c,
              x: Math.min(1 - c.width, Math.max(0, at.x - drag.dx)),
              y: Math.min(1 - c.height, Math.max(0, at.y - drag.dy)),
            };
          }
          // Resize from the bottom-right corner; keep a floor so a box can
          // never collapse to something unclickable.
          return {
            ...c,
            width: Math.min(1 - c.x, Math.max(0.02, at.x - c.x)),
            height: Math.min(1 - c.y, Math.max(0.02, at.y - c.y)),
          };
        });
        return { ...prev, covers };
      });
    }
    function onUp() { dragRef.current = null; }
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
  }, [overlays, fractionAt]);

  function patchCover(index: number, patch: Partial<Cover>) {
    setOverlays(prev => prev && {
      ...prev,
      covers: prev.covers.map((c, i) => (i === index ? { ...c, ...patch } : c)),
    });
  }

  async function save(asChannelDefault = false) {
    if (!overlays) return;
    setBusy(asChannelDefault ? 'channel' : 'save'); setError('');
    try {
      const res = await fetch(`/api/reup/jobs/${jobId}/overlays`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ overlays, as_channel_default: asChannelDefault }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
      if (asChannelDefault) setNote(`Đã đặt làm mặc định cho kênh ${channel}`);
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  }

  /** Save, then re-run the export stage — the only step that puts the boxes
   *  into the actual video file. Roughly 3 minutes for a 9-minute source. */
  async function saveAndExport() {
    if (!overlays) return;
    await save();
    setBusy('export'); setError(''); setExported('');
    try {
      const res = await fetch(`/api/reup/jobs/${jobId}/export?gpu=${gpu}`, { method: 'POST' });
      if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
      setExported('running');
    } catch (e: any) { setError(e.message); setBusy(''); }
  }

  // Export runs in a background thread on the server; watch the job row.
  useEffect(() => {
    if (exported !== 'running') return;
    const timer = setInterval(async () => {
      try {
        const job = await (await fetch(`/api/reup/jobs/${jobId}`)).json();
        if (job.status === 'done') { setExported(job.exported_video_path || 'done'); setBusy(''); }
        else if (job.status === 'failed') { setError(job.error || 'export failed'); setExported(''); setBusy(''); }
      } catch { /* keep polling; a blip is not a failure */ }
    }, 4000);
    return () => clearInterval(timer);
  }, [exported, jobId]);

  async function renderPreview() {
    if (!overlays) return;
    setBusy('preview'); setError('');
    try {
      const res = await fetch(`/api/reup/jobs/${jobId}/overlays/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ overlays, t: frameTime }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
      const blob = await res.blob();
      setPreview(old => { if (old) URL.revokeObjectURL(old); return URL.createObjectURL(blob); });
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  }

  if (!overlays) return <Card><div className="p-4 text-sm opacity-60">Đang tải…</div></Card>;

  const cover = overlays.covers[selected];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Lớp phủ — che chữ, logo, chống ăn cắp</CardTitle>
        <CardSub>Kéo để di chuyển, kéo góc dưới-phải để đổi kích thước</CardSub>
      </CardHeader>

      <div className="space-y-4 px-4 pb-4">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <label className="flex items-center gap-2">
            Khung tại giây
            <input
              type="range" min={0} max={Math.max(1, Math.floor(duration))} step={1}
              value={frameTime} onChange={e => setFrameTime(Number(e.target.value))}
              className="w-48"
            />
            <span className="w-12 tabular-nums opacity-70">{frameTime}s</span>
          </label>
          <Button onClick={() => {
            const covers = [...overlays.covers, nextCover(overlays.covers)];
            setOverlays({ ...overlays, covers });
            setSelected(covers.length - 1);
          }}>
            <Plus size={14} className="mr-1" /> Thêm vùng che
          </Button>
          <Button onClick={renderPreview} disabled={busy === 'preview'}>
            <Eye size={14} className="mr-1" /> {busy === 'preview' ? '...' : 'Xem thử'}
          </Button>
          <Button onClick={() => save(false)} disabled={busy === 'save'}>
            <Save size={14} className="mr-1" /> {busy === 'save' ? '...' : 'Lưu'}
          </Button>
          {channel && (
            <Button onClick={() => save(true)} disabled={busy === 'channel'} title={`channels/${channel}.json`}>
              <Save size={14} className="mr-1" />
              {busy === 'channel' ? '...' : 'Lưu làm mặc định kênh'}
            </Button>
          )}
          <Button onClick={saveAndExport} disabled={busy === 'export' || exported === 'running'}>
            <Film size={14} className="mr-1" />
            {exported === 'running' ? 'Đang xuất…' : 'Lưu & xuất video'}
          </Button>
          <label className="flex items-center gap-1 text-xs opacity-80" title="h264_nvenc — đo được 1,2 phút thay vì 3,1 phút, file không to hơn">
            <input type="checkbox" checked={gpu} onChange={e => setGpu(e.target.checked)} />
            GPU
          </label>
          {preview && (
            <Button onClick={() => { URL.revokeObjectURL(preview); setPreview(''); }}>
              <RotateCcw size={14} className="mr-1" /> Về ảnh gốc
            </Button>
          )}
        </div>

        {/* Every region, including ones sitting under another — the stage alone
            cannot show you a box that is fully covered by its neighbour. */}
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="opacity-60">{overlays.covers.length} vùng che:</span>
          {overlays.covers.map((c, i) => (
            <button
              key={i}
              onClick={() => setSelected(i)}
              className={
                'rounded-full border px-2 py-0.5 ' +
                (i === selected ? 'border-pink-400 bg-pink-400/20 text-pink-200' : 'border-white/25 opacity-70')
              }
            >
              {c.label || MODE_LABEL[c.mode]}
            </button>
          ))}
          {overlays.covers.length === 0 && (
            <span className="opacity-50">chưa có — bấm “Thêm vùng che”</span>
          )}
        </div>

        {/* 16:9 stage. Boxes are positioned in percentages so they track resize. */}
        <div
          ref={stageRef}
          className="relative w-full select-none overflow-hidden rounded border bg-black"
          style={{ aspectRatio: '16 / 9' }}
        >
          <img
            src={preview || frameUrl}
            alt="khung hình"
            className="pointer-events-none absolute inset-0 h-full w-full object-contain"
            draggable={false}
          />
          {!preview && overlays.covers.map((c, i) => (
            <div
              key={i}
              onPointerDown={e => {
                const at = fractionAt(e);
                dragRef.current = { kind: 'move', index: i, dx: at.x - c.x, dy: at.y - c.y };
                setSelected(i);
              }}
              className={
                'absolute cursor-move border-2 ' +
                (i === selected ? 'border-pink-400 bg-pink-400/25' : 'border-white/60 bg-white/10')
              }
              style={{
                left: `${c.x * 100}%`, top: `${c.y * 100}%`,
                width: `${c.width * 100}%`, height: `${c.height * 100}%`,
              }}
            >
              <span className="absolute -top-5 left-0 whitespace-nowrap text-[11px] text-pink-300">
                {c.label || MODE_LABEL[c.mode]}
              </span>
              <div
                onPointerDown={e => {
                  e.stopPropagation();
                  dragRef.current = { kind: 'resize', index: i };
                  setSelected(i);
                }}
                className="absolute -bottom-1.5 -right-1.5 h-3 w-3 cursor-se-resize rounded-sm bg-pink-400"
              />
            </div>
          ))}
          {!preview && (() => {
            const s = overlays.subtitle;
            const pos = subtitleBox(s);
            const col = (s.alignment - 1) % 3;           // 0 left, 1 centre, 2 right
            const row = Math.floor((s.alignment - 1) / 3); // 0 bottom, 1 middle, 2 top
            // libass scales the 384x288 reference to the video height, so a
            // FontSize of 16 draws at 16/288 of the frame. The marker has to
            // use that same ratio against the stage's real pixel height —
            // `cqh` silently resolved against the viewport (no container-type
            // anywhere), which is why the marker dwarfed the actual subtitle.
            const px = (s.font_size / ASS_H) * (stageH || 0);
            return (
              <div
                onPointerDown={e => {
                  e.stopPropagation();
                  dragRef.current = { kind: 'subtitle', index: -1, dx: 0, dy: 0 };
                }}
                title="Kéo để đặt vị trí phụ đề — cỡ chữ đúng bằng bản xuất"
                className="absolute cursor-move whitespace-nowrap border border-dashed border-sky-400/70 text-sky-50"
                style={{
                  left: `${pos.x * 100}%`,
                  top: `${pos.y * 100}%`,
                  // Anchored the way libass anchors: alignment 2 puts the text's
                  // BOTTOM at MarginV, not its centre.
                  transform: `translate(${col === 0 ? '0' : col === 2 ? '-100%' : '-50%'}, ${
                    row === 0 ? '-100%' : row === 2 ? '0' : '-50%'
                  })`,
                  fontSize: px ? `${px}px` : undefined,
                  lineHeight: 1.1,
                  // Outline and shadow are part of how big it reads on screen.
                  WebkitTextStroke: `${(s.outline / ASS_H) * (stageH || 0)}px rgba(0,0,0,.85)`,
                  paintOrder: 'stroke fill',
                }}
              >
                Phụ đề tiếng Việt
              </div>
            );
          })()}
          {preview && (
            <div className="absolute right-2 top-2 rounded bg-black/70 px-2 py-1 text-xs text-white">
              Ảnh đã render — bấm “Về ảnh gốc” để sửa tiếp
            </div>
          )}
        </div>

        {error && <div className="text-sm text-red-500">{error}</div>}
        {note && <div className="text-sm text-emerald-400">{note}</div>}
        {!channel && (
          <div className="text-xs opacity-60">
            Job này chưa gắn kênh nên lớp phủ chỉ áp cho riêng video. Chọn kênh khi tạo job
            để logo/watermark/cỡ chữ dùng chung cho cả kênh.
          </div>
        )}
        {exported === 'running' && (
          <div className="text-sm text-sky-400">
            Đang encode lại video với lớp phủ — {gpu ? 'khoảng 1,5 phút' : 'khoảng 3 phút'} cho
            video 9 phút. Cứ để trang mở.
          </div>
        )}
        {exported && exported !== 'running' && (
          <div className="break-all text-sm text-emerald-400">Đã xuất: {exported}</div>
        )}

        {/* Selected cover */}
        {cover && (
          <div className="grid grid-cols-2 gap-3 rounded border p-3 md:grid-cols-5">
            <label className="text-sm">
              <span className="mb-1 block opacity-70">Tên</span>
              <Input value={cover.label} onChange={(e: any) => patchCover(selected, { label: e.target.value })} />
            </label>
            <label className="text-sm">
              <span className="mb-1 block opacity-70">Kiểu che</span>
              <Select value={cover.mode} onChange={(e: any) => patchCover(selected, { mode: e.target.value })}>
                {(Object.keys(MODE_LABEL) as CoverMode[]).map(m => (
                  <option key={m} value={m}>{MODE_LABEL[m]}</option>
                ))}
              </Select>
            </label>
            <label className="text-sm">
              <span className="mb-1 block opacity-70">Độ mạnh {cover.strength}</span>
              <input type="range" min={2} max={40} value={cover.strength} className="w-full"
                onChange={e => patchCover(selected, { strength: Number(e.target.value) })} />
            </label>
            <label className="text-sm">
              <span className="mb-1 block opacity-70">Độ mờ {Math.round(cover.opacity * 100)}%</span>
              <input type="range" min={0} max={100} value={Math.round(cover.opacity * 100)} className="w-full"
                onChange={e => patchCover(selected, { opacity: Number(e.target.value) / 100 })} />
            </label>
            <div className="flex items-end">
              <Button onClick={() => {
                setOverlays({ ...overlays, covers: overlays.covers.filter((_, i) => i !== selected) });
                setSelected(0);
              }}>
                <Trash2 size={14} className="mr-1" /> Xoá vùng
              </Button>
            </div>
          </div>
        )}

        {/* Logo */}
        <div className="grid grid-cols-2 gap-3 rounded border p-3 md:grid-cols-5">
          <label className="col-span-2 text-sm">
            <span className="mb-1 block opacity-70">Logo kênh (đường dẫn ảnh PNG)</span>
            <Input value={overlays.logo.path} placeholder="E:\\...\\logo.png"
              onChange={(e: any) => setOverlays({ ...overlays, logo: { ...overlays.logo, path: e.target.value } })} />
          </label>
          <label className="text-sm">
            <span className="mb-1 block opacity-70">Vị trí</span>
            <Select value={overlays.logo.position}
              onChange={(e: any) => setOverlays({ ...overlays, logo: { ...overlays.logo, position: e.target.value } })}>
              <option value="top-left">Trên trái</option>
              <option value="top-right">Trên phải</option>
              <option value="bottom-left">Dưới trái</option>
              <option value="bottom-right">Dưới phải</option>
              <option value="top-center">Trên giữa</option>
              <option value="bottom-center">Dưới giữa</option>
            </Select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block opacity-70">Cỡ {Math.round(overlays.logo.scale * 100)}% bề ngang</span>
            <input type="range" min={2} max={40} value={Math.round(overlays.logo.scale * 100)} className="w-full"
              onChange={e => setOverlays({ ...overlays, logo: { ...overlays.logo, scale: Number(e.target.value) / 100 } })} />
          </label>
          <label className="text-sm">
            <span className="mb-1 block opacity-70">Độ mờ {Math.round(overlays.logo.opacity * 100)}%</span>
            <input type="range" min={0} max={100} value={Math.round(overlays.logo.opacity * 100)} className="w-full"
              onChange={e => setOverlays({ ...overlays, logo: { ...overlays.logo, opacity: Number(e.target.value) / 100 } })} />
          </label>
        </div>

        {/* Roaming watermark */}
        <div className="grid grid-cols-2 gap-3 rounded border p-3 md:grid-cols-5">
          <label className="col-span-2 flex items-end gap-2 text-sm">
            <input type="checkbox" checked={overlays.roaming.enabled}
              onChange={e => setOverlays({ ...overlays, roaming: { ...overlays.roaming, enabled: e.target.checked } })} />
            <span>Watermark chạy quanh khung (chống ăn cắp)</span>
          </label>
          <label className="col-span-2 text-sm">
            <span className="mb-1 block opacity-70">Chữ</span>
            <Input value={overlays.roaming.text} placeholder="@KenhCuaBan"
              onChange={(e: any) => setOverlays({ ...overlays, roaming: { ...overlays.roaming, text: e.target.value } })} />
          </label>
          <label className="text-sm">
            <span className="mb-1 block opacity-70">Cỡ chữ {overlays.roaming.font_size}</span>
            <input type="range" min={16} max={120} value={overlays.roaming.font_size} className="w-full"
              onChange={e => setOverlays({ ...overlays, roaming: { ...overlays.roaming, font_size: Number(e.target.value) } })} />
          </label>
          <label className="text-sm">
            <span className="mb-1 block opacity-70">Độ mờ {Math.round(overlays.roaming.opacity * 100)}%</span>
            <input type="range" min={5} max={100} value={Math.round(overlays.roaming.opacity * 100)} className="w-full"
              onChange={e => setOverlays({ ...overlays, roaming: { ...overlays.roaming, opacity: Number(e.target.value) / 100 } })} />
          </label>
          <label className="text-sm">
            <span className="mb-1 block opacity-70">Phạm vi trôi {Math.round(overlays.roaming.travel * 100)}%</span>
            <input type="range" min={0} max={100} value={Math.round(overlays.roaming.travel * 100)} className="w-full"
              onChange={e => setOverlays({ ...overlays, roaming: { ...overlays.roaming, travel: Number(e.target.value) / 100 } })} />
          </label>
        </div>

        {/* Vietnamese subtitle */}
        <div className="grid grid-cols-2 gap-3 rounded border p-3 md:grid-cols-4">
          <label className="text-sm">
            <span className="mb-1 block opacity-70">Cỡ chữ phụ đề {overlays.subtitle.font_size}</span>
            <input type="range" min={6} max={40} value={overlays.subtitle.font_size} className="w-full"
              onChange={e => setOverlays({ ...overlays, subtitle: { ...overlays.subtitle, font_size: Number(e.target.value) } })} />
          </label>
          <label className="text-sm">
            <span className="mb-1 block opacity-70">Viền {overlays.subtitle.outline}</span>
            <input type="range" min={0} max={6} value={overlays.subtitle.outline} className="w-full"
              onChange={e => setOverlays({ ...overlays, subtitle: { ...overlays.subtitle, outline: Number(e.target.value) } })} />
          </label>
          <label className="text-sm">
            <span className="mb-1 block opacity-70">
              Neo {overlays.subtitle.alignment} · lề {overlays.subtitle.margin_v}
            </span>
            <input type="range" min={0} max={200} value={overlays.subtitle.margin_v} className="w-full"
              onChange={e => setOverlays({ ...overlays, subtitle: { ...overlays.subtitle, margin_v: Number(e.target.value) } })} />
          </label>
          <label className="text-sm">
            <span className="mb-1 block opacity-70">Font</span>
            <Input value={overlays.subtitle.font_name}
              onChange={(e: any) => setOverlays({ ...overlays, subtitle: { ...overlays.subtitle, font_name: e.target.value } })} />
          </label>
        </div>

        <p className="text-xs opacity-60">
          Cỡ chữ phụ đề tính theo chuẩn ASS (khung tham chiếu 384×288), nên 12 là cỡ
          bình thường trên video 1080p. Bấm <strong>Xem thử</strong> để render một khung
          thật với toàn bộ lớp phủ trước khi xuất cả video.
        </p>
      </div>
    </Card>
  );
};
