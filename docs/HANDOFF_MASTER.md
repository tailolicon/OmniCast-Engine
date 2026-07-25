# Bàn giao — OmniCast P0 / P0.1, phiên 2026-07-25

Đọc file này trước. Ba file kia là chi tiết:

| File | Nội dung |
|---|---|
| `docs/HANDOFF_P0_competitor_intel.md` | 5 mục P0 gốc (cohort, comments, transcript, gap score, video_intel) |
| `docs/HANDOFF_P01_containment.md` | P0.1 nhóm 1 + 45 lỗi do audit tìm ra |
| `docs/HANDOFF_P01_ssot.md` | Quyết định SSOT + 6 blocker vòng review cuối |

---

## 1. TRẠNG THÁI — ĐỌC KỸ PHẦN NÀY

**Code nằm trên `ws/visuals-flow`, CHƯA COMMIT.** 46 file.

**Commit bằng cách chạy `commit_p01.bat` trên Windows.** Không commit qua bridge:
`git add` trong VM Linux fail (`unable to unlink .git/objects/tmp_obj_*:
Operation not permitted`), stage 0 file, và để lại `.git/index.lock` chặn git
Windows. Tôi đã dọn rác lần trước sang `_to_delete/git_tmp/`; nếu bạn thấy
`.git/index.lock` xuất hiện lại thì có agent nào đó vừa chạy git qua bridge —
xoá nó đi.

`commit_p01.bat` chỉ stage đúng 46 file này. ~93 file churn CRLF và phần
narrative/visual không liên quan vẫn unstaged — cố ý.

**Thư mục `_to_delete/` ở gốc repo** chứa tar tạm + rác git của phiên này. VM
Linux không có quyền `rm`, nên bạn xoá tay.

---

## 2. BỐN THIẾT LẬP KHÔNG ĐƯỢC ĐỔI NẾU CHƯA ĐỌC LÝ DO

### `omnicast_scoring_mode = "shadow"` (mặc định)

v2 được tính và ghi trên mọi topic nhưng **v1 vẫn quyết định**. Lý do: cùng
`outlier_ratio=8`, v2 cho 59.5 điểm với kênh median 2M và 75.5 với kênh median
20k — approve hay review phụ thuộc một chiều chưa ai hiệu chuẩn.

**Muốn bật v2**: thu shadow corpus (`output/shadow_scoring.jsonl`, tự sinh mỗi
discovery run) → `scoring_calibration.summarize(rows)` → chỉ bật khi
`ready_to_promote` là True. Nó đòi **cả** `migration_is_stable` **và** có nhãn
chất lượng (`labelled`/`outcome` trên row). Corpus toàn điểm số sẽ luôn trả
False — cố ý.

### `omnicast_topic_router = "scorer_gate"` (mặc định)

TopicScorer nhận, ChannelArchitect xếp hạng. Đây là quyết định kiến trúc của
phiên này, lý do đầy đủ trong `HANDOFF_P01_ssot.md`. Escape hatch:
`architect_only` trả về hành vi cũ.

### Row `competitor_intel` cũ trong vault.db bị từ chối

Status `legacy`. Theo cấu trúc chúng là "artifact có thể cũ + metadata run mới
nhất" — không chứng minh được. **Chạy lại `POST /api/competitor-intel/{channel_id}`
là dùng được.** Đây là hành vi cố ý, không phải bug.

### Config Pha 2 DeepSeek

`.env` `CLAUDE_ONLY=0` + `run_seq_batch.py` — **chưa ai đụng vào**, đúng như bạn
yêu cầu từ đầu phiên. Vẫn uncommitted.

---

## 3. CHẠY TEST

Repo yêu cầu Python **>=3.12** (`narrative_pipeline.py` dùng f-string có
backslash — 3.11 không parse được).

```bash
cd implementation
uv pip install -e ".[dev]"
pytest tests -q --ignore=tests/integration
```

Kỳ vọng: **1782 pass**. 262 test trong số đó là của đợt này.

3 fail đã biết (đo trong sandbox, **chưa verify trên máy bạn** — GPT đo trên máy
bạn ra 4 fail với nguyên nhân khác một phần):

* 2× `test_claude_cli_effort` — thiếu/khác `.env`
* 1× `test_image_gemini` — test còn chờ Gemini model ID cũ

Bật ASR fallback thật cần: `uv pip install -e ".[competitor-research]"`
(`youtube-transcript-api`, `yt-dlp`, `faster-whisper` — đã khai báo trong
pyproject nhưng là optional extra).

---

## 4. FILE MỚI (5 module, 13 test file)

```
src/omnicast/analytics/transcript.py          full transcript + ASR fallback
src/omnicast/analytics/intel_gate.py          gate máy: ok/missing/uncontrolled/stale/error/legacy
src/omnicast/discovery/scoring_calibration.py go/no-go cho việc bật v2
src/omnicast/discovery/shadow_log.py          corpus JSONL từ mỗi discovery run
src/omnicast/discovery/topic_router.py        SSOT: ai nhận, ai xếp hạng
```

