# Bàn giao — P0.1 nhóm 1 (containment), 2026-07-25

Code nằm trên working tree `ws/visuals-flow`, **chưa commit**. Suite: **1756 pass**
(tests/ trừ integration), 3 fail duy nhất do sandbox chạy test thiếu `.env` —
không dính code. 32 file đã ghi về đĩa, md5 khớp byte-for-byte với bản đã test.

## Về "codex plugin"

Không gọi được: không có trong catalog plugin của tài khoản, và không có
`codex` CLI trong VM Linux của bridge. Thay bằng **3 vòng audit đối kháng** với
subagent ngữ cảnh độc lập, mỗi agent được lệnh *phản bác* thay vì xác nhận, và
bắt buộc **chạy code** chứ không đọc suông. Vòng 4 bị cắt giữa chừng do giới hạn
phiên API; đòn tấn công cuối (phân bố lệch trong `correlation_ratio`) tôi tự chạy
— và nó **tìm ra lỗi thật**, đã sửa (xem mục cuối).

Audit tìm ra **~45 lỗi**, trong đó **11 lỗi do chính bản sửa vòng trước tạo ra**.
Đó là lý do phải lặp 3 vòng.

---

## Đã làm — P0.1 nhóm 1

### 1. Freeze/shadow scoring v2

`omnicast_scoring_mode` = `v1` | `shadow` | `v2`, **mặc định `shadow`**: v2 được
tính và ghi trên mọi topic nhưng **v1 vẫn quyết định** `auto_approved`.

Lý do cụ thể: cùng `outlier_ratio=8`, v2 cho 59.5 điểm với kênh median 2M và
75.5 với kênh median 20k — approve hay review phụ thuộc một chiều chưa ai hiệu
chuẩn. `ScoredTopic` giờ mang cả `total_score_v1`, `total_score_v2`,
`shadow_delta`, `shadow_disagrees`.

### 2. `discovery/scoring_calibration.py` — công cụ quyết định promote

- **Routing impact** theo làn (`approve→review` bao nhiêu), không chỉ trung bình.
- **Bằng chứng tách chiều**: Pearson **và** eta (correlation ratio). Chỉ tính
  trên rows `youtube_competitor` — nguồn duy nhất từng có double-count; gộp
  chung với rows RSS/Reddit gap-hằng-số sẽ pha loãng tương quan về 0 và bài
  kiểm tra tự đậu.
- Eta bắt được quan hệ **phi tuyến** mà Pearson mù: quan hệ hình chữ U xác định
  hoàn toàn cho `r = -0.03` ("đã tách"), eta = 0.86 ("chưa tách").
- `ready_to_promote` yêu cầu: đủ rows, đã tách (cả hai phép đo), không có row
  hỏng, và churn làn < 25% **cả tổng thể lẫn riêng youtube**.

### 3. Gỡ blocking khỏi event loop

`learn_for_channel` được await trong FastAPI handler nhưng chạy: caption
download, yt-dlp, Whisper, 10 lượt tải thumbnail, 2 vision SDK đồng bộ, sqlite,
`create_llm` (4 kết nối sqlite + `nvidia-smi`), OAuth refresh (HTTPS chặn, mặc
định 120s), `googleapiclient.discovery.build` (~200ms mỗi lần).

Đã đo và sửa: `fetch_comments` **1023ms → 20ms** loop stall. Transcript/ASR/
thumbnail chạy trên **pool riêng có giới hạn** (`RESEARCH_POOL_SIZE=2`) — không
phải executor mặc định dùng chung, nơi một job ASR 45 phút bắt lệnh 10ms không
liên quan phải chờ 1.8 giây.

### 4. Research run nguyên khối + gate máy cho writer

- `research_run_id` cho mỗi run; **artifact và provenance đi cùng nhau**. SQL cũ
  giữ playbook cũ nhưng thay `cohort_meta` mới → playbook học không có control
  group về sau đọc như đã kiểm chứng.
- `analytics/intel_gate.py`: tập trạng thái đóng — `ok` / `missing` /
  `uncontrolled` / `stale` / `error` / `legacy`. Writer chỉ tiêm playbook khi
  `usable`; `except Exception: pass` đã bị thay bằng status có kiểu + policy
  `competitor_intel_required` per-channel.
- **Row cũ trong vault.db → `legacy`, bị từ chối**: theo cấu trúc chúng là
  "artifact có thể cũ + metadata run mới nhất", không thể chứng minh được. Phải
  chạy lại learner mới dùng được. Đây là quyết định *cố ý*, không phải bug.

### 5. `fetch_comments` an toàn khi chạy song song

