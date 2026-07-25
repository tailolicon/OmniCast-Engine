> STATUS: SUPERSEDED (2026-07-26) bởi `IMPLEMENTATION_STATUS.md` §4b — toàn bộ việc trong §5 của file này đã làm xong. Giữ lại làm lịch sử; KHÔNG dùng làm nguồn sự thật.

# Bàn giao — P0 competitor-intel (5/5 mục), 2026-07-25

Trạng thái: **đã xong cả 5 mục P0**, code nằm trên working tree `ws/visuals-flow`,
**chưa commit** (theo chỉ đạo). Suite: **1610 pass** (tests/ trừ integration), 3 fail
duy nhất do thiếu `.env` trong sandbox chạy test — không liên quan code.

---

## 1. Nối `cohort.select_cohort` vào `competitor_intel` ✅

`_top_competitor_videos` (chỗ `vids.sort(key=views)`) đã **bị xoá hẳn**, thay bằng:

| Hàm mới | Vai trò |
|---|---|
| `_fetch_competitor_videos(channel, api_key)` | fetch video **giữ nguyên nhóm theo kênh** — không có nhóm thì không tính được median của kênh |
| `build_competitor_cohort(...)` | → `(Cohort, by_id)`; `by_id` để lấy thumbnail/duration mà `CohortVideo` không mang |
| `_all_competitor_videos(...)` | danh sách phẳng sort theo views — **chỉ** cho harvest BGM (đào description, không đưa ra kết luận nhân quả). Docstring ghi rõ "NOT for learning" |

