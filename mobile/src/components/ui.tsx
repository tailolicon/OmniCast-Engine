import type { ReactNode, CSSProperties } from 'react';

/** UI primitives — bubble/glass style (Dreamy Sky, theo Pinterest board của user). */

interface CardProps {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  onClick?: () => void;
}

export function Card({ children, className = '', style, onClick }: CardProps) {
  return (
    <div className={`sticker p-4 ${className}`} style={style} onClick={onClick}>
      {children}
    </div>
  );
}

type Tone = 'accent' | 'green' | 'blue' | 'purple' | 'amber' | 'red' | 'muted';

const TONE_BG: Record<Tone, string> = {
  accent: 'var(--accent-soft)',
  green: 'var(--green-soft)',
  blue: 'var(--blue-soft)',
  purple: 'var(--purple-soft)',
  amber: 'var(--amber-soft)',
  red: 'var(--red-soft)',
  muted: 'var(--surface2)',
};

const TONE_FG: Record<Tone, string> = {
  accent: 'var(--accent)',
  green: 'var(--green-ink)',
  blue: 'var(--blue)',
  purple: 'var(--purple)',
  amber: 'var(--amber)',
  red: 'var(--red)',
  muted: 'var(--text2)',
};

interface BadgeProps {
  children: ReactNode;
  tone?: Tone;
}

export function Badge({ children, tone = 'muted' }: BadgeProps) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
      style={{ background: TONE_BG[tone], color: TONE_FG[tone] }}
    >
      {children}
    </span>
  );
}

interface ButtonProps {
  children: ReactNode;
  onClick?: () => void;
  tone?: Tone;
  disabled?: boolean;
  full?: boolean;
  small?: boolean;
  /** Nút chính: gradient hồng→tím + glow */
  cta?: boolean;
}

export function Button({ children, onClick, tone = 'accent', disabled, full, small, cta }: ButtonProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`sticker-sm press font-display font-bold ${cta ? 'cta' : ''} ${full ? 'w-full' : ''} ${
        small ? 'px-4 py-2 text-sm' : 'px-5 py-2.5 text-base'
      } ${disabled ? 'opacity-50' : ''}`}
      style={cta ? undefined : { background: TONE_BG[tone], color: TONE_FG[tone] }}
    >
      {children}
    </button>
  );
}

interface StatProps {
  label: string;
  value: ReactNode;
  tone?: Tone;
  icon?: ReactNode;
}

export function Stat({ label, value, tone = 'accent', icon }: StatProps) {
  return (
    <Card className="flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold" style={{ color: 'var(--text2)' }}>{label}</span>
        {icon}
      </div>
      <span className="stat-value text-3xl" style={{ color: TONE_FG[tone] }}>{value}</span>
    </Card>
  );
}

/** Progress bar kiểu goal-widget: track kính, fill gradient, tim ở mũi + chip đếm. */
interface GoalBarProps {
  pct: number;
  danger?: boolean;
  label?: string;
}

export function GoalBar({ pct, danger, label }: GoalBarProps) {
  const clamped = Math.max(0, Math.min(100, pct));
  return (
    <div className="relative">
      <div className="h-4 overflow-visible rounded-full" style={{ background: 'var(--surface2)', border: '1px solid var(--border-soft)' }}>
        <div
          className="relative h-full rounded-full"
          style={{
            width: `${clamped}%`,
            backgroundImage: danger
              ? 'linear-gradient(135deg, #ff6ea8, #ff9f6e)'
              : 'var(--grad-cta)',
            boxShadow: 'var(--glow-pink)',
            minWidth: clamped > 0 ? 16 : 0,
            transition: 'width 400ms ease',
          }}
        >
          {clamped > 0 && (
            <span className="absolute -right-1.5 -top-2 text-xs" style={{ filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.25))' }}>
              {danger ? '🐡' : '🐠'}
            </span>
          )}
        </div>
      </div>
      {label && (
        <span
          className="absolute -top-2 right-8 rounded-full px-2 py-0.5 text-[10px] font-bold"
          style={{ background: 'var(--surface)', color: 'var(--text2)', boxShadow: 'var(--shadow-pill)' }}
        >
          {label}
        </span>
      )}
    </div>
  );
}

export function Spinner() {
  return (
    <div className="flex items-center justify-center py-10">
      <span className="bob text-3xl">🐟</span>
    </div>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <Card className="text-sm" style={{ background: 'var(--red-soft)', color: 'var(--red)' }}>
      <span className="font-bold">Lỗi kết nối:</span> {message}
      <div className="mt-1 text-xs" style={{ color: 'var(--text2)' }}>
        Kiểm tra địa chỉ server trong tab Cài đặt.
      </div>
    </Card>
  );
}
