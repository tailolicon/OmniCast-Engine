import React, { useState, useEffect, useCallback, useRef  } from 'react';

const API = 'http://127.0.0.1:8767';

// ── API hook ──────────────────────────────────────────────────────────────────
// Module-level cache + in-flight dedup: prevents the "empty state flicker"
// when a page component remounts on tab switch. Subsequent useApi calls for
// the same endpoint render the last known payload immediately, then refresh
// in the background.
const _apiCache = {};      // endpoint -> last JSON payload
const _apiInflight = {};   // endpoint -> Promise (dedup concurrent fetches)

function useApi(endpoint, intervalMs = 0) {
    const cached = _apiCache[endpoint] ?? null;
    const [data, setData] = useState(cached);
    const [loading, setLoading] = useState(cached === null);
    const [error, setError] = useState(null);

    const fetch_ = useCallback(async () => {
        try {
            // Dedup: if a fetch for this endpoint is already in flight,
            // await its result instead of issuing a duplicate request.
            let promise = _apiInflight[endpoint];
            if (!promise) {
                promise = (async () => {
                    const r = await fetch(API + endpoint);
                    if (!r.ok) throw new Error(`HTTP ${r.status}`);
                    return await r.json();
                })();
                _apiInflight[endpoint] = promise;
                promise.finally(() => { delete _apiInflight[endpoint]; });
            }
            const json = await promise;
            _apiCache[endpoint] = json;
            setData(json);
            setError(null);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    }, [endpoint]);

    useEffect(() => {
        fetch_();
        if (intervalMs > 0) {
            const id = setInterval(fetch_, intervalMs);
            return () => clearInterval(id);
        }
    }, [fetch_, intervalMs]);

    return { data, loading, error, refetch: fetch_ };
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const nicheColor = c => ({ finance: 'green', health: 'blue', history: 'amber', technology: 'purple', lifestyle: 'amber' }[c] || 'purple');
const statusColor = s => {
    if (!s || s === 'idle') return 'green';
    if (s.includes('running')) return 'amber';
    if (s === 'error') return 'red';
    return 'blue';
};
const fmt = n => n === undefined || n === null ? '—' : n;

// ── Icons (SVG strings) ───────────────────────────────────────────────────────
const Ico = {
    home:    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9,22 9,12 15,12 15,22"/></svg>,
    pipe:    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="5" height="5" rx="1"/><rect x="10" y="3" width="5" height="5" rx="1"/><rect x="17" y="3" width="5" height="5" rx="1"/><rect x="3" y="10" width="5" height="5" rx="1"/><rect x="10" y="10" width="5" height="5" rx="1"/></svg>,
    channel: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="7" width="20" height="15" rx="2"/><polyline points="17,2 12,7 7,2"/></svg>,
    niche:   <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>,
    budget:  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>,
    vault:   <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="12" cy="12" r="3"/><path d="M12 9V7M12 17v-2M9 12H7M17 12h-2M10.17 10.17l-1.42-1.42M15.25 15.25l-1.42-1.42M13.83 10.17l1.42-1.42M8.75 15.25l1.42-1.42"/></svg>,
    refresh: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="23,4 23,10 17,10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>,
    play:    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5,3 19,12 5,21"/></svg>,
    up:      <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polyline points="18,15 12,9 6,15"/></svg>,
    bolt:    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="13,2 3,14 12,14 11,22 21,10 12,10"/></svg>,
    save:    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/><polyline points="17,21 17,13 7,13 7,21"/><polyline points="7,3 7,8 15,8"/></svg>,
    bulb:    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 18h6M10 22h4M12 2a7 7 0 00-4 12.7c.7.5 1 1.3 1 2.1V18h6v-1.2c0-.8.3-1.6 1-2.1A7 7 0 0012 2z"/></svg>,
    tv:      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="7" width="20" height="15" rx="2"/><polyline points="17,2 12,7 7,2"/></svg>,
    inbox:   <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><polyline points="22,12 16,12 14,15 10,15 8,12 2,12"/><path d="M5.45 5.11L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6l-3.45-6.89A2 2 0 0016.76 4H7.24a2 2 0 00-1.79 1.11z"/></svg>,
    target:  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>,
    archive: <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><polyline points="21,8 21,21 3,21 3,8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/></svg>,
    infra:   <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="3" width="20" height="5" rx="1"/><rect x="2" y="10" width="20" height="5" rx="1"/><rect x="2" y="17" width="20" height="5" rx="1"/><line x1="6" y1="5.5" x2="6.01" y2="5.5"/><line x1="6" y1="12.5" x2="6.01" y2="12.5"/><line x1="6" y1="19.5" x2="6.01" y2="19.5"/></svg>,
    cpu:     <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/></svg>,
    heart:   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 000-7.78z"/></svg>,
    stop:    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>,
};

// ── KillSwitchPill — topbar paused-state indicator (rule #2: always inescapable) ────
function KillSwitchPill({ setTab }) {
    const { data } = useApi('/api/system/state', 4000);
    const payload = data?.data;
    if (!payload) return null;
    // Visibly surface 3 distinct states the operator must distinguish:
    if (!payload.redis_available) {
        return (
            <div className="status-pill error" title="Redis unreachable — kill-switch state cannot be read or enforced">
                <span className="dot"/>
                <span>Kill-switch: unknown</span>
            </div>
        );
    }
    if (payload.paused) {
        const since = (payload.paused_since || '').slice(11, 19);
        return (
            <button className="status-pill error"
                    style={{border:'none',cursor:'pointer',animation:'pulse 1.2s infinite'}}
                    onClick={() => setTab && setTab('infra')}
                    title="Pipeline paused. Click to view Infrastructure.">
                <span className="dot"/>
                <span>PAUSED since {since} UTC</span>
            </button>
        );
    }
    return null; // running normally — the default status-pill covers this
}

// ── fmtSecs — format "45s" / "2m 15s" / "1h 5m" ──────────────────────────────
function fmtSecs(s) {
    if (s === null || s === undefined || isNaN(s)) return '';
    if (s < 0) s = 0;
    if (s < 60)   return `${s}s`;
    if (s < 3600) return `${Math.floor(s/60)}m ${s%60}s`;
    return `${Math.floor(s/3600)}h ${Math.floor((s%3600)/60)}m`;
}

// ── ActiveJobCard — operator visibility for long-running background tasks ────
function ActiveJobCard({ job, title, defaultStage }) {
    const [showHistory, setShowHistory] = useState(false);
    const stage = job.stage || defaultStage || job.phase || 'Starting…';
    const pct = typeof job.progress_pct === 'number' ? job.progress_pct : null;
    const detail = job.detail || '';

    // Prefer server-computed elapsed/eta; fall back to client-derived elapsed if missing.
    let elapsed = job.elapsed_seconds;
    if ((elapsed === null || elapsed === undefined) && job.started_at) {
        try {
            elapsed = Math.floor((Date.now() - new Date(job.started_at + 'Z')) / 1000);
        } catch { /* ignore */ }
    }
    const eta = job.eta_seconds;
    const history = Array.isArray(job.stage_history) ? job.stage_history : [];

    return (
        <div style={{background:'var(--surface)', border:'1px solid var(--border)', borderRadius:'var(--r-md)', padding:'14px 16px'}}>
            <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:6}}>
                <span className="spinner"/>
                <span style={{fontSize:13,fontWeight:700,color:'var(--text)'}}>{title || job.channel_id}</span>
                <span style={{marginLeft:'auto',display:'flex',gap:10,fontSize:11,color:'var(--text3)',fontFamily:'monospace'}}>
                    {elapsed !== null && elapsed !== undefined && <span title="Time since job started">⏱ {fmtSecs(elapsed)}</span>}
                    {eta !== null && eta !== undefined && <span style={{color:'var(--amber)'}} title="Estimated time remaining (linear extrapolation from current progress)">ETA ~{fmtSecs(eta)}</span>}
                </span>
            </div>
            <div style={{fontSize:12,color:'var(--blue)',fontWeight:600,marginBottom:2}}>{stage}</div>
            {detail && <div style={{fontSize:11,color:'var(--text3)',marginBottom:8,lineHeight:1.4}}>{detail}</div>}
            {pct !== null && (
                <div className="progress" style={{height:5}}>
                    <div className="progress-fill blue" style={{width:`${pct}%`}}/>
                </div>
            )}
            {pct !== null && (
                <div style={{fontSize:10,color:'var(--text3)',marginTop:4,textAlign:'right',fontFamily:'monospace'}}>{pct}%</div>
            )}

            {/* Stage history — collapsible audit trail of every stage transition */}
            {history.length > 0 && (
                <div style={{marginTop:10,borderTop:'1px dashed var(--border)',paddingTop:8}}>
                    <button
                        onClick={() => setShowHistory(!showHistory)}
                        style={{background:'none',border:'none',color:'var(--text3)',fontSize:10,cursor:'pointer',padding:0,fontFamily:'inherit'}}>
                        {showHistory ? '▼' : '▶'} Stage history ({history.length} step{history.length>1?'s':''})
                    </button>
                    {showHistory && (
                        <div style={{marginTop:6,fontSize:10,color:'var(--text3)',fontFamily:'monospace',lineHeight:1.6}}>
                            {history.map((h, i) => (
                                <div key={i} style={{display:'flex',gap:8}}>
                                    <span style={{color:'var(--text3)',width:60}}>{(h.at || '').slice(11,19)}</span>
                                    <span style={{color:'var(--blue)',width:40}}>{h.pct !== null && h.pct !== undefined ? h.pct + '%' : '—'}</span>
                                    <span style={{color:'var(--text2)'}}>{h.stage}</span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

// ── ErrorLogPanel — dashboard surface for background-task crashes (rule #4 No Blackbox) ──
function ErrorLogPanel({ limit = 5, title = 'Recent Errors', allowClear = false }) {
    const { data, error: apiError, refetch } = useApi(`/api/errors?limit=${limit}`, 6000);
    const [expanded, setExpanded] = useState(null);
    const [clearing, setClearing] = useState(false);

    const payload = data?.data;
    const errors  = payload?.errors || [];
    const total   = payload?.total || 0;

    const onClear = async () => {
        if (!confirm('Clear the error log? (an audit entry will record this action)')) return;
        setClearing(true);
        try {
            await fetch(API + '/api/errors/clear', { method: 'POST' });
            if (refetch) refetch();
        } catch { /* surfaced via OfflineBanner */ }
        setClearing(false);
    };

    return (
        <div className="card mb2">
            <div className="card-header">
                <div>
                    <div className="card-title" style={{display:'flex',alignItems:'center',gap:6}}>
                        <span style={{color: total > 0 ? 'var(--red)' : 'var(--text3)'}}>{Ico.bolt}</span>
                        {title}
                        {total > 0 && <span className="tag red" style={{fontSize:10}}>{total}</span>}
                    </div>
                    <div className="card-sub">
                        Polled every 6s — click an entry to expand the full Python traceback
                    </div>
                </div>
                {allowClear && total > 0 && (
                    <button className="btn btn-ghost btn-sm" onClick={onClear} disabled={clearing}>
                        {clearing ? <><span className="spinner"/> Clearing…</> : 'Clear log'}
                    </button>
                )}
            </div>

            {errors.length === 0 ? (
                <div className="empty" style={{padding:'24px 12px'}}>
                    <div style={{color:'var(--green)',marginBottom:6}}>✓ No recent errors</div>
                    <div style={{fontSize:11,color:'var(--text3)'}}>Background tasks have not raised since the last log clear.</div>
                </div>
            ) : (
                <div style={{display:'grid',gap:8}}>
                    {errors.map((e, i) => {
                        const isOpen = expanded === i;
                        const isAudit = e.channel_id === '__system__';
                        return (
                            <div key={i} style={{background:'var(--surface2)',border:`1px solid ${isAudit?'var(--border)':'var(--red-dim)'}`,borderRadius:6,padding:'10px 12px'}}>
                                <div
                                    style={{display:'flex',alignItems:'center',gap:8,cursor: isAudit ? 'default' : 'pointer'}}
                                    onClick={() => !isAudit && setExpanded(isOpen ? null : i)}>
                                    <span className={`tag ${isAudit ? 'purple' : 'red'}`} style={{fontSize:10}}>
                                        {isAudit ? 'AUDIT' : (e.phase || 'failed')}
                                    </span>
                                    <span style={{fontSize:12,fontWeight:600,color:'var(--text)'}}>
                                        {e.channel_id === '__niche_discovery__' ? 'Niche Discovery'
                                          : e.channel_id === '__system__' ? 'System'
                                          : e.channel_id}
                                    </span>
                                    {e.stage && (
                                        <span style={{fontSize:11,color:'var(--blue)'}}>at: {e.stage}</span>
                                    )}
                                    <span style={{marginLeft:'auto',fontSize:10,color:'var(--text3)',fontFamily:'monospace'}}>
                                        {(e.ts || '').slice(0,19).replace('T',' ')} UTC
                                    </span>
                                    {!isAudit && (
                                        <span style={{fontSize:10,color:'var(--text3)',marginLeft:6}}>{isOpen ? '▼' : '▶'}</span>
                                    )}
                                </div>
                                <div style={{fontSize:12,color: isAudit ? 'var(--text3)' : 'var(--red)',marginTop:4,fontFamily:'monospace',wordBreak:'break-word'}}>
                                    {e.message}
                                </div>
                                {isOpen && e.traceback && (
                                    <pre style={{marginTop:8,background:'var(--surface)',padding:10,borderRadius:4,fontSize:10,color:'var(--text2)',overflow:'auto',maxHeight:280,lineHeight:1.4,whiteSpace:'pre-wrap'}}>
{e.traceback}
                                    </pre>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

// ── Components ────────────────────────────────────────────────────────────────
function OfflineBanner({ error }) {
    if (!error) return null;
    return (
        <div className="offline-banner">
            ⚠ API offline — start server: <code style={{fontFamily:'monospace', background:'rgba(0,0,0,.3)', padding:'2px 6px', borderRadius:'4px'}}>
                python -m uvicorn omnicast.api.server:app --port 8765
            </code>
        </div>
    );
}

// ── Dashboard Home ─────────────────────────────────────────────────────────────
function DashboardHome() {
    const { data: status, error, loading } = useApi('/api/status', 5000);
    const { data: pipeline } = useApi('/api/pipeline', 5000);

    const kpis = status?.kpis || {};
    const recent = pipeline?.recent_results || [];
    const active = pipeline?.active_jobs || [];

    const spendPct = kpis.daily_cap_usd ? ((kpis.daily_spend_usd || 0) / kpis.daily_cap_usd * 100).toFixed(0) : 0;

    return (
        <div>
            <OfflineBanner error={error} />

            <div className="grid g4 mb2">
                <div className="kpi">
                    <div className="kpi-label">Active Runs</div>
                    <div className="kpi-val" style={{color: active.length > 0 ? 'var(--amber)' : 'var(--green)'}}>
                        {loading ? <span className="spinner"/> : active.length}
                    </div>
                    <div className="kpi-sub">{active.length > 0 ? active.map(j=>j.channel_id).join(', ') : 'All idle'}</div>
                </div>
                <div className="kpi">
                    <div className="kpi-label">Scripts Approved</div>
                    <div className="kpi-val">{loading ? '—' : (kpis.scripts_approved_today || 0)}</div>
                    <div className="kpi-sub">Today (score ≥ 70)</div>
                </div>
                <div className="kpi">
                    <div className="kpi-label">Daily Spend</div>
                    <div className="kpi-val" style={{fontSize:'28px'}}>${loading ? '—' : (kpis.daily_spend_usd || 0).toFixed(2)}</div>
                    <div className="kpi-sub">/ ${kpis.daily_cap_usd || 100} cap</div>
                    <div className="progress" style={{marginTop:'8px'}}>
                        <div className="progress-fill amber" style={{width: `${spendPct}%`}}/>
                    </div>
                </div>
                <div className="kpi">
                    <div className="kpi-label">Channels</div>
                    <div className="kpi-val">{loading ? '—' : (kpis.total_channels || 0)}</div>
                    <div className="kpi-sub up">{status?.system?.niches_discovered || 0} niches discovered</div>
                </div>
            </div>

            {/* Active jobs */}
            {active.length > 0 && (
                <div className="card mb2">
                    <div className="card-header">
                        <div>
                            <div className="card-title" style={{display:'flex',alignItems:'center',gap:6}}>
                                <span style={{color:'var(--amber)'}}>{Ico.bolt}</span>
                                Active Pipeline Jobs
                            </div>
                            <div className="card-sub">Running right now</div>
                        </div>
                    </div>
                    <div style={{display:'grid',gap:10}}>
                        {active.map((job, i) => (
                            <ActiveJobCard
                                key={i}
                                job={job}
                                title={job.channel_id === '__niche_discovery__' ? 'Niche Discovery' : job.channel_id}
                                defaultStage={job.phase === 'niche_scan' ? 'Scanning YouTube' : 'Discovery scan'}
                            />
                        ))}
                    </div>
                </div>
            )}

            {/* Recent errors — inescapable on the home page (rule #2) */}
            <ErrorLogPanel limit={5} title="Recent Errors" allowClear={false} />

            {/* Recent activity */}
            <div className="card mb2">
                <div className="card-header">
                    <div><div className="card-title">Recent Activity</div><div className="card-sub">Last pipeline events</div></div>
                </div>
                {recent.length === 0 ? (
                    <div className="empty"><div className="empty-icon" style={{color:'var(--text3)'}}>{Ico.inbox}</div>No activity yet — run a channel pipeline to see results</div>
                ) : recent.slice(0, 8).map((r, i) => (
                    <div key={i} className="row">
                        <div>
                            <div className="row-label" style={{fontWeight:600,color:'var(--text)'}}>{r.topic || r.channel_id}</div>
                            <div className="row-label"><small>{r.channel_id} • {r.phase} • {r.ts?.slice(0,19).replace('T',' ')}</small></div>
                        </div>
                        <div style={{display:'flex',alignItems:'center',gap:'8px'}}>
                            {r.score > 0 && <span style={{fontSize:'13px',fontWeight:700,color: r.score>=70?'var(--green)':'var(--amber)'}}>{r.score}/100</span>}
                            <span className={`tag ${r.status==='completed'?'green':r.status==='failed'?'red':'amber'}`}>{r.status}</span>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}

// ── Channels Master-Detail ─────────────────────────────────────────────────────────────
function ChannelEditor({ channelId, isNew, onSaved, onDeleted, triggerRun, triggerScript, cancelRun, running, liveStatus }) {
    const [formData, setFormData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (isNew) {
            setFormData({
                channel_id: '', name: '', niche: 'finance', sub_niche: '', market: 'US',
                visual_style: 'high_energy', voice_profile: 'kokoro_en_us_v1', brand_voice: '',
                tone: 'direct', hook_format: '', voice_persona: '', competitor_handles: [],
                audience: { age_range: '', gender_skew: '', income_level: '', pain_points: [], content_triggers: [], preferred_video_length_min: 10, engagement_drivers: [] },
                trends_keywords: [], subreddits: [], rpm_floor: 5.0, target_duration_min: 10,
                brand_color_hex: '#1A1A2E', font_vibe: 'sans_modern'
            });
            return;
        }
        
        if (channelId) {
            setLoading(true);
            fetch(`${API}/api/channels/${channelId}`)
                .then(r => r.json())
                .then(d => { setFormData(d); setLoading(false); })
                .catch(e => { console.error(e); setLoading(false); });
        }
    }, [channelId, isNew]);

    const handleSave = async () => {
        if (!formData.channel_id) return alert('Channel ID is required');
        setSaving(true);
        const method = isNew ? 'POST' : 'PUT';
        const url = isNew ? `${API}/api/channels` : `${API}/api/channels/${channelId}`;
        try {
            const r = await fetch(url, {
                method, headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(formData)
            });
            if (r.ok) {
                onSaved();
            } else {
                const err = await r.json();
                alert(`Error saving: ${err.detail}`);
            }
        } catch { alert('Failed to save. API offline?');
        }
        setSaving(false);
    };

    const handleDelete = async () => {
        if (!confirm('Are you sure you want to delete this channel? This cannot be undone.')) return;
        try {
            const r = await fetch(`${API}/api/channels/${channelId}`, { method: 'DELETE' });
            if (r.ok) onDeleted();
            else alert('Error deleting channel');
        } catch { alert('Failed to delete. API offline?');
        }
    };

    const handleChange = (field, value) => {
        setFormData(prev => ({ ...prev, [field]: value }));
    };

    if (loading || !formData) return <div className="empty"><span className="spinner"/> Loading configuration...</div>;

    return (
        <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px', paddingBottom: '16px', borderBottom: '1px solid var(--border)' }}>
                <div>
                    <h2 style={{ fontSize: '20px', fontWeight: 800, color: 'var(--text)' }}>
                        {isNew ? 'Create New Channel' : formData.name}
                    </h2>
                    {!isNew && <div style={{ fontSize: '12px', color: 'var(--text3)', marginTop: '4px' }}>{formData.channel_id}</div>}
                </div>
                <div style={{ display: 'flex', gap: '8px' }}>
                    {!isNew && (
                        <>
                            <button className="btn btn-ghost" onClick={handleDelete} style={{ color: 'var(--red)' }}>
                                Delete
                            </button>
                            {liveStatus?.includes('running') || running[channelId] ? (
                                <button
                                    className="btn btn-ghost"
                                    style={{color:'var(--red)', borderColor:'rgba(239,68,68,.4)'}}
                                    onClick={() => cancelRun(channelId)}
                                >
                                    <span className="spinner" style={{borderTopColor:'var(--red)'}}/> Running… ✕ Cancel
                                </button>
                            ) : (
                                <>
                                    <button className="btn btn-ghost" onClick={() => triggerRun(channelId)} style={{color:'var(--text2)'}}>
                                        {Ico.play} Phase 1
                                    </button>
                                    <button className="btn btn-primary" onClick={() => triggerScript(channelId)}>
                                        ✍️ Phase 2 — Script
                                    </button>
                                </>
                            )}
                        </>
                    )}
                    <button className="btn btn-green" onClick={handleSave} disabled={saving}>
                        {saving ? <><span className="spinner"/> Saving...</> : 'Save Changes'}
                    </button>
                </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
                {/* Identity */}
                <div style={{ background: 'var(--surface2)', padding: '16px', borderRadius: 'var(--r-md)' }}>
                    <h3 style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text2)', textTransform: 'uppercase', marginBottom: '12px' }}>Identity</h3>
                    
                    {isNew && (
                        <div className="mb">
                            <label style={{ display: 'block', fontSize: '12px', color: 'var(--text3)', marginBottom: '4px' }}>Channel ID (must be unique)</label>
                            <input className="form-input" value={formData.channel_id} onChange={e => handleChange('channel_id', e.target.value)} />
                        </div>
                    )}
                    <div className="mb">
                        <label style={{ display: 'block', fontSize: '12px', color: 'var(--text3)', marginBottom: '4px' }}>Name</label>
                        <input className="form-input" value={formData.name} onChange={e => handleChange('name', e.target.value)} />
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }} className="mb">
                        <div>
                            <label style={{ display: 'block', fontSize: '12px', color: 'var(--text3)', marginBottom: '4px' }}>Niche</label>
                            <input className="form-input" value={formData.niche} onChange={e => handleChange('niche', e.target.value)} />
                        </div>
                        <div>
                            <label style={{ display: 'block', fontSize: '12px', color: 'var(--text3)', marginBottom: '4px' }}>Sub Niche</label>
                            <input className="form-input" value={formData.sub_niche} onChange={e => handleChange('sub_niche', e.target.value)} />
                        </div>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                        <div>
                            <label style={{ display: 'block', fontSize: '12px', color: 'var(--text3)', marginBottom: '4px' }}>Market</label>
                            <input className="form-input" value={formData.market} onChange={e => handleChange('market', e.target.value)} />
                        </div>
                        <div>
                            <label style={{ display: 'block', fontSize: '12px', color: 'var(--text3)', marginBottom: '4px' }}>RPM Floor ($)</label>
                            <input type="number" step="0.1" className="form-input" value={formData.rpm_floor} onChange={e => handleChange('rpm_floor', parseFloat(e.target.value))} />
                        </div>
                    </div>
                </div>

                {/* Brand Identity */}
                <div style={{ background: 'var(--surface2)', padding: '16px', borderRadius: 'var(--r-md)' }}>
                    <h3 style={{ fontSize: '13px', fontWeight: 700, color: 'var(--purple)', textTransform: 'uppercase', marginBottom: '12px' }}>Brand Identity</h3>
                    <div className="mb">
                        <label style={{ display: 'block', fontSize: '12px', color: 'var(--text3)', marginBottom: '4px' }}>Voice Persona</label>
                        <input className="form-input" value={formData.voice_persona || ''} onChange={e => handleChange('voice_persona', e.target.value)} placeholder="e.g. cynical on-chain analyst" />
                    </div>
                    <div className="mb">
                        <label style={{ display: 'block', fontSize: '12px', color: 'var(--text3)', marginBottom: '4px' }}>Brand Voice</label>
                        <textarea className="form-input" style={{ height: '60px', resize: 'none' }} value={formData.brand_voice} onChange={e => handleChange('brand_voice', e.target.value)} />
                    </div>
                    <div className="mb">
                        <label style={{ display: 'block', fontSize: '12px', color: 'var(--text3)', marginBottom: '4px' }}>Tone</label>
                        <input className="form-input" value={formData.tone} onChange={e => handleChange('tone', e.target.value)} />
                    </div>
                    <div>
                        <label style={{ display: 'block', fontSize: '12px', color: 'var(--text3)', marginBottom: '4px' }}>Hook Format</label>
                        <textarea className="form-input" style={{ height: '60px', resize: 'none' }} value={formData.hook_format || ''} onChange={e => handleChange('hook_format', e.target.value)} />
                    </div>
                </div>

                {/* Production */}
                <div style={{ background: 'var(--surface2)', padding: '16px', borderRadius: 'var(--r-md)' }}>
                    <h3 style={{ fontSize: '13px', fontWeight: 700, color: 'var(--blue)', textTransform: 'uppercase', marginBottom: '12px' }}>Production</h3>
                    <div className="mb">
                        <label style={{ display: 'block', fontSize: '12px', color: 'var(--text3)', marginBottom: '4px' }}>Visual Style</label>
                        <input className="form-input" value={formData.visual_style} onChange={e => handleChange('visual_style', e.target.value)} />
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }} className="mb">
                        <div>
                            <label style={{ display: 'block', fontSize: '12px', color: 'var(--text3)', marginBottom: '4px' }}>Brand Color</label>
                            <div style={{ display: 'flex', gap: '8px' }}>
                                <input type="color" value={formData.brand_color_hex || '#1A1A2E'} onChange={e => handleChange('brand_color_hex', e.target.value)} style={{ width: '32px', height: '32px', padding: 0, border: 'none', borderRadius: '4px', cursor: 'pointer' }} />
                                <input className="form-input" style={{ flex: 1 }} value={formData.brand_color_hex || ''} onChange={e => handleChange('brand_color_hex', e.target.value)} />
                            </div>
                        </div>
                        <div>
                            <label style={{ display: 'block', fontSize: '12px', color: 'var(--text3)', marginBottom: '4px' }}>Font Vibe</label>
                            <input className="form-input" value={formData.font_vibe || ''} onChange={e => handleChange('font_vibe', e.target.value)} placeholder="e.g. sans_modern" />
                        </div>
                    </div>
                    <div className="mb">
                        <label style={{ display: 'block', fontSize: '12px', color: 'var(--text3)', marginBottom: '4px' }}>Voice Profile (TTS Model)</label>
                        <input className="form-input" value={formData.voice_profile} onChange={e => handleChange('voice_profile', e.target.value)} />
                    </div>
                    <div>
                        <label style={{ display: 'block', fontSize: '12px', color: 'var(--text3)', marginBottom: '4px' }}>Target Duration (mins)</label>
                        <input type="number" className="form-input" value={formData.target_duration_min} onChange={e => handleChange('target_duration_min', parseInt(e.target.value))} />
                    </div>
                </div>

                {/* Arrays / Meta */}
                <div style={{ background: 'var(--surface2)', padding: '16px', borderRadius: 'var(--r-md)' }}>
                    <h3 style={{ fontSize: '13px', fontWeight: 700, color: 'var(--amber)', textTransform: 'uppercase', marginBottom: '12px' }}>Metadata</h3>
                    <div className="mb">
                        <label style={{ display: 'block', fontSize: '12px', color: 'var(--text3)', marginBottom: '4px' }}>Competitor Handles (comma separated)</label>
                        <input className="form-input" value={(formData.competitor_handles||[]).join(', ')} onChange={e => handleChange('competitor_handles', e.target.value.split(',').map(s=>s.trim()).filter(Boolean))} />
                    </div>
                    <div className="mb">
                        <label style={{ display: 'block', fontSize: '12px', color: 'var(--text3)', marginBottom: '4px' }}>Trends Keywords (comma separated)</label>
                        <input className="form-input" value={(formData.trends_keywords||[]).join(', ')} onChange={e => handleChange('trends_keywords', e.target.value.split(',').map(s=>s.trim()).filter(Boolean))} />
                    </div>
                    <div>
                        <label style={{ display: 'block', fontSize: '12px', color: 'var(--text3)', marginBottom: '4px' }}>Subreddits (comma separated)</label>
                        <input className="form-input" value={(formData.subreddits||[]).join(', ')} onChange={e => handleChange('subreddits', e.target.value.split(',').map(s=>s.trim()).filter(Boolean))} />
                    </div>
                </div>
            </div>
        </div>
    );
}

function Channels() {
    const { data, error, loading, refetch } = useApi('/api/channels', 6000);
    const [running, setRunning] = useState({});
    const [selectedChannelId, setSelectedChannelId] = useState(null);
    const [isCreating, setIsCreating] = useState(false);

    const triggerRun = async (channelId) => {
        setRunning(p => ({...p, [channelId]: true}));
        try {
            const r = await fetch(`${API}/api/run/${channelId}`, {method:'POST'});
            await r.json();
            if (r.status === 409) alert(`${channelId} is already running`);
            else refetch();
        } catch { alert('API offline'); }
        setTimeout(() => { setRunning(p => ({...p, [channelId]: false})); refetch(); }, 2000);
    };

    const cancelRun = async (channelId) => {
        if (!confirm(`Cancel active job for "${channelId}"?`)) return;
        try {
            const r = await fetch(`${API}/api/run/${channelId}/cancel`, {method:'POST'});
            const d = await r.json();
            if (d.status === 'not_running') alert('No active job found.');
            refetch();
        } catch { alert('API offline'); }
        setRunning(p => ({...p, [channelId]: false}));
        setTimeout(refetch, 1000);
    };

    const triggerScript = async (channelId) => {
        setRunning(p => ({...p, [channelId]: true}));
        try {
            const r = await fetch(`${API}/api/run/${channelId}/script`, {method:'POST'});
            await r.json();
            if (r.status === 409) alert(`${channelId} is already running`);
            else refetch();
        } catch { alert('API offline'); }
        setTimeout(() => { setRunning(p => ({...p, [channelId]: false})); refetch(); }, 2000);
    };

    const channels = data?.channels || [];
    const activeChannel = channels.find(c => c.channel_id === selectedChannelId);

    return (
        <div style={{ display: 'flex', gap: '24px', minHeight: 'calc(100vh - 120px)' }}>
            <OfflineBanner error={error} />
            
            {/* Master List (Left Column) */}
            <div style={{ width: '320px', flexShrink: 0, display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <h3 style={{ fontSize: '15px', color: 'var(--text)' }}>Channels Directory</h3>
                    <button className="btn btn-primary btn-sm" onClick={() => { setIsCreating(true); setSelectedChannelId(null); }}>
                        + New Channel
                    </button>
                </div>
                
                <div style={{ overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: '8px', paddingRight: '4px' }}>
                    {loading && <div className="empty" style={{padding: '20px'}}><span className="spinner"/> Loading...</div>}
                    {channels.map(ch => {
                        const sc = statusColor(ch.status);
                        const isSelected = selectedChannelId === ch.channel_id;
                        return (
                            <div key={ch.channel_id} 
                                 onClick={() => { setSelectedChannelId(ch.channel_id); setIsCreating(false); }}
                                 style={{
                                     padding: '12px', background: isSelected ? 'var(--surface2)' : 'var(--surface)',
                                     border: `1px solid ${isSelected ? 'var(--blue)' : 'var(--border)'}`,
                                     borderRadius: 'var(--r-md)', cursor: 'pointer', transition: 'all .2s',
                                     boxShadow: isSelected ? '0 0 0 1px var(--blue-dim)' : 'none'
                                 }}>
                                <div style={{ fontWeight: 700, fontSize: '14px', color: 'var(--text)' }}>{ch.name}</div>
                                <div style={{ fontSize: '11px', color: 'var(--text3)', marginTop: '2px' }}>{ch.channel_id} • {ch.niche}</div>
                                <div style={{ marginTop: '8px', fontSize: '12px', color: 'var(--text2)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                                    <div className="dot" style={{ color: sc === 'green' ? 'var(--green)' : sc === 'amber' ? 'var(--amber)' : 'var(--blue)' }}/>
                                    <span style={{ fontWeight: 600 }}>{ch.status === 'idle' ? 'Idle' : ch.status?.replace('_', ' ')}</span>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* Detail View (Right Column) */}
            <div style={{ flex: 1, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', padding: '24px', overflowY: 'auto', maxHeight: 'calc(100vh - 120px)' }}>
                {!selectedChannelId && !isCreating ? (
                    <div className="empty" style={{ marginTop: '100px' }}>
                        <div className="empty-icon" style={{ color: 'var(--text3)' }}>{Ico.channel}</div>
                        <div style={{ fontSize: '14px', color: 'var(--text2)', fontWeight: 600, marginBottom: '8px' }}>No Channel Selected</div>
                        <div>Select a channel from the directory to view or edit its configuration.</div>
                    </div>
                ) : (
                    <ChannelEditor
                        channelId={selectedChannelId}
                        isNew={isCreating}
                        onSaved={() => { refetch(); setIsCreating(false); }}
                        onDeleted={() => { setSelectedChannelId(null); refetch(); }}
                        triggerRun={triggerRun}
                        triggerScript={triggerScript}
                        cancelRun={cancelRun}
                        running={running}
                        liveStatus={activeChannel?.status}
                    />
                )}
            </div>
        </div>
    );
}

// ── LiveAgentFeed ─── real-time debate log, polls while job active ─────────────
function LiveAgentFeed({ channelId }) {
    const [events, setEvents] = React.useState([]);
    const [open, setOpen] = React.useState(true);
    const bottomRef = React.useRef(null);

    React.useEffect(() => {
        if (!channelId) return;
        setEvents([]);
        const id = setInterval(() => {
            fetch(`${API}/api/run/${channelId}/log`)
                .then(r => r.json())
                .then(d => setEvents(d.events || []))
                .catch(() => {});
        }, 1500);
        return () => clearInterval(id);
    }, [channelId]);

    React.useEffect(() => {
        if (open && bottomRef.current) bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }, [events, open]);

    if (events.length === 0) return null;

    const typeStyle = {
        round:          { color: 'var(--blue)',   icon: '🔵' },
        writer_start:   { color: 'var(--amber)',  icon: '✍️' },
        writer_done:    { color: 'var(--amber)',  icon: '✍️' },
        writer_revise:  { color: 'var(--amber)',  icon: '🔄' },
        debate_start:   { color: 'var(--purple)', icon: '⚔️' },
        visual_director:{ color: 'var(--blue)',   icon: '🎨' },
        tournament_start:{ color: 'var(--green)', icon: '🏆' },
        tournament_done: { color: 'var(--green)', icon: '🏆' },
        evolution_start: { color: 'var(--purple)', icon: '🧬' },
        evolution_done:  { color: 'var(--green)',  icon: '🧬' },
        evolution_fail:  { color: 'var(--red)',    icon: '💥' },
        pipeline_done:   { color: 'var(--green)',  icon: '✅' },
        phase_start:     { color: 'var(--text3)',  icon: '▶' },
        converged:       { color: 'var(--amber)',  icon: '📉' },
        loop_lock:       { color: 'var(--red)',    icon: '🔒' },
        max_rounds:      { color: 'var(--red)',    icon: '🛑' },
    };

    return (
        <div className="card mb2" style={{border:'1px solid var(--blue)', borderRadius:'var(--r-lg)'}}>
            <div
                className="card-header"
                style={{cursor:'pointer', background:'rgba(59,130,246,.06)'}}
                onClick={() => setOpen(o => !o)}
            >
                <div style={{flex:1}}>
                    <div className="card-title" style={{color:'var(--blue)', display:'flex', alignItems:'center', gap:8}}>
                        <span style={{animation: 'spin 1.5s linear infinite', display:'inline-block'}}>⚙</span>
                        Live Agent Feed — {channelId}
                        <span style={{fontSize:11, color:'var(--text3)', fontWeight:400}}>({events.length} events)</span>
                    </div>
                    <div className="card-sub">Writer ↔ Critic debate in real-time · auto-refresh 1.5s</div>
                </div>
                <span style={{color:'var(--text3)', fontSize:14}}>{open ? '▲' : '▼'}</span>
            </div>

            {open && (
                <div style={{maxHeight:340, overflowY:'auto', padding:'8px 16px', fontFamily:'monospace', fontSize:12}}>
                    {events.map((ev, i) => {
                        const style = typeStyle[ev.type] || { color: 'var(--text2)', icon: '·' };
                        const isRound = ev.type === 'round';
                        return (
                            <div key={i} style={{
                                display:'flex', gap:8, padding:'4px 0',
                                borderBottom: i < events.length - 1 ? '1px solid var(--border)' : 'none',
                                background: ev.type === 'pipeline_done' ? 'rgba(34,197,94,.05)' : 'transparent',
                            }}>
                                <span style={{color:'var(--text3)', minWidth:75, fontSize:10, paddingTop:1}}>
                                    {ev.ts ? ev.ts.slice(11,19) : ''}
                                </span>
                                <span style={{minWidth:16}}>{style.icon}</span>
                                <span style={{color: style.color, flex:1, lineHeight:1.5}}>{ev.msg}</span>
                                {isRound && ev.rejection_reasons?.length > 0 && (
                                    <span style={{color:'var(--red)', fontSize:10, maxWidth:200, textAlign:'right', lineHeight:1.4}}>
                                        {ev.rejection_reasons[0]}
                                    </span>
                                )}
                            </div>
                        );
                    })}
                    <div ref={bottomRef}/>
                </div>
            )}
        </div>
    );
}

// ── Pipeline ───────────────────────────────────────────────────────────────────
function Pipeline() {
    const { data, error, loading } = useApi('/api/pipeline', 4000);

    const active = data?.active_jobs || [];
    const recent = data?.recent_results || [];

    const byStatus = (s) => recent.filter(r => r.status === s);
    const completed = byStatus('completed');
    const failed = byStatus('failed');

    // script_generation jobs — show live feed for each
    const scriptJobs = active.filter(j => j.phase === 'script_generation');

    return (
        <div>
            <OfflineBanner error={error} />

            {scriptJobs.map(j => (
                <LiveAgentFeed key={j.channel_id} channelId={j.channel_id} />
            ))}

            <div className="pipeline-board mb2">
                {/* Discovery */}
                <div className="pipe-col">
                    <div className="pipe-col-header">
                        <div className="pipe-col-title">Discovery</div>
                        <div className="pipe-count">{active.filter(j=>j.phase==='discovery').length}</div>
                    </div>
                    <div className="pipe-items">
                        {active.filter(j=>j.phase==='discovery').map((j,i)=>(
                            <ActiveJobCard
                                key={i}
                                job={j}
                                title={j.channel_id}
                                defaultStage="Scanning YouTube"
                            />
                        ))}
                        {active.filter(j=>j.phase==='discovery').length === 0 && (
                            <div className="empty" style={{padding:'20px 10px'}}>No active scans</div>
                        )}
                    </div>
                </div>

                {/* Niche Scan */}
                <div className="pipe-col">
                    <div className="pipe-col-header">
                        <div className="pipe-col-title">Niche Scan</div>
                        <div className="pipe-count">{active.filter(j=>j.channel_id==='__niche_discovery__').length}</div>
                    </div>
                    <div className="pipe-items">
                        {active.filter(j=>j.channel_id==='__niche_discovery__').map((j,i)=>(
                            <ActiveJobCard
                                key={i}
                                job={j}
                                title="Broad YouTube Scan"
                                defaultStage="Clustering niches"
                            />
                        ))}
                        {active.filter(j=>j.channel_id==='__niche_discovery__').length === 0 && (
                            <div className="empty" style={{padding:'20px 10px'}}>No scan running</div>
                        )}
                    </div>
                </div>

                {/* Script Generation */}
                <div className="pipe-col">
                    <div className="pipe-col-header">
                        <div className="pipe-col-title" style={{color:'var(--blue)'}}>Script Gen</div>
                        <div className="pipe-count">{scriptJobs.length}</div>
                    </div>
                    <div className="pipe-items">
                        {scriptJobs.map((j,i)=>(
                            <ActiveJobCard
                                key={i}
                                job={j}
                                title={j.channel_id}
                                defaultStage="Writer Agent"
                            />
                        ))}
                        {scriptJobs.length === 0 && (
                            <div className="empty" style={{padding:'20px 10px'}}>No scripts running</div>
                        )}
                    </div>
                </div>

                {/* Completed */}
                <div className="pipe-col">
                    <div className="pipe-col-header">
                        <div className="pipe-col-title" style={{color:'var(--green)'}}>Completed</div>
                        <div className="pipe-count">{completed.length}</div>
                    </div>
                    <div className="pipe-items">
                        {completed.slice(0,5).map((r,i)=>(
                            <div key={i} className="pipe-item">
                                <div className="pipe-item-title">{r.topic || r.channel_id}</div>
                                <div className="pipe-item-meta">{r.channel_id} • {r.score ? `${r.score}/100` : r.phase}</div>
                            </div>
                        ))}
                        {completed.length === 0 && <div className="empty" style={{padding:'20px 10px'}}>No completed jobs</div>}
                    </div>
                </div>

                {/* Failed */}
                <div className="pipe-col">
                    <div className="pipe-col-header">
                        <div className="pipe-col-title" style={{color:'var(--red)'}}>Failed</div>
                        <div className="pipe-count">{failed.length}</div>
                    </div>
                    <div className="pipe-items">
                        {failed.slice(0,5).map((r,i)=>(
                            <div key={i} className="pipe-item">
                                <div className="pipe-item-title">{r.channel_id}</div>
                                <div className="pipe-item-meta">{r.error || r.phase}</div>
                            </div>
                        ))}
                        {failed.length === 0 && <div className="empty" style={{padding:'20px 10px'}}>No failures</div>}
                    </div>
                </div>
            </div>
        </div>
    );
}

// ── Niche Discovery ────────────────────────────────────────────────────────────
function NicheDiscovery() {
    const { data, error, loading, refetch } = useApi('/api/niches', 8000);
    const { data: pipeline } = useApi('/api/pipeline', 4000);
    const [scanning, setScanning] = useState(false);

    const isRunning = pipeline?.active_jobs?.some(j => j.channel_id === '__niche_discovery__');

    const triggerScan = async () => {
        setScanning(true);
        try {
            const r = await fetch(`${API}/api/discover-niches`, {method:'POST'});
            await r.json();
            if (r.status === 409) alert('Niche discovery already running');
            else refetch();
        } catch { alert('API offline — start the server first'); }
        setTimeout(() => { setScanning(false); refetch(); }, 3000);
    };

    const niches = data?.niches || [];

    const scoreColor = (pct) => {
        if (pct >= 70) return 'var(--green)';
        if (pct >= 50) return 'var(--amber)';
        return 'var(--red)';
    };

    return (
        <div>
            <OfflineBanner error={error} />

            {/* Header action */}
            <div className="card mb2">
                <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', flexWrap:'wrap', gap:12}}>
                    <div>
                        <div className="card-title" style={{fontSize:'16px',display:'flex',alignItems:'center',gap:6}}>
                            {Ico.niche} Niche Discovery
                        </div>
                        <div className="card-sub" style={{marginTop:4}}>
                            Scan YouTube broadly → cluster into niches → rank by demand × gap × RPM
                        </div>
                        {data?.scanned_at && (
                            <div style={{fontSize:'12px', color:'var(--text3)', marginTop:4}}>
                                Last scan: {data.scanned_at.slice(0,19).replace('T',' ')} UTC
                                &nbsp;•&nbsp; {data.channels_analyzed} channels analyzed
                            </div>
                        )}
                    </div>
                    <button
                        className="btn btn-primary"
                        onClick={triggerScan}
                        disabled={isRunning || scanning}
                    >
                        {isRunning || scanning
                            ? <><span className="spinner"/> Scanning (~60s)…</>
                            : <>{Ico.refresh} Run Niche Scan</>}
                    </button>
                </div>
            </div>

            {/* Scanning indicator — live progress from /api/pipeline */}
            {(() => {
                const job = pipeline?.active_jobs?.find(j => j.channel_id === '__niche_discovery__');
                if (!job && !scanning) return null;
                if (job) {
                    return (
                        <div className="mb2">
                            <ActiveJobCard
                                job={job}
                                title="Niche Discovery — live progress"
                                defaultStage="Starting scan"
                            />
                        </div>
                    );
                }
                // Optimistic state while waiting for first poll after POST
                return (
                    <div className="scan-card mb2">
                        <div style={{display:'flex',alignItems:'center',justifyContent:'center',gap:10,marginBottom:'10px'}}>
                            <span className="spinner"/>
                            <span style={{fontSize:'15px', fontWeight:700, color:'var(--text)'}}>Starting niche scan…</span>
                        </div>
                        <div style={{fontSize:'12px', color:'var(--text2)'}}>
                            Waiting for first progress event (≤4s).
                        </div>
                    </div>
                );
            })()}

            {/* Results */}
            {niches.length === 0 && !loading && !isRunning && !scanning && (
                <div className="card">
                    <div className="empty">
                        <div className="empty-icon" style={{color:'var(--text3)'}}>{Ico.target}</div>
                        No niche data yet. Click "Run Niche Scan" to discover opportunities.
                    </div>
                </div>
            )}

            <div className="niche-grid">
                {niches.map((n, i) => {
                    const demandPct = (n.demand_score / 40 * 100).toFixed(0);
                    const gapPct = (n.gap_score / 30 * 100).toFixed(0);
                    const rpmPct = (n.rpm_score / 20 * 100).toFixed(0);
                    return (
                        <div key={n.niche_id || i} className="niche-card">
                            <div className="niche-rank">#{i+1} · {n.category?.toUpperCase()}</div>
                            <div className="niche-name">{n.niche_name}</div>
                            <div className="niche-audience">{n.audience_description}</div>

                            {/* Score ring */}
                            <div style={{display:'flex',alignItems:'center',gap:16,marginBottom:14}}>
                                <div style={{
                                    width:56, height:56, borderRadius:'50%', flexShrink:0,
                                    background:`conic-gradient(${scoreColor(n.total_score)} ${n.total_score*3.6}deg, var(--surface2) 0deg)`,
                                    display:'flex', alignItems:'center', justifyContent:'center',
                                }}>
                                    <div style={{
                                        width:42, height:42, borderRadius:'50%', background:'var(--surface)',
                                        display:'flex', alignItems:'center', justifyContent:'center',
                                        fontSize:14, fontWeight:800, color:scoreColor(n.total_score),
                                    }}>{n.total_score}</div>
                                </div>
                                <div style={{flex:1}}>
                                    <div className="score-bar-row">
                                        <span className="score-bar-label">Demand</span>
                                        <div className="score-bar-track">
                                            <div className="score-bar-fill" style={{width:`${demandPct}%`, background:'var(--blue)'}}/>
                                        </div>
                                        <span style={{fontSize:11,color:'var(--text3)',width:24,textAlign:'right'}}>{n.demand_score}</span>
                                    </div>
                                    <div className="score-bar-row">
                                        <span className="score-bar-label">Gap</span>
                                        <div className="score-bar-track">
                                            <div className="score-bar-fill" style={{width:`${gapPct}%`, background:'var(--green)'}}/>
                                        </div>
                                        <span style={{fontSize:11,color:'var(--text3)',width:24,textAlign:'right'}}>{n.gap_score}</span>
                                    </div>
                                    <div className="score-bar-row">
                                        <span className="score-bar-label">RPM</span>
                                        <div className="score-bar-track">
                                            <div className="score-bar-fill" style={{width:`${rpmPct}%`, background:'var(--amber)'}}/>
                                        </div>
                                        <span style={{fontSize:11,color:'var(--text3)',width:24,textAlign:'right'}}>${n.estimated_rpm}</span>
                                    </div>
                                </div>
                            </div>

                            {/* Pain points */}
                            <div className="niche-tags">
                                {(n.pain_points || []).slice(0,3).map((p,j) => (
                                    <span key={j} className="tag red" style={{fontSize:'10px'}}>{p.slice(0,32)}</span>
                                ))}
                            </div>

                            {/* Why */}
                            {n.why_opportunity && (
                                <div style={{fontSize:'12px', color:'var(--text2)', marginBottom:8, lineHeight:1.4, display:'flex', gap:6}}>
                                    <span style={{color:'var(--amber)',flexShrink:0,marginTop:1}}>{Ico.bulb}</span>
                                    <span>{n.why_opportunity}</span>
                                </div>
                            )}

                            {/* Channels */}
                            {(n.example_channels || []).length > 0 && (
                                <div style={{fontSize:'11px', color:'var(--text3)', display:'flex', alignItems:'center', gap:6}}>
                                    <span style={{color:'var(--text3)'}}>{Ico.tv}</span>
                                    <span>{n.example_channels.slice(0,3).join(', ')}</span>
                                </div>
                            )}

                            {/* Best title */}
                            {(n.breakout_titles || [])[0] && (
                                <div className="niche-title">"{n.breakout_titles[0].slice(0,60)}"</div>
                            )}
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

// ── Infrastructure — DB/Redis/Workers health (auto-polled 5s) ─────────────────
function Infrastructure() {
    const { data, error, loading } = useApi('/api/infra', 5000);
    const { data: stateRaw } = useApi('/api/system/state', 4000);
    const payload = data?.data;
    const state = stateRaw?.data;

    const db      = payload?.db      || { ok: false, error: 'loading' };
    const redis   = payload?.redis   || { ok: false, error: 'loading' };
    const workers = payload?.workers || [];
    const summary = payload?.summary || { total: 0, healthy: 0, degraded: 0, offline: 0 };

    const heartbeatAge = (iso) => {
        if (!iso) return '—';
        try {
            const s = Math.floor((Date.now() - new Date(iso)) / 1000);
            if (s < 60)   return `${s}s ago`;
            if (s < 3600) return `${Math.floor(s/60)}m ago`;
            return `${Math.floor(s/3600)}h ago`;
        } catch (e) { return iso.slice(11,19); }
    };

    const statusBadge = {
        healthy:  { tag: 'green',  text: 'Healthy'  },
        degraded: { tag: 'amber',  text: 'Degraded' },
        offline:  { tag: 'red',    text: 'Offline'  },
    };

    return (
        <div>
            <OfflineBanner error={error} />

            {/* Kill-switch surface (rule #2: approval gate state inescapable) */}
            {state && state.paused && (
                <div className="offline-banner" style={{background:'var(--red-dim)',borderColor:'var(--red)',color:'var(--red)'}}>
                    {Ico.stop}
                    <span style={{fontWeight:700}}>PIPELINE PAUSED</span>
                    <span>since {(state.paused_since || '').slice(0,19).replace('T',' ')} UTC — workers will not pull new jobs.</span>
                </div>
            )}
            {state && !state.redis_available && (
                <div className="offline-banner">
                    ⚠ Redis unreachable — kill-switch state cannot be read or enforced. Investigate Redis before relying on emergency stop.
                </div>
            )}

            {/* Top row: DB + Redis pills + worker summary */}
            <div className="grid g4 mb2">
                <div className="kpi">
                    <div className="kpi-label">PostgreSQL</div>
                    <div className="kpi-val" style={{fontSize:22,color: db.ok ? 'var(--green)' : 'var(--red)'}}>
                        {db.ok ? 'Connected' : 'DOWN'}
                    </div>
                    <div className="kpi-sub">{db.error || 'Auto-polled every 5s'}</div>
                </div>
                <div className="kpi">
                    <div className="kpi-label">Redis</div>
                    <div className="kpi-val" style={{fontSize:22,color: redis.ok ? 'var(--green)' : 'var(--red)'}}>
                        {redis.ok ? 'Connected' : 'DOWN'}
                    </div>
                    <div className="kpi-sub">{redis.error || 'Auto-polled every 5s'}</div>
                </div>
                <div className="kpi">
                    <div className="kpi-label">Workers — Healthy</div>
                    <div className="kpi-val" style={{color: summary.healthy === summary.total && summary.total > 0 ? 'var(--green)' : 'var(--amber)'}}>
                        {loading ? <span className="spinner"/> : `${summary.healthy} / ${summary.total}`}
                    </div>
                    <div className="kpi-sub">{summary.degraded} degraded · {summary.offline} offline</div>
                </div>
                <div className="kpi">
                    <div className="kpi-label">Provenance</div>
                    <div className="kpi-val" style={{fontSize:14,fontWeight:600,color:'var(--text2)',marginTop:14}}>
                        {data?.source || '—'}
                    </div>
                    <div className="kpi-sub">fetched {data?.fetched_at?.slice(11,19) || '—'} UTC</div>
                </div>
            </div>

            {/* Worker cards */}
            <div className="card mb2">
                <div className="card-header">
                    <div>
                        <div className="card-title" style={{display:'flex',alignItems:'center',gap:6}}>
                            {Ico.cpu} Workers
                        </div>
                        <div className="card-sub">Live heartbeat from Redis — click a card to inspect raw payload</div>
                    </div>
                </div>
                {workers.length === 0 ? (
                    <div className="empty">
                        <div className="empty-icon" style={{color:'var(--text3)'}}>{Ico.cpu}</div>
                        No workers reporting heartbeat. {redis.ok ? 'Workers offline.' : 'Redis is down — fix that first.'}
                    </div>
                ) : (
                    <div className="grid g2" style={{gap:12}}>
                        {workers.map(w => {
                            const badge = statusBadge[w.status] || { tag: 'purple', text: w.status };
                            return (
                                <div key={w.worker_id} className="card" style={{padding:14,background:'var(--surface2)'}}>
                                    <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:8}}>
                                        <div>
                                            <div style={{fontWeight:700,fontSize:13,color:'var(--text)'}}>{w.hostname}</div>
                                            <div style={{fontSize:11,color:'var(--text3)',fontFamily:'monospace'}}>{w.worker_id}</div>
                                        </div>
                                        <span className={`tag ${badge.tag}`}>{badge.text}</span>
                                    </div>

                                    {/* CPU bar */}
                                    <div style={{marginBottom:6}}>
                                        <div style={{display:'flex',justifyContent:'space-between',fontSize:11,color:'var(--text3)',marginBottom:3}}>
                                            <span>CPU</span><span>{w.cpu_percent?.toFixed?.(1)}%</span>
                                        </div>
                                        <div className="progress"><div className={`progress-fill ${w.cpu_percent>80?'red':w.cpu_percent>60?'amber':'green'}`} style={{width:`${Math.min(100,w.cpu_percent||0)}%`}}/></div>
                                    </div>
                                    {/* RAM bar */}
                                    <div style={{marginBottom:6}}>
                                        <div style={{display:'flex',justifyContent:'space-between',fontSize:11,color:'var(--text3)',marginBottom:3}}>
                                            <span>RAM</span><span>{w.ram_percent?.toFixed?.(1)}%</span>
                                        </div>
                                        <div className="progress"><div className={`progress-fill ${w.ram_percent>85?'red':w.ram_percent>70?'amber':'blue'}`} style={{width:`${Math.min(100,w.ram_percent||0)}%`}}/></div>
                                    </div>

                                    <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginTop:10,fontSize:11}}>
                                        <div style={{color:'var(--text3)'}}>
                                            {w.gpu_temp != null && <span style={{marginRight:8}}>GPU {w.gpu_temp}°C</span>}
                                            <span style={{color: w.status==='offline' ? 'var(--red)' : 'var(--text3)'}}>♥ {heartbeatAge(w.last_heartbeat)}</span>
                                        </div>
                                        {w.current_task && (
                                            <code style={{fontSize:10,color:'var(--blue)',background:'var(--blue-dim)',padding:'2px 6px',borderRadius:3}}>
                                                {w.current_task.slice(0,30)}
                                            </code>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>

            {/* Full error log (with clear button) */}
            <ErrorLogPanel limit={20} title="Error Log" allowClear={true} />

            {/* Raw payload — rule #4 No Blackbox */}
            <div className="card">
                <div className="card-header">
                    <div>
                        <div className="card-title">Raw payload</div>
                        <div className="card-sub">Inspect the exact JSON returned by /api/infra (rule #4: no blackbox)</div>
                    </div>
                </div>
                <pre style={{background:'var(--surface2)',padding:12,borderRadius:6,fontSize:11,maxHeight:300,overflow:'auto',color:'var(--text2)'}}>
{JSON.stringify(data || {}, null, 2)}
                </pre>
            </div>
        </div>
    );
}

// ── Budget ─────────────────────────────────────────────────────────────────────
function Budget() {
    const { data, error } = useApi('/api/budget', 10000);

    const spend = data?.today_usd || 0;
    const cap = data?.daily_cap_usd || 100;
    const pct = (spend / cap * 100).toFixed(1);
    const breakdown = data?.breakdown || [];

    return (
        <div>
            <OfflineBanner error={error} />

            <div className="grid g2 mb2">
                <div className="kpi">
                    <div className="kpi-label">Today's Spend</div>
                    <div className="kpi-val">${spend.toFixed(2)}</div>
                    <div className="progress" style={{marginTop:10}}>
                        <div className={`progress-fill ${pct > 80 ? 'red' : pct > 50 ? 'amber' : 'green'}`}
                             style={{width:`${Math.min(pct,100)}%`}}/>
                    </div>
                    <div className="kpi-sub" style={{marginTop:6}}>{pct}% of ${cap} daily cap</div>
                </div>
                <div className="kpi">
                    <div className="kpi-label">Total (All Time)</div>
                    <div className="kpi-val">${(data?.total_usd || 0).toFixed(2)}</div>
                    <div className="kpi-sub">Accumulated LLM costs</div>
                </div>
            </div>

            <div className="card">
                <div className="card-header">
                    <div><div className="card-title">Cost Breakdown</div><div className="card-sub">Today by category</div></div>
                </div>
                {breakdown.length === 0
                    ? <div className="empty">No costs recorded yet</div>
                    : breakdown.map((b, i) => (
                        <div key={i} className="row">
                            <div className="row-label">{b.category}</div>
                            <div className="row-val">${b.amount.toFixed(4)}</div>
                        </div>
                    ))
                }
            </div>
        </div>
    );
}

// ── Destinations ─────────────────────────────────────────────────────────────
function Destinations() {
    const { data: platformsData, error: platformsError } = useApi('/api/platforms', 15000);
    const { data: destinationsData, error: destinationsError } = useApi('/api/destinations', 8000);
    const { data: readinessData, error: readinessError } = useApi('/api/monetization/readiness', 12000);

    const platforms = platformsData?.platforms || [];
    const destinations = destinationsData?.destinations || [];
    const readiness = readinessData || {};
    const recommendation = readiness.recommendation || 'wait';
    const recClass = recommendation === 'ship' ? 'green' : recommendation === 'reject' ? 'red' : 'amber';

    return (
        <div>
            <OfflineBanner error={platformsError || destinationsError || readinessError} />

            <div className="grid g3 mb2">
                <div className="kpi">
                    <div className="kpi-label">Platforms</div>
                    <div className="kpi-val">{platforms.length}</div>
                    <div className="kpi-sub">Registered adapters</div>
                </div>
                <div className="kpi">
                    <div className="kpi-label">Destinations</div>
                    <div className="kpi-val">{destinations.length}</div>
                    <div className="kpi-sub">Channel targets</div>
                </div>
                <div className="kpi">
                    <div className="kpi-label">Monetization Readiness</div>
                    <div className="kpi-val">{readiness.score ?? 0}%</div>
                    <div className={`tag ${recClass}`} style={{marginTop:8}}>{recommendation.toUpperCase()}</div>
                </div>
            </div>

            <div className="grid g2 mb2">
                <div className="card">
                    <div className="card-header">
                        <div><div className="card-title">Platform Formats</div><div className="card-sub">Publish surfaces</div></div>
                    </div>
                    {platforms.map(p => (
                        <div className="row" key={p.platform_id}>
                            <div>
                                <div className="row-label">{p.name}</div>
                                <div className="row-sub">{p.format_spec?.variant} · {p.format_spec?.aspect_ratio} · {p.format_spec?.width}x{p.format_spec?.height}</div>
                            </div>
                            <div className={`tag ${p.capabilities?.scheduling ? 'green' : 'amber'}`}>
                                {p.capabilities?.publish === true ? 'API' : 'API gated'}
                            </div>
                        </div>
                    ))}
                    {platforms.length === 0 && <div className="empty">No platforms registered</div>}
                </div>

                <div className="card">
                    <div className="card-header">
                        <div><div className="card-title">Destinations</div><div className="card-sub">Per-channel routing</div></div>
                    </div>
                    {destinations.slice(0, 8).map(d => (
                        <div className="row" key={d.destination_id}>
                            <div>
                                <div className="row-label">{d.channel_name || d.channel_id}</div>
                                <div className="row-sub">{d.platform_id} · {d.format_variant} · {d.account_id}</div>
                            </div>
                            <div className={`tag ${d.approval_required ? 'amber' : 'green'}`}>
                                {d.approval_required ? 'Approval' : 'Auto'}
                            </div>
                        </div>
                    ))}
                    {destinations.length === 0 && <div className="empty">No destinations configured</div>}
                </div>
            </div>

            <div className="card">
                <div className="card-header">
                    <div><div className="card-title">Readiness Checks</div><div className="card-sub">Public monetized publishing gate</div></div>
                </div>
                {(readiness.checks || []).map(c => (
                    <div className="row" key={c.name}>
                        <div>
                            <div className="row-label">{c.name.replaceAll('_', ' ')}</div>
                            <div className="row-sub">{c.evidence}</div>
                        </div>
                        <div className={`tag ${c.passed ? 'green' : 'red'}`}>{c.passed ? 'Pass' : 'Block'}</div>
                    </div>
                ))}
            </div>
        </div>
    );
}

// ── Vault ─────────────────────────────────────────────────────────────────────

function DebateResultModal({ result, onClose }) {
    if (!result) return null;
    return (
        <div style={{ position: 'fixed', top: 0, left: 0, width: '100%', height: '100%', backgroundColor: 'rgba(0,0,0,0.8)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999 }}>
            <div style={{ background: 'var(--surface)', padding: '24px', borderRadius: 'var(--r-lg)', width: '800px', maxWidth: '90%', border: '1px solid var(--border)', boxShadow: '0 20px 40px rgba(0,0,0,0.5)', overflowY: 'auto', maxHeight: '90vh' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                    <h2 style={{ margin: 0, color: 'var(--text)', fontSize: '18px' }}>🤖 DeepSeek Pro Debate Results</h2>
                    <button className="btn btn-sm btn-ghost" onClick={onClose} style={{ padding: '4px 8px' }}>✕ Close</button>
                </div>
                
                <div style={{ marginBottom: '24px', padding: '16px', background: 'var(--surface2)', borderRadius: 'var(--r-md)', borderLeft: '4px solid var(--green)' }}>
                    <div style={{ fontSize: '12px', color: 'var(--text3)', textTransform: 'uppercase', fontWeight: 700, marginBottom: '8px' }}>Winner Selected</div>
                    <div style={{ fontSize: '24px', fontWeight: 800, color: 'var(--green)', marginBottom: '8px' }}>⭐ {result.winner}</div>
                    <div style={{ fontSize: '14px', color: 'var(--text2)', lineHeight: 1.5 }}>{result.reason}</div>
                </div>

                <h3 style={{ fontSize: '14px', color: 'var(--text)', marginBottom: '12px' }}>Candidate Pool</h3>
                <table className="table" style={{ width: '100%' }}>
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>@Handle</th>
                            <th>Trust</th>
                            <th>SEO</th>
                            <th>Total</th>
                            <th>Avail</th>
                        </tr>
                    </thead>
                    <tbody>
                        {result.candidates.map((c, i) => (
                            <tr key={i} style={{ background: c.name === result.winner ? 'rgba(34, 197, 94, 0.1)' : 'transparent' }}>
                                <td style={{ fontWeight: c.name === result.winner ? 700 : 500, color: c.name === result.winner ? 'var(--green)' : 'var(--text)' }}>
                                    {c.name} {c.name === result.winner && '⭐'}
                                </td>
                                <td style={{ color: 'var(--text2)' }}>{c.handle}</td>
                                <td>{c.trust?.toFixed(1)}</td>
                                <td>{c.seo?.toFixed(1)}</td>
                                <td style={{ fontWeight: 600 }}>{c.total_score?.toFixed(2)}</td>
                                <td>
                                    {c.available === true ? '✅' : c.available === false ? '❌' : '❓'}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

function Vault() {
    const { data, error, loading, refetch } = useApi('/api/vault', 8000);
    const [saving, setSaving] = useState(false);
    const [checking, setChecking] = useState(false);
    const [view, setView] = useState('all'); // 'all' | 'hot'
    const [debateResult, setDebateResult] = useState(null);

    const niches = data?.niches || [];
    const hot = niches.filter(n => n.status === 'hot');
    const shown = view === 'hot' ? hot : niches;

    const statusIcon = { hot: '🔴', watching: '🟡', active: '🟢', stale: '🔘', archived: '⬛' };
    const statusColor = { hot: 'red', watching: 'amber', active: 'green', stale: 'purple', archived: 'purple' };

    const age = (iso) => {
        if (!iso) return '—';
        const d = Math.floor((Date.now() - new Date(iso)) / 86400000);
        return d === 0 ? 'today' : d === 1 ? '1d' : `${d}d`;
    };
    const checked = (iso) => {
        if (!iso) return 'never';
        const h = Math.floor((Date.now() - new Date(iso)) / 3600000);
        if (h === 0) return 'just now';
        if (h < 24) return `${h}h ago`;
        return `${Math.floor(h/24)}d ago`;
    };
    const trendEl = (n) => {
        const delta = n.current_health - n.original_score;
        if (delta > 2) return <span className="trend-up">↑ +{delta}</span>;
        if (delta < -2) return <span className="trend-down">↓ {delta}</span>;
        return <span className="trend-flat">━</span>;
    };

    const saveAll = async () => {
        setSaving(true);
        try {
            await fetch(`${API}/api/vault/save-all`, {method:'POST'});
            setTimeout(() => { setSaving(false); refetch(); }, 2000);
        } catch(e) { setSaving(false); alert('API offline'); }
    };
    const healthCheck = async () => {
        setChecking(true);
        try {
            await fetch(`${API}/api/vault/health-check`, {method:'POST'});
            setTimeout(() => { setChecking(false); refetch(); }, 5000);
        } catch(e) { setChecking(false); alert('API offline'); }
    };
    const createChannel = async (id, btn) => {
        if (!confirm(`Auto-create a channel for niche "${id}" using the DeepSeek + Claude Multi-Agent Debate pipeline?`)) return;
        btn.disabled = true;
        const oldText = btn.innerHTML;
        btn.innerHTML = `<span class="spinner" style="width:10px;height:10px;border-width:2px;margin-right:4px;"></span> Building...`;
        try {
            const res = await fetch(`${API}/api/vault/create-channel/${id}`, {method:'POST'});
            const data = await res.json();
            if (res.ok) {
                if (data.debate) {
                    setDebateResult(data.debate);
                } else {
                    alert(`Channel created successfully!\n\nID: ${data.channel.channel_id}\nName: ${data.channel.name}\n\nSwitch to the Channels tab to configure or run it!`);
                }
            } else {
                alert(`Error: ${data.detail || 'Unknown error'}`);
            }
        } catch { alert('Failed to connect to API');
        }
        btn.innerHTML = oldText;
        btn.disabled = false;
    };

    const archive = async (id) => {
        if (!confirm(`Archive "${id}"?`)) return;
        await fetch(`${API}/api/vault/archive/${id}`, {method:'POST'});
        refetch();
    };

    return (
        <div>
            <DebateResultModal result={debateResult} onClose={() => setDebateResult(null)} />
            <OfflineBanner error={error} />

            {/* Header stats */}
            <div className="grid g4 mb2">
                <div className="kpi">
                    <div className="kpi-label">Total Niches</div>
                    <div className="kpi-val">{data?.total || 0}</div>
                    <div className="kpi-sub">In vault</div>
                </div>
                <div className="kpi">
                    <div className="kpi-label">🔴 HOT</div>
                    <div className="kpi-val" style={{color:'var(--red)'}}>{data?.hot_count || 0}</div>
                    <div className="kpi-sub">Act now</div>
                </div>
                <div className="kpi">
                    <div className="kpi-label">🟡 Watching</div>
                    <div className="kpi-val" style={{color:'var(--amber)'}}>{data?.watching_count || 0}</div>
                    <div className="kpi-sub">Monitoring</div>
                </div>
                <div className="kpi">
                    <div className="kpi-label">🔘 Stale</div>
                    <div className="kpi-val" style={{color:'var(--text3)'}}>{data?.stale_count || 0}</div>
                    <div className="kpi-sub">Skip</div>
                </div>
            </div>

            {/* Actions */}
            <div className="vault-actions">
                <button className="btn btn-primary" onClick={saveAll} disabled={saving}>
                    {saving ? <><span className="spinner"/> Saving…</> : <>{Ico.save} Save from Scan</>}
                </button>
                <button className="btn btn-ghost" onClick={healthCheck} disabled={checking}>
                    {checking ? <><span className="spinner"/> Checking…</> : <>{Ico.refresh} Health Check All</>}
                </button>
                <button className={`btn btn-sm ${view==='all'?'btn-primary':'btn-ghost'}`} onClick={() => setView('all')}>All</button>
                <button className={`btn btn-sm ${view==='hot'?'btn-primary':'btn-ghost'}`} style={{color: view==='hot'?undefined:'var(--red)', borderColor: view!=='hot'?'rgba(239,68,68,.3)':undefined}} onClick={() => setView('hot')}>
                    🔴 HOT ({hot.length})
                </button>
            </div>

            {/* HOT panels */}
            {view === 'hot' && hot.length > 0 && (
                <div className="mb2">
                    {hot.map((n, i) => (
                        <div key={n.niche_id} className="hot-panel">
                            <div className="hot-panel-title">#{i+1} {n.niche_name} [{n.current_health}/100]</div>
                            <div className="hot-panel-meta">
                                {n.market} · {n.category} · Est. RPM ${n.estimated_rpm} · Saved {age(n.saved_at)} ago
                            </div>
                            {n.health_notes?.length > 0 && (
                                <div className="hot-why">
                                    {n.health_notes.map((note, j) => <div key={j}>✦ {note}</div>)}
                                </div>
                            )}
                            {n.top_video?.title && (
                                <div className="hot-breakout">
                                    TOP BREAKOUT: "{n.top_video.title?.slice(0,70)}"
                                    {n.top_video.video_id && (
                                        <a href={`https://youtu.be/${n.top_video.video_id}`} target="_blank"
                                           style={{color:'var(--blue)', marginLeft:8, textDecoration:'none'}}>
                                            ↗ youtu.be/{n.top_video.video_id}
                                        </a>
                                    )}
                                    <span style={{marginLeft:8, color:'var(--text3)'}}>
                                        {n.top_video.views?.toLocaleString()} views · {n.top_video.outlier_x}x median
                                    </span>
                                </div>
                            )}
                            <div style={{marginTop:12, display:'flex', gap:8}}>
                                <span className="tag green" style={{fontSize:10}}>Score {n.original_score} → {n.current_health}</span>
                                <button className="btn btn-sm btn-ghost" style={{fontSize:11,padding:'3px 8px'}} onClick={() => archive(n.niche_id)}>Archive</button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Table */}
            {view === 'all' && (
                <div className="card">
                    {loading && <div className="empty"><span className="spinner"/> Loading vault…</div>}
                    {!loading && niches.length === 0 && (
                        <div className="empty">
                            <div className="empty-icon" style={{color:'var(--text3)'}}>{Ico.archive}</div>
                            Vault empty — run a niche scan then click "Save from Scan"
                        </div>
                    )}
                    {niches.length > 0 && (
                        <table className="vault-table">
                            <thead>
                                <tr>
                                    <th></th>
                                    <th>Status</th>
                                    <th>Score</th>
                                    <th>Trend</th>
                                    <th>Niche</th>
                                    <th>Mkt</th>
                                    <th>RPM</th>
                                    <th>Age</th>
                                    <th>Checked</th>
                                    <th></th>
                                </tr>
                            </thead>
                            <tbody>
                                {shown.map(n => (
                                    <tr key={n.niche_id}>
                                        <td>{statusIcon[n.status] || '⬜'}</td>
                                        <td><span className={`tag ${statusColor[n.status]||'purple'}`}>{n.status.toUpperCase()}</span></td>
                                        <td><span className="vault-score" style={{color: n.current_health>=80?'var(--green)':n.current_health>=60?'var(--amber)':'var(--red)'}}>{n.current_health}</span></td>
                                        <td>{trendEl(n)}</td>
                                        <td style={{maxWidth:340, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis', color:'var(--text)', fontWeight:500}}>{n.niche_name}</td>
                                        <td style={{color:'var(--text3)'}}>{n.market}</td>
                                        <td style={{color:'var(--green)'}}>${n.estimated_rpm}</td>
                                        <td style={{color:'var(--text3)'}}>{age(n.saved_at)}</td>
                                        <td style={{color:'var(--text3)'}}>{checked(n.last_checked)}</td>
                                        <td>
                                            <button className="btn btn-sm btn-primary" style={{fontSize:11,padding:'2px 8px',marginRight:4}}
                                                onClick={(e) => createChannel(n.niche_id, e.currentTarget)}>⚡ Auto-Create Channel</button>
                                            <button className="btn btn-sm btn-ghost" style={{fontSize:11,padding:'2px 8px'}}
                                                onClick={() => archive(n.niche_id)}>Archive</button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </div>
            )}
        </div>
    );
}

// ── ScriptViewer ───────────────────────────────────────────────────────────────
function ScriptViewer() {
    const { data: channelsData } = useApi('/api/channels', 30000);
    const channels = channelsData?.channels || [];

    const [channelId, setChannelId] = React.useState('');
    const [scripts, setScripts] = React.useState([]);
    const [loading, setLoading] = React.useState(false);
    const [discovery, setDiscovery] = React.useState([]);
    const [writingTopic, setWritingTopic] = React.useState(null);
    const [error, setError] = React.useState(null);
    const [expanded, setExpanded] = React.useState({});
    const [debateOpen, setDebateOpen] = React.useState({});
    const [copied, setCopied] = React.useState(null);

    React.useEffect(() => {
        if (channels.length > 0 && !channelId) setChannelId(channels[0].channel_id);
    }, [channels]);

    React.useEffect(() => {
        if (!channelId) return;
        setLoading(true); setError(null);
        Promise.all([
            fetch(`${API}/api/scripts/${channelId}`).then(r => r.json()),
            fetch(`${API}/api/discovery/${channelId}`).then(r => r.json()),
        ]).then(([sd, dd]) => {
            setScripts(sd.scripts || []);
            setDiscovery(dd.topics || []);
            setLoading(false);
        }).catch(e => { setError(e.message); setLoading(false); });
    }, [channelId]);

    const toggleExpand = (key) => setExpanded(p => ({ ...p, [key]: !p[key] }));
    const toggleDebate = (key) => setDebateOpen(p => ({ ...p, [key]: !p[key] }));

    const copyPrompt = (text, key) => {
        navigator.clipboard.writeText(text).then(() => {
            setCopied(key); setTimeout(() => setCopied(null), 1500);
        });
    };

    const writeScript = async (topic) => {
        setWritingTopic(topic);
        try {
            const url = `${API}/api/run/${channelId}/script?topic=${encodeURIComponent(topic)}`;
            const r = await fetch(url, {method:'POST'});
            await r.json();
            if (r.status === 409) alert('Already running — check Pipeline tab');
            else alert(`✍️ Script generation started!\nTopic: "${topic}"\n\nSwitch to Pipeline tab to watch live debate.`);
        } catch { alert('API offline'); }
        setWritingTopic(null);
    };

    const byTopic = {};
    for (const s of scripts) {
        if (!byTopic[s.topic_slug]) byTopic[s.topic_slug] = [];
        byTopic[s.topic_slug].push(s);
    }
    const topicSlugs = Object.keys(byTopic);

    // All discovered topics (flat list from all runs, deduplicated by title)
    const allTopics = [];
    const seen = new Set();
    for (const run of discovery) {
        for (const t of (run.topic_queue || [])) {
            const title = t.title || t;
            if (!seen.has(title)) { seen.add(title); allTopics.push({...t, title, run_id: run.run_id, saved_at: run.saved_at}); }
        }
    }

    return (
        <div>
            {/* Channel selector */}
            <div className="card mb2" style={{padding:'12px 16px'}}>
                <div style={{display:'flex',alignItems:'center',gap:12,flexWrap:'wrap'}}>
                    <span style={{fontSize:13,color:'var(--text2)',fontWeight:600}}>Channel:</span>
                    <select
                        value={channelId}
                        onChange={e => setChannelId(e.target.value)}
                        style={{background:'var(--surface2)',color:'var(--text)',border:'1px solid var(--border)',borderRadius:'var(--r-sm)',padding:'6px 10px',fontSize:13,cursor:'pointer'}}
                    >
                        {channels.map(c => (
                            <option key={c.channel_id} value={c.channel_id}>{c.name || c.channel_id}</option>
                        ))}
                    </select>
                    {loading && <span className="spinner"/>}
                    {scripts.length > 0 && <span style={{fontSize:12,color:'var(--text3)'}}>{scripts.length} script{scripts.length>1?'s':''}</span>}
                    {allTopics.length > 0 && <span style={{fontSize:12,color:'var(--amber)'}}>{allTopics.length} discovered topic{allTopics.length>1?'s':''}</span>}
                </div>
            </div>

            {error && <div className="offline-banner">⚠ {error}</div>}

            {/* Discovered Topics */}
            {allTopics.length > 0 && (
                <div className="card mb2">
                    <div className="card-header">
                        <div>
                            <div className="card-title" style={{color:'var(--amber)'}}>🔍 Discovered Topics</div>
                            <div className="card-sub">From Phase 1 discovery — click ✍️ to generate script</div>
                        </div>
                    </div>
                    {allTopics.map((t, i) => (
                        <div key={i} style={{display:'flex',alignItems:'center',gap:10,padding:'10px 16px',borderTop:'1px solid var(--border)'}}>
                            <div style={{flex:1}}>
                                <div style={{fontSize:13,color:'var(--text)',fontWeight:500}}>{t.title}</div>
                                {(t.audience_segment || t.pain_point) && (
                                    <div style={{fontSize:11,color:'var(--text3)',marginTop:2}}>
                                        {t.audience_segment && <span style={{marginRight:8}}>👤 {t.audience_segment}</span>}
                                        {t.pain_point && <span>💢 {t.pain_point}</span>}
                                    </div>
                                )}
                            </div>
                            {t.score > 0 && <span className="tag amber" style={{fontSize:10}}>Score {t.score}</span>}
                            <button
                                className="btn btn-sm btn-primary"
                                style={{fontSize:11,padding:'4px 10px',whiteSpace:'nowrap'}}
                                disabled={writingTopic === t.title}
                                onClick={() => writeScript(t.title)}
                            >
                                {writingTopic === t.title ? <><span className="spinner" style={{width:10,height:10,borderWidth:2}}/> Starting…</> : '✍️ Write Script'}
                            </button>
                        </div>
                    ))}
                </div>
            )}

            {!loading && scripts.length === 0 && allTopics.length === 0 && channelId && (
                <div className="empty">
                    <div className="empty-icon">📄</div>
                    No scripts or discovery data yet. Run Phase 1 (Discover Topics) first, then Phase 2 (Write Script).
                </div>
            )}

            {/* Topic groups */}
            {topicSlugs.map(slug => {
                const variants = byTopic[slug];
                const topic = variants[0]?.topic || slug;
                return (
                    <div key={slug} className="card mb2">
                        <div className="card-header" style={{cursor:'default'}}>
                            <div style={{flex:1}}>
                                <div className="card-title" style={{fontSize:15}}>{topic}</div>
                                <div className="card-sub">{variants.length} variant{variants.length>1?'s':''} · slug: {slug}</div>
                            </div>
                        </div>

                        {variants.map(s => {
                            const key = `${slug}:${s.variant_id}`;
                            const isOpen = !!expanded[key];
                            const isDebateOpen = !!debateOpen[key];
                            const hasDebate = s.debate_rounds && s.debate_rounds.length > 0;

                            return (
                                <div key={key} style={{borderTop:'1px solid var(--border)'}}>
                                    {/* Variant header */}
                                    <div
                                        onClick={() => toggleExpand(key)}
                                        style={{display:'flex',alignItems:'center',gap:10,padding:'10px 16px',cursor:'pointer',background:isOpen?'var(--surface2)':'transparent',transition:'background 0.15s'}}
                                    >
                                        <span style={{fontSize:12,color:'var(--text3)',fontFamily:'monospace',minWidth:80}}>
                                            variant_{s.variant_id}
                                        </span>
                                        <span className={`tag ${s.approved ? 'green' : s.score >= 70 ? 'amber' : 'purple'}`} style={{fontSize:10}}>
                                            {s.approved ? '✅ Approved' : `Score ${s.score ?? '?'}`}
                                        </span>
                                        <span style={{fontSize:12,color:'var(--text3)',marginLeft:'auto'}}>
                                            {s.scenes?.length || 0} scenes
                                        </span>
                                        <span style={{color:'var(--text3)',fontSize:14}}>{isOpen ? '▲' : '▼'}</span>
                                    </div>

                                    {isOpen && (
                                        <div style={{padding:'0 16px 16px'}}>
                                            {/* Hook */}
                                            {s.hook && (
                                                <div style={{marginBottom:12,padding:'10px 12px',background:'var(--blue-dim)',borderRadius:'var(--r-sm)',borderLeft:'3px solid var(--blue)'}}>
                                                    <div style={{fontSize:11,color:'var(--blue)',fontWeight:700,marginBottom:4,textTransform:'uppercase'}}>Hook</div>
                                                    <div style={{fontSize:13,color:'var(--text)',lineHeight:1.5}}>{s.hook}</div>
                                                </div>
                                            )}

                                            {/* Scenes table */}
                                            <div style={{overflowX:'auto'}}>
                                                <table className="table" style={{width:'100%',tableLayout:'fixed'}}>
                                                    <colgroup>
                                                        <col style={{width:'40px'}}/>
                                                        <col style={{width:'100px'}}/>
                                                        <col style={{width:'35%'}}/>
                                                        <col/>
                                                        <col style={{width:'70px'}}/>
                                                        <col style={{width:'80px'}}/>
                                                    </colgroup>
                                                    <thead>
                                                        <tr>
                                                            <th>#</th>
                                                            <th>Segment</th>
                                                            <th>Voiceover</th>
                                                            <th>Visual Prompt</th>
                                                            <th>SFX</th>
                                                            <th>Copy</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody>
                                                        {(s.scenes || []).map((sc, idx) => {
                                                            const copyKey = `${key}:${idx}`;
                                                            const isCopied = copied === copyKey;
                                                            return (
                                                                <tr key={idx} style={{verticalAlign:'top'}}>
                                                                    <td style={{color:'var(--text3)',fontFamily:'monospace',fontSize:11}}>{idx+1}</td>
                                                                    <td style={{color:'var(--text2)',fontSize:11,wordBreak:'break-word'}}>{sc.segment}</td>
                                                                    <td style={{fontSize:12,lineHeight:1.5,color:'var(--text)'}}>{sc.voiceover}</td>
                                                                    <td style={{fontSize:12,lineHeight:1.4,color:'var(--text2)',fontStyle:'italic'}}>{sc.visual_prompt}</td>
                                                                    <td style={{fontSize:11,color:'var(--amber)'}}>{sc.sfx || '—'}</td>
                                                                    <td>
                                                                        <button
                                                                            className={`btn btn-sm ${isCopied ? 'btn-primary' : 'btn-ghost'}`}
                                                                            style={{fontSize:11,padding:'3px 8px',whiteSpace:'nowrap'}}
                                                                            onClick={() => copyPrompt(sc.visual_prompt, copyKey)}
                                                                            title={sc.visual_prompt}
                                                                        >
                                                                            {isCopied ? '✓ Copied' : '📋 Copy'}
                                                                        </button>
                                                                    </td>
                                                                </tr>
                                                            );
                                                        })}
                                                    </tbody>
                                                </table>
                                            </div>

                                            {/* Outro */}
                                            {s.outro && (
                                                <div style={{marginTop:12,padding:'10px 12px',background:'var(--surface2)',borderRadius:'var(--r-sm)',borderLeft:'3px solid var(--text3)'}}>
                                                    <div style={{fontSize:11,color:'var(--text3)',fontWeight:700,marginBottom:4,textTransform:'uppercase'}}>Outro</div>
                                                    <div style={{fontSize:12,color:'var(--text2)',lineHeight:1.5}}>{s.outro}</div>
                                                </div>
                                            )}

                                            {/* Debate log toggle */}
                                            {hasDebate && (
                                                <div style={{marginTop:12}}>
                                                    <button
                                                        className="btn btn-sm btn-ghost"
                                                        onClick={() => toggleDebate(key)}
                                                        style={{fontSize:11}}
                                                    >
                                                        🤖 {isDebateOpen ? 'Hide' : 'Show'} Agent Debate ({s.debate_rounds.length} rounds)
                                                    </button>

                                                    {isDebateOpen && (
                                                        <div style={{marginTop:10}}>
                                                            <div style={{fontSize:12,color:'var(--text3)',marginBottom:8,fontWeight:600}}>
                                                                Writer ↔ Critic debate rounds — variant_{s.variant_id}
                                                            </div>
                                                            {s.debate_rounds.map((rd, ri) => (
                                                                <div key={ri} style={{
                                                                    marginBottom:10,
                                                                    padding:'12px',
                                                                    background:'var(--surface2)',
                                                                    borderRadius:'var(--r-sm)',
                                                                    borderLeft:`3px solid ${rd.approved ? 'var(--green)' : rd.score >= 70 ? 'var(--amber)' : 'var(--red)'}`,
                                                                }}>
                                                                    <div style={{display:'flex',alignItems:'center',gap:10,marginBottom:8}}>
                                                                        <span style={{fontWeight:700,fontSize:13,color:'var(--text)'}}>Round {rd.round_number}</span>
                                                                        <span className={`tag ${rd.approved ? 'green' : rd.score >= 70 ? 'amber' : 'red'}`} style={{fontSize:10}}>
                                                                            {rd.approved ? '✅ Approved' : `Score ${rd.score}`}
                                                                        </span>
                                                                        <span style={{fontSize:11,color:'var(--text3)'}}>
                                                                            VO {rd.voiceover_score} · Prod {rd.production_score}
                                                                            {rd.score_delta !== 0 && (
                                                                                <span style={{color: rd.score_delta > 0 ? 'var(--green)' : 'var(--red)', marginLeft:6}}>
                                                                                    {rd.score_delta > 0 ? '+' : ''}{rd.score_delta}
                                                                                </span>
                                                                            )}
                                                                        </span>
                                                                        {rd.exit_reason && ri === s.debate_rounds.length - 1 && (
                                                                            <span className="tag purple" style={{fontSize:10,marginLeft:'auto'}}>{rd.exit_reason}</span>
                                                                        )}
                                                                    </div>

                                                                    {rd.rejection_reasons?.length > 0 && (
                                                                        <div style={{marginBottom:6}}>
                                                                            <div style={{fontSize:11,color:'var(--red)',fontWeight:600,marginBottom:3}}>🚫 Rejection reasons:</div>
                                                                            {rd.rejection_reasons.map((r, i) => (
                                                                                <div key={i} style={{fontSize:11,color:'var(--text2)',paddingLeft:12}}>• {r}</div>
                                                                            ))}
                                                                        </div>
                                                                    )}
                                                                    {rd.specific_fixes?.length > 0 && (
                                                                        <div style={{marginBottom:6}}>
                                                                            <div style={{fontSize:11,color:'var(--amber)',fontWeight:600,marginBottom:3}}>✏️ VO fixes requested:</div>
                                                                            {rd.specific_fixes.map((r, i) => (
                                                                                <div key={i} style={{fontSize:11,color:'var(--text2)',paddingLeft:12}}>• {r}</div>
                                                                            ))}
                                                                        </div>
                                                                    )}
                                                                    {rd.visual_fixes?.length > 0 && (
                                                                        <div>
                                                                            <div style={{fontSize:11,color:'var(--blue)',fontWeight:600,marginBottom:3}}>🎨 Visual fixes:</div>
                                                                            {rd.visual_fixes.map((r, i) => (
                                                                                <div key={i} style={{fontSize:11,color:'var(--text2)',paddingLeft:12}}>• {r}</div>
                                                                            ))}
                                                                        </div>
                                                                    )}
                                                                </div>
                                                            ))}
                                                        </div>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                );
            })}
        </div>
    );
}

// ── Sidebar ────────────────────────────────────────────────────────────────────
function Sidebar({ tab, setTab, activeJobs, niches, hotCount, infraAlert }) {
    const nav = [
        { id: 'home',     label: 'Dashboard',      icon: Ico.home },
        { id: 'pipeline', label: 'Pipeline',        icon: Ico.pipe,    badge: activeJobs > 0 ? activeJobs : null, badgeColor: 'amber' },
        { id: 'channels', label: 'Channels',        icon: Ico.channel },
        { id: 'destinations', label: 'Destinations', icon: Ico.target },
        { id: 'scripts',  label: 'Scripts',         icon: '📄' },
        { id: 'infra',    label: 'Infrastructure',  icon: Ico.infra,   badge: infraAlert > 0 ? infraAlert : null, badgeColor: 'red' },
        { id: 'niches',   label: 'Niche Discovery', icon: Ico.niche,   badge: niches > 0 ? niches : null, badgeColor: 'green' },
        { id: 'vault',    label: 'Niche Vault',     icon: Ico.vault,   badge: hotCount > 0 ? hotCount : null, badgeColor: 'red' },
        { id: 'budget',   label: 'Budget & Cost',   icon: Ico.budget },
    ];

    return (
        <div className="sidebar">
            <div className="sidebar-logo">
                <div className="logo-icon">O</div>
                <div>
                    <div className="logo-text">OmniCast</div>
                    <div className="logo-sub">Engine v2</div>
                </div>
            </div>

            <div className="nav-section">
                <div className="nav-label">Navigation</div>
                {nav.map(n => (
                    <button key={n.id} className={`nav-item ${tab===n.id?'active':''}`} onClick={() => setTab(n.id)}>
                        {n.icon}
                        <span style={{flex:1}}>{n.label}</span>
                        {n.badge && <span className={`nav-badge ${n.badgeColor||''}`}>{n.badge}</span>}
                    </button>
                ))}
            </div>
        </div>
    );
}

// ── App ────────────────────────────────────────────────────────────────────────
function App() {
    const [tab, setTab] = useState('home');
    const { data: pipeline } = useApi('/api/pipeline', 5000);
    const { data: niches } = useApi('/api/niches', 15000);
    const { data: vault } = useApi('/api/vault', 10000);
    const { data: infraEnv } = useApi('/api/infra', 5000);
    const { data: sysEnv } = useApi('/api/system/state', 4000);

    const activeJobs = pipeline?.active_jobs?.length || 0;
    const nicheCount = niches?.niches?.length || 0;
    const hotCount = (vault?.niches || []).filter(n => n.status === 'hot').length;

    // Infra alert count = down components + offline workers (rule #2: surface gates in nav)
    const infraPayload = infraEnv?.data;
    const infraAlert = (infraPayload
        ? (infraPayload.db?.ok ? 0 : 1) + (infraPayload.redis?.ok ? 0 : 1) + (infraPayload.summary?.offline || 0)
        : 0
    );
    const sysPaused = !!sysEnv?.data?.paused;

    const titles = {
        home: 'Dashboard', pipeline: 'Pipeline Monitor',
        channels: 'Channel Intelligence', scripts: 'Script Library',
        destinations: 'Destinations', infra: 'Infrastructure', niches: 'Niche Discovery',
        vault: 'Niche Vault', budget: 'Budget & Cost',
    };

    const statusText = activeJobs > 0 ? `${activeJobs} job${activeJobs>1?'s':''} running` : 'All Systems Idle';
    const statusClass = activeJobs > 0 ? 'loading' : 'online';

    return (
        <div className="app">
            <Sidebar tab={tab} setTab={setTab} activeJobs={activeJobs} niches={nicheCount} hotCount={hotCount} infraAlert={infraAlert} />

            <div className="main">
                <div className="topbar">
                    <div className="page-title">{titles[tab]}</div>
                    <div className="topbar-right" style={{display:'flex',gap:8}}>
                        <KillSwitchPill setTab={setTab} />
                        {!sysPaused && (
                            <div className={`status-pill ${statusClass}`}>
                                <span className="dot"/>
                                <span>{statusText}</span>
                            </div>
                        )}
                    </div>
                </div>

                <div className="content">
                    {tab === 'home'     && <DashboardHome />}
                    {tab === 'pipeline' && <Pipeline />}
                    {tab === 'channels' && <Channels />}
                    {tab === 'destinations' && <Destinations />}
                    {tab === 'scripts'  && <ScriptViewer />}
                    {tab === 'infra'    && <Infrastructure />}
                    {tab === 'niches'   && <NicheDiscovery />}
                    {tab === 'vault'    && <Vault />}
                    {tab === 'budget'   && <Budget />}
                </div>
            </div>
        </div>
    );
}

export default App;