`_last_comments_error` (state trên adapter) đã bị **xoá hẳn** — hai lượt fetch
đồng thời ghi đè lý do của nhau. Status giờ nằm trên kết quả (`CommentFetch`,
kế thừa `list` nên caller cũ không đổi). OAuth hỏng **thật sự fallback API key**.

---

## Các lỗi audit tìm được đáng chú ý nhất

| Lỗi | Hậu quả |
|---|---|
| `_calc_trend_momentum` trả **số âm** | `ScoredTopic(ge=0)` raise → **một post Reddit bị downvote giết cả discovery run** |
| ASR budget: `if duration and duration > max` | `0.0` lọt cả hai cổng — và `0.0` chính là cái scanner báo cho **livestream/premiere** (`P0D`, `P1DT2H` parse sai) |
| `_ASR_MODELS` check-then-act | 8 caller đồng thời → **6 model được nạp**, 5 cái mồ côi nhưng vẫn thường trú. Ở `large-v3` là vài GB |
| Cache intel của writer (do tôi thêm ở vòng 2) | Cache cả kết quả **rỗng** → discovery học xong, writer vẫn thấy "chưa có gì" suốt 60s; với `required=True` là **fail cứng** |
| `correlation_ratio` chia bin theo **rank** | Tie bị tách nhóm → eta 1.0 trên eta thật 0.018, và **đổi kết quả khi xáo thứ tự dòng** |
| `correlation_ratio` chia bin theo **độ rộng** (bản sửa kế tiếp) | Một outlier ở 900 dồn 59 dòng vào 1 bin → quan hệ thật báo 0.09 = "đã tách" → **đèn xanh sai** |
| `getattr(brief, "competitor_intel_required")` | `OmnicastSchema` drop key lạ → cờ **luôn False**, nhánh fail-closed là dead code |
| Test không ghim gate của writer | Revert **cả hai nửa** của gate, **toàn bộ suite vẫn xanh** |

Bản sửa cuối của `correlation_ratio` gom nhóm theo **giá trị x**, cân theo số
điểm: tie luôn đi cùng nhau, độc lập thứ tự dòng, miễn nhiễm outlier. Đã verify
6 tính chất (lệch/tie/hằng/chữ-U/nhiễu/thứ tự).

---

## CHƯA làm — phần còn lại của brief §15

Đây mới là **1 trong 4 nhóm** của P0.1, và P0.1 chỉ là phần sửa lỗi của **1
trong 3 nhóm P0** trong brief.

**P0.1 còn lại**
2. Khoa học cohort: winner selection theo `views_per_day` (median cũng phải đổi
   theo, không thì lệch đơn vị), comparability theo từng cặp, cap winner/channel,
   prompt giữ mapping winner–control, proxy format qua `_classify_title` (~5 dòng,
   hàm đã có sẵn).
3. Làm capability chạy thật: `StackProfile` sinh từ channel config, scanner
   populate `similar_competitor_videos` + `production_requirements`, test xuyên
   `ChannelProfile → DiscoveryOrchestrator → ScoredTopic`, chạy shadow calibration
   trên dữ liệu thật.
4. Quyết định `video_intel`: wire vào producer hoặc đánh dấu `experimental/dead`.
   Hiện **không có production caller nào**.

**P0 khác trong brief §15 — chưa động tới**
- Competitor intelligence: **content pillar**, **comments** (đã fetch được nhưng
  chưa phân tích/nối vào intel), **schedule** (§4.6), **dossier thống nhất** (§4.5).
- **Niche opportunity model**: công thức brief yêu cầu `demand + supply weakness +
  audience fit + stack-fit + monetization + repeatability − risk`. Hiện có
  demand/supply/stack-fit/monetization; **thiếu audience fit, repeatability,
  penalty rủi ro production/legal/YMYL**.
- **Production mode router**: phân loại scene → chọn giữa 8 mode. Chưa bắt đầu.

## Việc cần bạn quyết

1. **Commit** — 32 file uncommitted trên `ws/visuals-flow`. Nên dọn churn CRLF
   (`.gitattributes` đã gửi lượt trước) *trước*, kẻo diff thật bị chôn.
2. **Row vault.db hiện có sẽ bị từ chối** (`legacy`) cho tới khi chạy lại
   `POST /api/competitor-intel/{channel_id}`. Cố ý — nhưng bạn cần biết trước.
3. **`omnicast_scoring_mode`** mặc định `shadow`. Muốn v2 quyết định thì phải
   thu shadow corpus + chạy `scoring_calibration.summarize` cho tới khi
   `ready_to_promote` là True.
4. `faster-whisper` / `yt-dlp` / `youtube-transcript-api` đã khai báo trong
   extra `competitor-research` — cần `uv pip install -e ".[competitor-research]"`
   để bật ASR fallback thật.
