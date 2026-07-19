import { Component, useEffect, useState, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { api, getBaseUrl } from './api';
import { LineIcon } from './components/LineIcons';
import { PondScene } from './components/PondScene';
import { Home } from './pages/Home';
import { Channels } from './pages/Channels';
import { Approvals } from './pages/Approvals';
import { Budgets } from './pages/Budgets';
import { Settings } from './pages/Settings';

const qc = new QueryClient();

interface BoundaryState { error: Error | null }

class TabBoundary extends Component<{ children: ReactNode; tab: string }, BoundaryState> {
  state: BoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error };
  }

  componentDidUpdate(prev: { tab: string }) {
    if (prev.tab !== this.props.tab && this.state.error) this.setState({ error: null });
  }

  render() {
    if (this.state.error) {
      return (
        <div className="sticker p-4 text-sm" style={{ background: 'var(--red-soft)', color: 'var(--red)' }}>
          <div className="font-display font-bold">Tab này gặp lỗi 😿</div>
          <div className="mt-1 font-mono text-xs">{this.state.error.message}</div>
        </div>
      );
    }
    return this.props.children;
  }
}

type Tab = 'home' | 'channels' | 'approvals' | 'budgets' | 'settings';

const TABS: Array<{ id: Tab; label: string; icon: string }> = [
  { id: 'home', label: 'Tổng quan', icon: 'fish' },
  { id: 'channels', label: 'Kênh', icon: 'tv' },
  { id: 'approvals', label: 'Duyệt', icon: 'heart' },
  { id: 'budgets', label: 'Chi phí', icon: 'coin' },
  { id: 'settings', label: 'Cài đặt', icon: 'gear' },
];

const TITLES: Record<Tab, string> = {
  home: 'Tổng quan',
  channels: 'Kênh của bạn',
  approvals: 'Chờ duyệt',
  budgets: 'Ngân sách',
  settings: 'Cài đặt',
};

function StatusDot() {
  const sys = useQuery({ queryKey: ['system'], queryFn: api.systemState, refetchInterval: 4000, retry: false });
  const color = sys.isError ? 'var(--text3)' : sys.data?.data.paused ? 'var(--red)' : 'var(--green)';
  return <span className="pulse-dot inline-block h-2.5 w-2.5 rounded-full" style={{ background: color }} />;
}

function ApprovalsBadge() {
  const q = useQuery({ queryKey: ['approvals'], queryFn: api.approvals, refetchInterval: 15000, retry: false });
  const n = q.data?.total ?? 0;
  if (n === 0) return null;
  return (
    <span
      className="absolute -right-1.5 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[9px] font-bold text-white"
      style={{ background: 'var(--accent)', boxShadow: 'var(--glow-pink)' }}
    >
      {n}
    </span>
  );
}

function Shell() {
  const [tab, setTab] = useState<Tab>(getBaseUrl() ? 'home' : 'settings');
  const [dark, setDark] = useState(() => localStorage.getItem('omnicast.dark') === '1');
  const [slideDir, setSlideDir] = useState<'l' | 'r'>('r');

  const activeIdx = TABS.findIndex(t => t.id === tab);

  const goTab = (next: Tab) => {
    const nextIdx = TABS.findIndex(t => t.id === next);
    setSlideDir(nextIdx >= activeIdx ? 'r' : 'l');
    setTab(next);
  };

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
    localStorage.setItem('omnicast.dark', dark ? '1' : '0');
  }, [dark]);

  return (
    <div className="relative flex h-full flex-col">
      <PondScene dark={dark} />

      {/* Header — pill trắng mảnh trên mặt ao */}
      <header className="pt-safe relative z-10 px-4 pb-2">
        <div className="sticker flex items-center justify-between px-4 py-2.5" style={{ borderRadius: 999 }}>
          <div className="flex items-center gap-2">
            <span className="bob inline-flex"><LineIcon name="fish" size={20} className="text-[color:var(--accent)]" /></span>
            <span className="font-display text-lg font-bold" style={{ color: 'var(--heading)', letterSpacing: '0.02em' }}>
              OmniCast
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold" style={{ color: 'var(--text2)' }}>{TITLES[tab]}</span>
            <StatusDot />
          </div>
        </div>
      </header>

      {/* Nội dung — chuyển cảnh slide theo hướng tab */}
      <main key={tab} className={`relative z-10 flex-1 overflow-y-auto px-4 pb-4 pt-2 screen-in-${slideDir}`}>
        <TabBoundary tab={tab}>
          {tab === 'home' && <Home />}
          {tab === 'channels' && <Channels />}
          {tab === 'approvals' && <Approvals />}
          {tab === 'budgets' && <Budgets />}
          {tab === 'settings' && <Settings dark={dark} onToggleDark={() => setDark(v => !v)} />}
        </TabBoundary>
      </main>

      {/* Bottom nav — hõm nước trượt theo tab, icon active nổi trong bong bóng */}
      <nav className="pb-safe relative z-10 px-4 pt-6">
        <div className="relative" style={{ height: 60 }}>
          {/* thanh nền */}
          <div className="sticker absolute inset-0 overflow-hidden" style={{ borderRadius: 999 }}>
            {/* hõm nước — trượt cùng bubble */}
            <div
              className="absolute top-0"
              style={{
                left: `calc(${activeIdx * 20}% + 10%)`,
                transform: 'translateX(-50%)',
                transition: 'left 380ms cubic-bezier(0.34, 1.3, 0.64, 1)',
              }}
            >
              <svg width="72" height="30" viewBox="0 0 72 30" style={{ display: 'block' }}>
                <path d="M0 0 C14 0 16 22 36 22 C56 22 58 0 72 0 L72 0 L0 0 Z" fill="var(--water)" />
                <path d="M22 10 Q28 6 34 10 T46 10" stroke="var(--wave-ink)" strokeWidth="1.4" strokeLinecap="round" fill="none" opacity="0.7" />
              </svg>
            </div>
          </div>

          {/* bubble icon active — nổi trên hõm */}
          <div
            className="pointer-events-none absolute"
            style={{
              left: `calc(${activeIdx * 20}% + 10%)`,
              top: -18,
              transform: 'translateX(-50%)',
              transition: 'left 380ms cubic-bezier(0.34, 1.3, 0.64, 1)',
            }}
          >
            <div
              key={tab}
              className="bubble-pop flex h-12 w-12 items-center justify-center rounded-full text-white"
              style={{ backgroundImage: 'var(--grad-cta)', boxShadow: 'var(--shadow-pill)', border: '2.5px solid var(--surface)' }}
            >
              <LineIcon name={TABS[activeIdx].icon} size={25} />
            </div>
          </div>

          {/* hàng nút */}
          <div className="absolute inset-0 flex items-stretch">
            {TABS.map(t => {
              const active = tab === t.id;
              return (
                <button
                  key={t.id}
                  onClick={() => goTab(t.id)}
                  className="relative flex flex-1 flex-col items-center justify-end gap-0.5 pb-1.5"
                  style={{ color: active ? 'var(--green-ink)' : 'var(--text3)' }}
                >
                  <span
                    className="relative inline-flex items-center justify-center"
                    style={{ width: 34, height: 26, opacity: active ? 0 : 1, transition: 'opacity 200ms' }}
                  >
                    <LineIcon name={t.icon} size={23} />
                    {t.id === 'approvals' && <ApprovalsBadge />}
                  </span>
                  <span className={`text-[10px] ${active ? 'font-bold' : 'font-semibold'}`}>{t.label}</span>
                </button>
              );
            })}
          </div>
        </div>
      </nav>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <Shell />
    </QueryClientProvider>
  );
}
