// ============================================================================
// OmniCast Engine — Pixel Office (embeds the REAL Pixel Agents / agent-office
// webview, built from https://github.com/harishkotra/agent-office which is built
// on pixel-agents (MIT)). We serve its static bundle at /office_app and drive it
// with the SAME postMessage protocol the VS Code extension uses:
//   agentCreated {id, folderName}      → spawn a pixel character at a desk
//   agentStatus  {id, status}          → active = walk to desk + type; idle = wander
// This gives a pixel-for-pixel identical office (walls, floors, furniture, walk
// animation, bubbles) instead of a hand-ported lookalike. The 12 OmniCast agents
// are mapped to characters; their activity follows the real pipeline.
// ============================================================================
(function () {
  const { useEffect, useRef, useState } = React;

  // Self-contained pipeline→agent mapping. (office_canvas.jsx defines its own copy
  // inside a separate IIFE that this file cannot see — referencing it here always
  // threw "undefined" so every agent stayed idle. Keep a local copy here.)
  const PHASE_AGENTS = {
    niche_scan: ['scanner', 'research', 'scorer'],
    discovery: ['research', 'scorer', 'scanner'],
    writing: ['writer'], script_generation: ['writer', 'critic'], scriptgen: ['writer'],
    critic: ['critic'],
    image_generation: ['visual', 'media'],
    render: ['media', 'quality'], rendering: ['media'],
    policy_scan: ['compliance'],
    upload: ['upload'], analytics: ['analytics'], abtest: ['abtest'],
  };
  // Per-agent tool drives the sitting animation: reading tools (Read/Grep/Glob/
  // WebFetch/WebSearch) → "reading" pose, others → "typing" pose. Picked to fit
  // each role so the office looks like real work, not everyone typing identically.
  const TOOL_BY_AGENT = {
    research: 'WebSearch', scorer: 'Read', scanner: 'WebFetch',
    writer: 'Write', critic: 'Read', visual: 'Edit',
    media: 'Bash', compliance: 'Read', quality: 'Grep',
    upload: 'Bash', abtest: 'Edit', analytics: 'Read',
  };
  // Debate narration — turns a raw orchestrator live_log event into a line a real
  // co-worker would say, and decides WHO says it (writer ↔ critic talking to each
  // other). The machine numbers (VO/Prod/Total, 8-dim breakdown) live in the right
  // panel; the bubble is plain conversation + the actual fix the critic wants.
  // Returns { who:'writer'|'critic', text } or null (event not worth a bubble).
  function narrateDebate(e) {
    const t = e.type;
    if (t === 'writer_start') return { who: 'writer', text: 'Để mình phác vài bản nháp cho chủ đề này đã…' };
    if (t === 'writer_done') return { who: 'writer', text: 'Nháp xong! Đưa giám khảo soi thử nào.' };
    if (t === 'debate_start') return { who: 'writer', text: `Bản #${e.variant_id != null ? e.variant_id : ''} vào vòng phản biện đây.` };
    if (t === 'thinking') {
      // e.msg = "Thinking (model) → variant_x Rn: <note>" — pull the note after the colon.
      const note = String(e.msg || '').split(': ').slice(1).join(': ').trim();
      return { who: 'writer', text: note ? ('Để mình tự soi lại: ' + note) : 'Để mình tự soi lại đoạn vừa viết…' };
    }
    if (t === 'round') {
      if (e.approved) return { who: 'critic', text: 'Ổn rồi! Bản này mình duyệt. 👍' };
      const r = String(e.routing || '').toLowerCase();
      const fix = (e.specific_fixes && e.specific_fixes[0]) || (e.visual_fixes && e.visual_fixes[0]) || '';
      const reason = (e.rejection_reasons && e.rejection_reasons[0]) || '';
      let lead;
      if (r.includes('visual')) lead = 'Lời thoại ổn rồi, nhưng phần hình ảnh cần chỉnh.';
      else if (r.includes('writer') || r.includes('rewrite')) lead = 'Lời thoại chưa đủ cuốn, viết lại giúp mình nhé.';
      else lead = 'Chưa đạt — mình cần bạn chỉnh thêm.';
      const tail = fix ? (' Cụ thể: ' + fix) : (reason ? (' Vấn đề: ' + reason) : '');
      return { who: 'critic', text: lead + tail };
    }
    if (t === 'converged') return { who: 'critic', text: 'Xoay mãi cũng không khá hơn — mình chốt bản này.' };
    if (t === 'loop_lock') return { who: 'critic', text: 'Hai đứa giậm chân tại chỗ rồi, dừng ở đây thôi.' };
    if (t === 'visual_director') return { who: 'critic', text: 'Khoá lời thoại lại, chỉ sửa phần hình ảnh thôi.' };
    if (t === 'tournament_start') return { who: 'critic', text: 'Cho các bản đấu loại trực tiếp, chọn bản hay nhất.' };
    if (t === 'tournament_done') return { who: 'critic', text: 'Đã có bản thắng cuộc!' };
    if (t === 'evolution_start') return { who: 'writer', text: 'Mình ghép tinh hoa mấy bản tốt nhất thành bản cuối.' };
    if (t === 'evolution_done') return { who: 'writer', text: 'Bản cuối hoàn thiện xong! 🎬' };
    if (t === 'evolution_fail') return { who: 'writer', text: 'Ghép bản bị lỗi, mình dùng bản tốt nhất hiện có.' };
    return null;
  }

  // ── Human narration ───────────────────────────────────────────────────────
  // Bubbles must read like a real co-worker telling you what THEY are doing —
  // not a machine progress line. So we never put "[15%] Sampling ~40 channels"
  // in a bubble; the % lives only in the right panel. Instead each agent in a
  // phase gets a role-specific sentence, and as the pipeline `stage` advances
  // ("Searching YouTube" → "Clustering with DeepSeek") their line changes too —
  // so different agents say different things and the office feels alive.
  const ROLE_VERB = {
    scanner: 'Đang quét nguồn dữ liệu',
    research: 'Đang nghiên cứu chủ đề',
    scorer: 'Đang chấm điểm & xếp hạng',
    writer: 'Đang viết kịch bản',
    critic: 'Đang phản biện kịch bản',
    visual: 'Đang lên ý tưởng hình ảnh',
    media: 'Đang dựng & render video',
    quality: 'Đang kiểm tra chất lượng',
    compliance: 'Đang rà soát chính sách',
    upload: 'Đang tải video lên',
    analytics: 'Đang phân tích số liệu',
    abtest: 'Đang chạy thử nghiệm A/B',
  };
  // phase → ordered rows; first row whose keyword appears in (stage+detail) wins.
  // kw:[''] = catch-all (always matches) — keep it last in a phase's list.
  const NARRATION = {
    niche_scan: [
      { kw: ['seed', 'loading', 'reading', 't0', 'query'], by: {
          scanner: 'Đang nạp bộ từ khoá hạt giống T0–T5',
          research: 'Chuẩn bị danh sách chủ đề để đi quét',
          scorer: 'Chờ dữ liệu kênh đổ về để chấm điểm' } },
      { kw: ['search', 'sampling', 'youtube'], by: {
          scanner: 'Đang quét YouTube — lấy mẫu ~40 kênh đối thủ',
          research: 'Đang gom kênh từ 20 truy vấn hạt giống',
          scorer: 'Đang lọc bỏ các kênh trùng lặp' } },
      { kw: ['cluster', 'deepseek', 'analys'], by: {
          scanner: 'Quét xong, bàn giao dữ liệu cho phân tích',
          research: 'Đang gom nhóm các kênh theo chủ đề (DeepSeek)',
          scorer: 'Đang tính điểm tiềm năng cho từng cụm niche' } },
      { kw: ['saving', 'writing', 'result', 'niche'], by: {
          scanner: 'Đã hoàn tất quét nguồn',
          research: 'Đang chốt danh sách niche tiềm năng',
          scorer: 'Đang ghi điểm và lưu kết quả vào kho' } },
    ],
    discovery: [
      { kw: ['loading', 'profile', 'resolving'], by: {
          research: 'Đang đọc hồ sơ kênh và cấu hình niche',
          scorer: 'Chờ chủ đề về để xếp hạng',
          scanner: 'Sẵn sàng quét nguồn xu hướng' } },
      { kw: ['discovery scan', 'reddit', 'news', 'trends', 'podcast', 'parallel'], by: {
          research: 'Đang quét YouTube, Reddit, News, Trends, Podcast cùng lúc',
          scanner: 'Đang thu thập chủ đề nóng từ mạng xã hội',
          scorer: 'Đang gom các chủ đề thô về một chỗ' } },
      { kw: ['architect', 'ranking', 'top'], by: {
          research: 'Đã thu thập xong, chuyển sang xếp hạng',
          scorer: 'Đang chọn top-5 chủ đề đáng làm nhất',
          scanner: 'Hỗ trợ đối chiếu dữ liệu kênh' } },
      { kw: ['writing', 'event', 'persist'], by: {
          research: 'Đang chốt chủ đề thắng cuộc',
          scorer: 'Đang lưu kết quả xếp hạng',
          scanner: 'Hoàn tất công đoạn khám phá' } },
    ],
    image_generation: [
      { kw: ['loading', 'script json'], by: {
          visual: 'Đang đọc kịch bản để chia cảnh dựng hình',
          media: 'Chuẩn bị công cụ tạo ảnh' } },
      { kw: ['generating', 'imagen', 'gemini', 'image'], by: {
          visual: 'Đang phác ý tưởng & viết prompt cho từng cảnh',
          media: 'Đang tạo ảnh minh hoạ theo storyboard' } },
      { kw: ['saving', 'result'], by: {
          visual: 'Đã chốt hình cho các cảnh',
          media: 'Đang lưu ảnh vào thư mục dự án' } },
      { kw: [''], by: {
          visual: 'Đang lên ý tưởng hình ảnh cho từng cảnh',
          media: 'Đang tạo ảnh minh hoạ theo storyboard' } },
    ],
    render: [
      { kw: ['concat', 'stitch', 'merge', 'ghép'], by: {
          media: 'Đang ghép các cảnh thành video hoàn chỉnh',
          quality: 'Đang chờ bản dựng để kiểm tra' } },
      { kw: ['music', 'audio', 'mix', 'nhạc'], by: {
          media: 'Đang lồng nhạc nền và thuyết minh',
          quality: 'Đang nghe lại audio xem có lỗi không' } },
      { kw: ['qa', 'check', 'quality'], by: {
          media: 'Đã render xong, đợi kiểm định',
          quality: 'Đang soát lỗi hình ảnh & âm thanh cuối cùng' } },
      { kw: [''], by: {
          media: 'Đang render video — dựng từng cảnh',
          quality: 'Đang theo dõi tiến độ render' } },
    ],
  };
  function humanize(phase, stage, detail, agentId) {
    // Match on the clean `stage` only — detail strings can contain misleading
    // keywords (e.g. "...across 20 seed queries" would wrongly trigger the
    // "Loading seed queries" row). stage is the authoritative current action.
    const hay = String(stage || '').toLowerCase();
    const table = NARRATION[phase];
    if (table) {
      for (const row of table) {
        if (row.kw.some(k => k === '' || hay.includes(k))) {
          const line = row.by[agentId];
          if (line) return line;
        }
      }
    }
    return ROLE_VERB[agentId] || (stage ? ('Đang xử lý: ' + stage) : 'Đang làm việc');
  }

  // Niche-scan narration — turns a granular scanner/discoverer live_log event into
  // a realtime line, with WHO (event carries agent: scanner/research/scorer). Shows
  // exactly what each agent does right now: which query, which channel, which niche
  // scored — plus a measured ETA on sampling. Returns {who, text} or null.
  function narrateNiche(e) {
    const t = e.type, who = e.agent;
    if (t === 'niche_search')
      return { who, text: `Quét “${e.query}” → ${e.found} kênh (tổng ${e.total_channels})` };
    if (t === 'niche_stats')
      return { who, text: `Lấy thống kê ${e.fetched} kênh` };
    if (t === 'niche_filter')
      return { who, text: `Lọc còn ${e.candidates}/${e.from_total} kênh tiềm năng` };
    if (t === 'niche_sample') {
      const eta = e.eta_s ? ` · còn ~${e.eta_s}s` : '';
      const last = e.last_channel ? ` · ${e.last_channel}` : '';
      return { who, text: `Phân tích kênh ${e.done}/${e.total}${last}${eta}` };
    }
    if (t === 'niche_cluster')
      return { who, text: `Gom nhóm ${e.channels} kênh → đi tìm ngách` };
    if (t === 'niche_scored')
      return { who, text: `Chấm “${e.name}”: demand ${e.demand} · gap ${e.gap} · RPM $${e.est_rpm} → ${e.total}đ` };
    return null;
  }

  // Returns { agentId: {stage, detail, pct, phase} } for every agent whose phase
  // is active, so the office can narrate what each working agent is doing.
  function activeFromPipeline() {
    const pl = window.OMNI_PIPELINE || {};
    const jobs = pl.active_jobs || [];
    const a = {};
    jobs.forEach(j => {
      const phase = String(j.phase || j.stage || '').toLowerCase();
      const stage = String(j.stage || '').trim();
      const detail = String(j.detail || j.stage || j.current_stage || '').trim();
      const pct = (j.progress_pct != null) ? j.progress_pct : null;
      (PHASE_AGENTS[phase] || []).forEach(id => { a[id] = { stage, detail, pct, phase }; });
    });
    return a;
  }

  function PixelOffice() {
    const ref = useRef(null);
    const postRef = useRef(null);

    const [selectedChannel, setSelectedChannel] = useState(window.CHANNELS?.[0]?.id || 'ch_fin01');
    const [selectedModel, setSelectedModel] = useState('deepseek');
    const [chatInput, setChatInput] = useState('');

    const list = (typeof AGENTS !== 'undefined') ? AGENTS : [];
    const idxOf = (agentId) => list.findIndex(a => a.id === agentId);

    const effectiveChannelId = () => {
      const channels = window.CHANNELS || [];
      if (channels.some(c => c.id === selectedChannel)) return selectedChannel;
      return channels[0]?.id || selectedChannel;
    };

    const triggerAction = (type) => {
      if (!window.OmniActions) {
        alert("OmniActions không khả dụng — kiểm tra API backend.");
        return;
      }
      const channelId = effectiveChannelId();
      if (channelId !== selectedChannel) setSelectedChannel(channelId);
      if (type === 'phase1') {
        window.OmniActions.runChannel(channelId);
        alert(`Kích hoạt Phase 1 (Tìm Topic) cho kênh: ${selectedChannel}`);
      } else if (type === 'phase2') {
        window.OmniActions.runScript(channelId);
        alert(`Kích hoạt Phase 2 (Viết Kịch bản) cho kênh: ${selectedChannel}`);
      } else if (type === 'full') {
        window.OmniActions.runChannel(channelId);
        alert(`Kích hoạt Full Run cho kênh: ${selectedChannel}`);
      } else if (type === 'auto') {
        window.OmniActions.autoRun(channelId, false);
        alert(`Kích hoạt Auto-Pilot cho kênh: ${selectedChannel}`);
      }
    };

    const handleSendChat = () => {
      if (!chatInput.trim()) return;
      const text = chatInput.trim();
      setChatInput('');

      // Add to Feed list
      const timeStr = new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
      const newEvent = {
        id: Date.now(),
        time: timeStr,
        dot: 'blue',
        title: 'Operator gửi lệnh',
        desc: text,
        token: 'Gửi trực tiếp',
        live: false
      };
      if (window.FEED) {
        window.FEED = [newEvent, ...window.FEED];
      }
      if (window.__omniRerender) window.__omniRerender();

      // Send to Iframe
      const lowercaseText = text.toLowerCase();
      let targetedAgent = null;
      if (lowercaseText.includes('writer') || lowercaseText.includes('viết') || lowercaseText.includes('kịch bản')) {
        targetedAgent = 'writer';
      } else if (lowercaseText.includes('critic') || lowercaseText.includes('phản biện') || lowercaseText.includes('chấm điểm')) {
        targetedAgent = 'critic';
      } else if (lowercaseText.includes('research') || lowercaseText.includes('tìm') || lowercaseText.includes('niche')) {
        targetedAgent = 'research';
      } else if (lowercaseText.includes('visual') || lowercaseText.includes('ảnh') || lowercaseText.includes('director')) {
        targetedAgent = 'visual';
      } else if (lowercaseText.includes('media') || lowercaseText.includes('render') || lowercaseText.includes('video')) {
        targetedAgent = 'media';
      } else if (lowercaseText.includes('compliance') || lowercaseText.includes('luật') || lowercaseText.includes('chính sách')) {
        targetedAgent = 'compliance';
      } else if (lowercaseText.includes('upload') || lowercaseText.includes('đăng')) {
        targetedAgent = 'upload';
      }

      const post = postRef.current;
      if (post) {
        if (targetedAgent) {
          const idx = idxOf(targetedAgent);
          if (idx >= 0) {
            const tool = TOOL_BY_AGENT[targetedAgent] || 'Edit';
            post({ type: 'agentToolStart', id: idx, toolId: 'chat-' + idx, status: tool, toolName: tool, permissionActive: false });
            post({ type: 'agentSay', id: idx, text: `Nhận lệnh: "${text.slice(0, 80)}"` });
            
            // Auto trigger backend actions
            if (targetedAgent === 'writer' && (lowercaseText.includes('viết') || lowercaseText.includes('kịch bản'))) {
              if (window.OmniActions && window.OmniActions.runScript) {
                window.OmniActions.runScript(effectiveChannelId());
              }
            }
            if (targetedAgent === 'research' && (lowercaseText.includes('niche') || lowercaseText.includes('quét'))) {
              if (window.OmniActions && window.OmniActions.vaultHealthCheck) {
                window.OmniActions.vaultHealthCheck();
              }
            }
          }
        } else {
          const randomAgents = ['writer', 'critic', 'research', 'media'];
          const agentName = randomAgents[Math.floor(Math.random() * randomAgents.length)];
          const idx = idxOf(agentName);
          if (idx >= 0) {
            post({ type: 'agentSay', id: idx, text: `Đã hiểu lệnh: "${text.slice(0, 80)}"` });
          }
        }
      }
    };

    useEffect(() => {
      const iframe = ref.current;
      if (!iframe) return;
      let pollIv = null, spawnT = null, debateIv = null, nicheIv = null;

      const post = (msg) => {
        try { iframe.contentWindow.postMessage(msg, '*'); } catch (e) {}
      };
      postRef.current = post;

      // Hide the editor chrome (+Agent / Layout / Settings / zoom / version popups)
      // and lock the view (no wheel-zoom, no drag-pan) so the office is a fixed,
      // read-only display. Re-applied via MutationObserver since the SPA re-renders.
      const lockAndHide = (doc) => {
        try {
          const st = doc.createElement('style');
          st.textContent = `
            .top-8.left-8, .bottom-10.left-10,
            .bottom-8.right-8, .bottom-10.right-10, .top-10.right-10 { display:none !important; }
          `;
          doc.head.appendChild(st);
          const climbHide = (el) => {
            let n = el;
            for (let i = 0; i < 5 && n && n !== doc.body; i++) {
              const pos = doc.defaultView.getComputedStyle(n).position;
              if (pos === 'absolute' || pos === 'fixed') {
                n.style.setProperty('display', 'none', 'important'); return;
              }
              n = n.parentElement;
            }
            el.style.setProperty('display', 'none', 'important');
          };
          const hide = () => {
            doc.querySelectorAll('button, a').forEach(el => {
              const t = (el.textContent || '').trim().toLowerCase();
              if (t === 'layout' || t === 'settings' || t === '+' || t === '−' || t === '-'
                  || t.startsWith('+ agent') || t === 'agent') {
                el.style.setProperty('display', 'none', 'important');
              } else if (t === "see what's new" || t.indexOf('see what') === 0) {
                climbHide(el);
              }
            });
            doc.querySelectorAll('div, span, p').forEach(el => {
              if (el.children.length === 0) {
                const t = (el.textContent || '').trim();
                if (/^v\d+\.\d+/i.test(t) || t.indexOf('Updated to') === 0) climbHide(el);
              }
            });
          };
          hide();
          const mo = new MutationObserver(hide);
          mo.observe(doc.body, { childList: true, subtree: true });
          doc.addEventListener('wheel', (e) => e.preventDefault(), { capture: true, passive: false });
          doc.addEventListener('mousedown', (e) => e.stopPropagation(), { capture: true });
          doc.addEventListener('contextmenu', (e) => e.preventDefault(), { capture: true });
        } catch (e) {}
      };

      const lastStatus = {};
      const lastSay = {};
      let refreshDebateHandler = null;
      let refreshNicheHandler = null;
      const onLoad = () => {
        try { if (iframe.contentDocument) lockAndHide(iframe.contentDocument); } catch (e) {}
        spawnT = setTimeout(() => {
          list.forEach((a, i) => post({ type: 'agentCreated', id: i, folderName: a.name, seatId: 'seat-' + a.id }));
        }, 1800);

        pollIv = setInterval(() => {
          // Idempotent: re-ensure all agents are spawned in the iframe (addAgent returns immediately if they already exist).
          // This self-heals from the race condition where layoutLoaded rebuilds the map and clears characters after spawnT.
          list.forEach((a, i) => post({ type: 'agentCreated', id: i, folderName: a.name, seatId: 'seat-' + a.id }));

          let act = {};
          try { act = activeFromPipeline(); } catch (e) {}
          list.forEach((a, i) => {
            const info = act[a.id];
            const s = info ? 'active' : 'idle';
            if (lastStatus[i] !== s) {
              lastStatus[i] = s;
              if (s === 'active') {
                const tool = TOOL_BY_AGENT[a.id] || 'Edit';
                post({ type: 'agentToolStart', id: i, toolId: 'omni-' + i, status: tool, toolName: tool, permissionActive: false });
              } else {
                post({ type: 'agentToolsClear', id: i });
                post({ type: 'agentStatus', id: i, status: 'idle' });
              }
            }
            // Human-narration bubble for coarse-stage phases (discovery/image/
            // render). Script phase uses the debate feed; niche_scan uses its own
            // granular live feed below — both excluded here to avoid double bubbles.
            if (info && !String(info.phase).includes('script') && info.phase !== 'niche_scan') {
              const txt = humanize(info.phase, info.stage, info.detail, a.id);
              if (txt && lastSay[i] !== txt) { lastSay[i] = txt; post({ type: 'agentSay', id: i, text: txt.slice(0, 110) }); }
            }
          });
        }, 3000);

        let lastTs = '';
        const refreshDebate = () => {
          const pl = window.OMNI_PIPELINE || {};
          const job = (pl.active_jobs || []).find(j => String(j.phase || j.stage || '').includes('script'));
          if (!job) return;
          fetch('/api/run/' + job.channel_id + '/log').then(r => r.json()).then(d => {
            const evs = d.events || [];
            window.OMNI_DEBATE = evs;
            const fresh = evs.filter(e => (e.ts || '') > lastTs);
            if (!fresh.length) return;
            lastTs = evs[evs.length - 1].ts || lastTs;
            fresh.forEach(e => {
              const line = narrateDebate(e); if (!line) return;
              const idx = idxOf(line.who); if (idx < 0) return;
              // critic reads the draft, writer types the rewrite — pose matches role.
              const tool = line.who === 'critic' ? 'Read' : 'Write';
              post({ type: 'agentToolStart', id: idx, toolId: 'dbt-' + idx, status: tool, toolName: tool, permissionActive: false });
              post({ type: 'agentSay', id: idx, text: String(line.text).slice(0, 140) });
            });
            if (window.__omniRerender) window.__omniRerender();
          }).catch(() => {});
        };
        refreshDebateHandler = refreshDebate;
        window.addEventListener('omni:job-event', refreshDebateHandler);
        debateIv = setInterval(refreshDebate, 15000);

        // Niche-scan live feed — granular scanner/discoverer events drive realtime
        // bubbles (per query, per channel sampled, per niche scored). Polls fast
        // (2s) so the office reflects what's happening almost instantly.
        let lastNTs = '';
        const refreshNiche = () => {
          const pl = window.OMNI_PIPELINE || {};
          const job = (pl.active_jobs || []).find(j => String(j.phase || j.stage || '').toLowerCase() === 'niche_scan');
          if (!job) return;
          const cid = job.channel_id || '__niche_discovery__';
          fetch('/api/run/' + cid + '/log').then(r => r.json()).then(d => {
            const evs = d.events || [];
            window.OMNI_NICHE = evs;
            const fresh = evs.filter(e => (e.ts || '') > lastNTs);
            if (!fresh.length) return;
            lastNTs = evs[evs.length - 1].ts || lastNTs;
            fresh.forEach(e => {
              const line = narrateNiche(e); if (!line || !line.who) return;
              const idx = idxOf(line.who); if (idx < 0) return;
              const tool = TOOL_BY_AGENT[line.who] || 'WebSearch';
              post({ type: 'agentToolStart', id: idx, toolId: 'nch-' + idx, status: tool, toolName: tool, permissionActive: false });
              post({ type: 'agentSay', id: idx, text: String(line.text).slice(0, 140) });
            });
            if (window.__omniRerender) window.__omniRerender();
          }).catch(() => {});
        };
        refreshNicheHandler = refreshNiche;
        window.addEventListener('omni:job-event', refreshNicheHandler);
        nicheIv = setInterval(refreshNiche, 15000);
      };

      iframe.addEventListener('load', onLoad);
      if (iframe.contentWindow && iframe.contentDocument && iframe.contentDocument.readyState === 'complete') {
        onLoad();
      }
      return () => {
        iframe.removeEventListener('load', onLoad);
        if (pollIv) clearInterval(pollIv);
        if (debateIv) clearInterval(debateIv);
        if (nicheIv) clearInterval(nicheIv);
        if (refreshDebateHandler) window.removeEventListener('omni:job-event', refreshDebateHandler);
        if (refreshNicheHandler) window.removeEventListener('omni:job-event', refreshNicheHandler);
        if (spawnT) clearTimeout(spawnT);
      };
    }, []);

    return (
      <div style={{ display: 'flex', gap: '16px', flex: 1, minWidth: 0, height: 'calc(100vh - 120px)' }}>
        {/* Left Control Panel — ChatDev style */}
        <div style={{ width: '260px', display: 'flex', flexDirection: 'column', gap: '12px', flexShrink: 0 }}>
          <div className="card" style={{ padding: '14px' }}>
            <div className="card-title" style={{ fontSize: '13.5px', marginBottom: '8px' }}>🤖 Chọn Model & Kênh</div>
            <div style={{ marginBottom: '10px' }}>
              <label style={{ fontSize: '11px', color: 'var(--text3)', display: 'block', marginBottom: '4px' }}>Model Phản Biện</label>
              <select
                className="field"
                style={{ width: '100%', padding: '6px', fontSize: '12px', background: 'var(--surface2)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: '4px' }}
                value={selectedModel}
                onChange={e => setSelectedModel(e.target.value)}
              >
                <option value="deepseek">DeepSeek Pro</option>
                <option value="claude">Claude 3.5 Sonnet</option>
                <option value="gemini">Gemini 1.5 Pro</option>
                <option value="gpt4">GPT-4o</option>
              </select>
            </div>
            <div>
              <label style={{ fontSize: '11px', color: 'var(--text3)', display: 'block', marginBottom: '4px' }}>Kênh đích</label>
              <select
                className="field"
                style={{ width: '100%', padding: '6px', fontSize: '12px', background: 'var(--surface2)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: '4px' }}
                value={selectedChannel}
                onChange={e => setSelectedChannel(e.target.value)}
              >
                {(window.CHANNELS || []).map(c => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="card" style={{ padding: '14px', flex: 1, display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div className="card-title" style={{ fontSize: '13.5px', marginBottom: '4px' }}>⚡ Kích hoạt Nhanh</div>
            <button className="btn btn-ghost sm" style={{ width: '100%', justifyContent: 'flex-start' }} onClick={() => triggerAction('phase1')}>
              🔍 Phase 1: Tìm Topic
            </button>
            <button className="btn btn-primary sm" style={{ width: '100%', justifyContent: 'flex-start' }} onClick={() => triggerAction('phase2')}>
              ✍️ Phase 2: Kịch bản
            </button>
            <button className="btn btn-green sm" style={{ width: '100%', justifyContent: 'flex-start' }} onClick={() => triggerAction('full')}>
              🚀 Full Run Pipeline
            </button>
            <button className="btn btn-ghost sm" style={{ width: '100%', justifyContent: 'flex-start', color: 'var(--purple)', borderColor: 'rgba(168,85,247,.4)' }} onClick={() => triggerAction('auto')}>
              🤖 Auto-Pilot Kênh
            </button>

            <div style={{ marginTop: 'auto', borderTop: '1px solid var(--border)', paddingTop: '10px' }}>
              <div style={{ fontSize: '11px', color: 'var(--text3)' }}>Trạng thái Kênh</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '4px' }}>
                <span className="dot live" style={{ width: '8px', height: '8px', background: 'var(--green)', borderRadius: '50%' }}></span>
                <span style={{ fontSize: '12px', fontWeight: 'bold', color: 'var(--green)' }}>Sẵn sàng nhận lệnh</span>
              </div>
            </div>
          </div>
        </div>

        {/* Center Area — Map + Input */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '12px', minWidth: 0 }}>
          <div className="card" style={{ padding: '0px', flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: '#11182a', borderRadius: '12px', border: '1px solid var(--border)' }}>
            <iframe ref={ref} src="/office_app/index.html" title="Pixel Office" scrolling="no"
              style={{ width: '100%', flex: 1, border: 0, display: 'block', background: '#11182a' }} />
          </div>

          {/* Bottom Chat Input Bar — ChatDev Style */}
          <div className="card" style={{ padding: '10px 14px', display: 'flex', gap: '10px', alignItems: 'center', border: '1px solid var(--border)' }}>
            <span style={{ fontSize: '18px' }}>💬</span>
            <input
              type="text"
              className="field"
              placeholder="Giao việc cho Agent (ví dụ: 'Writer, viết bài về Bitcoin', 'Tìm niche tài chính mới')..."
              style={{ flex: 1, height: '36px', padding: '0 12px', background: 'var(--surface2)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: '6px', fontSize: '13px' }}
              value={chatInput}
              onChange={e => setChatInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleSendChat(); }}
            />
            <button className="btn btn-primary" style={{ height: '36px' }} onClick={handleSendChat}>
              Gửi lệnh ⚡
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Override the canvas implementation — the embedded real webview is authoritative.
  window.PixelOffice = PixelOffice;
})();