Mọi prompt giờ là **prompt tương phản**: winner + control được gắn nhãn trong
input, system prompt cấm báo cáo đặc điểm xuất hiện ở cả hai nhóm ("house style,
not a differentiator"). Khi cohort không có control → playbook vẫn ra nhưng bị
đóng dấu `[UNCONTROLLED — ...]` ở đầu, để reader/writer agent hạ độ tin cậy thay
vì tin ngang nhau.

Persist thêm cột `competitor_intel.cohort_meta` (JSON: winner/control count,
`is_comparable`, ngưỡng chọn, toàn bộ notes) — dùng đúng pattern
`ALTER TABLE ... IF NOT EXISTS` sẵn có của `vault/db.py`, không phá DB cũ.
`GET /api/competitor-intel/{niche}` giờ trả thêm `is_comparable` + `cohort`.

## 2. `fetch_comments` thật (commentThreads API) ✅

`platforms/youtube.py` không còn `return []`. Có phân trang (`nextPageToken`),
làm phẳng reply, chuẩn hoá dict, chạy blocking client qua `asyncio.to_thread`,
OAuth trước — fallback API key.

Điểm quan trọng: **rỗng giờ có lý do**. `_last_comments_error` mang
`comments_disabled` / `quota_exceeded` / `video_not_found` / `dry_run` /
`no post_id`. Trước đây "video không có comment" và "chưa ai implement" là một.

## 3. Full transcript + ASR fallback ✅

Module mới `analytics/transcript.py`:

- **Bỏ cắt 3.500 ký tự.** Trước đó mọi kết luận về STRUCTURE / PACING /
  RETENTION / CTA đều rút ra từ ~4 phút đầu — nửa sau video chưa bao giờ vào
  context, và không có gì báo điều đó.
- `chunks()` map-reduce: mỗi video → digest cấu trúc riêng (`_digest_video`),
  rồi mới tổng hợp chéo winner vs control. Nếu vẫn phải cắt thì **khai báo**
  (`head_chars()` trả `(text, truncated)`; digest ghi chú số phần bị bỏ).
- **ASR fallback**: yt-dlp → faster-whisper (fallback openai-whisper) khi kênh
  tắt caption. Nhóm kênh tắt caption không ngẫu nhiên — thiên về kênh nhỏ và
  không-nói-tiếng-Anh, đúng nhóm mà cohort đang cố ngừng lấy mẫu thiếu.
  Có trần `ASR_MAX_MINUTES=45` và mọi lần bỏ đều ghi note.
- Giữ timing từng cue → phục vụ luôn mục 5 (wpm thật, hook 30 giây thật).

## 4. `gap_score`: bỏ double-count + thêm stack-fit ✅

Bug đã verify: `outlier_ratio` nuôi **cả** `trend_momentum` (`min(ratio*3,30)`)
**và** `gap_score` (20/28/35). Một phép đo cho tới 65/100 điểm — đủ tự vượt
ngưỡng auto-approve 70 mà không cần chiều nào khác đồng ý. Tệ hơn: hai chiều lẽ
ra trả lời hai câu hỏi ngược nhau (có cầu? / đã bị chiếm chưa?).

Ngân sách điểm mới (vẫn tổng 100):

| Chiều | Cũ | Mới |
|---|---|---|
| trend_momentum | 30 | 30 |
| gap_score | 40 | **25** |
| rpm_potential | 20 | 20 |
| novelty | 10 | 10 |
| **stack_fit** | — | **15** |

- `gap_score` **mù hoàn toàn với `outlier_ratio`**, chỉ đọc tín hiệu bão hoà:
  quy mô kênh incumbent (`channel_median_views`), số video đối thủ đã phủ chủ đề
  (`similar_competitor_videos`), engagement lift so với chuẩn của chính kênh đó.
  **Thiếu dữ liệu = trung tính**, không phải "trống" — nhầm hai cái này khiến
  chủ đề chưa ai nghiên cứu trông như một phát hiện.
- `stack_fit` (`StackProfile`): niche / market / dải thời lượng / format đã từng
  ship / yêu cầu sản xuất không đáp ứng được / từ khoá cấm. Cần face-cam hay
  live footage → **0 điểm cứng + lý do**. Chưa cấu hình profile → trung tính 7.5,
  không âm thầm phạt. Lý do trả về trong `ScoredTopic.score_notes`.

⚠️ **Ngưỡng 70/50 cần hiệu chuẩn lại khi có dữ liệu thật** — phân phối điểm dịch
xuống là cố ý (một outlier đơn độc không còn tự duyệt được), nhưng con số 70 thì
vốn được đặt cho thang cũ.

## 5. `video_intel`: bỏ placeholder ✅

Trước: `art_direction="cinematic"`, `words_per_min=150`, `hook_type="question"`,
`hook_strength=8`, `music_energy="medium"` — hằng số, cho mọi video, rồi chảy vào
`ProductionBlueprint` mang `confidence` tới 0.8. Blueprint bịa và blueprint đo
được **không phân biệt nổi** ở phía dưới.

Giờ:

- `words_per_min` đếm từ thật / thời lượng thật; `voice_pacing` suy ra từ đó.
- `analyze_hook` đọc **30 GIÂY đầu thật** (không phải N ký tự đầu — lệch nặng
  giữa người nói nhanh và chậm), phân loại question / shock_stat / story / pain /
  preview / cold_open kèm `evidence` gây ra phân loại. `hook_strength` là suy ra.
- `analyze_structure` tách beat theo pause thật + discourse marker trong timing.
- `analyze_visual_style` đếm trên frame descriptions được đưa vào; **không có
  frame → `"unknown"`**, không bao giờ là `"cinematic"`.
- `build_blueprint`: `confidence = base(sample_size) × coverage đo được`.
  Và **vote đa số** thay cho `analyses[0]` — chỗ này âm thầm biến mẫu đầu tiên
  thành kết luận.

---

## Test

+90 test cho vùng này (gồm 9 test cohort có sẵn):

| File | Test |
|---|---|
| `test_cohort_selection.py` | 9 (có sẵn) |
| `test_transcript_fetch.py` | 10 |
| `test_competitor_intel_cohort.py` | 14 |
| `test_youtube_comments.py` | 12 |
| `test_scorer_gap_and_stack_fit.py` | 20 |
| `test_video_intel_measurement.py` | 19 |

Sửa 3 file test cũ vì đổi thang điểm: `test_scorer.py`,
`test_discovery_models.py`, `test_discovery_orchestrator.py`.

## Việc còn treo cho người tiếp nhận

1. **Chưa commit** — 18 file (10 sửa + 8 mới) đang nằm uncommitted trên
   `ws/visuals-flow`. Lưu ý repo gốc đang ở nhánh này, **không phải `main`** như
   bàn giao trước ghi.
2. **Config Pha 2 DeepSeek** (`.env` `CLAUDE_ONLY=0`, `run_seq_batch.py`) — vẫn
   để nguyên, chưa commit chưa revert, theo yêu cầu.
3. `git status` báo ~111 file modified, nhưng ~93 trong đó là **churn CRLF có
   sẵn từ trước** (`git diff --ignore-cr-at-eol` ra rỗng: alembic.ini,
   docker-compose.yml, pyproject.toml…). Nên xử lý riêng (`.gitattributes` /
   `core.autocrlf`) trước khi commit, kẻo diff thật bị chôn.
4. Thư mục `_to_delete/` ở gốc repo chứa 4 file tar tạm của session này — xoá
   được (Linux VM không có quyền unlink nên tôi chỉ move được).
5. Ngưỡng auto-approve 70/50 (mục 4) chờ hiệu chuẩn lại trên dữ liệu thật.
6. `faster-whisper` chưa có trong `pyproject.toml` — ASR fallback sẽ degrade
   gracefully (ghi note) nếu chưa cài; thêm dependency khi muốn bật thật.
