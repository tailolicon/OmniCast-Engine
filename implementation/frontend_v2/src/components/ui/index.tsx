import React, { useState, useEffect, useRef } from 'react';
import { useApi } from '../../api/hooks';
import { apiPost, getMediaUrl } from '../../api/client';

// ── Button ───────────────────────────────────────────────────────────────────
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'ghost' | 'danger' | 'secondary';
  size?: 'sm' | 'md' | 'lg';
}
export const Button: React.FC<ButtonProps> = ({ variant = 'secondary', size = 'md', className = '', style, ...props }) => {
  const base = 'inline-flex items-center justify-center font-bold rounded-full transition-all cursor-pointer border-2 active:translate-y-px disabled:opacity-50 disabled:cursor-not-allowed';
  const sizeClasses = {
    sm: 'px-3.5 py-1.5 text-xs gap-1.5',
    md: 'px-4 py-2 text-sm gap-2',
    lg: 'px-5 py-2.5 text-base gap-2',
  };
  const variantClasses = {
    primary: 'text-white border-[var(--ink)] bg-[linear-gradient(135deg,var(--accent),var(--purple))]',
    ghost: 'border-transparent text-[var(--text2)] hover:text-[var(--accent)] hover:bg-[var(--accent-soft)]',
    danger: 'text-white border-[var(--ink)] bg-[var(--red)]',
    secondary: 'bg-[var(--surface)] border-[var(--ink)] hover:bg-[var(--surface2)] text-[var(--text)]',
  };
  const withShadow = variant !== 'ghost';
  return (
    <button
      className={`${base} ${sizeClasses[size]} ${variantClasses[variant]} ${className}`}
      style={withShadow ? { boxShadow: 'var(--shadow-hard-sm)', ...style } : style}
      {...props}
    />
  );
};

// ── Card ─────────────────────────────────────────────────────────────────────
export const Card: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className = '', style, ...props }) => {
  return (
    <div
      className={`relative overflow-hidden border-2 border-[var(--ink)] rounded-[var(--radius-card)] p-5 ${className}`}
      style={{ background: 'var(--surface-gradient)', boxShadow: 'var(--shadow-hard), var(--glow)', ...style }}
      {...props}
    />
  );
};
export const CardHeader: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className = '', ...props }) => {
  return <div className={`flex items-start justify-between gap-4 mb-4 ${className}`} {...props} />;
};
export const CardTitle: React.FC<React.HTMLAttributes<HTMLHeadingElement>> = ({ className = '', ...props }) => {
  return <h3 className={`text-base font-semibold text-[var(--heading)] leading-none ${className}`} {...props} />;
};
export const CardSub: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className = '', ...props }) => {
  return <div className={`text-xs text-[var(--text2)] mt-1 ${className}`} {...props} />;
};

// ── KPI ──────────────────────────────────────────────────────────────────────
export interface KPIProps {
  label: string;
  value: string | number;
  sub?: React.ReactNode;
  icon?: React.ReactNode;
}
export const KPI: React.FC<KPIProps> = ({ label, value, sub, icon }) => {
  return (
    <Card className="flex flex-col justify-between h-full p-4">
      <span aria-hidden className="absolute -bottom-2.5 -right-1.5 text-4xl text-[var(--accent-soft)] pointer-events-none select-none">✦</span>
      <div className="relative">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[11px] text-[var(--text2)] font-bold">{label}</span>
          {icon && (
            <span className="w-[30px] h-[30px] rounded-[10px] border-2 border-[var(--ink)] bg-[var(--accent-soft)] flex items-center justify-center text-[var(--accent)] shrink-0">
              {icon}
            </span>
          )}
        </div>
        <div className="disp text-[28px] leading-tight font-extrabold text-[var(--heading)]">{value}</div>
      </div>
      {sub && <div className="relative text-[11px] text-[var(--text3)] mt-0.5">{sub}</div>}
    </Card>
  );
};

