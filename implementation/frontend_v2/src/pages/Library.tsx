import React, { useState } from 'react';
import { useApi, useInvalidate } from '../api/hooks';
import { apiPost } from '../api/client';
import {
  Button,
  Card,
  Skeleton,
  EmptyState,
  Badge,
  Drawer,
  QCBadge
} from '../components/ui';
import { Library as LibIcon, Film, Calendar, ArrowRight, AlertTriangle } from 'lucide-react';

/** Shared duration formatter — avoids float artifacts like "8.30000000000011s" */
function formatDuration(totalSec: number | undefined | null): string {
  if (!totalSec && totalSec !== 0) return '—';
  const m = Math.floor(totalSec / 60);
  const s = Math.round(totalSec % 60);
  return `${m}m ${s.toString().padStart(2, '0')}s`;
}

/** Product files (video/thumbnail) live under /pmedia (= output/products), NOT
 *  /media (= output/real) — getMediaUrl of a bare filename resolves to the wrong
 *  tree and 404s (defect S1/S2). The backend now returns an absolute /pmedia/...
 *  URL directly; this only builds one itself as a fallback for a bare filename. */
function pmediaUrl(p: any, file?: string | null): string {
  if (!file) return '';
  if (file.startsWith('/pmedia/') || file.startsWith('/media/') || file.startsWith('http')) return file;
  if (!p || !p.channel || !p.slug) return '';
  return `/pmedia/${p.channel}/${p.slug}/${file}`;
}