Test: `test_transcript_fetch`, `test_competitor_intel_cohort`,
`test_competitor_intel_containment`, `test_youtube_comments`,
`test_scorer_gap_and_stack_fit`, `test_video_intel_measurement`,
`test_scoring_shadow_mode`, `test_intel_gate`, `test_writer_intel_gate_wiring`,
`test_topic_router_ssot`, `test_p01_audit_regressions`, `test_p01_audit_round2`,
`test_p01_round4_wiring`.

---

## 5. VIỆC CÒN LẠI — THEO THỨ TỰ

### P0.1 nhóm 2 — khoa học cohort

1. Winner selection theo `views_per_day`, **và median cũng phải tính trên
   `views_per_day`** — làm nửa vời sẽ so lệch đơn vị và tệ hơn hiện tại.
2. `is_comparable` theo **từng cặp**, không phải toàn cohort. Hiện 12 winner + 1
   control vẫn `is_comparable=True`.
3. Cap winner mỗi channel — một kênh có thể chiếm hết top-12.
4. Prompt phải giữ mapping winner–control và channel (hiện chỉ liệt kê hai nhóm).
5. Proxy format rẻ: `_classify_title()` trong `youtube_scanner.py` đã là hàm
   thuần, deterministic, không LLM — thêm vào matching ~5 dòng. **Không** làm
   pillar classifier ở P0.

### P0.1 nhóm 3 — làm capability chạy thật

`StackProfile` hiện luôn neutral 7.5 vì `orchestrator.py:113` tạo
`TopicScorer()` không truyền profile, và scanner **không sinh**
`similar_competitor_videos` / `production_requirements`. Cần:
sinh `StackProfile` từ channel config → scanner populate supply signals → một
test xuyên `ChannelProfile → DiscoveryOrchestrator → ScoredTopic` chứng minh
điểm đổi thật.

### P0.1 nhóm 4 — `video_intel`

**Không có production caller nào.** Hoặc wire một vertical slice thật vào
competitor pipeline, hoặc đánh dấu `experimental/dead`. Đừng đánh bóng thêm
module chưa ai gọi. Nó cũng vẫn suy diễn `video_format="documentary"`,
`crossfade=0.5`, target duration — nên trạng thái đúng là PARTIAL.

### Nợ kỹ thuật đã biết

* **Intel keyed theo broad niche** — nhiều kênh finance ghi đè playbook của
  nhau. Cần `scope_key = channel/archetype + audience + format + market + pillar`
  + migration.
* `topics` table chỉ có một cột `score`; muốn nối outcome cho nhãn chất lượng
  thì cần khoá `topic_id` trên `published_videos`.

### Brief §15 — hai nhóm P0 chưa động tới

* **Competitor intelligence còn**: content pillar, phân tích comment (đã fetch
  được nhưng chưa nối vào intel), schedule (§4.6), dossier thống nhất (§4.5).
* **Niche opportunity model**: brief đòi `demand + supply weakness + audience fit
  + stack-fit + monetization + repeatability − risk`. Hiện có demand/supply/
  stack-fit/monetization. **Thiếu**: audience fit, repeatability, penalty rủi ro
  production/legal/YMYL.
* **Production mode router**: phân loại scene → chọn giữa 8 mode. Chưa bắt đầu.

---

## 6. CÁCH LÀM VIỆC — PHẦN NÀY QUAN TRỌNG NHẤT

**Codex plugin không gọi được** (không có trong catalog tài khoản, không có CLI
trong VM bridge). Thay bằng subagent đối kháng ngữ cảnh độc lập, mỗi agent bị
buộc **chạy code để phản bác** thay vì đọc suông.

Bốn vòng audit tìm ra **~45 lỗi. 11 trong số đó do chính bản sửa của vòng trước
tạo ra.** Vài ví dụ:

| Lỗi | Do đâu |
|---|---|
| `trend_momentum` âm → một post Reddit downvote giết cả discovery run | code gốc |
| Cache intel trả kết quả rỗng → learn xong vẫn "chưa có gì" 60s | **bản sửa vòng 2** |
| `correlation_ratio` đổi kết quả khi xáo thứ tự dòng | **bản sửa vòng 2** |
| Chia bin theo độ rộng → một outlier làm quan hệ thật báo "đã tách" | **bản sửa vòng 3** |
| Facade OAuth async gọi thẳng hàm sync — chặn y hệt, chỉ trông như cố ý | **bản sửa vòng 3** |

**Bài học đắt nhất**: một audit revert **cả hai nửa** gate của writer mà toàn bộ
suite vẫn xanh. Một quy tắc mà không test nào làm nó fail thì không phải quy
tắc. Sau đó `resolve_competitor_playbook` được tách ra module-level và có 9 test
ghim.

**Cạm bẫy tôi mắc ba lần**: phát biểu về môi trường của bạn dựa trên sandbox
("3 fail chỉ do thiếu `.env`"). Sandbox ≠ máy bạn. Luôn ghi rõ "đo ở đâu".

---

## 7. NẾU MUỐN AGENT TỰ COMMIT ĐƯỢC

Chạy Cowork **trên máy bạn** thay vì trên cloud — nút "Run this task" ở góc trên
bên phải khi mở task mới trong app desktop. Khi đó git chạy thẳng trên đĩa
Windows, không qua VM Linux, và lỗi permission `.git/objects` biến mất.

Phiên này chạy trên cloud nên toàn bộ file phải đi qua tar → SendUserFile →
device_commit_files, và git thì không đi được đường đó.