// ── Badge ────────────────────────────────────────────────────────────────────
export interface BadgeProps {
  variant?: 'green' | 'blue' | 'amber' | 'red' | 'purple' | 'neutral';
  children: React.ReactNode;
}
export const Badge: React.FC<BadgeProps> = ({ variant = 'neutral', children }) => {
  const classes = {
    neutral: 'bg-[var(--purple-soft)] text-[var(--text2)] border-[var(--ink)]',
    green: 'bg-[var(--green)] text-white border-[var(--ink)]',
    blue: 'bg-[var(--blue)] text-white border-[var(--ink)]',
    amber: 'bg-[var(--amber)] text-white border-[var(--ink)]',
    red: 'bg-[var(--red)] text-white border-[var(--ink)]',
    purple: 'bg-[var(--purple)] text-white border-[var(--ink)]',
  };
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-extrabold border-[1.5px] ${classes[variant]}`}>
      {children}
    </span>
  );
};

// ── StatusTag ────────────────────────────────────────────────────────────────
export interface StatusTagProps {
  status: 'idle' | 'running' | 'success' | 'failed';
}
export const StatusTag: React.FC<StatusTagProps> = ({ status }) => {
  const config = {
    idle: { label: 'Chờ', classes: 'bg-[var(--purple-soft)] text-[var(--text2)]' },
    running: { label: 'Đang chạy', classes: 'bg-[var(--blue)] text-white' },
    success: { label: 'Thành công', classes: 'bg-[var(--green)] text-white' },
    failed: { label: 'Lỗi', classes: 'bg-[var(--red)] text-white' },
  };
  const { label, classes } = config[status] || config.idle;
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-extrabold border-[1.5px] border-[var(--ink)] ${classes}`}>
      {status === 'running' && <span className="w-1.5 h-1.5 bg-white rounded-full mr-1.5 animate-ping"></span>}
      {label}
    </span>
  );
};

// ── Table ────────────────────────────────────────────────────────────────────
export const Table: React.FC<React.TableHTMLAttributes<HTMLTableElement>> = ({ className = '', children, ...props }) => {
  return (
    <div className="w-full overflow-x-auto border-2 border-[var(--ink)] rounded-[14px]" style={{ boxShadow: 'var(--shadow-hard-sm)' }}>
      <table className={`w-full border-collapse text-sm ${className}`} {...props}>
        {children}
      </table>
    </div>
  );
};
export const THead: React.FC<React.HTMLAttributes<HTMLTableSectionElement>> = (props) => <thead className="bg-[var(--surface2)] border-b-2 border-[var(--ink)]" {...props} />;
export const TBody: React.FC<React.HTMLAttributes<HTMLTableSectionElement>> = (props) => <tbody className="divide-y divide-[var(--border-soft)]" {...props} />;
export const TR: React.FC<React.HTMLAttributes<HTMLTableRowElement>> = (props) => <tr className="h-11 hover:bg-[var(--accent-soft)] transition-colors" {...props} />;
export const TH: React.FC<React.ThHTMLAttributes<HTMLTableHeaderCellElement>> = ({ className = '', ...props }) => <th className={`px-4 text-left font-extrabold text-[var(--text2)] text-[10px] uppercase tracking-wider ${className}`} {...props} />;
export const TD: React.FC<React.TdHTMLAttributes<HTMLTableDataCellElement>> = ({ className = '', ...props }) => <td className={`px-4 py-2 text-[var(--text)] align-middle ${className}`} {...props} />;

// ── Modal ────────────────────────────────────────────────────────────────────
export interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}
export const Modal: React.FC<ModalProps> = ({ isOpen, onClose, title, children }) => {
  React.useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    if (isOpen) window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#2a1a4a]/40 backdrop-blur-sm" onClick={onClose}>
      <div className="border-2 border-[var(--ink)] rounded-[var(--radius-card)] w-full max-w-md p-6 max-h-[90vh] overflow-y-auto" style={{ background: 'var(--surface-gradient)', boxShadow: 'var(--shadow-hard), var(--glow)' }} onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="disp text-lg font-extrabold text-[var(--heading)]">{title}</h3>
          <button className="text-[var(--text3)] hover:text-[var(--text)] text-xl cursor-pointer" onClick={onClose}>&times;</button>
        </div>
        {children}
      </div>
    </div>
  );
};

