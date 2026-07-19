import type { ReactNode } from 'react';

/** Gauge bong bóng tròn to kiểu màn hình "0%" của bộ 鱼塘 —
    vòng stroke mảnh + bóng nước bên trong. */
interface RingGaugeProps {
  pct: number;
  size?: number;
  danger?: boolean;
  children: ReactNode;
}

export function RingGauge({ pct, size = 168, danger, children }: RingGaugeProps) {
  const clamped = Math.max(0, Math.min(100, pct));
  const r = 46;
  const c = 2 * Math.PI * r;
  const stroke = danger ? 'var(--red)' : 'var(--accent)';

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg className="absolute inset-0" width={size} height={size} viewBox="0 0 104 104">
        <circle cx="52" cy="52" r={r} fill="var(--surface)" stroke="var(--border)" strokeWidth="2.5" />
        {/* mực nước trong bóng */}
        <path
          d={`M6 ${98 - clamped * 0.9} Q 30 ${92 - clamped * 0.9} 52 ${98 - clamped * 0.9} T 98 ${98 - clamped * 0.9} L 98 98 L 6 98 Z`}
          fill="var(--water)"
          opacity="0.9"
          clipPath="circle(46px at 52px 52px)"
        />
        <circle
          cx="52" cy="52" r={r}
          fill="none"
          stroke={stroke}
          strokeWidth="3.5"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - clamped / 100)}
          transform="rotate(-90 52 52)"
          style={{ transition: 'stroke-dashoffset 600ms ease' }}
        />
      </svg>
      <div className="relative z-[1] flex flex-col items-center">{children}</div>
    </div>
  );
}
