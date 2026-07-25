> STATUS: SUPERSEDED (2026-07-26) bởi `IMPLEMENTATION_STATUS.md` §4b — toàn bộ việc trong §5 của file này đã làm xong. Giữ lại làm lịch sử; KHÔNG dùng làm nguồn sự thật.

# Quyết định SSOT + vòng sửa 4 — 2026-07-25

## Quyết định: TopicScorer NHẬN, ChannelArchitect XẾP HẠNG

Bạn uỷ quyền cho tôi quyết, nên đây là quyết định và lý do.

**Vấn đề không phải là hai chính sách, mà là một chính sách bị bỏ qua ở một
đường.** `DiscoveryOrchestrator → BriefGenerator` chỉ tạo brief cho topic
`approve` — lane của scorer có hiệu lực. Nhưng đường API chính đưa **toàn bộ
`all_raw`** cho `ChannelArchitectAgent` và vứt điểm scorer đi. Nghĩa là mọi công
sức hiệu chuẩn của P0.1 đang đo một quyết định không ai dùng trên đường bận hơn.

Phân vai theo **cái mỗi bên thực sự biết được**:

| | Biết | Không biết |
|---|---|---|
| `TopicScorer` | bão hoà, RPM, trùng lặp, ta có sản xuất nổi không | topic có hợp audience của kênh này không |
| `ChannelArchitect` | audience fit, pain point, góc kể | không thể tính lại bão hoà/RPM từ raw metrics rẻ hơn hay đáng tin hơn số học đã có |

Nên: **lane `discard` có hiệu lực trên cả hai đường**, Architect xếp hạng phần
sống sót. Dùng LLM để suy lại những gì số học đã tính vừa đắt vừa kém tin cậy.

Hai chốt an toàn:

1. Lane lấy từ **thế hệ đang quyết định** (v1 khi shadow bật) — không bao giờ
   từ thế hệ chưa hiệu chuẩn.
2. Nếu gate làm rỗng danh sách, run **fallback về danh sách chưa gate và log to
   tiếng**. Lịch nội dung rỗng là hỏng nặng hơn là gate quá dễ.

Escape hatch: `omnicast_topic_router=architect_only` trả về hành vi cũ.

**Đây không phải đổi chính sách** — `BriefGenerator` vốn đã coi `discard` là
loại bỏ. Đây là làm hai đường nhất quán.

## Sáu blocker của vòng review — đã sửa hết

| Blocker | Cách sửa |
|---|---|
| Cờ `competitor_intel_required` không per-channel | Lên `ChannelProfile` → 4 builder (`brief_generator`, `steps`, `channel_architect`, `server`). Test grep từng module builder |
| Không có shadow corpus | `discovery/shadow_log.py`, JSONL append-only, ghi từ `orchestrator.run()` mỗi run |
| `ready_to_promote` thiếu nhãn chất lượng | Tách `migration_is_stable` (ổn định) và `ready_to_promote` (thêm điều kiện có `labelled`/`outcome`) |
| Production bypass TopicScorer | `discovery/topic_router.py` — xem quyết định ở trên |
| OAuth còn chặn ngoài đường comment | Facade → `await asyncio.to_thread(get_credentials_sync, ...)` |
| Gate nhận `research_run_id` rỗng | Bắt buộc non-empty, thiếu → `legacy` |

Cộng: lost update (`replace_competitor_intel` với `BEGIN IMMEDIATE`), SQLite của
writer prewarm off-loop, test flaky viết lại bằng `threading.Event`.

## ⚠️ KHÔNG COMMIT ĐƯỢC TỪ BRIDGE

`git add` chạy trong VM Linux của bridge **fail**: không unlink được file tạm
trong `.git/objects` (`Operation not permitted`), stage 0 file, và để lại
`.git/index.lock` — thứ sẽ chặn git trên Windows của bạn.

Tôi đã dọn: 2 `index.lock` + 6 `tmp_obj_*` chuyển sang `_to_delete/git_tmp/`.

**Chạy `commit_p01.bat` trên Windows.** Nó chỉ stage đúng 46 file của đợt này;
~93 file churn CRLF và phần narrative/visual không liên quan vẫn nằm nguyên
unstaged — đúng như review đề nghị.

Nếu muốn tôi tự commit được ở các phiên sau, cần chạy Cowork **trên máy bạn**
thay vì trên cloud (nút "Run this task" góc trên bên phải khi mở task mới trong
app desktop) — khi đó git chạy trực tiếp trên đĩa Windows, không qua VM.

## Còn treo

- Intel vẫn keyed theo **broad niche**: nhiều kênh finance ghi đè playbook của
  nhau. Cần `scope_key = channel/archetype + audience + format + market + pillar`
  + migration.
- **P0.1 nhóm 2** (khoa học cohort: `views_per_day` cho winner selection + median
  đổi theo, comparability từng cặp, cap winner/channel, proxy format qua
  `_classify_title`).
- **P0.1 nhóm 3** (`StackProfile` sinh từ channel config, scanner populate
  `similar_competitor_videos` + `production_requirements`).
- **P0.1 nhóm 4**: `video_intel` vẫn không có production caller — wire hoặc đánh
  dấu dead.
- Brief §15 còn: content pillar, phân tích comment, schedule, dossier thống nhất,
  niche model (thiếu audience fit / repeatability / risk penalty), production
  mode router.

Suite: 1782 pass, 3 fail — **đo trong sandbox của tôi, chưa verify trên máy bạn**.