export interface ConfirmModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  desc: string;
  confirmLabel?: string;
  cancelLabel?: string;
}
export const ConfirmModal: React.FC<ConfirmModalProps> = ({ isOpen, onClose, onConfirm, title, desc, confirmLabel = 'Xác nhận', cancelLabel = 'Hủy' }) => {
  return (
    <Modal isOpen={isOpen} onClose={onClose} title={title}>
      <p className="text-sm text-[var(--text2)] mb-6 leading-relaxed">{desc}</p>
      <div className="flex items-center justify-end gap-3">
        <Button variant="ghost" onClick={onClose}>{cancelLabel}</Button>
        <Button variant="primary" onClick={() => { onConfirm(); onClose(); }}>{confirmLabel}</Button>
      </div>
    </Modal>
  );
};

// ── Drawer ───────────────────────────────────────────────────────────────────
export interface DrawerProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}
export const Drawer: React.FC<DrawerProps> = ({ isOpen, onClose, title, children }) => {
  React.useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    if (isOpen) window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  return (
    <>
      {isOpen && <div className="fixed inset-0 z-40 bg-[#2a1a4a]/35 backdrop-blur-sm transition-opacity" onClick={onClose} />}
      <div className={`fixed top-0 right-0 bottom-0 z-50 w-full max-w-[480px] border-l-2 border-[var(--ink)] shadow-2xl transition-transform duration-300 ${isOpen ? 'translate-x-0' : 'translate-x-full'} flex flex-col`} style={{ background: 'var(--surface-gradient)' }}>
        <div className="flex items-center justify-between p-4 border-b-2 border-[var(--border-soft)]">
          <h3 className="disp font-extrabold text-lg text-[var(--heading)]">{title}</h3>
          <button className="text-[var(--text3)] hover:text-[var(--text)] text-xl cursor-pointer" onClick={onClose}>&times;</button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">
          {children}
        </div>
      </div>
    </>
  );
};

// ── Skeleton ─────────────────────────────────────────────────────────────────
export const Skeleton: React.FC<{ w?: string; h?: string; className?: string }> = ({ w = '100%', h = '20px', className = '' }) => {
  return (
    <div
      className={`shimmer-loader rounded-md ${className}`}
      style={{ width: w, height: h }}
    />
  );
};

// ── EmptyState ───────────────────────────────────────────────────────────────
export interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  desc: string;
  actionLabel?: string;
  onAction?: () => void;
}
export const EmptyState: React.FC<EmptyStateProps> = ({ icon, title, desc, actionLabel, onAction }) => {
  return (
    <div className="flex flex-col items-center justify-center p-8 text-center max-w-sm mx-auto my-4">
      {icon && <div className="text-[var(--text3)] mb-3">{icon}</div>}
      <h4 className="font-semibold text-sm text-[var(--heading)] mb-1">{title}</h4>
      <p className="text-xs text-[var(--text2)] mb-4 leading-relaxed">{desc}</p>
      {actionLabel && onAction && (
        <Button variant="secondary" size="sm" onClick={onAction}>{actionLabel}</Button>
      )}
    </div>
  );
};

