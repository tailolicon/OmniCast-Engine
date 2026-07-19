/** Cảnh ao cá dưới đáy màn hình (bộ pin 鱼塘): mặt nước gợn sóng, cá bơi qua lại,
    rong đung đưa. Dark = mặt nước đêm hoàng hôn + sao. Fixed, không chặn touch. */

interface FishProps {
  color: string;
  size?: number;
  flip?: boolean;
}

/** Cá kawaii nét mảnh — mắt chấm + má hồng nhạt, vây tam giác mềm. */
export function Fish({ color, size = 34, flip }: FishProps) {
  return (
    <svg
      width={size}
      height={size * 0.62}
      viewBox="0 0 52 32"
      fill="none"
      style={flip ? { transform: 'scaleX(-1)' } : undefined}
    >
      <path
        d="M4 16c7-9 17-13 26-13 8 0 14 5 16 13-2 8-8 13-16 13-9 0-19-4-26-13z"
        fill={color}
        stroke="var(--ink)"
        strokeWidth="1.6"
        strokeLinejoin="round"
        opacity="0.92"
      />
      <path d="M46 16l5-7c-1 4-1 10 0 14z" fill={color} stroke="var(--ink)" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M24 3.5C22 7 22 11 24 14M32 4c-1.6 3-1.6 7 0 10" stroke="var(--ink)" strokeWidth="1.2" strokeLinecap="round" opacity="0.5" />
      <circle cx="13" cy="14" r="1.7" fill="var(--ink)" />
      <circle cx="17.5" cy="19" r="2" fill="#f2b8ad" opacity="0.75" />
      <path d="M9 17.5q1.6 1.2 3.2 0" stroke="var(--ink)" strokeWidth="1.1" strokeLinecap="round" />
    </svg>
  );
}

/** Cụm rong nét mảnh. */
function Seaweed({ height = 46, left, delay = '0s' }: { height?: number; left: string; delay?: string }) {
  return (
    <svg
      className="sway absolute bottom-0"
      style={{ left, animationDelay: delay }}
      width={height * 0.55}
      height={height}
      viewBox="0 0 26 48"
      fill="none"
      stroke="var(--accent)"
      strokeWidth="1.6"
      strokeLinecap="round"
      opacity="0.65"
    >
      <path d="M6 48C4 38 8 32 5 24c-2-6 0-12 3-16" />
      <path d="M13 48c1-8-2-14 1-22 2-5 1-10-1-14" />
      <path d="M20 48c2-9-2-13 0-21 1.5-5 4-8 4-12" />
      <circle cx="8" cy="6" r="1.6" fill="var(--accent)" stroke="none" />
      <circle cx="12.5" cy="10" r="1.3" fill="var(--accent)" stroke="none" />
      <circle cx="23" cy="13" r="1.4" fill="var(--accent)" stroke="none" />
    </svg>
  );
}

interface PondSceneProps {
  dark: boolean;
}

export function PondScene({ dark }: PondSceneProps) {
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-0 overflow-hidden" style={{ height: '34vh' }} aria-hidden>
      {/* sao đêm (dark) */}
      {dark && (
        <>
          {[
            { top: '2%', left: '12%', d: '0s' },
            { top: '10%', left: '78%', d: '1.2s' },
            { top: '-4%', left: '46%', d: '2s' },
          ].map((s, i) => (
            <svg key={i} className="twinkle absolute" style={{ top: s.top, left: s.left, animationDelay: s.d }} width="12" height="12" viewBox="0 0 24 24" fill="var(--star)">
              <path d="M12 2l2.2 6.2L20 10l-5.8 1.8L12 18l-2.2-6.2L4 10l5.8-1.8z" />
            </svg>
          ))}
        </>
      )}

      {/* chấm màu blur trôi lơ lửng (deco kiểu pin hiking đêm) */}
      <div className="bob absolute" style={{ top: '4%', left: '6%', width: 26, height: 26, borderRadius: '50%', background: dark ? '#8fe3c0' : 'var(--accent)', opacity: 0.35, filter: 'blur(3px)', animationDelay: '1s' }} />
      <div className="bob absolute" style={{ top: '18%', right: '8%', width: 16, height: 16, borderRadius: '50%', background: 'var(--star)', opacity: 0.4, filter: 'blur(2px)', animationDelay: '2.4s' }} />

      {/* mặt trời/trăng lặn sát mặt nước */}
      <div
        className="bob absolute"
        style={{
          bottom: '52%',
          right: '10%',
          width: 44,
          height: 44,
          borderRadius: '50%',
          background: dark ? 'radial-gradient(circle, #f7d9a8, #e8a68c)' : 'radial-gradient(circle, #ffffff, #eef6ef)',
          opacity: dark ? 0.98 : 0.7,
          boxShadow: dark ? '0 0 40px 6px rgba(244, 201, 155, 0.6)' : '0 0 18px rgba(255,255,255,0.8)',
        }}
      />

      {/* 2 lớp sóng nước */}
      <svg className="ripple-drift absolute bottom-0 left-[-30px]" width="120%" height="62%" viewBox="0 0 480 160" preserveAspectRatio="none">
        <path
          d="M0 36 Q40 22 80 34 T160 32 T240 38 T320 30 T400 36 T480 32 L480 160 L0 160 Z"
          fill="var(--water)"
          opacity="0.85"
        />
      </svg>
      <svg className="ripple-drift absolute bottom-0 left-[-60px]" style={{ animationDelay: '2.2s', animationDirection: 'reverse' }} width="130%" height="46%" viewBox="0 0 480 120" preserveAspectRatio="none">
        <path
          d="M0 28 Q48 14 96 26 T192 24 T288 30 T384 22 T480 28 L480 120 L0 120 Z"
          fill="var(--water-deep)"
          opacity="0.9"
        />
      </svg>

      {/* gợn sóng nét mảnh trên mặt nước */}
      <svg className="absolute" style={{ bottom: '58%', left: '18%' }} width="52" height="8" viewBox="0 0 52 8" stroke="var(--wave-ink)" strokeWidth="1.6" strokeLinecap="round" fill="none" opacity="0.8">
        <path d="M2 5 Q8 1 14 5 T26 5" />
        <path d="M32 5 Q38 1 44 5 T50 5" opacity="0.6" />
      </svg>

      {/* đàn cá bơi trong nước */}
      <div className="swim absolute" style={{ bottom: '26%' }}>
        <Fish color="var(--fish-coral)" size={40} />
      </div>
      <div className="swim absolute" style={{ bottom: '12%', animationDelay: '-9s', animationDuration: '34s' }}>
        <Fish color="var(--fish-mustard)" size={28} />
      </div>
      <div className="swim absolute" style={{ bottom: '35%', animationDelay: '-19s', animationDuration: '42s' }}>
        <Fish color="var(--fish-blue)" size={22} />
      </div>

      {/* rong hai góc */}
      <Seaweed left="4%" height={52} />
      <Seaweed left="86%" height={40} delay="1.4s" />
      <Seaweed left="14%" height={30} delay="2.6s" />
    </div>
  );
}
