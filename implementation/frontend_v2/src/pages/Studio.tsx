import React, { useState, useEffect } from 'react';
import { Link } from 'react-router';
import { useApi, useInvalidate } from '../api/hooks';
import { apiPost } from '../api/client';

const formatDur = (s?: number) => {
  if (s == null) return '—';
  const t = Math.round(s); // seconds may be a float (e.g. 533.70000045) — round it
  if (t >= 60) return `${Math.floor(t / 60)}m ${t % 60}s`;
  return `${t}s`;
};

export const Studio: React.FC = () => {
  const invalidate = useInvalidate();

  // App state
  const [activeChannelId, setActiveChannelId] = useState<string>('');
  const [generatorModel] = useState<string>('gemini-2.5-flash');
  const [topic, setTopic] = useState<string>('');
  const [logs, setLogs] = useState<string[]>([]);
  const [isRendering, setIsRendering] = useState(false);

  // Render override state
  const [voiceOverride, setVoiceOverride] = useState<string>('');
  const [voiceRate, setVoiceRate] = useState<string>('1.0');
  const [voicePitch, setVoicePitch] = useState<string>('0');
  const [flowImageModel, setFlowImageModel] = useState<string>('imagen4');
  const [styleOverride, setStyleOverride] = useState<string>('');
  const [musicEnabled, setMusicEnabled] = useState<boolean>(true);
  const [musicMood, setMusicMood] = useState<string>('random');
  const [musicVolume, setMusicVolume] = useState<string>('0.15');
  const [beatWords, setBeatWords] = useState<number>(15);
  const [isShorts, setIsShorts] = useState<boolean>(false);
  const [isForce, setIsForce] = useState<boolean>(false);

  const [selectedSlug, setSelectedSlug] = useState<string>('');
  const [selectedChannel, setSelectedChannel] = useState<string>('');
  const [timelineData, setTimelineData] = useState<any>(null);
  const [activePreviewAudio, setActivePreviewAudio] = useState<string>('');

  const [editScriptData, setEditScriptData] = useState<any>(null);
  const [scriptText, setScriptText] = useState<string>('');
  const [lastLoadedScriptPath, setLastLoadedScriptPath] = useState<string>('');

  // Xuong-standalone design state
  const [view, setView] = useState<'discovery' | 'script' | 'render' | 'duyet'>('discovery');
  const [drawerOpen, setDrawerOpen] = useState<boolean>(false);
  const [chanOpen, setChanOpen] = useState<boolean>(false);
  const [sceneIdx, setSceneIdx] = useState<number>(0);

  // Queries
  const { data: pipelineData } = useApi<any>('/api/pipeline', { refetchInterval: 3000 });
  const { data: channelsData } = useApi<any>('/api/channels');
  const { data: renderStatusData } = useApi<any>('/api/render/status', {
    refetchInterval: (query: any) => (query?.state?.data?.rendering ? 3000 : false),
  });
  const { data: latestVideoData, refetch: refetchLatest } = useApi<any>(
    `/api/render/latest?channel_id=${activeChannelId}`,
    { enabled: !!activeChannelId }
  );
  const { data: topicsData } = useApi<any>(`/api/topics/${activeChannelId}`, { enabled: !!activeChannelId });
  const { data: productsData, refetch: refetchProducts } = useApi<any>(
    `/api/products${activeChannelId ? '?channel_id=' + activeChannelId : ''}`
  );
  // Live agent log (debate/script events) — was invisible in the UI before.
  const { data: liveLogData } = useApi<any>(activeChannelId ? `/api/run/${activeChannelId}/log` : '', {
    enabled: !!activeChannelId, refetchInterval: 4000,
  });
  // Approval queue shown inline in the Duyệt step (was just a link).
  const { data: approvalsData } = useApi<any>('/api/approvals', { refetchInterval: 10000 });
  // Thumb Studio candidates for the selected product.
  const { data: thumbsData, refetch: refetchThumbs } = useApi<any>(
    selectedChannel && selectedSlug ? `/api/thumbs/${selectedChannel}/${selectedSlug}` : '',
    { enabled: !!(selectedChannel && selectedSlug), refetchInterval: 8000 }
  );
  const [productScript, setProductScript] = useState<string>('');
  const [thumbNote, setThumbNote] = useState<string>('');
  // Discovery workspace: topic đang mở chi tiết + kết quả check trùng lặp.
  const [selTopicId, setSelTopicId] = useState<string>('');
  const [dedupInfo, setDedupInfo] = useState<any>(null);
  const [topicBusy, setTopicBusy] = useState<string>('');
  const [showRawTopics, setShowRawTopics] = useState<boolean>(false);
  const liveEvents: any[] = liveLogData?.events || [];
  const pendingApprovals: any[] = approvalsData?.approvals || [];
  const thumbCands: string[] = thumbsData?.candidates || [];

  const handleSelectThumb = async (f: string) => {
    try {
      await fetch(`/api/thumbs/${selectedChannel}/${selectedSlug}/select`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ candidate: f }),
      });
    } catch (e) {}
    refetchThumbs(); refetchProducts();
  };
  const handleGenThumbs = async () => {
    try {
      await fetch(`/api/thumbs/${selectedChannel}/${selectedSlug}/generate`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: thumbNote, count: 4, per_angle: 2 }),
      });
    } catch (e) {}
  };
  const handleApprovalDecision = async (id: string, decision: 'approve' | 'reject') => {
    try {
      await fetch(`/api/approvals/${id}/${decision}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}),
      });
    } catch (e) {}
    invalidate('/api/approvals');
  };

  const activeJobs = pipelineData?.active_jobs || [];
  const activeJob = activeJobs.find((j: any) => j.channel_id === activeChannelId);
  const products: any[] = productsData?.products || [];
  const topics: any[] = topicsData?.topics || [];

  // ── Xưởng = workspace cho sản phẩm ĐANG LÀM. Sản phẩm đã upload (meta.youtube_id
  // do luồng publish ghi) rời Xưởng và chỉ còn trong Thư viện.
  const wipProducts = products.filter((p: any) => !p.youtube_id);
  const stageInfo = (p: any): { label: string; color: string; step: 'script' | 'render' | 'duyet' } => {
    const appr = pendingApprovals.find((a: any) => (a.video_path || '').includes(p.slug));
    if (p.video) {
      if (p.qa_ok === false) return { label: 'QA FAIL', color: 'var(--red)', step: 'render' };
      return appr
        ? { label: 'Chờ duyệt', color: 'var(--amber)', step: 'duyet' }
        : { label: 'Sẵn sàng duyệt', color: 'var(--amber)', step: 'duyet' };
    }
    if (p.script) return { label: 'Chờ render', color: 'var(--blue)', step: 'render' };
    return { label: 'Đang sinh script', color: 'var(--purple)', step: 'script' };
  };
  const selectedProduct = products.find((p: any) => p.slug === selectedSlug) || wipProducts[0] || products[0] || null;

  // Product picker — the Studio is a PER-PRODUCT workspace: every step (Script/
  // Render) shows the SELECTED product, and this dropdown switches it from any
  // step. Options carry the stage label so the operator sees status AT A GLANCE.
  const selectProduct = (slug: string, jump?: boolean) => {
    const p = products.find((x: any) => x.slug === slug);
    setSelectedSlug(slug);
    setSelectedChannel(p?.channel || activeChannelId);
    if (jump && p) setView(stageInfo(p).step);
  };
  const productPicker = wipProducts.length > 0 ? (
    <select value={selectedSlug} onChange={(e) => selectProduct(e.target.value)}
      style={{ maxWidth: 280, padding: '6px 10px', background: 'var(--surface)', color: 'var(--text)', border: '2px solid var(--ink)', borderRadius: 10, fontSize: 12, fontFamily: 'inherit', outline: 'none' }}>
      {wipProducts.map((p: any) => {
        const st = stageInfo(p);
        return (
          <option key={p.slug} value={p.slug}>
            [{st.label}{p.score != null ? ` · ${p.score}đ` : ''}] {(p.title || p.topic || p.slug).slice(0, 38)}
          </option>
        );
      })}
    </select>
  ) : null;

  // ── Discovery workspace: chỉ topic 'queued' còn dùng được. Topic đã sản xuất
  // (used) biến mất khỏi danh sách — sản phẩm của nó nằm ở board bên phải.
  const queuedTopics = topics.filter((t: any) => t.status === 'queued' && (t.score || 0) > 0);
  const rawTopics = topics.filter((t: any) => t.status === 'queued' && !((t.score || 0) > 0));

  const handleTopicScript = async (t: any, force = false) => {
    if (!activeChannelId || topicBusy) return;
    setTopicBusy(t.topic_id);
    try {
      const r = await fetch(`/api/topics/${activeChannelId}/${t.topic_id}/script${force ? '?force=true' : ''}`, { method: 'POST' });
      const d = await r.json().catch(() => ({} as any));
      if (r.status === 409) {
        if (d.status === 'already_running') {
          alert('Kênh đang chạy job khác — đợi xong rồi tạo tiếp.');
        } else if (d.status === 'duplicate_blocked') {
          alert(d.message || 'Topic này đã đăng trên chính kênh này — bị chặn.');
        } else if (d.status === 'duplicate_warning') {
          if (confirm((d.message || 'Topic tương tự đã dùng ở kênh khác.') + '\n\nVẫn tạo script?')) {
            setTopicBusy('');
            return handleTopicScript(t, true);
          }
        }
      } else if (r.ok) {
        setView('script'); // theo dõi debate live ngay
      }
      invalidate(`/api/topics/${activeChannelId}`);
      invalidate('/api/pipeline');
    } catch (e) {}
    setTopicBusy('');
  };
  const handleTopicSkip = async (t: any) => {
    if (!activeChannelId) return;
    try { await fetch(`/api/topics/${activeChannelId}/${t.topic_id}/skip`, { method: 'POST' }); } catch (e) {}
    if (selTopicId === t.topic_id) setSelTopicId('');
    invalidate(`/api/topics/${activeChannelId}`);
  };

  // /api/products already returns an absolute /pmedia/{channel}/{slug}/{file} URL
  // for video/thumbnail (server.py::_enrich_product_meta) — do not re-prefix here,
  // that produced a doubled/broken path (S1/S2 root cause).
  const videoUrl = selectedProduct?.video || '';
  const thumbnailUrl = selectedProduct?.thumbnail || '';
  const displayDuration = selectedProduct?.duration_s ?? latestVideoData?.duration_seconds ?? null;
  const displaySize = selectedProduct?.size_mb ?? latestVideoData?.size_mb ?? null;
  const displayResolution = selectedProduct?.video_probe?.streams?.[0]
    ? `${selectedProduct.video_probe.streams[0].width}x${selectedProduct.video_probe.streams[0].height}`
    : null;

  // Default channel
  useEffect(() => {
    if (channelsData?.channels?.length && !activeChannelId) {
      setActiveChannelId(channelsData.channels[0].channel_id);
    }
  }, [channelsData, activeChannelId]);

  // Default selected product
  useEffect(() => {
    const pool = wipProducts.length ? wipProducts : products;
    if (pool.length && !selectedSlug) {
      setSelectedSlug(pool[0].slug);
      setSelectedChannel(pool[0].channel || activeChannelId);
    } else if (!products.length) {
      setSelectedSlug('');
      setSelectedChannel('');
      setTimelineData(null);
    }
  }, [productsData]);

  // Load scene timeline from status.json (served under /pmedia = output/products)
  useEffect(() => {
    if (selectedSlug && selectedChannel) {
      fetch(`/pmedia/${selectedChannel}/${selectedSlug}/_status/status.json`)
        .then((res) => { if (res.ok) return res.json(); throw new Error('nf'); })
        .then((data) => setTimelineData(data))
        .catch(() => setTimelineData(null));
    } else {
      setTimelineData(null);
    }
    setSceneIdx(0);
  }, [selectedSlug, selectedChannel]);

  // Load the selected product's script for the Script step (previously the
  // step only worked in WAITING_EDIT mode and showed nothing otherwise).
  useEffect(() => {
    if (selectedSlug && selectedChannel) {
      fetch(`/pmedia/${selectedChannel}/${selectedSlug}/script.txt`)
        .then((r) => (r.ok ? r.text() : ''))
        .then((t) => setProductScript(t))
        .catch(() => setProductScript(''));
    } else {
      setProductScript('');
    }
  }, [selectedSlug, selectedChannel]);

  // Dedup check khi mở chi tiết 1 topic — cảnh báo nếu trùng nội dung đã đăng.
  useEffect(() => {
    setDedupInfo(null);
    if (selTopicId && activeChannelId) {
      const t = (topicsData?.topics || []).find((x: any) => x.topic_id === selTopicId);
      if (t) {
        fetch(`/api/dedup/check?channel_id=${activeChannelId}&title=${encodeURIComponent(t.title)}`)
          .then((r) => (r.ok ? r.json() : null))
          .then((d) => setDedupInfo(d))
          .catch(() => setDedupInfo(null));
      }
    }
  }, [selTopicId, activeChannelId, topicsData]);

  // Sync render status + logs
  useEffect(() => {
    if (renderStatusData) {
      setIsRendering(!!renderStatusData.rendering);
      if (Array.isArray(renderStatusData.log)) setLogs(renderStatusData.log);
    }
  }, [renderStatusData]);

  // WAITING_EDIT script load
  useEffect(() => {
    if (activeJob?.stage === 'WAITING_EDIT' && activeJob?.detail && activeJob.detail !== lastLoadedScriptPath) {
      fetch(`/api/script/edit?path=${encodeURIComponent(activeJob.detail)}`)
        .then((res) => res.json())
        .then((data) => {
          setEditScriptData(data);
          if (data?.scenes) setScriptText(data.scenes.map((s: any) => s.narration).join('\n\n'));
          setLastLoadedScriptPath(activeJob.detail);
          setView('script');
        })
        .catch(() => { setEditScriptData(null); setScriptText(''); });
    } else if (activeJob?.stage !== 'WAITING_EDIT') {
      setEditScriptData(null);
      setScriptText('');
      setLastLoadedScriptPath('');
    }
  }, [activeJob, lastLoadedScriptPath]);

  // SSE live logs
  useEffect(() => {
    const onJob = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.log) setLogs((prev) => [...prev, detail.log].slice(-100));
      if (detail?.job_id && detail.status === 'completed') {
        refetchLatest();
        refetchProducts();
        invalidate(`/api/render/latest?channel_id=${activeChannelId}`);
        invalidate(`/api/products?channel_id=${activeChannelId}`);
        invalidate('/api/products');
      }
    };
    window.addEventListener('omni:job-event', onJob);
    return () => window.removeEventListener('omni:job-event', onJob);
  }, [activeChannelId, refetchLatest, refetchProducts, invalidate]);

  // Handlers
  const handleDiscoverNiches = async () => {
    // Tìm topic cho KÊNH đang chọn (Phase 1) — không phải quét niche toàn cục,
    // nên không bị chặn khi niche scan đang chạy song song.
    if (!activeChannelId) return;
    try { await apiPost(`/api/run/${activeChannelId}`); invalidate('/api/topics/' + activeChannelId); invalidate('/api/pipeline'); } catch (e) {}
  };
  const handleRunScript = async () => {
    if (!activeChannelId) return;
    try {
      await apiPost(`/api/run/${activeChannelId}/script`, { topic, model: generatorModel });
      invalidate('/api/pipeline');
    } catch (e) {}
  };
  const handleStartRender = async () => {
    if (!activeChannelId) return;
    setIsRendering(true);
    setLogs(['[render] Bắt đầu sản xuất video…']);
    try {
      const q = new URLSearchParams();
      if (voiceOverride) q.append('voice', voiceOverride);
      if (voiceRate) q.append('voice_rate', voiceRate);
      if (voicePitch) q.append('voice_pitch', voicePitch);
      if (flowImageModel) q.append('flow_image_model', flowImageModel);
      if (styleOverride) q.append('style', styleOverride);
      q.append('music', musicEnabled ? 'true' : 'false');
      if (musicMood) q.append('music_mood', musicMood);
      if (musicVolume) q.append('music_volume', musicVolume);
      q.append('beat_words', String(beatWords));
      q.append('shorts', isShorts ? 'true' : 'false');
      q.append('force', isForce ? 'true' : 'false');
      if (topic) q.append('script', topic);
      const qs = q.toString();
      await apiPost(`/api/render/${activeChannelId}${qs ? '?' + qs : ''}`);
      invalidate('/api/pipeline');
    } catch (e) { setIsRendering(false); }
  };
  const handleCancelJob = async () => {
    if (!activeChannelId) return;
    try { await apiPost(`/api/run/${activeChannelId}/cancel`); invalidate('/api/render/status'); } catch (e) {}
  };
  const handleSaveEditedScript = async () => {
    if (!editScriptData || !activeJob?.detail) return;
    try {
      const paras = scriptText.split('\n\n').map((p) => p.trim()).filter(Boolean);
      const updated = editScriptData.scenes.map((sc: any, i: number) => (paras[i] ? { ...sc, narration: paras[i] } : sc));
      if (paras.length > editScriptData.scenes.length) {
        const last = editScriptData.scenes[editScriptData.scenes.length - 1] || {};
        for (let i = editScriptData.scenes.length; i < paras.length; i++)
          updated.push({ ...last, idx: i, narration: paras[i], heading: paras[i].slice(0, 40) + '...' });
      }
      await fetch(`/api/script/edit?path=${encodeURIComponent(activeJob.detail)}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...editScriptData, scenes: updated }),
      });
    } catch (e) {}
  };
  const handleResumePipeline = async () => {
    if (!activeJob?.job_id) return;
    try { await apiPost(`/api/pipelines/resume/${activeJob.job_id}`); invalidate('/api/pipeline'); } catch (e) {}
  };

  // ── OmniCast Neon standalone — Xưởng layout (khớp scratch_neon_template) ──
  const ACCENT = 'var(--accent)';
  const channels = channelsData?.channels || [];
  const activeChannel = channels.find((c: any) => c.channel_id === activeChannelId) || channels[0];
  const scenes: any[] = timelineData?.shots || [];
  const selScene = scenes[sceneIdx] || scenes[0];
  const rendering = isRendering || !!renderStatusData?.rendering;
  const progressPct = typeof renderStatusData?.progress === 'number'
    ? Math.round(renderStatusData.progress * (renderStatusData.progress <= 1 ? 100 : 1))
    : (rendering ? 60 : (selectedProduct ? 100 : 0));
  const doneScenes = scenes.filter((s: any) => (s.state || s.status) === 'done').length;

  // 4 step-card màu cố định như bản Neon: xanh ✓ / vàng ✎ / hồng ▶ / lavender 4
  const stepDefs = [
    { id: 'discovery', title: '1 · Discovery', icon: '✓', color: 'var(--green)', bg: 'var(--green-soft)', sub: queuedTopics.length ? `${queuedTopics.length} topic sẵn sàng` : '' },
    { id: 'script', title: '2 · Script', icon: '✎', color: 'var(--amber)', bg: 'var(--amber-soft)', sub: activeJob?.phase === 'script_generation' ? 'đang sinh…' : (editScriptData ? `${editScriptData?.scenes?.length ?? '?'} cảnh` : '') },
    { id: 'render', title: '3 · Render', icon: '▶', color: 'var(--accent)', bg: 'var(--accent-soft)', sub: rendering ? `${progressPct}% · đang render` : '' },
    { id: 'duyet', title: '4 · Duyệt', icon: '4', color: 'var(--text3)', bg: 'var(--surface2)', sub: pendingApprovals.length ? `${pendingApprovals.length} chờ duyệt` : '' },
  ];

  // Card lớn kiểu Neon: gradient trắng-hồng, viền ink 2px, bóng lệch + glow hồng
  const panel: React.CSSProperties = { background: 'var(--surface-gradient)', border: '2px solid var(--ink)', borderRadius: 20, padding: 16, boxShadow: '3px 3px 0 0 rgba(74,59,122,.18), 0 0 26px -8px rgba(244,95,206,.42)' };
  const qcBox: React.CSSProperties = { background: 'var(--surface2)', border: '2px solid var(--ink)', borderRadius: 14, padding: '9px 11px', boxShadow: 'var(--shadow-hard-sm)' };
  const pillBtn: React.CSSProperties = { background: 'var(--surface)', color: 'var(--text)', border: '2px solid var(--ink)', borderRadius: 999, padding: '7px 14px', fontSize: 12, fontWeight: 700, boxShadow: 'var(--shadow-hard-sm)', cursor: 'pointer', fontFamily: 'var(--font-display)' };
  const pillBtnPrimary: React.CSSProperties = { ...pillBtn, background: 'linear-gradient(135deg,var(--red),var(--accent))', color: '#fff' };
  const mono = "'IBM Plex Mono', monospace";
  const GRADS = ['linear-gradient(135deg,#8db4ff,#c9b3ff)', 'linear-gradient(135deg,#7fe6d8,#a9d4ff)', 'linear-gradient(135deg,#c79dff,#ffb3e6)', 'linear-gradient(135deg,#9db8ff,#7fe6d8)', 'linear-gradient(135deg,#ffb3e6,#c9b3ff)', 'linear-gradient(135deg,#a9d4ff,#c79dff)'];

  // Live Monitor: tô màu [tag] như bản Neon (tts xanh lá, image xanh dương, flow/music tím, render hồng)
  const TAG_COLORS: Record<string, string> = { tts: 'var(--green-ink)', audio: 'var(--green-ink)', image: 'var(--blue)', imagen: 'var(--blue)', flow: 'var(--purple)', music: 'var(--purple)', render: 'var(--accent)', video: 'var(--accent)', error: 'var(--red)', fail: 'var(--red)' };
  const renderLogLine = (line: string, key: number) => {
    const m = line.match(/^(\[[^\]]*\])\s*(\[[^\]]*\])?\s*(.*)$/);
    if (!m) return <div key={key}>{line}</div>;
    const [, t1, t2, rest] = m;
    const tagOf = (s?: string) => { if (!s) return null; const w = s.replace(/[\[\]]/g, '').toLowerCase(); const hit = Object.keys(TAG_COLORS).find((k) => w.includes(k)); return hit ? TAG_COLORS[hit] : null; };
    const c1 = tagOf(t1); const c2 = tagOf(t2);
    return (
      <div key={key}>
        <span style={{ color: c1 || 'var(--text3)', fontWeight: c1 ? 700 : 400 }}>{t1}</span>
        {t2 && <> <span style={{ color: c2 || 'var(--purple)', fontWeight: 700 }}>{t2}</span></>}
        {' '}{rest}
      </div>
    );
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Page header — khớp bản Neon: title sparkle + subtitle; kênh & trạng thái bên phải */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h2 className="disp text-2xl font-extrabold text-[var(--heading)]" style={{ margin: 0, textShadow: '0 0 18px rgba(244,95,206,.30)' }}>
            Xưởng sản xuất <span className="text-[15px] tracking-[3px] text-[var(--accent)]" style={{ textShadow: '0 0 10px rgba(244,95,206,.65)' }}>⋆｡˚✧</span>
          </h2>
          <p className="text-xs text-[var(--text2)]" style={{ margin: '2px 0 0' }}>Quy trình 4 bước: Discovery → Script → Render → Duyệt</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span className="disp" style={{ display: 'inline-flex', alignItems: 'center', gap: 7, background: rendering ? 'var(--accent-soft)' : 'var(--green-soft)', border: '2px solid var(--ink)', borderRadius: 999, padding: '5px 13px', fontSize: 12, fontWeight: 700, color: rendering ? 'var(--accent)' : '#1a9e7a', boxShadow: 'var(--shadow-hard-sm)' }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: rendering ? 'var(--accent)' : 'var(--green)', animation: 'pulseDot 1.6s infinite' }}></span>
            {rendering ? 'Đang render' : 'Đã kết nối'}
          </span>
          <div style={{ position: 'relative' }}>
            <div onClick={() => setChanOpen((o) => !o)} style={{ display: 'flex', alignItems: 'center', gap: 9, background: 'var(--surface)', border: '2px solid var(--ink)', borderRadius: 12, padding: '5px 12px', cursor: 'pointer', boxShadow: 'var(--shadow-hard-sm)' }}>
              <span style={{ width: 24, height: 24, borderRadius: 8, background: 'linear-gradient(135deg,var(--accent),var(--purple))', border: '1.5px solid var(--ink)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11 }}>🎬</span>
              <div>
                <div className="disp" style={{ fontSize: 13, fontWeight: 700, color: 'var(--heading)', lineHeight: 1.2 }}>{activeChannel?.name || activeChannel?.channel_id || 'Chọn kênh'}</div>
                <div style={{ fontSize: 9.5, color: 'var(--text3)', fontFamily: mono, lineHeight: 1.2 }}>{activeChannel?.channel_id || ''}</div>
              </div>
              <span style={{ color: 'var(--text3)', marginLeft: 2 }}>▾</span>
            </div>
            {chanOpen && (
              <div style={{ position: 'absolute', top: 46, right: 0, width: 250, background: 'var(--surface-gradient)', border: '2px solid var(--ink)', borderRadius: 16, padding: 6, boxShadow: 'var(--shadow-hard), var(--glow)', zIndex: 30 }}>
                {channels.map((c: any) => (
                  <div key={c.channel_id} onClick={() => { setActiveChannelId(c.channel_id); setSelectedSlug(''); setChanOpen(false); }} className="hover:bg-[var(--accent-soft)]" style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '9px 10px', borderRadius: 10, cursor: 'pointer' }}>
                    <span style={{ width: 24, height: 24, borderRadius: 8, background: 'linear-gradient(135deg,var(--accent),var(--purple))', border: '1.5px solid var(--ink)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, flexShrink: 0 }}>🎬</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{c.name || c.channel_id}</div>
                      <div style={{ fontSize: 9.5, color: 'var(--text3)', fontFamily: mono }}>{c.channel_id}</div>
                    </div>
                    {c.channel_id === activeChannelId && <span style={{ color: ACCENT }}>✓</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Stepper — 4 card màu (khớp bản Neon: bg soft màu bước, badge tròn, ring hồng khi active) */}
      <div style={{ display: 'flex', alignItems: 'stretch', gap: 8 }}>
        {stepDefs.map((s) => (
          <div
            key={s.id}
            onClick={() => setView(s.id as any)}
            style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 11, padding: '12px 15px', borderRadius: 16, cursor: 'pointer', background: s.bg, border: '2px solid var(--ink)', boxShadow: `${view === s.id ? '0 0 0 3px rgba(244,95,206,.25), ' : ''}2px 2px 0 0 rgba(74,59,122,.15)` }}
          >
            <div className="disp" style={{ width: 34, height: 34, borderRadius: '50%', background: s.color, border: '2px solid var(--ink)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 800, flexShrink: 0 }}>{s.icon}</div>
            <div style={{ minWidth: 0 }}>
              <div className="disp" style={{ fontSize: 13, fontWeight: 700, color: 'var(--heading)' }}>{s.title}</div>
              <div style={{ fontSize: 11, fontWeight: 700, color: s.color, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.sub}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Split content */}
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
        {/* LEFT WORK PANEL */}
        <div style={{ flex: 1.55, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 14 }}>
          {view === 'render' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div style={panel}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, gap: 10, flexWrap: 'wrap' }}>
                  <div className="disp" style={{ fontSize: 16, fontWeight: 700, color: 'var(--heading)' }}>Bước 3 · Render Video</div>
                  {productPicker}
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button onClick={handleStartRender} disabled={rendering} style={{ ...pillBtn, opacity: rendering ? 0.5 : 1 }}>↻ Render lại</button>
                    {rendering
                      ? <button onClick={handleCancelJob} style={pillBtnPrimary}>■ Huỷ Job</button>
                      : <button onClick={handleStartRender} style={pillBtnPrimary}>▶ Render</button>}
                  </div>
                </div>
                <div style={{ aspectRatio: '16/9', borderRadius: 16, border: '2px solid var(--ink)', background: videoUrl ? '#000' : 'linear-gradient(160deg,#8db4ff,#b79cff 60%,#ffb3e6)', display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative', overflow: 'hidden', boxShadow: videoUrl ? undefined : 'inset 0 -30px 50px rgba(74,59,122,.25)' }}>
                  {videoUrl
                    ? <video src={videoUrl} controls poster={thumbnailUrl || undefined} style={{ width: '100%', height: '100%', objectFit: 'contain', background: '#000' }} />
                    : (
                      <>
                        <div style={{ position: 'absolute', top: 20, left: 30, fontSize: 22, color: '#fff', filter: 'drop-shadow(0 0 6px #fff)' }}>✦</div>
                        <div style={{ position: 'absolute', bottom: 60, right: 70, fontSize: 15, color: '#fff', filter: 'drop-shadow(0 0 6px #fff)' }}>✦</div>
                        <div onClick={handleStartRender} style={{ width: 64, height: 64, borderRadius: '50%', background: 'rgba(255,255,255,.85)', border: '2px solid var(--ink)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent)', fontSize: 24, paddingLeft: 4, cursor: 'pointer', boxShadow: '0 4px 0 0 rgba(74,59,122,.25)' }}>▶</div>
                        <div className="disp" style={{ position: 'absolute', bottom: 14, left: 16, color: '#fff', fontSize: 15, fontWeight: 700, textShadow: '0 1px 4px rgba(74,59,122,.6)' }}>{selectedProduct?.title || topic || 'Chưa có video — bấm ▶ để render'}</div>
                      </>
                    )}
                  {selectedProduct && (
                    <span className="disp" style={{ position: 'absolute', top: 12, right: 12, fontSize: 11, fontWeight: 800, color: '#fff', background: selectedProduct?.qa_ok === false ? 'var(--red)' : 'var(--green)', border: '2px solid var(--ink)', padding: '3px 10px', borderRadius: 999, pointerEvents: 'none' }}>{selectedProduct?.qa_ok === false ? 'QA FAIL' : 'QA PASS'}</span>
                  )}
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10, marginTop: 14 }}>
                  <div style={qcBox}><div style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 600 }}>Thời lượng</div><div className="disp" style={{ fontSize: 15, fontWeight: 800, color: 'var(--heading)', fontFamily: mono }}>{formatDur(displayDuration)}</div></div>
                  <div style={qcBox}><div style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 600 }}>Phân giải</div><div className="disp" style={{ fontSize: 15, fontWeight: 800, color: 'var(--heading)', fontFamily: mono }}>{displayResolution || '—'}</div></div>
                  <div style={qcBox}><div style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 600 }}>Dung lượng</div><div className="disp" style={{ fontSize: 15, fontWeight: 800, color: 'var(--heading)', fontFamily: mono }}>{displaySize ? Math.round(displaySize) + ' MB' : '—'}</div></div>
                  <div style={qcBox}><div style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 600 }}>Cảnh xong</div><div className="disp" style={{ fontSize: 15, fontWeight: 800, color: 'var(--heading)', fontFamily: mono }}>{doneScenes} / {scenes.length || (selectedProduct?.scene_count || 0)}</div></div>
                </div>
              </div>

              {/* Timeline phân cảnh — card riêng full-width như bản Neon */}
              <div style={{ ...panel, minWidth: 0 }}>
                <div className="disp" style={{ fontSize: 14, fontWeight: 700, color: 'var(--heading)', marginBottom: 12 }}>Timeline phân cảnh <span style={{ color: 'var(--text3)', fontWeight: 600 }}>({scenes.length})</span></div>
                <div style={{ display: 'flex', gap: 10, overflowX: 'auto', paddingBottom: 6 }}>
                  {scenes.length === 0 && <div style={{ color: 'var(--text3)', fontSize: 12, padding: 8 }}>Chưa có phân cảnh (render xong sẽ hiện).</div>}
                  {scenes.map((c: any, i: number) => {
                    const st = c.state || c.status;
                    const done = st === 'done'; const running = st === 'running'; const sel = i === sceneIdx;
                    const dot = done ? 'var(--green)' : running ? 'var(--accent)' : '#c9b8f0';
                    const thumbBase: React.CSSProperties = { aspectRatio: '16/9', borderRadius: 12, position: 'relative', overflow: 'hidden', display: 'flex', cursor: 'pointer' };
                    const thumb: React.CSSProperties = (done || running)
                      ? { ...thumbBase, background: running ? 'linear-gradient(135deg,#f45fce,#a877ff)' : GRADS[i % GRADS.length], border: '2px solid var(--ink)', boxShadow: `${sel ? '0 0 0 3px rgba(244,95,206,.3), ' : ''}2px 2px 0 0 rgba(74,59,122,.15)` }
                      : { ...thumbBase, background: 'var(--surface3)', border: '2px dashed #c9b8f0', boxShadow: sel ? '0 0 0 3px rgba(244,95,206,.3)' : undefined };
                    return (
                      <div key={i} style={{ flex: '0 0 130px' }}>
                        <div onClick={() => setSceneIdx(i)} style={thumb}>
                          <span style={{ position: 'absolute', top: 5, left: 5, background: 'rgba(74,59,122,.75)', color: '#fff', fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 999, fontFamily: mono }}>#{i}</span>
                          <span style={{ position: 'absolute', top: 5, right: 5, width: 11, height: 11, borderRadius: '50%', border: '2px solid #fff', background: dot }}></span>
                        </div>
                        <div className="disp" style={{ fontSize: 10.5, marginTop: 7, lineHeight: 1.3, height: 27, overflow: 'hidden', color: (done || running || sel) ? 'var(--text2)' : 'var(--text3)', fontWeight: 600 }}>{c.heading || ''}</div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Cảnh đang chọn — panel chức năng, style Neon */}
              {selScene && (
                <div style={{ ...panel, boxShadow: '0 0 0 3px rgba(244,95,206,.25), 2px 2px 0 0 rgba(74,59,122,.15)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                    <div className="disp" style={{ fontSize: 13, fontWeight: 700, color: 'var(--heading)' }}>Cảnh đang chọn · <span style={{ color: ACCENT, fontFamily: mono }}>#{sceneIdx}</span></div>
                    <span className="disp" style={{ fontSize: 10, fontWeight: 800, color: '#fff', background: (selScene.state || selScene.status) === 'done' ? 'var(--green)' : ((selScene.state || selScene.status) === 'running' ? 'var(--accent)' : 'var(--text3)'), border: '1.5px solid var(--ink)', borderRadius: 999, padding: '2px 9px' }}>{(selScene.state || selScene.status) === 'done' ? 'Xong' : ((selScene.state || selScene.status) === 'running' ? 'Đang tạo' : 'Chờ')}</span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text2)', lineHeight: 1.5, marginBottom: 12 }}>{selScene.heading || selScene.narration || ''}</div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button onClick={() => setActivePreviewAudio(`/pmedia/${selectedChannel}/${selectedSlug}/_assets/scene_${String(sceneIdx).padStart(2, '0')}.mp3`)} style={{ ...pillBtn, flex: 1, color: 'var(--accent)' }}>▶ Nghe audio</button>
                    <button onClick={handleStartRender} style={{ ...pillBtn, flex: '0 0 auto' }}>↻</button>
                  </div>
                  {activePreviewAudio && <audio src={activePreviewAudio} controls autoPlay style={{ width: '100%', marginTop: 8, height: 30 }} />}
                </div>
              )}
            </div>
          )}

          {view === 'script' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {editScriptData ? (
                <>
                  <div style={{ background: 'var(--amber-soft)', border: '2px solid var(--amber)', borderRadius: 14, padding: 14 }}>
                    <div className="disp" style={{ fontSize: 12, fontWeight: 800, color: 'var(--amber)', textTransform: 'uppercase', letterSpacing: '.04em', display: 'inline-flex', alignItems: 'center', gap: 7 }}><span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--amber)', animation: 'pulseDot 1.6s infinite' }}></span>Chờ duyệt kịch bản</div>
                    <p style={{ fontSize: 12, color: 'var(--text2)', margin: '8px 0 0', lineHeight: 1.5 }}>Chỉnh sửa kịch bản phân cảnh bên dưới rồi bấm <b style={{ color: 'var(--text)' }}>Tiếp tục chạy</b>. Mỗi phân cảnh cách nhau bởi 1 dòng trống.</p>
                  </div>
                  <div style={panel}>
                    <div className="disp" style={{ fontSize: 16, fontWeight: 700, color: 'var(--heading)', marginBottom: 10 }}>Bước 2 · Script</div>
                    <textarea value={scriptText} onChange={(e) => setScriptText(e.target.value)} style={{ width: '100%', height: 300, padding: 12, background: 'var(--surface)', color: 'var(--text)', border: '2px solid var(--ink)', borderRadius: 12, fontSize: 12, lineHeight: 1.7, resize: 'none', outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box' }} />
                    <div style={{ display: 'flex', gap: 9, marginTop: 12 }}>
                      <button onClick={handleSaveEditedScript} style={{ ...pillBtn, flex: 1, padding: '10px 14px', fontSize: 13 }}>💾 Lưu kịch bản</button>
                      <button onClick={handleResumePipeline} style={{ ...pillBtnPrimary, flex: 1, padding: '10px 14px', fontSize: 13 }}>▶ Tiếp tục chạy</button>
                    </div>
                  </div>
                </>
              ) : (
                <>
                  {activeJob && activeJob.phase === 'script_generation' && (
                    <div style={panel}>
                      <div className="disp" style={{ fontSize: 14, fontWeight: 700, color: 'var(--heading)', marginBottom: 10, display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--green)', animation: 'pulseDot 1.4s infinite' }}></span>
                        Đang sinh script — theo dõi agent trực tiếp
                      </div>
                      <div style={{ fontFamily: mono, fontSize: 11, lineHeight: 1.9, color: 'var(--text2)', maxHeight: 240, overflowY: 'auto' }}>
                        {liveEvents.length === 0 && <div style={{ color: 'var(--text3)' }}>Chờ sự kiện đầu tiên…</div>}
                        {liveEvents.slice(-40).map((e: any, i: number) => (
                          <div key={i}>▸ {e.msg}</div>
                        ))}
                      </div>
                    </div>
                  )}
                  <div style={panel}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10, gap: 10, flexWrap: 'wrap' }}>
                      <div className="disp" style={{ fontSize: 16, fontWeight: 700, color: 'var(--heading)' }}>Bước 2 · Script</div>
                      {productPicker}
                      {selectedProduct?.score != null && (
                        <span className="disp" style={{ fontSize: 11, fontWeight: 800, color: '#fff', background: 'var(--green)', border: '1.5px solid var(--ink)', borderRadius: 999, padding: '3px 11px' }}>{selectedProduct.score} điểm</span>
                      )}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 8 }}>{selectedProduct?.title || selectedProduct?.topic || selectedSlug || 'Chưa chọn sản phẩm'}</div>
                    <pre style={{ whiteSpace: 'pre-wrap', margin: 0, padding: 12, background: 'var(--surface)', border: '2px solid var(--border-soft)', borderRadius: 12, fontSize: 12, lineHeight: 1.7, color: 'var(--text)', maxHeight: 380, overflowY: 'auto', fontFamily: 'inherit' }}>
                      {productScript || 'Chưa có script cho sản phẩm này — chọn sản phẩm ở Lịch sử render, hoặc chạy Sinh Script ở Bước 1.'}
                    </pre>
                  </div>
                </>
              )}
            </div>
          )}

          {view === 'discovery' && (
            <div style={panel}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                <div className="disp" style={{ fontSize: 16, fontWeight: 700, color: 'var(--heading)' }}>Bước 1 · Discovery</div>
                <button onClick={handleDiscoverNiches} disabled={activeJob?.phase === 'discovery'} style={{ ...pillBtn, opacity: activeJob?.phase === 'discovery' ? 0.5 : 1 }}>
                  {activeJob?.phase === 'discovery' ? '⏳ Đang quét…' : '🔍 Tìm topic mới'}
                </button>
              </div>
              <label className="disp" style={{ fontSize: 11, fontWeight: 800, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.05em' }}>Chủ đề tuỳ chỉnh</label>
              <div style={{ display: 'flex', gap: 8, marginTop: 7 }}>
                <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Nhập chủ đề…" style={{ flex: 1, padding: '10px 13px', background: 'var(--surface)', color: 'var(--text)', border: '2px solid var(--ink)', borderRadius: 12, fontSize: 13, fontFamily: 'inherit', outline: 'none' }} />
                <button onClick={handleRunScript} style={{ ...pillBtnPrimary, padding: '0 16px', fontSize: 13 }}>Sinh Script ▶</button>
              </div>

              <div style={{ fontSize: 11, color: 'var(--text3)', margin: '14px 0 8px', fontWeight: 600 }}>
                Topic đề xuất ({queuedTopics.length}) — đã loại topic đã sản xuất/đã đăng. Bấm 1 topic để xem chi tiết.
              </div>
              {queuedTopics.length === 0 && (
                <div style={{ fontSize: 12, color: 'var(--text3)', padding: '10px 0' }}>Hàng chờ trống — bấm 🔍 Tìm topic mới để quét nguồn (đối thủ YouTube, Trends, Reddit, tin tức).</div>
              )}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                {queuedTopics.map((t: any, i: number) => {
                  const open = selTopicId === t.topic_id;
                  const scoreColor = t.score >= 85 ? 'var(--green)' : t.score >= 70 ? 'var(--amber)' : 'var(--text3)';
                  return (
                    <div key={t.topic_id} style={{ background: open ? 'var(--accent-soft)' : 'var(--surface2)', border: open ? '2px solid var(--ink)' : '1.5px solid var(--border-soft)', borderRadius: 12, boxShadow: open ? 'var(--shadow-hard-sm)' : undefined }}>
                      <div onClick={() => setSelTopicId(open ? '' : t.topic_id)} style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '10px 12px', cursor: 'pointer' }}>
                        <span style={{ fontSize: 12, fontWeight: 700, color: ACCENT, width: 20, fontFamily: mono }}>{i + 1}</span>
                        <span style={{ flex: 1, fontSize: 13, color: 'var(--text)', fontWeight: open ? 700 : 500 }}>{t.title}</span>
                        <span className="disp" style={{ fontSize: 10, fontWeight: 800, color: '#fff', background: scoreColor, border: '1.5px solid var(--ink)', padding: '2px 9px', borderRadius: 999 }}>{t.score}</span>
                        <span style={{ color: 'var(--text3)', fontSize: 11 }}>{open ? '▴' : '▾'}</span>
                      </div>
                      {open && (
                        <div style={{ padding: '0 12px 12px 43px' }}>
                          <div style={{ display: 'grid', gridTemplateColumns: '96px 1fr', gap: '5px 10px', fontSize: 12, lineHeight: 1.5 }}>
                            <span style={{ color: 'var(--text3)', fontWeight: 700 }}>Khán giả</span>
                            <span style={{ color: 'var(--text)' }}>{t.audience_segment || '—'}</span>
                            <span style={{ color: 'var(--text3)', fontWeight: 700 }}>Nỗi đau</span>
                            <span style={{ color: 'var(--text)' }}>{t.pain_point || '—'}</span>
                            <span style={{ color: 'var(--text3)', fontWeight: 700 }}>Góc khai thác</span>
                            <span style={{ color: 'var(--text)' }}>{t.content_angle || '—'}</span>
                            <span style={{ color: 'var(--text3)', fontWeight: 700 }}>Nguồn</span>
                            <span>{t.source_url ? <a href={t.source_url} target="_blank" rel="noreferrer" style={{ color: ACCENT, fontWeight: 700, textDecoration: 'none' }}>{t.source_url.slice(0, 52)}…</a> : '—'}</span>
                            <span style={{ color: 'var(--text3)', fontWeight: 700 }}>Phát hiện</span>
                            <span style={{ color: 'var(--text2)', fontFamily: mono, fontSize: 11 }}>{(t.discovered_at || '').slice(0, 16).replace('T', ' ')}</span>
                          </div>
                          <div style={{ marginTop: 9 }}>
                            {dedupInfo == null && <span style={{ fontSize: 11, color: 'var(--text3)' }}>Đang kiểm tra trùng lặp…</span>}
                            {dedupInfo?.severity === 'block' && <span className="disp" style={{ fontSize: 10, fontWeight: 800, color: '#fff', background: 'var(--red)', border: '1.5px solid var(--ink)', padding: '3px 10px', borderRadius: 999 }}>⛔ Đã đăng trên kênh này — không dùng lại</span>}
                            {dedupInfo?.severity === 'warn' && <span className="disp" style={{ fontSize: 10, fontWeight: 800, color: '#fff', background: 'var(--amber)', border: '1.5px solid var(--ink)', padding: '3px 10px', borderRadius: 999 }}>⚠ Tương tự video đã đăng kênh khác</span>}
                            {dedupInfo?.severity === 'ok' && <span className="disp" style={{ fontSize: 10, fontWeight: 800, color: '#fff', background: 'var(--green)', border: '1.5px solid var(--ink)', padding: '3px 10px', borderRadius: 999 }}>✓ Không trùng nội dung đã đăng</span>}
                          </div>
                          <div style={{ display: 'flex', gap: 8, marginTop: 11 }}>
                            <button onClick={() => handleTopicScript(t)} disabled={!!topicBusy || dedupInfo?.severity === 'block'} className="disp" style={{ ...pillBtnPrimary, flex: 1, padding: '9px 0', fontSize: 12, opacity: (topicBusy || dedupInfo?.severity === 'block') ? 0.5 : 1 }}>
                              {topicBusy === t.topic_id ? '⏳ Đang khởi động…' : '▶ Tạo script từ topic này'}
                            </button>
                            <button onClick={() => handleTopicSkip(t)} className="disp" style={{ ...pillBtn, padding: '9px 14px', fontSize: 12, color: 'var(--text2)' }}>Bỏ qua</button>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>

              {rawTopics.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div onClick={() => setShowRawTopics((s) => !s)} style={{ fontSize: 11, color: 'var(--text3)', fontWeight: 700, cursor: 'pointer' }}>
                    {showRawTopics ? '▴' : '▾'} Topic thô chưa chấm điểm ({rawTopics.length}) — tiêu đề quét từ đối thủ, KHÔNG nên dùng trực tiếp (rủi ro trùng nội dung)
                  </div>
                  {showRawTopics && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 5, marginTop: 7 }}>
                      {rawTopics.map((t: any) => (
                        <div key={t.topic_id} style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '7px 11px', background: 'var(--surface2)', border: '1.5px dashed var(--border-soft)', borderRadius: 10 }}>
                          <span style={{ flex: 1, fontSize: 12, color: 'var(--text3)' }}>{t.title}</span>
                          <button onClick={() => handleTopicSkip(t)} style={{ background: 'none', border: 'none', color: 'var(--red)', cursor: 'pointer', fontSize: 11, fontWeight: 700, fontFamily: 'inherit' }}>Loại</button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {view === 'duyet' && (
            <div style={panel}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                <div className="disp" style={{ fontSize: 16, fontWeight: 700, color: 'var(--heading)' }}>Bước 4 · Duyệt & Đăng</div>
                <span className="disp" style={{ fontSize: 11, fontWeight: 800, color: '#fff', background: pendingApprovals.length ? 'var(--amber)' : 'var(--text3)', border: '1.5px solid var(--ink)', borderRadius: 999, padding: '3px 11px' }}>{pendingApprovals.length} chờ duyệt</span>
              </div>
              {pendingApprovals.length === 0 && (
                <div style={{ fontSize: 13, color: 'var(--text3)', padding: '14px 0' }}>Không có video nào đang chờ duyệt. Video PASS QC sẽ tự xuất hiện ở đây.</div>
              )}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
                {pendingApprovals.map((a: any) => (
                  <div key={a.approval_id} style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '10px 12px', background: 'var(--surface2)', border: '1.5px solid var(--border-soft)', borderRadius: 12 }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.title || a.raw?.title || a.video_path || a.approval_id}</div>
                      <div style={{ fontSize: 10, color: 'var(--text3)', fontFamily: mono }}>{a.channel_id || ''} · {a.requested_at || ''}</div>
                    </div>
                    <button onClick={() => handleApprovalDecision(a.approval_id, 'approve')} className="disp" style={{ background: 'var(--green)', color: '#fff', border: '2px solid var(--ink)', borderRadius: 999, padding: '6px 13px', fontSize: 11, fontWeight: 800, cursor: 'pointer', boxShadow: 'var(--shadow-hard-sm)' }}>✓ Duyệt</button>
                    <button onClick={() => handleApprovalDecision(a.approval_id, 'reject')} className="disp" style={{ background: 'var(--surface)', color: 'var(--red)', border: '2px solid var(--ink)', borderRadius: 999, padding: '6px 13px', fontSize: 11, fontWeight: 800, cursor: 'pointer', boxShadow: 'var(--shadow-hard-sm)' }}>✕ Từ chối</button>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 12 }}>
                <Link to="/approvals" className="disp" style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent)', textDecoration: 'none' }}>Mở trang Duyệt & Đăng đầy đủ (QC, bản quyền, lịch đăng) →</Link>
              </div>
            </div>
          )}
        </div>

        {/* RIGHT CONTEXT */}
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={panel}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <div className="disp" style={{ fontSize: 14, fontWeight: 700, color: 'var(--heading)' }}>Cấu hình sản xuất</div>
              <button onClick={() => setDrawerOpen(true)} className="disp" style={{ background: 'var(--accent-soft)', border: '2px solid var(--ink)', color: 'var(--accent)', fontSize: 11, fontWeight: 700, borderRadius: 999, padding: '5px 12px', cursor: 'pointer', boxShadow: 'var(--shadow-hard-sm)' }}>Chỉnh ✎</button>
            </div>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '5px 0' }}><span style={{ color: 'var(--text3)' }}>Giọng đọc</span><span style={{ color: 'var(--heading)', fontWeight: 700 }}>{voiceOverride || 'Mặc định'} · {voiceRate}×</span></div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '5px 0' }}><span style={{ color: 'var(--text3)' }}>Model ảnh</span><span style={{ color: 'var(--heading)', fontWeight: 700 }}>{flowImageModel}</span></div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '5px 0' }}><span style={{ color: 'var(--text3)' }}>AI Script</span><span style={{ color: 'var(--heading)', fontWeight: 700 }}>{generatorModel}</span></div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '5px 0' }}><span style={{ color: 'var(--text3)' }}>Nhạc nền</span><span style={{ color: 'var(--heading)', fontWeight: 700 }}>{musicEnabled ? `${musicMood} · ${Math.round(parseFloat(musicVolume) * 100)}%` : 'Tắt'}</span></div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '5px 0' }}><span style={{ color: 'var(--text3)' }}>Định dạng</span><span style={{ color: 'var(--heading)', fontWeight: 700 }}>{isShorts ? '9:16' : '16:9'} · {beatWords} từ/beat</span></div>
            </div>
          </div>

          {/* Live Monitor — nền tím nhạt + tag màu, khớp bản Neon */}
          <div style={{ background: 'var(--surface3)', border: '2px solid var(--ink)', borderRadius: 20, padding: 16, boxShadow: '3px 3px 0 0 rgba(74,59,122,.18), 0 0 26px -8px rgba(244,95,206,.42)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
              <span style={{ width: 9, height: 9, borderRadius: '50%', background: rendering ? 'var(--green)' : 'var(--text3)', animation: rendering ? 'pulseDot 1.4s infinite' : undefined }}></span>
              <div className="disp" style={{ fontSize: 13, fontWeight: 700, color: 'var(--heading)' }}>Live Monitor</div>
              {rendering && <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--text3)', fontFamily: mono }}>{progressPct}%</span>}
            </div>
            <div style={{ fontFamily: mono, fontSize: 11, lineHeight: 1.8, color: 'var(--text2)', maxHeight: 190, overflowY: 'auto' }}>
              {activeJob?.phase === 'script_generation' && liveEvents.slice(-25).map((e: any, i: number) => (
                <div key={'dbt' + i} style={{ color: 'var(--text2)' }}>▸ {e.msg}</div>
              ))}
              {logs.length === 0 && !(activeJob?.phase === 'script_generation' && liveEvents.length) && (
                <div style={{ color: 'var(--text3)' }}>Chưa có log — bắt đầu chạy để xem tiến trình.</div>
              )}
              {logs.map((l: string, i: number) => renderLogLine(l, i))}
            </div>
          </div>

          {/* Thumb Studio — chọn thumb chính thức / tạo batch mới kèm yêu cầu */}
          <div style={panel}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
              <div className="disp" style={{ fontSize: 14, fontWeight: 700, color: 'var(--heading)' }}>Thumbnail</div>
              <span style={{ fontSize: 10, color: 'var(--text3)', fontFamily: mono }}>{thumbCands.length} ứng viên</span>
            </div>
            {selectedProduct?.thumbnail && (
              <div style={{ marginBottom: 8 }}>
                <img src={selectedProduct.thumbnail + '?t=' + (thumbsData?.selected || '')} alt="thumb" style={{ width: '100%', borderRadius: 10, border: '2px solid var(--green)', display: 'block' }} />
                <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>✅ Bản chính thức hiện tại</div>
              </div>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, maxHeight: 260, overflowY: 'auto' }}>
              {thumbCands.map((f: string) => (
                <div key={f} style={{ position: 'relative' }}>
                  <img src={`/pmedia/${selectedChannel}/${selectedSlug}/thumbs/${f}`} alt={f} style={{ width: '100%', borderRadius: 8, border: thumbsData?.selected === f ? '2.5px solid var(--green)' : '1.5px solid var(--border-soft)', display: 'block', cursor: 'pointer' }} onClick={() => handleSelectThumb(f)} title="Bấm để dùng làm thumb chính thức" />
                </div>
              ))}
            </div>
            {thumbCands.length === 0 && <div style={{ fontSize: 12, color: 'var(--text3)' }}>Chưa có ứng viên — tạo batch bên dưới.</div>}
            <textarea value={thumbNote} onChange={(e) => setThumbNote(e.target.value)} placeholder="Yêu cầu cho agent tạo thumb (vd: mặt kinh hãi hơn, thêm mũi tên đỏ chỉ vào ly cà phê…)" style={{ width: '100%', minHeight: 52, marginTop: 10, padding: 10, background: 'var(--surface)', color: 'var(--text)', border: '2px solid var(--ink)', borderRadius: 10, fontSize: 12, fontFamily: 'inherit', resize: 'vertical', outline: 'none', boxSizing: 'border-box' }} />
            <button onClick={handleGenThumbs} className="disp" style={{ ...pillBtnPrimary, width: '100%', marginTop: 8, padding: '9px 0', fontSize: 12 }}>⚡ Tạo batch thumb (Flow · 4 góc × 2)</button>
          </div>

          <div style={{ ...panel, flex: 1 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 11 }}>
              <div className="disp" style={{ fontSize: 14, fontWeight: 700, color: 'var(--heading)' }}>Sản phẩm trong xưởng</div>
              <span style={{ fontSize: 11, color: 'var(--text3)' }}>{wipProducts.length} đang làm</span>
            </div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 8 }}>Bấm 1 sản phẩm → nhảy tới bước nó đang chờ. Sản phẩm đã đăng nằm ở Thư viện.</div>
            {wipProducts.length === 0 && (
              <div style={{ fontSize: 12, color: 'var(--text3)', padding: '8px 0' }}>Xưởng trống — chọn topic ở Bước 1 để bắt đầu sản phẩm mới.</div>
            )}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {wipProducts.map((h: any, i: number) => {
                const st = stageInfo(h);
                return (
                  <div key={h.slug || i} onClick={() => selectProduct(h.slug, true)} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: 8, background: h.slug === selectedSlug ? 'var(--accent-soft)' : 'var(--surface2)', border: h.slug === selectedSlug ? '2px solid var(--ink)' : '1.5px solid var(--border-soft)', borderRadius: 12, cursor: 'pointer', boxShadow: h.slug === selectedSlug ? 'var(--shadow-hard-sm)' : undefined }}>
                    <div style={{ width: 44, height: 28, borderRadius: 8, background: GRADS[i % GRADS.length], border: '1.5px solid var(--ink)', flexShrink: 0 }}></div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{h.title || h.topic || h.slug}</div>
                      <div style={{ fontSize: 10, color: 'var(--text3)', fontFamily: mono }}>
                        {h.score != null ? `${h.score}đ · ` : ''}{formatDur(h.duration_s)}{h.llm_cost_script_usd ? ` · $${(Number(h.llm_cost_script_usd) + Number(h.llm_cost_render_usd || 0)).toFixed(2)}` : ''}
                      </div>
                    </div>
                    <span className="disp" style={{ fontSize: 10, fontWeight: 800, color: '#fff', background: st.color, border: '1.5px solid var(--ink)', borderRadius: 999, padding: '2px 9px', whiteSpace: 'nowrap' }}>{st.label}</span>
                  </div>
                );
              })}
            </div>
            <div style={{ marginTop: 10 }}>
              <Link to="/library" className="disp" style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent)', textDecoration: 'none' }}>Thư viện — sản phẩm đã hoàn thành →</Link>
            </div>
          </div>
        </div>
      </div>

      {/* CONFIG DRAWER */}
      {drawerOpen && <div onClick={() => setDrawerOpen(false)} style={{ position: 'fixed', inset: 0, background: 'rgba(42,26,74,.4)', backdropFilter: 'blur(4px)', zIndex: 40 }}></div>}
      <aside style={{ position: 'fixed', top: 0, right: 0, bottom: 0, width: 340, background: 'var(--surface-gradient)', borderLeft: '2px solid var(--ink)', display: 'flex', flexDirection: 'column', zIndex: 41, transform: drawerOpen ? 'translateX(0)' : 'translateX(100%)', transition: 'transform .2s' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '18px 18px 14px', borderBottom: '2px solid var(--border-soft)' }}>
          <div className="disp" style={{ fontSize: 16, fontWeight: 800, color: 'var(--heading)' }}>Cấu hình sản xuất</div>
          <button onClick={() => setDrawerOpen(false)} style={{ width: 30, height: 30, borderRadius: 10, background: 'var(--surface)', border: '2px solid var(--ink)', color: 'var(--text2)', cursor: 'pointer', fontSize: 14, boxShadow: 'var(--shadow-hard-sm)' }}>✕</button>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: 18, display: 'flex', flexDirection: 'column', gap: 18 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 10 }}>🎙 Giọng đọc & TTS</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <input value={voiceOverride} onChange={(e) => setVoiceOverride(e.target.value)} placeholder="provider:voice_id (vd edge:vi-VN-...)" style={{ background: 'var(--surface)', border: '2px solid var(--ink)', borderRadius: 10, padding: '10px 12px', fontSize: 13, color: 'var(--text)', fontFamily: 'inherit', outline: 'none' }} />
              <div><div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text2)', marginBottom: 5 }}><span>Tốc độ</span><span style={{ color: ACCENT, fontFamily: mono }}>{voiceRate}×</span></div><input type="range" min="0.5" max="1.5" step="0.05" value={voiceRate} onChange={(e) => setVoiceRate(e.target.value)} style={{ width: '100%', accentColor: ACCENT }} /></div>
              <div><div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text2)', marginBottom: 5 }}><span>Pitch</span><span style={{ color: ACCENT, fontFamily: mono }}>{voicePitch}</span></div><input type="range" min="-10" max="10" step="1" value={voicePitch} onChange={(e) => setVoicePitch(e.target.value)} style={{ width: '100%', accentColor: ACCENT }} /></div>
            </div>
          </div>
          <div style={{ borderTop: '2px solid var(--border-soft)', paddingTop: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 10 }}>🖼 Hình ảnh & Style</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <select value={flowImageModel} onChange={(e) => setFlowImageModel(e.target.value)} style={{ background: 'var(--surface)', border: '2px solid var(--ink)', borderRadius: 10, padding: '10px 12px', fontSize: 13, color: 'var(--text)', fontFamily: 'inherit' }}>
                <option value="imagen4">Imagen 4</option><option value="nano-banana">Nano Banana</option><option value="nano-banana-pro">Nano Banana Pro</option>
              </select>
              <input value={styleOverride} onChange={(e) => setStyleOverride(e.target.value)} placeholder="Ghi đè style…" style={{ background: 'var(--surface)', border: '2px solid var(--ink)', borderRadius: 10, padding: '10px 12px', fontSize: 13, color: 'var(--text)', fontFamily: 'inherit', outline: 'none' }} />
            </div>
          </div>
          <div style={{ borderTop: '2px solid var(--border-soft)', paddingTop: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 10 }}>🎵 Nhạc nền</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--text)' }}><input type="checkbox" checked={musicEnabled} onChange={(e) => setMusicEnabled(e.target.checked)} style={{ accentColor: ACCENT }} />Bật nhạc nền</label>
              <input value={musicMood} onChange={(e) => setMusicMood(e.target.value)} placeholder="Mood (calm, uplifting…)" style={{ background: 'var(--surface)', border: '2px solid var(--ink)', borderRadius: 10, padding: '10px 12px', fontSize: 13, color: 'var(--text)', fontFamily: 'inherit', outline: 'none' }} />
              <div><div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text2)', marginBottom: 5 }}><span>Âm lượng</span><span style={{ color: ACCENT, fontFamily: mono }}>{Math.round(parseFloat(musicVolume) * 100)}%</span></div><input type="range" min="0" max="1" step="0.01" value={musicVolume} onChange={(e) => setMusicVolume(e.target.value)} style={{ width: '100%', accentColor: ACCENT }} /></div>
            </div>
          </div>
          <div style={{ borderTop: '2px solid var(--border-soft)', paddingTop: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 10 }}>📐 Nhịp & Định dạng</div>
            <div><div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text2)', marginBottom: 5 }}><span>Từ/beat</span><span style={{ color: ACCENT, fontFamily: mono }}>{beatWords}</span></div><input type="range" min="8" max="30" step="1" value={beatWords} onChange={(e) => setBeatWords(parseInt(e.target.value))} style={{ width: '100%', accentColor: ACCENT }} /></div>
            <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
              <label style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 8, background: 'var(--surface)', border: '2px solid var(--ink)', borderRadius: 10, padding: '10px 12px', fontSize: 12, color: 'var(--text)', cursor: 'pointer' }}><input type="checkbox" checked={isShorts} onChange={(e) => setIsShorts(e.target.checked)} style={{ accentColor: ACCENT }} />Shorts 9:16</label>
              <label style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 8, background: 'var(--surface)', border: '2px solid var(--ink)', borderRadius: 10, padding: '10px 12px', fontSize: 12, color: 'var(--text)', cursor: 'pointer' }}><input type="checkbox" checked={isForce} onChange={(e) => setIsForce(e.target.checked)} style={{ accentColor: ACCENT }} />Force QC</label>
            </div>
          </div>
        </div>
        <div style={{ padding: '16px 18px', borderTop: '2px solid var(--border-soft)' }}>
          <button onClick={() => setDrawerOpen(false)} className="disp" style={{ width: '100%', background: 'linear-gradient(135deg,var(--red),var(--accent))', color: '#fff', border: '2px solid var(--ink)', borderRadius: 999, padding: 11, fontSize: 13, fontWeight: 700, cursor: 'pointer', boxShadow: 'var(--shadow-hard-sm)' }}>Áp dụng cấu hình</button>
        </div>
      </aside>
    </div>
  );
};