export const Library: React.FC = () => {
  const invalidate = useInvalidate();
  const [selectedProduct, setSelectedProduct] = useState<any | null>(null);
  const [videoError, setVideoError] = useState(false);
  const [thumbErrors, setThumbErrors] = useState<Record<number, boolean>>({});

  // Queries
  const { data: productsData, isLoading: isProductsLoading } = useApi<any>('/api/products?limit=100');

  const allProducts = productsData?.products || [];
  // Thư viện = nơi xem sản phẩm ĐÃ HOÀN THÀNH (đã upload — meta.youtube_id).
  // Sản phẩm đang làm dở sống ở tab Xưởng; tab "Tất cả" ở đây chỉ để tra cứu.
  const publishedProducts = allProducts.filter((p: any) => !!p.youtube_id);
  const [libTab, setLibTab] = useState<'published' | 'all'>('published');
  const products = libTab === 'published' ? publishedProducts : allProducts;

  // Rebuild metadata action
  const handleRebuildMeta = async () => {
    try {
      await apiPost('/api/products/rebuild-meta');
      invalidate('/api/products');
    } catch (e) {}
  };

  const handleStartRender = async (channelId: string) => {
    try {
      await apiPost(`/api/render/${channelId}`);
      invalidate('/api/pipeline');
    } catch (e) {}
  };

  const handlePublish = async (channelId: string) => {
    try {
      await apiPost(`/api/publish/${channelId}`, { privacy_status: 'unlisted' });
      invalidate('/api/approvals');
    } catch (e) {}
  };

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h2 className="disp text-2xl font-extrabold text-[var(--heading)]" style={{ textShadow: '0 0 18px rgba(244,95,206,.30)' }}>Thư viện <span className="text-[15px] tracking-[3px] text-[var(--accent)]" style={{ textShadow: '0 0 10px rgba(244,95,206,.65)' }}>⋆｡˚✧</span></h2>
          <p className="text-xs text-[var(--text2)]">Kho lưu trữ kịch bản, ấn phẩm video và kiểm định chất lượng</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-full border-2 border-[var(--ink)] overflow-hidden" style={{ boxShadow: 'var(--shadow-hard-sm)' }}>
            <button onClick={() => setLibTab('published')} className={`px-3 py-1.5 text-xs font-bold ${libTab === 'published' ? 'bg-[var(--accent)] text-white' : 'bg-[var(--surface)] text-[var(--text2)]'}`}>Đã đăng ({publishedProducts.length})</button>
            <button onClick={() => setLibTab('all')} className={`px-3 py-1.5 text-xs font-bold ${libTab === 'all' ? 'bg-[var(--accent)] text-white' : 'bg-[var(--surface)] text-[var(--text2)]'}`}>Tất cả ({allProducts.length})</button>
          </div>
          <Button variant="secondary" size="sm" onClick={handleRebuildMeta} className="text-xs">
            Đồng bộ Meta
          </Button>
        </div>
      </div>

      {isProductsLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <Skeleton h="160px" />
          <Skeleton h="160px" />
          <Skeleton h="160px" />
        </div>
      ) : products.length === 0 ? (
        <EmptyState
          icon={<LibIcon size={32} />}
          title={libTab === 'published' ? 'Chưa có video nào được đăng' : 'Chưa có sản phẩm nào'}
          desc={libTab === 'published'
            ? 'Video được duyệt & upload lên YouTube sẽ chuyển từ Xưởng vào đây. Chuyển tab "Tất cả" để xem cả sản phẩm đang làm.'
            : 'Các video đã sản xuất hoặc kịch bản đã lưu sẽ xuất hiện ở đây.'}
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {products.map((p: any, idx: number) => {
            const thumbUrl = pmediaUrl(p, p.thumbnail);
            const isRendered = !!p.video;
            const isPublished = !!p.youtube_id || p.status === 'uploaded' || p.status === 'published' || p.status === 'completed';
            const statusText = isPublished ? 'Đã đăng' : isRendered ? 'Đã render' : 'Script-only';

            return (
              <Card
                key={idx}
                onClick={() => { setSelectedProduct(p); setVideoError(false); }}
                className="flex flex-col justify-between hover:border-[var(--border-hover)] transition-all cursor-pointer group"
              >
                <div className="space-y-3">
                  {/* Thumbnail / Placeholder */}
                  <div className="w-full aspect-video rounded-[12px] overflow-hidden border-2 border-[var(--ink)] relative flex items-center justify-center" style={{ background: ['linear-gradient(135deg,#8db4ff,#c9b3ff)', 'linear-gradient(135deg,#7fe6d8,#a9d4ff)', 'linear-gradient(135deg,#c79dff,#ffb3e6)', 'linear-gradient(135deg,#9db8ff,#7fe6d8)', 'linear-gradient(135deg,#ffb3e6,#c9b3ff)', 'linear-gradient(135deg,#a9d4ff,#c79dff)'][idx % 6] }}>
                    {thumbUrl && !thumbErrors[idx] ? (
                      <img
                        src={thumbUrl}
                        className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                        alt={p.title}
                        onError={() => setThumbErrors(prev => ({ ...prev, [idx]: true }))}
                      />
                    ) : (
                      <Film size={28} className="text-[var(--text3)]" />
                    )}
                    <span className="absolute top-2 left-2">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-extrabold border-[1.5px] border-[var(--ink)] ${
                        isPublished ? 'bg-[var(--green)] text-white' : isRendered ? 'bg-[var(--blue)] text-white' : 'bg-[var(--surface2)] text-[var(--text2)]'
                      }`}>
                        {statusText}
                      </span>
                    </span>
                    <div className="absolute top-2 right-2 flex flex-col gap-1 items-end">
                      {p.score && <Badge variant="blue">{p.score} pts</Badge>}
                      <span className={`px-1.5 py-0.5 rounded-full text-[8px] font-extrabold font-mono border-[1.5px] border-[var(--ink)] text-white ${
                        p.qa_ok ? 'bg-[var(--green)]' : 'bg-[var(--amber)]'
                      }`}>
                        QA: {p.qa_ok ? 'PASS' : 'WARN'}
                      </span>
                    </div>
                  </div>

                  {/* Title & Info */}
                  <div className="space-y-1">
                    <span className="text-[10px] font-bold text-[var(--text3)] uppercase tracking-wider block">
                      Kênh: {p.channel}
                    </span>
                    <h4 className="font-semibold text-sm text-[var(--heading)] leading-snug line-clamp-2">
                      {p.title || p.slug}
                    </h4>
                  </div>
                </div>

                <div className="pt-3 border-t border-[var(--border-soft)] mt-4 flex items-center justify-between text-xs text-[var(--text2)] font-mono">
                  <span className="flex items-center gap-1">
                    <Calendar size={12} />
                    {p.created_at ? new Date(p.created_at).toLocaleDateString('vi-VN') : '—'}
                  </span>
                  <span className="text-[var(--blue)] hover:underline inline-flex items-center gap-1 font-semibold">
                    <span>Chi tiết</span>
                    <ArrowRight size={12} />
                  </span>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {/* ── DETAIL DRAWER ──────────────────────────────────────────────────── */}
      <Drawer
        isOpen={selectedProduct !== null}
        onClose={() => { setSelectedProduct(null); setVideoError(false); }}
        title={selectedProduct?.title || selectedProduct?.slug || 'Chi tiết sản phẩm'}
      >
        {selectedProduct && (
          <div className="space-y-6">
            {/* Metadata summary */}
            <div className="grid grid-cols-2 gap-3 text-xs bg-[var(--surface2)] p-3 rounded-[12px] border-[1.5px] border-[var(--border-soft)] font-mono">
              <div>
                <span className="text-[var(--text2)] block">Kênh:</span>
                <span className="font-semibold text-[var(--heading)]">{selectedProduct.channel}</span>
              </div>
              <div>
                <span className="text-[var(--text2)] block">Điểm Debate:</span>
                <span className="font-semibold text-[var(--heading)]">{selectedProduct.score || '—'} pts</span>
              </div>
              <div className="col-span-2 border-t border-[var(--border-soft)] pt-2 mt-1">
                <span className="text-[var(--text2)] block">Thời gian tạo:</span>
                <span className="text-[var(--heading)]">
                  {selectedProduct.created_at ? new Date(selectedProduct.created_at).toLocaleString('vi-VN') : '—'}
                </span>
              </div>
            </div>

            {/* QC Manifest Details Badges */}
            <div className="grid grid-cols-2 gap-2 my-4">
              <QCBadge label="Độ phân giải" value={selectedProduct.width && selectedProduct.height ? `${selectedProduct.width}x${selectedProduct.height}` : undefined} />
              <QCBadge label="Thời lượng" value={selectedProduct.duration_s ? formatDuration(selectedProduct.duration_s) : undefined} />
              <QCBadge label="Dung lượng" value={selectedProduct.size_mb ? `${selectedProduct.size_mb} MB` : undefined} />
              <QCBadge
                label="QA Status"
                value={selectedProduct.qa_ok ? 'PASS' : selectedProduct.qa_ok === false ? 'FAIL' : 'PENDING'}
                status={selectedProduct.qa_ok ? 'pass' : selectedProduct.qa_ok === false ? 'fail' : 'neutral'}
              />
            </div>

            {/* Video Player */}
            {selectedProduct.video ? (
              <div className="space-y-2">
                <span className="text-xs font-semibold text-[var(--text2)] block">Bản xem trước Video</span>
                {videoError ? (
                  <div className="p-4 bg-[var(--red-soft)] border-2 border-[var(--red)] rounded-[12px] flex items-center gap-2 text-xs text-[var(--red)] font-semibold">
                    <AlertTriangle size={16} />
                    <span>Video không tải được — kiểm tra file tồn tại trên đĩa hoặc thử Đồng bộ lại từ đĩa.</span>
                  </div>
                ) : (
                  <video
                    src={pmediaUrl(selectedProduct, selectedProduct.video)}
                    controls
                    preload="metadata"
                    className="w-full rounded-[14px] border-2 border-[var(--ink)] bg-black"
                    style={{ boxShadow: 'var(--shadow-hard-sm)' }}
                    onError={() => setVideoError(true)}
                  />
                )}
                <div className="flex justify-end gap-2 text-xs font-mono">
                  <a
                    href={pmediaUrl(selectedProduct, selectedProduct.video)}
                    download
                    className="text-[var(--blue)] hover:underline font-semibold"
                  >
                    Tải Video
                  </a>
                  {selectedProduct.thumbnail && (
                    <a
                      href={pmediaUrl(selectedProduct, selectedProduct.thumbnail)}
                      download
                      className="text-[var(--blue)] hover:underline font-semibold"
                    >
                      Tải Thumbnail
                    </a>
                  )}
                </div>
              </div>
            ) : (
              <div className="p-4 bg-[var(--surface2)] border-[1.5px] border-[var(--border-soft)] rounded-[12px] text-center text-xs text-[var(--text2)]">
                Chưa render video cho kịch bản này
              </div>
            )}

            {/* Script Text Reader */}
            {selectedProduct.script ? (
              <div className="space-y-2">
                <span className="text-xs font-semibold text-[var(--text2)] block">Nội dung Kịch bản</span>
                <div className="text-[var(--text)] border-2 border-[var(--ink)] rounded-[14px] p-4 text-[12px] leading-relaxed font-sans max-h-80 overflow-y-auto space-y-4" style={{ background: 'var(--surface3)' }}>
                  {selectedProduct.script.split('\n\n').map((para: string, idx: number) => {
                    const cleanPara = para.trim();
                    if (cleanPara.startsWith('[') || cleanPara.startsWith('#')) {
                      return <div key={idx} className="font-bold text-[var(--blue)] font-mono">{cleanPara}</div>;
                    }
                    return <p key={idx}>{cleanPara}</p>;
                  })}
                </div>
              </div>
            ) : (
              <div className="p-4 bg-[var(--surface2)] border-[1.5px] border-[var(--border-soft)] rounded-[12px] text-center text-xs text-[var(--text2)]">
                Không tìm thấy nội dung kịch bản
              </div>
            )}

            {/* Action Buttons */}
            <div className="pt-4 border-t-2 border-[var(--border-soft)] flex flex-col gap-2">
              <Button
                variant="secondary"
                onClick={async () => {
                  await fetch(`/api/product/meta?channel_id=${selectedProduct.channel}&slug=${selectedProduct.slug}&rebuild=true`);
                  invalidate('/api/products');
                  setSelectedProduct(null);
                }}
                className="w-full text-xs"
              >
                Đồng bộ lại từ đĩa (Backfill)
              </Button>
              <div className="flex gap-2">
                {!selectedProduct.video && (
                  <Button
                    variant="primary"
                    className="flex-1"
                    onClick={() => handleStartRender(selectedProduct.channel)}
                  >
                    Render Video
                  </Button>
                )}
                {selectedProduct.video && selectedProduct.status !== 'completed' && (
                  <Button
                    variant="primary"
                    className="flex-1"
                    onClick={() => handlePublish(selectedProduct.channel)}
                  >
                    Gửi duyệt đăng
                  </Button>
                )}
              </div>
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
};
