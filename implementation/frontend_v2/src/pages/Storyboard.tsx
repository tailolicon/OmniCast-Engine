import React, { useMemo, useRef, useState } from 'react';
import { useApi, useInvalidate } from '../api/hooks';
import { apiPatch, apiPost } from '../api/client';
import {
  Badge,
  Button,
  Card,
  CardSub,
  CardTitle,
  Checkbox,
  EmptyState,
  Input,
  Select,
  Skeleton,
} from '../components/ui';
import {
  AlertTriangle,
  Check,
  Clapperboard,
  Image as ImageIcon,
  RefreshCw,
  Upload,
} from 'lucide-react';

/** Trang Storyboard — nơi người duyệt DÀN VAI trước khi hệ thống đốt credit ảnh.
 *
 *  Vì sao có màn này: một ảnh tham chiếu sai thì SAI Ở MỌI KHUNG HÌNH gắn nó.
 *  Backend (omnicast/storyboard/pipeline.py) cố tình dừng ở trạng thái
 *  `cast_pending` và chờ; trang này là chỗ trả lời. Mọi thứ hiển thị ở đây đều
 *  do backend tính (`derived`), không tính lại ở client — để trình duyệt và
 *  cổng kiểm tra không bao giờ nói hai điều khác nhau. */

type Img = { image_id: string; path: string; url: string; view: string; role: string; source: string; approved: boolean };
type Entity = { entity_id: string; kind: string; name: string; description: string; aliases: string[]; conflicts: string[]; images: Img[] };
type Mapping = { token: string; entity_id: string; name: string; kind: string; role: string; path: string; url: string };
type Frame = { frame_id: string; shot_id: string; frame_type: string; base_prompt: string; rendered_prompt: string; mappings: Mapping[]; image_path: string; url: string; approved: boolean };
type Shot = { shot_id: string; index: number; title: string; voiceover: string; camera_shot: string; angle: string; movement: string; location_id: string | null; cast: { entity_id: string }[]; declared_changes: string[] };
type Board = { board_id: string; channel_id: string; title: string; status: string; style_prompt: string; entities: Entity[]; shots: Shot[]; frames: Frame[]; notes: string[] };
type Issue = { shot_index: number; axis: string; severity: string; detail: string; evidence: string };
type Derived = {
  cast_ready: boolean;
  unready: { entity_id: string; name: string; reason: string }[];
  working: boolean;
  continuity: { blocked: boolean; hard_count: number; warn_count: number; issues: Issue[] } | null;
};
type BoardResponse = { board: Board; derived: Derived };

const STATUS_LABEL: Record<string, string> = {
  draft: 'Nháp',
  cast_pending: 'Chờ duyệt dàn vai',
  cast_approved: 'Đã duyệt dàn vai',
  frames_ready: 'Đã dựng khung hình',
  blocked: 'Bị chặn',
  approved: 'Đã duyệt',
  rendered: 'Đã render',
};

const STATUS_VARIANT: Record<string, 'green' | 'blue' | 'amber' | 'red' | 'purple' | 'neutral'> = {
  draft: 'neutral',
  cast_pending: 'amber',
  cast_approved: 'blue',
  frames_ready: 'blue',
  blocked: 'red',
  approved: 'green',
  rendered: 'green',
};

const KIND_LABEL: Record<string, string> = {
  character: 'Nhân vật',
  location: 'Bối cảnh',
  prop: 'Đạo cụ',
  costume: 'Trang phục',
};

const ROLE_LABEL: Record<string, string> = {
  identity: 'nhận dạng',
  wardrobe: 'trang phục',
  prop: 'đạo cụ',
  environment: 'bối cảnh',
  style: 'phong cách',
  pose: 'dáng',
};

const STEPS = ['draft', 'cast_pending', 'cast_approved', 'frames_ready', 'approved'];

