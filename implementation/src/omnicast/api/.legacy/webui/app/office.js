// ============================================
// OmniCast Engine — Pipeline Office (signature, isometric)
// ============================================
const { useState, useEffect, useRef, useCallback } = React;

function AgentSprite({ color, species, asset }) {
  return (
    <div className="agent">
      {window.renderCharacter(species, color, 'idle', 'up')}
    </div>
  );
}

function Workstation({ agent, active, away, errored, statusText, drains, deskRef }) {
  const cls = errored ? 'error' : active ? 'active' : 'idle';
  return (
    <div className={`ws ${cls} c-${agent.color}`}>
      <div className="ws-label">
        <div className="ws-name">{agent.name}</div>
        <div className="ws-status">{errored ? '⚠ Gặp lỗi' : away ? 'Đang giao tài liệu…' : active ? statusText : 'Đang rảnh'}</div>
      </div>
      <div className="desk-unit" ref={deskRef}>
        {drains.map(d => (
          <span key={d.key} className="token-drain"
            style={{ left: `${48 + d.off}%`, color: d.color }}>-{d.amt} 🪙</span>
        ))}
        <div className="desk-shadow"></div>
        <div className="monitor">{active ? agent.icon : ''}</div>
        <div className="desk-top"></div>
        <div className="desk-edge"></div>
        <div className="desk-leg l"></div>
        <div className="desk-leg r"></div>
        {!away && <AgentSprite color={agent.color} species={agent.species} asset={agent.asset} />}
        <div className="chair">
          <div className="back"></div>
          <div className="seat"></div>
          <div className="pole"></div>
          <div className="base"></div>
        </div>
      </div>
    </div>
  );
}

// Map a real pipeline phase → which office agents light up.
const PHASE_AGENTS = {
  discovery: ['research', 'scorer', 'scanner'],
  writing: ['writer'], script_generation: ['writer'], scriptgen: ['writer'],
  critic: ['critic'], image_generation: ['media', 'visual'], rendering: ['media'],
  upload: ['upload'], analytics: ['analytics'],
};
function _activeFromPipeline() {
  const pl = window.OMNI_PIPELINE || {};
  const jobs = pl.active_jobs || [];
  const a = {};
  jobs.forEach(j => {
    const phase = String(j.phase || j.stage || '').toLowerCase();
    (PHASE_AGENTS[phase] || []).forEach(id => { a[id] = true; });
  });
  return a;  // empty object = all idle (honest when nothing running)
}
// Recent failed events → which agents show the error state (last ~10 min).
function _erroredFromPipeline() {
  const e = {};
  const errs = window.OMNI_ERRORS || [];
  const now = Date.now();
  errs.slice(0, 8).forEach(er => {
    const phase = String(er.phase || er.stage || '').toLowerCase();
    const ts = er.ts ? Date.parse(er.ts) : now;
    if (now - ts < 600000) (PHASE_AGENTS[phase] || []).forEach(id => { e[id] = true; });
  });
  return e;
}

