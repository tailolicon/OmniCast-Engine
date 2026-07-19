/** Icon nav nét mảnh kiểu bộ 鱼塘 — outline 1.7px, mặt kawaii chấm mắt. */

const S = "viewBox='0 0 28 28' fill='none' stroke='currentColor' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'";
const eye = (x: number, y: number) => `<circle cx='${x}' cy='${y}' r='.8' fill='currentColor' stroke='none'/>`;

const ICONS: Record<string, string> = {
  // cá — Tổng quan (ao nhà)
  fish: `<svg ${S}><path d='M3.5 14c4.5-5.5 10-8 15-8 4.5 0 7.5 3 9 8-1.5 5-4.5 8-9 8-5 0-10.5-2.5-15-8z'/><path d='M23 14l3.5-4.5c-.7 2.8-.7 6.2 0 9z'/>${eye(9, 12.5)}<path d='M6.8 15.5q1.4 1 2.8 0'/><path d='M14 7.5c-1 2-1 4 0 6M18 8c-.8 1.7-.8 3.6 0 5.3'/></svg>`,
  // tivi — Kênh
  tv: `<svg ${S}><rect x='4' y='9' width='20' height='14' rx='4'/><path d='M10 4.5 14 9l4-4.5'/>${eye(11, 14.5)}${eye(17, 14.5)}<path d='M12 17.5q2 1.4 4 0'/></svg>`,
  // tim — Duyệt
  heart: `<svg ${S}><path d='M14 23S5.5 17.5 5.5 11.7A4.4 4.4 0 0 1 14 9.4a4.4 4.4 0 0 1 8.5 2.3C22.5 17.5 14 23 14 23z'/>${eye(11.5, 13)}${eye(16.5, 13)}<path d='M12.8 15.4q1.2 1 2.4 0'/></svg>`,
  // đồng xu — Chi phí
  coin: `<svg ${S}><circle cx='14' cy='14' r='9.5'/><path d='M14 9v10M11 11.5h4.5a2 2 0 0 1 0 4h-3a2 2 0 0 0 0 4H17'/></svg>`,
  // bánh răng mặt cười — Cài đặt
  gear: `<svg ${S}><circle cx='14' cy='14' r='5.5'/><path d='M14 4.5v2.5M14 21v2.5M4.5 14H7M21 14h2.5M7.3 7.3l1.8 1.8M18.9 18.9l1.8 1.8M20.7 7.3l-1.8 1.8M9.1 18.9l-1.8 1.8'/>${eye(12.2, 13.5)}${eye(15.8, 13.5)}<path d='M12.6 15.6q1.4 1 2.8 0'/></svg>`,
};

interface LineIconProps {
  name: keyof typeof ICONS | string;
  size?: number;
  className?: string;
}

export function LineIcon({ name, size = 24, className = '' }: LineIconProps) {
  const raw = ICONS[name] ?? ICONS.fish;
  const svg = raw.replace('<svg ', `<svg width='${size}' height='${size}' `);
  return (
    <span
      className={`inline-flex items-center justify-center shrink-0 ${className}`}
      style={{ width: size, height: size, lineHeight: 0 }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
