// ============================================
let _consecutiveFailures = 0;

function Icon({ name, size = 16, className = '', style = {} }) {
  return (
    <svg width={size} height={size} className={'ico ' + className} style={style}
         fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <use href={'assets/icons.svg#' + name} />
    </svg>
  );
}
window.Icon = Icon;
// OmniCast Engine — Mock Data + Icons
// ============================================

const I = {
  search: <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="7" cy="7" r="5"/><path d="M11 11l3 3"/></svg>,
  dashboard: <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7"><rect x="3" y="3" width="6" height="8" rx="1.5"/><rect x="11" y="3" width="6" height="5" rx="1.5"/><rect x="3" y="13" width="6" height="4" rx="1.5"/><rect x="11" y="10" width="6" height="7" rx="1.5"/></svg>,
  office: <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M3 17h14M5 17V6l5-3 5 3v11"/><path d="M8 9h0.01M12 9h0.01M8 13h0.01M12 13h0.01"/></svg>,
  channels: <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7"><rect x="2" y="4" width="16" height="11" rx="2"/><path d="M8 8.5l4 2-4 2z" fill="currentColor"/></svg>,
  scripts: <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M5 2h7l4 4v12H5z"/><path d="M12 2v4h4M8 11h5M8 14h5"/></svg>,
  scanner: <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="8.5" cy="8.5" r="5"/><path d="M12.5 12.5L17 17"/><path d="M8.5 6v5M6 8.5h5"/></svg>,
  vault: <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7"><rect x="3" y="3" width="14" height="14" rx="2"/><circle cx="10" cy="10" r="3"/><path d="M10 3v2M10 15v2"/></svg>,
  infra: <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7"><rect x="3" y="3" width="14" height="5" rx="1.5"/><rect x="3" y="12" width="14" height="5" rx="1.5"/><path d="M6 5.5h0.01M6 14.5h0.01"/></svg>,
  budget: <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="10" cy="10" r="7"/><path d="M10 6v8M8 8h3M8 12h3"/></svg>,
  create: <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7"><rect x="3" y="4" width="14" height="12" rx="2"/><path d="M3 8h14"/><path d="M10 11v3M8.5 12.5h3"/></svg>,
  film: <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7"><rect x="3" y="4" width="14" height="12" rx="2"/><path d="M3 8h14M3 12h14M7 4v12M13 4v12"/></svg>,
  bell: <svg width="17" height="17" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M6 8a4 4 0 018 0c0 4 1.5 5 1.5 5h-11S6 12 6 8z"/><path d="M8.5 16a1.5 1.5 0 003 0"/></svg>,
  menu: <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M3 6h14M3 10h14M3 14h14"/></svg>,
  bolt: <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M9 1L3 9h4l-1 6 6-8H8z"/></svg>,
  up: <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor"><path d="M8 3l5 6h-3v4H6V9H3z"/></svg>,
  coin: <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor"><circle cx="8" cy="8" r="6.5" opacity="0.25"/><circle cx="8" cy="8" r="4.5"/></svg>,
};

// Agents in the pipeline office
const AGENTS = [
  { id: 'research',  name: 'Research',         row: 1, col: 1, color: 'green',  icon: '🔍', species: 'fox' },
  { id: 'scorer',    name: 'Topic Scorer',     row: 1, col: 2, color: 'green',  icon: '📊', species: 'fox' },
  { id: 'scanner',   name: 'Competitor Scan',  row: 1, col: 3, color: 'green',  icon: '🛰️', species: 'fox' },

  { id: 'writer',    name: 'Writer',           row: 2, col: 1, color: 'blue',   icon: '✍️', species: 'cat' },
  { id: 'critic',    name: 'Critic',           row: 2, col: 2, color: 'red',    icon: '⚖️', species: 'horse' },
  { id: 'visual',    name: 'Visual Director',  row: 2, col: 3, color: 'purple', icon: '🎨', species: 'cat' },

  { id: 'media',     name: 'Media Engineer',   row: 3, col: 1, color: 'amber',  icon: '🎬', species: 'bear' },
  { id: 'compliance',name: 'Compliance',       row: 3, col: 2, color: 'gray',   icon: '✅', species: 'owl' },
  { id: 'quality',   name: 'Quality Check',    row: 3, col: 3, color: 'gray',   icon: '🔬', species: 'owl' },

  { id: 'upload',    name: 'Upload',           row: 4, col: 1, color: 'gray',   icon: '📤', species: 'bird' },
  { id: 'abtest',    name: 'A/B Test',         row: 4, col: 2, color: 'gray',   icon: '🧪', species: 'bird' },
  { id: 'analytics', name: 'Analytics',        row: 4, col: 3, color: 'gray',   icon: '📈', species: 'bird' },
];

const AGENT_COLOR = {
  blue: '#3b82f6', red: '#ef4444', purple: '#a855f7',
  green: '#22c55e', amber: '#f59e0b', gray: '#94a3b8',
};

// Initial activity feed
let FEED = [
  { id: 1, time: '12:10', dot: 'green',  title: 'Writer Agent bắt đầu viết', desc: '"5 crypto whales đang gom Bitcoin..."', token: 'Token: đang tính...', live: true },
  { id: 2, time: '12:08', dot: 'green',  title: 'Critic Agent approved', desc: 'Score: 82/100 ✅', token: 'Dùng: 1,847 tokens' },
  { id: 3, time: '12:05', dot: 'blue',   title: 'Research Agent hoàn thành', desc: 'Tổng hợp 14 nguồn', token: 'Dùng: 523 tokens' },
  { id: 4, time: '11:58', dot: 'purple', title: 'Visual Director xong', desc: '6 prompt ảnh đã tạo', token: 'Dùng: 912 tokens' },
  { id: 5, time: '11:42', dot: 'red',    title: 'Critic Agent rejected', desc: 'Score: 45/100 — hook yếu', token: 'Dùng: 1,203 tokens' },
];