function PipelineOffice({ feed, setFeed }) {
  const [active, setActive] = useState(_activeFromPipeline());
  const [errored, setErrored] = useState(_erroredFromPipeline());
  // Re-derive active agents from the real pipeline every 3s.
  useEffect(() => {
    const iv = setInterval(() => {
      setActive(_activeFromPipeline());
      setErrored(_erroredFromPipeline());
    }, 3000);
    return () => clearInterval(iv);
  }, []);
  const [statusMap] = useState({
    research: 'Đang tổng hợp nguồn', writer: 'Đang viết kịch bản',
    critic: 'Đang chấm điểm', visual: 'Đang tạo prompt ảnh',
    media: 'Đang render', scorer: 'Đang chấm chủ đề',
    scanner: 'Đang quét đối thủ', compliance: 'Đang kiểm tra',
    quality: 'Đang QC', upload: 'Đang tải lên', abtest: 'Đang test A/B', analytics: 'Đang phân tích',
  });
  const [drains, setDrains] = useState({});
  const [courier, setCourier] = useState(null);
  const [away, setAway] = useState(null);
  const [binShake, setBinShake] = useState(false);
  const deskRefs = useRef({});
  const stageRef = useRef(null);
  const drainSeq = useRef(0);

  // token drain loop
  useEffect(() => {
    const iv = setInterval(() => {
      setDrains(prev => {
        const next = { ...prev };
        Object.keys(active).forEach(id => {
          if (!active[id] || Math.random() > 0.5) return;
          const k = ++drainSeq.current;
          const amt = [1, 1, 2, 3, 5][Math.floor(Math.random() * 5)];
          const color = amt >= 3 ? '#ef4444' : '#f59e0b';
          const off = (Math.random() * 26 - 13);
          next[id] = [...(next[id] || []), { key: k, amt, off, color }];
          setTimeout(() => setDrains(p => ({ ...p, [id]: (p[id] || []).filter(d => d.key !== k) })), 1500);
        });
        return next;
      });
    }, 750);
    return () => clearInterval(iv);
  }, [active]);

  // handoff: agent stands up, carries the document, then walks back and sits
  const runHandoff = useCallback((fromId, toId, reject) => {
    const stage = stageRef.current;
    const fromEl = deskRefs.current[fromId];
    const toEl = deskRefs.current[reject ? 'bin' : toId];
    if (!stage || !fromEl || !toEl) return;
    const g = stage.getBoundingClientRect();
    const f = fromEl.getBoundingClientRect();
    const t = toEl.getBoundingClientRect();
    const posOf = (r) => ({
      left: r.left - g.left + r.width / 2 - 22 + stage.scrollLeft,
      top: r.top - g.top + 16 + stage.scrollTop,
    });
    const start = posOf(f);
    const end = posOf(t);
    const fromAgent = AGENTS.find(a => a.id === fromId);
    const col = AGENT_COLOR[fromAgent.color];

    // Determine L-shape midpoints
    const midForward = { left: end.left, top: start.top };
    const midBackward = { left: start.left, top: end.top };

    // Calculate directions for all segments upfront to prevent rotation glitches
    let dir1 = 'right';
    let dir2 = 'down';
    if (Math.abs(end.left - start.left) > 5 && Math.abs(end.top - start.top) > 5) {
      // Two-segment L-path (different row and col)
      dir1 = end.left > start.left ? 'right' : 'left';
      dir2 = end.top > start.top ? 'down' : 'up';
    } else if (Math.abs(end.left - start.left) > 5) {
      // Purely horizontal walk
      dir1 = end.left > start.left ? 'right' : 'left';
      dir2 = dir1;
    } else {
      // Purely vertical walk
      dir1 = end.top > start.top ? 'down' : 'up';
      dir2 = dir1;
    }

    let dir3 = 'left';
    let dir4 = 'up';
    if (Math.abs(start.left - end.left) > 5 && Math.abs(start.top - end.top) > 5) {
      // Return path: horizontal first then vertical
      dir3 = start.left > end.left ? 'right' : 'left';
      dir4 = start.top > end.top ? 'down' : 'up';
    } else if (Math.abs(start.left - end.left) > 5) {
      // Purely horizontal return
      dir3 = start.left > end.left ? 'right' : 'left';
      dir4 = dir3;
    } else {
      // Purely vertical return
      dir3 = start.top > end.top ? 'down' : 'up';
      dir4 = dir3;
    }

    // 1. Agent stands up — chair becomes empty
    setAway(fromId);
    
    // Spawn Courier at start looking in Segment 1 direction
    setCourier({
      left: start.left,
      top: start.top,
      doc: reject ? '🗑️' : '📄',
      color: fromAgent.color, // pass role color string
      species: fromAgent.species,
      carrying: true,
      direction: dir1,
      action: 'walk'
    });

    // 2. Walk to Midpoint (Starts moving horizontally, facing dir1)
    setTimeout(() => {
      setCourier(c => c ? { ...c, left: midForward.left, top: midForward.top } : c);
    }, 50);

    // 3. Walk to End (Destination) (Rotates to face dir2 for vertical leg)
    setTimeout(() => {
      setCourier(c => c ? { ...c, left: end.left, top: end.top, direction: dir2 } : c);
    }, 1250);

    // 4. Deliver document
    setTimeout(() => {
      if (reject) {
        setBinShake(true);
        setTimeout(() => setBinShake(false), 450);
      } else {
        setActive(a => ({ ...a, [toId]: true }));
      }
      
      // Face dir3 for return path Segment 1
      setCourier(c => c ? { ...c, carrying: false, direction: dir3 } : c);
    }, 2450);

    // 5. Return to Midpoint (Starts moving back, facing dir3)
    setTimeout(() => {
      setCourier(c => c ? { ...c, left: midBackward.left, top: midBackward.top } : c);
    }, 2550);

    // 6. Return to Start Desk (Rotates to face dir4 for vertical return leg)
    setTimeout(() => {
      setCourier(c => c ? { ...c, left: start.left, top: start.top, direction: dir4 } : c);
    }, 3750);

    // 7. Sit down
    setTimeout(() => {
      setCourier(null);
      setAway(null);
    }, 4950);
  }, []);

  useEffect(() => {
    let step = 0;
    const handoffs = [
      { from: 'research', to: 'writer', reject: false, label: 'Research → Writer: bàn giao tài liệu' },
      { from: 'writer', to: 'critic', reject: false, label: 'Writer → Critic: gửi bản nháp' },
      { from: 'critic', to: 'visual', reject: false, label: 'Critic duyệt → Visual Director' },
      { from: 'critic', to: 'bin', reject: true, label: 'Critic từ chối bản nháp (score 45)' },
      { from: 'visual', to: 'media', reject: false, label: 'Visual → Media Engineer: prompt ảnh' },
    ];
    const iv = setInterval(() => {
      const h = handoffs[step % handoffs.length];
      runHandoff(h.from, h.to, h.reject);
      setFeed(prev => [{
        id: Date.now(), time: new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' }),
        dot: h.reject ? 'red' : 'blue', title: h.label, desc: h.reject ? 'Quay lại Writer' : 'Chuyển giao pipeline',
        token: h.reject ? 'Tốn: 1,203 tokens' : 'Handoff hoàn tất', live: false,
      }, ...prev].slice(0, 8));
      step++;
    }, 6500);
    return () => clearInterval(iv);
  }, [runHandoff, setFeed]);

  const toggleAgent = (id) => setActive(a => ({ ...a, [id]: !a[id] }));
  const activeCount = Object.values(active).filter(Boolean).length;

  const wsAt = (row, col) => {
    const a = AGENTS.find(x => x.row === row && x.col === col);
    if (!a) return <div key={`e${row}${col}`}></div>;
    return (
      <div key={a.id} onClick={() => toggleAgent(a.id)} style={{ cursor: 'pointer' }}>
        <Workstation agent={a} active={!!active[a.id]} errored={!!errored[a.id]} away={away === a.id} statusText={statusMap[a.id]}
          drains={drains[a.id] || []} deskRef={el => deskRefs.current[a.id] = el} />
      </div>
    );
  };

  return (
    <div className="office-wrap">
      <div className="office-title">Văn phòng OmniCast — {activeCount} agent đang làm việc</div>
      <div className="office-legend">
        <div className="leg-item"><span className="leg-dot" style={{ background: AGENT_COLOR.green }}></span>Nghiên cứu</div>
        <div className="leg-item"><span className="leg-dot" style={{ background: AGENT_COLOR.blue }}></span>Writer</div>
        <div className="leg-item"><span className="leg-dot" style={{ background: AGENT_COLOR.red }}></span>Critic</div>
        <div className="leg-item"><span className="leg-dot" style={{ background: AGENT_COLOR.purple }}></span>Visual</div>
        <div className="leg-item"><span className="leg-dot" style={{ background: AGENT_COLOR.amber }}></span>Media</div>
        <div className="leg-item" style={{ color: 'var(--text3)' }}>· Bấm vào bàn để bật/tắt agent</div>
      </div>

      <div className="office-stage" ref={stageRef}>
        <div className="office-floor">
          {/* Left prop column */}
          <div className="deco-col">
            <div className="prop">
              <div className="iso-obj">
                <div className="sh"></div>
                <div className="obj-counter"></div>
                <div className="obj-machine"></div>
                <div className="obj-cup" style={{ bottom: 16, left: 22 }}></div>
                <div className="obj-cup" style={{ bottom: 16, left: 34 }}></div>
              </div>
              <div className="prop-label">Quầy café</div>
            </div>
            <div className="prop">
              <div className="iso-obj">
                <div className="sh"></div>
                <div className="obj-leaf"></div>
                <div className="obj-pot"></div>
              </div>
              <div className="prop-label">Cây xanh</div>
            </div>
            <div className="prop">
              <div className="iso-obj">
                <div className="sh"></div>
                <div className="obj-server"><span className="rk"></span><span className="rk"></span><span className="rk"></span><span className="rk"></span></div>
              </div>
              <div className="prop-label">Server</div>
            </div>
            <div className="prop">
              <div className="iso-obj" ref={el => deskRefs.current['bin'] = el}>
                <div className="sh"></div>
                <div className={`obj-bin ${binShake ? 'bin-shake' : ''}`}></div>
              </div>
              <div className="prop-label">Thùng từ chối</div>
            </div>
          </div>

          {/* Desk grid */}
          <div className="desk-area">
            {wsAt(1, 1)}{wsAt(1, 2)}{wsAt(1, 3)}
            {wsAt(2, 1)}{wsAt(2, 2)}{wsAt(2, 3)}
            {wsAt(3, 1)}{wsAt(3, 2)}{wsAt(3, 3)}
            {wsAt(4, 1)}{wsAt(4, 2)}{wsAt(4, 3)}
          </div>
        </div>

        {courier && (
          <div className="courier" style={{
            left: courier.left,
            top: courier.top,
            transition: 'left 1.2s linear, top 1.2s linear'
          }}>
            {courier.carrying && (
              <div className="doc-card" style={{ borderColor: AGENT_COLOR[courier.color] }}>
                <span className="doc-emoji">{courier.doc}</span>
              </div>
            )}
            <div className="courier-char">
              {window.renderCharacter(courier.species, courier.color, courier.action, courier.direction)}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

window.PipelineOffice = PipelineOffice;
