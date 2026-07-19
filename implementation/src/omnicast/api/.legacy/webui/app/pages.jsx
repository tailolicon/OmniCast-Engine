// ============================================
// OmniCast Engine — Right Panel + Pages
// ============================================
const { useState: uS } = React;

/* ---------- RIGHT PANEL (Office companion) ---------- */
function RightPanel({ feed }) {
  const [openDim, setOpenDim] = uS(-1);  // expanded debate row index (8-dim grid)
  // Real data from the backend (cost aggregated from the pipeline event log).
  const bud = window.OMNI_BUDGET || {};
  const k = (window.OMNI_STATUS || {}).kpis || {};
  const pl = window.OMNI_PIPELINE || {};
  const recent = pl.recent_results || [];
  const cost = +(bud.today_usd ?? k.daily_spend_usd ?? 0);
  const totalCost = +(bud.total_usd ?? cost);
  const costCap = +(bud.daily_cap_usd ?? k.daily_cap_usd ?? 5);
  const costPct = costCap ? Math.min(100, (cost / costCap) * 100) : 0;
  const running = (pl.active_jobs || []).length;
  const done = recent.filter(r => r.status === 'completed').length;
  const failed = recent.filter(r => r.status === 'failed').length;
  // Token total only if the backend actually tracks it; otherwise show events.
  const tokens = bud.tokens_today;
  const realFeed = (window.OMNI_FEED && window.OMNI_FEED.length) ? window.OMNI_FEED : feed;
  return (
    <div className="rpanel">
      <div className="card">
        <div className="card-hd" style={{ marginBottom: 8 }}>
          <div className="card-title" style={{ fontSize: 14 }}>Chi phí hôm nay</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
          <span style={{ fontSize: 24, fontWeight: 800, letterSpacing: '-0.02em' }}>${cost.toFixed(4)}</span>
          <span style={{ fontSize: 12, color: 'var(--text3)' }}>/ ${costCap.toFixed(2)}</span>
        </div>
        <div className="prog"><i className="green" style={{ width: `${Math.max(costPct, 1.5)}%` }}></i></div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 14, alignItems: 'baseline' }}>
          <span style={{ fontSize: 12.5, color: 'var(--text2)', fontWeight: 600 }}>{tokens != null ? 'Token hôm nay' : 'Tổng chi phí'}</span>
          <span style={{ fontSize: 16, fontWeight: 800 }}>{tokens != null ? Number(tokens).toLocaleString() : '$' + totalCost.toFixed(4)}</span>
        </div>
      </div>

      <div className="card">
        <div className="counter-grid">
          <div className="counter-cell"><div className="counter-num text-green">{running}</div><div className="counter-lbl">Đang chạy</div></div>
          <div className="counter-cell"><div className="counter-num" style={{ color: failed ? 'var(--red)' : 'var(--text3)' }}>{failed}</div><div className="counter-lbl">Lỗi</div></div>
          <div className="counter-cell"><div className="counter-num text-blue">{done}</div><div className="counter-lbl">Hoàn thành</div></div>
        </div>
      </div>

      {(() => {
        // Active-job progress (niche scan / discovery / image / render) — shows
        // what each running stage is doing with a live progress bar.
        const jobs = (pl.active_jobs || []).filter(j => j.phase || j.stage);
        if (!jobs.length) return null;
        const PHASE_LBL = {
          niche_scan: '🔭 Quét niche', discovery: '🔍 Tìm chủ đề', script_generation: '<Icon name="file-text" /> Viết kịch bản',
          image_generation: '<Icon name="settings" /> Tạo ảnh', render: '<Icon name="video" /> Render video', policy_scan: '<Icon name="check" /> Kiểm policy',
        };
        return (
          <div className="card">
            <div className="card-hd" style={{ marginBottom: 6 }}><div className="card-title" style={{ fontSize: 14 }}><Icon name="settings" /> Đang xử lý</div></div>
            {jobs.map((j, i) => {
              const ph = String(j.phase || j.stage || '');
              const pct = j.progress_pct != null ? j.progress_pct : null;
              return (
                <div key={i} style={{ padding: '5px 0', borderBottom: i < jobs.length - 1 ? '1px solid var(--border)' : 'none' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, fontWeight: 600 }}>
                    <span>{PHASE_LBL[ph] || ph}</span>{pct != null && <span className="text-blue">{pct}%</span>}
                  </div>
                  {(j.detail || j.stage) && <div style={{ fontSize: 11.5, color: 'var(--text2)', marginTop: 1 }}>{j.detail || j.stage}</div>}
                  {pct != null && <div className="prog" style={{ marginTop: 4 }}><i className="green" style={{ width: Math.max(pct, 2) + '%' }}></i></div>}
                </div>
              );
            })}
          </div>
        );
      })()}

      {(() => {
        // Live debate feed (Writer ↔ Critic ↔ Tournament ↔ Evolution) with model
        // + VO/Prod score breakdown. Populated by office_embed while phase2 runs.
        const dbt = window.OMNI_DEBATE || [];
        if (!dbt.length) return null;
        const ic = { writer_start: '<Icon name="file-text" />', writer_done: '<Icon name="file-text" />', debate_start: '⚔️', thinking: '💭', round: '<Icon name="shield" />', converged: '✓', loop_lock: '🔁', tournament_start: '🏆', tournament_done: '🏆', evolution_start: '🧬', evolution_done: '🧬', evolution_fail: '⚠️', pipeline_done: '<Icon name="video" />' };
        const last = dbt.slice(-14).reverse();
        return (
          <div className="card" style={{ maxHeight: 340, overflowY: 'auto' }}>
            <div className="card-hd" style={{ marginBottom: 6 }}><div className="card-title" style={{ fontSize: 14 }}>⚔️ Phản biện Agent (live)</div></div>
            {last.map((e, i) => {
              const hasDim = e.dimensions && e.dimensions.length;
              return (
              <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid var(--border)', cursor: hasDim ? 'pointer' : 'default' }}
                   onClick={() => hasDim && setOpenDim(openDim === i ? -1 : i)}>
                <div style={{ display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span>{ic[e.type] || '•'}</span>
                  {e.model && <span className="tag" style={{ fontSize: 10 }}>{e.model}</span>}
                  {e.vo_score != null && <span className="tag green" style={{ fontSize: 10 }}>VO {e.vo_score}/70</span>}
                  {e.prod_score != null && <span className="tag amber" style={{ fontSize: 10 }}>Prod {e.prod_score}/30</span>}
                  {e.approved && <span className="tag green" style={{ fontSize: 10 }}><Icon name="check" /></span>}
                  {hasDim && <span style={{ fontSize: 10, color: 'var(--text3)' }}>{openDim === i ? '▾' : '▸'} 8 chiều</span>}
                </div>
                <div style={{ color: 'var(--text2)', marginTop: 2, fontSize: 12 }}>{e.msg}</div>
                {e.routing && e.routing !== 'approved' && <div style={{ color: 'var(--text3)', fontSize: 11, marginTop: 1 }}>→ {e.routing}</div>}
                {hasDim && openDim === i && (
                  <div style={{ marginTop: 6, paddingLeft: 4 }}>
                    {e.dimensions.map((d, k) => {
                      const pct = d.max ? Math.round((d.score / d.max) * 100) : 0;
                      const col = pct >= 90 ? 'var(--green)' : pct >= 60 ? 'var(--amber)' : 'var(--red)';
                      return (
                        <div key={k} style={{ marginBottom: 3 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5, color: 'var(--text2)' }}>
                            <span>{d.name}</span><span>{d.score}/{d.max}</span>
                          </div>
                          <div style={{ height: 4, background: 'var(--border)', borderRadius: 2 }}>
                            <div style={{ height: '100%', width: pct + '%', background: col, borderRadius: 2 }}></div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
              );
            })}
          </div>
        );
      })()}

      <div className="card" style={{ flex: 1 }}>
        <div className="card-hd" style={{ marginBottom: 6 }}>
          <div className="card-title" style={{ fontSize: 14 }}>Hoạt động gần đây</div>
        </div>
        {realFeed.map(f => (
          <div key={f.id} className="feed-item">
            <span className="feed-dot" style={{ background: AGENT_COLOR[f.dot] || 'var(--blue)' }}></span>
            <div className="feed-body">
              <div className="feed-top">
                <span className="feed-title">{f.title}</span>
                <span className="feed-time">{f.time}</span>
              </div>
              <div className="feed-desc">{f.desc}</div>
              <div className="feed-token"><Icon name="dollar-sign" /> {f.token}{f.live && <span className="tag green" style={{ marginLeft: 6 }}>Đang chạy</span>}</div>
            </div>
          </div>
        ))}
        <div className="feed-empty">— Không có hoạt động nào thêm —</div>
      </div>
    </div>
  );
}

/* ---------- DASHBOARD ---------- */
function Dashboard() {
  // ── live data (falls back to mock when backend payloads absent) ──
  const _st = window.OMNI_STATUS || {};
  const _k = _st.kpis || {};
  const _sys = _st.system || {};
  const _pl = window.OMNI_PIPELINE || {};
  const _fmtDur = (s) => s == null ? '—' : (s >= 60 ? Math.floor(s / 60) + 'm ' + (s % 60) + 's' : s + 's');
  const chName = (id) => { const c = (CHANNELS || []).find(x => x.id === id); return c ? c.name : id; };
  const jobs = (_pl.active_jobs || []).map(j => ({
    channel_id: j.channel_id,
    ch: chName(j.channel_id),
    stage: (j.phase || 'pipeline') + (j.current_topic ? ' · ' + j.current_topic : ''),
    pct: typeof j.progress_pct === 'number' ? j.progress_pct : 0,
    elapsed: _fmtDur(j.elapsed_seconds),
    eta: j.eta_seconds != null ? '~' + _fmtDur(j.eta_seconds) : '—',
  }));
  const spend = typeof _k.daily_spend_usd === 'number' ? _k.daily_spend_usd : 42.30;
  const cap = typeof _k.daily_cap_usd === 'number' ? _k.daily_cap_usd : 100;
  const spendPct = Math.min(100, Math.round((spend / (cap || 1)) * 100));
  const kRunning = _k.active_runs != null ? _k.active_runs : jobs.length;
  const kScripts = _k.scripts_approved_today != null ? _k.scripts_approved_today : 18;
  const kChannels = _k.total_channels != null ? _k.total_channels : (CHANNELS || []).length;
  const kNiches = _sys.niches_discovered != null ? _sys.niches_discovered : (VAULT_NICHES || []).length;
  const activity = (_st.recent_activity || []).slice(0, 4).map(a => ({
    topic: a.topic || '(no topic)',
    ch: chName(a.channel_id),
    phase: a.phase || '',
    score: a.score ? a.score : null,
    status: a.status === 'completed' ? 'green' : a.status === 'failed' ? 'red' : 'blue',
  }));
  return (
    <div>
      <div className="page-title">Dashboard</div>
      <div className="page-desc">Tổng quan hệ thống sản xuất nội dung OmniCast Engine</div>

      <div className="grid g4 mb24">
        <div className="kpi">
          <div className="kpi-label"><span className="kpi-ico" style={{ background: 'var(--amber-soft)', color: 'var(--amber)' }}>{I.bolt}</span>Đang chạy</div>
          <div className="kpi-val text-amber">{kRunning}</div>
          <div className="kpi-sub" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>{kRunning > 0 && <span className="spin"></span>}pipeline active</div>
        </div>
        <div className="kpi">
          <div className="kpi-label"><span className="kpi-ico" style={{ background: 'var(--blue-soft)', color: 'var(--blue)' }}>{I.scripts}</span>Script hôm nay</div>
          <div className="kpi-val">{kScripts}</div>
          <div className="kpi-sub up">{I.up} score ≥ 70</div>
        </div>
        <div className="kpi">
          <div className="kpi-label"><span className="kpi-ico" style={{ background: 'var(--green-soft)', color: 'var(--green)' }}>{I.budget}</span>Chi phí hôm nay</div>
          <div className="kpi-val">${spend.toFixed(2)}</div>
          <div className="prog"><i className="amber" style={{ width: spendPct + '%' }}></i></div>
        </div>
        <div className="kpi">
          <div className="kpi-label"><span className="kpi-ico" style={{ background: 'var(--purple-soft)', color: 'var(--purple)' }}>{I.channels}</span>Kênh</div>
          <div className="kpi-val">{kChannels}</div>
          <div className="kpi-sub">{kNiches} niches discovered</div>
        </div>
      </div>

      <div className="grid g2 mb16">
        <div className="card pad-lg">
          <div className="card-hd"><div><div className="card-title">Pipeline đang chạy</div><div className="card-sub">Real-time job status</div></div></div>
          {window.OMNI_PIPELINE === undefined ? (
            <Skeleton h="120px" />
          ) : jobs.length === 0 ? (
            <EmptyState
              icon={<Icon name="zap" size={32} />}
              title="Không có pipeline nào đang chạy"
              desc='Bấm "Full Run Pipeline" ở tab Văn phòng hoặc chạy từng phase ở tab Kênh.'
            />
          ) : (
            jobs.map((j, i) => (
              <div key={i} style={{ padding: '12px 0', borderBottom: i < jobs.length - 1 ? '1px solid var(--border)' : 'none' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span className="spin"></span><span style={{ fontWeight: 700, fontSize: 13.5 }}>{j.ch}</span>
                  </div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <button className="btn btn-ghost sm" style={{ fontSize: 11, padding: '2px 8px', color: 'var(--text2)', borderColor: 'var(--border)' }} onClick={() => {
                      window.__showConfirm('Khởi động lại pipeline', 'Khởi động lại pipeline cho kênh này từ đầu?', () => {
                        window.OmniActions.runChannel(j.channel_id || j.ch);
                      });
                    }}>
                      <Icon name="refresh-cw" size={10} /> Khởi động lại
                    </button>
                    <span className="tag amber"><Icon name="clock" size={12} /> {j.elapsed} · ETA {j.eta}</span>
                  </div>
                </div>
                <div className="text-blue" style={{ fontSize: 12.5, marginBottom: 6, fontWeight: 500 }}>{j.stage}</div>
                <div className="prog"><i style={{ width: `${j.pct}%` }}></i></div>
              </div>
            ))
          )}
        </div>

        <div className="card pad-lg">
          <div className="card-hd"><div><div className="card-title">Lỗi gần đây</div><div className="card-sub">từ pipeline</div></div></div>
          {(() => {
            const errs = window.OMNI_ERRORS || [];
            if (window.OMNI_ERRORS === undefined) return <Skeleton h="120px" />;
            if (!errs.length) return (
              <EmptyState
                icon={<Icon name="check" size={32} style={{ color: 'var(--green)' }} />}
                title="Không có lỗi nào"
                desc="Hệ thống đang chạy sạch."
              />
            );
            return errs.slice(0, 6).map((e, i) => (
              <div key={i} className="mrow" style={{ alignItems: 'flex-start' }}>
                <span className="feed-dot" style={{ background: 'var(--red)', marginTop: 5 }}></span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 12.5, fontWeight: 600 }}>{e.channel_id || e.phase || 'pipeline'}</div>
                  <div style={{ fontSize: 11.5, color: 'var(--text3)' }}>{(e.error || e.message || e.msg || JSON.stringify(e)).slice(0, 120)}</div>
                </div>
                {e.ts && <span className="feed-time">{(window.OMNI_FMT_TIME ? window.OMNI_FMT_TIME(e.ts) : '')}</span>}
              </div>
            ));
          })()}
        </div>
      </div>

      <div className="card pad-lg">
        <div className="card-hd"><div><div className="card-title">Hoạt động gần đây</div></div></div>
        {(activity.length ? activity : [
          { topic: 'Chưa có hoạt động', ch: '', phase: '', score: null, status: 'blue' },
        ]).map((a, i) => (
          <div key={i} className="mrow">
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600, fontSize: 13.5 }}>{a.topic}</div>
              <div style={{ fontSize: 11.5, color: 'var(--text3)', marginTop: 1 }}>{a.ch} · {a.phase}</div>
            </div>
            {a.score != null && <span className={`tag ${a.status}`} style={{ marginRight: 10 }}>Score {a.score}</span>}
            <span className={`tag ${a.status}`}>{a.phase}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------- CHANNELS (master-detail) ---------- */
function Channels() {
  const [selId, setSelId] = uS(CHANNELS[0] && CHANNELS[0].id);
  // Resolve against the live list so the detail panel never shows a stale row.
  const sel = (CHANNELS || []).find(c => c.id === selId) || CHANNELS[0] || {};
  const setSel = (c) => setSelId(c.id);
  const stColor = { active: 'green', paused: 'amber', idle: 'gray' };
  const _ovList = ((window.OMNI_CH_OVERVIEW || {}).channels) || [];
  const STAT = {}; _ovList.forEach(c => { STAT[c.channel_id] = c; });
  const _kn = (x) => (x || 0) >= 1000 ? ((x / 1000).toFixed(x >= 1e6 ? 2 : 1).replace(/\.0$/, '') + (x >= 1e6 ? 'M' : 'K')) : String(x || 0);
  const ss = STAT[sel.id] || {};
  return (
    <div style={{ height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 8 }}>
        <div>
          <div className="page-title">Kênh</div>
          <div className="page-desc">Quản lý tất cả kênh hệ thống đang vận hành</div>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button className="btn btn-ghost sm" onClick={() => window.OmniActions.refreshChannelStats()}><Icon name="refresh-cw" /> Cập nhật số liệu YouTube</button>
          {(() => { const a = window.OMNI_AUTO || {}; return a.running
            ? <span className="tag green"><Icon name="zap" /> Auto: {a.channel || '—'} · {a.step}</span>
            : <button className="btn btn-primary sm" onClick={() => { window.__showConfirm('Chạy Auto-Pilot', 'Chạy Auto-Pilot cho TẤT CẢ kênh? (discover→topic→script→render). Upload = riêng tư.', () => window.OmniActions.autoRun(null, false)); }}><Icon name="zap" /> Auto-Pilot tất cả</button>; })()}
        </div>
      </div>
      {(() => {
        const ov = window.OMNI_CH_OVERVIEW || {}; const t = ov.totals || {};
        const _n = (x) => (x || 0).toLocaleString('en-US');
        const cards = [
          { l: 'Tổng kênh', v: _n(t.channels), s: (t.linked || 0) + ' đã liên kết' },
          { l: 'Tổng lượt xem', v: _n(t.views), s: _n(t.subscribers) + ' subs' },
          { l: 'Tổng video', v: _n(t.videos), s: 'trên tất cả kênh' },
          { l: 'Doanh thu ước tính', v: '$' + _n(Math.round(t.est_revenue_usd || 0)), s: 'views × RPM' },
        ];
        return <div className="grid g4" style={{ margin: '12px 0 16px' }}>{cards.map((c, i) => (
          <div key={i} className="kpi-card"><div className="kpi-lbl">{c.l}</div><div className="kpi-val">{c.v}</div><div className="kpi-sub" style={{ fontSize: 11, color: 'var(--text3)' }}>{c.s}</div></div>
        ))}</div>;
      })()}
      <div className="md">
        <div className="md-list">
          <button className="btn btn-primary" style={{ width: '100%' }} onClick={() => {
            const id = prompt('Channel ID (vd: fin_crypto_us):'); if (!id) return;
            const name = prompt('Tên kênh:') || id;
            const niche = prompt('Niche (finance/health/mythology...):') || 'finance';
            window.OmniActions.createChannel({ channel_id: id.trim(), name, niche, market: 'US' });
          }}>+ Kênh mới</button>
          {CHANNELS.map(c => {
            const s = STAT[c.id] || {}; const h = s.health || c.health || 0; return (
            <div key={c.id} className={`chan-item ${sel.id === c.id ? 'sel' : ''}`} onClick={() => setSel(c)}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {s.avatar_url
                  ? <img src={s.avatar_url} alt="" style={{ width: 34, height: 34, borderRadius: '50%', objectFit: 'cover', flexShrink: 0 }} />
                  : <div style={{ width: 34, height: 34, borderRadius: '50%', background: 'var(--surface2,#1a1f2e)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, flexShrink: 0 }}>{(c.name || '?')[0]}</div>}
                <div style={{ minWidth: 0 }}>
                  <div className="chan-name" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.name}</div>
                  <div className="chan-meta mono" style={{ fontSize: 11 }}>{c.id}</div>
                </div>
              </div>
              <div className="chan-foot" style={{ marginTop: 6 }}>
                <span style={{ fontSize: 11, color: 'var(--text3)' }}>👁 {_kn(s.total_views)} · <Icon name="video" /> {s.video_count || 0}{s.subscribers ? ' · 👤 ' + _kn(s.subscribers) : ''}</span>
                <span style={{ marginLeft: 'auto' }} className={`tag ${h >= 80 ? 'green' : h >= 60 ? 'amber' : h > 0 ? 'red' : 'gray'}`}>♥ {h || '—'}</span>
              </div>
            </div>
            ); })}
        </div>

        <div className="md-detail">
          <div className="card pad-lg">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18, flexWrap: 'wrap', gap: 10 }}>
              <div>
                <div style={{ fontSize: 20, fontWeight: 800, letterSpacing: '-0.02em' }}>{sel.name}</div>
                <div className="mono" style={{ fontSize: 12, color: 'var(--text3)' }}>{sel.id}</div>
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button className="btn btn-ghost-red sm" onClick={() => { window.__showConfirm('Xóa kênh', 'Bạn có chắc chắn muốn xóa kênh ' + sel.name + '?', () => window.OmniActions.deleteChannel(sel.id)); }}><Icon name="x" /> Xóa</button>
                <button className="btn btn-ghost sm" onClick={() => window.OmniActions.runChannel(sel.id)}>â–¶ Phase 1</button>
                <button className="btn btn-primary sm" onClick={() => window.OmniActions.runScript(sel.id)}><Icon name="file-text" /> Phase 2 — Script</button>
                <button className="btn btn-green sm" onClick={() => window.OmniActions.runChannel(sel.id)}>🚀 Full run</button>
                <button className="btn btn-primary sm" title="Tự động: tìm topic → kịch bản → render cho kênh này" onClick={() => { window.__showConfirm('Auto-Pilot kênh', 'Auto-Pilot kênh ' + sel.name + '? (discover→topic→script→render)', () => window.OmniActions.autoRun(sel.id, false)); }}><Icon name="zap" /> Auto kênh này</button>
              </div>
            </div>

            <div className="grid g2">
              <div className="section-card">
                <h4>🆔 Danh tính</h4>
                <div className="field"><label>Channel ID</label><div className="fval mono">{sel.id}</div></div>
                <div className="field"><label>Tên kênh</label><input id="__chan_name" defaultValue={sel.name} key={sel.id + 'n'} />
                  <button className="btn btn-ghost sm" style={{ marginTop: 6 }} onClick={() => { const v = (document.getElementById('__chan_name') || {}).value; if (v) window.OmniActions.updateChannel(sel.id, { name: v }); }}>💾 Lưu tên</button>
                </div>
                <div className="grid g2">
                  <div className="field"><label>Niche</label><div className="fval">{sel.niche}</div></div>
                  <div className="field"><label>Sub Niche</label><div className="fval">{sel.sub}</div></div>
                  <div className="field"><label>Market</label><div className="fval">{sel.market}</div></div>
                  <div className="field"><label>RPM Floor</label><div className="fval">${sel.rpm}</div></div>
                </div>
              </div>

              <div className="section-card">
                <h4><Icon name="settings" /> Thương hiệu</h4>
                <div className="field"><label>Voice Persona</label>
                  <div className="fval" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span>{sel.voice}</span>
                    <a href={`/voices?channel=${sel.id}`} target="_blank" rel="noopener"
                       style={{ background: '#5b5bd6', color: '#fff', padding: '4px 10px', borderRadius: 8, fontSize: 12, textDecoration: 'none', fontWeight: 600 }}>
                      🎙️ Đổi giọng
                    </a>
                  </div>
                </div>
                <div className="field"><label>Brand Tone</label><div className="fval">{sel.tone}</div></div>
                <div className="field"><label>Hook Format</label><div className="fval">{sel.hook}</div></div>
              </div>

              <div className="section-card">
                <h4><Icon name="video" /> Sản xuất</h4>
                <div className="field"><label>Visual Style</label><div className="fval">{sel.visual}</div></div>
                <div className="field"><label>Brand Color</label><div className="fval"><span className="swatch" style={{ background: sel.color }}></span>{sel.color}</div></div>
                <div className="grid g2">
                  <div className="field"><label>Font Vibe</label><div className="fval">{sel.font}</div></div>
                  <div className="field"><label>Target Duration</label><div className="fval">{sel.dur}</div></div>
                </div>
              </div>

              <div className="section-card">
                <h4>📊 Metadata</h4>
                <div className="field"><label>Competitor Handles</label><div className="fval">{sel.competitors}</div></div>
                <div className="field"><label>Trend Keywords</label><div className="fval">{sel.trends}</div></div>
                <div className="field"><label>Subreddits</label><div className="fval mono">{sel.subs}</div></div>
              </div>

              <div className="section-card">
                <h4><Icon name="activity" /> Số liệu YouTube</h4>
                {ss.linked ? (
                  <div className="grid g2">
                    <div className="field"><label>Subscribers</label><div className="fval">{_kn(ss.subscribers)}</div></div>
                    <div className="field"><label>Tổng views</label><div className="fval">{_kn(ss.total_views)}</div></div>
                    <div className="field"><label>Số video</label><div className="fval">{ss.video_count}</div></div>
                    <div className="field"><label>Doanh thu ước tính</label><div className="fval">${(ss.est_revenue_usd || 0).toLocaleString('en-US')}</div></div>
                    <div className="field"><label>Health</label><div className="fval"><span className={`tag ${ss.health >= 80 ? 'green' : ss.health >= 60 ? 'amber' : 'red'}`}>♥ {ss.health}</span></div></div>
                    <div className="field"><label>YouTube ID</label><div className="fval mono" style={{ fontSize: 11 }}>{ss.youtube_channel_id}</div></div>
                  </div>
                ) : (
                  <div className="fhint">Chưa liên kết YouTube. Thêm <code>youtube_channel_id</code> vào config rồi bấm "🔄 Cập nhật số liệu".</div>
                )}
              </div>

              <div className="section-card">
                <h4><Icon name="shield" /> Niche kênh đang làm</h4>
                {(sel.niches && sel.niches.length) ? (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {sel.niches.map((n, i) => <span key={i} className="tag blue" title={n.assigned_at}>{n.niche_name || n.niche_id}</span>)}
                  </div>
                ) : <div className="fhint">Niche chính: <b>{sel.niche}{sel.sub ? ' / ' + sel.sub : ''}</b>. Chưa có niche bổ sung gán vào kênh.</div>}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------- SCRIPTS ---------- */
const uE = React.useEffect;
function Scripts() {
  const chId = window.OMNI_SCRIPT_CH || (CHANNELS[0] && CHANNELS[0].id);
  const variants = (window.OMNI_VARIANTS && window.OMNI_VARIANTS.length) ? window.OMNI_VARIANTS : [];
  // Durable Topic Vault (queued/used/skipped) — survives event churn.
  const tv = window.OMNI_TOPIC_VAULT || {};
  const vaultTopics = (tv.channel_id === chId && Array.isArray(tv.topics)) ? tv.topics : [];
  const tcounts = tv.channel_id === chId ? (tv.counts || {}) : {};
  uE(() => { if (chId && window.OmniActions) window.OmniActions.loadTopics(chId); }, [chId]);
  const [open, setOpen] = uS(variants[0] ? variants[0].key : null);
  const [debate, setDebate] = uS(null);
  const curTopic = variants[0] ? variants[0].topic : '';
  return (
    <div>
      <div className="page-title">Kịch bản</div>
      <div className="page-desc">Thư viện script · chủ đề khám phá · variant management</div>

      <div className="card mb16" style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
        <span style={{ fontWeight: 600, fontSize: 13 }}>Kênh:</span>
        <select className="field" style={{ width: 'auto', minWidth: 220 }} value={chId} onChange={e => window.OmniLoadScripts(e.target.value)}>
          {CHANNELS.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <span className="tag blue">{variants.length} scripts</span>
        <span className="tag amber">{tcounts.queued || 0} topic chờ</span>
        {(tcounts.used || 0) > 0 && <span className="tag green">{tcounts.used} đã dùng</span>}
        <button className="btn btn-ghost sm" style={{ marginLeft: 'auto' }} onClick={() => window.OmniActions.runChannel(chId)}><Icon name="search" /> Tìm topic (Phase 1)</button>
      </div>

      <div className="card mb16">
        <div className="card-hd"><div><div className="card-title text-amber">🔍 Kho chủ đề</div><div className="card-sub">Topic lưu bền — automation lấy dần · {tcounts.queued || 0} chờ / {tcounts.used || 0} đã dùng / {tcounts.skipped || 0} bỏ</div></div></div>
        {vaultTopics.length === 0 && <div style={{ padding: 18, textAlign: 'center', color: 'var(--text3)' }}>Chưa có topic. Bấm "<Icon name="search" /> Tìm topic (Phase 1)" cho kênh này.</div>}
        {vaultTopics.map(t => (
          <div key={t.topic_id} className="topic-row" style={{ opacity: t.status === 'skipped' ? 0.5 : 1 }}>
            <div className="topic-main">
              <div className="topic-title">{t.title} {t.status === 'used' && <span className="tag green" style={{ fontSize: 10 }}>đã dùng</span>}{t.status === 'skipped' && <span className="tag gray" style={{ fontSize: 10 }}>đã bỏ</span>}</div>
              <div className="topic-sub">{t.pain_point ? '💢 ' + t.pain_point : ''}{t.audience_segment ? ' · 👥 ' + t.audience_segment : ''}</div>
            </div>
            <span className={`tag ${t.score >= 85 ? 'green' : t.score >= 75 ? 'amber' : 'gray'}`}>Score {t.score}</span>
            {t.status === 'queued' && <button className="btn btn-primary sm" onClick={() => window.OmniActions.scriptFromTopic(chId, t.topic_id)}><Icon name="file-text" /> Tạo kịch bản</button>}
            {t.status === 'queued' && <button className="btn btn-ghost sm" onClick={() => window.OmniActions.skipTopic(chId, t.topic_id)}>Bỏ</button>}
            {t.status === 'skipped' && <button className="btn btn-ghost sm" onClick={() => window.OmniActions.requeueTopic(chId, t.topic_id)}>Khôi phục</button>}
          </div>
        ))}
      </div>

      <div className="card">
        <div className="card-hd"><div><div className="card-title">Script Variants</div><div className="card-sub">{curTopic ? '"' + curTopic + '"' : 'Chưa có script'}</div></div></div>
        {variants.length === 0 && <div style={{ padding: 18, textAlign: 'center', color: 'var(--text3)' }}>Chưa có script cho kênh này. Chạy Phase 2 (Script) để tạo.</div>}
        {variants.map(v => (
          <div key={v.key} className="variant">
            <div className="variant-hd" onClick={() => setOpen(open === v.key ? null : v.key)}>
              <span className="mono" style={{ fontWeight: 700, fontSize: 13 }}>{v.id}{v.approved ? ' ✓' : ''}</span>
              <span className={`tag ${v.score >= 85 ? 'green' : 'amber'}`}>Score {v.score}</span>
              <span className="tag gray">{v.scenes} scenes</span>
              <span style={{ marginLeft: 'auto', color: 'var(--text3)' }}>{open === v.key ? 'â–²' : 'â–¼'}</span>
            </div>
            {open === v.key && (
              <div className="variant-body">
                <div className="hook-block"><b>Hook:</b> {v.hook}</div>
                <table className="scenes">
                  <thead><tr><th style={{ width: 40 }}>#</th><th style={{ width: '42%' }}>Visual</th><th>Voiceover</th></tr></thead>
                  <tbody>
                    {v.sceneList.map(s => (
                      <tr key={s.n}><td className="mono">{s.n}</td><td>{s.visual}</td><td>{s.vo}</td></tr>
                    ))}
                  </tbody>
                </table>
                <div className="outro-block"><b>Outro:</b> {v.outro}</div>
                <button className="btn btn-ghost sm" style={{ marginTop: 12 }} onClick={() => setDebate(debate === v.key ? null : v.key)}>
                  ⚔️ {debate === v.key ? 'Ẩn' : 'Xem'} Debate Log (Writer ↔ Critic)
                </button>
                {debate === v.key && (
                  <div style={{ marginTop: 12, background: 'var(--surface2)', borderRadius: 'var(--r-sm)', padding: '4px 14px' }}>
                    {v.debate.map((d, i) => (
                      <div key={i} className="debate-round">
                        <span className={`debate-side tag ${d.tone}`}>{d.side}</span>
                        <span style={{ fontSize: 12.5, color: 'var(--text2)' }}>{d.text}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------- NICHE VAULT ---------- */
function NicheVault() {
  const counts = {
    hot: VAULT_NICHES.filter(n => n.state === 'hot').length,
    watching: VAULT_NICHES.filter(n => n.state === 'watching').length,
    stale: VAULT_NICHES.filter(n => n.state === 'stale').length,
    active: VAULT_NICHES.filter(n => n.state === 'active').length,
    archived: VAULT_NICHES.filter(n => n.state === 'archived').length,
  };
  const stateTag = { hot: 'red', watching: 'amber', stale: 'gray', active: 'green', archived: 'gray' };
  const stateLbl = { hot: '<Icon name="alert-triangle" /> HOT', watching: '🟡 Watching', stale: '🔘 Stale', active: '🟢 Active', archived: '📦 Archived' };
  // Detail panel is now click-to-open: a row in the table reveals the full card
  // (evidence channels, note, Auto-Create / Archive). Nothing is shown until the
  // operator clicks a niche — keeps the page clean now that everything auto-runs.
  const [sel, setSel] = uS(null);
  const detail = (n) => (
    <div className="niche-panel" style={{ marginBottom: 16, borderLeft: `3px solid var(--${stateTag[n.state] === 'red' ? 'red' : stateTag[n.state] === 'green' ? 'green' : 'amber'})` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
        <span className="rank-num">#{n.rank}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 700, fontSize: 15 }}>{n.name}</div>
          <div style={{ fontSize: 12, color: 'var(--text3)' }}>{n.market} · {n.cat} · RPM ${n.rpm}</div>
        </div>
        <span className={`tag ${stateTag[n.state]}`}>{n.score}/100</span>
        <button className="btn btn-ghost sm" onClick={() => setSel(null)} title="Đóng" style={{ padding: '2px 8px' }}>✕</button>
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--text2)', marginBottom: 6 }}>📋 {n.note}</div>
      <div style={{ fontSize: 12, color: 'var(--text3)', marginBottom: 8 }}><Icon name="video" /> {n.video}</div>
      {(n.evidence && n.evidence.length > 0) && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text2)', marginBottom: 5 }}><Icon name="tv" /> Kênh đã trigger ngách này (học hỏi)</div>
          {n.evidence.slice(0, 4).map((e, i) => {
            const ox = e.channel_outlier || e.outlier || 0;
            return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11.5, padding: '4px 0', borderBottom: '1px solid rgba(0,0,0,0.04)' }}>
              {e.channel_url
                ? <a href={e.channel_url} target="_blank" rel="noopener" style={{ fontWeight: 700, color: 'var(--accent,#3b82f6)', minWidth: 0, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', textDecoration: 'none' }} title="Mở kênh trên YouTube">{e.channel || '—'} ↗</a>
                : <span style={{ fontWeight: 600, minWidth: 0, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.channel || '—'}</span>}
              {e.subs_k > 0 && <span className="tag gray" style={{ fontSize: 10 }}>👤 {e.subs_k >= 1000 ? (e.subs_k / 1000).toFixed(1) + 'M' : e.subs_k + 'K'}</span>}
              {ox > 0 && <span className={`tag ${ox >= 5 ? 'red' : ox >= 2 ? 'amber' : 'green'}`} style={{ fontSize: 10 }} title="Outlier: views vượt baseline kênh bao nhiêu lần">{ox.toFixed(1)}x</span>}
              {e.views > 0 && (e.video_url
                ? <a href={e.video_url} target="_blank" rel="noopener" style={{ fontSize: 10.5, color: 'var(--text3)', textDecoration: 'none' }} title={e.title}>👁 {e.views >= 1e6 ? (e.views / 1e6).toFixed(1) + 'M' : Math.round(e.views / 1000) + 'K'}</a>
                : <span style={{ fontSize: 10.5, color: 'var(--text3)' }}>👁 {e.views >= 1e6 ? (e.views / 1e6).toFixed(1) + 'M' : Math.round(e.views / 1000) + 'K'}</span>)}
            </div>
            );
          })}
        </div>
      )}
      {(!n.evidence || n.evidence.length === 0) && n.example_channels && n.example_channels.length > 0 && (
        <div style={{ fontSize: 11.5, color: 'var(--text3)', marginBottom: 12 }}>📺 {n.example_channels.slice(0, 3).join(' · ')}</div>
      )}
      <div style={{ display: 'flex', gap: 8 }}>
        <button className="btn btn-primary sm" onClick={() => window.OmniActions.vaultToChannel(n.niche_id)} disabled={!n.niche_id}><Icon name="zap" /> Auto-Create kênh</button>
        <button className="btn btn-ghost sm" onClick={() => window.OmniActions.archiveNiche(n.niche_id)} disabled={!n.niche_id}>📦 Archive</button>
      </div>
    </div>
  );
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div className="page-title">Niche Vault</div>
          <div className="page-desc">Kho niche đã khám phá · health tracking · auto-create · bấm 1 niche để xem chi tiết</div>
        </div>
        <button className="btn btn-ghost sm" onClick={() => window.OmniActions.vaultHealthCheck()}>🩺 Health check</button>
      </div>

      <div className="grid g4 mb24">
        <div className="kpi"><div className="kpi-label">Tổng Niches</div><div className="kpi-val">{VAULT_NICHES.length}</div><div className="kpi-sub">đã lưu vào vault</div></div>
        <div className="kpi"><div className="kpi-label"><Icon name="alert-triangle" /> HOT</div><div className="kpi-val text-red">{counts.hot}</div><div className="kpi-sub">sẵn sàng tạo kênh</div></div>
        <div className="kpi"><div className="kpi-label">🟡 Watching</div><div className="kpi-val text-amber">{counts.watching}</div><div className="kpi-sub">đang theo dõi</div></div>
        <div className="kpi"><div className="kpi-label">🔘 Stale</div><div className="kpi-val" style={{ color: 'var(--text3)' }}>{counts.stale}</div><div className="kpi-sub">giảm quan tâm</div></div>
      </div>

      {sel && detail(sel)}

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <table className="dtable">
          <thead><tr><th>#</th><th>Niche</th><th>Market</th><th>Category</th><th>Score</th><th>RPM</th><th>Trạng thái</th></tr></thead>
          <tbody>
            {VAULT_NICHES.map(n => {
              const isSel = sel && sel.rank === n.rank;
              return (
              <tr key={n.rank} onClick={() => setSel(isSel ? null : n)} style={{ cursor: 'pointer', background: isSel ? 'var(--surface2)' : undefined }} title="Bấm để xem chi tiết">
                <td className="mono" style={{ color: 'var(--text3)' }}>{n.rank}</td>
                <td style={{ fontWeight: 600 }}>{n.name}</td>
                <td>{n.market}</td><td>{n.cat}</td>
                <td><b>{n.score}</b></td><td>${n.rpm}</td>
                <td><span className={`tag ${stateTag[n.state]}`}>{stateLbl[n.state]}</span></td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ---------- SCHEDULER (per-channel auto post) ---------- */
function Scheduler() {
  const sc = window.OMNI_SCHED || {};
  const chans = sc.channels || [];
  const cadences = Object.keys(sc.cadence_map || { daily: 7, '3x_weekly': 3, twice_weekly: 2, weekly: 1 });
  const A = window.OmniActions;
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 8 }}>
        <div>
          <div className="page-title">Lịch đăng tự động</div>
          <div className="page-desc">Mỗi kênh tự chạy (tìm topic → script → render → đăng) theo cadence + giờ vàng</div>
        </div>
        <button className={`btn sm ${sc.enabled ? 'btn-green' : 'btn-primary'}`} onClick={() => A.schedulerMaster(!sc.enabled)}>
          {sc.enabled ? '🟢 Lịch ĐANG BẬT — tắt' : '⏸ Bật lịch tự động'}
        </button>
      </div>
      {!sc.enabled && <div className="card pad-lg" style={{ marginTop: 14, color: 'var(--text2)', fontSize: 13 }}>Công tắc tổng đang TẮT. Bật để các kênh đã lên lịch tự chạy. Mỗi tick {Math.round((sc.tick_seconds || 300) / 60)} phút kiểm tra 1 lần, mỗi lần chạy 1 kênh đến hạn.</div>}

      <div className="card" style={{ padding: 0, overflow: 'hidden', marginTop: 16 }}>
        <table className="dtable">
          <thead><tr><th>Kênh</th><th>Bật</th><th>Tần suất</th><th>Giờ (UTC)</th><th>Shorts</th><th>Tự đăng</th><th>Lần cuối</th><th>Tuần này</th></tr></thead>
          <tbody>
            {chans.map(c => (
              <tr key={c.channel_id}>
                <td style={{ fontWeight: 600 }}>{c.name}<div className="mono" style={{ fontSize: 10, color: 'var(--text3)' }}>{c.channel_id}</div></td>
                <td><input type="checkbox" checked={!!c.enabled} onChange={e => A.setChannelSchedule(c.channel_id, { enabled: e.target.checked })} /></td>
                <td>
                  <select className="field" style={{ width: 'auto', minWidth: 110, padding: '3px 6px' }} value={c.cadence} onChange={e => A.setChannelSchedule(c.channel_id, { cadence: e.target.value })}>
                    {cadences.map(cd => <option key={cd} value={cd}>{cd}</option>)}
                  </select>
                </td>
                <td className="mono" style={{ fontSize: 11 }}>{(c.prime_hours || []).join(', ')}</td>
                <td><input type="checkbox" checked={!!c.shorts} onChange={e => A.setChannelSchedule(c.channel_id, { shorts: e.target.checked })} /></td>
                <td><input type="checkbox" checked={!!c.upload} onChange={e => A.setChannelSchedule(c.channel_id, { upload: e.target.checked })} /></td>
                <td className="mono" style={{ fontSize: 11, color: 'var(--text3)' }}>{c.last_run || '—'}</td>
                <td className="mono" style={{ fontSize: 11 }}>{c.week_count || 0}/{(sc.cadence_map || {})[c.cadence] || '?'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ fontSize: 11.5, color: 'var(--text3)', marginTop: 10 }}>
        Giờ đặt theo UTC. Sửa giờ vàng trong channel config (<code>prime_time_hours</code>). "Tự đăng" = upload luôn (private) sau render; tắt = chỉ render chờ duyệt.
      </div>
    </div>
  );
}

/* ---------- POLICY ---------- */
function Policy() {
  const p = window.OMNI_POLICY || {};
  const pending = p.pending || [], active = p.active || [], checks = p.compliance_checks || [];
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 8 }}>
        <div>
          <div className="page-title">Chính sách YouTube</div>
          <div className="page-desc">Theo dõi thay đổi chính sách · cổng compliance trước khi đăng</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {p.policy_running && <span className="tag amber">⏳ Đang quét…</span>}
          <button className="btn btn-primary sm" onClick={() => window.OmniActions.policyFetch()}>🔄 Quét chính sách mới</button>
        </div>
      </div>

      <div className="card pad-lg" style={{ marginTop: 16 }}>
        <div className="card-title" style={{ marginBottom: 10 }}><Icon name="check" /> Compliance gate (chặn trước khi đăng)</div>
        <div className="grid g2">
          {checks.map(c => (
            <div key={c.id} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', padding: '7px 0', borderBottom: '1px solid rgba(0,0,0,0.05)' }}>
              <span className="tag green" style={{ fontSize: 10 }}>ON</span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 12.5 }}>{c.id}</div>
                <div style={{ fontSize: 11.5, color: 'var(--text2)' }}>{c.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="card pad-lg" style={{ marginTop: 16 }}>
        <div className="card-title" style={{ marginBottom: 4 }}>⚠ Thay đổi chính sách chờ duyệt ({pending.length})</div>
        <div className="card-sub" style={{ marginBottom: 10 }}>Hệ thống phát hiện YouTube đổi chính sách — bạn duyệt để áp dụng</div>
        {pending.length === 0 && <div style={{ color: 'var(--text3)', fontSize: 12.5, padding: 12, textAlign: 'center' }}>Chưa có thay đổi nào chờ duyệt. Bấm "Quét chính sách mới".</div>}
        {pending.map(r => (
          <div key={r.rule_id} style={{ padding: '10px 0', borderBottom: '1px solid rgba(0,0,0,0.05)' }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 3 }}>{r.rule_text}</div>
            {r.diff_context && <div style={{ fontSize: 11.5, color: 'var(--text3)', marginBottom: 6 }}>{(r.diff_context || '').slice(0, 220)}</div>}
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              {r.source_url && <a href={r.source_url} target="_blank" rel="noopener" style={{ fontSize: 11, color: 'var(--accent,#3b82f6)' }}>nguồn ↗</a>}
              <button className="btn btn-green sm" onClick={() => window.OmniActions.policyRule(r.rule_id, 'approve')}><Icon name="check" /> Duyệt</button>
              <button className="btn btn-ghost sm" onClick={() => window.OmniActions.policyRule(r.rule_id, 'reject')}><Icon name="x" /> Bỏ</button>
            </div>
          </div>
        ))}
      </div>

      <div className="card pad-lg" style={{ marginTop: 16 }}>
        <div className="card-title" style={{ marginBottom: 10 }}><Icon name="file-text" /> Rule đang áp dụng ({active.length})</div>
        {active.length === 0 && <div style={{ color: 'var(--text3)', fontSize: 12.5 }}>Chưa có rule nào được duyệt.</div>}
        {active.map(r => (
          <div key={r.rule_id} style={{ display: 'flex', gap: 8, padding: '6px 0', fontSize: 12.5, borderBottom: '1px solid rgba(0,0,0,0.04)' }}>
            <span className="tag blue" style={{ fontSize: 10 }}>active</span>
            <span style={{ flex: 1 }}>{r.rule_text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------- INFRASTRUCTURE ---------- */
function Infrastructure() {
  const stColor = { up: '#22c55e', degraded: '#f59e0b', down: '#ef4444' };
  const stLabel = { up: 'Hoạt động', degraded: 'Suy giảm', down: 'Offline' };
  const offline = COMPONENTS.filter(c => c.status !== 'up').length;
  return (
    <div>
      <div className="page-title">Hạ tầng</div>
      <div className="page-desc">Trạng thái các component hệ thống · error log</div>

      <div className="grid g4 mb24">
        <div className="kpi"><div className="kpi-label">Tổng components</div><div className="kpi-val">{COMPONENTS.length}</div><div className="kpi-sub">đang giám sát</div></div>
        <div className="kpi"><div className="kpi-label">Hoạt động</div><div className="kpi-val text-green">{COMPONENTS.length - offline}</div><div className="kpi-sub up">{I.up} ổn định</div></div>
        <div className="kpi"><div className="kpi-label">Cảnh báo</div><div className="kpi-val text-amber">{offline}</div><div className="kpi-sub">cần chú ý</div></div>
        <div className="kpi"><div className="kpi-label">Tình trạng</div><div className="kpi-val" style={{ color: offline ? 'var(--amber)' : 'var(--green)' }}>{COMPONENTS.length ? Math.round(((COMPONENTS.length - offline) / COMPONENTS.length) * 100) : 0}%</div><div className="kpi-sub">{COMPONENTS.length - offline}/{COMPONENTS.length} component online</div></div>
      </div>

      <div className="grid g4 mb16">
        {COMPONENTS.map((c, i) => (
          <div key={i} className="comp-card">
            <div className="comp-hd">
              <div className="comp-ico">{c.icon}</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: 13, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.name}</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 2 }}>
                  <span className="status-dot-lg" style={{ background: stColor[c.status] }}></span>
                  <span style={{ fontSize: 11.5, color: 'var(--text2)' }}>{stLabel[c.status]}</span>
                </div>
              </div>
            </div>
            <div className="mrow" style={{ padding: '6px 0' }}><span className="mlabel">Latency</span><span className="mval mono">{c.latency}</span></div>
            <div className="mrow" style={{ padding: '6px 0' }}><span className="mlabel">Version</span><span className="mval mono">{c.version}</span></div>
            <div className="mrow" style={{ padding: '6px 0' }}><span className="mlabel">Uptime</span><span className="mval mono">{c.uptime}</span></div>
          </div>
        ))}
      </div>

      <div className="card pad-lg">
        <div className="card-hd"><div><div className="card-title">Error Log</div><div className="card-sub">từ pipeline (24h)</div></div></div>
        {(() => {
          const errs = window.OMNI_ERRORS || [];
          if (!errs.length) return <div style={{ color: 'var(--green)', fontSize: 13, padding: '8px 0' }}><Icon name="check" /> Không có lỗi nào ghi nhận</div>;
          return (
            <pre style={{ background: '#1a1a2e', color: '#e8e8ec', padding: 16, borderRadius: 'var(--r-sm)', fontSize: 12, fontFamily: 'var(--mono)', overflow: 'auto', lineHeight: 1.7, maxHeight: 220 }}>
{errs.slice(0, 20).map(e => `[${(e.ts || '').slice(11, 19)}] ${(e.channel_id || e.phase || 'pipeline')} — ${(e.error || e.message || e.msg || JSON.stringify(e)).slice(0, 140)}`).join('\n')}
            </pre>
          );
        })()}
      </div>
    </div>
  );
}

/* ---------- BUDGET ---------- */
function Budget() {
  const _bg = window.OMNI_BUDGET || {};
  const today = typeof _bg.today_usd === 'number' ? _bg.today_usd : 42.30;
  const cap = typeof _bg.daily_cap_usd === 'number' ? _bg.daily_cap_usd : 100;
  const total = typeof _bg.total_usd === 'number' ? _bg.total_usd : 3847;
  const todayPct = Math.min(100, Math.round((today / (cap || 1)) * 100));
  const _bd = Array.isArray(_bg.breakdown) ? _bg.breakdown : [];
  const _bdMax = _bd.reduce((m, b) => Math.max(m, b.amount || b.amt || 0), 0) || 1;
  const breakdown = _bd.length ? _bd.map(b => {
    const amt = b.amount || b.amt || 0;
    return { cat: b.category || b.cat || b.label || '—', amt, pct: Math.round((amt / _bdMax) * 100) };
  }) : [
    { cat: 'Chưa có chi phí ghi nhận', amt: 0, pct: 0 },
  ];
  return (
    <div>
      <div className="page-title">Chi phí</div>
      <div className="page-desc">Theo dõi ngân sách và tối ưu ROI</div>

      <div className="grid g3 mb24">
        <div className="kpi"><div className="kpi-label">Chi phí hôm nay</div><div className="kpi-val">${today.toFixed(2)}</div><div className="prog"><i className="amber" style={{ width: todayPct + '%' }}></i></div><div className="kpi-sub" style={{ marginTop: 6 }}>{todayPct}% của ${cap} cap</div></div>
        <div className="kpi"><div className="kpi-label">Cap hằng ngày</div><div className="kpi-val text-green">${cap}</div><div className="kpi-sub">giới hạn ngân sách</div></div>
        <div className="kpi"><div className="kpi-label">Tổng all-time</div><div className="kpi-val">${total.toLocaleString()}</div><div className="kpi-sub">tích lũy</div></div>
      </div>

      <div className="grid g2">
        <div className="card pad-lg">
          <div className="card-hd"><div className="card-title">Cost Breakdown</div></div>
          {breakdown.map((b, i) => (
            <div key={i} style={{ marginBottom: 14 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
                <span className="mlabel">{b.cat}</span><span className="mval">${b.amt}</span>
              </div>
              <div className="prog"><i style={{ width: `${b.pct}%` }}></i></div>
            </div>
          ))}
        </div>
        <div className="card pad-lg">
          <div className="card-hd"><div className="card-title">RPM theo Niche</div><div className="card-sub">ước tính, từ vault thật</div></div>
          {(() => {
            const rows = (VAULT_NICHES || []).filter(n => (n.rpm || 0) > 0)
              .sort((a, b) => (b.rpm || 0) - (a.rpm || 0)).slice(0, 8);
            if (!rows.length) return <div style={{ color: 'var(--text3)', fontSize: 13 }}>Chưa có dữ liệu RPM</div>;
            return rows.map((n, i) => (
              <div key={i} className="mrow">
                <span className="mlabel">{n.name}</span>
                <span className={`mval text-${n.rpm >= 12 ? 'green' : n.rpm >= 7 ? 'amber' : 'red'}`}>${(+n.rpm).toFixed(1)}</span>
              </div>
            ));
          })()}
        </div>
      </div>
    </div>
  );
}

function getMediaUrl(path) {
  if (!path) return '';
  let clean = path.replace(/\\/g, '/');
  if (clean.startsWith('/media/')) return clean;
  if (clean.startsWith('media/')) return '/' + clean;
  const idx = clean.indexOf('/output/');
  if (idx !== -1) {
    return '/media/' + clean.slice(idx + 8);
  }
  return '/media/' + clean;
}
window.getMediaUrl = getMediaUrl;

function ApprovalCard({ a }) {
  const [showApproveModal, setShowApproveModal] = uS(false);
  const [showRejectModal, setShowRejectModal] = uS(false);
  const [privacy, setPrivacy] = uS('unlisted');
  const [force, setForce] = uS(false);
  const [rejectNote, setRejectNote] = uS('');
  const [publishError, setPublishError] = uS(a.raw?.publish_error || '');
  const [youtubeVideoId, setYoutubeVideoId] = uS(a.raw?.youtube_video_id || '');

  const handleApprove = () => {
    window.OmniActions.approvalDecision(a.approval_id, 'approve', { privacy_status: privacy, force, operator: 'dashboard' })
      .then(res => {
        setShowApproveModal(false);
        const updated = res || {};
        const raw = updated.raw || {};
        if (raw.youtube_video_id) {
          window._toast('Đã đăng! Link: https://youtu.be/' + raw.youtube_video_id, true);
          window.open('https://youtu.be/' + raw.youtube_video_id, '_blank');
        } else if (raw.publish_error) {
          setPublishError(raw.publish_error);
          window._toast('Lỗi đăng video', false);
        } else {
          window._toast('Duyệt thành công', true);
        }
      })
      .catch(e => {
        setPublishError(e.message);
        window._toast('Lỗi: ' + e.message, false);
      });
  };

  const handleReject = () => {
    window.OmniActions.approvalDecision(a.approval_id, 'reject', { note: rejectNote, operator: 'dashboard' })
      .then(() => {
        setShowRejectModal(false);
        window._toast('Từ chối thành công', true);
      });
  };

  const getDuration = (ts) => {
    if (!ts) return '';
    const diffMs = new Date() - new Date(ts);
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'vừa xong';
    if (diffMins < 60) return diffMins + ' phút trước';
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return diffHours + ' giờ trước';
    return Math.floor(diffHours / 24) + ' ngày trước';
  };

  const thumbUrl = a.raw?.thumbnail_paths?.[0] ? getMediaUrl(a.raw.thumbnail_paths[0]) : '';
  const summaryText = a.summary ? a.summary.slice(0, 200) + (a.summary.length > 200 ? '...' : '') : '';

  return (
    <div className="card pad-md mb16" style={{ display: 'flex', flexDirection: 'row', gap: 16, alignItems: 'flex-start' }}>
      <div style={{ width: 120, height: 68, borderRadius: 'var(--r-sm)', background: 'var(--surface2)', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', flexShrink: 0 }}>
        {thumbUrl ? (
          <img src={thumbUrl} style={{ width: '100%', height: '100%', objectFit: 'cover' }} onError={(e) => { e.target.style.display = 'none'; }} />
        ) : (
          <Icon name="film" size={24} style={{ color: 'var(--text3)' }} />
        )}
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <h4 style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>{a.title || a.video_id || a.approval_id}</h4>
        
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8, alignItems: 'center' }}>
          <span className="tag gray">{a.channel_id}</span>
          <span className={`tag ${a.platform_id === 'youtube' ? 'red' : 'gray'}`} style={{ background: a.platform_id === 'youtube' ? '#fee2e2' : undefined, color: a.platform_id === 'youtube' ? '#ef4444' : undefined }}>
            {a.platform_id}
          </span>
          {a.raw?.dry_run && <span className="tag amber">dry-run</span>}
          <span className="tag gray" style={{ fontSize: 11 }}><Icon name="clock" size={10} /> {getDuration(a.requested_at)}</span>
        </div>

        <p style={{ fontSize: 12.5, color: 'var(--text2)', marginBottom: 8, lineHeight: 1.4 }}>{summaryText}</p>

        {publishError && (
          <div style={{ padding: '8px 12px', background: 'var(--red-soft)', color: 'var(--red)', borderRadius: 'var(--r-sm)', fontSize: 12, marginBottom: 8, fontWeight: 500 }}>
            <Icon name="alert-triangle" size={12} /> {publishError}
          </div>
        )}

        {youtubeVideoId && (
          <div style={{ marginBottom: 8 }}>
            <a href={`https://youtu.be/${youtubeVideoId}`} target="_blank" rel="noopener noreferrer" style={{ fontSize: 12.5, color: 'var(--blue)', fontWeight: 600, textDecoration: 'none' }}>
              <Icon name="external-link" size={12} /> https://youtu.be/{youtubeVideoId}
            </a>
          </div>
        )}
      </div>

      <div style={{ display: 'flex', gap: 8, alignSelf: 'center', flexShrink: 0 }}>
        <button className="btn btn-primary sm" onClick={() => setShowApproveModal(true)}>
          <Icon name="check" /> Duyệt
        </button>
        <button className="btn btn-ghost sm" onClick={() => setShowRejectModal(true)} style={{ color: 'var(--red)', borderColor: 'var(--red)' }}>
          <Icon name="x" /> Từ chối
        </button>
      </div>

      {showApproveModal && (
        <div className="modal-backdrop" onClick={() => setShowApproveModal(false)}>
          <div className="card pad-lg" style={{ maxWidth: 400, width: '90%', background: 'var(--surface)', borderRadius: 'var(--r-md)' }} onClick={e => e.stopPropagation()}>
            <h3 style={{ marginBottom: 12, fontSize: 15 }}>Duyệt & Đăng video</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 20 }}>
              <div>
                <label style={{ fontSize: 12, color: 'var(--text2)', display: 'block', marginBottom: 4 }}>Chế độ riêng tư (Privacy Status)</label>
                <select className="field" value={privacy} onChange={e => setPrivacy(e.target.value)}>
                  <option value="unlisted">unlisted (mặc định)</option>
                  <option value="private">private</option>
                  <option value="public">public</option>
                </select>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
                <input type="checkbox" id={`chk-force-${a.approval_id}`} checked={force} onChange={e => setForce(e.target.checked)} />
                <label htmlFor={`chk-force-${a.approval_id}`} style={{ fontSize: 12.5, color: 'var(--text)' }}>Force (bỏ qua cảnh báo compliance)</label>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button className="btn btn-ghost sm" onClick={() => setShowApproveModal(false)}>Hủy</button>
              <button className="btn btn-primary sm" onClick={handleApprove}>Duyệt & Đăng</button>
            </div>
          </div>
        </div>
      )}

      {showRejectModal && (
        <div className="modal-backdrop" onClick={() => setShowRejectModal(false)}>
          <div className="card pad-lg" style={{ maxWidth: 400, width: '90%', background: 'var(--surface)', borderRadius: 'var(--r-md)' }} onClick={e => e.stopPropagation()}>
            <h3 style={{ marginBottom: 12, fontSize: 15 }}>Từ chối đăng video</h3>
            <div style={{ marginBottom: 20 }}>
              <label style={{ fontSize: 12, color: 'var(--text2)', display: 'block', marginBottom: 4 }}>Lý do từ chối (Note)</label>
              <textarea className="field" style={{ minHeight: 80, resize: 'vertical' }} value={rejectNote} onChange={e => setRejectNote(e.target.value)} placeholder="Nhập lý do..." />
            </div>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button className="btn btn-ghost sm" onClick={() => setShowRejectModal(false)}>Hủy</button>
              <button className="btn btn-primary sm" onClick={handleReject} style={{ background: 'var(--red)', borderColor: 'var(--red)' }}>Từ chối</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------- MONETIZATION ---------- */
function Monetization() {
  const readiness = window.OMNI_READINESS || {};
  const checks = readiness.checks || [];
  const blockers = readiness.blockers || [];
  const platforms = ((window.OMNI_PLATFORMS || {}).platforms) || [];
  const destinations = ((window.OMNI_DESTINATIONS || {}).destinations) || [];
  const credentials = ((window.OMNI_CREDENTIALS || {}).credentials) || [];
  const offers = ((window.OMNI_OFFERS || {}).offers) || [];
  const capabilities = ((window.OMNI_CAPABILITIES || {}).capabilities) || [];
  const providerHealth = window.OMNI_PROVIDER_HEALTH || {};
  const budgets = ((window.OMNI_BUDGETS || {}).budgets) || [];
  const usage = window.OMNI_USAGE || {};
  const approvals = ((window.OMNI_APPROVALS || {}).approvals) || [];
  const [cred, setCred] = uS({ provider: 'youtube', account_id: '', secret: '', scopes: 'upload' });
  const [offer, setOffer] = uS({
    offer_id: '',
    name: '',
    network: '',
    url: '',
    niches: 'health',
    commission_type: 'cpa',
    commission_value: '0',
  });
  const [budget, setBudget] = uS({ scope: 'channel', scope_id: 'beat_glp1_nausea', limit_usd: '5' });
  const [credCapability, setCredCapability] = uS('');
  const credentialProviders = capabilities.map(c => {
    const metadata = c.metadata || {};
    const schema = metadata.config_schema || {};
    const schemaFields = Object.values(schema);
    const providerField = schemaFields.find(f => f && f.provider);
    return {
      key: c.capability_id,
      kind: c.kind,
      provider: providerField ? providerField.provider : c.provider_id,
      provider_id: c.provider_id,
      label: c.kind + ':' + c.provider_id,
      requiresCredential: !!metadata.requires_credential,
      schema,
    };
  }).filter(p => p.requiresCredential || Object.keys(p.schema).length);
  const rec = readiness.recommendation || 'wait';
  const recClass = rec === 'ship' ? 'green' : rec === 'reject' ? 'red' : 'amber';
  const saveCred = () => {
    if (!cred.provider || !cred.account_id || !cred.secret) return window._toast('Provider, account và secret là bắt buộc', false);
    return window.OmniActions.storeCredential({
      provider: cred.provider,
      account_id: cred.account_id,
      secret: cred.secret,
      scopes: cred.scopes.split(',').map(s => s.trim()).filter(Boolean),
    }).then(() => setCred({ ...cred, secret: '' }));
  };
  const saveOffer = () => {
    if (!offer.offer_id || !offer.name || !offer.url) return window._toast('Offer ID, tên và URL là bắt buộc', false);
    return window.OmniActions.saveOffer({
      offer_id: offer.offer_id,
      name: offer.name,
      network: offer.network,
      url: offer.url,
      niches: offer.niches.split(',').map(s => s.trim()).filter(Boolean),
      commission_type: offer.commission_type,
      commission_value: parseFloat(offer.commission_value || '0'),
    });
  };
  const saveBudget = () => {
    if (!budget.scope || !budget.scope_id) return window._toast('Scope và scope_id là bắt buộc', false);
    return window.OmniActions.saveBudget({
      scope: budget.scope,
      scope_id: budget.scope_id,
      limit_usd: parseFloat(budget.limit_usd || '0'),
    });
  };
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div className="page-title">Kiếm tiền</div>
          <div className="page-desc">Readiness, affiliate offers, credential vault và đa nền tảng</div>
        </div>
        <button className="btn btn-primary" onClick={() => window.OmniActions.refreshMonetization()}>{I.bolt} Kiểm tra lại</button>
      </div>

      <div className="grid g4 mb24">
        <div className="kpi"><div className="kpi-label">Khuyến nghị</div><div className={`kpi-val text-${recClass}`}>{rec.toUpperCase()}</div><div className="kpi-sub">score {readiness.score || 0}%</div></div>
        <div className="kpi"><div className="kpi-label">Nền tảng</div><div className="kpi-val text-blue">{platforms.length}</div><div className="kpi-sub">{(readiness.platform_ids || []).join(', ') || 'đang tải'}</div></div>
        <div className="kpi"><div className="kpi-label">Credential mã hoá</div><div className={`kpi-val text-${credentials.some(c => c.encrypted) ? 'green' : 'amber'}`}>{credentials.filter(c => c.encrypted).length}</div><div className="kpi-sub">{credentials.length} credential trong vault</div></div>
        <div className="kpi"><div className="kpi-label">Offer active</div><div className={`kpi-val text-${offers.length ? 'green' : 'amber'}`}>{offers.length}</div><div className="kpi-sub">{blockers.length} blocker còn lại</div></div>
      </div>

      <div className="grid g3 mb24">
        <div className="kpi"><div className="kpi-label">Capabilities</div><div className="kpi-val text-blue">{capabilities.length}</div><div className="kpi-sub">registry unified</div></div>
        <div className="kpi"><div className="kpi-label">Budgets</div><div className={`kpi-val text-${budgets.length ? 'green' : 'amber'}`}>{budgets.length}</div><div className="kpi-sub">persistent guard</div></div>
        <div className="kpi"><div className="kpi-label">Usage ledger</div><div className="kpi-val">${Number(usage.cost_usd || 0).toFixed(2)}</div><div className="kpi-sub">{usage.total || 0} usage records</div></div>
      </div>

      <div className="grid g2 mb24">
        <div className="card pad-lg">
          <div className="card-hd"><div><div className="card-title">Readiness checklist</div><div className="card-sub">public + monetized publish gate</div></div></div>
          {checks.map((c, i) => (
            <div key={i} className="mrow">
              <span className="mlabel">{c.passed ? '✓' : '!' } {c.name}</span>
              <span className={`mval text-${c.passed ? 'green' : 'amber'}`}>{c.evidence}</span>
            </div>
          ))}
          {!checks.length && <div style={{ color: 'var(--text3)', fontSize: 13 }}>Đang tải readiness...</div>}
        </div>
        <div className="card pad-lg">
          <div className="card-hd"><div><div className="card-title">Blockers</div><div className="card-sub">phải xử lý trước khi bật kiếm tiền</div></div></div>
          {!blockers.length && <div style={{ color: 'var(--green)', fontSize: 13 }}>Không còn blocker bắt buộc</div>}
          {blockers.map((b, i) => (
            <div key={i} className="topic-row">
              <div className="topic-main"><div className="topic-title">{b.name}</div><div className="topic-sub">{b.evidence}</div></div>
              <span className="tag amber">WAIT</span>
            </div>
          ))}
        </div>
      </div>

      <div className="card pad-lg mb24">
        <div className="card-hd"><div><div className="card-title">Approval Queue</div><div className="card-sub">publish jobs waiting for HITL approval</div></div></div>
        {window.OMNI_APPROVALS === undefined ? (
          <Skeleton h="120px" />
        ) : (!approvals || approvals.length === 0) ? (
          <EmptyState
            icon={<Icon name="film" size={32} />}
            title="Chưa có video chờ duyệt"
            desc='Render xong một video rồi bấm "Gửi duyệt đăng" ở tab Sản xuất Video — video sẽ xuất hiện ở đây để bạn duyệt trước khi đăng.'
            actionLabel="Đi tới Sản xuất Video"
            onAction={() => window.__omniSetTab ? window.__omniSetTab('produce') : null}
          />
        ) : (
          approvals.map(a => (
            <ApprovalCard key={a.approval_id} a={a} />
          ))
        )}
      </div>

      <div className="grid g2 mb24">
        <div className="card pad-lg">
          <div className="card-hd"><div><div className="card-title">Destinations</div><div className="card-sub">channel targets</div></div></div>
          {window.OMNI_DESTINATIONS === undefined ? (
            <Skeleton h="120px" />
          ) : (!destinations || destinations.length === 0) ? (
            <EmptyState
              icon={<Icon name="tv" size={32} />}
              title="Kênh chưa có đích đăng nào bật"
              desc="Bật destination trong file cấu hình kênh để đăng đa nền tảng."
            />
          ) : (
            destinations.map((d, i) => (
              <div key={i} className="topic-row">
                <div className="topic-main"><div className="topic-title">{d.channel_name || d.channel_id}</div><div className="topic-sub">{d.platform_id} · {d.format_variant} · {d.enabled ? 'enabled' : 'disabled'}</div></div>
                <span className={`tag ${d.approval_required ? 'amber' : 'green'}`}>{d.approval_required ? 'approval' : 'auto'}</span>
              </div>
            ))
          )}
        </div>
        <div className="card pad-lg">
          <div className="card-hd"><div><div className="card-title">Platforms</div><div className="card-sub">official API contracts</div></div></div>
          {platforms.map(p => (
            <div key={p.platform_id} className="mrow">
              <span className="mlabel">{p.name}</span>
              <span className="mval">{p.format_spec.aspect_ratio} · {p.format_spec.width}x{p.format_spec.height}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="mb24">
        <div className="card pad-lg">
          <div className="card-hd"><div><div className="card-title">Affiliate offers</div><div className="card-sub">active offer để inject CTA/disclosure</div></div></div>
          <div className="grid g3" style={{ gap: 8 }}>
            <input className="field" value={offer.offer_id} onChange={e => setOffer({ ...offer, offer_id: e.target.value })} placeholder="Offer ID (e.g. amazon_kindle)" />
            <input className="field" value={offer.name} onChange={e => setOffer({ ...offer, name: e.target.value })} placeholder="Tên Offer" />
            <input className="field" value={offer.url} onChange={e => setOffer({ ...offer, url: e.target.value })} placeholder="URL Affiliate" />
          </div>
          <div className="grid g3" style={{ gap: 8, marginTop: 8 }}>
            <input className="field" value={offer.niches} onChange={e => setOffer({ ...offer, niches: e.target.value })} placeholder="Niches (ngăn cách bằng dấu phẩy)" />
            <input className="field" value={offer.network} onChange={e => setOffer({ ...offer, network: e.target.value })} placeholder="Mạng lưới (Network)" />
            <select className="field" value={offer.commission_type} onChange={e => setOffer({ ...offer, commission_type: e.target.value })}>
              <option value="cpa">CPA (Giá mỗi hành động)</option>
              <option value="cps">CPS (Giá mỗi lượt bán)</option>
              <option value="cpc">CPC (Giá mỗi lượt click)</option>
              <option value="cpm">CPM (Giá mỗi 1000 hiển thị)</option>
              <option value="revenue_share">Chia sẻ doanh thu</option>
              <option value="flat">Cố định (Flat)</option>
            </select>
          </div>
          <div style={{ marginTop: 8 }}>
            <label style={{ fontSize: 12, color: 'var(--text2)', fontWeight: 600, display: 'block', marginBottom: 4 }}>Giá trị hoa hồng</label>
            <input className="field" value={offer.commission_value} onChange={e => setOffer({ ...offer, commission_value: e.target.value })} placeholder="Giá trị hoa hồng (e.g. 5.50 hoặc 0.10 cho 10%)" />
            <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 2 }}>Nhập số tiền cố định bằng USD hoặc tỉ lệ phần trăm chia sẻ (từ 0.0 đến 1.0).</div>
          </div>
          <button className="btn btn-primary sm" style={{ marginTop: 10 }} onClick={saveOffer}>Lưu offer</button>
          <div style={{ marginTop: 12 }}>
            {window.OMNI_OFFERS === undefined ? (
              <Skeleton h="60px" />
            ) : (!offers || offers.length === 0) ? (
              <EmptyState
                icon={<Icon name="wallet" size={32} />}
                title="Chưa cấu hình affiliate offer"
                desc="Thêm offer (link + commission) để hệ thống tự chèn link kiếm tiền vào mô tả video."
                actionLabel="Thêm offer"
                onAction={() => {
                  const input = document.querySelector('input[placeholder="offer_id"]');
                  if (input) input.focus();
                }}
              />
            ) : (
              offers.map(o => <div key={o.offer_id} className="mrow"><span className="mlabel">{o.name}</span><span className="mval">{o.network || 'direct'} · {o.status}</span></div>)
            )}
          </div>
          {window.RevenueAnalyticsChart && React.createElement(window.RevenueAnalyticsChart)}
        </div>
      </div>

      <div className="mb24">
        <div className="card pad-lg">
          <div className="card-hd"><div><div className="card-title">Budgets</div><div className="card-sub">global / campaign / channel kill-switch</div></div></div>
          <div className="grid g3" style={{ gap: 8 }}>
            <select className="field" value={budget.scope} onChange={e => setBudget({ ...budget, scope: e.target.value })}>
              <option value="global">global</option>
              <option value="campaign">campaign</option>
              <option value="channel">channel</option>
            </select>
            <input className="field" value={budget.scope_id} onChange={e => setBudget({ ...budget, scope_id: e.target.value })} placeholder="scope_id" />
            <input className="field" value={budget.limit_usd} onChange={e => setBudget({ ...budget, limit_usd: e.target.value })} placeholder="limit_usd" />
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
            <button className="btn btn-primary sm" onClick={saveBudget}>Lưu budget</button>
            <button className="btn sm" onClick={() => window.OmniActions.systemPause()}>Pause all</button>
            <button className="btn sm" onClick={() => window.OmniActions.systemResume()}>Resume</button>
          </div>
          <div style={{ marginTop: 12 }}>
            {budgets.map(b => <div key={b.budget_id} className="mrow"><span className="mlabel">{b.scope}:{b.scope_id}</span><span className="mval">${Number(b.spent_usd || 0).toFixed(2)} / ${Number(b.limit_usd || 0).toFixed(2)}</span></div>)}
            {!budgets.length && <div style={{ color: 'var(--text3)', fontSize: 13 }}>Chưa có budget guard nào</div>}
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { RightPanel, Dashboard, Channels, Scripts, NicheVault, Scheduler, Policy, Infrastructure, Budget, Monetization, Providers, RevenueAnalyticsChart });
/* ---------- PROVIDERS & APIs ---------- */
function Providers() {
  const credentials = ((window.OMNI_CREDENTIALS || {}).credentials) || [];
  const capabilities = ((window.OMNI_CAPABILITIES || {}).capabilities) || [];
  const providerHealth = window.OMNI_PROVIDER_HEALTH || {};
  const [cred, setCred] = uS({ provider: '', account_id: '', secret: '', scopes: '' });
  const [credCapability, setCredCapability] = uS('');
  const [credConfigValues, setCredConfigValues] = uS({});

  const credentialProviders = capabilities.map(c => {
    const metadata = c.metadata || {};
    const schema = metadata.config_schema || {};
    return {
      key: c.capability_id,
      kind: c.kind,
      provider: c.provider_id,
      provider_id: c.provider_id,
      label: c.kind + ':' + c.provider_id,
      requiresCredential: !!metadata.requires_credential,
      schema,
    };
  }).filter(p => p.requiresCredential || Object.keys(p.schema).length);

  const saveCred = () => {
    const activePreset = credentialProviders.find(p => p.key === credCapability);
    const hasSchema = activePreset && Object.keys(activePreset.schema).length > 0;
    
    const secretVal = hasSchema ? JSON.stringify(credConfigValues) : cred.secret;
    const finalCred = {
      provider: cred.provider,
      account_id: cred.account_id,
      secret: secretVal,
      scopes: cred.scopes.split(',').map(s => s.trim()).filter(Boolean),
    };

    if (!finalCred.provider || !finalCred.account_id || !finalCred.secret) {
      return window._toast('Provider, account và secret/config là bắt buộc', false);
    }

    return window.OmniActions.storeCredential(finalCred).then(() => {
      setCred({ provider: '', account_id: '', secret: '', scopes: '' });
      setCredCapability('');
      setCredConfigValues({});
      window._toast('Lưu credential thành công', true);
    });
  };

  const activePreset = credentialProviders.find(p => p.key === credCapability);

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10, marginBottom: 20 }}>
        <div>
          <div className="page-title">Providers</div>
          <div className="page-desc">Quản lý Credentials, Capabilities, Health tests và Usage logs</div>
        </div>
        <button className="btn btn-primary" onClick={() => window.OmniActions.refreshMonetization()}>{I.bolt} Refresh</button>
      </div>

      <div className="grid g2 mb24">
        {/* Credential Form & Vault */}
        <div className="card pad-lg">
          <div className="card-hd"><div><div className="card-title">Credential vault</div><div className="card-sub">Cấu hình kết nối API bảo mật</div></div></div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {credentialProviders.length > 0 && (
              <div>
                <label style={{ fontSize: 12, color: 'var(--text2)', display: 'block', marginBottom: 4 }}>Preset cấu hình</label>
                <select className="field" value={credCapability} onChange={e => {
                  const selected = credentialProviders.find(p => p.key === e.target.value);
                  setCredCapability(e.target.value);
                  if (selected) {
                    setCred({ provider: selected.provider, account_id: '', secret: '', scopes: selected.kind });
                    setCredConfigValues({});
                  } else {
                    setCred({ provider: '', account_id: '', secret: '', scopes: '' });
                    setCredConfigValues({});
                  }
                }}>
                  <option value="">Tự nhập preset...</option>
                  {credentialProviders.map(p => (
                    <option key={p.key} value={p.key}>{p.label}</option>
                  ))}
                </select>
              </div>
            )}
            
            <div className="grid g2" style={{ gap: 8 }}>
              <div>
                <label style={{ fontSize: 12, color: 'var(--text2)', display: 'block', marginBottom: 4 }}>Provider ID</label>
                <input className="field" value={cred.provider} onChange={e => setCred({ ...cred, provider: e.target.value })} placeholder="e.g. youtube, openai" />
              </div>
              <div>
                <label style={{ fontSize: 12, color: 'var(--text2)', display: 'block', marginBottom: 4 }}>Account/Client ID</label>
                <input className="field" value={cred.account_id} onChange={e => setCred({ ...cred, account_id: e.target.value })} placeholder="e.g. developer, default" />
              </div>
            </div>

            {/* Dynamic Schema Fields */}
            {activePreset && Object.keys(activePreset.schema).length > 0 ? (
              <div style={{ background: 'var(--surface2)', padding: 12, borderRadius: 'var(--r-sm)', marginTop: 4 }}>
                <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8, color: 'var(--text2)' }}>Cấu hình schema chi tiết</div>
                {Object.entries(activePreset.schema).map(([key, field]) => {
                  const f = typeof field === 'object' ? field : { name: key, label: key, type: 'text' };
                  const label = f.label || f.name || key;
                  const description = f.description || '';
                  const required = !!f.required;
                  const type = f.type || 'text';
                  return (
                    <div key={key} style={{ marginBottom: 10 }}>
                      <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>
                        {label} {required && <span style={{ color: 'var(--red)' }}>*</span>}
                      </label>
                      {type === 'select' ? (
                        <select
                          className="field"
                          value={credConfigValues[key] || f.default || ''}
                          onChange={e => setCredConfigValues({ ...credConfigValues, [key]: e.target.value })}
                        >
                          {(f.options || []).map(opt => (
                            <option key={opt} value={opt}>{opt}</option>
                          ))}
                        </select>
                      ) : (
                        <input
                          className="field"
                          type={type === 'password' ? 'password' : 'text'}
                          placeholder={description || label}
                          value={credConfigValues[key] || f.default || ''}
                          onChange={e => setCredConfigValues({ ...credConfigValues, [key]: e.target.value })}
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            ) : (
              <div>
                <label style={{ fontSize: 12, color: 'var(--text2)', display: 'block', marginBottom: 4 }}>API Key / Secret Token</label>
                <input className="field" value={cred.secret} onChange={e => setCred({ ...cred, secret: e.target.value })} placeholder="secret api key..." type="password" />
              </div>
            )}

            <div>
              <label style={{ fontSize: 12, color: 'var(--text2)', display: 'block', marginBottom: 4 }}>Scopes (ngăn cách bởi dấu phẩy)</label>
              <input className="field" value={cred.scopes} onChange={e => setCred({ ...cred, scopes: e.target.value })} placeholder="e.g. upload, render" />
            </div>
          </div>
          <button className="btn btn-primary sm" style={{ marginTop: 12 }} onClick={saveCred}>Lưu credential</button>
        </div>

        {/* Credentials table */}
        <div className="card pad-lg">
          <div className="card-hd"><div><div className="card-title">Credentials quản lý</div><div className="card-sub">Trạng thái bảo mật & test kết nối</div></div></div>
          {window.OMNI_CREDENTIALS === undefined ? (
            <Skeleton h="120px" />
          ) : credentials.length === 0 ? (
            <EmptyState icon={<Icon name="shield" size={32} />} title="Không có credential nào" desc="Bắt đầu thêm credentials preset hoặc custom để kết nối API ngoài." />
          ) : (
            <table className="mini-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)', textAlign: 'left' }}>
                  <th style={{ padding: 8 }}>Đối tác & Account</th>
                  <th style={{ padding: 8 }}>Mã hóa</th>
                  <th style={{ padding: 8 }}>Health</th>
                  <th style={{ padding: 8, textAlign: 'right' }}>Thao tác</th>
                </tr>
              </thead>
              <tbody>
                {credentials.map(c => {
                  const healthKey = c.provider;
                  const health = providerHealth[healthKey] || providerHealth[c.scopes?.[0] + ':' + c.provider];
                  const healthOk = health && health.ok !== false;
                  const healthLabel = health ? (healthOk ? 'ok' : 'error') : 'chưa test';
                  const healthTone = health ? (healthOk ? 'green' : 'red') : 'amber';
                  
                  return (
                    <tr key={c.credential_id} style={{ borderBottom: '1px solid var(--border-light)' }}>
                      <td style={{ padding: 8, fontWeight: 500 }}>
                        {c.provider} <span style={{ color: 'var(--text3)', fontWeight: 400 }}>({c.account_id})</span>
                      </td>
                      <td style={{ padding: 8 }}>
                        <span className={`text-${c.encrypted ? 'green' : 'amber'}`}>{c.encrypted ? 'Mã hóa' : 'Mở'}</span>
                      </td>
                      <td style={{ padding: 8 }}>
                        <span className={`tag ${healthTone}`}>{healthLabel}</span>
                      </td>
                      <td style={{ padding: 8, textAlign: 'right' }}>
                        <button className="btn sm" onClick={() => {
                          const matchedCap = capabilities.find(cap => cap.provider_id === c.provider);
                          const kind = matchedCap ? matchedCap.kind : (c.scopes?.[0] || 'publisher');
                          window.OmniActions.testCapability(kind, c.provider);
                        }}>Test</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Capability registry & usage */}
      <div className="card pad-lg mb24">
        <div className="card-hd"><div><div className="card-title">Capability registry & Usage logs</div><div className="card-sub">Registry các API tích hợp và nhật ký usage</div></div></div>
        {window.OMNI_CAPABILITIES === undefined ? (
          <Skeleton h="120px" />
        ) : capabilities.length === 0 ? (
          <EmptyState icon={<Icon name="server" size={32} />} title="Không có capability nào" desc="Báo cáo capability từ server rỗng. Kiểm tra kết nối backend." />
        ) : (
          <div className="grid g2" style={{ gap: 16 }}>
            {capabilities.map(c => {
              const health = providerHealth[c.capability_id] || providerHealth[c.kind + ':' + c.provider_id];
              const healthOk = health && health.ok !== false;
              const healthLabel = health ? (healthOk ? 'ok' : 'error') : 'untested';
              const healthTone = health ? (healthOk ? 'green' : 'red') : 'amber';

              // Filter usage records for this capability / provider
              const capabilityUsage = (window.OMNI_USAGE?.usage || []).filter(u => u.provider_id === c.provider_id);
              const totalCost = capabilityUsage.reduce((sum, u) => sum + (u.cost_usd || 0), 0);
              const totalCalls = capabilityUsage.length;

              return (
                <div key={c.capability_id} className="card pad-md" style={{ background: 'var(--surface2)', border: '1px solid var(--border-light)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                    <span style={{ fontWeight: 700, fontSize: 13.5 }}>{c.kind}:{c.provider_id}</span>
                    <span className={`tag ${healthTone}`}>{healthLabel}</span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text3)', marginBottom: 8 }}>
                    Runtime: {c.runtime} · Model: {c.model_id || '-'}
                  </div>
                  <button className="btn sm mb12" style={{ width: '100%' }} onClick={() => window.OmniActions.testCapability(c.kind, c.provider_id, c.capability_id)}>Test Capability</button>
                  
                  {/* Usage Table */}
                  <div style={{ borderTop: '1px solid var(--border-light)', paddingTop: 8 }}>
                    <div style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--text2)', marginBottom: 4 }}>Bản ghi Usage (Tổng: ${totalCost.toFixed(4)})</div>
                    {capabilityUsage.length === 0 ? (
                      <div style={{ fontSize: 11, color: 'var(--text3)', fontStyle: 'italic', padding: '4px 0' }}>Chưa có usage nào được ghi</div>
                    ) : (
                      <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
                        <thead>
                          <tr style={{ borderBottom: '1px solid var(--border-light)', textAlign: 'left', color: 'var(--text3)' }}>
                            <th style={{ padding: '2px 0' }}>Thời gian</th>
                            <th style={{ padding: '2px 0' }}>Scope</th>
                            <th style={{ padding: '2px 0', textAlign: 'right' }}>Cost</th>
                          </tr>
                        </thead>
                        <tbody>
                          {capabilityUsage.slice(0, 3).map((u, i) => (
                            <tr key={i}>
                              <td style={{ padding: '2px 0', color: 'var(--text3)' }}>
                                {u.created_at ? new Date(u.created_at).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' }) : ''}
                              </td>
                              <td style={{ padding: '2px 0' }}>{u.scope}:{u.scope_id}</td>
                              <td style={{ padding: '2px 0', textAlign: 'right', fontWeight: 600 }}>${Number(u.cost_usd || 0).toFixed(4)}</td>
                            </tr>
                          ))}
                          {capabilityUsage.length > 3 && (
                            <tr>
                              <td colSpan="3" style={{ padding: '2px 0', textAlign: 'center', color: 'var(--text3)', fontSize: 10 }}>
                                và {capabilityUsage.length - 3} bản ghi khác ({totalCalls} lần gọi)
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
function RevenueAnalyticsChart() {
  const data = [
    { niche: 'AI Productivity', lastMonth: 240, thisMonth: 410, color: 'hsl(142, 70%, 45%)' },
    { niche: 'Quantum Sci', lastMonth: 180, thisMonth: 320, color: 'hsl(217, 91%, 60%)' },
    { niche: 'Stoic Philosophy', lastMonth: 110, thisMonth: 190, color: 'hsl(271, 91%, 65%)' },
    { niche: 'Deep Sea', lastMonth: 90, thisMonth: 150, color: 'hsl(32, 98%, 50%)' },
  ];

  const width = 500;
  const height = 180;
  const paddingLeft = 110;
  const paddingRight = 20;
  const paddingTop = 10;
  const paddingBottom = 20;

  const chartWidth = width - paddingLeft - paddingRight;
  const chartHeight = height - paddingTop - paddingBottom;
  const maxVal = 500;

  return (
    <div style={{ marginTop: 24, padding: 16, background: 'var(--surface2)', borderRadius: 'var(--r-md)', border: '1px solid var(--border-light)' }}>
      <div style={{ fontWeight: 700, fontSize: 13.5, marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>Phân tích doanh thu ước tính theo ngách (USD)</span>
        <div style={{ display: 'flex', gap: 12, fontSize: 11.5, fontWeight: 400 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 8, height: 8, background: 'var(--text3)', borderRadius: '50%' }}></span>Tháng trước
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 8, height: 8, background: 'hsl(142, 72%, 29%)', borderRadius: '50%' }}></span>Tháng này
          </span>
        </div>
      </div>
      
      <div style={{ overflowX: 'auto' }}>
        <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} style={{ minWidth: 400, display: 'block' }}>
          {[0, 0.25, 0.5, 0.75, 1].map((p, idx) => {
            const x = paddingLeft + p * chartWidth;
            return (
              <g key={idx}>
                <line x1={x} y1={paddingTop} x2={x} y2={height - paddingBottom} stroke="var(--border-light)" strokeDasharray="3,3" />
                <text x={x} y={height - 4} fill="var(--text3)" fontSize="9" textAnchor="middle">${p * maxVal}</text>
              </g>
            );
          })}

          {data.map((item, idx) => {
            const barSpacing = chartHeight / data.length;
            const y = paddingTop + idx * barSpacing + 4;
            const lastMonthWidth = (item.lastMonth / maxVal) * chartWidth;
            const thisMonthWidth = (item.thisMonth / maxVal) * chartWidth;
            const barHeight = 12;

            return (
              <g key={idx}>
                <text x={paddingLeft - 8} y={y + 12} fill="var(--text2)" fontSize="11" fontWeight="600" textAnchor="end">{item.niche}</text>
                <rect x={paddingLeft} y={y} width={lastMonthWidth} height={barHeight} fill="var(--border)" rx="2" />
                <rect x={paddingLeft} y={y + 14} width={thisMonthWidth} height={barHeight} fill={item.color} rx="2" />
                <text x={paddingLeft + thisMonthWidth + 6} y={y + 24} fill="var(--text)" fontSize="10" fontWeight="700">${item.thisMonth}</text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
