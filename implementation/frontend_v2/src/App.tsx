import React, { useState, useEffect, useRef } from 'react';
import { HashRouter, Routes, Route, Navigate, Link, useLocation } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { connectSSE } from './api/sse';
import { translateError } from './lib/errorTranslator';
import { Dashboard } from './pages/Dashboard';
import { Studio } from './pages/Studio';
import { Approvals } from './pages/Approvals';
import { Library } from './pages/Library';
import { Channels } from './pages/Channels';
import { Monetization } from './pages/Monetization';
import { System } from './pages/System';
import { Scheduler } from './pages/Scheduler';
import { PlatformsDestinations } from './pages/PlatformsDestinations';
import { Analytics } from './pages/Analytics';
import { AuditLog } from './pages/AuditLog';
import { Sun, Moon, Bell, Pause, Play } from 'lucide-react';
import {
  StatusPill,
  ConfirmModal
} from './components/ui';
import { KawaiiIcon } from './components/KawaiiIcons';
import { NeonDecor } from './components/NeonDecor';
import { ProgressDock } from './components/ProgressDock';

// Sidebar nav — grouped, with kawaii icon names (see KawaiiIcons.tsx)
const NAV_GROUPS = [
  { eyebrow: 'Sản xuất', items: [
    { path: '/dashboard', label: 'Bảng điều khiển', icon: 'dashboard' },
    { path: '/studio', label: 'Xưởng', icon: 'studio' },
    { path: '/library', label: 'Thư viện', icon: 'library' },
  ]},
  { eyebrow: 'Kênh', items: [
    { path: '/channels', label: 'Kênh & Niche', icon: 'channels' },
    { path: '/scheduler', label: 'Lịch & Tự động', icon: 'scheduler' },
  ]},
  { eyebrow: 'Phân phối', items: [
    { path: '/approvals', label: 'Duyệt & Đăng', icon: 'approvals' },
    { path: '/platforms', label: 'Nền tảng & Đích', icon: 'platforms' },
    { path: '/analytics', label: 'Phân tích', icon: 'analytics' },
  ]},
  { eyebrow: 'Kiếm tiền', items: [
    { path: '/monetization', label: 'Doanh thu', icon: 'monetization' },
    { path: '/audit', label: 'Nhật ký kiểm toán', icon: 'audit' },
    { path: '/studio/office', label: 'Văn phòng', icon: 'office' },
  ]},
];
const ALL_NAV = [...NAV_GROUPS.flatMap(g => g.items), { path: '/system', label: 'Hệ thống', icon: 'system' }];

// Initialize TanStack Query Client
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

// Initialize real-time SSE stream events listener
connectSSE(queryClient);

