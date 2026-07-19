// ============================================
// OmniCast Engine — Video Production + Create Studio
// ============================================
const { useState: vS } = React;

// cinematic mood gradients for scene thumbnails
const GRADS = [
  'linear-gradient(135deg,#3a2a4d,#6b3a2a)', 'linear-gradient(135deg,#2a3a4d,#1a2233)',
  'linear-gradient(135deg,#4d3a2a,#7a5230)', 'linear-gradient(135deg,#2a2a3a,#4a2a3a)',
  'linear-gradient(135deg,#3a2a2a,#5a3030)', 'linear-gradient(135deg,#2a3a3a,#1a3340)',
  'linear-gradient(135deg,#4a3520,#2a2418)', 'linear-gradient(135deg,#352040,#20243a)',
  'linear-gradient(135deg,#402028,#5a2a30)', 'linear-gradient(135deg,#203540,#2a4a4a)',
  'linear-gradient(135deg,#3a3020,#503e22)', 'linear-gradient(135deg,#2a2040,#3a2a55)',
];

const ALL_DONE = { script: 'done', image: 'done', voice: 'done', subtitle: 'done', render: 'done' };

function scenesDone(narrations) {
  return narrations.map((nar, i) => ({
    n: i + 1, dur: 5 + (i % 4), narration: nar,
    image_prompt: 'Cinematic wide shot, dramatic chiaroscuro lighting, dust and haze, ancient Roman road at dawn, photorealistic, 35mm film grain, shallow depth of field',
    video_prompt: 'Slow dolly-in, subtle wind moving dust, golden hour light shift, gentle parallax on background figures, 5s',
    voice: 'Epic Narrator — trầm, chậm rãi', transition: i % 3 === 0 ? 'fade' : 'cut',
    stages: { ...ALL_DONE }, grad: GRADS[i % GRADS.length],
  }));
}

const PRODUCTIONS = [
  {
    id: 'p1', title: 'Dặm Thứ Hai: Phản Kháng Không Bạo Lực', channel: 'Thần Thoại Hy Lạp', channel_id: 'myth_greek_us',
    status: 'completed', ratio: '16:9 — YouTube ngang', lang: 'Tiếng Việt', log: 'Pipeline completed', logTime: '02:20:21.158',
    scenes: scenesDone([
      'Nếu có người bắt anh đi một dặm, hãy đi với người ấy hai dặm. Nghe như lời dạy phải tuân theo nhiều hơn, nhưng thực ra là một chiến lược phản kháng tinh vi.',
      'Để hiểu câu này, phải bước vào bối cảnh Giu-đê dưới sự chiếm đóng của La Mã. Lính đế quốc có quyền chiếm dụng dân thường bất cứ lúc nào.',
      'Nhưng quyền lực ấy có một giới hạn rất quan trọng. Theo luật La Mã, người lính chỉ được ép dân thường đi đúng một dặm — không hơn.',
      'Hãy tưởng tượng bạn là một người Do Thái. Một lính La Mã chặn bạn lại và ép vác hành lý nặng của hắn suốt một dặm đường.',
      'Thông thường chỉ có hai phản ứng: phục tùng trong cay đắng, hoặc chống trả. Nhưng Chúa Giê-su đề xuất một con đường thứ ba.',
      'Khi người bị ép chủ động đi quá một dặm, mọi cán cân đảo chiều. Người lính giờ rơi vào thế vi phạm chính luật của mình.',
      'Đột nhiên, người bị ép buộc lại là người kiểm soát tình huống. Người dân lại tiếp tục bước đi, còn người lính bối rối.',
      'Đây không phải là cam chịu. Đây là phản kháng phi bạo lực — giành lại phẩm giá bằng cách lật ngược vai trò nạn nhân.',
      'Điều thú vị là ba ảnh hình trong Bài Giảng Trên Núi đều theo cùng một logic: đưa má trái, cho luôn áo ngoài, đi thêm một dặm.',
      'Ngày nay, ta thường đọc câu này như lời khuyên cá nhân: hãy cố gắng hơn. Nhưng với người Do Thái thế kỷ thứ nhất, nó mang sức nặng chính trị.',
      'Gandhi và Martin Luther King sau này đã biến chính nguyên tắc ấy thành vũ khí thay đổi cả lịch sử nhân loại.',
      'Vậy "đi hai dặm" không phải là yếu đuối. Đó là sức mạnh của người chọn không bị khuất phục — kể cả khi không có quyền lực.',
    ]),
  },
  {
    id: 'p2', title: '5 Crypto Whales Đang Âm Thầm Gom Bitcoin', channel: 'Crypto Việt', channel_id: 'crypto_viet',
    status: 'producing', ratio: '16:9 — YouTube ngang', lang: 'Tiếng Việt', log: 'Đang render scene 3/8 · GPU node #2', logTime: '12:18:04.902',
    scenes: [
      { n: 1, dur: 6, narration: '3 ví lạnh vừa rút 12.000 BTC khỏi sàn — đây là điều các cá voi không muốn bạn thấy.', stages: { script: 'done', image: 'done', voice: 'done', subtitle: 'done', render: 'done' }, grad: GRADS[1] },
      { n: 2, dur: 7, narration: 'Trong 48 giờ qua, blockchain ghi nhận một chuyển động bất thường từ các ví tổ chức.', stages: { script: 'done', image: 'done', voice: 'done', subtitle: 'done', render: 'done' }, grad: GRADS[5] },
      { n: 3, dur: 5, narration: 'Ba ví ẩn danh đã gom hơn 12.000 Bitcoin, trị giá gần 800 triệu đô la.', stages: { script: 'done', image: 'done', voice: 'done', subtitle: 'active', render: 'active' }, grad: GRADS[9] },
      { n: 4, dur: 6, narration: 'Mô hình tích lũy này từng xuất hiện ngay trước đợt tăng giá lịch sử năm 2020.', stages: { script: 'done', image: 'done', voice: 'active', subtitle: 'pending', render: 'pending' }, grad: GRADS[3] },
      { n: 5, dur: 5, narration: 'Trong khi đám đông hoảng loạn bán tháo, cá voi lại lặng lẽ mua vào từng đợt.', stages: { script: 'done', image: 'active', voice: 'pending', subtitle: 'pending', render: 'pending' }, grad: GRADS[7] },
      { n: 6, dur: 6, narration: 'Dữ liệu on-chain cho thấy dòng tiền chảy ra khỏi các sàn giao dịch tập trung.', stages: { script: 'done', image: 'pending', voice: 'pending', subtitle: 'pending', render: 'pending' }, grad: GRADS[11] },
      { n: 7, dur: 5, narration: 'Liệu đây có phải tín hiệu cho một chu kỳ tăng giá mới? Hãy cùng phân tích.', stages: { script: 'done', image: 'pending', voice: 'pending', subtitle: 'pending', render: 'pending' }, grad: GRADS[0] },
      { n: 8, dur: 7, narration: 'Nếu lịch sử lặp lại, 90 ngày tới sẽ rất thú vị. Bạn nghĩ sao? Để lại bình luận.', stages: { script: 'done', image: 'pending', voice: 'pending', subtitle: 'pending', render: 'pending' }, grad: GRADS[4] },
    ].map(s => ({ ...s, image_prompt: 'On-chain data visualization, glowing blue nodes, dark trading floor, neon candlestick charts, cinematic, volumetric light', video_prompt: 'Animated data flow, pulsing nodes, camera push-in on chart, 5s', voice: 'Sharp Analyst — năng lượng cao', transition: 'cut' })),
  },
  {
    id: 'p3', title: 'Bí Mật Sống Thọ Của Người Nhật', channel: 'Sức Khỏe Vàng', channel_id: 'health_nutrition_us',
    status: 'queued', ratio: '16:9 — YouTube ngang', lang: 'Tiếng Việt', log: 'Trong hàng đợi · chờ slot render', logTime: '—',
    scenes: scenesDone(['Vùng Okinawa của Nhật Bản có tỉ lệ người sống trên trăm tuổi cao nhất thế giới.', 'Bí mật không nằm ở gen, mà ở lối sống và chế độ ăn hàng ngày.', 'Khái niệm "hara hachi bu" — chỉ ăn no đến 80%.', 'Cộng đồng gắn kết và mục đích sống "ikigai" giữ tinh thần luôn tích cực.'])
      .map(s => ({ ...s, stages: { script: 'done', image: 'pending', voice: 'pending', subtitle: 'pending', render: 'pending' } })),
  },
];