// ── StatusPill ───────────────────────────────────────────────────────────────
export interface StatusPillProps {
  status: 'green' | 'yellow' | 'red';
}
export const StatusPill: React.FC<StatusPillProps> = ({ status }) => {
  const configs = {
    green: { label: 'Kết nối tốt', dot: 'bg-[var(--green)]', pill: 'bg-[var(--green-soft)] text-[var(--green-ink)]' },
    yellow: { label: 'Đang kết nối lại…', dot: 'bg-[var(--amber)] animate-pulse', pill: 'bg-[var(--amber-soft)] text-[var(--amber)]' },
    red: { label: 'Mất kết nối', dot: 'bg-[var(--red)]', pill: 'bg-[var(--red-soft)] text-[var(--red)]' },
  };
  const { label, dot, pill } = configs[status] || configs.green;
  return (
    <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold border-2 border-[var(--ink)] ${pill}`} style={{ boxShadow: 'var(--shadow-hard-sm)' }}>
      <span className={`w-2 h-2 rounded-full ${dot}`} style={{ animation: 'pulseDot 1.6s infinite' }}></span>
      {label}
    </span>
  );
};

// ── VideoPlayer ──────────────────────────────────────────────────────────────
export const VideoPlayer: React.FC<{ src: string; className?: string }> = ({ src, className = '' }) => {
  return (
    <video
      src={src}
      controls
      className={`w-full rounded-[14px] border-2 border-[var(--ink)] bg-black ${className}`}
      style={{ boxShadow: 'var(--shadow-hard-sm)' }}
    />
  );
};

// ── LogViewer ────────────────────────────────────────────────────────────────
export const LogViewer: React.FC<{ logs: string[]; className?: string }> = ({ logs, className = '' }) => {
  const bottomRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);
  return (
    <div className={`text-[var(--text2)] font-mono text-[11px] p-4 rounded-[14px] overflow-y-auto max-h-48 border-2 border-[var(--ink)] ${className}`} style={{ background: 'var(--surface3)' }}>
      {logs.map((line, idx) => <div key={idx} className="whitespace-pre-wrap">{line}</div>)}
      <div ref={bottomRef} />
    </div>
  );
};

// ── JsonKV ───────────────────────────────────────────────────────────────────
export const JsonKV: React.FC<{ data: Record<string, any> }> = ({ data }) => {
  return (
    <div className="bg-[var(--surface2)] border-[1.5px] border-[var(--border-soft)] p-3 rounded-[12px] font-mono text-xs overflow-x-auto text-[var(--text)]">
      {Object.entries(data).map(([k, v]) => (
        <div key={k} className="flex py-1 border-b border-[var(--border-soft)] last:border-b-0">
          <span className="font-semibold text-[var(--text2)] mr-2 w-28 shrink-0">{k}:</span>
          <span className="break-all">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
        </div>
      ))}
    </div>
  );
};

// ── Form Inputs ──────────────────────────────────────────────────────────────
export const Input: React.FC<React.InputHTMLAttributes<HTMLInputElement>> = ({ className = '', ...props }) => {
  return (
    <input
      className={`w-full px-3 py-1.5 bg-[var(--surface)] border-2 border-[var(--ink)] focus:border-[var(--accent)] focus:outline-hidden rounded-[10px] text-sm transition-colors text-[var(--text)] ${className}`}
      {...props}
    />
  );
};

export const Select: React.FC<React.SelectHTMLAttributes<HTMLSelectElement>> = ({ className = '', children, ...props }) => {
  return (
    <select
      className={`w-full px-3 py-1.5 bg-[var(--surface)] border-2 border-[var(--ink)] focus:border-[var(--accent)] focus:outline-hidden rounded-[10px] text-sm transition-colors text-[var(--text)] ${className}`}
      {...props}
    >
      {children}
    </select>
  );
};

export const Checkbox: React.FC<React.InputHTMLAttributes<HTMLInputElement>> = ({ className = '', ...props }) => {
  return (
    <input
      type="checkbox"
      className={`w-4 h-4 rounded-sm border-[var(--ink)] accent-[var(--accent)] focus:ring-0 cursor-pointer ${className}`}
      {...props}
    />
  );
};

// ── Section Accordion ───────────────────────────────────────────────────────
export const SectionAccordion: React.FC<{
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}> = ({ title, children, defaultOpen = false }) => {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  return (
    <div className="border-2 border-[var(--ink)] rounded-[14px] overflow-hidden bg-[var(--surface)]" style={{ boxShadow: 'var(--shadow-hard-sm)' }}>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="disp w-full px-4 py-2.5 flex items-center justify-between font-extrabold text-xs text-[var(--heading)] uppercase tracking-wider bg-[var(--surface2)] hover:bg-[var(--accent-soft)] transition-colors cursor-pointer"
      >
        <span>{title}</span>
        <span className="text-[var(--text3)] font-mono">{isOpen ? '▼' : '▶'}</span>
      </button>
      {isOpen && <div className="p-4 space-y-4 border-t-2 border-[var(--border-soft)]">{children}</div>}
    </div>
  );
};

// ── LogTail ──────────────────────────────────────────────────────────────────
export const LogTail: React.FC<{
  logs: string[];
  maxHeight?: string;
}> = ({ logs, maxHeight = '240px' }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [logs]);

  return (
    <div
      ref={containerRef}
      style={{ maxHeight, background: 'var(--surface3)' }}
      className="p-3 text-[var(--green)] font-mono text-[11px] rounded-[14px] border-2 border-[var(--ink)] overflow-y-auto space-y-1 select-text scrollbar-thin"
    >
      {logs.length === 0 ? (
        <div className="text-[var(--text3)] italic">No logs generated.</div>
      ) : (
        logs.map((line, idx) => {
          const isError = line.toLowerCase().includes('error') || line.toLowerCase().includes('failed');
          const isWarn = line.toLowerCase().includes('warning') || line.toLowerCase().includes('warn');
          return (
            <div
              key={idx}
              className={`word-break-all whitespace-pre-wrap ${
                isError ? 'text-[var(--red)] font-semibold' : isWarn ? 'text-[var(--amber)]' : ''
              }`}
            >
              {line}
            </div>
          );
        })
      )}
    </div>
  );
};

// ── QCBadge ──────────────────────────────────────────────────────────────────
export const QCBadge: React.FC<{
  label: string;
  value: string | number | undefined;
  status?: 'pass' | 'fail' | 'warn' | 'neutral';
}> = ({ label, value, status = 'neutral' }) => {
  const statusClasses = {
    pass: 'bg-[var(--green-soft)] text-[var(--green)] border-[var(--ink)]',
    fail: 'bg-[var(--red-soft)] text-[var(--red)] border-[var(--ink)]',
    warn: 'bg-[var(--amber-soft)] text-[var(--amber)] border-[var(--ink)]',
    neutral: 'bg-[var(--surface2)] text-[var(--text2)] border-[var(--border-soft)]',
  };
  return (
    <div className={`px-2.5 py-1.5 rounded-[10px] border-[1.5px] flex items-center justify-between text-xs font-mono ${statusClasses[status]}`}>
      <span className="opacity-75">{label}:</span>
      <span className="font-bold">{value != null ? value : '—'}</span>
    </div>
  );
};

// ── MiniChart ────────────────────────────────────────────────────────────────
export const MiniChart: React.FC<{
  data: number[];
  height?: number;
}> = ({ data, height = 40 }) => {
  if (data.length === 0) return null;
  const max = Math.max(...data) || 1;
  const points = data
    .map((val, idx) => {
      const x = (idx / (data.length - 1)) * 100;
      const y = 100 - (val / max) * 100;
      return `${x},${y}`;
    })
    .join(' ');

  return (
    <div className="w-full" style={{ height: `${height}px` }}>
      <svg className="w-full h-full overflow-visible" viewBox="0 0 100 100" preserveAspectRatio="none">
        <polyline fill="none" stroke="var(--blue)" strokeWidth="3" points={points} />
      </svg>
    </div>
  );
};

// ── DataTable ────────────────────────────────────────────────────────────────
export interface Column<T> {
  header: string;
  accessor: (item: T) => React.ReactNode;
  sortableKey?: string;
}
export interface DataTableProps<T> {
  data: T[];
  columns: Column<T>[];
  searchKey?: (item: T) => string;
  actions?: (item: T) => React.ReactNode;
}
export function DataTable<T>({ data, columns, searchKey, actions }: DataTableProps<T>) {
  const [searchQuery, setSearchQuery] = useState('');

  // Filter
  const filtered = searchQuery && searchKey
    ? data.filter(item => searchKey(item).toLowerCase().includes(searchQuery.toLowerCase()))
    : data;

  const sorted = [...filtered];

  return (
    <div className="space-y-3 w-full">
      {searchKey && (
        <input
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          placeholder="Tìm kiếm..."
          className="w-full max-w-xs px-3 py-1.5 bg-[var(--surface)] border-2 border-[var(--ink)] focus:border-[var(--accent)] focus:outline-hidden rounded-[10px] text-xs text-[var(--text)] transition-colors"
        />
      )}
      <div className="overflow-x-auto rounded-[14px] border-2 border-[var(--ink)] bg-[var(--surface)]" style={{ boxShadow: 'var(--shadow-hard-sm)' }}>
        <table className="w-full text-left border-collapse text-xs">
          <thead>
            <tr className="bg-[var(--surface2)] border-b-2 border-[var(--ink)] text-[var(--text2)] uppercase tracking-wider text-[10px] font-extrabold">
              {columns.map((col, idx) => (
                <th key={idx} className="p-3 font-extrabold">{col.header}</th>
              ))}
              {actions && <th className="p-3 font-extrabold text-right">Thao tác</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border-soft)]">
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={columns.length + (actions ? 1 : 0)} className="p-6 text-center text-[var(--text3)] italic">
                  Không có dữ liệu
                </td>
              </tr>
            ) : (
              sorted.map((item, rowIdx) => (
                <tr key={rowIdx} className="hover:bg-[var(--accent-soft)] transition-colors">
                  {columns.map((col, colIdx) => (
                    <td key={colIdx} className="p-3 align-middle text-[var(--text)]">{col.accessor(item)}</td>
                  ))}
                  {actions && (
                    <td className="p-3 align-middle text-right space-x-1.5">
                      {actions(item)}
                    </td>
                  )}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── VoicePicker ──────────────────────────────────────────────────────────────
export const VoicePicker: React.FC<{
  selectedVoice: string;
  onChange: (spec: string) => void;
  channelId?: string;
  onSaveSuccess?: () => void;
}> = ({ selectedVoice, onChange, channelId, onSaveSuccess }) => {
  const [langFilter, setLangFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [previewText, setPreviewText] = useState('Chào mừng bạn đến với hệ thống OmniCast.');
  const [previewAudioUrl, setPreviewAudioUrl] = useState('');
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);

  const { data: voicesData, isLoading: isVoicesLoading } = useApi<any>('/api/voices');
  const voices = voicesData?.voices || [];
  const langs = voicesData?.langs || [];

  const handlePreview = async (spec: string) => {
    setIsPreviewLoading(true);
    setPreviewAudioUrl('');
    try {
      const res = await apiPost<any>('/api/voice/preview', {
        spec,
        text: previewText
      });
      if (res && res.url) {
        setPreviewAudioUrl(getMediaUrl(res.url));
      }
    } catch (e) {
      console.error(e);
    } finally {
      setIsPreviewLoading(false);
    }
  };

  const handleSaveToChannel = async (spec: string) => {
    if (!channelId) return;
    try {
      await apiPost(`/api/channel/${channelId}/voice?spec=${encodeURIComponent(spec)}`);
      onSaveSuccess?.();
    } catch (e) {}
  };

  const filtered = voices.filter((v: any) => {
    const spec = `${v.provider}:${v.voice_id}`;
    const matchesSearch = 
      v.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      spec.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesLang = langFilter ? v.lang === langFilter : true;
    return matchesSearch && matchesLang;
  });

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2">
        <select
          value={langFilter}
          onChange={e => setLangFilter(e.target.value)}
          className="w-full px-2 py-1 bg-[var(--surface)] border-2 border-[var(--ink)] focus:border-[var(--accent)] rounded-[10px] text-xs text-[var(--text)] focus:outline-hidden"
        >
          <option value="">Lọc ngôn ngữ...</option>
          {langs.map((l: string) => (
            <option key={l} value={l}>{l}</option>
          ))}
        </select>
        <input
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          placeholder="Tìm giọng..."
          className="w-full px-2 py-1 bg-[var(--surface)] border-2 border-[var(--ink)] focus:border-[var(--accent)] rounded-[10px] text-xs text-[var(--text)] focus:outline-hidden"
        />
      </div>

      <div className="space-y-1.5 max-h-40 overflow-y-auto border-2 border-[var(--ink)] rounded-[12px] bg-[var(--surface2)] p-2">
        {isVoicesLoading ? (
          <div className="text-[10px] text-[var(--text3)] py-4 text-center">Đang tải giọng nói...</div>
        ) : filtered.length === 0 ? (
          <div className="text-[10px] text-[var(--text3)] py-4 text-center">Không tìm thấy giọng nói</div>
        ) : (
          filtered.map((v: any) => {
            const spec = `${v.provider}:${v.voice_id}`;
            const isSelected = selectedVoice === spec;
            return (
              <div
                key={spec}
                onClick={() => onChange(spec)}
                className={`flex items-center justify-between px-2.5 py-1.5 rounded-[10px] text-xs cursor-pointer border-[1.5px] ${
                  isSelected ? 'bg-[var(--accent-soft)] text-[var(--accent)] font-bold border-[var(--ink)]' : 'hover:bg-[var(--surface)] text-[var(--text2)] border-transparent'
                }`}
              >
                <div className="truncate pr-2">
                  <span className="font-semibold block truncate">{v.name}</span>
                  <span className="text-[9px] text-[var(--text3)] uppercase font-mono">{v.provider} · {v.gender} · {v.lang}</span>
                </div>
                {isSelected && <span className="text-[10px] text-[var(--accent)] font-bold">✓</span>}
              </div>
            );
          })
        )}
      </div>

      {selectedVoice && (
        <div className="bg-[var(--surface2)] p-2 rounded-[12px] border-[1.5px] border-[var(--border-soft)] space-y-2">
          <textarea
            value={previewText}
            onChange={e => setPreviewText(e.target.value)}
            className="w-full p-1.5 bg-[var(--surface)] border-2 border-[var(--ink)] focus:border-[var(--accent)] rounded-[10px] text-[10px] min-h-10 text-[var(--text)] focus:outline-hidden"
            placeholder="Văn bản nghe thử..."
          />
          <div className="flex items-center justify-between gap-2">
            <button
              type="button"
              onClick={() => handlePreview(selectedVoice)}
              disabled={isPreviewLoading}
              className="px-2.5 py-1 bg-[var(--surface)] hover:bg-[var(--surface2)] border-[1.5px] border-[var(--ink)] text-[10px] font-bold rounded-full text-[var(--text)] cursor-pointer"
              style={{ boxShadow: 'var(--shadow-hard-sm)' }}
            >
              {isPreviewLoading ? 'Đang tạo...' : 'Nghe thử'}
            </button>
            {channelId && (
              <button
                type="button"
                onClick={() => handleSaveToChannel(selectedVoice)}
                className="px-2.5 py-1 text-white text-[10px] font-bold rounded-full cursor-pointer border-[1.5px] border-[var(--ink)]"
                style={{ background: 'linear-gradient(135deg,var(--accent),var(--purple))', boxShadow: 'var(--shadow-hard-sm)' }}
              >
                Lưu làm mặc định
              </button>
            )}
          </div>
          {previewAudioUrl && <audio src={previewAudioUrl} controls className="w-full h-8 mt-1" autoPlay />}
        </div>
      )}
    </div>
  );
};
