// BS-2 — Error translator: map raw backend/tool error strings to plain Vietnamese
// + a suggested action. Single source of truth so every surface (notification bell,
// approval cards, job rows) shows the same human message instead of raw FFmpeg/OAuth
// stack traces. Matching is substring/regex, case-insensitive, first match wins.

export interface TranslatedError {
  title: string;        // short human title (VN)
  detail: string;       // what it means / how to fix
  action?: {            // optional one-click action
    label: string;
    to?: string;        // route to navigate (react-router path)
    kind?: 'retry';     // or a known action kind the caller handles
  };
  severity: 'error' | 'warning';
}

interface Rule {
  test: RegExp;
  build: (raw: string) => TranslatedError;
}

const RULES: Rule[] = [
  {
    test: /quota.?exceeded|exceededquota|dailylimitexceeded|quota.*(units|limit)/i,
    build: () => ({
      title: 'Hết hạn mức YouTube API',
      detail: 'Quota upload YouTube trong ngày đã cạn (mỗi upload ~1.600 units, mặc định 10.000/ngày). Chờ reset 00:00 giờ Thái Bình Dương hoặc xin tăng quota.',
      action: { label: 'Xem quota', to: '/system' },
      severity: 'error',
    }),
  },
  {
    test: /oauth|token.*(expired|invalid|revoked)|invalid_grant|refresh token/i,
    build: () => ({
      title: 'Đăng nhập YouTube hết hạn',
      detail: 'OAuth token của kênh đã hết hạn hoặc bị thu hồi. Chạy lại xác thực để cấp token mới.',
      action: { label: 'Tới Providers', to: '/system' },
      severity: 'error',
    }),
  },
  {
    test: /compliance|policy.?block|ymyl|disclaimer|verifiable source/i,
    build: () => ({
      title: 'Kịch bản vi phạm chính sách',
      detail: 'ComplianceChecker chặn trước khi đăng (thiếu disclaimer y tế, nguồn không kiểm chứng, hoặc vi phạm policy YouTube). Sửa kịch bản hoặc bật Force khi duyệt nếu chắc chắn.',
      action: { label: 'Xem chính sách', to: '/system' },
      severity: 'error',
    }),
  },
  {
    test: /ffmpeg|libx264|aac|moov atom|invalid data|codec|Output audit failed/i,
    build: (raw) => ({
      title: 'Lỗi render/ghép video',
      detail: /Output audit failed/i.test(raw)
        ? 'Video render xong nhưng không đạt QC (âm lượng/độ dài/độ phân giải/visual). Xem chi tiết issues rồi render lại.'
        : 'FFmpeg lỗi khi ghép/encode video. Thường do file nguồn hỏng hoặc thiếu codec. Thử render lại.',
      action: { label: 'Render lại', kind: 'retry' },
      severity: 'error',
    }),
  },
  {
    test: /flow.*(fail|timeout|expired)|playwright|browser.*closed|~~~~\^\^/i,
    build: () => ({
      title: 'Phiên Google Flow lỗi',
      detail: 'Trình duyệt Flow (tạo ảnh) hết phiên hoặc timeout. Đăng nhập lại profile Flow, hoặc hệ thống sẽ tự lùi về ảnh stock.',
      action: { label: 'Render lại', kind: 'retry' },
      severity: 'warning',
    }),
  },
  {
    test: /rate.?limit|429|too many requests/i,
    build: () => ({
      title: 'Bị giới hạn tần suất',
      detail: 'Nhà cung cấp (TTS/LLM/ảnh) trả 429 — gọi quá nhanh. Đợi một lát rồi thử lại; cân nhắc giảm số job song song.',
      action: { label: 'Thử lại', kind: 'retry' },
      severity: 'warning',
    }),
  },
  {
    test: /connection|timed? out|unreachable|ECONNREFUSED|network/i,
    build: () => ({
      title: 'Lỗi kết nối mạng',
      detail: 'Không gọi được dịch vụ bên ngoài (mạng/API tạm gián đoạn). Kiểm tra internet rồi thử lại.',
      action: { label: 'Thử lại', kind: 'retry' },
      severity: 'warning',
    }),
  },
];

/** Translate a raw error string to a human VN message + action. Returns a generic
 *  fallback (keeping the raw text as detail) when no rule matches. */
export function translateError(raw?: string | null): TranslatedError {
  const text = (raw || '').toString();
  for (const rule of RULES) {
    if (rule.test.test(text)) return rule.build(text);
  }
  return {
    title: 'Lỗi hệ thống',
    detail: text.slice(0, 300) || 'Không rõ nguyên nhân — xem log chi tiết.',
    severity: 'error',
  };
}