let CHANNELS = [
  { id: 'ch_fin01', name: 'Tài Chính Thông Minh', niche: 'Personal Finance', sub: 'Investing', market: 'US', rpm: 15.30, status: 'active', health: 87,
    voice: 'Calm Mentor', tone: 'Authoritative, warm', hook: 'Bold claim + stat', visual: 'Cinematic minimal', color: '#1e40af', font: 'Editorial serif', dur: '8-12 min',
    competitors: '@GrahamStephan, @AndreiJikh', trends: 'index funds, FIRE, dividend', subs: 'r/financialindependence' },
  { id: 'ch_cry02', name: 'Crypto Việt', niche: 'Crypto', sub: 'Market Analysis', market: 'UK', rpm: 13.80, status: 'active', health: 91,
    voice: 'Sharp Analyst', tone: 'Energetic, urgent', hook: 'Contrarian take', visual: 'Neon data viz', color: '#7c3aed', font: 'Geometric sans', dur: '6-9 min',
    competitors: '@CoinBureau, @BitBoy', trends: 'BTC ETF, altseason, halving', subs: 'r/CryptoCurrency' },
  { id: 'ch_hea03', name: 'Sức Khỏe Vàng', niche: 'Health', sub: 'Longevity', market: 'US', rpm: 12.50, status: 'active', health: 72,
    voice: 'Trusted Doctor', tone: 'Reassuring, factual', hook: 'Myth-bust', visual: 'Clean documentary', color: '#0d9488', font: 'Humanist sans', dur: '10-14 min',
    competitors: '@hubermanlab, @drberg', trends: 'fasting, sleep, longevity', subs: 'r/longevity' },
  { id: 'ch_psy04', name: 'Tâm Lý Học', niche: 'Psychology', sub: 'Self-help', market: 'US', rpm: 11.20, status: 'paused', health: 68,
    voice: 'Thoughtful Guide', tone: 'Empathetic, deep', hook: 'Relatable scenario', visual: 'Soft illustrative', color: '#db2777', font: 'Rounded sans', dur: '8-11 min',
    competitors: '@Psych2go, @TheSchoolOfLife', trends: 'attachment, habits, anxiety', subs: 'r/psychology' },
  { id: 'ch_myt05', name: 'Thần Thoại Hy Lạp', niche: 'Mythology', sub: 'Storytelling', market: 'AU', rpm: 10.50, status: 'active', health: 79,
    voice: 'Epic Narrator', tone: 'Dramatic, immersive', hook: 'In-media-res', visual: 'Painterly epic', color: '#b45309', font: 'Display serif', dur: '12-18 min',
    competitors: '@MythologyExplained', trends: 'Zeus, Odyssey, Titans', subs: 'r/mythology' },
  { id: 'ch_tec06', name: 'Tech Innovations', niche: 'Technology', sub: 'AI & Future', market: 'CA', rpm: 14.20, status: 'active', health: 85,
    voice: 'Curious Futurist', tone: 'Excited, clear', hook: 'What-if question', visual: 'Sleek tech', color: '#0ea5e9', font: 'Mono accent', dur: '7-10 min',
    competitors: '@mkbhd, @ColdFusion', trends: 'AI agents, robotics, chips', subs: 'r/Futurology' },
];

let TOPICS = [
  { id: 't1', title: '5 crypto whales đang âm thầm gom Bitcoin', audience: 'Crypto investors', score: 88 },
  { id: 't2', title: 'Tại sao 90% trader thua lỗ trong 90 ngày', audience: 'New traders', score: 81 },
  { id: 't3', title: 'Bitcoin ETF: điều gì xảy ra tiếp theo?', audience: 'Long-term holders', score: 76 },
];

let VARIANTS = [
  {
    id: 'variant_a', topic: 't1', score: 88, scenes: 6,
    hook: '3 ví lạnh vừa rút 12.000 BTC khỏi sàn — đây là điều các cá voi không muốn bạn thấy.',
    sceneList: [
      { n: 1, visual: 'On-chain flow animation, glowing nodes', vo: 'Trong 48 giờ qua, blockchain ghi nhận một chuyển động bất thường...' },
      { n: 2, visual: 'Whale wallet dashboard, red highlights', vo: 'Ba ví ẩn danh đã gom hơn 12.000 Bitcoin...' },
      { n: 3, visual: 'Historical chart overlay 2020 vs now', vo: 'Mô hình này từng xuất hiện ngay trước đợt tăng giá 2020...' },
      { n: 4, visual: 'Split screen: fear index vs accumulation', vo: 'Trong khi đám đông hoảng loạn, cá voi lại lặng lẽ mua vào...' },
    ],
    outro: 'Nếu lịch sử lặp lại, 90 ngày tới sẽ rất thú vị. Bạn nghĩ sao? Để lại bình luận.',
    debate: [
      { side: 'Writer', tone: 'blue', text: 'Draft v1: hook dùng câu hỏi tu từ "Bạn có biết...".' },
      { side: 'Critic', tone: 'red', text: 'Reject. Hook yếu, câu hỏi tu từ bị cấm. Cần stat cụ thể. Score 58.' },
      { side: 'Writer', tone: 'blue', text: 'v2: thay bằng "3 ví lạnh rút 12.000 BTC". Thêm urgency.' },
      { side: 'Critic', tone: 'green', text: 'Approve. Hook mạnh, có số liệu, dưới 15 từ. Score 88.' },
    ],
  },
  {
    id: 'variant_b', topic: 't1', score: 74, scenes: 5,
    hook: 'Cá voi Bitcoin vừa làm một điều mà 99% nhà đầu tư đã bỏ lỡ.',
    sceneList: [
      { n: 1, visual: 'Ocean metaphor, whale silhouette', vo: 'Hãy tưởng tượng đại dương tài chính...' },
      { n: 2, visual: 'Data table of large transactions', vo: 'Các giao dịch lớn nhất tuần này đến từ đâu?' },
    ],
    outro: 'Theo dõi kênh để không bỏ lỡ động thái tiếp theo của cá voi.',
    debate: [
      { side: 'Writer', tone: 'blue', text: 'Draft: ẩn dụ đại dương cho hook.' },
      { side: 'Critic', tone: 'amber', text: 'OK nhưng ẩn dụ làm chậm hook. Score 74.' },
    ],
  },
];

