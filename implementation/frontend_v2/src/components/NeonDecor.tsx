import React from 'react';

/**
 * Kawaii-neon ambient background: sparkle grid, dreamy glow blobs, twinkling
 * stars and floating clouds. Purely decorative — fixed behind all content,
 * pointer-events disabled. Colors come from theme tokens so it works light/dark.
 */
const STARS: Array<{ s: React.CSSProperties; ch: string }> = [
  { s: { top: 80, left: 360, fontSize: 20 }, ch: '✦' },
  { s: { top: 220, right: 180, fontSize: 15, animationDelay: '.7s' }, ch: '✦' },
  { s: { bottom: 120, left: 320, fontSize: 17, animationDelay: '1.2s' }, ch: '✦' },
  { s: { bottom: 70, right: 320, fontSize: 13, animationDelay: '.4s' }, ch: '✦' },
  { s: { top: 130, left: '54%', fontSize: 11, color: '#ffb3e6', animationDelay: '1.9s' }, ch: '✦' },
  { s: { top: '48%', left: '20%', fontSize: 14, color: '#c9b3ff', animationDelay: '.9s' }, ch: '✚' },
  { s: { top: '64%', right: '8%', fontSize: 12, color: '#ffd45e', animationDelay: '2.4s' }, ch: '✦' },
  { s: { top: '24%', left: '32%', fontSize: 9, color: '#9ae1ff', animationDelay: '1.4s' }, ch: '✦' },
  { s: { bottom: '28%', left: '46%', fontSize: 12, color: '#ffb3e6', animationDelay: '3s' }, ch: '✚' },
  { s: { top: '12%', right: '34%', fontSize: 10, animationDelay: '.5s' }, ch: '✦' },
  { s: { bottom: '14%', right: '12%', fontSize: 16, color: '#c9b3ff', animationDelay: '1.1s' }, ch: '✦' },
];

const Cloud: React.FC<{ style: React.CSSProperties; scale?: number }> = ({ style, scale = 1 }) => (
  <div className="oc-cloud absolute" style={style}>
    <div style={{ width: 160 * scale, height: 46 * scale, background: 'var(--cloud)', borderRadius: 999 }} />
    <div style={{ width: 66 * scale, height: 66 * scale, background: 'var(--cloud)', borderRadius: '50%', position: 'absolute', top: -28 * scale, left: 28 * scale }} />
    <div style={{ width: 48 * scale, height: 48 * scale, background: 'var(--cloud)', borderRadius: '50%', position: 'absolute', top: -18 * scale, left: 86 * scale }} />
  </div>
);

export const NeonDecor: React.FC = () => {
  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none z-0" aria-hidden>
      <div className="oc-grid absolute" style={{ inset: -64, opacity: 0.45 }} />
      {/* dreamy glow blobs */}
      <div style={{ position: 'absolute', width: 560, height: 560, left: -160, top: -180, borderRadius: '50%', background: 'radial-gradient(circle, rgba(255,158,216,.30), transparent 65%)' }} />
      <div style={{ position: 'absolute', width: 640, height: 640, right: -200, bottom: -240, borderRadius: '50%', background: 'radial-gradient(circle, rgba(154,225,255,.34), transparent 65%)' }} />
      <div style={{ position: 'absolute', width: 420, height: 420, right: '24%', top: -160, borderRadius: '50%', background: 'radial-gradient(circle, rgba(201,179,255,.28), transparent 65%)' }} />
      <Cloud style={{ left: '6%', bottom: '8%', opacity: 0.55 }} />
      <Cloud style={{ right: '10%', top: '9%', opacity: 0.45, animationDelay: '3s' }} scale={0.7} />
      {STARS.map((st, i) => (
        <div key={i} className="star" style={st.s}>{st.ch}</div>
      ))}
    </div>
  );
};

export default NeonDecor;
