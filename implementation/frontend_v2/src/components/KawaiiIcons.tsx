import React from 'react';

/**
 * Kawaii-neon icon set — original hand-drawn SVGs (faces + blush), ported from the
 * OmniCast Neon design. Stroke + pupils use `currentColor` so the icon inherits the
 * nav item's active/inactive color and works in both light and neon-dark themes.
 * Pastel fills stay fixed (they read on both surfaces).
 */

const eye = (x: number, y: number) => `<circle cx='${x}' cy='${y}' r='.85' fill='currentColor' stroke='none'/>`;
const blush = (x: number, y: number) => `<circle cx='${x}' cy='${y}' r='1.1' fill='#ff9ed8' stroke='none'/>`;
const S = "viewBox='0 0 28 28' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'";

const ICONS: Record<string, string> = {
  dashboard: `<svg ${S}><path d='M4.5 13.5 14 5.5l9.5 8'/><path d='M7 12.5V22h14v-9.5' fill='#ffd0ee'/>${eye(11,17.5)}${eye(17,17.5)}${blush(9,18.5)}${blush(19,18.5)}</svg>`,
  studio: `<svg ${S}><rect x='4' y='9.5' width='20' height='13' rx='3' fill='#e0d4ff'/><path d='M4.5 12.5 23.5 9.5'/><path d='M9 9.7l-1.2 2.8M14 9.2l-1.2 2.8M19 9l-1.2 2.8'/>${eye(11,17)}${eye(16,17)}${blush(9,18)}${blush(18,18)}</svg>`,
  storyboard: `<svg ${S}><rect x='3.5' y='6' width='9' height='7.5' rx='1.6' fill='#e0d4ff'/><rect x='15.5' y='6' width='9' height='7.5' rx='1.6' fill='#cdeeff'/><rect x='3.5' y='16.5' width='9' height='5.5' rx='1.6' fill='#fff0c9'/><rect x='15.5' y='16.5' width='9' height='5.5' rx='1.6' fill='#ffd0ee'/>${eye(6.5,10)}${eye(9.5,10)}${blush(5,11.2)}${blush(11,11.2)}</svg>`,
  library: `<svg ${S}><rect x='5.5' y='5.5' width='5' height='17' rx='1.6' fill='#cdeeff'/><rect x='11.5' y='5.5' width='5' height='17' rx='1.6' fill='#ffd0ee'/><path d='M17.6 6.4l4 .9-3 15.6-4-.9z' fill='#fff0c9'/></svg>`,
  channels: `<svg ${S}><path d='M14 8.5 10 4.5M14 8.5l4-4'/><rect x='4' y='8.5' width='20' height='14' rx='3.5' fill='#d3f7ea'/>${eye(11,15)}${eye(17,15)}${blush(9,16)}${blush(19,16)}</svg>`,
  scheduler: `<svg ${S}><circle cx='14' cy='15' r='8' fill='#ffe0d0'/><path d='M6 6.5 9 8.6M22 6.5l-3 2.1'/><path d='M14 15V11M14 15l3 1.5'/>${blush(9.5,16)}${blush(18.5,16)}</svg>`,
  approvals: `<svg ${S}><path d='M14 22.5S5 16.8 5 10.8A4.6 4.6 0 0 1 14 8.4a4.6 4.6 0 0 1 9 2.4C23 16.8 14 22.5 14 22.5z' fill='#ffd0ee'/>${eye(11.5,12.5)}${eye(16.5,12.5)}<path d='M13 14.8q1 .9 2 0'/></svg>`,
  platforms: `<svg ${S}><rect x='3.5' y='11' width='13' height='6' rx='3' fill='#e0d4ff'/><rect x='11.5' y='11' width='13' height='6' rx='3' fill='#cdeeff'/></svg>`,
  analytics: `<svg ${S}><rect x='4.5' y='14' width='4.2' height='8' rx='1.4' fill='#cdeeff'/><rect x='11.9' y='9' width='4.2' height='13' rx='1.4' fill='#ffd0ee'/><rect x='19.3' y='6' width='4.2' height='16' rx='1.4' fill='#d3f7ea'/></svg>`,
  monetization: `<svg ${S}><path d='M10 8.5h8l-2-3.2h-4z' fill='#fff0c9'/><path d='M9.2 8.7C7.4 11.4 6 14.4 6 16.6a8 8 0 0 0 16 0c0-2.2-1.4-5.2-3.2-7.9z' fill='#fff0c9'/><path d='M14 12.5v5M12 14h4'/>${blush(9.5,16)}${blush(18.5,16)}</svg>`,
  audit: `<svg ${S}><rect x='7' y='5.5' width='14' height='17' rx='2.4' fill='#fff0c9'/><path d='M10 10.5h8M10 14h8M10 17.5h5'/></svg>`,
  office: `<svg ${S}><rect x='6' y='10.5' width='16' height='12' rx='2.4' fill='#ffe0d0'/><path d='M6 10.5 8 5.5h12l2 5'/><path d='M12 22.5v-5h4v5'/>${blush(9,15)}${blush(19,15)}</svg>`,
  system: `<svg ${S}><circle cx='14' cy='14' r='6' fill='#e0d4ff'/><path d='M14 4v3M14 21v3M4 14h3M21 14h3M7 7l2 2M19 19l2 2M21 7l-2 2M7 21l2-2'/>${eye(11.6,14)}${eye(16.4,14)}</svg>`,
  robot: `<svg ${S}><path d='M14 4.5v3'/><circle cx='14' cy='4' r='1.4' fill='#ff9ed8' stroke='none'/><rect x='5.5' y='7.5' width='17' height='13' rx='4.5' fill='#cdeeff'/>${eye(10.5,13.5)}${eye(17.5,13.5)}<path d='M12 16.5q2 1.4 4 0'/>${blush(8.3,15.8)}${blush(19.7,15.8)}<path d='M9.5 23.5v-3M18.5 23.5v-3'/></svg>`,
  calendar: `<svg ${S}><rect x='4.5' y='6.5' width='19' height='16' rx='4' fill='#ffd0ee'/><path d='M4.5 11.5h19'/><path d='M9.5 4v4M18.5 4v4'/>${eye(11,16.5)}${eye(17,16.5)}<path d='M12.2 19q1.8 1.2 3.6 0'/></svg>`,
  key: `<svg ${S}><circle cx='9.5' cy='11' r='5' fill='#fff0c9'/><path d='M13.5 14.5 22 23M18.5 19.5l3-3'/>${eye(8,10.5)}${eye(11,10.5)}<path d='M8.4 13q1.1 .8 2.2 0'/></svg>`,
  wrench: `<svg ${S}><path d='M18.5 5a5.5 5.5 0 0 0-5 7.8L5 21.3a2.3 2.3 0 0 0 3.2 3.2l8.6-8.4a5.5 5.5 0 0 0 7-6.6l-3.6 3.5-3-.9-.9-3 3.5-3.5A5.6 5.6 0 0 0 18.5 5z' fill='#e0d4ff'/></svg>`,
  film: `<svg ${S}><path d='M4.5 9.5 22.6 5l1 3.9L5.5 13.4z' fill='#e0d4ff'/><path d='M9.3 8.3l1.5 3M14.5 7l1.5 3M19.7 5.7l1.5 3'/><rect x='4.5' y='13' width='19' height='9.5' rx='2.6' fill='#ffd0ee'/>${eye(11, 17.5)}${eye(17, 17.5)}<path d='M12.6 19.6q1.4 1 2.8 0'/>${blush(8.8, 18.6)}${blush(19.2, 18.6)}</svg>`,
};