let NICHES = [
  { rank: 1, name: 'AI Productivity Tools', market: 'US', cat: 'Tech', score: 94, rpm: 18.5, state: 'hot', note: 'Search +210% QoQ, low competition', video: '"I replaced my team with AI" — 4.2M views' },
  { rank: 2, name: 'Quantum Computing Explained', market: 'US', cat: 'Science', score: 89, rpm: 16.2, state: 'hot', note: 'Breakout, high RPM, evergreen', video: '"Quantum supremacy" — 2.8M views' },
  { rank: 3, name: 'Stoic Philosophy Daily', market: 'UK', cat: 'Education', score: 82, rpm: 11.8, state: 'watching', note: 'Steady growth, saturated top', video: '"Marcus Aurelius routine" — 1.9M' },
  { rank: 4, name: 'Deep Sea Mysteries', market: 'AU', cat: 'Documentary', score: 78, rpm: 9.4, state: 'watching', note: 'Seasonal spikes', video: '"What lives at 11km deep" — 3.1M' },
  { rank: 5, name: 'Retro Gaming History', market: 'US', cat: 'Gaming', score: 61, rpm: 7.2, state: 'stale', note: 'Declining interest', video: '"Why the SNES won" — 800K' },
];

let VAULT_NICHES = [
  { rank: 1, name: 'AI Productivity Tools', market: 'US', cat: 'Tech', score: 94, rpm: 18.5, state: 'hot', note: 'Search +210% QoQ, low competition', video: '"I replaced my team with AI" — 4.2M views' },
  { rank: 2, name: 'Quantum Computing Explained', market: 'US', cat: 'Science', score: 89, rpm: 16.2, state: 'hot', note: 'Breakout, high RPM, evergreen', video: '"Quantum supremacy" — 2.8M views' },
  { rank: 3, name: 'Stoic Philosophy Daily', market: 'UK', cat: 'Education', score: 82, rpm: 11.8, state: 'watching', note: 'Steady growth, saturated top', video: '"Marcus Aurelius routine" — 1.9M' },
  { rank: 4, name: 'Deep Sea Mysteries', market: 'AU', cat: 'Documentary', score: 78, rpm: 9.4, state: 'watching', note: 'Seasonal spikes', video: '"What lives at 11km deep" — 3.1M' },
];

let COMPONENTS = [
  { name: 'Master Orchestrator', icon: '🧠', status: 'up', latency: '12ms', version: 'v2.4.1', uptime: '23d 4h' },
  { name: 'PostgreSQL', icon: '🗄️', status: 'up', latency: '3ms', version: '16.2', uptime: '23d 4h' },
  { name: 'RabbitMQ', icon: '🐰', status: 'up', latency: '5ms', version: '3.13', uptime: '23d 4h' },
  { name: 'Redis Cache', icon: '⚡', status: 'up', latency: '1ms', version: '7.2', uptime: '23d 4h' },
  { name: 'ChromaDB (Vector)', icon: '🔢', status: 'up', latency: '8ms', version: '0.5.0', uptime: '18d 2h' },
  { name: 'GPU Render Node', icon: '🎮', status: 'degraded', latency: '142ms', version: 'CUDA 12.4', uptime: '6h 12m' },
  { name: 'TTS Service', icon: '🎙️', status: 'up', latency: '320ms', version: 'v1.8', uptime: '23d 4h' },
  { name: 'NAS Storage', icon: '💾', status: 'up', latency: '18ms', version: 'TrueNAS', uptime: '90d+' },
];

Object.assign(window, { I, AGENTS, AGENT_COLOR, FEED, CHANNELS, TOPICS, VARIANTS, NICHES, VAULT_NICHES, COMPONENTS });

// ============================================
// LIVE DATA LAYER — fetch real backend state and swap into the mutable
// globals above. Same-origin (served by FastAPI), so no CORS / port config.
// The mock values above act as instant first-paint defaults until the first
// fetch lands; afterwards they are overwritten with real data.
// ============================================
const OMNI_API = '';                 // same origin as the served page
const _PALETTE = ['#1e40af', '#7c3aed', '#0d9488', '#db2777', '#b45309', '#0ea5e9', '#dc2626', '#059669'];

async function _get(path, timeoutMs = 6000) {
  // Per-request timeout: a slow/hanging endpoint (e.g. /api/infra waiting on a
  // cold DB connection) must not block the whole Promise.all batch.
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(OMNI_API + path, { signal: ctrl.signal });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return await r.json();
  } finally {
    clearTimeout(timer);
  }
}
function _hhmm(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  if (isNaN(d)) return '';
  return d.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', hour12: false });
}
function _statusLabel(s) {
  const st = String(s || '');
  if (st.endsWith('_running') || st === 'running') return 'active';
  if (st === 'paused') return 'paused';
  if (st === 'active') return 'active';
  return 'idle';
}