const STAGE_DEFS = [
  { key: 'script', short: 'Scr', label: 'Script' },
  { key: 'image', short: 'Ảnh', label: 'Hình ảnh' },
  { key: 'voice', short: 'Giọng', label: 'Giọng đọc' },
  { key: 'subtitle', short: 'Phụ', label: 'Phụ đề' },
  { key: 'render', short: 'Ren', label: 'Render' },
];

function sceneOverall(scene) {
  const v = Object.values(scene.stages);
  if (v.includes('error')) return 'error';
  if (v.every(x => x === 'done')) return 'done';
  if (v.includes('active')) return 'render';
  return 'wait';
}

function Check() { return <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M2.5 6.5l2.5 2.5 4.5-5"/></svg>; }

function StageChip({ def, state }) {
  return (
    <span className={`chip ${state === 'done' ? 'done' : state === 'active' ? 'active' : state === 'error' ? 'error' : ''}`}>
      {state === 'done' && <span className="chip-ic"><Check /></span>}
      {state === 'active' && <span className="mini-spin"></span>}
      {def.short}
    </span>
  );
}

function SceneCard({ scene, channelId, onOpen }) {
  const overall = sceneOverall(scene);
  const badge = { done: ['done', '<Icon name="check" /> Video'], render: ['render', '<Icon name="refresh-cw" /> Rendering'], wait: ['wait', 'Đang chờ'], error: ['error', '<Icon name="alert-triangle" /> Lỗi'] }[overall];
  const [imgErr, setImgErr] = React.useState(false);
  const padN = String(scene.n - 1).padStart(2, '0');
  const imgUrl = (channelId && scene.stages.image === 'done') ? `/media/${channelId}/_assets/scene_${padN}_illu.png` : null;

  return (
    <div className="scene-card">
      <div className="scene-thumb" style={{ background: scene.grad }}>
        {imgUrl && !imgErr && (
          <img 
            src={imgUrl} 
            style={{ width: '100%', height: '100%', objectFit: 'cover' }} 
            onError={() => setImgErr(true)} 
          />
        )}
        <span className={`st-badge ${badge[0]}`}>{badge[1]}</span>
        {overall === 'done' && <div className="st-play" onClick={() => onOpen(scene)}><Icon name="play" /></div>}
        {overall === 'render' && <div className="st-overlay"><div className="spin-lg"></div>Đang dựng...</div>}
        {overall === 'wait' && <div className="st-overlay" style={{ opacity: 0.7 }}><Icon name="clock" /> Đang chờ</div>}
        <span className="st-dur">{scene.dur}s</span>
      </div>
      <div className="scene-body">
        <div className="scene-head">
          <span className="scene-name">Cảnh {scene.n}</span>
          <span className="tag gray" style={{ fontSize: 10 }}>{scene.transition}</span>
        </div>
        <div className="scene-text">{scene.narration}</div>
        <div className="stage-chips">
          {STAGE_DEFS.map(d => <StageChip key={d.key} def={d} state={scene.stages[d.key]} />)}
        </div>
        <div className="scene-actions">
          <button className="scene-btn" onClick={() => onOpen(scene)}><Icon name="file-text" /> Chi tiết</button>
          <button className="scene-btn primary" onClick={() => onOpen(scene)}><Icon name="play" /> Xem</button>
        </div>
      </div>
    </div>
  );
}

function SceneDetail({ scene, prod, onClose }) {
  const [imgErr, setImgErr] = React.useState(false);
  const padN = String(scene.n - 1).padStart(2, '0');
  const imgUrl = (prod.channel_id && scene.stages.image === 'done') ? `/media/${prod.channel_id}/_assets/scene_${padN}_illu.png` : null;
  const overall = sceneOverall(scene);

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="side-panel" onClick={e => e.stopPropagation()}>
        <div className="sp-head">
          <div>
            <div className="sp-title">Cảnh {scene.n}</div>
            <div style={{ fontSize: 12, color: 'var(--text3)' }}>{prod.title}</div>
          </div>
          <button className="sp-close" onClick={onClose}>✕</button>
        </div>
        <div className="sp-body">
          <div className="scene-thumb" style={{ background: scene.grad, borderRadius: 'var(--r-md)', aspectRatio: '16/9', position: 'relative', overflow: 'hidden' }}>
            {scene.render_output ? (
              (scene.render_output.endsWith('.mp3') || scene.render_output.endsWith('.wav') || scene.render_output.endsWith('.ogg')) ? (
                <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative' }}>
                  {imgUrl && !imgErr && (
                    <img 
                      src={imgUrl} 
                      style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: 'var(--r-md)', position: 'absolute', inset: 0 }} 
                      onError={() => setImgErr(true)} 
                    />
                  )}
                  <audio controls src={window.getMediaUrl ? window.getMediaUrl(scene.render_output) : scene.render_output} style={{ width: '90%', zIndex: 2 }} />
                </div>
              ) : (
                <video controls src={window.getMediaUrl ? window.getMediaUrl(scene.render_output) : scene.render_output} style={{ width: '100%', height: '100%', objectFit: 'contain', borderRadius: 'var(--r-md)' }} />
              )
            ) : (
              <>
                {imgUrl && !imgErr && (
                  <img 
                    src={imgUrl} 
                    style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: 'var(--r-md)', position: 'absolute', inset: 0 }} 
                    onError={() => setImgErr(true)} 
                  />
                )}
                {overall === 'done' ? (
                  <div className="st-overlay"><div className="spin-lg"></div></div>
                ) : overall === 'render' ? (
                  <div className="st-overlay"><div className="spin-lg"></div></div>
                ) : (
                  <div className="st-overlay" style={{ opacity: 0.7 }}><Icon name="clock" /></div>
                )}
              </>
            )}
            <span className="st-dur">{scene.dur}s</span>
          </div>

          <div className="sp-field">
            <label>Tiến trình sản xuất</label>
            <div className="stage-track">
              {STAGE_DEFS.map(d => {
                const st = scene.stages[d.key];
                return (
                  <div className="stage-step" key={d.key}>
                    <span className={`ss-dot ${st}`}>{st === 'done' ? '<Icon name="check" />' : st === 'active' ? '' : st === 'error' ? '!' : ''}{st === 'active' && <span className="mini-spin" style={{ borderColor: 'rgba(255,255,255,0.4)', borderTopColor: '#fff' }}></span>}</span>
                    <div style={{ flex: 1 }}>
                      <div className="ss-name">{d.label}</div>
                      <div className="ss-meta">{st === 'done' ? 'Hoàn thành' : st === 'active' ? 'Đang xử lý...' : st === 'error' ? 'Lỗi — cần retry' : 'Chờ xử lý'}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="sp-field"><label>Lời thoại (Narration)</label><div className="sp-val">{scene.narration}</div></div>
          <div className="sp-field"><label>Giọng đọc</label><div className="sp-val">{scene.voice}</div></div>
          <div className="sp-field"><label>Image Prompt</label><div className="prompt-box">{scene.image_prompt}</div></div>
          <div className="sp-field"><label>Video Prompt</label><div className="prompt-box">{scene.video_prompt}</div></div>
          <div className="grid g2">
            <div className="sp-field"><label>Thời lượng</label><div className="sp-val">{scene.dur} giây</div></div>
            <div className="sp-field"><label>Transition</label><div className="sp-val">{scene.transition}</div></div>
          </div>
        </div>
      </div>
    </div>
  );
}

// Build a production entry from a live script variant (real scenes from backend).
function _variantToProduction(v, chId) {
  const chName = (window.CHANNELS || []).find(c => c.id === chId);
  const rawScenes = Array.isArray(v.scenes) ? v.scenes
                  : Array.isArray(v.sceneList) ? v.sceneList : [];
  const scenes = rawScenes.map((s, i) => ({
    n: s.n || i + 1,
    dur: Math.round(s.duration_s || s.dur || 5),
    narration: s.voiceover || s.vo || '',
    image_prompt: s.visual_prompt || s.visual || '',
    video_prompt: s.sfx || '—',
    voice: '—',
    transition: i % 3 === 0 ? 'fade' : 'cut',
    stages: v.approved
      ? { script: 'done', image: 'done', voice: 'done', subtitle: 'done', render: 'done' }
      : { script: 'done', image: 'pending', voice: 'pending', subtitle: 'pending', render: 'pending' },
    grad: GRADS[i % GRADS.length],
  }));
  return {
    id: v.file || v.key || v.id,
    title: (v.topic || v.id) + ' · ' + v.variant_id,
    channel: chName ? chName.name : chId,
    channel_id: chId,
    status: v.approved ? 'completed' : 'queued',
    ratio: '16:9 — YouTube ngang',
    lang: 'Tiếng Việt',
    log: 'Variant ' + v.variant_id + ' · score ' + v.score + (v.approved ? ' · approved' : ''),
    logTime: '—',
    scenes,
  };
}

// Live render status from the real pipeline (render_real_video → status.json,
// surfaced by GET /api/render/status + /api/render/latest).
function RealRenderPanel() {
  const rs = window.OMNI_RENDER;
  const out = window.OMNI_RENDER_OUT;
  const [privacy, setPrivacy] = vS('private');
  const [showUploadForm, setShowUploadForm] = vS(false);
  const [imgErrs, setImgErrs] = vS({});
  const logRef = React.useRef(null);
  // Auto-scroll the log console to the newest line as it grows.
  React.useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [rs && rs.log ? rs.log.length : 0]);

  // Keep the panel mounted whenever there is anything worth showing — shots, a
  // log, an error, or a finished video. Only hide it when truly empty, so the
  // operator can still read the LAST log/error after a render ends or crashes.
  if (!rs) return null;
  const _emptyIdle = (!rs.shots || !rs.shots.length)
    && (!rs.log || !rs.log.length)
    && !rs.error
    && !(out && out.video);
  if (_emptyIdle && (rs.stage === 'idle' || !rs.stage)) return null;
  const STAGES = ['script', 'storyboard', 'images', 'compose', 'concat', 'done'];
  const ic = { done: '<Icon name="check" />', active: '<Icon name="refresh-cw" />', error: '<Icon name="x" />', pending: '·' };
  const shots = rs.shots || [];
  const doneN = shots.filter(s => s.state === 'done').length;
  const cr = rs.credits;

  return (
    <div className="card pad-lg" style={{ marginBottom: 16, borderColor: 'var(--accent, #3b82f6)' }}>
      <div className="card-hd" style={{ marginBottom: 10 }}>
        <div className="card-title"><Icon name="alert-triangle" /> {rs.title || 'Đang tạo…'} <span style={{ color: 'var(--text3)', fontWeight: 500, fontSize: 12 }}>· {rs.channel || '—'} · {Math.round(rs.elapsed || 0)}s</span></div>
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
        {STAGES.map(k => {
          const st = (rs.stages || {})[k] || 'pending';
          return <span key={k} className={`tag ${st === 'done' ? 'green' : st === 'active' ? 'blue' : st === 'error' ? 'red' : 'gray'}`}>{ic[st]} {k}</span>;
        })}
      </div>
      {cr && <div className="fhint" style={{ marginBottom: 8 }}><Icon name="wallet" /> credit: {cr.balance} {cr.cost_per_clip ? `· ${cr.cost_per_clip}/clip · cần ${cr.needed}` : ''}</div>}
      {rs.qa && (
        <div style={{ marginBottom: 8 }}>
          <span className={`tag ${rs.qa.ok ? 'green' : 'red'}`} style={{ marginRight: 6 }}>{rs.qa.ok ? '<Icon name="check" /> QA' : '<Icon name="x" /> QA'} {rs.qa.summary}</span>
          {Object.entries(rs.qa.checks || {}).map(([k, c]) => (
            <span key={k} className={`tag ${c.pass ? 'green' : c.soft ? 'gray' : 'red'}`} style={{ marginRight: 4, fontSize: 11 }} title={c.detail}>{c.pass ? '<Icon name="check" />' : '<Icon name="x" />'} {k}</span>
          ))}
        </div>
      )}
      {shots.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
          <div className="prog" style={{ flex: 1, marginTop: 0 }}><i className={rs.stages && rs.stages.done === 'done' ? 'green' : ''} style={{ width: `${shots.length ? (doneN / shots.length) * 100 : 0}%` }}></i></div>
          <span style={{ fontSize: 13, fontWeight: 700 }}>{doneN}/{shots.length} shot</span>
        </div>
      )}
      
      {/* Shots Grid */}
      <div className="scene-grid" style={{ maxHeight: 220, overflowY: 'auto', marginBottom: 12 }}>
        {shots.map(s => {
          // Resolve illustration URL by appending channel ID if s.illu is just _assets/...
          const illuPath = (s.illu && rs.channel) 
            ? (s.illu.startsWith('_assets/') ? `${rs.channel}/${s.illu}` : s.illu)
            : s.illu;
          const hasImg = illuPath && !imgErrs[s.idx];
          return (
            <div key={s.idx} className="scene-card" style={{ display: 'inline-block', width: 140, margin: 4, verticalAlign: 'top' }}>
              <div className="scene-thumb" style={{ background: '#0a0d14', height: 78 }}>
                {hasImg ? <img 
                            src={'/media/' + illuPath} 
                            style={{ width: '100%', height: '100%', objectFit: 'cover' }} 
                            alt={'shot ' + (s.idx + 1)} 
                            onError={() => setImgErrs(prev => ({ ...prev, [s.idx]: true }))}
                          />
                        : <div className="st-overlay" style={{ opacity: 0.6 }}>{s.idx + 1}</div>}
                <span className={`st-badge ${s.state === 'done' ? 'done' : s.state === 'active' ? 'render' : 'wait'}`}>{s.state}</span>
              </div>
              <div className="scene-body" style={{ padding: 6 }}><div className="scene-text" style={{ fontSize: 10, height: 28, overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.heading}</div></div>
            </div>
          );
        })}
      </div>

      {/* Render error banner — surfaced so the operator sees WHY a run stopped
          without opening server.log. */}
      {rs.error && (
        <div className="tag red" style={{ display: 'block', padding: '8px 10px', marginBottom: 10, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
          <Icon name="x" /> {rs.error}
        </div>
      )}

      {/* Terminal Log Console */}
      {rs.log && rs.log.length > 0 && (
        <div style={{ marginTop: 10, marginBottom: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ color: '#9ca3af', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>Tiến trình chi tiết ({rs.log.length} dòng)</span>
            <button className="btn btn-ghost sm" style={{ fontSize: 11, padding: '2px 8px' }} onClick={() => {
              const blob = new Blob([(rs.log || []).join('\n')], { type: 'text/plain' });
              const a = document.createElement('a');
              a.href = URL.createObjectURL(blob);
              a.download = `render_${rs.channel || 'log'}_${Math.round(rs.elapsed || 0)}s.log`;
              a.click(); URL.revokeObjectURL(a.href);
            }}><Icon name="archive" /> Tải log</button>
          </div>
          <div ref={logRef} style={{
            padding: 10,
            background: '#090d16',
            color: '#34d399',
            fontFamily: 'monospace',
            fontSize: '11px',
            borderRadius: 'var(--r-md)',
            maxHeight: '280px',
            overflowY: 'auto',
            border: '1px solid var(--border)',
            textAlign: 'left'
          }}>
            {rs.log.map((line, idx) => <div key={idx} style={{ wordBreak: 'break-word' }}>{line}</div>)}
          </div>
        </div>
      )}

      {out && out.video && (
        <div style={{ marginTop: 14 }}>
          {out.title && <div className="card-title text-green" style={{ marginBottom: 6 }}><Icon name="video" /> {out.title}</div>}
          <video src={window.getMediaUrl ? window.getMediaUrl(out.video) : out.video} controls style={{ width: '100%', maxWidth: 640, borderRadius: 'var(--r-md)', border: '1px solid var(--border)' }}></video>
          {out.thumbnail && (
            <div style={{ marginTop: 10, marginBottom: 14 }}>
              <div style={{ fontSize: 12, color: 'var(--text3)', marginBottom: 4 }}>Thumbnail</div>
              <img src={window.getMediaUrl ? window.getMediaUrl(out.thumbnail) : out.thumbnail} style={{ width: '100%', maxWidth: 320, borderRadius: 'var(--r-sm)', border: '1px solid var(--border)' }} />
            </div>
          )}
          <div style={{ display: 'flex', gap: 10, marginTop: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <a className="btn btn-ghost sm" href={window.getMediaUrl ? window.getMediaUrl(out.video) : out.video} download><Icon name="archive" /> Tải video</a>
            {out.thumbnail && <a className="btn btn-ghost sm" href={window.getMediaUrl ? window.getMediaUrl(out.thumbnail) : out.thumbnail} download><Icon name="archive" /> Thumbnail</a>}
            
            {rs.channel && !showUploadForm && (
              <button className="btn btn-primary sm" onClick={() => setShowUploadForm(true)}><Icon name="upload" /> Gửi duyệt đăng...</button>
            )}

            {showUploadForm && (
              <div className="card pad-md" style={{ width: '100%', marginTop: 8, background: 'rgba(255,255,255,0.02)', borderColor: 'var(--border)' }}>
                <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8 }}>Cấu hình gửi duyệt đăng</div>
                <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                  <select className="field sm" style={{ width: 'auto' }} value={privacy} onChange={e => setPrivacy(e.target.value)}>
                    <option value="private">Riêng tư (Private)</option>
                    <option value="unlisted">Không công khai (Unlisted)</option>
                    <option value="public">Công khai (Public)</option>
                  </select>
                  <button className="btn btn-primary sm" onClick={() => {
                    if (window.OmniActions) {
                      window.OmniActions.uploadVideo(rs.channel, privacy);
                      setShowUploadForm(false);
                    }
                  }}>Gửi vào hàng duyệt</button>
                  <button className="btn btn-ghost sm" onClick={() => setShowUploadForm(false)}>Hủy</button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Manual render parameter tuning ──────────────────────────────────────────
const RENDER_STYLES = ['editorial', 'documentary', 'watercolor', 'dark_finance',
                       'clean_educational', 'vibrant_3d', 'whiteboard_sketch'];
const RENDER_MOODS = ['cinematic', 'dramatic', 'ambient', 'corporate', 'uplifting',
                      'tense', 'calm', 'epic'];
const RENDER_VOICES = [
  ['', '(Mặc định kênh)'],
  ['kokoro:af_heart', 'Kokoro · af_heart (nữ US)'],
  ['kokoro:am_michael', 'Kokoro · am_michael (nam US)'],
  ['kokoro:bf_emma', 'Kokoro · bf_emma (nữ UK)'],
  ['edge:en-US-AriaNeural', 'Edge · Aria (nữ US)'],
  ['edge:en-US-GuyNeural', 'Edge · Guy (nam US)'],
  ['edge:en-US-JennyNeural', 'Edge · Jenny (nữ US)'],
  ['edge:en-GB-SoniaNeural', 'Edge · Sonia (nữ UK)'],
  ['edge:vi-VN-HoaiMyNeural', 'Edge · HoaiMy (nữ VN)'],
];

function defaultROpts() {
  try {
    const s = localStorage.getItem('omni_ropts');
    if (s) return { ...{ beat_words: 18, style: '', voice: '', shorts: false, music: true, music_volume: 10, music_mood: '' }, ...JSON.parse(s) };
  } catch (e) {}
  return { beat_words: 18, style: '', voice: '', shorts: false, music: true, music_volume: 10, music_mood: '' };
}

// Convert UI state → /api/render query params (omit empties → channel defaults).
function renderOptsToQuery(o) {
  const q = { beat_words: o.beat_words };
  if (o.style) q.style = o.style;
  if (o.voice) q.voice = o.voice;
  if (o.shorts) q.shorts = true;
  if (!o.music) { q.music = false; }
  else {
    if (o.music_mood) q.music_mood = o.music_mood;
    if (o.music_volume != null) q.music_volume = (o.music_volume / 100).toFixed(2);
  }
  return q;
}

function RenderSettings({ opts, setOpts }) {
  const [open, setOpen] = vS(false);
  const up = (k, v) => { const n = { ...opts, [k]: v }; setOpts(n); try { localStorage.setItem('omni_ropts', JSON.stringify(n)); } catch (e) {} };
  return (
    <div className="card pad-lg" style={{ marginBottom: 16 }}>
      <div className="card-hd" style={{ marginBottom: open ? 14 : 0, cursor: 'pointer' }} onClick={() => setOpen(!open)}>
        <div>
          <div className="card-title"><Icon name="settings" /> Tùy chỉnh render {open ? '' : '▸'}</div>
          {!open && <div className="card-sub">Giọng · pacing · style · nhạc · shorts — bấm để mở</div>}
        </div>
        <span style={{ color: 'var(--text3)', fontSize: 18 }}>{open ? '▾' : '▸'}</span>
      </div>
      {open && (
        <div className="grid g3" style={{ gap: 14 }}>
          <div className="field">
            <label>Giọng đọc</label>
            <select value={opts.voice} onChange={e => up('voice', e.target.value)}>
              {RENDER_VOICES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div className="field">
            <label>Style hình</label>
            <select value={opts.style} onChange={e => up('style', e.target.value)}>
              <option value="">(Mặc định kênh)</option>
              {RENDER_STYLES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div className="field">
            <label>Pacing (từ/cảnh): {opts.beat_words}</label>
            <input type="range" className="range" min={12} max={50} value={opts.beat_words}
                   onChange={e => up('beat_words', +e.target.value)} />
          </div>
          <div className="field">
            <label>Nhạc nền</label>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <button className={`toggle ${opts.music ? 'on' : ''}`} onClick={() => up('music', !opts.music)}><span className="knob"></span></button>
              <span style={{ fontSize: 12.5, color: 'var(--text2)' }}>{opts.music ? 'Bật' : 'Tắt'}</span>
            </div>
          </div>
          <div className="field">
            <label>Mood nhạc</label>
            <select value={opts.music_mood} onChange={e => up('music_mood', e.target.value)} disabled={!opts.music}>
              <option value="">(Tự theo niche)</option>
              {RENDER_MOODS.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div className="field">
            <label>Âm lượng nhạc: {opts.music_volume}%</label>
            <input type="range" className="range" min={0} max={40} value={opts.music_volume}
                   disabled={!opts.music} onChange={e => up('music_volume', +e.target.value)} />
          </div>
          <div className="field">
            <label>Định dạng dọc (Shorts/Reels)</label>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <button className={`toggle ${opts.shorts ? 'on' : ''}`} onClick={() => up('shorts', !opts.shorts)}><span className="knob"></span></button>
              <span style={{ fontSize: 12.5, color: 'var(--text2)' }}>{opts.shorts ? '9:16 dọc' : '16:9 ngang'}</span>
            </div>
          </div>
          <div className="field" style={{ gridColumn: '1 / -1' }}>
            <div className="fhint">Phụ đề luôn bật (word-synced). Bỏ trống = dùng cấu hình kênh. Thiết lập lưu trên trình duyệt này.</div>
          </div>
        </div>
      )}
    </div>
  );
}

function VideoProduction() {
  const live = (window.OMNI_VARIANTS && window.OMNI_VARIANTS.length)
    ? window.OMNI_VARIANTS.filter(v => (Array.isArray(v.scenes) && v.scenes.length) || (Array.isArray(v.sceneList) && v.sceneList.length)).map(v => _variantToProduction(v, window.OMNI_SCRIPT_CH))
    : null;
  
  const isMock = !(live && live.length);
  const PROD = isMock ? PRODUCTIONS : live;

  const [selId, setSel] = vS(PROD[0] ? PROD[0].id : 'p2');
  const [detail, setDetail] = vS(null);
  const [ropts, setROpts] = vS(defaultROpts());
  const prod = PROD.find(p => p.id === selId) || PROD[0];
  const done = prod ? prod.scenes.filter(s => sceneOverall(s) === 'done').length : 0;
  const total = prod ? prod.scenes.length : 0;
  const stBadge = { completed: ['green', '<Icon name="check" /> Hoàn thành'], producing: ['blue', '<Icon name="refresh-cw" /> Đang sản xuất'], queued: ['amber', '<Icon name="clock" /> Hàng đợi'] };

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div className="page-title">Sản xuất Video</div>
          <div className="page-desc">Theo dõi chi tiết từng cảnh trong video đang được sản xuất</div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <select className="field" style={{ width: 'auto', minWidth: 200 }} value={window.OMNI_SCRIPT_CH || ''} onChange={e => window.OmniLoadScripts(e.target.value)}>
            {(window.CHANNELS || []).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <button className="btn btn-primary sm" onClick={() => {
            const id = window.OMNI_SCRIPT_CH;
            if (id && window.OmniActions) {
              if (isMock) {
                window._toast('Không thể sản xuất kịch bản mẫu. Hãy chọn kịch bản thật của bạn.', false);
                return;
              }
              if (confirm(`Bắt đầu sản xuất video cho kênh '${id}' sử dụng kịch bản '${prod.id}'?\n\nTiến trình này sẽ sinh giọng nói, Playwright vẽ ảnh Flow, và chạy FFmpeg render.`)) {
                window.OmniActions.startRender(id, { script: prod.id, ...renderOptsToQuery(ropts) });
              }
            }
          }}><Icon name="video" /> Sản xuất video thật</button>
        </div>
      </div>

      <RenderSettings opts={ropts} setOpts={setROpts} />

      <RealRenderPanel />

      {isMock && (
        <div className="pipeline-log" style={{ background: 'rgba(239, 68, 68, 0.08)', borderColor: '#ef4444', color: '#f87171', marginBottom: 16 }}>
          <span style={{ fontWeight: 700 }}><Icon name="alert-triangle" /> Chế độ Demo:</span> Kênh này chưa có kịch bản thật được duyệt. Đang hiển thị kịch bản mẫu. Hãy chuyển sang tab <b>Tạo Video</b> để tạo kịch bản thật.
        </div>
      )}

      <div className="prod-tabs">
        {PROD.map(p => {
          const d = p.scenes.filter(s => sceneOverall(s) === 'done').length;
          return (
            <div key={p.id} className={`prod-tab ${selId === p.id ? 'sel' : ''}`} onClick={() => setSel(p.id)}>
              <span className="dot" style={{ background: AGENT_COLOR[stBadge[p.status][0] === 'green' ? 'green' : stBadge[p.status][0] === 'blue' ? 'blue' : 'amber'] }}></span>
              <div>
                <div className="pt-name">{p.title.length > 32 ? p.title.slice(0, 32) + '…' : p.title}</div>
                <div className="pt-meta">{p.channel} · {d}/{p.scenes.length} cảnh</div>
              </div>
            </div>
          );
        })}
      </div>

      {prod && (
        <div className="card pad-lg">
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 14 }}>
            <div>
              <div style={{ fontSize: 19, fontWeight: 800, letterSpacing: '-0.02em' }}>{prod.title}</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginTop: 7 }}>
                <span className={`tag ${stBadge[prod.status][0]}`}>{stBadge[prod.status][1]}</span>
                <span style={{ fontSize: 12.5, color: 'var(--text2)' }}>{prod.channel} · {prod.ratio} · {prod.lang}</span>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <button className="btn btn-ghost sm" onClick={() => window.OmniLoad && window.OmniLoad()}><Icon name="refresh-cw" /> Refresh</button>
              <button className="btn btn-primary sm" onClick={() => {
                const id = window.OMNI_SCRIPT_CH;
                if (id && window.OmniActions) {
                  if (isMock) {
                    window._toast('Không thể sản xuất kịch bản mẫu. Hãy chọn kịch bản thật của bạn.', false);
                    return;
                  }
                  if (confirm(`Render lại kịch bản '${prod.id}' cho kênh '${id}'?`)) {
                    window.OmniActions.startRender(id, { script: prod.id, ...renderOptsToQuery(ropts) });
                  }
                }
              }}><Icon name="video" /> Render lại</button>
            </div>
          </div>

          <div className="pipeline-log">
            <span className="lg-time">[{prod.logTime}]</span>
            <span className="lg-info">[INFO]</span>
            <span>{prod.log}</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 18 }}>
            <div className="prog" style={{ flex: 1, marginTop: 0 }}>
              <i className={prod.status === 'completed' ? 'green' : ''} style={{ width: `${(done / total) * 100}%` }}></i>
            </div>
            <span style={{ fontSize: 13, fontWeight: 700, whiteSpace: 'nowrap' }}>{done}/{total} cảnh</span>
          </div>

          <div className="scene-grid">
            {prod.scenes.map(s => <SceneCard key={s.n} scene={s} channelId={prod.channel_id} onOpen={(sc) => setDetail(sc)} />)}
          </div>
        </div>
      )}

      {detail && <SceneDetail scene={detail} prod={prod} onClose={() => setDetail(null)} />}
    </div>
  );
}

/* ---------- CREATE STUDIO ---------- */
const SAMPLE_SCENES = [
  'Mở đầu bằng một câu hỏi gây tò mò khiến người xem phải dừng lại.',
  'Giới thiệu bối cảnh và vấn đề cốt lõi của chủ đề.',
  'Đưa ra bằng chứng hoặc số liệu bất ngờ để tạo sức nặng.',
  'Phân tích sâu, kết nối các ý với nhau một cách logic.',
  'Kết luận mạnh mẽ và lời kêu gọi tương tác cuối video.',
];

function CreateVideo({ goProduce }) {
  const [source, setSource] = vS('scratch');
  const [ratio, setRatio] = vS('16:9');
  const [name, setName] = vS('');
  const [desc, setDesc] = vS('');
  const [audience, setAudience] = vS('');
  const [channel, setChannel] = vS((CHANNELS[0] && CHANNELS[0].id) || '');
  const channelName = ((CHANNELS || []).find(c => c.id === channel) || {}).name || channel;
  const [sceneCount, setSceneCount] = vS(5);
  const [lang, setLang] = vS('Tiếng Việt');
  const [subtitle, setSubtitle] = vS(true);
  const [music, setMusic] = vS(true);
  const [vol, setVol] = vS(20);
  const [built, setBuilt] = vS(false);

  const ratios = [
    { id: '9:16', emoji: '<Icon name="tv" />', label: 'Dọc 9:16', sub: '1080×1920' },
    { id: '16:9', emoji: '<Icon name="tv" />', label: 'Ngang 16:9', sub: '1920×1080' },
    { id: '1:1', emoji: '<Icon name="archive" />', label: 'Vuông 1:1', sub: '1080×1080' },
  ];
  const canBuild = name.trim().length > 0;

  return (
    <div>
      <div className="page-title">Tạo Video</div>
      <div className="page-desc">Studio vận hành — tạo video thủ công với AI pipeline</div>

      <div className="create-layout">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Source */}
          <div className="card pad-lg">
            <div className="card-hd" style={{ marginBottom: 12 }}><div className="card-title">Nguồn nội dung</div></div>
            <div className="opt-grid">
              <div className={`opt-card ${source === 'scratch' ? 'sel' : ''}`} onClick={() => setSource('scratch')}>
                <span style={{ fontSize: 22 }}><Icon name="file-text" /></span>
                <div className="oc-title">Từ ý tưởng</div>
                <div className="oc-desc">Mô tả ý tưởng, AI tự sinh kịch bản và phân cảnh</div>
              </div>
              <div className={`opt-card ${source === 'crawl' ? 'sel' : ''}`} onClick={() => setSource('crawl')}>
                <span style={{ fontSize: 22 }}><Icon name="globe" /></span>
                <div className="oc-title">Từ URL</div>
                <div className="oc-desc">Crawl một bài viết/landing page làm nội dung gốc</div>
              </div>
            </div>
            {source === 'crawl' && (
              <div style={{ display: 'flex', gap: 8, marginTop: 12, alignItems: 'center' }}>
                <input className="finput" placeholder="https://vn.beincrypto.com/can..." disabled />
                <button className="btn btn-primary" disabled title="Tính năng crawl URL đang phát triển">Crawl</button>
                <span className="fhint">Sắp có</span>
              </div>
            )}
          </div>

          {/* Content */}
          <div className="card pad-lg">
            <div className="card-hd" style={{ marginBottom: 14 }}><div className="card-title">Nội dung</div></div>
            <div style={{ marginBottom: 14 }}>
              <label className="flabel">Kênh đăng</label>
              <select className="fselect" value={channel} onChange={e => setChannel(e.target.value)}>
                {CHANNELS.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div style={{ marginBottom: 14 }}>
              <label className="flabel">Chủ đề / Tiêu đề video *</label>
              <input className="finput" value={name} onChange={e => setName(e.target.value)} placeholder="VD: 5 crypto whales đang gom Bitcoin" />
            </div>
            <div style={{ marginBottom: 14 }}>
              <label className="flabel">Mô tả ý tưởng</label>
              <textarea className="ftext" value={desc} onChange={e => setDesc(e.target.value)} placeholder="Mô tả góc nhìn, tông giọng, các điểm chính bạn muốn đề cập..." />
            </div>
            <div>
              <label className="flabel">Đối tượng khán giả</label>
              <input className="finput" value={audience} onChange={e => setAudience(e.target.value)} placeholder="VD: Nhà đầu tư crypto 25-40 tuổi" />
            </div>
          </div>

          {/* Format */}
          <div className="card pad-lg">
            <div className="card-hd" style={{ marginBottom: 14 }}><div className="card-title">Định dạng</div></div>
            <label className="flabel">Tỉ lệ khung hình</label>
            <div className="opt-3" style={{ marginBottom: 16 }}>
              {ratios.map(r => (
                <div key={r.id} className={`opt-mini ${ratio === r.id ? 'sel' : ''}`} onClick={() => setRatio(r.id)}>
                  <div className="om-emoji">{r.emoji}</div>
                  <div className="om-label">{r.label}</div>
                  <div className="om-sub">{r.sub}</div>
                </div>
              ))}
            </div>
            <div className="grid g2">
              <div>
                <label className="flabel">Số cảnh</label>
                <input type="number" className="finput" min={1} max={20} value={sceneCount} onChange={e => setSceneCount(+e.target.value)} />
                <div className="fhint">AI sẽ tạo đúng số cảnh này</div>
              </div>
              <div>
                <label className="flabel">Ngôn ngữ</label>
                <select className="fselect" value={lang} onChange={e => setLang(e.target.value)}>
                  <option>Tiếng Việt</option><option>English</option><option>日本語</option>
                </select>
              </div>
            </div>
          </div>

          {/* Extras */}
          <div className="card pad-lg">
            <div className="card-hd" style={{ marginBottom: 14 }}><div className="card-title">Bổ sung</div></div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingBottom: 14, borderBottom: '1px solid var(--border)' }}>
              <div><div style={{ fontSize: 13, fontWeight: 600 }}>Phụ đề (burn-in)</div><div className="fhint" style={{ marginTop: 2 }}>Ghi phụ đề trực tiếp lên video</div></div>
              <button className={`toggle ${subtitle ? 'on' : ''}`} onClick={() => setSubtitle(!subtitle)}><span className="knob"></span></button>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 0' }}>
              <div><div style={{ fontSize: 13, fontWeight: 600 }}>Nhạc nền</div><div className="fhint" style={{ marginTop: 2 }}>Từ thư viện an toàn bản quyền</div></div>
              <button className={`toggle ${music ? 'on' : ''}`} onClick={() => setMusic(!music)}><span className="knob"></span></button>
            </div>
            {music && (
              <div>
                <label className="flabel">Âm lượng nhạc nền: {vol}%</label>
                <input type="range" className="range" min={0} max={100} value={vol} onChange={e => setVol(+e.target.value)} />
              </div>
            )}
          </div>

          {built && (
            <div className="card pad-lg">
              <div className="card-hd">
                <div>
                  <div className="card-title text-blue"><Icon name="file-text" /> Đang khởi tạo kịch bản...</div>
                  <div className="card-sub">AI đang chạy luồng tranh luận kịch bản (Phase 2). Vui lòng chuyển sang tab <b>Văn phòng</b> hoặc <b>Kịch bản</b> để theo dõi luồng chat Agent thời gian thực.</div>
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '40px 20px', flexDirection: 'column', gap: 12 }}>
                <div className="spin-lg"></div>
                <div style={{ color: 'var(--text2)', fontSize: 13 }}>Kịch bản đang được viết ngầm trên máy chủ...</div>
                <button className="btn btn-ghost sm" onClick={() => setBuilt(false)}>Tạo kịch bản khác</button>
              </div>
            </div>
          )}
        </div>

        {/* Summary sidebar */}
        <div className="card pad-lg sticky-summary">
          <div className="card-hd" style={{ marginBottom: 12 }}><div className="card-title">Tóm tắt cấu hình</div></div>
          <div className="summary-row"><span className="sr-label">Nguồn</span><span className="sr-val">{source === 'scratch' ? 'Từ ý tưởng' : 'Từ URL'}</span></div>
          <div className="summary-row"><span className="sr-label">Kênh</span><span className="sr-val">{channelName.length > 16 ? channelName.slice(0, 16) + '…' : channelName}</span></div>
          <div className="summary-row"><span className="sr-label">Tỉ lệ</span><span className="sr-val">{ratio} ngang</span></div>
          <div className="summary-row"><span className="sr-label">Số cảnh</span><span className="sr-val">{sceneCount}</span></div>
          <div className="summary-row"><span className="sr-label">Ngôn ngữ</span><span className="sr-val">{lang}</span></div>
          <div className="summary-row"><span className="sr-label">Phụ đề</span><span className="sr-val">{subtitle ? 'Bật' : 'Tắt'}</span></div>
          <div className="summary-row"><span className="sr-label">Nhạc nền</span><span className="sr-val">{music ? `${vol}%` : 'Tắt'}</span></div>
          <div className="summary-row"><span className="sr-label">Chi phí ước tính</span><span className="sr-val text-amber">~${(sceneCount * 0.42).toFixed(2)}</span></div>
          <button className="btn btn-primary" style={{ width: '100%', marginTop: 16 }} disabled={!canBuild} onClick={() => { setBuilt(true); if (window.OmniActions && channel) window.OmniActions.runScript(channel, name, { desc, audience }); }}>
            <Icon name="zap" /> Tạo kịch bản (chạy Phase 2)
          </button>
          {!canBuild && <div className="fhint" style={{ textAlign: 'center', marginTop: 8 }}>Nhập tiêu đề video để tiếp tục</div>}
          <div className="fhint" style={{ marginTop: 10, lineHeight: 1.5 }}>
            Tiêu đề + Mô tả + Đối tượng được áp vào kịch bản. <b>Tỉ lệ / phụ đề / nhạc</b> áp ở bước <b>Sản xuất video</b> (render).
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { VideoProduction, CreateVideo });