export const Storyboard: React.FC = () => {
  const invalidate = useInvalidate();
  const [boardId, setBoardId] = useState<string>('');
  const [busy, setBusy] = useState<string>('');
  const [err, setErr] = useState<string>('');
  const [channelId, setChannelId] = useState('quiet_hours_drama_us');
  const [scriptText, setScriptText] = useState('');
  const [tab, setTab] = useState<'cast' | 'shots' | 'issues'>('cast');

  const listPath = '/api/storyboards';
  const { data: list } = useApi<{ boards: any[] }>(listPath, { refetchInterval: 15000 });
  const boardPath = boardId ? `/api/storyboards/${boardId}` : '';
  const { data, isLoading } = useApi<BoardResponse>(boardPath, {
    enabled: !!boardId,
    // Chỉ poll khi backend đang chạy nền (dựng ref sheet / render khung hình).
    refetchInterval: (q: any) => (q?.state?.data?.derived?.working ? 3000 : false),
  });

  const board = data?.board;
  const derived = data?.derived;
  const boards = list?.boards || [];

  const run = async (label: string, fn: () => Promise<any>) => {
    setBusy(label);
    setErr('');
    try {
      await fn();
      invalidate(boardPath);
      invalidate(listPath);
    } catch (e: any) {
      // Thông điệp 409 của backend nêu đích danh entity còn thiếu gì — hiện
      // nguyên văn, đừng rút gọn thành "thất bại".
      setErr(e?.message || String(e));
    } finally {
      setBusy('');
    }
  };

  const usedIds = useMemo(
    () => new Set((board?.shots || []).flatMap((s) => [...s.cast.map((c) => c.entity_id), s.location_id].filter(Boolean) as string[])),
    [board],
  );

  return (
    <div className="p-6 space-y-5">
      <div>
        <h1 className="text-2xl font-black text-[var(--text)] flex items-center gap-2">
          <Clapperboard className="w-6 h-6 text-[var(--purple)]" /> Storyboard
        </h1>
        <CardSub>
          Dàn vai + khung hình có ràng ảnh tham chiếu. Duyệt dàn vai một lần, phần còn lại chạy tự động.
        </CardSub>
      </div>

      {/* ── Chọn / tạo bảng ── */}
      <Card className="p-4 space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[280px]">
            <label className="text-[10px] font-extrabold uppercase tracking-wider text-[var(--text2)]">Bảng đang mở</label>
            <Select value={boardId} onChange={(e) => setBoardId(e.target.value)}>
              <option value="">— chọn một storyboard —</option>
              {boards.map((b: any) => (
                <option key={b.board_id} value={b.board_id}>
                  {(b.title || b.board_id)} · {b.channel_id} · {STATUS_LABEL[b.status] || b.status}
                </option>
              ))}
            </Select>
          </div>
          <div className="min-w-[220px]">
            <label className="text-[10px] font-extrabold uppercase tracking-wider text-[var(--text2)]">Kênh (tạo mới)</label>
            <Input value={channelId} onChange={(e) => setChannelId(e.target.value)} />
          </div>
          <Button
            variant="primary"
            disabled={!!busy || !scriptText.trim()}
            onClick={() =>
              run('create', async () => {
                const r = await apiPost<BoardResponse>('/api/storyboards', {
                  channel_id: channelId,
                  script_text: scriptText,
                });
                setBoardId(r.board.board_id);
              })
            }
          >
            {busy === 'create' ? 'Đang bóc tách…' : 'Tạo từ kịch bản'}
          </Button>
        </div>
        <textarea
          value={scriptText}
          onChange={(e) => setScriptText(e.target.value)}
          placeholder="Dán kịch bản vào đây để bóc tách dàn vai + phân cảnh…"
          className="w-full h-24 px-3 py-2 rounded-[12px] border-2 border-[var(--ink)] bg-[var(--surface)] text-[var(--text)] text-sm font-mono"
        />
      </Card>

      {err && (
        <Card className="p-3 border-[var(--red)]">
          <div className="flex items-start gap-2 text-sm text-[var(--red)] font-bold">
            <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
            <span className="whitespace-pre-wrap">{err}</span>
          </div>
        </Card>
      )}

      {!boardId && (
        <EmptyState
          icon={<Clapperboard className="w-10 h-10" />}
          title="Chưa mở storyboard nào"
          desc="Chọn một bảng có sẵn, hoặc dán kịch bản để tạo mới."
        />
      )}

      {boardId && isLoading && <Skeleton h="240px" />}

      {board && derived && (
        <>
          {/* ── Trạng thái + hành động ── */}
          <Card className="p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <CardTitle>{board.title || board.board_id}</CardTitle>
                <Badge variant={STATUS_VARIANT[board.status] || 'neutral'}>
                  {STATUS_LABEL[board.status] || board.status}
                </Badge>
                {derived.working && <Badge variant="blue">Đang chạy nền…</Badge>}
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  disabled={!!busy || derived.working}
                  onClick={() => run('prepare', () => apiPost(`/api/storyboards/${boardId}/cast/prepare`))}
                >
                  <RefreshCw className="w-3.5 h-3.5 mr-1" /> Dựng ảnh tham chiếu
                </Button>
                <Button
                  variant="primary"
                  disabled={!!busy || derived.working || !derived.cast_ready}
                  title={derived.cast_ready ? '' : 'Còn thành viên chưa có ảnh được duyệt'}
                  onClick={() => run('approve', () => apiPost(`/api/storyboards/${boardId}/cast/approve`))}
                >
                  <Check className="w-3.5 h-3.5 mr-1" /> Duyệt dàn vai
                </Button>
                <Button
                  disabled={!!busy || derived.working}
                  onClick={() => run('frames', () => apiPost(`/api/storyboards/${boardId}/frames/build`))}
                >
                  Dựng khung hình
                </Button>
                <Button
                  disabled={!!busy || derived.working || !board.frames.length}
                  onClick={() => run('render', () => apiPost(`/api/storyboards/${boardId}/frames/render`, {}))}
                >
                  <ImageIcon className="w-3.5 h-3.5 mr-1" /> Render ảnh
                </Button>
                <Button
                  disabled={!!busy || derived.working || !board.frames.length}
                  onClick={() => run('finalize', () => apiPost(`/api/storyboards/${boardId}/finalize`))}
                >
                  Chạy cổng liên tục
                </Button>
              </div>
            </div>

            {/* Stepper */}
            <div className="flex items-center gap-1">
              {STEPS.map((s, i) => {
                const done = STEPS.indexOf(board.status) >= i && board.status !== 'blocked';
                return (
                  <React.Fragment key={s}>
                    <div
                      className={`px-2.5 py-1 rounded-full text-[10px] font-extrabold border-2 border-[var(--ink)] ${
                        done ? 'bg-[var(--green)] text-white' : 'bg-[var(--surface2)] text-[var(--text3)]'
                      }`}
                    >
                      {STATUS_LABEL[s]}
                    </div>
                    {i < STEPS.length - 1 && <div className="w-4 h-0.5 bg-[var(--border-soft)]" />}
                  </React.Fragment>
                );
              })}
            </div>

            {!derived.cast_ready && derived.unready.length > 0 && (
              <div className="rounded-[12px] border-2 border-[var(--amber)] bg-[var(--surface2)] p-3">
                <div className="text-[10px] font-extrabold uppercase tracking-wider text-[var(--text2)] mb-1">
                  Chưa duyệt được — còn thiếu
                </div>
                <ul className="text-xs text-[var(--text)] space-y-0.5">
                  {derived.unready.map((u) => (
                    <li key={u.entity_id}>
                      <b>{u.name}</b>: {u.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Card>

          {/* ── Tabs ── */}
          <div className="flex gap-1">
            {([
              ['cast', `Dàn vai (${board.entities.length})`],
              ['shots', `Phân cảnh (${board.shots.length})`],
              ['issues', `Liên tục${derived.continuity ? ` (${derived.continuity.hard_count}⛔ ${derived.continuity.warn_count}⚠)` : ''}`],
            ] as const).map(([k, label]) => (
              <button
                key={k}
                onClick={() => setTab(k as any)}
                className={`px-3 py-1.5 rounded-full text-xs font-extrabold border-2 border-[var(--ink)] ${
                  tab === k ? 'bg-[var(--purple)] text-white' : 'bg-[var(--surface)] text-[var(--text2)]'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {tab === 'cast' && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {board.entities.map((e) => (
                <CastCard
                  key={e.entity_id}
                  entity={e}
                  used={usedIds.has(e.entity_id)}
                  busy={!!busy}
                  onApproveImage={(imageId, approved) =>
                    run('img', () =>
                      apiPost(`/api/storyboards/${boardId}/images/${imageId}/approve`, { approved }),
                    )
                  }
                  onUpload={(dataUrl) =>
                    run('upload', () =>
                      apiPost(`/api/storyboards/${boardId}/entities/${e.entity_id}/upload`, { data: dataUrl }),
                    )
                  }
                  onRegenerate={(description) =>
                    run('regen', () =>
                      apiPost(`/api/storyboards/${boardId}/entities/${e.entity_id}/regenerate`, { description }),
                    )
                  }
                  onResolve={() =>
                    run('resolve', () =>
                      apiPost(`/api/storyboards/${boardId}/entities/${e.entity_id}/resolve-conflict`),
                    )
                  }
                />
              ))}
            </div>
          )}

          {tab === 'shots' && (
            <div className="space-y-3">
              {board.shots.map((s) => (
                <ShotCard
                  key={s.shot_id}
                  shot={s}
                  board={board}
                  busy={!!busy}
                  onEditFrame={(frameId, basePrompt) =>
                    run('frame', () =>
                      apiPatch(`/api/storyboards/${boardId}/frames/${frameId}`, { base_prompt: basePrompt }),
                    )
                  }
                />
              ))}
            </div>
          )}

          {tab === 'issues' && <IssuesPanel derived={derived} notes={board.notes} />}
        </>
      )}
    </div>
  );
};

// ── Một thành viên dàn vai ───────────────────────────────────────────────────
const CastCard: React.FC<{
  entity: Entity;
  used: boolean;
  busy: boolean;
  onApproveImage: (imageId: string, approved: boolean) => void;
  onUpload: (dataUrl: string) => void;
  onRegenerate: (description: string) => void;
  onResolve: () => void;
}> = ({ entity, used, busy, onApproveImage, onUpload, onRegenerate, onResolve }) => {
  const fileRef = useRef<HTMLInputElement>(null);
  const [desc, setDesc] = useState(entity.description);
  const approvedCount = entity.images.filter((i) => i.approved).length;

  const pick = (file?: File) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => onUpload(String(reader.result || ''));
    reader.readAsDataURL(file);
  };

  return (
    <Card className={`p-4 space-y-3 ${entity.conflicts.length ? 'border-[var(--red)]' : ''}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <CardTitle>{entity.name}</CardTitle>
            <Badge variant="purple">{KIND_LABEL[entity.kind] || entity.kind}</Badge>
            {!used && <Badge variant="neutral">không xuất hiện ở cảnh nào</Badge>}
            {approvedCount > 0 ? (
              <Badge variant="green">{approvedCount} ảnh đã duyệt</Badge>
            ) : (
              <Badge variant="amber">chưa duyệt ảnh</Badge>
            )}
          </div>
          {entity.aliases.length > 0 && (
            <CardSub>Còn gọi là: {entity.aliases.join(' · ')}</CardSub>
          )}
        </div>
      </div>

      {entity.conflicts.length > 0 && (
        <div className="rounded-[12px] border-2 border-[var(--red)] p-2 space-y-1">
          <div className="text-[10px] font-extrabold uppercase text-[var(--red)]">Xung đột gộp thực thể — phải xử lý</div>
          {entity.conflicts.map((c, i) => (
            <div key={i} className="text-xs text-[var(--text)]">{c}</div>
          ))}
          <Button size="sm" disabled={busy} onClick={onResolve}>Giữ nguyên, đánh dấu đã xử lý</Button>
        </div>
      )}

      <div className="flex gap-2 overflow-x-auto pb-1">
        {entity.images.length === 0 && (
          <div className="text-xs text-[var(--text3)] py-6">Chưa có ảnh tham chiếu.</div>
        )}
        {entity.images.map((im) => (
          <div key={im.image_id} className="shrink-0 w-32 space-y-1">
            <div className="w-32 h-32 rounded-[10px] border-2 border-[var(--ink)] overflow-hidden bg-[var(--surface2)]">
              {im.url ? (
                <img src={im.url} alt={im.view} className="w-full h-full object-cover" />
              ) : (
                <div className="w-full h-full grid place-items-center text-[10px] text-[var(--text3)] p-1 text-center">
                  không hiển thị được
                </div>
              )}
            </div>
            <div className="text-[10px] text-[var(--text2)] font-bold truncate" title={`${im.view} · ${im.role}`}>
              {im.view} · {ROLE_LABEL[im.role] || im.role}
            </div>
            <label className="flex items-center gap-1 text-[10px] text-[var(--text2)] cursor-pointer">
              <Checkbox
                checked={im.approved}
                disabled={busy}
                onChange={(e) => onApproveImage(im.image_id, e.target.checked)}
              />
              Duyệt {im.source === 'operator' && <b>(tải lên)</b>}
            </label>
          </div>
        ))}
      </div>

      <textarea
        value={desc}
        onChange={(e) => setDesc(e.target.value)}
        placeholder="Mô tả ngoại hình để vẽ lại cho khớp…"
        className="w-full h-16 px-2 py-1.5 rounded-[10px] border-2 border-[var(--ink)] bg-[var(--surface)] text-[var(--text)] text-xs"
      />
      <div className="flex gap-2">
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          className="hidden"
          onChange={(e) => pick(e.target.files?.[0])}
        />
        <Button size="sm" disabled={busy} onClick={() => fileRef.current?.click()}>
          <Upload className="w-3 h-3 mr-1" /> Tải ảnh thật
        </Button>
        <Button size="sm" disabled={busy} onClick={() => onRegenerate(desc)}>
          <RefreshCw className="w-3 h-3 mr-1" /> Vẽ lại
        </Button>
      </div>
    </Card>
  );
};

// ── Một phân cảnh + các khung hình của nó ────────────────────────────────────
const ShotCard: React.FC<{
  shot: Shot;
  board: Board;
  busy: boolean;
  onEditFrame: (frameId: string, basePrompt: string) => void;
}> = ({ shot, board, busy, onEditFrame }) => {
  const frames = board.frames.filter((f) => f.shot_id === shot.shot_id);
  const nameOf = (id: string) => board.entities.find((e) => e.entity_id === id)?.name || id;

  return (
    <Card className="p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-black text-[var(--text3)]">#{shot.index}</span>
        <CardTitle>{shot.title || '(chưa đặt tên)'}</CardTitle>
        <Badge variant="blue">{shot.camera_shot}</Badge>
        <Badge variant="neutral">{shot.angle}</Badge>
        <Badge variant="neutral">{shot.movement}</Badge>
      </div>
      <div className="flex flex-wrap gap-1">
        {shot.cast.map((c) => (
          <span key={c.entity_id} className="px-2 py-0.5 rounded-full bg-[var(--purple-soft)] text-[10px] font-bold text-[var(--text2)]">
            {nameOf(c.entity_id)}
          </span>
        ))}
        {shot.location_id && (
          <span className="px-2 py-0.5 rounded-full bg-[var(--accent-soft)] text-[10px] font-bold text-[var(--text2)]">
            📍 {nameOf(shot.location_id)}
          </span>
        )}
      </div>
      {shot.declared_changes.length > 0 && (
        <div className="text-[10px] text-[var(--text2)]">
          Thay đổi có chủ ý: {shot.declared_changes.join(' · ')}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {frames.map((f) => (
          <FrameCard key={f.frame_id} frame={f} busy={busy} onEdit={onEditFrame} />
        ))}
        {frames.length === 0 && (
          <div className="text-xs text-[var(--text3)]">Chưa dựng khung hình cho cảnh này.</div>
        )}
      </div>
    </Card>
  );
};

const FrameCard: React.FC<{
  frame: Frame;
  busy: boolean;
  onEdit: (frameId: string, basePrompt: string) => void;
}> = ({ frame, busy, onEdit }) => {
  const [text, setText] = useState(frame.base_prompt);
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-[12px] border-2 border-[var(--ink)] p-2 space-y-2 bg-[var(--surface)]">
      <div className="flex items-center gap-2">
        <Badge variant="amber">{frame.frame_type}</Badge>
        {frame.url ? <Badge variant="green">đã render</Badge> : <Badge variant="neutral">chưa render</Badge>}
      </div>
      {frame.url && (
        <img src={frame.url} alt={frame.frame_type} className="w-full rounded-[8px] border-2 border-[var(--ink)]" />
      )}

      {/* Bảng ràng buộc ảnh — thứ cần đọc ĐẦU TIÊN khi khuôn mặt ra sai. */}
      <div className="space-y-1">
        <div className="text-[10px] font-extrabold uppercase tracking-wider text-[var(--text2)]">
          Ảnh tham chiếu đã gắn
        </div>
        {frame.mappings.length === 0 && (
          <div className="text-[10px] text-[var(--red)] font-bold">
            Không gắn ảnh nào — model sẽ tự bịa ngoại hình.
          </div>
        )}
        <div className="flex gap-1.5 flex-wrap">
          {frame.mappings.map((m) => (
            <div key={m.token} className="flex items-center gap-1 px-1.5 py-1 rounded-[8px] bg-[var(--surface2)] border border-[var(--border-soft)]">
              {m.url && <img src={m.url} alt={m.name} className="w-7 h-7 rounded object-cover border border-[var(--ink)]" />}
              <div className="text-[9px] leading-tight">
                <div className="font-black text-[var(--text)]">{m.token}</div>
                <div className="text-[var(--text3)]">{m.name} · {ROLE_LABEL[m.role] || m.role}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        className="w-full h-20 px-2 py-1.5 rounded-[10px] border-2 border-[var(--ink)] bg-[var(--surface)] text-[var(--text)] text-[11px]"
      />
      <div className="flex gap-2">
        <Button size="sm" disabled={busy || text === frame.base_prompt} onClick={() => onEdit(frame.frame_id, text)}>
          Lưu &amp; ràng lại token
        </Button>
        <Button size="sm" variant="secondary" onClick={() => setOpen(!open)}>
          {open ? 'Ẩn' : 'Xem'} prompt gửi đi
        </Button>
      </div>
      {open && (
        <pre className="text-[9px] whitespace-pre-wrap bg-[var(--surface2)] p-2 rounded-[8px] border border-[var(--border-soft)] max-h-64 overflow-auto">
          {frame.rendered_prompt}
        </pre>
      )}
    </div>
  );
};

// ── Báo cáo liên tục ─────────────────────────────────────────────────────────
const IssuesPanel: React.FC<{ derived: Derived; notes: string[] }> = ({ derived, notes }) => {
  const c = derived.continuity;
  return (
    <div className="space-y-4">
      <Card className="p-4 space-y-2">
        <CardTitle>Cổng liên tục</CardTitle>
        {!c && <CardSub>Chưa chạy — cần dựng khung hình trước.</CardSub>}
        {c && c.issues.length === 0 && (
          <div className="text-sm text-[var(--green-ink)] font-bold">Không phát hiện vấn đề nào.</div>
        )}
        {c &&
          c.issues.map((i, n) => (
            <div
              key={n}
              className={`rounded-[10px] border-2 p-2 ${
                i.severity === 'hard' ? 'border-[var(--red)]' : 'border-[var(--amber)]'
              }`}
            >
              <div className="flex items-center gap-2 mb-0.5">
                <Badge variant={i.severity === 'hard' ? 'red' : 'amber'}>
                  {i.severity === 'hard' ? 'CHẶN' : 'CẢNH BÁO'}
                </Badge>
                <span className="text-[10px] font-extrabold uppercase text-[var(--text2)]">
                  {i.shot_index >= 0 ? `Cảnh ${i.shot_index}` : 'Toàn bảng'} · {i.axis}
                </span>
              </div>
              <div className="text-xs text-[var(--text)]">{i.detail}</div>
              {i.evidence && (
                <div className="text-[10px] text-[var(--text3)] font-mono mt-1">{i.evidence}</div>
              )}
            </div>
          ))}
      </Card>

      {notes.length > 0 && (
        <Card className="p-4 space-y-1">
          <CardTitle>Nhật ký dựng bảng</CardTitle>
          <CardSub>Mọi thứ hệ thống tự sửa hoặc bỏ qua đều ghi ở đây — không có gì bị bỏ im lặng.</CardSub>
          <ul className="text-xs text-[var(--text2)] space-y-0.5 mt-2">
            {notes.map((n, i) => (
              <li key={i}>• {n}</li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
};