function _mapChannel(c, i) {
  const score = (typeof c.last_score === 'number') ? Math.max(0, Math.min(100, c.last_score)) : null;
  return {
    id: c.channel_id || c.id || ('ch_' + i),
    name: c.name || c.channel_id || 'Channel',
    niche: c.niche || '',
    sub: c.sub_niche || '',
    market: c.market || '',
    rpm: (typeof c.rpm_floor === 'number') ? c.rpm_floor : 0,
    status: _statusLabel(c.status),
    health: score != null ? Math.min(100, score) : 75,
    voice: c.brand_voice || '',
    tone: c.current_phase ? ('Đang: ' + c.current_phase) : '—',
    hook: c.last_topic || c.current_topic || '—',
    visual: '—',
    color: _PALETTE[i % _PALETTE.length],
    font: '—',
    dur: '—',
    competitors: (c.competitor_handles || []).join(', ') || '—',
    trends: c.current_topic || '—',
    subs: '—',
    niches: c.niches || [],
    youtube_channel_id: c.youtube_channel_id || '',
  };
}
function _mapNiche(n, i) {
  const score = n.total_score ?? n.score ?? 0;
  return {
    rank: i + 1,
    niche_id: n.niche_id,
    name: n.niche_name || n.name || 'Niche',
    market: n.market || '—',
    cat: n.category || n.cat || '—',
    score: score,
    rpm: n.estimated_rpm ?? n.rpm ?? 0,
    state: score >= 85 ? 'hot' : score >= 75 ? 'watching' : 'stale',
    note: n.why_opportunity || n.note || '',
    video: (n.breakout_titles && n.breakout_titles[0]) || n.video || '',
    example_channels: n.example_channels || [],
    // Per-channel competitor evidence: [{channel, title, views, outlier_x, views_per_day}]
    evidence: (n.evidence || []).map(e => ({
      channel: e.channel || e.name || '',
      channel_url: e.channel_url || '',
      video_url: e.video_url || '',
      title: e.title || '',
      views: e.views || 0,
      vpd: e.views_per_day || e.vpd || 0,
      outlier: e.outlier_x || e.outlier || 0,
      channel_outlier: e.channel_outlier_x || 0,
      subs_k: e.subs_k || 0,
    })),
  };
}
function _mapVaultNiche(n, i) {
  const score = n.current_health ?? n.original_score ?? 0;
  return {
    rank: i + 1,
    niche_id: n.niche_id,
    name: n.niche_name || 'Niche',
    market: n.market || '—',
    cat: n.category || '—',
    score: score,
    rpm: n.estimated_rpm ?? 0,
    state: n.status || 'watching', // database status values: watching, hot, stale, active, archived
    note: n.why_opportunity || '',
    video: (n.breakout_titles && n.breakout_titles[0]) || '',
    example_channels: n.example_channels || [],
    evidence: (n.evidence || []).map(e => ({
      channel: e.channel || e.name || '',
      channel_url: e.channel_url || '',
      video_url: e.video_url || '',
      title: e.title || '',
      views: e.views || 0,
      vpd: e.views_per_day || e.vpd || 0,
      outlier: e.outlier_x || e.outlier || 0,
      channel_outlier: e.channel_outlier_x || 0,
      subs_k: e.subs_k || 0,
    })),
  };
}
function _mapFeed(pl) {
  const active = pl.active_jobs || [];
  const activeIds = new Set(active.map(j => j.channel_id));
  const dotFor = (status) => status === 'completed' ? 'green' : status === 'failed' ? 'red' : status === 'started' ? 'blue' : 'purple';
  const phaseVN = {
    niche_scan: 'Tìm ngách',
    discovery: 'Nghiên cứu',
    writing: 'Viết kịch bản',
    script_generation: 'Tạo kịch bản',
    image_generation: 'Tạo ảnh',
    critic: 'Phản biện',
    media: 'Dựng video',
    render: 'Dựng video',
    upload: 'Đăng YouTube',
    policy_scan: 'Kiểm tra chính sách',
    cancelled: 'Pipeline',
  };
  const statusVN = { completed: 'hoàn thành', started: 'bắt đầu', failed: 'thất bại', cancelled: 'đã hủy' };
  const items = (pl.recent_results || []).slice(0, 8).map((r, i) => ({
    id: r.ts || i,
    time: _hhmm(r.ts),
    dot: dotFor(r.status),
    title: (phaseVN[r.phase] || r.phase || 'Pipeline') + ' ' + (statusVN[r.status] || r.status || ''),
    desc: r.error ? ('⚠ ' + String(r.error).slice(0, 120)) : (r.topic ? '"' + r.topic + '"' : (r.channel_id || '')),
    token: typeof r.cost_usd === 'number' && r.cost_usd > 0 ? ('$' + r.cost_usd.toFixed(4)) : (r.score ? ('Score: ' + r.score) : ''),
    live: activeIds.has(r.channel_id) && r.status === 'started',
  }));
  return items.length ? items : FEED;
}