// ── Error Boundary ───────────────────────────────────────────────────────────
// A thrown render error used to blank the ENTIRE app (React unmounts the whole tree
// when nothing catches it). Wrap the page content so a crash shows a readable card +
// the error, and the shell (sidebar/topbar) keeps working.
class PageErrorBoundary extends React.Component<
  { children: React.ReactNode; resetKey?: string },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidUpdate(prev: { resetKey?: string }) {
    // Navigating to another route clears the error so the new page can render.
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }
  render() {
    if (this.state.error) {
      return (
        <div className="max-w-2xl mx-auto mt-10 p-6 rounded-[18px] border-2 border-[var(--ink)] bg-[var(--red-soft)]" style={{ boxShadow: 'var(--shadow-hard)' }}>
          <div className="disp font-extrabold text-[var(--red)] mb-2">Màn hình này gặp lỗi khi hiển thị</div>
          <pre className="text-xs whitespace-pre-wrap break-all text-[var(--text2)] font-mono">
            {String(this.state.error?.stack || this.state.error?.message || this.state.error)}
          </pre>
          <button
            onClick={() => this.setState({ error: null })}
            className="mt-4 px-4 py-2 rounded-full border-2 border-[var(--ink)] text-white text-sm font-bold cursor-pointer"
            style={{ background: 'linear-gradient(135deg,var(--accent),var(--purple))', boxShadow: 'var(--shadow-hard-sm)' }}
          >
            Thử lại
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

// ── App Shell Layout ────────────────────────────────────────────────────────
const Layout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const location = useLocation();
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') || 'light');
  const [connectionStatus, setConnectionStatus] = useState<'green' | 'yellow' | 'red'>('green');
  const [systemPaused, setSystemPaused] = useState(false);
  const [isKillSwitchConfirmOpen, setIsKillSwitchConfirmOpen] = useState(false);
  const [isNotificationsOpen, setIsNotificationsOpen] = useState(false);
  const [errorsList, setErrorsList] = useState<any[]>([]);
  const consecutiveFailures = useRef(0);
  const [navPinned, setNavPinned] = useState(() => localStorage.getItem('navPinned') === '1');

  useEffect(() => {
    localStorage.setItem('navPinned', navPinned ? '1' : '0');
  }, [navPinned]);

  // Dark Mode Toggle
  useEffect(() => {
    // Dark là mặc định (:root). Light = thêm class 'light' để override tokens.
    if (theme === 'light') {
      document.documentElement.classList.add('light');
      document.documentElement.classList.remove('dark');
    } else {
      document.documentElement.classList.remove('light');
      document.documentElement.classList.add('dark');
    }
    localStorage.setItem('theme', theme);
  }, [theme]);

  // Connection Quality Polling
  useEffect(() => {
    const checkConnection = async () => {
      try {
        const res = await fetch('/api/status');
        if (res.ok) {
          consecutiveFailures.current = 0;
          setConnectionStatus('green');
        } else {
          throw new Error('Offline');
        }
      } catch (e) {
        consecutiveFailures.current += 1;
        if (consecutiveFailures.current >= 3) {
          setConnectionStatus('red');
        } else {
          setConnectionStatus('yellow');
        }
      }
    };
    checkConnection();
    const interval = setInterval(checkConnection, 5000);
    return () => clearInterval(interval);
  }, []);

  // System State Polling
  useEffect(() => {
    const fetchState = async () => {
      try {
        const res = await fetch('/api/system/state');
        if (res.ok) {
          const json = await res.json();
          const data = json?.data ?? json; // endpoint bọc envelope {data,...}
          setSystemPaused(!!data.paused);
        }
      } catch (e) {}
    };
    fetchState();
    const interval = setInterval(fetchState, 10000);
    return () => clearInterval(interval);
  }, []);

  // Errors Polling (Notification Bell)
  useEffect(() => {
    const fetchErrors = async () => {
      try {
        const res = await fetch('/api/errors?limit=10');
        if (res.ok) {
          const json = await res.json();
          const data = json?.data ?? json; // endpoint bọc envelope {data,...}
          setErrorsList(data.errors || []);
        }
      } catch (e) {}
    };
    fetchErrors();
    const interval = setInterval(fetchErrors, 15000);
    return () => clearInterval(interval);
  }, []);

  // Kill Switch Action
  const handleToggleSystem = async () => {
    try {
      const action = systemPaused ? 'resume' : 'pause';
      const res = await fetch(`/api/system/${action}`, { method: 'POST' });
      if (res.ok) {
        setSystemPaused(!systemPaused);
      }
    } catch (e) {}
  };

  const currentTab = [...ALL_NAV].sort((a, b) => b.path.length - a.path.length)
    .find(item => location.pathname.startsWith(item.path))?.label || 'OmniCast';

  return (
    <div className="relative flex h-screen overflow-hidden text-[var(--text)]">
      <NeonDecor />
      {/* Sidebar — icon-rail 74px, hover bung 236px; click logo để ghim mở (khớp .oc-sidebar bản Neon) */}
      <aside
        className={`oc-sidebar ${navPinned ? 'oc-pinned' : ''} relative z-10 shrink-0 flex flex-col pt-3.5 pb-3.5 gap-0.5 overflow-y-auto overflow-x-hidden scrollbar-thin backdrop-blur-md`}
        style={{
          background: 'var(--glass)',
          borderRight: '1.5px solid var(--glass-border)',
        }}
      >
        <div className="oc-logo flex items-center gap-2.5 mb-3.5" style={{ width: '100%' }}>
          <div
            onClick={() => setNavPinned((p) => !p)}
            title={navPinned ? 'Thu gọn sidebar' : 'Ghim mở sidebar'}
            className="relative flex items-center justify-center text-white font-extrabold text-lg select-none shrink-0 cursor-pointer"
            style={{ width: 38, height: 38, borderRadius: 13, background: 'linear-gradient(135deg,var(--accent),var(--purple))', border: '2px solid var(--ink)', boxShadow: '3px 3px 0 0 rgba(74,59,122,.2), var(--glow-pink)' }}
          >
            ✿
            <span style={{ position: 'absolute', top: -8, right: -8, fontSize: 13, color: 'var(--star)', filter: 'drop-shadow(0 0 4px rgba(255,212,94,.9))', animation: 'twinkle 2s infinite' }}>✦</span>
          </div>
          <span className="oc-label disp text-lg font-extrabold text-[var(--heading)] tracking-tight select-none">OmniCast</span>
        </div>
        {NAV_GROUPS.map((group, gi) => (
          <React.Fragment key={gi}>
            <div className="oc-eyebrow disp px-[18px] text-[10px] font-extrabold uppercase tracking-[.08em] text-[var(--text3)] select-none mt-2.5">
              {group.eyebrow}
            </div>
            {group.items.map((item) => {
              const isActive = location.pathname.startsWith(item.path) || (item.path === '/dashboard' && location.pathname === '/');
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  title={item.label}
                  className="oc-nav flex items-center transition-all rounded-xl"
                  style={{
                    height: 40,
                    margin: '2px 8px',
                    color: isActive ? 'var(--accent)' : 'var(--text2)',
                    background: isActive ? 'var(--accent-soft)' : 'transparent',
                    border: isActive ? '2px solid var(--ink)' : '2px solid transparent',
                    boxShadow: isActive ? 'var(--shadow-hard-sm), var(--glow-pink)' : 'none',
                  }}
                >
                  <span className="w-6 flex items-center justify-center shrink-0"><KawaiiIcon name={item.icon} size={22} /></span>
                  <span className="oc-label disp text-[13px] font-bold">{item.label}</span>
                </Link>
              );
            })}
          </React.Fragment>
        ))}
        <Link
          to="/system"
          title="Thiết lập hệ thống"
          className="oc-nav flex items-center transition-all rounded-xl mt-3"
          style={{
            height: 40,
            margin: '2px 8px',
            color: location.pathname.startsWith('/system') ? 'var(--accent)' : 'var(--text2)',
            background: location.pathname.startsWith('/system') ? 'var(--accent-soft)' : 'var(--surface)',
            border: '2px solid var(--ink)',
            boxShadow: 'var(--shadow-hard-sm)',
          }}
        >
          <span className="w-6 flex items-center justify-center shrink-0"><KawaiiIcon name="system" size={22} /></span>
          <span className="oc-label disp text-[13px] font-bold">Hệ thống</span>
        </Link>
      </aside>

      {/* Main Container */}
      <div className="relative z-10 flex-1 flex flex-col overflow-hidden">
        {/* Topbar */}
        <header className="h-[62px] flex items-center justify-between px-6 shrink-0">
          {/* Left: Breadcrumbs */}
          <div className="disp flex items-center gap-2 text-sm font-bold text-[var(--text2)]">
            <span className="hover:text-[var(--text)] transition-colors cursor-pointer">OmniCast</span>
            <span className="text-[var(--text3)]">✧</span>
            <span className="text-[var(--heading)]">{currentTab}</span>
          </div>

          {/* Right: Controls & Indicators */}
          <div className="flex items-center gap-2.5">
            {/* Connection Status */}
            <StatusPill status={connectionStatus} />

            {/* System Kill Switch */}
            <button
              onClick={() => setIsKillSwitchConfirmOpen(true)}
              className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold cursor-pointer border-2 border-[var(--ink)] transition-colors"
              style={{
                boxShadow: 'var(--shadow-hard-sm)',
                color: systemPaused ? 'var(--red)' : 'var(--text2)',
                background: systemPaused ? 'var(--red-soft)' : 'var(--surface)',
              }}
              title={systemPaused ? "Hệ thống đang tạm dừng" : "Hệ thống đang chạy"}
            >
              {systemPaused ? <Play size={12} /> : <Pause size={12} />}
              <span>{systemPaused ? "Tạm dừng" : "Đang chạy"}</span>
            </button>

            {/* Dark Mode Toggle */}
            <button
              onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}
              className="flex items-center justify-center rounded-xl text-[var(--text2)] hover:text-[var(--accent)] transition-colors cursor-pointer"
              style={{ width: 36, height: 36, background: 'var(--surface)', border: '2px solid var(--ink)', boxShadow: 'var(--shadow-hard-sm)' }}
              title="Chuyển chế độ sáng/tối"
            >
              {theme === 'light' ? <Moon size={17} /> : <Sun size={17} />}
            </button>

            {/* Notification Bell */}
            <div className="relative">
              <button
                onClick={() => setIsNotificationsOpen(!isNotificationsOpen)}
                className="flex items-center justify-center rounded-xl text-[var(--text2)] hover:text-[var(--accent)] transition-colors cursor-pointer relative"
                style={{ width: 36, height: 36, background: 'var(--surface)', border: '2px solid var(--ink)', boxShadow: 'var(--shadow-hard-sm)' }}
                title="Thông báo lỗi"
              >
                <Bell size={17} />
                {errorsList.length > 0 && (
                  <span className="absolute top-1 right-1 w-2.5 h-2.5 bg-[var(--red)] rounded-full border-2 border-[var(--surface)] animate-bounce"></span>
                )}
              </button>

              {/* Notification Dropdown */}
              {isNotificationsOpen && (
                <div className="absolute right-0 mt-2 w-80 border-2 border-[var(--ink)] rounded-[18px] z-50 p-4 max-h-96 overflow-y-auto" style={{ background: 'var(--surface-gradient)', boxShadow: 'var(--shadow-hard), var(--glow)' }}>
                  <div className="flex items-center justify-between border-b-2 border-[var(--border-soft)] pb-2 mb-2">
                    <span className="disp font-extrabold text-xs text-[var(--heading)]">Lỗi hệ thống gần đây</span>
                    <button onClick={() => setIsNotificationsOpen(false)} className="text-xs text-[var(--text3)] hover:text-[var(--text)] cursor-pointer">&times;</button>
                  </div>
                  {errorsList.length === 0 ? (
                    <div className="text-center py-4 text-xs text-[var(--text3)]">Không có lỗi hệ thống</div>
                  ) : (
                    <div className="space-y-2">
                      {errorsList.map((err, idx) => {
                        const t = translateError(err.message);
                        return (
                          <div key={idx} className={`p-2 rounded-[10px] text-[11px] leading-relaxed border-l-4 ${t.severity === 'warning' ? 'bg-[var(--amber-soft)] border-[var(--amber)]' : 'bg-[var(--red-soft)] border-[var(--red)]'}`}>
                            <div className="font-semibold text-[var(--heading)] mb-0.5">{t.title} <span className="font-mono text-[9px] text-[var(--text3)]">· {err.module || ''}</span></div>
                            <div className="text-[var(--text2)]">{t.detail}</div>
                            <div className="flex items-center justify-between mt-1">
                              <span className="text-[var(--text3)] text-[9px] font-mono">{err.timestamp}</span>
                              {t.action?.to && (
                                <Link to={t.action.to} onClick={() => setIsNotificationsOpen(false)} className="text-[9px] font-semibold text-[var(--blue)] hover:underline">{t.action.label} →</Link>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </header>

        {/* Content Area */}
        <main className="relative flex-1 overflow-y-auto px-6 pt-2 pb-7">
          <PageErrorBoundary resetKey={location.pathname}>{children}</PageErrorBoundary>
        </main>
      </div>

      {/* Goal Widget — floating live-progress dock */}
      <ProgressDock />

      {/* Kill Switch Confirm Modal */}
      <ConfirmModal
        isOpen={isKillSwitchConfirmOpen}
        onClose={() => setIsKillSwitchConfirmOpen(false)}
        onConfirm={handleToggleSystem}
        title={systemPaused ? "Khởi động lại hệ thống" : "Tạm dừng hệ thống"}
        desc={systemPaused 
          ? "Bạn có chắc chắn muốn tiếp tục các tác vụ sản xuất và đăng video của hệ thống?" 
          : "Tạm dừng hệ thống sẽ dừng mọi tiến trình sản xuất và đăng video tự động đang chạy. Các tiến trình hiện tại có thể bị gián đoạn."
        }
        confirmLabel={systemPaused ? "Khởi động lại" : "Tạm dừng"}
      />
    </div>
  );
};

// ── Fullscreen Office Companion Iframe ───────────────────────────────────────
const FullscreenOffice: React.FC = () => {
  return (
    <div className="fixed inset-0 z-50 bg-[var(--bg)] flex flex-col">
      <div className="h-12 border-b-2 border-[var(--ink)] flex items-center justify-between px-6 shrink-0" style={{ background: 'var(--surface-gradient)' }}>
        <span className="disp font-extrabold text-sm text-[var(--heading)]">Pixel Office Companion (Fullscreen)</span>
        <Link to="/studio" className="text-xs text-[var(--accent)] hover:underline font-bold flex items-center gap-1">
          &larr; Quay lại Xưởng
        </Link>
      </div>
      <div className="flex-1 w-full bg-[#120e1f] relative">
        <iframe
          src="/office_app/index.html"
          className="w-full h-full border-0"
          title="Pixel Office Fullscreen"
        />
      </div>
    </div>
  );
};

// ── App Routing & Providers ──────────────────────────────────────────────────
export const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <HashRouter>
        <Layout>
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/studio" element={<Studio />} />
            <Route path="/studio/office" element={<FullscreenOffice />} />
            <Route path="/library" element={<Library />} />
            <Route path="/channels" element={<Channels />} />
            <Route path="/scheduler" element={<Scheduler />} />
            <Route path="/approvals" element={<Approvals />} />
            <Route path="/platforms" element={<PlatformsDestinations />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/monetization" element={<Monetization />} />
            <Route path="/audit" element={<AuditLog />} />
            <Route path="/system" element={<System />} />
          </Routes>
        </Layout>
      </HashRouter>
    </QueryClientProvider>
  );
};