// Solid brand glyphs (white fill, for colored platform tiles).
const GLYPHS: Record<string, string> = {
  play: `<svg viewBox='0 0 24 24'><path d='M8 5.5v13l11-6.5z' fill='currentColor' stroke='currentColor' stroke-width='1.6' stroke-linejoin='round'/></svg>`,
  tiktok: `<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M9 18.2V6.5l9-2v10.7'/><circle cx='6.8' cy='18.4' r='2.4' fill='currentColor' stroke='none'/><circle cx='15.8' cy='15.4' r='2.4' fill='currentColor' stroke='none'/></svg>`,
  facebook: `<svg viewBox='0 0 24 24'><path d='M13.5 21v-7h2.6l.4-3h-3V9.1c0-.9.3-1.5 1.6-1.5h1.6V5c-.3 0-1.2-.1-2.2-.1-2.2 0-3.7 1.3-3.7 3.8V11H8.2v3h2.6v7z' fill='currentColor'/></svg>`,
};

export type KawaiiName = keyof typeof ICONS | keyof typeof GLYPHS;

interface KawaiiIconProps {
  name: string;
  size?: number;
  className?: string;
  style?: React.CSSProperties;
}

export const KawaiiIcon: React.FC<KawaiiIconProps> = ({ name, size = 22, className = '', style }) => {
  const raw = ICONS[name] || GLYPHS[name] || ICONS.dashboard;
  const svg = raw.replace('<svg ', `<svg width='${size}' height='${size}' `);
  return (
    <span
      className={`inline-flex items-center justify-center shrink-0 ${className}`}
      style={{ width: size, height: size, lineHeight: 0, ...style }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
};

export default KawaiiIcon;