// ── Per-channel scripts + discovery (Scripts / Create / Production pages) ────────
function _cleanText(s) {
  // Some saved variants have polluted hook/outro fields ("SCENES: ```json...").
  // Strip everything from a "SCENES:" / code-fence marker onward.
  if (!s) return '';
  const cut = String(s).split(/SCENES:|```/)[0].trim();
  return cut || String(s).slice(0, 200);
}
function _mapVariant(v, i) {
  const scenes = Array.isArray(v.scenes) ? v.scenes : [];
  const rounds = Array.isArray(v.debate_rounds) ? v.debate_rounds : [];
  return {
    key: v.file || ((v.variant_id || 'v') + '_' + i),
    id: v.variant_id || ('v' + i),
    topic: v.topic || v.topic_slug || '',
    score: v.score != null ? v.score : 0,
    approved: !!v.approved,
    scenes: scenes.length,
    hook: _cleanText(v.hook),
    outro: _cleanText(v.outro),
    sceneList: scenes.map((s, k) => ({
      n: k + 1,
      visual: s.visual_prompt || s.segment || '',
      vo: s.voiceover || '',
      dur: s.duration_s || 5,
      sfx: s.sfx || '',
    })),
    debate: rounds.map(r => {
      const fixes = (r.rejection_reasons && r.rejection_reasons.length ? r.rejection_reasons : (r.specific_fixes || []));
      return {
        side: 'Critic · R' + (r.round_number != null ? r.round_number : '?'),
        tone: r.approved ? 'green' : (r.score >= 70 ? 'amber' : 'red'),
        text: 'Score ' + (r.score != null ? r.score : '?') + (fixes.length ? ' — ' + fixes.slice(0, 2).join('; ') : (r.approved ? ' — approved' : '')),
      };
    }),
  };
}
async function OmniLoadScripts(chId) {
  if (!chId) return;
  window.OMNI_SCRIPT_CH = chId;
  try {
    const [sc, dc] = await Promise.all([
      _get('/api/scripts/' + chId).catch(() => null),
      _get('/api/discovery/' + chId).catch(() => null),
    ]);
    window.OMNI_VARIANTS = (sc && Array.isArray(sc.scripts) ? sc.scripts : []).map(_mapVariant);
    const topics = [];
    if (dc && Array.isArray(dc.topics)) dc.topics.forEach(t => (t.topic_queue || []).forEach(q => topics.push(q)));
    window.OMNI_TOPICS = topics.map((q, i) => ({
      id: 't' + i,
      title: q.title || '(untitled)',
      audience: q.audience_segment || q.pain_point || q.content_angle || '',
      score: q.score || 0,
    }));
    window.OMNI_SCRIPT_META = { channel: chId, scripts: window.OMNI_VARIANTS.length, topics: window.OMNI_TOPICS.length };
    if (window.__omniRerender) window.__omniRerender();
  } catch (e) {
    console.warn('[OmniLoadScripts] failed', e);
  }
}
window.OmniLoadScripts = OmniLoadScripts;

let _lastSnap = '';
function _commit() {
  Object.assign(window, { FEED, CHANNELS, TOPICS, VARIANTS, NICHES, VAULT_NICHES, COMPONENTS });
  const snap = JSON.stringify({
    c: CHANNELS, n: NICHES, v: VAULT_NICHES, f: FEED, s: window.OMNI_STATUS,
    b: window.OMNI_BUDGET, k: COMPONENTS, r: window.OMNI_READINESS,
    d: window.OMNI_DESTINATIONS, p: window.OMNI_PLATFORMS,
    cr: window.OMNI_CREDENTIALS, of: window.OMNI_OFFERS,
    cap: window.OMNI_CAPABILITIES, bud: window.OMNI_BUDGETS, use: window.OMNI_USAGE,
    appr: window.OMNI_APPROVALS,
  });
  if (snap !== _lastSnap) {
    _lastSnap = snap;
    if (window.__omniRerender) window.__omniRerender();
  }
}
async function OmniLoad() {
  // Critical data first (fast endpoints) — assign + re-render immediately so the
  // UI never waits on a slow dependency.
  try {
    const [st, ch, ni, bg, pl, vt] = await Promise.all([
      _get('/api/status').catch(() => null),
      _get('/api/channels').catch(() => null),
      _get('/api/niches').catch(() => null),
      _get('/api/budget').catch(() => null),
      _get('/api/pipeline').catch(() => null),
      _get('/api/vault').catch(() => null),
    ]);
    if (ch && Array.isArray(ch.channels)) {
      CHANNELS = ch.channels.map(_mapChannel);
      // Default the Scripts/Create/Produce pages to a channel that has run before.
      if (!window.OMNI_SCRIPT_CH && ch.channels.length) {
        const def = ch.channels.find(c => c.last_topic) || ch.channels[0];
        OmniLoadScripts(def.channel_id);
      }
    }
    if (ni && Array.isArray(ni.niches)) {
      NICHES = ni.niches.map(_mapNiche);
      window.OMNI_NICHE_META = { analyzed: ni.channels_analyzed || 0, scanned_at: ni.scanned_at || null };
    }
    if (vt && Array.isArray(vt.niches)) {
      VAULT_NICHES = vt.niches.map(_mapVaultNiche);
    }
    if (pl) { FEED = _mapFeed(pl); window.OMNI_FEED = FEED; }
    window.OMNI_STATUS = st || window.OMNI_STATUS;
    window.OMNI_BUDGET = bg || window.OMNI_BUDGET;
    window.OMNI_PIPELINE = pl || window.OMNI_PIPELINE;
    // Server reachable iff the core /api/status call returned. Drives the topbar
    // health pill so a dead backend reads "offline" instead of a stale "running".
    if (st) {
      _consecutiveFailures = 0;
      window.__omniApiUp = 'green';
    } else {
      _consecutiveFailures++;
      window.__omniApiUp = _consecutiveFailures >= 3 ? 'red' : 'yellow';
    }
    _commit();
  } catch (e) {
    _consecutiveFailures++;
    window.__omniApiUp = _consecutiveFailures >= 3 ? 'red' : 'yellow';
    console.warn('[OmniLoad] core failed', e);
  }
  // Infra is best-effort and may be slow/unavailable (needs PostgreSQL+Redis);
  // load it independently so it never blocks the rest. Map the real db/redis/
  // workers health into the COMPONENTS list (no fake "all up" mock).
  _get('/api/infra').then(inf => {
    const d = (inf && inf.data) || inf || {};
    if (d.db || d.redis || d.workers) {
      const comps = [];
      const svc = (name, icon, s) => comps.push({
        name, icon,
        status: s && s.ok ? 'up' : 'offline',
        latency: s && s.ok ? 'ok' : '—',
        version: s && s.error ? String(s.error).split('\n')[0].slice(0, 40) : '',
        uptime: s && s.ok ? 'connected' : 'down',
      });
      svc('PostgreSQL', '🗄️', d.db);
      svc('Redis Cache', '⚡', d.redis);
      (d.workers || []).forEach((w, i) => comps.push({
        name: w.name || ('Worker ' + (i + 1)), icon: '⚙️',
        status: w.status || (w.ok ? 'up' : 'offline'),
        latency: w.latency || '—', version: w.version || '', uptime: w.uptime || '',
      }));
      if (comps.length) { COMPONENTS = comps; window.OMNI_INFRA = inf; _commit(); }
    } else if (inf && Array.isArray(inf.components) && inf.components.length) {
      COMPONENTS = inf.components; window.OMNI_INFRA = inf; _commit();
    }
  }).catch(() => {});
  // Render status/output (Video pages) — cheap (reads status.json, no browser).
  // NOTE: do NOT fetch /api/credits here — reading Flow credits launches a real
  // Chrome session, so it must be on-demand only (button), never on every load.
  // Credits during a render come from the render status.json (rs.credits).
  _get('/api/render/status').then(rs => { window.OMNI_RENDER = rs; _commit(); }).catch(() => {});
  _get('/api/render/latest').then(rl => { window.OMNI_RENDER_OUT = rl; _commit(); }).catch(() => {});
  // Channels management overview (KPIs + per-channel cached YouTube stats).
  _get('/api/channels/overview').then(ov => { window.OMNI_CH_OVERVIEW = ov; _commit(); }).catch(() => {});
  _get('/api/auto/status').then(a => { window.OMNI_AUTO = a; _commit(); }).catch(() => {});
  _get('/api/policy').then(p => { window.OMNI_POLICY = p; _commit(); }).catch(() => {});
  _get('/api/scheduler').then(sc => { window.OMNI_SCHED = sc; _commit(); }).catch(() => {});
  _get('/api/system/state').then(st => { window.OMNI_SYSTEM_STATE = st; _commit(); }).catch(() => {});
  _get('/api/platforms').then(p => { window.OMNI_PLATFORMS = p; _commit(); }).catch(() => {});
  _get('/api/destinations').then(d => { window.OMNI_DESTINATIONS = d; _commit(); }).catch(() => {});
  _get('/api/credentials').then(c => { window.OMNI_CREDENTIALS = c; _commit(); }).catch(() => {});
  _get('/api/monetization/offers').then(o => { window.OMNI_OFFERS = o; _commit(); }).catch(() => {});
  _get('/api/monetization/readiness').then(r => { window.OMNI_READINESS = r; _commit(); }).catch(() => {});
  _get('/api/capabilities').then(c => { window.OMNI_CAPABILITIES = c; _commit(); }).catch(() => {});
  _get('/api/budgets').then(b => { window.OMNI_BUDGETS = b; _commit(); }).catch(() => {});
  _get('/api/usage').then(u => { window.OMNI_USAGE = u; _commit(); }).catch(() => {});
  // Real error log (Dashboard "Lỗi gần đây" + Infra "Error Log").
  _get('/api/errors?limit=30').then(er => {
    const d = er || {};
    window.OMNI_ERRORS = (d.data && d.data.errors) || d.errors || (Array.isArray(d) ? d : []);
    _commit();
  }).catch(() => { window.OMNI_ERRORS = window.OMNI_ERRORS || []; });
}
window.OmniLoad = OmniLoad;

let _jobEventSource = null;
let _jobRefreshTimer = null;
function OmniConnectJobEvents() {
  if (_jobEventSource || typeof EventSource === 'undefined') return;
  try {
    _jobEventSource = new EventSource('/jobengine/api/v1/events/stream');
    _jobEventSource.onmessage = (ev) => {
      let data = null;
      try { data = JSON.parse(ev.data || '{}'); } catch (e) {}
      window.OMNI_JOB_EVENTS = [data].concat(window.OMNI_JOB_EVENTS || []).filter(Boolean).slice(0, 100);
      window.dispatchEvent(new CustomEvent('omni:job-event', { detail: data }));
      
      // Propagate real-time progress updates directly to OMNI_PIPELINE
      if (data && data.job_id && data.progress_pct != null && window.OMNI_PIPELINE && window.OMNI_PIPELINE.active_jobs) {
        const job = window.OMNI_PIPELINE.active_jobs.find(j => j.job_id === data.job_id);
        if (job) {
          job.progress_pct = data.progress_pct;
          if (data.current_step) job.phase = data.current_step;
          if (window.__omniRerender) window.__omniRerender();
        }
      }
      
      clearTimeout(_jobRefreshTimer);
      _jobRefreshTimer = setTimeout(() => { if (window.OmniLoad) window.OmniLoad(); }, 250);
    };
    _jobEventSource.onerror = () => {
      try { _jobEventSource.close(); } catch (e) {}
      _jobEventSource = null;
      setTimeout(OmniConnectJobEvents, 5000);
    };
  } catch (e) {
    _jobEventSource = null;
  }
}
window.OmniConnectJobEvents = OmniConnectJobEvents;

// ── Action helpers (POST to backend) — used by buttons across pages ──────────────
async function _post(path, body) {
  const r = await fetch(OMNI_API + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error('HTTP ' + r.status + ' on ' + path);
  return r.json().catch(() => ({}));
}
async function _del(path) {
  const r = await fetch(OMNI_API + path, { method: 'DELETE' });
  if (!r.ok) throw new Error('HTTP ' + r.status + ' on ' + path);
  return r.json().catch(() => ({}));
}
// Wrap an action with a toast + auto-refresh so every button gives feedback.
function _toast(msg, ok = true) {
  window._toast = _toast;
  let el = document.getElementById('__omni_toast');
  if (!el) {
    el = document.createElement('div');
    el.id = '__omni_toast';
    el.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);z-index:99999;padding:10px 18px;border-radius:10px;font:600 13px/1.4 Inter,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.18);transition:opacity .3s;color:#fff';
    document.body.appendChild(el);
  }
  el.style.background = ok ? '#16a34a' : '#dc2626';
  el.textContent = msg;
  el.style.opacity = '1';
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.style.opacity = '0'; }, 3200);
}
function _run(label, p) {
  return p.then(r => { _toast(label + ' ✓'); OmniLoad(); return r; })
          .catch(e => { _toast(label + ' ✗ ' + e.message, false); throw e; });
}
const OmniActions = {
  discoverNiches: () => _run('Quét niche', _post('/api/discover-niches')),
  runChannel: (id) => _run('Phase 1 — Discovery', _post('/api/run/' + id)),
  runScript: (id, topic, opts) => _run('Phase 2 — Script', _post('/api/run/' + id + '/script', {
    topic: topic || '',
    desc: (opts && opts.desc) || '',
    audience: (opts && opts.audience) || '',
  })),
  cancelRun: (id) => _run('Hủy run', _post('/api/run/' + id + '/cancel')),
  deleteChannel: (id) => _run('Xóa kênh', _del('/api/channels/' + id)),
  createChannel: (body) => _run('Tạo kênh', _post('/api/channels', body)),
  updateChannel: (id, body) => _run('Lưu kênh', fetch('/api/channels/' + id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })),
  vaultToChannel: (nicheId) => _run('Tạo kênh từ niche', _post('/api/vault/create-channel/' + nicheId)),
  vaultHealthCheck: () => _run('Health check', _post('/api/vault/health-check')),
  saveVault: () => _run('Lưu vault', _post('/api/vault/save-all')),
  archiveNiche: (nicheId) => _run('Archive niche', _post('/api/vault/archive/' + nicheId)),
  startRender: (id, opts) => {
    // Forward render overrides as query params (script, beat_words, shorts, style,
    // voice, voice_rate, voice_pitch, music, music_volume, music_mood). Omitted
    // keys fall back to the channel config defaults on the backend.
    const qs = Object.entries(opts || {})
      .filter(([, v]) => v !== undefined && v !== null && v !== '')
      .map(([k, v]) => k + '=' + encodeURIComponent(v))
      .join('&');
    return _run('Sản xuất video', _post('/api/render/' + id + (qs ? '?' + qs : '')));
  },
  uploadVideo: (id, privacy) => _run('Gửi duyệt đăng', _post('/api/publish/' + id, { privacy_status: privacy || 'private' })).then(() => OmniActions.refreshMonetization()),
  uploadStatus: (id) => fetch('/api/upload/status/' + id).then(r => r.json()),
  refreshChannelStats: (id) => _run('Cập nhật số liệu', _post('/api/channels/refresh-stats' + (id ? '?channel_id=' + id : ''))).then(r => { _get('/api/channels/overview').then(ov => { window.OMNI_CH_OVERVIEW = ov; if (window.__omniRerender) window.__omniRerender(); }); return r; }),
  channelDetail: (id) => fetch('/api/channels/' + id + '/detail').then(r => r.json()),
  loadTopics: (id) => fetch('/api/topics/' + id).then(r => r.json()).then(d => { window.OMNI_TOPIC_VAULT = d; if (window.__omniRerender) window.__omniRerender(); return d; }),
  scriptFromTopic: (id, topicId) => fetch('/api/topics/' + id + '/' + topicId + '/script', { method: 'POST' }).then(async r => {
    const d = await r.json().catch(() => ({}));
    if (r.status === 409 && d.dedup) {
      const ms = (d.dedup.matches || []).map(m => `• [${m.scope === 'same_channel' ? 'CÙNG KÊNH' : 'kênh khác'}] "${m.title}" (${Math.round(m.similarity * 100)}%)`).join('\n');
      if (d.dedup.severity === 'block') { alert('⛔ ' + d.message + '\n\n' + ms); throw new Error('duplicate_blocked'); }
      if (!confirm('⚠ ' + d.message + '\n\n' + ms + '\n\nVẫn tạo?')) throw new Error('cancelled');
      return fetch('/api/topics/' + id + '/' + topicId + '/script?force=true', { method: 'POST' }).then(rr => { if (!rr.ok) throw new Error('HTTP ' + rr.status); _toast('Tạo kịch bản (bỏ qua cảnh báo) ✓', true); return rr.json(); });
    }
    if (!r.ok) throw new Error('HTTP ' + r.status);
    _toast('Tạo kịch bản từ topic ✓', true); return d;
  }).catch(e => { if (e.message !== 'cancelled' && e.message !== 'duplicate_blocked') _toast('Tạo kịch bản ✗ ' + e.message, false); throw e; }),
  dedupCheck: (id, title) => fetch('/api/dedup/check?channel_id=' + id + '&title=' + encodeURIComponent(title)).then(r => r.json()),
  skipTopic: (id, topicId) => _run('Bỏ topic', _post('/api/topics/' + id + '/' + topicId + '/skip')).then(() => OmniActions.loadTopics(id)),
  requeueTopic: (id, topicId) => _run('Khôi phục topic', _post('/api/topics/' + id + '/' + topicId + '/requeue')).then(() => OmniActions.loadTopics(id)),
  autoRun: (id, upload) => _run(id ? 'Auto-Pilot kênh' : 'Auto-Pilot tất cả', _post('/api/auto/run' + '?upload=' + (upload ? 'true' : 'false') + (id ? '&channel_id=' + id : ''))),
  autoStatus: () => fetch('/api/auto/status').then(r => r.json()).then(d => { window.OMNI_AUTO = d; if (window.__omniRerender) window.__omniRerender(); return d; }),
  loadPolicy: () => fetch('/api/policy').then(r => r.json()).then(d => { window.OMNI_POLICY = d; if (window.__omniRerender) window.__omniRerender(); return d; }),
  policyFetch: () => _run('Quét chính sách YouTube', _post('/api/policy/fetch')),
  policyRule: (id, action) => _run(action === 'approve' ? 'Duyệt rule' : 'Bỏ rule', _post('/api/policy/rules/' + id + '/' + action)).then(() => OmniActions.loadPolicy()),
  loadScheduler: () => fetch('/api/scheduler').then(r => r.json()).then(d => { window.OMNI_SCHED = d; if (window.__omniRerender) window.__omniRerender(); return d; }),
  schedulerMaster: (on) => _run(on ? 'Bật lịch tự động' : 'Tắt lịch', _post('/api/scheduler/toggle?enabled=' + (on ? 'true' : 'false'))).then(() => OmniActions.loadScheduler()),
  setChannelSchedule: (cid, params) => { const qs = Object.entries(params).map(([k, v]) => k + '=' + encodeURIComponent(v)).join('&'); return _run('Lưu lịch kênh', _post('/api/scheduler/channel/' + cid + '?' + qs)).then(() => OmniActions.loadScheduler()); },
  refreshMonetization: () => Promise.all([
    _get('/api/platforms').then(p => { window.OMNI_PLATFORMS = p; }),
    _get('/api/destinations').then(d => { window.OMNI_DESTINATIONS = d; }),
    _get('/api/credentials').then(c => { window.OMNI_CREDENTIALS = c; }),
    _get('/api/monetization/offers').then(o => { window.OMNI_OFFERS = o; }),
    _get('/api/monetization/readiness').then(r => { window.OMNI_READINESS = r; }),
    _get('/api/capabilities').then(c => { window.OMNI_CAPABILITIES = c; }),
    _get('/api/budgets').then(b => { window.OMNI_BUDGETS = b; }),
    _get('/api/usage').then(u => { window.OMNI_USAGE = u; }),
    _get('/api/approvals').then(a => { window.OMNI_APPROVALS = a; }),
    _get('/api/system/state').then(st => { window.OMNI_SYSTEM_STATE = st; }),
  ]).then(() => { _commit(); return window.OMNI_READINESS; }),
  storeCredential: (body) => _run('Lưu credential', _post('/api/credentials', body)).then(() => OmniActions.refreshMonetization()),
  saveOffer: (body) => _run('Lưu offer', _post('/api/monetization/offers', body)).then(() => OmniActions.refreshMonetization()),
  saveBudget: (body) => _run('Lưu budget', _post('/api/budgets', body)).then(() => OmniActions.refreshMonetization()),
  systemPause: () => _run('Kill-switch pause', _post('/api/system/pause', { operator: 'dashboard' })),
  systemResume: () => _run('Kill-switch resume', _post('/api/system/resume', { operator: 'dashboard' })),
  approvalDecision: (id, decision, payload = {}) => _run(decision === 'approve' ? 'Duyệt & đăng' : 'Từ chối đăng', _post('/api/approvals/' + encodeURIComponent(id) + '/' + decision, Object.assign({ operator: 'dashboard' }, payload))).then(res => { OmniActions.refreshMonetization(); return res; }),
  testCapability: (kind, providerId, capabilityId) => {
    const key = capabilityId || (kind + ':' + providerId);
    const path = '/api/capabilities/' + encodeURIComponent(kind) + '/' + encodeURIComponent(providerId) + '/health';
    return fetch(OMNI_API + path, { method: 'POST' })
      .then(async r => {
        const body = await r.json().catch(() => ({ ok: false, error: 'HTTP ' + r.status }));
        const ok = r.ok && body.ok !== false;
        window.OMNI_PROVIDER_HEALTH = Object.assign({}, window.OMNI_PROVIDER_HEALTH || {}, {
          [key]: Object.assign({}, body, { ok, status: r.status, checked_at: new Date().toISOString() }),
        });
        _toast((ok ? 'Provider OK: ' : 'Provider loi: ') + providerId, ok);
        _commit();
        return body;
      })
      .catch(e => {
        window.OMNI_PROVIDER_HEALTH = Object.assign({}, window.OMNI_PROVIDER_HEALTH || {}, {
          [key]: { ok: false, provider_id: providerId, capability: kind, error: e.message, checked_at: new Date().toISOString() },
        });
        _toast('Provider loi: ' + providerId + ' - ' + e.message, false);
        _commit();
        return window.OMNI_PROVIDER_HEALTH[key];
      });
  },
};
window.OmniActions = OmniActions;
window.OMNI_FMT_TIME = _hhmm;

// Poll render status while a render is active (every 3s) so the Video pages
// show real per-shot progress + the finished video.
setInterval(() => {
  _get('/api/render/status').then(rs => {
    const prev = JSON.stringify(window.OMNI_RENDER || {});
    window.OMNI_RENDER = rs;
    if (JSON.stringify(rs) !== prev) {
      _get('/api/render/latest').then(rl => { window.OMNI_RENDER_OUT = rl; if (window.__omniRerender) window.__omniRerender(); }).catch(() => {});
      if (window.__omniRerender) window.__omniRerender();
    }
  }).catch(() => {});
}, 3000);

function Skeleton({ w = '100%', h = '20px', style = {} }) {
  const css = Object.assign({
    width: w,
    height: h,
    borderRadius: 'var(--r-sm)',
    background: 'var(--surface3)',
    position: 'relative',
    overflow: 'hidden'
  }, style);
  return <div className="shimmer-loader" style={css} />;
}
window.Skeleton = Skeleton;

function EmptyState({ icon, title, desc, actionLabel, onAction }) {
  return (
    <div className="empty-state" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '32px 16px', textAlign: 'center', width: '100%', maxWidth: 480, margin: '20px auto' }}>
      {icon && <div style={{ color: 'var(--text3)', marginBottom: 12 }}>{icon}</div>}
      <h4 style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text)', margin: '0 0 6px 0' }}>{title}</h4>
      <p style={{ fontSize: '13px', color: 'var(--text3)', margin: '0 0 16px 0', lineHeight: 1.5 }}>{desc}</p>
      {actionLabel && onAction && (
        <button className="btn btn-ghost sm" onClick={onAction}>{actionLabel}</button>
      )}
    </div>
  );
}
window.EmptyState = EmptyState;
