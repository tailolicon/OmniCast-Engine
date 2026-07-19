
class Component extends DCLogic {
  state = { view: 'dashboard', dark: false, paused: false, chSub: 'list', step: 'render', dockOpen: true };

  renderVals() {
    const st = this.state;
    const ink = '#4a3b7a';
    const set = (v) => () => this.setState({ view: v });

    // ── nav: bộ icon kawaii GỐC (SVG tự vẽ, không copy pack bản quyền) ──
    const ic = (s) => React.createElement('span', { style:{display:'inline-flex',alignItems:'center',justifyContent:'center',width:22,height:22}, dangerouslySetInnerHTML:{__html:s} });
    const S = "width='22' height='22' viewBox='0 0 28 28' fill='none' stroke='#4a3b7a' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'";
    const eye = (x,y)=>`<circle cx='${x}' cy='${y}' r='.85' fill='#4a3b7a' stroke='none'/>`;
    const blush = (x,y)=>`<circle cx='${x}' cy='${y}' r='1.1' fill='#ff9ed8' stroke='none'/>`;
    const svgDash = `<svg ${S}><path d='M4.5 13.5 14 5.5l9.5 8'/><path d='M7 12.5V22h14v-9.5' fill='#ffd0ee'/>${eye(11,17.5)}${eye(17,17.5)}${blush(9,18.5)}${blush(19,18.5)}</svg>`;
    const svgStudio = `<svg ${S}><rect x='4' y='9.5' width='20' height='13' rx='3' fill='#e0d4ff'/><path d='M4.5 12.5 23.5 9.5'/><path d='M9 9.7l-1.2 2.8M14 9.2l-1.2 2.8M19 9l-1.2 2.8'/>${eye(11,17)}${eye(16,17)}${blush(9,18)}${blush(18,18)}</svg>`;
    const svgLib = `<svg ${S}><rect x='5.5' y='5.5' width='5' height='17' rx='1.6' fill='#cdeeff'/><rect x='11.5' y='5.5' width='5' height='17' rx='1.6' fill='#ffd0ee'/><path d='M17.6 6.4l4 .9-3 15.6-4-.9z' fill='#fff0c9'/></svg>`;
    const svgTv = `<svg ${S}><path d='M14 8.5 10 4.5M14 8.5l4-4'/><rect x='4' y='8.5' width='20' height='14' rx='3.5' fill='#d3f7ea'/>${eye(11,15)}${eye(17,15)}${blush(9,16)}${blush(19,16)}</svg>`;
    const svgClock = `<svg ${S}><circle cx='14' cy='15' r='8' fill='#ffe0d0'/><path d='M6 6.5 9 8.6M22 6.5l-3 2.1'/><path d='M14 15V11M14 15l3 1.5'/>${blush(9.5,16)}${blush(18.5,16)}</svg>`;
    const svgHeart = `<svg ${S}><path d='M14 22.5S5 16.8 5 10.8A4.6 4.6 0 0 1 14 8.4a4.6 4.6 0 0 1 9 2.4C23 16.8 14 22.5 14 22.5z' fill='#ffd0ee'/>${eye(11.5,12.5)}${eye(16.5,12.5)}<path d='M13 14.8q1 .9 2 0'/></svg>`;
    const svgLink = `<svg ${S}><rect x='3.5' y='11' width='13' height='6' rx='3' fill='#e0d4ff'/><rect x='11.5' y='11' width='13' height='6' rx='3' fill='#cdeeff'/></svg>`;
    const svgChart = `<svg ${S}><rect x='4.5' y='14' width='4.2' height='8' rx='1.4' fill='#cdeeff'/><rect x='11.9' y='9' width='4.2' height='13' rx='1.4' fill='#ffd0ee'/><rect x='19.3' y='6' width='4.2' height='16' rx='1.4' fill='#d3f7ea'/></svg>`;
    const svgMoney = `<svg ${S}><path d='M10 8.5h8l-2-3.2h-4z' fill='#fff0c9'/><path d='M9.2 8.7C7.4 11.4 6 14.4 6 16.6a8 8 0 0 0 16 0c0-2.2-1.4-5.2-3.2-7.9z' fill='#fff0c9'/><path d='M14 12.5v5M12 14h4'/>${blush(9.5,16)}${blush(18.5,16)}</svg>`;
    const svgScroll = `<svg ${S}><rect x='7' y='5.5' width='14' height='17' rx='2.4' fill='#fff0c9'/><path d='M10 10.5h8M10 14h8M10 17.5h5'/></svg>`;
    const svgShop = `<svg ${S}><rect x='6' y='10.5' width='16' height='12' rx='2.4' fill='#ffe0d0'/><path d='M6 10.5 8 5.5h12l2 5'/><path d='M12 22.5v-5h4v5'/>${blush(9,15)}${blush(19,15)}</svg>`;
    const svgGear = `<svg ${S}><circle cx='14' cy='14' r='6' fill='#e0d4ff'/><path d='M14 4v3M14 21v3M4 14h3M21 14h3M7 7l2 2M19 19l2 2M21 7l-2 2M7 21l2-2'/>${eye(11.6,14)}${eye(16.4,14)}</svg>`;
    const svgRobot = `<svg ${S}><path d='M14 4.5v3'/><circle cx='14' cy='4' r='1.4' fill='#ff9ed8' stroke='none'/><rect x='5.5' y='7.5' width='17' height='13' rx='4.5' fill='#cdeeff'/>${eye(10.5,13.5)}${eye(17.5,13.5)}<path d='M12 16.5q2 1.4 4 0'/>${blush(8.3,15.8)}${blush(19.7,15.8)}<path d='M9.5 23.5v-3M18.5 23.5v-3'/></svg>`;
    const svgCal = `<svg ${S}><rect x='4.5' y='6.5' width='19' height='16' rx='4' fill='#ffd0ee'/><path d='M4.5 11.5h19'/><path d='M9.5 4v4M18.5 4v4'/>${eye(11,16.5)}${eye(17,16.5)}<path d='M12.2 19q1.8 1.2 3.6 0'/></svg>`;
    const svgKey = `<svg ${S}><circle cx='9.5' cy='11' r='5' fill='#fff0c9'/><path d='M13.5 14.5 22 23M18.5 19.5l3-3'/>${eye(8,10.5)}${eye(11,10.5)}<path d='M8.4 13q1.1 .8 2.2 0'/></svg>`;
    const svgWrench = `<svg ${S}><path d='M18.5 5a5.5 5.5 0 0 0-5 7.8L5 21.3a2.3 2.3 0 0 0 3.2 3.2l8.6-8.4a5.5 5.5 0 0 0 7-6.6l-3.6 3.5-3-.9-.9-3 3.5-3.5A5.6 5.6 0 0 0 18.5 5z' fill='#e0d4ff'/></svg>`;
    const svgPlay = `<svg width='20' height='20' viewBox='0 0 24 24'><path d='M8 5.5v13l11-6.5z' fill='#fff' stroke='#4a3b7a' stroke-width='1.6' stroke-linejoin='round'/></svg>`;
    const svgNote = `<svg width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='#fff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M9 18.2V6.5l9-2v10.7'/><circle cx='6.8' cy='18.4' r='2.4' fill='#fff' stroke='none'/><circle cx='15.8' cy='15.4' r='2.4' fill='#fff' stroke='none'/></svg>`;
    const svgFb = `<svg width='20' height='20' viewBox='0 0 24 24'><path d='M13.5 21v-7h2.6l.4-3h-3V9.1c0-.9.3-1.5 1.6-1.5h1.6V5c-.3 0-1.2-.1-2.2-.1-2.2 0-3.7 1.3-3.7 3.8V11H8.2v3h2.6v7z' fill='#fff'/></svg>`;
    this._svgGear = svgGear;

    // ── nav ──
    const groups = [
      { eyebrow: 'Sản xuất', items: [
        { key:'dashboard', label:'Bảng điều khiển', icon:ic(svgDash) },
        { key:'studio', label:'Xưởng', icon:ic(svgStudio) },
        { key:'library', label:'Thư viện', icon:ic(svgLib) },
      ]},
      { eyebrow: 'Kênh', items: [
        { key:'channels', label:'Kênh & Niche', icon:ic(svgTv) },
        { key:'scheduler', label:'Lịch & Tự động', icon:ic(svgClock) },
      ]},
      { eyebrow: 'Phân phối', items: [
        { key:'approvals', label:'Duyệt & Đăng', icon:ic(svgHeart) },
        { key:'platforms', label:'Nền tảng & Đích', icon:ic(svgLink) },
        { key:'analytics', label:'Phân tích', icon:ic(svgChart) },
      ]},
      { eyebrow: 'Kiếm tiền', items: [
        { key:'monetization', label:'Doanh thu', icon:ic(svgMoney) },
        { key:'audit', label:'Nhật ký kiểm toán', icon:ic(svgScroll) },
        { key:'library', label:'Văn phòng', icon:ic(svgShop) },
      ]},
    ];
    const itemStyle = (active) => `display:flex; align-items:center; gap:11px; margin:2px 8px; padding:8px 11px; border-radius:12px; cursor:pointer; color:${active?'#f45fce':'#8676bd'}; background:${active?'#ffe0f5':'transparent'}; border:2px solid ${active?ink:'transparent'}; box-shadow:${active?'2px 2px 0 0 rgba(74,59,122,.16), 0 0 16px -2px rgba(244,95,206,.55)':'none'};`;
    const navGroups = groups.map(g => ({ eyebrow: g.eyebrow, items: g.items.map(it => ({
      ...it, style: itemStyle(st.view === it.key), onClick: set(it.key),
    })) }));

    const labels = { dashboard:'Bảng điều khiển', studio:'Xưởng', library:'Thư viện', channels:'Kênh & Niche', scheduler:'Lịch & Tự động', approvals:'Duyệt & Đăng', platforms:'Nền tảng & Đích', analytics:'Phân tích', monetization:'Doanh thu', audit:'Nhật ký kiểm toán', system:'Hệ thống' };

    // ── dashboard ──
    const kpis = [
      { label:'Đang chạy', value:'2', icon:'▶', iconBg:'#fff5da', sub:'2 pipeline active' },
      { label:'Script hôm nay', value:'14', icon:'✎', iconBg:'#e6f6ff', sub:'chất lượng score ≥ 70' },
      { label:'Chi phí hôm nay', value:'$23.80', icon:'$', iconBg:'#e3fff4', sub:'Spend limit: $100 · 24%' },
      { label:'Kênh', value:'4', icon:'◈', iconBg:'#f3ecff', sub:'12 ngách được phát hiện' },
    ];
    const pipelines = [
      { channel:'Sleep Stories VN', stage:'render · Bí ẩn đại dương sâu thẳm', eta:'2m 40s · ETA ~3m', fill:'width:62%; height:100%; background:linear-gradient(90deg,#f45fce,#a877ff);' },
      { channel:'Deep Focus', stage:'script · Âm thanh mưa rừng', eta:'0m 55s · ETA ~5m', fill:'width:28%; height:100%; background:linear-gradient(90deg,#37b6f5,#a877ff);' },
    ];
    const tagOK = 'font-size:10px; font-weight:800; color:#fff; background:#22c9a8; border:1.5px solid '+ink+'; padding:2px 9px; border-radius:999px;';
    const tagRun = 'font-size:10px; font-weight:800; color:#fff; background:#37b6f5; border:1.5px solid '+ink+'; padding:2px 9px; border-radius:999px;';
    const tagFail = 'font-size:10px; font-weight:800; color:#fff; background:#ff5f9e; border:1.5px solid '+ink+'; padding:2px 9px; border-radius:999px;';
    const activities = [
      { ch:'Sleep Stories VN', phase:'render', status:'success', tag:tagOK },
      { ch:'Calm Mind', phase:'publish', status:'success', tag:tagOK },
      { ch:'Deep Focus', phase:'script', status:'running', tag:tagRun },
      { ch:'Sleep Stories VN', phase:'discovery', status:'failed', tag:tagFail },
    ];

    // ── studio stepper ──
    const stepDefs = [
      { key:'discovery', title:'1 · Discovery', sub:'Hoàn tất', icon:'✓', color:'#22c9a8', bg:'#e3fff4' },
      { key:'script', title:'2 · Script', sub:'Chờ duyệt · 8 cảnh', icon:'✎', color:'#f2a93b', bg:'#fff5da' },
      { key:'render', title:'3 · Render', sub:'62% · ETA 3m', icon:'▶', color:'#f45fce', bg:'#ffe0f5' },
      { key:'duyet', title:'4 · Duyệt', sub:'Chờ render', icon:'4', color:'#b0a3d6', bg:'#faf4ff' },
    ];
    const steps = stepDefs.map(s => {
      const active = st.step === s.key;
      return { ...s, onClick: () => this.setState({ step: s.key }),
        style: `flex:1; display:flex; align-items:center; gap:11px; padding:12px 15px; border-radius:16px; cursor:pointer; background:${s.bg}; border:2px solid ${ink}; box-shadow:${active?'0 0 0 3px rgba(244,95,206,.25),':''}2px 2px 0 0 rgba(74,59,122,.15);`,
        badge: `width:34px;height:34px;border-radius:50%;background:${s.color};border:2px solid ${ink};display:flex;align-items:center;justify-content:center;color:#fff;font-weight:800;`,
        titleColor:'#372a66', subColor:s.color };
    });
    const bodyMap = {
      discovery:{ title:'Bước 1 · Discovery', btn1:'Quét lại', btn2:'▶ Chọn chủ đề' },
      script:{ title:'Bước 2 · Script', btn1:'Tạo lại', btn2:'▶ Tiếp tục chạy' },
      render:{ title:'Bước 3 · Render Video', btn1:'Render lại', btn2:'■ Huỷ Job' },
      duyet:{ title:'Bước 4 · Duyệt & Đăng', btn1:'Làm mới', btn2:'✓ Duyệt' },
    };
    const stepBody = bodyMap[st.step] || bodyMap.render;
    const renderStats = [
      { k:'Thời lượng', v:'8m 53s' }, { k:'Phân giải', v:'1920×1080' }, { k:'Dung lượng', v:'214 MB' }, { k:'Cảnh xong', v:'5 / 8' },
    ];
    const rawScenes = [
      { n:1, t:'Ánh sáng cuối trên mặt biển', s:'done', g:'linear-gradient(135deg,#8db4ff,#c9b3ff)' },
      { n:2, t:'Vùng chạng vạng phát sáng', s:'done', g:'linear-gradient(135deg,#7fe6d8,#a9d4ff)' },
      { n:3, t:'Sinh vật lướt qua bóng tối', s:'done', g:'linear-gradient(135deg,#c79dff,#ffb3e6)' },
      { n:4, t:'Áp suất nghiền nát dưới sâu', s:'done', g:'linear-gradient(135deg,#9db8ff,#7fe6d8)' },
      { n:5, t:'Hố sâu Mariana', s:'active', g:'linear-gradient(135deg,#f45fce,#a877ff)' },
      { n:6, t:'Loài chưa từng đặt tên', s:'wait', g:'' },
      { n:7, t:'Vẻ đẹp giữa lòng đại dương', s:'wait', g:'' },
      { n:8, t:'Kết: trở lại mặt nước', s:'wait', g:'' },
    ];
    const scenes = rawScenes.map(sc => {
      const done = sc.s==='done', active = sc.s==='active';
      const base = 'aspect-ratio:16/9; border-radius:12px; position:relative; overflow:hidden; display:flex; border:2px solid '+ink+'; box-shadow:2px 2px 0 0 rgba(74,59,122,.15);';
      let thumb;
      if (active) thumb = base+' background:'+sc.g+'; box-shadow:0 0 0 3px rgba(244,95,206,.3),2px 2px 0 0 rgba(74,59,122,.15);';
      else if (done) thumb = base+' background:'+sc.g+';';
      else thumb = 'aspect-ratio:16/9; border-radius:12px; position:relative; overflow:hidden; display:flex; background:#f3ecff; border:2px dashed #c9b8f0;';
      const dc = done?'#22c9a8':active?'#f45fce':'#c9b8f0';
      return { num:'#'+sc.n, title:sc.t, tc:(done||active)?'#6b5aa0':'#b0a3d6', thumb,
        dot:'position:absolute; top:5px; right:5px; width:11px;height:11px;border-radius:50%;border:2px solid #fff; background:'+dc+';' };
    });
    const config = [
      { k:'Giọng đọc', v:'Ngọc Huyền · 1.0×' }, { k:'Model ảnh', v:'Imagen 4' }, { k:'AI Script', v:'Gemini 2.5 Flash' }, { k:'Nhạc nền', v:'Calm · 15%' }, { k:'Định dạng', v:'16:9 · 15 từ/beat' },
    ];
    const logs = [
      { t:'14:22:07', tag:'[tts]', c:'#1a9e7a', msg:'scene_04.mp3 ✓' },
      { t:'14:22:19', tag:'[image]', c:'#37b6f5', msg:'imagen4 → scene_05…' },
      { t:'14:22:31', tag:'[flow]', c:'#a877ff', msg:'ghép animation cảnh 5' },
      { t:'14:22:38', tag:'[music]', c:'#a877ff', msg:'ocean_calm_02 -18dB' },
      { t:'14:22:44', tag:'[render]', c:'#f45fce', msg:'progress 62%' },
    ];

    // ── channels ──
    const stActive = 'font-size:10px; font-weight:800; color:#1a9e7a; background:#e3fff4; border:1.5px solid '+ink+'; padding:2px 9px; border-radius:999px; justify-self:start;';
    const stOff = 'font-size:10px; font-weight:800; color:#8676bd; background:#f3ecff; border:1.5px solid '+ink+'; padding:2px 9px; border-radius:999px; justify-self:start;';
    const channels = [
      { name:'Sleep Stories VN', id:'UC_sleep01', status:'Active', statusStyle:stActive, niche:'relaxation', views:'842.109', subs:'8.204', rev:'$412.80' },
      { name:'Calm Mind', id:'UC_calm02', status:'Active', statusStyle:stActive, niche:'meditation', views:'318.442', subs:'3.110', rev:'$221.35' },
      { name:'Deep Focus', id:'UC_focus03', status:'Active', statusStyle:stActive, niche:'study music', views:'124.351', subs:'1.116', rev:'$92.02' },
      { name:'Night Rain', id:'UC_rain04', status:'Lịch tắt', statusStyle:stOff, niche:'ambient', views:'0', subs:'0', rev:'$0.00' },
    ];
    const chCols = ['Kênh','Trạng thái','Niche','Views','Subs','Doanh thu',''];
    const badgeHi = 'font-size:10px; font-weight:800; color:#fff; background:#22c9a8; border:1.5px solid '+ink+'; padding:2px 9px; border-radius:999px;';
    const badgeMid = 'font-size:10px; font-weight:800; color:#fff; background:#37b6f5; border:1.5px solid '+ink+'; padding:2px 9px; border-radius:999px;';
    const niches = [
      { name:'Vì sao biển sâu phát sáng?', score:'92 pts', badge:badgeHi, desc:'Ngách tiềm năng cao về từ khóa tìm kiếm và tỷ lệ chuyển đổi quảng cáo.' },
      { name:'Những con tàu đắm bí ẩn', score:'88 pts', badge:badgeHi, desc:'Chủ đề lịch sử — bí ẩn có lượng tìm kiếm ổn định quanh năm.' },
      { name:'Sự sống quanh núi lửa ngầm', score:'85 pts', badge:badgeHi, desc:'Khoa học tự nhiên, hình ảnh đẹp, phù hợp video dài.' },
      { name:'Loài sứa bất tử ngoài đời', score:'78 pts', badge:badgeMid, desc:'Chủ đề độc lạ, dễ viral nhưng cạnh tranh trung bình.' },
    ];

    // ── scheduler ──
    const schBadgeOn = 'font-size:10px; font-weight:800; color:#1a9e7a; background:#e3fff4; border:1.5px solid '+ink+'; padding:2px 9px; border-radius:999px;';
    const schBadgeOff = 'font-size:10px; font-weight:800; color:#8676bd; background:#f3ecff; border:1.5px solid '+ink+'; padding:2px 9px; border-radius:999px;';
    const schedule = [
      { name:'Sleep Stories VN', next:'Chạy tiếp: hôm nay 21:00', cadence:'daily', state:'Bật', badge:schBadgeOn, grad:'linear-gradient(135deg,#8db4ff,#c9b3ff)' },
      { name:'Calm Mind', next:'Chạy tiếp: T4, T6', cadence:'3x_weekly', state:'Bật', badge:schBadgeOn, grad:'linear-gradient(135deg,#7fe6d8,#a9d4ff)' },
      { name:'Deep Focus', next:'Chạy tiếp: CN 08:00', cadence:'weekly', state:'Bật', badge:schBadgeOn, grad:'linear-gradient(135deg,#c79dff,#ffb3e6)' },
      { name:'Night Rain', next:'Đã tạm dừng lịch', cadence:'daily', state:'Tắt', badge:schBadgeOff, grad:'linear-gradient(135deg,#9db8ff,#7fe6d8)' },
    ];

    // ── approvals ──
    const qcPass = 'font-size:10px; font-weight:800; color:#fff; background:#22c9a8; border:1.5px solid '+ink+'; padding:2px 9px; border-radius:999px;';
    const qcWarn = 'font-size:10px; font-weight:800; color:#fff; background:#f2a93b; border:1.5px solid '+ink+'; padding:2px 9px; border-radius:999px;';
    const approvals = [
      { title:'Bí ẩn đại dương sâu thẳm', qc:qcPass, qcText:'QC PASS', channel:'Sleep Stories VN', dur:'8m 53s', ago:'12 phút trước', grad:'linear-gradient(135deg,#8db4ff,#b79cff)' },
      { title:'Âm thanh mưa rừng cho giấc ngủ', qc:qcWarn, qcText:'QC WARN', channel:'Calm Mind', dur:'10m 05s', ago:'34 phút trước', grad:'linear-gradient(135deg,#c79dff,#ffb3e6)' },
      { title:'Hành trình qua dải ngân hà', qc:qcPass, qcText:'QC PASS', channel:'Deep Focus', dur:'8m 33s', ago:'1 giờ trước', grad:'linear-gradient(135deg,#7fe6d8,#a9d4ff)' },
    ];

    // ── analytics ──
    const anCols = ['Video','Nền tảng','Lượt xem','Lượt thích','Giờ xem','Doanh thu'];
    const platYT = 'font-size:10px; font-weight:800; color:#fff; background:#ff5f9e; border:1.5px solid '+ink+'; padding:2px 9px; border-radius:999px; justify-self:start;';
    const analytics = [
      { title:'Tại sao ta ngủ mơ?', platform:'YOUTUBE', plat:platYT, views:'128.401', likes:'6.204', watch:'842h', rev:'$210.40' },
      { title:'Bí mật giấc ngủ sâu', platform:'YOUTUBE', plat:platYT, views:'98.220', likes:'4.881', watch:'611h', rev:'$164.12' },
      { title:'Tiếng mưa đêm thư giãn', platform:'YOUTUBE', plat:platYT, views:'76.510', likes:'3.402', watch:'503h', rev:'$121.90' },
      { title:'Hành trình qua dải ngân hà', platform:'YOUTUBE', plat:platYT, views:'54.118', likes:'2.740', watch:'388h', rev:'$92.55' },
      { title:'Đại dương băng ở Nam Cực', platform:'YOUTUBE', plat:platYT, views:'41.902', likes:'1.980', watch:'274h', rev:'$68.20' },
    ];

    // ── library ──
    const grads = ['linear-gradient(135deg,#8db4ff,#c9b3ff)','linear-gradient(135deg,#7fe6d8,#a9d4ff)','linear-gradient(135deg,#c79dff,#ffb3e6)','linear-gradient(135deg,#9db8ff,#7fe6d8)','linear-gradient(135deg,#ffb3e6,#c9b3ff)','linear-gradient(135deg,#a9d4ff,#c79dff)'];
    const libTitles = ['Tại sao ta ngủ mơ?','Bí mật của giấc ngủ sâu','Tiếng mưa đêm thư giãn','Hành trình qua dải ngân hà','Đại dương băng ở Nam Cực','Bí ẩn đại dương sâu thẳm'];
    const library = libTitles.map((t,i) => ({
      title:t, channel:['Sleep Stories VN','Calm Mind','Deep Focus'][i%3], dur:['7m 41s','9m 12s','10m 05s','8m 33s','8m 10s','8m 53s'][i], grad:grads[i],
      qc: i===2 ? qcWarn+'position:absolute;top:6px;left:6px;' : qcPass+'position:absolute;top:6px;left:6px;',
      qcText: i===2 ? 'WARN' : 'PASS',
    }));

    // ── platforms ──
    const pOn = 'font-size:10px; font-weight:800; color:#1a9e7a; background:#e3fff4; border:1.5px solid '+ink+'; padding:2px 9px; border-radius:999px;';
    const pOff = 'font-size:10px; font-weight:800; color:#8676bd; background:#f3ecff; border:1.5px solid '+ink+'; padding:2px 9px; border-radius:999px;';
    const platforms = [
      { name:'YouTube', handle:'@sleepstoriesvn', icon:ic(svgPlay), grad:'linear-gradient(135deg,#ff5f9e,#ffb3e6)', state:'Đã kết nối', badge:pOn },
      { name:'TikTok', handle:'chưa liên kết', icon:ic(svgNote), grad:'linear-gradient(135deg,#a877ff,#c9b3ff)', state:'Chưa kết nối', badge:pOff },
      { name:'Facebook', handle:'chưa liên kết', icon:ic(svgFb), grad:'linear-gradient(135deg,#37b6f5,#a9d4ff)', state:'Chưa kết nối', badge:pOff },
    ];

    // ── monetization ──
    const money = [
      { label:'Doanh thu tháng này', value:'$842.17', sub:'+18% so với tháng trước' },
      { label:'YouTube AdSense', value:'$681.40', sub:'ước tính từ RPM' },
      { label:'Affiliate', value:'$160.77', sub:'12 lượt chuyển đổi' },
    ];
    const rdOn = 'font-size:10px; font-weight:800; color:#1a9e7a; background:#e3fff4; border:1.5px solid '+ink+'; padding:2px 9px; border-radius:999px;';
    const rdOff = 'font-size:10px; font-weight:800; color:#8676bd; background:#f3ecff; border:1.5px solid '+ink+'; padding:2px 9px; border-radius:999px;';
    const dotOK = 'width:20px;height:20px;border-radius:50%;background:#22c9a8;border:2px solid '+ink+';display:flex;align-items:center;justify-content:center;color:#fff;font-size:11px;font-weight:800;';
    const dotNo = 'width:20px;height:20px;border-radius:50%;background:#f3ecff;border:2px solid #c9b8f0;display:flex;align-items:center;justify-content:center;color:#b0a3d6;font-size:11px;font-weight:800;';
    const readiness = [
      { name:'1000 subscribers', mark:'✓', dot:dotOK, state:'Đạt', badge:rdOn },
      { name:'4000 giờ xem công khai', mark:'✓', dot:dotOK, state:'Đạt', badge:rdOn },
      { name:'Bật kiếm tiền YouTube', mark:'✓', dot:dotOK, state:'Đã bật', badge:rdOn },
      { name:'Liên kết tài khoản AdSense', mark:'!', dot:dotNo, state:'Chưa', badge:rdOff },
    ];

    // ── audit ──
    const auPub = 'font-size:9px; font-weight:800; color:#fff; background:#22c9a8; border:1.5px solid '+ink+'; padding:2px 8px; border-radius:999px;';
    const auSys = 'font-size:9px; font-weight:800; color:#fff; background:#37b6f5; border:1.5px solid '+ink+'; padding:2px 8px; border-radius:999px;';
    const auUsr = 'font-size:9px; font-weight:800; color:#fff; background:#a877ff; border:1.5px solid '+ink+'; padding:2px 8px; border-radius:999px;';
    const audit = [
      { type:'PUBLISH', tag:auPub, msg:'Đăng "Tại sao ta ngủ mơ?" lên YouTube (unlisted)', actor:'admin', time:'14:20' },
      { type:'USER', tag:auUsr, msg:'Duyệt kịch bản job_8f21c', actor:'admin', time:'14:02' },
      { type:'SYSTEM', tag:auSys, msg:'Autopilot bắt đầu chu kỳ cho Deep Focus', actor:'system', time:'13:55' },
      { type:'SYSTEM', tag:auSys, msg:'Render hoàn tất scene_04 (Sleep Stories VN)', actor:'system', time:'13:40' },
      { type:'USER', tag:auUsr, msg:'Cập nhật giọng đọc kênh Calm Mind', actor:'admin', time:'12:18' },
      { type:'PUBLISH', tag:auPub, msg:'Đăng "Bí mật giấc ngủ sâu" (public)', actor:'admin', time:'11:02' },
    ];

    // ── system ──
    const sysCards = [
      { icon:ic(svgKey), title:'API Keys', rows:[{k:'Gemini',v:'••••3f2a'},{k:'YouTube Data',v:'••••9c17'},{k:'ElevenLabs',v:'••••ab04'}] },
      { icon:ic(svgMoney), title:'Giới hạn chi phí', rows:[{k:'Ngân sách/ngày',v:'$100.00'},{k:'Đã dùng hôm nay',v:'$23.80'},{k:'Cảnh báo tại',v:'80%'}] },
      { icon:ic(svgGear), title:'Cấu hình chung', rows:[{k:'Ngôn ngữ',v:'Tiếng Việt'},{k:'Múi giờ',v:'GMT+7'},{k:'Chế độ',v:st.dark?'Tối':'Sáng'}] },
      { icon:ic(svgWrench), title:'Bảo trì', rows:[{k:'Phiên bản',v:'v3.2.1'},{k:'DB',v:'PostgreSQL 16'},{k:'Uptime',v:'6d 4h'}] },
    ];

    return {
      navGroups, goSystem: set('system'), systemIcon: ic(this._svgGear),
      systemStyle: `display:flex; align-items:center; gap:11px; margin:14px 8px 2px; padding:8px 11px; border-radius:12px; cursor:pointer; color:${st.view==='system'?'#f45fce':'#8676bd'}; background:${st.view==='system'?'#ffe0f5':'#fff'}; border:2px solid ${ink}; box-shadow:2px 2px 0 0 rgba(74,59,122,.14);`,
      currentTab: labels[st.view] || 'OmniCast',
      toggleDark: () => this.setState({ dark: !st.dark }),
      darkIcon: ic(st.dark
        ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#f2a93b" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4.2" fill="#ffe0b0"/><path d="M12 3v2.4M12 18.6V21M3 12h2.4M18.6 12H21M5.6 5.6l1.7 1.7M16.7 16.7l1.7 1.7M18.4 5.6l-1.7 1.7M7.3 16.7l-1.7 1.7"/></svg>`
        : `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#8676bd" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 14.5A8 8 0 1 1 9.5 4a6.4 6.4 0 0 0 10.5 10.5z" fill="#e0d4ff"/></svg>`),
      pauseSvg: { __html: st.paused
        ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>`
        : `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1.4"/><rect x="14" y="5" width="4" height="14" rx="1.4"/></svg>` },
      bellIcon: ic(`<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#8676bd" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6z" fill="#ffe0f5"/><path d="M10 20a2 2 0 0 0 4 0"/></svg>`),
      togglePause: () => this.setState({ paused: !st.paused }),
      pauseLabel: st.paused ? 'Tạm dừng' : 'Đang chạy',
      pauseStyle: `display:inline-flex; align-items:center; gap:6px; border-radius:999px; padding:5px 13px; font-size:12px; font-weight:700; cursor:pointer; border:2px solid ${ink}; box-shadow:2px 2px 0 0 rgba(74,59,122,.15); color:${st.paused?'#ff5f9e':'#8676bd'}; background:${st.paused?'#fff0f6':'#fff'};`,
      isDashboard: st.view==='dashboard', isStudio: st.view==='studio', isChannels: st.view==='channels',
      isScheduler: st.view==='scheduler', isApprovals: st.view==='approvals', isAnalytics: st.view==='analytics',
      isLibrary: st.view==='library', isPlatforms: st.view==='platforms', isMonetization: st.view==='monetization',
      isAudit: st.view==='audit', isSystem: st.view==='system',
      kpis, pipelines, activities,
      steps, stepBody, renderStats, scenes, config, logs,
      chTabList: () => this.setState({ chSub:'list' }), chTabNiche: () => this.setState({ chSub:'niche' }),
      chShowList: st.chSub==='list', chShowNiche: st.chSub==='niche',
      chTab1Style: `padding:6px 14px; border-radius:999px; font-size:12px; font-weight:700; cursor:pointer; color:${st.chSub==='list'?'#f45fce':'#8676bd'}; background:${st.chSub==='list'?'#fff':'transparent'}; border:${st.chSub==='list'?'2px solid '+ink:'2px solid transparent'};`,
      chTab2Style: `padding:6px 14px; border-radius:999px; font-size:12px; font-weight:700; cursor:pointer; color:${st.chSub==='niche'?'#f45fce':'#8676bd'}; background:${st.chSub==='niche'?'#fff':'transparent'}; border:${st.chSub==='niche'?'2px solid '+ink:'2px solid transparent'};`,
      channels, chCols, niches,
      schedule, approvals, anCols, analytics, library, platforms, money, readiness, audit, sysCards,
      autopilotIcon: ic(svgRobot), schedCalIcon: ic(svgCal),
      // ── progress dock — Goal Widget ──
      toggleDock: () => this.setState({ dockOpen: !st.dockOpen }),
      dockOpen: st.dockOpen,
      dockCount: '3 đang chạy',
      dockBorder: st.dockOpen ? '1.5px solid rgba(180,150,255,.22)' : 'none',
      dockBodyMax: st.dockOpen ? '300px' : '0px',
      chevronRot: st.dockOpen ? 'rotate(0deg)' : 'rotate(180deg)',
      tasks: (() => {
        const palette = [
          { color:'#ff6fd0', glow:'rgba(255,111,208,.7)', g:'linear-gradient(90deg,#ff9de0,#ff5fc4)' },
          { color:'#6fa8ff', glow:'rgba(111,168,255,.7)', g:'linear-gradient(90deg,#8fc2ff,#5f8bff)' },
          { color:'#b07cff', glow:'rgba(176,124,255,.7)', g:'linear-gradient(90deg,#c9a3ff,#9d5fff)' },
          { color:'#7de08a', glow:'rgba(125,224,138,.7)', g:'linear-gradient(90deg,#a9f0b0,#4fd86a)' },
          { color:'#ffb44d', glow:'rgba(255,180,77,.7)', g:'linear-gradient(90deg,#ffd08a,#ff9e2e)' },
        ];
        // random hoá + đảm bảo không trùng màu
        const pool = palette.map((p,i)=>({p,r:Math.random()})).sort((a,b)=>a.r-b.r).map(x=>x.p);
        const jobs = [
          { title:'Sleep Stories VN', stage:'render · cảnh 5/8', pct:62, count:'62/100', charm:'✿', charm2:'🌸' },
          { title:'Deep Focus', stage:'script · Âm thanh mưa rừng', pct:28, count:'28/100', charm:'☾', charm2:'✦' },
          { title:'Calm Mind', stage:'image · Imagen 4', pct:84, count:'84/100', charm:'🐱', charm2:'🐈' },
        ];
        return jobs.map((j,i) => {
          const c = pool[i % pool.length];
          return {
            title:j.title, stage:j.stage, count:j.count, color:c.color, glow:c.glow,
            charm:j.charm, charm2:j.charm2, pctStr: j.pct + '%',
            fill: `position:absolute; left:0; top:0; height:100%; width:${j.pct}%; background:${c.g}; border-radius:999px; box-shadow:0 0 10px 1px ${c.glow}, inset 0 1px 0 rgba(255,255,255,.4);`,
            flower: `position:absolute; top:50%; left:${j.pct}%; transform:translate(-50%,-50%); font-size:19px; color:${c.color}; filter:drop-shadow(0 0 6px ${c.glow}); pointer-events:none; z-index:2;`,
            petal1: `font-size:8px; color:${c.color}; filter:drop-shadow(0 0 3px ${c.glow}); left:-6px; animation-delay:0s;`,
            petal2: `font-size:7px; color:#fff; filter:drop-shadow(0 0 3px ${c.glow}); left:2px; animation-delay:.9s;`,
            petal3: `font-size:6px; color:${c.color}; filter:drop-shadow(0 0 3px ${c.glow}); left:-2px; animation-delay:1.7s;`,
          };
        });
      })(),
    };
  }
}
