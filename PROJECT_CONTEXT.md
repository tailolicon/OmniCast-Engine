# OmniCast Engine — Project Context v4.0 (Enterprise-grade)

> **Dành cho AI agents:** Đọc file này trước khi làm bất kỳ task nào.
> Đây là context tổng hợp. Khi có xung đột, thứ tự ưu tiên là:
> **code + test hiện tại** → `docs/SCRIPT_ENGINE_REVIEW_PACK.md` →
> `IMPLEMENTATION_STATUS.md` → các section lịch sử bên dưới.
> v3.1: OAuth2 lifecycle, GPU scheduling, DRP, YMYL compliance, Content Lifecycle.
> v3.2: Operator Experience Layer (Sections 32-44).
> v3.3: Channel Quality Diagnostics & Auto-Correction (Section 49).
> v3.4: Niche Vault + Health Monitor (Section 50), Scanner filter fixes (Section 51).
> v3.5: Gemini quality fixes — scoring rework, Shorts filter, tiered breakout, Reddit/category seed enrichment (Section 52).
> v3.6: Scene-based script format, Two-stage Critic (VO/Prod split), VisualDirectorAgent, Storage chain fix (Section 53).
> v3.7: T5 Category Sweeper, Niche Dedup Agent, Critic AND logic, ChannelGuard (Velocity & Strike), Brand Identity JSON override.
> v4.0: Runtime-truth refresh; unit-first narrative engine, bounded self-improvement,
> fail-closed release integrity, cross-video memory và candidate hospital (Section 0).

---

## 0. CURRENT RUNTIME TRUTH — đọc phần này trước (2026-07-22)

Phần lớn section 1-53 là **lịch sử thiết kế** được tích luỹ từ tháng 5. Chúng vẫn hữu ích
để hiểu mục tiêu, nhưng không được dùng để suy ra đường chạy hiện tại nếu chưa đối chiếu code.
Runtime đang hoạt động nằm chủ yếu trong `implementation/`; tài liệu chi tiết nhất về script
engine là `docs/SCRIPT_ENGINE_REVIEW_PACK.md`.

### 0.1 Entry point và lựa chọn script flow

Nguồn quyết định là `implementation/src/omnicast/pipeline/steps.py::_step_script`:

- Kênh narrative có `channel.script_profile` hợp lệ mặc định chạy **`unit_first`**.
- Kênh khác mặc định chạy **`claude_first`**.
- **`debate`** là đường legacy/experimental, chỉ dùng khi override
  `OMNICAST_SCRIPT_FLOW=debate`; Evolution mặc định tắt và chỉ bật bằng
  `OMNICAST_DEBATE_EVOLUTION=1`.
- Kênh `true_dread_files_us` đang khai `script_profile=true_horror_strict_v1`, vì vậy
  đường production của nó là `NarrativeUnitPipeline`, không phải Writer/Critic debate cũ.

Các file phải đọc cùng nhau khi sửa script engine:

| File | Vai trò runtime |
|---|---|
| `implementation/src/omnicast/pipeline/steps.py` | Chọn flow, resolve model role, lưu artifact, chặn promote script fail |
| `implementation/src/omnicast/agents/narrative_pipeline.py` | Plan/write/audit/repair/release state machine |
| `implementation/src/omnicast/config/narrative_quality.py` | Profile bất biến và quality floors theo kênh |
| `implementation/src/omnicast/agents/cross_video.py` | Rolling fingerprint chống lặp giữa video |
| `implementation/scripts/run_seq_batch.py` | Batch policy, role mặc định và quota-aware retry |
| `implementation/scripts/finish_candidate.py` | Hospital pass cho candidate đã lưu; không auto-release |

### 0.2 “Tự nâng cấp khi sinh script” thực sự là gì

Tên đúng về mặt kỹ thuật là **bounded generate → verify → repair**. Hệ thống tự cải thiện
ứng viên trong một run và dùng memory nhẹ để steering run sau; nó **không tự sửa source
code, không tự train model và không tự phát minh rồi persist rule/prompt mới**.

Luồng `unit_first` hiện tại:

1. Đọc 20 fingerprint gần nhất của kênh, feed-forward tên, motif và archetype
   `threat_identity/escape_mechanism` cần tránh. Lỗi đọc history fail-open nhưng phải log.
2. Planner sinh `CompilationPlan` typed. Mỗi story khóa 5 mechanism axes, ledger liên tục,
   `topic_promise`, safety obligation, voice seed và `distinguishing_turn`.
3. Schema có đúng một contract retry. Sau đó chạy deterministic preflight, mechanism
   diversity, premise freshness và semantic plan audit **trước khi mua prose**.
4. Plan bị block chỉ được targeted repair story lỗi; story sạch phải byte-identical và toàn
   bộ gate/audit chạy lại. Profile strict hiện cho `maximum_plan_attempts=2`,
   `maximum_plan_repairs=1` mỗi outer attempt.
5. Ba story writer chạy song song, mỗi writer chỉ thấy locked plan của story mình.
6. Deterministic gate chạy trước semantic judge. Lỗi cục bộ có bounded recovery; story
   không audit được vì gộp beat có đúng một rewrite rescue rồi re-audit.
7. Per-story compliance kiểm entailment của từng locked beat bằng exact, ordered,
   non-overlapping quotes. Critic chấm 7 chiều trên 100 và merge compliance findings.
8. Repair engine tạo **hai patch candidate** hoặc full rewrite, chạy trial gate, blind
   selector, compliance và critic lại. Chỉ nhận patch theo priority-monotonic rule:
   không tăng gate/critical/major, phải giảm blocker được giao, giữ floor với noise band 1đ.
9. Tối đa ba repair wave có điều kiện: wave đầu sửa gate/major; wave hai chỉ cho candidate
   đã mạnh; wave ba chỉ là finishing wave cho bản sát release, ít blocker và mọi blocker
   có quote. Bản sạch major nhưng thiếu tối đa 3 điểm có một near-miss minor wave.
10. Wave nhiều story bị reject toàn cục được salvage tối đa hai story, xếp patch từng cái
    trên trạng thái vừa được chấp nhận; một patch hỏng không được kéo patch tốt xuống theo.
11. Nếu **originality là điều kiện duy nhất** chặn lock, challenger-tier model được chấm
    lại đúng một lần; kết quả thay thế điểm cũ theo cả hai chiều, không hạ floor.
12. Candidate đạt floor mới qua final editor. Final editor có thể cấp một bounded repair
    còn budget. Adversarial release challenger là gate cuối; veto không được sửa trong cùng
    attempt, outer retry phải dùng concept mới.
13. `run_with_retry` mặc định tối đa 2 outer attempt, cấm dùng lại spent concept, giữ best
    `needs_edit` candidate, và cộng đủ call/cost/latency của mọi attempt. Run không sinh được
    candidate ghi `narrative_failure_audit.json`, không bịa score hay script để lấp chỗ trống.
14. Chỉ khi content lock + final editor + challenger + annotation coverage đều đạt thì
    `production_ready=True`. Candidate fail được lưu để audit nhưng không có canonical
    `script.txt` renderable.

### 0.3 Quality contract hiện tại của True Dread Files

Profile `true_horror_strict_v1` là immutable named strategy:

- Tổng điểm tối thiểu **84/100**; continuity tối thiểu **23/25**.
- Mỗi dimension phải đạt ít nhất **65%** thang điểm của chính dimension.
- Ít nhất 2/3 story là human threat; ít nhất một story evidence-free.
- Gate bắt buộc: distinct typed mechanisms, topic alignment, plan-fact fidelity,
  safety response, forbidden ending, stylometric texture và premise freshness.
- `distinguishing_turn` phải là clause 4-25 từ, khác giữa các story và không được chỉ
  paraphrase threat. Đây là hợp đồng plan-time cho originality, không phải lời quảng cáo.
- Stylometric gate bắt exact shared phrase từ 5 token giữa hai narrator khi còn ít nhất
  3 content word sau khi trừ stopword/domain vocabulary; quote toàn bộ occurrence để repair.
- Plan và critic issues ở mức major/critical phải có bằng chứng ground được. Provider,
  schema hoặc grounding contract hỏng thì fail-closed.

### 0.4 Model routing và failure domain

- `run_seq_batch.py` ghim standard role: planner + writer = `claude-sonnet-5/high`, nhưng
  explicit operator environment vẫn được ưu tiên.
- Judge mode có thể DeepSeek-first hoặc Claude-only; Gemini CLI là failure-domain fallback
  opt-in. Health được theo **provider account**, không theo model name: hai model cùng account
  không phải HA fallback.
- Release challenger mặc định là Claude Opus. Code đo independence theo resolved identity
  thực sự đã chạy; provider-family independence mạnh hơn có thể opt-in bằng
  `OMNICAST_NARRATIVE_CHALLENGER_PROVIDER=deepseek` sau khi account có balance.
- Quota retry chỉ áp cho run thực sự chết vì session limit/0-score poisoned verdict; một
  verdict nội dung đã hoàn tất không được chạy lại chỉ vì log có marker limit cũ.

### 0.5 Memory và giới hạn của “learning”

Đã implement:

- Cross-video rolling fingerprint: tên, motif, typed archetype; history tối đa 20 script.
- Typed audit artifacts, rejected-plan evidence, attempt accounting và failure audit.
- Human/autopsy-driven hardening: mỗi lớp lỗi live được chuyển thành rule + regression test.
- `hospital_pass` có thể nhặt candidate đã lưu, re-judge và chạy cùng repair machinery; output
  là `hospital_script.txt` + `hospital_report.json` để **human review**, không auto-release.

Chưa được phép claim:

- Không có runtime tự động biến analytics/critic result thành code hoặc prompt mới.
- Bảng `lessons`, `TopicBrief.lessons` và KB client là hạ tầng có sẵn, nhưng `unit_first`
  chưa tự extract/distill lesson từ mỗi run rồi inject lại một cách production-verified.
- Section 12B bên dưới là target architecture dài hạn; các ví dụ `lessons.json`, weekly
  distillation và auto-rule generation không mô tả đường script production hiện tại.
- Cross-video freshness mới nhớ 2/5 typed mechanism axes; chưa phải semantic memory đầy đủ.
- Chưa được claim artifact `production_ready` mới đã vượt toàn bộ policy hiện hành nếu chưa
  có live artifact + independent manual audit tương ứng.

### 0.6 Artifact và test evidence

- Candidate audit: `output/products/<channel>/<run>/narrative_audit.json`.
- Zero-candidate failure: `narrative_failure_audit.json`.
- Rejected prose: `needs_edit.txt`; không promote sang `script.txt`.
- Hospital output: `hospital_script.txt`, `hospital_report.json`; human-only.
- Kiểm tra tại lần refresh context này: focused script suite **240 passed**; full
  `tests/unit` trên chính working tree **1430 passed, 6 skipped** (10 deprecation warning
  FastAPI `on_event`, không có test failure).
- Con số suite trong tài liệu cũ là bằng chứng lịch sử; dùng con số ở đây cho snapshot
  2026-07-22 và chạy lại nếu working tree tiếp tục thay đổi.

---

## 1. Tổng quan dự án

**OmniCast Engine** — hệ thống tự động sản xuất và phân phối video YouTube 24/7.
Từ nghiên cứu chủ đề → kịch bản → media → render → upload → phân tích → tối ưu.

### Mục tiêu kinh doanh
- Vận hành nhiều kênh YouTube song song (Hub & Spoke model)
- Thị trường RPM cao: **US ($15+), UK ($12+), AU ($10+), CA ($10+), JP ($8+), KR ($7+)**
- Đa ngách: Finance, Health, Mythology, Psychology, Tech, JP/KR culture
- Doanh thu: YouTube Adsense + Affiliate + Sponsorship (Hub channels)

### Nguyên tắc cốt lõi
- **Tuân thủ ToS:** Upload 100% qua YouTube Data API v3 — KHÔNG browser automation
- **Không spam rác:** Critic Agent kiểm duyệt, bao gồm Inauthentic Content check
- **Nhạc 100% AI-generated:** Không perturb nhạc có bản quyền — dùng ACE-Step v1.5
- **Tự học:** Analytics feedback loop tối ưu thuật toán theo tuần
- **Survive first, scale second:** Error recovery + compliance trước khi scale

---

## 2. Kiến trúc phần cứng

### Topology mạng nội bộ (LAN)

```
[Master Mac Mini] ←──LAN──→ [NAS Synology]
        ↕                           ↕
[Worker Mac Mini #1]         [Worker Mac Mini #2]
        ↕
[Worker Mac Mini #N]
```

### Phân quyền phần cứng

| Máy | Cấu hình | Nhiệm vụ |
|-----|----------|----------|
| **Master** | M4 / 16GB RAM | Orchestration, AI Agents, RabbitMQ, DB, Dashboard |
| **Worker** | M2 Pro / 32GB+ RAM | ComfyUI, TTS, FFmpeg render, Wan video gen |
| **NAS** | Synology DS923+ | Assets, videos, knowledge base, DB backups |

> **Standby Worker:** 1 Worker được chỉ định làm "Standby Master" — sync PostgreSQL streaming replication + RabbitMQ federation. Nếu Master offline >5 phút → Standby promote tự động → Telegram alert.

### Storage layout NAS

```
NAS/
├── assets/
│   ├── music/youtube_audio_lib/ # YouTube Audio Library cache (Priority 1)
│   ├── music/royalty_free/      # CC0/Attribution tracks (Priority 2)
│   ├── music/ai_generated/      # ACE-Step output (Priority 3)
│   │   └── metadata.json        # {mood, bpm, duration, use_count, license}
│   ├── sfx/
│   ├── broll/                   # Pexels/Pixabay cache
│   │   └── index.json
│   ├── intros/{channel_id}/
│   ├── outros/
│   ├── overlays/
│   ├── fonts/
│   └── brand_configs/{channel_id}.json
├── videos/
│   ├── raw/                     # Worker output chưa upload
│   ├── published/
│   └── archive/                 # Nén sau 90 ngày
├── knowledge_base/
│   ├── scripts/
│   └── competitor_analysis/
└── backups/
    ├── postgres/                # daily pg_dump
    └── chromadb/                # daily collection export
```

---

## 3. ⚠️ Ba vấn đề CRITICAL (phải sửa trước khi code)

### CRITICAL #1: Upload Pipeline — dùng YouTube Data API v3

**Playwright/AdsPower upload VI PHẠM ToS YouTube.** YouTube phát hiện qua TLS/TCP fingerprinting, CDP side effects, WebGL inconsistencies. Năm 2025: 12M kênh bị terminate phần lớn do automation.

```
SAI (vi phạm):  AdsPower → Playwright → youtube.com/upload → form fill → submit
ĐÚNG:           YouTube Data API v3 → videos.insert → thumbnails.set → videos.update
```

**Quota YouTube Data API v3 (10,000 units/ngày/project):**

| Thao tác | Cost | Capacity |
|----------|------|----------|
| `videos.insert` (upload) | 100 units | ~100 video/ngày |
| `thumbnails.set` | 50 units | ~200 lần/ngày |
| `videos.update` (metadata) | 50 units | ~200 lần/ngày |
| `videos.list` (analytics) | 1 unit | ~10,000 lần/ngày |

**Rule:** Mỗi kênh = Google Cloud Project riêng = API key riêng = quota riêng.

**AdsPower + Playwright CHỈ dùng cho:**
- Account warm-up (lướt feed, xem video — KHÔNG upload)
- YouTube Studio settings không có API (channel art, community posts)
- CAPTCHA handling khi cần

### CRITICAL #2: Nhạc — Hybrid Strategy (AI-generated + Royalty-Free)

**Audio perturb (pitch shift ±2 semitones) KHÔNG bypass ContentID.** ContentID dùng pattern-based fingerprinting, phát hiện mọi biến thể pitch/tempo/reverb. Cố tình bypass = willful infringement.

```
BỎ HOÀN TOÀN: "Audio perturb để bypass ContentID"

CHIẾN LƯỢC MỚI — Hybrid Music (ưu tiên an toàn + đa dạng):

  Nguồn 1: YouTube Audio Library (MIỄN PHÍ, 100% an toàn)
    → YouTube chính thức cung cấp, KHÔNG BAO GIỜ bị ContentID claim
    → Hàng ngàn bản nhạc, cập nhật thường xuyên
    → Nhược: nhiều creator khác cũng dùng → ít độc đáo

  Nguồn 2: ACE-Step v1.5 AI-generated (Apache 2.0)
    → Nhạc original, KHÔNG có trong ContentID database
    → LoRA fine-tuning cho từng niche (cinematic, lo-fi, epic)
    → Dùng khi cần nhạc unique khớp mood cụ thể

  Nguồn 3: Royalty-Free Libraries (Creative Commons / CC0)
    → Pixabay Music, Free Music Archive, Incompetech
    → Check license TRƯỚC khi dùng: CC0 hoặc Attribution-only
    → Asset Manager auto-verify license metadata

  Asset Manager logic:
    1. Tìm YouTube Audio Library TRƯỚC (safest)
    2. Nếu không match mood → tìm Royalty-Free Library
    3. Nếu vẫn thiếu → ACE-Step generate mới
    → KHÔNG BAO GIỜ perturb bất kỳ nguồn nào
```

### CRITICAL #3: Inauthentic Content Policy (từ 7/2025)

YouTube coi nội dung là "Inauthentic" nếu: AI voiceover + stock footage + ít editorial value, template-driven, mass-produced thiếu human perspective.

**Critic Agent phải check thêm:**
```python
INAUTHENTIC_CHECKS = {
    "human_editorial_value": 15,   # Có insight/unique angle không AI thuần tạo được?
    "template_divergence":   10,   # Script structure khác ≥30% so với 5 script gần nhất?
    "cross_channel_uniqueness": 10, # Nội dung KHÔNG trùng cross-channel?
    "ai_disclosure": "mandatory",  # Thêm AI disclosure vào description (bắt buộc 2026)
}
# Tổng điểm Critic: 100 điểm (35 điểm mới từ inauthentic checks)
# Threshold: ≥ 8/10 → APPROVED (tính cả 3 check mới)
```

---

## 4. Tech Stack

| Layer | Công cụ | Chạy trên | Ghi chú |
|-------|---------|-----------|---------|
| **Orchestration** | CrewAI + LangGraph | Master | |
| **LLM production** | Claude Sonnet API (claude-sonnet-4-6) | Cloud | |
| **LLM fallback** | Llama 3.1 70B via Ollama | Worker | Circuit breaker trigger |
| **TTS primary** | **Kokoro-82M** (Apache 2.0) | Worker | Top HF TTS Arena, CPU-friendly |
| **TTS voice cloning** | XTTSv2 | Worker | Khi cần clone giọng cụ thể |
| **TTS fast fallback** | Piper TTS | Worker | Lightweight, MIT license |
| **Image Gen (batch)** | ComfyUI + SDXL + ControlNet + IP-Adapter FaceID Plus V2 | Worker | |
| **Image Gen (hero)** | ComfyUI + **FLUX.1** | Worker | Photorealism, text rendering tốt hơn |
| **Face Consistency** | **FaceDetailer** (SDXL) hoặc **PuLID** (FLUX) | Worker | |
| **Music (safe)** | **YouTube Audio Library** | — | Miễn phí, 100% an toàn, ưu tiên dùng trước |
| **Music (AI gen)** | **ACE-Step v1.5** (Apache 2.0) | Worker | LoRA fine-tuning, khi cần unique mood |
| **Music (RF libs)** | Pixabay Music, FMA, Incompetech | — | CC0/Attribution, license auto-verify |
| **Music fallback** | MusicGen (AudioCraft) | Worker | |
| **Video Gen** | **Wan 2.1+** (Apache 2.0) | Worker | Scene phức tạp, 5-10s clips |
| **Subtitles** | **WhisperX** | Worker | Word-level alignment, không lệch sync |
| **Video Assembly** | FFmpeg-python | Worker | |
| **Upload automation** | YouTube Data API v3 (BẮT BUỘC) | Master | CHỈ warm-up + Studio settings |
| **Task Queue** | Temporal.io (Phase 5+) / RabbitMQ | Master | |
| **Distributed Caching** | **Redis** | Master | Rate limiting (Token Bucket) + Locks |
| **Data Pipeline** | **CocoIndex** | Master | Incremental ETL cho Knowledge Base |
| **Vector DB** | ChromaDB (Phase 1-4), Qdrant (Phase 5+ >500K vectors) | Master | |
| **SQL DB** | PostgreSQL + Alembic | Master | |
| **Observability** | Langfuse (LLM traces), Prometheus + Grafana (infra) | Master | |
| **Dashboard** | Streamlit (Phase 1) → FastAPI + **Next.js PWA** (Phase 2) | Master | Desktop + Mobile, real-time WebSocket |
| **Secrets** | dotenv + SOPS/age | Master/Workers | |
| **Containerization** | OrbStack (nhanh hơn Docker) | Master | |
| **Process guard** | launchd .plist (KeepAlive=true) | All machines | Auto-restart on crash/reboot |
| **Alert** | Telegram Bot | Master | |
| **Dashboard auth** | Cloudflare Access (email SSO) | Master | KHÔNG public |

---

## 5. Kiến trúc Agent System

> **Lưu ý runtime:** sơ đồ và Tournament-based Debate trong section này là kiến trúc
> legacy/generic. Với channel narrative có named `script_profile`, dùng Section 0 và
> `NarrativeUnitPipeline`; không suy ra runtime True Dread Files từ sơ đồ dưới đây.

### Sơ đồ luồng tổng thể

```
[Topic Discovery Engine (5 sources)]
         ↓
[Input Sanitizer Agent] ← Chặn Prompt Injection từ data rác (Security)
         ↓
[Research Agent] ──→ [Knowledge Base (CocoIndex ETL Incremental Update)]
         ↓                        ↑ similarity check + decay check
[Writer Agent] ←──→ [Critic Agent]  (debate, max 3 rounds, 100 điểm)
         ↓ (APPROVED — bao gồm Inauthentic checks)
[Compliance Checker] ← gate bắt buộc
         ↓ (PASS)
[Budget Manager] ← check daily spend + ROI estimate
         ↓
[Asset Manager] ──→ fetch/generate music, broll, sfx
         ↓
[Media Pipeline]
  ├── Kokoro-82M TTS Module
  ├── SDXL/FLUX Image Gen Module (IP-Adapter FaceID + FaceDetailer)
  ├── Wan 2.1 Video Gen (scene phức tạp)
  ├── ACE-Step v1.5 Music Gen
  ├── Thumbnail Gen (3 A/B/C variants)
  └── WhisperX Subtitle Module
         ↓
[FFmpeg Render + Brand Config Enforcer]
         ↓
[Content Fingerprint Check] ← multi-modal (text + visual + audio)
         ↓
[Quality Check Agent]
  ├── Pass → NAS/raw/
  └── Fail → DLQ + Telegram alert
         ↓
[Upload Scheduler] ← rate limiting intelligence
         ↓
[YouTube Data API v3 Upload]
  └── thumbnails.set (variant A)
         ↓
[A/B Test Agent] ← swap thumbnail via API nếu CTR < 4% sau 24h
         ↓
[Analytics Crawler] ← YouTube Analytics API + Retention heatmap
         ↓
[Channel Diagnostic Engine + ROI Calculator]
         ↓
[Strategist Agent] ← weekly decisions + canary deployment logic
         ↓
[Update KB (decay-aware) + Asset use_count + Budget log + Audit Trail]
```

### Danh sách Agent

| Agent | Model | Nhiệm vụ |
|-------|-------|----------|
| **Content Creation Engine** | | |
| Research Agent | Sonnet | Tổng hợp Topic Discovery data → Brief + source attribution |
| Writer Agent | Sonnet | Tạo N=3 variants per brief (pain_hook/data/contrarian angles), scene JSON output |
| Thinking Agent | DeepSeek Flash | Self-critique nội bộ trước Critic (private notes) |
| Critic Agent | Sonnet | Two-stage: VO group 70pt + Production group 30pt, Pydantic output |
| Visual Director Agent | DeepSeek Flash | Chỉ fix visual_prompt + sfx khi VO locked (không đụng VO text) |
| Evolution Agent | Sonnet | Combine best elements từ variants (Hub only), scene JSON output |
| Compliance Checker | DeepSeek Flash | Gate: AI disclosure, no copyright, FTC, COPPA, YMYL |
| **Learning Loop** | | |
| Diagnostic Agent | Sonnet | Weekly: correlate script patterns ↔ YouTube metrics |
| Learning Extractor | Haiku | Per-video: extract engagement patterns → KB |
| **Production** | | |
| Budget Manager | — | API spend cap, ROI tracking |
| Asset Manager | — | Registry assets NAS, hybrid music (YT Lib → RF → AI) |
| Media Engineer | Haiku | Điều phối TTS + Image + Video + Music |
| Quality Check Agent | Haiku | Verify output trước upload |
| Upload Scheduler | — | Rate limiting, spread uploads, mimic human pattern |
| A/B Test Agent | — | Monitor CTR → swap thumbnail via API |
| **Analytics & Strategy** | | |
| Analytics Agent | — | Pull YouTube Analytics API daily |
| Retention Analyst | Sonnet | Phân tích drop-off points → feed Learning Loop |
| Diagnostic Engine | Rule + Sonnet | Root cause analysis per channel |
| Strategist Agent | Sonnet | Weekly portfolio decisions + canary logic |
| Topic Scorer | Sonnet | Chấm 0-100 cho topic candidates |
| Competitor Scanner | Haiku | Scan outlier videos đối thủ |
| Replenisher | — | Auto-generate assets khi low stock |
| **Security** | | |
| Input Sanitizer | Rule + Haiku | Chặn Prompt Injection từ external data (RSS, Reddit, transcripts) |
| **Engagement** | | |
| Comment Manager | Haiku | Auto-pin, heart, reply, moderate comments per video |
| Community Post Agent | Haiku | Preview polls, engagement posts, milestone posts |
| **SEO & Planning** | | |
| SEO Optimizer | — | Keyword research, tag gen, title/description optimization |
| Content Calendar | — | Seasonal planning, diversity guard, series management |
| **Legal & Monetization** | | |
| Strike Tracker | — | Monitor copyright/community strikes, dispute workflow |
| YPP Tracker | — | Track YPP eligibility + monetization status per channel |

### Content Creation Engine — Tournament-based Debate (lấy cảm hứng từ Co-Scientist)

**Tại sao không giới hạn 3 rounds cứng?**

Hệ thống Co-Scientist của Google DeepMind (Nature, 2026) chứng minh: **chất lượng output scale theo test-time compute** — càng nhiều vòng debate + evolution, output càng tốt. Giới hạn 3 rounds cứng = cắt bỏ tiềm năng cải thiện. Thay vào đó, dùng **convergence-based termination** + **Elo tournament ranking**.

**Kiến trúc mới — 4 giai đoạn (Generation → Refinement → Tournament → Evolution):**

```
━━━ GIAI ĐOẠN 1: GENERATION (Đa dạng hóa) ━━━

Brief từ Topic Discovery
    ↓
Writer Agent tạo N=3 draft variants (khác nhau về angle/hook/structure)
    → Variant A: Storytelling angle
    → Variant B: Data-driven angle  
    → Variant C: Contrarian/debate angle
    → Mỗi variant là bản thảo độc lập, KHÔNG phải bản sửa

━━━ GIAI ĐOẠN 2: REFINEMENT LOOP (Per-variant, convergence-based) ━━━

Mỗi variant đi qua internal refinement loop:

  Writer nộp draft
      ↓
  [Thinking Agent] — Self-critique nội bộ
    → Tìm logical gaps, weak evidence, rhetorical inconsistencies
    → Xuất "thinking_notes" (private, Critic không thấy)
      ↓
  [Critic Agent] — Adversarial review (hostile auditor)
    → Chấm 100 điểm (VO group 70pt + Production group 30pt)
    → Nếu REJECT: structured feedback chỉ rõ CÂU NÀO cần sửa + LÝ DO
    → Feedback = Pydantic structured output (machine-routable)
      ↓
  Two-stage routing:
    VO < 53           → Writer.revise()        (VO viết kém — sửa nội dung)
    VO ≥ 53, PROD < 23 → VisualDirectorAgent   (VO đã tốt — chỉ fix visual/sfx)
    total ≥ threshold → APPROVED
      ↓
  Writer/VisualDirector sửa → Loop tiếp TỪ Thinking Agent

  Termination conditions (KHÔNG fixed rounds):
    ✅ Score ≥ 80 → APPROVED (variant exits loop)
    ⚠️ Score improvement < 3 điểm giữa 2 rounds liên tiếp → CONVERGED (diminishing returns)
    ❌ Rounds > 7 → HARD STOP (cost guard, tránh infinite loop)
    ❌ Total token spend > $0.50 per variant → BUDGET STOP
    
  Append-only memory: Mỗi round lưu đầy đủ vào PostgreSQL
    → draft_version, critic_score, critic_feedback, thinking_notes
    → Cho phép forensic reconstruction + learning extraction

━━━ GIAI ĐOẠN 3: TOURNAMENT RANKING (Elo-based, từ Co-Scientist) ━━━

Các variants APPROVED/CONVERGED vào tournament:

  Pairwise comparison (Critic Agent as judge):
    → Variant A vs B: "Variant nào sẽ có retention cao hơn trên YouTube?"
    → Variant B vs C: "Variant nào có hook mạnh hơn?"
    → Variant A vs C: ...
    
  Elo Rating System:
    → Mỗi variant bắt đầu Elo = 1000
    → Thắng: +K points, Thua: -K points (K=32)
    → Higher Elo = Higher quality (đã được validate bởi Co-Scientist paper)
    
  Winner = Variant có Elo cao nhất
  Nếu tất cả variants < 70 điểm → HỦY topic, chọn topic mới

━━━ GIAI ĐOẠN 4: EVOLUTION (Optional, cho Hub channels) ━━━

Chỉ áp dụng cho Hub channels (Critic threshold ≥ 85):

  Lấy winning variant + elements hay từ losing variants
      ↓
  [Evolution Agent] — Combine best elements
    → Hook từ Variant A + Structure từ Variant B + Data từ Variant C
      ↓
  Final Critic review (phải ≥ 85 cho Hub)
      ↓
  APPROVED → Compliance Checker gate
```

### Critic Scoring (100 điểm) — Two-Stage Split

```
━━━ VO GROUP (70 điểm) ━━━
hook_quality:         25 điểm  (mở đầu 30s giữ viewer? bold statement, NOT rhetorical Q)
anti_ai_cliche:       15 điểm  (no "delve", "tapestry", "realm", "let me show you"...)
retention_structure:  10 điểm  (pattern interrupts mỗi 60-90s, open loops tự nhiên?)
human_editorial:      10 điểm  (insight mà AI thuần không tạo được?)
niche_compliance:      5 điểm  (YMYL disclaimer, finance/health fatal rules?)
pacing_compliance:     5 điểm  (≤25 words/scene, segment ≤90s — VO issue không phải visual)

━━━ PRODUCTION GROUP (30 điểm) ━━━
visual_concreteness:  25 điểm  (visual_prompt = specific subject+action+context, filmable?)
sfx_appropriateness:   5 điểm  (SFX match niche + VO moment — alarm/cash-register/whoosh/ting)

━━━ ROUTING THRESHOLDS ━━━
VO_PASS  = 53  (75% × 70)
PROD_PASS = 23  (75% × 30)

Two-stage routing:
  VO < 53              → Writer.revise()     (VO cần sửa)
  VO ≥ 53, PROD < 23   → VisualDirectorAgent (lock VO, chỉ fix visual + sfx)
  (VO ≥ 53) AND (PROD ≥ 23) → APPROVED

Approval threshold: Hub ≥ 85 | Spoke ≥ 76 (BẮT BUỘC phải thỏa mãn cả VO và PROD min threshold)
Structured output: Pydantic schema → machine-routable decisions

NICHE FATAL RULES (niche_compliance = 0 nếu vi phạm):
  finance:    "guaranteed returns" → 0 điểm
  health:     medical claim không có citation → 0 điểm
  mythology:  present theory as fact → 0 điểm
```

### Script Format — Scene-based JSON

```
Writer + Evolution output: mỗi đoạn script = list of ScriptScene (3-5 giây/scene)

ScriptScene {
  vo:     str   # MAX 25 words. Natural speech ONLY. BANNED: scripting jargon
  visual: str   # stock footage query — subject + action + context. Filmable on Pexels/Storyblocks
  sfx:    str | None  # niche SFX + whoosh/ting/null. Chỉ dùng tại key numbers/reveals
}

BANNED trong vo: "hook", "segment", "B-roll", "CTA", "outro", "narration",
                 "let me show you", "in today's video", "don't forget to like",
                 "[OPEN LOOP:]", "[HOOK:]" tags

Natural open loop (ĐÚNG): "And there's something even worse — I'll show you in a few minutes"
Scripting jargon (SAI):   "[OPEN LOOP: tease the reveal]"

Niche-specific injection vào Writer + Evolution:
  → sfx_primary, sfx_secondary, broll_style, insider_angle (từ NicheConfig)
  → per-niche comment_hook, video_cta, hook examples (từ NicheConfig.prompt_hints)
```

### Loop-lock Detection (từ LangGraph research)

```
Loop-lock = Critic quá strict → Writer không bao giờ pass
Detection: 
  if rounds >= 5 AND max_score < 60 AND score_trend is FLAT:
    → Loop-lock detected
    → Action: Relax Critic thresholds 10% + Telegram alert
    → Hoặc: Đổi Writer prompt variant + retry
    → Log cho Learning System phân tích sau
```

---

## 6. Error Recovery & Advanced System Engineering

**Bắt buộc implement từ Phase 1 — hệ thống 24/7 không có error handling = sập.**

### Global Rate Limiting (Token Bucket)
```python
# Mọi Agent phải xin token từ Redis trước khi gọi Claude API.
# Đảm bảo không vượt quá TPM/RPM của nhà cung cấp khi có nhiều Worker chạy song song.
```

### State Machine Tracking
```
# KHÔNG phụ thuộc vào RabbitMQ để lưu trạng thái.
# Cần bảng video_production_states (Postgres) lưu trạng thái: 
# QUEUED → SCRIPTING → RENDERING → UPLOADING
# Nếu RabbitMQ crash, Master quét Postgres lấy những task đang lỡ dở và requeue.
```

### Circuit Breaker

```python
# Claude API fail 3 lần liên tiếp → open breaker 5 phút → route sang Ollama
# Auto-close sau cooldown. Langfuse track error rate tự động.
```

### Dead Letter Queue (DLQ)

```
Task fail sau 5 retries → park vào RabbitMQ DLQ
→ Telegram alert cho manual review
→ Dashboard tab "DLQ Items" hiện danh sách
→ Button "Retry" hoặc "Discard"
```

### Bulkhead — tách thread pools

```
Pool A: TTS processing    (ComfyUI crash ≠ TTS crash)
Pool B: Image generation
Pool C: Upload / API calls
Pool D: LLM Agent calls
```

### Retry + Exponential Backoff

```
Attempt 1: wait 5s
Attempt 2: wait 10s + jitter
Attempt 3: wait 20s + jitter
Attempt 4: wait 40s + jitter
Attempt 5: → DLQ
```

### Idempotency

```
Trước khi render/upload: check output đã tồn tại chưa?
→ Nếu rồi → skip (safe crash recovery)
Key: video_id + stage + content_hash
```

### Worker Health Checks

```
Worker heartbeat mỗi 30s → HTTP POST Master /api/heartbeat
Master: last_seen per worker
> 90s không heartbeat → Telegram alert + SSH restart attempt
> 5 phút Master offline → Standby Worker promote
```

### Graceful Degradation Matrix

| Component Down | Auto-Response |
|----------------|---------------|
| Claude API | Circuit breaker → Ollama fallback |
| ComfyUI (Worker N) | Route sang Worker khác, queue backlog |
| NAS offline | Worker local cache 24h, pause production, alert |
| RabbitMQ crash | Persistent messages (disk) → auto-recover on restart |
| Internet outage | Queue uploads locally, resume khi có mạng |
| PostgreSQL down | WAL recovery + auto-restart |
| Master Mac Mini | Standby Worker promote (streaming replication) |

---

## 7. Topic Discovery Engine

### 5 nguồn quét song song

```
Source 1: YouTube Competitor Scanner
  → COMPETITOR_CHANNELS per niche (100K-1M subs, có thể beat)
  → Outlier = views > 3x channel median
  → Bóc băng transcript → extract patterns → lưu KB

Source 2: Google Trends (pytrends)
  → 6 markets: US, UK, AU, CA, JP, KR
  → related_queries "rising" (growth > 100% trong 7 ngày)

Source 3: Reddit + Quora (PRAW)
  → r/mythology, r/longevity, r/investing, r/psychology, r/japan, r/korea
  → Filter: score > 500 AND comments > 50

Source 4: T5 Category Sweeper (Supernova Radar)  ← CORE ENGINE
  → Quét trực tiếp `mostPopular` API không cần từ khóa (Seed query).
  → High-RPM whitelist: 2 (Autos), 19 (Travel), 22 (People), 26 (How-to), 27 (Education), 28 (Tech).
  → Mục tiêu: Tìm kênh nhỏ (<100K subs) có video Viral bất thường (Supernova).

Source 5: News RSS
  → WebMD, Bloomberg, TechCrunch, NHK World, Korea JoongAng Daily
  → Topic mentions > 10 lần/24h = breaking trend
```

### Niche Dedup & Chống Context Bloat

Sau khi tìm ra ngách mới từ 5 nguồn trên:
1. **Top 20 Pre-filter:** Dùng vector search lấy 20 ngách gần giống nhất từ `vault.db`. KHÔNG nạp toàn bộ hàng ngàn ngách vào prompt để tránh nổ Token (Context Bloat).
2. **NicheDedupAgent (DeepSeek Flash):** Đọc Top 20 ngách cũ và Niche mới, so sánh Semantic Overlap. Nếu tệp khán giả và Pain points trùng >80% → BỎ QUA HOẶC MERGE.

### Scoring (0-100)

```
Trend Momentum:  0-30  (growth rate, capped 30)
Gap Score:       0-40  (0 quality videos = +40, <5 = +25, <20 = +10)
RPM Potential:   0-20  (market rpm_floor, capped 20)
Novelty vs KB:   0-10  (ChromaDB similarity < 0.7 = +10, decay-aware)

Threshold:
  > 70: Auto-approve → Brief Generator → RabbitMQ
  50-70: Telegram alert → User review
  < 50:  Discard
```

---

## 8. Channel Management System

### Database schema

```sql
channels:          id, name, niche, type(hub|spoke), language, target_market,
                   google_cloud_project, api_key_ref, adspower_profile,
                   brand_config_path, status, monetized, subscriber_count

channel_metrics:   channel_id, recorded_date, views, impressions, ctr,
                   avg_view_duration, avg_view_percentage, rpm,
                   estimated_revenue, subscribers_gained/lost, health_score

video_metrics:     video_id, channel_id, title, published_at, duration_seconds,
                   views, ctr, avg_view_duration, avg_view_percentage,
                   is_outlier, is_underperformer, thumbnail_variant,
                   cost_usd, revenue_usd, roi, diagnosis, audit_trail(JSONB)

channel_diagnostics: channel_id, period, score_ctr/retention/consistency/
                     seo/trend_alignment, issues(JSONB), recommendations(JSONB),
                     competitor_benchmark(JSONB)
```

### Health Score (0-100)

```
CTR score:         0-25  (< 2% = bad, > 5% = good)
Retention score:   0-30  (< 30% = bad, > 50% = good)
Consistency score: 0-15  (upload frequency vs target)
Momentum score:    0-20  (subscriber growth week-over-week)
Revenue score:     0-10  (RPM vs market benchmark)
```

### Auto-executable Actions

| Trigger | Action |
|---------|--------|
| CTR < 2% | Generate 3 thumbnail variants → A/B test via `thumbnails.set` API |
| Retention < 30% | brand_config → `script_template: fast_paced`, max_segment: 45s |
| Views drop > 60% vs prev week | status = shadowban, pause queue, Telegram CRITICAL |
| Video views > 3x median | Clone topic → queue 3 briefs (priority HIGH) |
| Retention drop point detected | Feed Retention Analyst → update Writer system prompt |
| Health < 30 | Telegram CRITICAL alert |
| Health > 80 (was < 60) | Telegram BREAKOUT, tăng production rate x2 |
| Niche ROI < 0 sau 30 ngày | Pause production, Strategist review |

### Channel Identity Isolation Protocol

```
Mỗi kênh phải CÓ riêng:
  ✅ Google Account
  ✅ IP Residential (1-1-1 ratio)
  ✅ AdsPower Profile
  ✅ Google Cloud Project + API Key  ← CRITICAL cho quota isolation
  ✅ Email domain (không dùng chung @gmail)
  ✅ Payment method / Adsense account
  ✅ Recovery email + phone riêng
  ✅ KHÔNG cross-link giữa các kênh
  ✅ Metadata templates KHÁC NHAU giữa kênh
```

### Competitor Benchmark

- Track 5-10 kênh đối thủ per niche (100K-1M subs)
- So sánh: CTR rank, retention rank, RPM rank, upload frequency rank
- Weekly update → Strategist Agent dùng để ra quyết định

### ChannelGuard: Channel Survival Protocol

**1. Upload Velocity Limiter:**
Ngăn chặn thuật toán YouTube đánh cờ kênh là Spam bằng cách giới hạn tốc độ đăng.
- Kênh non (<90 ngày tuổi): Tối đa 3 videos/tuần.
- Kênh trưởng thành (≥90 ngày tuổi): Tối đa 7 videos/tuần.

**2. Strike Recovery Protocol (Kill-switch):**
Nếu hệ thống phát hiện kênh dính gậy bản quyền (Copyright Strike) hoặc gậy cộng đồng (Community Strike):
- Đóng băng toàn bộ hoạt động upload của kênh đó trong đúng 14 ngày.
- Đưa kênh vào trạng thái `shadowban` và chờ manual review.

---

## 9. Asset Library System

### Asset Manager logic

```python
search_music(mood, bpm_range, duration_min)
  → ORDER BY use_count ASC  (ít dùng được ưu tiên)
  → Generate mới CHỈ KHI DB < 3 kết quả phù hợp

search_broll(tags, duration_needed)
  → Semantic search trong index.json
  → Download Pexels API nếu thiếu

register_asset(path, type, metadata)
  → MD5 fingerprint
  → Lưu SQLite

# CHÚ Ý CONCURRENCY:
# Phải dùng Redis Lock khi check DB và generate asset để tránh 
# 5 Worker cùng generate chung 1 bài nhạc gây quá tải GPU.

increment_use(asset_id)  → rotation tracking
```

### Auto-replenishment (Cron 2AM)

```
Check low stock: < 10 file per mood hoặc avg use_count > 20
→ Generate 5 tracks ACE-Step per mood thiếu
→ Download 10 B-roll clips Pexels per tag thiếu
KHÔNG: perturb audio — bỏ hoàn toàn
```

### Brand Config (per channel - Nguồn sự thật JSON)

```json
{
  "channel_id": "hub_finance_us",
  "voice_profile": "kokoro_en_us_v1",
  "voice_persona": "authoritative_50yo_male",
  "brand_color_hex": "#1A1A2E",
  "font_vibe": "Montserrat Bold",
  "hook_format": "[Contrarian statement] + [3s pause] + [Data reveal]",
  "rss_feeds": ["https://techcrunch.com/feed/"],
  "subreddits": ["r/investing", "r/personalfinance"],
  "transition_style": "zoom_in_0.3s",
  "intro_template": "assets/intros/hub_finance_us/intro_v2.mp4",
  "outro_template": "assets/outros/cta_v3.mp4",
  "music_bpm_range": [120, 140],
  "script_template": "standard",
  "target_duration_min": 10
}
```

**Quy tắc Ghi đè (Override Rule):**
LLM phải sinh ra các trường `hook_format`, `brand_color_hex`, `font_vibe`, `voice_persona`, `rss_feeds`, và `subreddits` vào file `channels/{id}.json`. Các tham số này sẽ GHI ĐÈ (Override) các cài đặt mặc định tĩnh trong `config/niches.py`. Khi Writer viết kịch bản, BẮT BUỘC phải đọc từ `channels/{id}.json` trước (Source of Truth).

---

## 10. Media Pipeline

### TTS Module

```
Primary:       Kokoro-82M → en/ja/ko/vi narration (Apache 2.0, CPU-friendly)
Voice cloning: XTTSv2     → khi brand_config.voice_clone != null
Fast fallback: Piper TTS  → khi Worker tải cao
Output:        audio.wav, normalized -14 LUFS (YouTube standard)
```

### Image Gen Module

```
Batch scenes:  ComfyUI + SDXL + ControlNet + IP-Adapter FaceID Plus V2
               + FaceDetailer (face consistency)
Hero shots:    ComfyUI + FLUX.1 (photorealism, text rendering)
Master Reference Rule:
  → 1 portrait chất lượng cao per character
  → IP-Adapter weight: 0.5-0.8
  → Chain: LoRA → IP-Adapter → FaceDetailer
Output:        PNG sequence
```

### Video Gen Module (mới)

```
Tool:   Wan 2.1+ (Apache 2.0), ComfyUI integration
Use:    Chỉ scene phức tạp (theo brand_config.use_video_gen)
Output: 5-10s cinematic clips
Fallback: SDXL image + Ken Burns effect (zoom/pan FFmpeg)
```

### Music Module (Hybrid Strategy)

```
Priority 1: YouTube Audio Library (MIỄN PHÍ, 100% safe)
  → Asset Manager search by mood/genre/duration
  → Ưu tiên dùng trước — KHÔNG BAO GIỜ bị ContentID claim
  → Cache downloaded tracks trong NAS/assets/music/youtube_audio_lib/

Priority 2: Royalty-Free Libraries (CC0 / Attribution)
  → Pixabay Music API, Free Music Archive, Incompetech
  → Auto-verify license metadata trước khi dùng
  → Attribution tracks → auto-inject credit vào description
  → Cache: NAS/assets/music/royalty_free/

Priority 3: ACE-Step v1.5 AI-generated (khi cần unique mood)
  → Apache 2.0, LoRA fine-tuning per niche
  → Dùng khi Priority 1+2 không match mood cụ thể
  → ComfyUI native integration

Fallback:  MusicGen (AudioCraft)
KHÔNG:     Perturb audio — bỏ hoàn toàn
Output:    music_bg.wav
```

### Subtitle Module

```
Tool:   WhisperX (word-level forced alignment)
Input:  audio.wav
Output: subtitle.srt (timestamp chính xác từng từ)
```

### Garbage Collection (Storage Management)

```
Daemon: Xóa toàn bộ raw PNG sequences và uncompressed WAV ngay sau khi
        FFmpeg render ra file mp4 thành công.
Lý do:  Tránh đầy NAS trong vài ngày do số lượng file trung gian khổng lồ.
```

### Thumbnail Gen

```
Tool:   ComfyUI (SDXL/FLUX) + PIL/Pillow (text overlay)
Output: 3 variants A/B/C (khác màu/biểu cảm/text)
Upload: thumbnails.set API (variant A ngay khi publish)
Swap:   A/B Test Agent swap sang B qua API nếu CTR < 4% sau 24h
```

### FFmpeg Render

```
Layer 1: PNG/Video clips (crossfade 0.5s hoặc Wan clips)
Layer 2: audio.wav (voiceover)
Layer 3: music_bg.wav (-20dB, ducking khi voiceover)
Layer 4: subtitle.srt
Layer 5: intro.mp4 + outro.mp4
Output:  final_video.mp4 (1080p H.264, AAC)
Enforcer: Brand Config đọc từ NAS — mọi Workers output nhất quán
```

### Content Fingerprint Check

```python
class ContentFingerprint:
    script_embedding:     Vector  # ChromaDB
    visual_hash:          str     # Perceptual hash key frames
    audio_fingerprint:    str     # Chromaprint voiceover
    music_fingerprint:    str     # ACE-Step output hash
    structure_signature:  str     # intro_length, scene_count, transition_types

    def similarity_score(self, other) -> float:
        # > 0.7 = quá giống → REJECT hoặc diversify assets
```

---

## 11. Upload Pipeline (YouTube Data API v3)

### Upload flow

```python
# 1. OAuth2 per channel (service account hoặc OAuth consent)
# 2. videos.insert — upload file từ NAS
# 3. Điền: title (variant A), description + AI disclosure + affiliate links + tags
# 4. Set publishAt (prime time market timezone)
# 5. thumbnails.set (variant A)
# 6. Log: video_id, channel_id, timestamp → video_metrics
```

### Upload Scheduler (rate limiting intelligence)

```
Rate limits:
  Hub channel:   MAX 1 video/kênh/ngày
  Spoke channel: MAX 3 video/kênh/ngày
  Spread:        Random 15-45 phút delay giữa uploads cùng kênh
  Time window:   Không upload 11PM-6AM local time (mimic human)
  Burst guard:   10 uploads → pause 2 giờ → tiếp (YouTube soft limit)
```

### Prime time per market

```
US:  Tue-Thu 2PM-4PM EST
UK:  Mon-Wed 12PM-2PM GMT
AU:  Tue-Thu 7PM-9PM AEST
JP:  Wed-Fri 8PM-10PM JST
KR:  Tue-Thu 7PM-9PM KST
```

### Compliance gate (bắt buộc trước mọi upload)

```python
ComplianceChecker.check(video):
  ✅ ai_disclosure_present()        # "This video was made with AI assistance"
  ✅ no_misleading_metadata()        # Title/thumbnail match nội dung
  ✅ no_copyrighted_music()          # Fingerprint check trước khi upload
  ✅ ftc_disclosure()                # Affiliate links disclosed rõ ràng
  ✅ advertiser_friendly()           # Không trigger demonetization
  ✅ not_targeting_children()        # COPPA
  ✅ cross_channel_uniqueness()      # Không duplicate cross-channel
  → Fail bất kỳ check → Video vào DLQ, không upload
```

---

## 12. Analytics & Feedback Loop

### Daily Cycle (6AM)

```
Health Crawler → YouTube Analytics API → channel_metrics + video_metrics
              → health_score
              → Retention heatmap analysis (drop-off points)
              → Auto-alerts: shadowban, outlier, critical
              → ROI calculation per video
```

### Weekly Cycle (Monday 9AM)

```
Diagnostic Engine → rule-based issues
Root Cause Analyst → LLM deep analysis (Claude Sonnet)
Retention Analyst → correlate drop-off với script structure
                  → update Writer Agent system prompt
Competitor Benchmark → update ranking
Strategist decisions:
  - Health < 30% → pause production
  - Breakout (health > 80, was < 60) → production x2
  - Outlier video → clone 3 briefs
  - New format → test trên Spoke (canary) TRƯỚC Hub
  - Niche ROI < 0 → reallocate budget
Knowledge Base decay → expire patterns > 30 ngày (trend-based)
```

### Monthly Cycle

```
Kill dead channels (status = dead 30+ ngày)
Reallocate Worker capacity (weak → strong channels)
LLM Evals Pipeline: Chạy bộ 50 regression tests trước khi update system prompt của Writer Agent
Update COMPETITOR_CHANNELS list
Review budget allocation per niche
Distill Knowledge Base (archive outdated patterns)
Rotate API keys + proxy accounts nếu cần
```

### Retention Heatmap Analysis

```
WhisperX timestamp + YouTube retention data
→ Tìm điểm viewer drop > 5%
→ Correlate với script segment đang ở
→ Auto-detect: "drop tại transition Y → weak hook"
→ Feed Writer Agent: "Tránh pattern X tại segment Y"
→ Đây là self-learning loop thực sự
```

### ROI per video

```
Cost = Claude API + proxy bandwidth + electricity (GPU hours × $/kWh) + NAS pro-rated
Revenue = Adsense + Affiliate clicks × commission + Sponsorship
ROI = (Revenue - Cost) / Cost
→ Track per video, per niche, per market
→ Strategist dùng để allocate budget
```

---

## 12B. Self-Improving Learning Loop Architecture (CORE SYSTEM)

> **Trạng thái 2026-07-22:** đây là **target architecture**, không phải mô tả đầy đủ code
> production hiện tại. Phần self-improvement đã chạy thật của script engine được chốt ở
> Section 0.2 và 0.5. Đặc biệt, không được nói hệ thống đang auto-update prompt/rule hay
> distill `lessons.json` nếu chưa chỉ ra wiring runtime + test tương ứng.

> **Đây là phần quan trọng nhất sau Content Creation Engine.**
> Hệ thống không có learning loop = static AI = output không cải thiện theo thời gian.
> Nghiên cứu từ: Co-Scientist (DeepMind), Constitutional AI (Anthropic),
> Learning Loop Architecture (Bosio.digital), AutoResearch Loop (Karpathy).

### Tại sao cần Learning Loop?

```
Vấn đề: Hệ thống AI tĩnh
  → Writer Agent ngày 1 = Writer Agent ngày 100
  → Cùng mistake lặp lại mãi (AI cliché, weak hooks, sai pacing)
  → Không học từ YouTube performance data thực tế
  → Prompt engineering thủ công = bottleneck (người phải đọc data → sửa prompt)

Mục tiêu: Hệ thống AI tự cải thiện
  → Writer Agent tháng 6 tốt HƠN ĐÁNG KỂ so với tháng 1
  → Tự phát hiện pattern nào work/fail từ production data
  → Auto-update behavior mà KHÔNG cần người sửa prompt thủ công
  → Compounding improvement: mỗi tuần tốt hơn tuần trước
```

### Model Routing cho Learning Loop

```
┌─────────────────────────────────────────────────────────────────────┐
│ Component              │ Model          │ Lý do                      │
├────────────────────────┼────────────────┼────────────────────────────┤
│ Path 1: Pattern detect │ KHÔNG CẦN LLM │ Redis counter (rule-based) │
│ Path 1: Auto-rule gen  │ Haiku          │ Simple template → rule     │
│ Path 2: Diagnostic     │ Sonnet         │ Complex correlation + plan │
│ Path 2: Canary eval    │ Haiku          │ Binary pass/fail scoring   │
│ Path 3: Learning Extract│ Haiku         │ Pattern extraction routine │
│ Binary Eval scoring    │ KHÔNG CẦN LLM │ Lambda functions (code)    │
│ Diagnostic Feedback    │ Haiku          │ Root cause per failure     │
│ Weekly summary report  │ Sonnet         │ Strategic recommendations  │
│ Lesson distillation    │ Haiku          │ Merge/archive old lessons  │
└─────────────────────────────────────────────────────────────────────┘

Chi phí ước tính Learning Loop:
  → Path 1: ~$0.01/event (1 Haiku call khi threshold crossed)
  → Path 2: ~$0.30/tuần (1 Sonnet diagnostic + N Haiku evals)
  → Path 3: ~$0.02/video (1 Haiku extraction call)
  → Tổng: < $2/tuần cho full learning loop
  → Target: < 5% tổng LLM spend
```

### Tự đánh giá — Ai đánh giá ai?

```
Quan trọng: KHÔNG để cùng 1 model tự đánh giá output của chính nó
(Self-evaluation bias — model tends to rate own output cao hơn thực tế)

Nguyên tắc:
  Writer (Sonnet) viết → Critic (Sonnet KHÁC instance, KHÁC prompt) đánh giá
  Critic score → Binary Evals (CODE, không LLM) verify khách quan
  YouTube metrics (THỰC TẾ) → Ground truth cuối cùng

Hierarchy of trust:
  1. YouTube real metrics (CTR, retention, revenue) ← Ground truth
  2. Binary Evals (code-based, deterministic)      ← Objective
  3. Critic Agent scoring (LLM-based)              ← Subjective nhưng structured
  4. Self-reported Writer confidence               ← Least trusted

Tại sao hierarchy này?
  → Critic có thể sai (hallucinate quality, drift over time)
  → Binary Evals khách quan nhưng chỉ check format/rule
  → CHỈ YouTube metrics cho biết viewer CÓ THỰC SỰ thích không
  → Learning Loop dùng YouTube metrics làm ultimate feedback signal
```

### 3-Path Feedback Architecture

```
━━━ PATH 1: Silent Skill Optimization (Auto, Real-time) ━━━
Scope: Sửa lỗi rõ ràng, không cần human review
Trigger: Mỗi khi Critic reject một pattern cụ thể ≥ 3 lần

  Ví dụ: Critic reject "hook dùng câu hỏi tu từ" 5 lần liên tiếp
    → Hệ thống tự thêm vào Writer's blacklist:
      "TRÁNH: Mở đầu bằng rhetorical question (Critic reject 5/5 lần)"
    → Writer tự động tránh pattern này từ lần sau
    → Log change vào skill_changelog

  Ví dụ: Script về Finance luôn bị Critic trừ điểm "source attribution"
    → Auto-add rule: "Finance scripts PHẢI có ≥ 2 source citations"
    → Effective ngay lập tức

  Implementation:
    pattern_tracker = Redis sorted set
    key: "{agent}:{rejection_reason}"
    value: count
    threshold: 3 occurrences → auto-update agent blacklist/rules
    
  Guard rails:
    → Max 5 auto-updates/tuần (tránh drift quá nhanh)
    → Mỗi auto-update có rollback hash
    → Nếu avg_score DROP sau auto-update → auto-rollback

━━━ PATH 2: Structured Learning with Human Gate (Weekly) ━━━
Scope: Thay đổi cấu trúc, ảnh hưởng nhiều agents
Trigger: Weekly Diagnostic Cycle (Monday 9AM)

  Step 1: Harvest Production Data
    → Pull tất cả video metrics tuần qua
    → Correlation analysis: script_pattern ↔ YouTube performance
    → Ví dụ: "Videos mở đầu bằng controversy có CTR 7.2% vs avg 4.1%"
    → Ví dụ: "Videos > 12 phút có retention drop 40% tại minute 8"

  Step 2: Diagnostic Agent (Claude Sonnet) phân tích
    → Input: performance data + current Writer rules + Critic patterns
    → Output: structured improvement_candidates
    
    improvement_candidates = [
      {
        "id": "IMP-2026-W21-001",
        "finding": "Controversy hooks +75% CTR vs question hooks",
        "proposed_change": "Writer prompt: Prioritize controversy/tension hooks",
        "affected_agents": ["writer", "critic"],
        "confidence": 0.82,
        "evidence": {"sample_size": 23, "p_value": 0.03},
        "risk": "medium — có thể trigger controversial content flags"
      }
    ]

  Step 3: Human Review Gate (Dashboard tab "Learning Queue")
    → Mỗi candidate hiển thị: finding, evidence, risk, proposed change
    → Buttons: [Approve] [Reject] [Modify] [Defer]
    → CHỈ KHI human approve → change được deploy
    
  Step 4: Deploy as Prompt Version (canary)
    → 20% traffic dùng new prompt version, 80% old
    → Monitor 48h: Critic scores, production success rate
    → Nếu improvement confirmed → full rollout
    → Nếu degradation → auto-rollback + log reason

  Tại sao cần Human Gate?
    → Nghiên cứu từ Bosio.digital (2026): Teams thử full automation
       ở layer này → hàng trăm changes/tuần → untraceable failures
       → multiple rollbacks → mất stability
    → Human gate = engineering requirement, không phải skepticism

━━━ PATH 3: Context Expansion on Cycle Close (Auto, Accumulative) ━━━
Scope: Mở rộng knowledge base từ mỗi production cycle
Trigger: Sau mỗi video published + có metrics (7 ngày sau upload)

  Video published + 7-day metrics available
      ↓
  [Learning Extractor Agent] phân tích:
    → Script structure → YouTube retention curve correlation
    → Hook type → CTR impact
    → Pacing pattern → avg_view_duration impact
    → Music mood → engagement correlation
    → Thumbnail style → CTR per niche
      ↓
  Extract "Engagement Patterns":
    {
      "pattern_id": "EP-2026-0521",
      "niche": "finance",
      "market": "US",
      "finding": "Numbered list format (5 Tips...) → +22% retention vs narrative",
      "confidence": 0.75,
      "sample_size": 12,
      "decay_date": "2026-08-21"  // 90 ngày cho evergreen
    }
      ↓
  Lưu vào Knowledge Base (ChromaDB + PostgreSQL)
    → Writer Agent query patterns trước khi viết
    → Decay-aware: patterns cũ giảm weight tự động
    → Cross-niche patterns được flag cho Strategist review
```

### Binary Eval System (từ AutoResearch Loop)

```python
# Thay vì chấm chủ quan "7/10", dùng binary pass/fail cho từng tiêu chí
# Mỗi eval = rõ ràng, actionable, có thể track improvement theo thời gian

WRITER_EVALS = {
    # Content Quality
    "hook_under_15_words":     lambda s: len(s.hook.split()) <= 15,
    "no_ai_cliches":           lambda s: not any(c in s.text for c in AI_CLICHE_LIST),
    "has_pattern_interrupt":   lambda s: s.pattern_interrupt_count >= 2,
    "sources_cited":           lambda s: s.source_count >= YMYL_REQUIREMENTS.get(s.niche, 0),
    
    # Structure
    "under_target_duration":   lambda s: s.estimated_duration <= s.brand_config.target_max,
    "segment_under_90s":       lambda s: all(seg.duration <= 90 for seg in s.segments),
    "intro_under_30s":         lambda s: s.intro_duration <= 30,
    
    # Uniqueness
    "template_divergence_30":  lambda s: s.divergence_from_recent(5) >= 0.30,
    "no_cross_channel_dup":    lambda s: s.cross_channel_similarity < 0.70,
    
    # Policy
    "has_ai_disclosure":       lambda s: "AI" in s.description_template,
    "no_coppa_violation":      lambda s: not s.targets_children,
}

# Track pass rate per eval over time
# Ví dụ: "hook_under_15_words" pass rate: W1=60%, W4=78%, W8=91%
# → Chứng minh hệ thống đang TỰ CẢI THIỆN
```

### Diagnostic Feedback (không chỉ score, mà CỤ THỂ tại sao fail)

```python
class DiagnosticEngine:
    """Turn failures into actionable lessons"""
    
    def diagnose(self, failed_evals: list, script: Script) -> list[Lesson]:
        # Không chỉ "test failed" → mà "tại sao" + "làm gì khác"
        prompt = f"""
        Failed evals: {failed_evals}
        Script excerpt: {script.failing_section}
        
        For each failure:
        1. Root cause (tại sao Writer tạo ra output này?)
        2. Specific instruction (Writer nên làm gì khác?)
        3. Example fix (viết lại đoạn đó)
        
        Output JSON: [{{eval_id, root_cause, instruction, example_fix}}]
        """
        return llm_call(prompt)  # Haiku đủ cho diagnostic
```

### Persistent Learning Store (lessons.json)

```python
# Mỗi Agent có learning store riêng, đọc trước mỗi execution

# writer_lessons.json
{
  "version": 42,
  "last_updated": "2026-05-23",
  "lessons": [
    {
      "id": "WL-001",
      "source": "path_1_auto",  # hoặc "path_2_human", "path_3_context"
      "created": "2026-03-15",
      "lesson": "TRÁNH rhetorical questions trong hook — dùng bold statement thay thế",
      "evidence": "Critic rejected 7/7 times, CTR +2.1% khi đổi sang statements",
      "confidence": 0.91,
      "applied_count": 34,
      "success_rate": 0.88
    },
    {
      "id": "WL-002", 
      "source": "path_2_human",
      "created": "2026-04-01",
      "lesson": "Finance videos: luôn đặt disclaimer trước minute 1",
      "evidence": "2 videos bị demonetized do thiếu disclaimer early",
      "confidence": 1.0,
      "applied_count": 18,
      "success_rate": 1.0
    }
  ],
  "max_lessons": 50,  # Distill khi vượt
  "archive": "writer_lessons_archive.json"
}

# Distillation logic (tránh token bloat):
# Khi > 50 lessons:
#   → Merge lessons cùng category
#   → Archive lessons có applied_count = 0 sau 30 ngày
#   → Archive lessons có success_rate < 0.5
#   → Giữ lessons có confidence > 0.8 AND success_rate > 0.7
```

### Learning Loop Metrics (Dashboard tab "Learning")

```
Metrics phải track để CHỨNG MINH hệ thống đang cải thiện:

1. Writer Score Trend
   → Avg Critic score per week: W1=72, W4=79, W8=84, W12=87
   → Target: Upward trend ≥ 1 point/tuần

2. Binary Eval Pass Rate
   → Per eval, per week
   → "no_ai_cliches": 60% → 78% → 91% → 95%
   → Visualize: heatmap of all evals over time

3. YouTube Performance Correlation
   → Are learning-loop-improved scripts actually performing better?
   → Correlation: Critic score ↔ CTR, Critic score ↔ Retention
   → If no correlation → learning loop is optimizing wrong metrics!

4. Lesson Utilization
   → How many lessons are actively being applied?
   → Lessons with 0 applied_count after 14 days → review/remove

5. Cost of Improvement
   → Extra LLM cost for diagnostic + learning extraction
   → Target: < 5% of total LLM spend
   → ROI: revenue improvement vs learning loop cost
```

### Comparison: OmniCast vs Industry Approaches

```
                    Old (v3.0)        New (v3.1)              Co-Scientist
Debate rounds:     Fixed 3           Convergence-based       Unlimited (Elo)
Variants:          1 (sequential)    3 (parallel)            Hundreds
Selection:         Pass/fail         Elo tournament          Elo tournament
Evolution:         None              Combine best elements   Genetic evolution
Learning:          Manual prompt     3-path auto-learning    Self-play improvement
Eval type:         Subjective 0-100  Binary pass/fail        Elo auto-rating
Knowledge:         Static KB         Decay-aware + auto-grow Specialized tools
Human oversight:   None              Path 2 gate             Scientist feedback
```

---

## 13. Compliance & Audit Trail

### Audit trail per video (JSONB trong video_metrics)

```json
{
  "brief_source": "google_trends:US, reddit:r/investing",
  "script_versions": [
    {"version": 1, "critic_score": 72, "rejection_reason": "hook too generic"},
    {"version": 2, "critic_score": 85, "status": "APPROVED"}
  ],
  "ai_models_used": ["claude-sonnet-4-6", "sdxl-1.0", "kokoro-82m", "ace-step-v1.5"],
  "compliance_checks": {
    "ai_disclosure": true,
    "no_copyright_music": true,
    "ftc_disclosure": true,
    "cross_channel_unique": true
  },
  "content_fingerprint": {
    "script_hash": "abc123",
    "visual_hash": "def456",
    "audio_hash": "ghi789"
  }
}
```

---

## 14. Dashboard — Full System Monitor (Desktop + Mobile)

> **Yêu cầu: Giám sát TOÀN BỘ hoạt động trên cả điện thoại lẫn desktop.**

### Tech Stack & Architecture

```
Phase 1 (MVP, Tuần 6):      Streamlit + Cloudflare Tunnels
Phase 2 (Production, Tuần 11): FastAPI backend + Next.js frontend (PWA)

Tại sao Next.js PWA thay vì native app?
  → 1 codebase chạy cả Desktop (browser) + Mobile (Add to Home Screen)
  → Push notifications qua Service Worker
  → Offline-capable (cache critical data)
  → Responsive design: auto-adapt phone/tablet/desktop
  → Không cần Apple/Google store approval

Stack Phase 2:
  Backend:  FastAPI + WebSocket (real-time updates)
  Frontend: Next.js 14 + TailwindCSS + shadcn/ui
  Auth:     Cloudflare Access (SSO email) hoặc NextAuth
  Hosting:  Master node (self-hosted) + Cloudflare Tunnel
  PWA:      next-pwa plugin → installable trên phone
  Real-time: WebSocket cho production pipeline live view
  Charts:   Recharts (lightweight, mobile-friendly)
```

### Tab Layout (10 tabs)

```
━━━ OVERVIEW ━━━

Tab 1: 🏠 Dashboard Home (Mobile-first summary)
  → Top KPIs: Videos today | Revenue today | Active channels | System health
  → Quick alerts: Critical issues cần action ngay
  → Pipeline status bar: X researching | Y debating | Z rendering | W publishing
  → Last 24h activity feed (timeline)
  → Mobile: swipe cards, tap to drill down

━━━ CONTENT CREATION ━━━

Tab 2: 📝 Production Monitor (Kanban/List toggle)
  Desktop: Kanban columns (Researching → Debate → Rendering → QC → Upload → Published)
  Mobile: List view (sortable by status/channel/priority)
  → Click/tap card → full detail:
    - Script versions + Critic scores per round
    - Tournament results (Elo rankings of variants)
    - Thinking Agent notes
    - Current status + estimated completion
  → Actions: [Force Approve] [Pause] [Kill] [Re-queue]
  → Filter: by channel, niche, status, date

Tab 3: 🧠 Learning Loop (MỚI — CORE)
  Section A: Writer Score Trend (line chart, weekly)
    → Clear upward trend = system improving
    → Flat/declining = investigate Path 2 findings
  Section B: Binary Eval Heatmap
    → Rows = eval criteria, Columns = weeks
    → Green/yellow/red pass rates
    → Tap cell → drill into specific failures
  Section C: Active Lessons (per agent)
    → Table: lesson, confidence, applied_count, success_rate
    → Actions: [Deactivate] [Archive] [Edit]
  Section D: Learning Queue (Path 2 human gate)
    → Pending improvement_candidates
    → Buttons: [Approve] [Reject] [Modify] [Defer]
    → Show evidence, confidence, risk level
  Section E: Skill Changelog
    → History of all auto-updates (Path 1) + human-approved changes (Path 2)
    → Rollback button per change
  Mobile: Collapsible sections, swipe between A-E

━━━ CHANNELS & ANALYTICS ━━━

Tab 4: 📊 Channel Intelligence
  Health heatmap (all channels at a glance, color = health score)
  → Tap channel → sub-pages:
    - Metrics: CTR, retention, revenue, subs (90-day charts)
    - Diagnosis: auto-detected issues + evidence
    - Prescriptions: Strategist recommendations + [Execute] buttons
    - Competitors: benchmark ranking + outlier alerts
  Mobile: Card per channel, swipe for details

Tab 5: 💰 Budget & Revenue
  → Daily API spend vs cap (bar chart)
  → Cost breakdown: Claude | GPU-hours | bandwidth | NAS
  → ROI per video, per niche, per market (table + chart)
  → Revenue projection (weekly/monthly)
  → Budget alerts: approaching cap, negative ROI niches
  Mobile: Summary cards with sparklines

━━━ SYSTEM OPERATIONS ━━━

Tab 6: 🖥️ Infrastructure
  → Worker cards: CPU%, RAM%, GPU temp, last heartbeat, status
  → Queue depth per Worker (real-time bar)
  → NAS status: free space, last backup, replication lag
  → Master health: PostgreSQL, RabbitMQ, Redis, ChromaDB
  → DLQ viewer: items + [Retry] [Discard] buttons
  Mobile: Red/green status dots, tap to expand

Tab 7: 🔐 Token Management (MỚI)
  → All OAuth tokens status: healthy/warning/expired
  → Token expiry countdown per channel
  → One-click re-auth flow (generate consent URL)
  → Token health history chart
  → Alert: scope changes, revocations
  Mobile: Red banner if any token critical

Tab 8: ✅ Compliance & Audit
  → Search audit trail by video ID / channel
  → Compliance check failure log (filterable)
  → AI disclosure verification status per video
  → ContentID claim tracker
  → YMYL disclaimer injection log
  Mobile: Search + recent failures list

━━━ KNOWLEDGE & ASSETS ━━━

Tab 9: 📚 Knowledge Base
  → Active engagement patterns (sortable by confidence/recency)
  → Pattern decay status (expiring soon)
  → Competitor insights archive
  → Search: by niche, market, pattern type
  → KB health: total patterns, avg age, coverage per niche
  Mobile: Search-first design

Tab 10: 🎨 Asset Library
  → Stock levels: music (3 sources) | images | b-roll | intros
  → Low stock alerts with auto-generate buttons
  → Music library browser: YouTube Audio Library, RF, AI-generated
  → Usage stats: most used, least used, never used
  Mobile: Grid view with thumbnails
```

### Mobile-Specific Features

```
1. Push Notifications (PWA Service Worker)
  → CRITICAL: Token expired, channel paused, DLQ overflow
  → WARNING: Low stock, budget approaching cap, health dropping
  → INFO: Video published, milestone reached

2. Quick Actions (bottom navigation on mobile)
  → [Approve] → Learning Queue items
  → [Status] → Pipeline overview
  → [Alerts] → All pending alerts
  → [Pause/Resume] → Emergency channel pause

3. Telegram Bot (parallel to Dashboard, same data)
  /status          → Pipeline summary
  /channels        → Health per channel
  /approve <id>    → Approve Learning Queue item
  /pause <channel> → Emergency pause
  /dlq             → DLQ count + top items
  /budget          → Today's spend vs cap
  /learning        → This week's score trend
  → Inline keyboards for quick approve/reject

4. Offline Mode (PWA)
  → Cache last-known state locally
  → Queue actions (approve/reject) until reconnect
  → Show "Last updated: X minutes ago" badge
```

### Access Control

```
Auth layers:
  Layer 1: Cloudflare Tunnel (not exposed to public internet)
  Layer 2: Cloudflare Access (email SSO — only your email)
  Layer 3: Session token (JWT, 24h expiry)
  
  Desktop: Browser → cloudflare tunnel URL → SSO login
  Mobile:  PWA → same URL → biometric (face/fingerprint after first login)
  Telegram: Pre-authorized chat_id (whitelist)

Role-based (nếu cần multi-user sau):
  Admin:  Full access + system config + Learning Queue approval
  Viewer: Read-only dashboards + alerts
```

### Real-time Updates

```
WebSocket channels:
  /ws/pipeline    → Live production status changes
  /ws/alerts      → Push critical alerts instantly
  /ws/workers     → Worker health every 10s
  /ws/learning    → New lessons/updates as they happen

Fallback: SSE (Server-Sent Events) nếu WebSocket blocked
Polling: 30s interval cho mobile khi background (save battery)
```

---

## 15. Infrastructure & Operations

### launchd .plist (mỗi Mac Mini)

```
com.omnicast.comfyui.plist        (KeepAlive=true)
com.omnicast.ollama.plist
com.omnicast.kokoro.plist
com.omnicast.rabbitmq-consumer.plist
com.omnicast.heartbeat.plist
```

### Monitoring stack

```
Master:
  Prometheus (scrape tất cả workers)
  Grafana dashboards:
    - Worker health overview
    - GPU utilization per worker
    - Queue depth & throughput
    - Thermal throttling alerts
  Alertmanager → Telegram

Workers:
  Prometheus Node Exporter (CPU, RAM, disk, temp)
  Heartbeat service → HTTP POST Master /api/heartbeat
```

### Backup

```
PostgreSQL: WAL archiving + daily pg_dump → NAS/backups/postgres/
ChromaDB:   Daily export collections → NAS/backups/chromadb/
NAS:        Synology Hyper Backup → Backblaze B2
brand_configs: git version control
DB migrations: Alembic (SQLAlchemy)
```

### Secrets Management

```
dotenv files encrypted với SOPS/age
KHÔNG hardcode API keys trong code
Network firewall:
  Workers: chỉ truy cập NAS + Master
  Master: allowlist (YouTube API, Claude API, Telegram, Google Trends)
  Dashboard: Cloudflare Access (không public internet)
```

---

## 16. Content Diversification Engine

**1 video dài (8-15 phút) → 10+ touchpoints:**

```
Long-form video (YouTube)
  ├── Auto-cut → 3-5 YouTube Shorts
  ├── Repurpose → TikTok (aspect ratio 9:16, khác hook)
  ├── Repurpose → Instagram Reels
  ├── Extract audio → Podcast (Spotify, Apple Podcasts)
  ├── Extract text + LLM rewrite → Blog post (SEO backlink)
  └── Extract quotes → Twitter/X threads

→ ROI: 1 sản phẩm → phân tán rủi ro khỏi YouTube dependency
→ Implement Phase 7+
```

---

## 17. Cron Jobs Schedule

```
*/30 * * * *   → Topic Discovery Engine (5 sources parallel)
06:00 daily    → Health Crawler (analytics, health scores)
06:30 daily    → Diagnostic Engine (rules, auto-alerts, ROI calc)
02:00 daily    → Asset Replenisher (low stock assets)
02:30 daily    → Competitor Scanner (outlier videos)
00:00 daily    → Budget Reset + Daily Report → Telegram
09:00 Monday   → Deep Diagnosis + Retention Analyst + Strategist
01:00 1st/month → Portfolio Review + KB Decay + API key rotation check
```

---

## 18. Knowledge Base Decay

```
Trend-based patterns:  > 30 ngày → decay score 50%
Evergreen patterns:    > 90 ngày → decay 50%
Unused > 60 ngày:      → auto-archive
Competitor outdated:   → flag review

→ Writer Agent chỉ học từ patterns còn fresh
→ Knowledge Base giữ relevant, không lỗi thời
```

---

## 19. Hub & Spoke Channel Strategy

### Hub Channel (1-2 per niche)

```
Video: Long-form 8-15 phút
Critic threshold: ≥ 85/100
Upload: MAX 1 video/ngày
Goal: Adsense + Sponsorship
Rule: KHÔNG BAO GIỜ dùng Hub làm guinea pig
      → Test format mới trên Spoke (canary) ít nhất 48h trước
```

### Spoke Channel (5-10 per niche)

```
Video: Shorts + 3-5 phút
Critic threshold: ≥ 70/100
Upload: MAX 3 video/ngày
Goal: Affiliate links + traffic funnel to Hub
Rule: Expendable — shadowban → abandon, tạo mới
```

### Canary Deployment

```
Format mới → test Spoke 48h → monitor CTR/retention/policy flags
OK → rollout Hub Channel
Fail → iterate Spoke → KHÔNG đụng Hub
```

---

## 20. Thị trường & Ngách ưu tiên

### Ngách Finance & Money ($15-30 RPM)

```
Crypto arbitrage, dividend investing, passive income strategies
Real estate, trading psychology, options explained
→ Advertiser spend cao nhất, evergreen content
```

### Ngách Health & Longevity ($12-20 RPM)

```
Gut health, sleep optimization, longevity supplements
Mental health explained, neuroscience for general audience
```

### Ngách Mythology & Religion ($8-15 RPM)

```
Norse/Greek/Egyptian mythology explained
Biblical prophecy, religious history, comparative religion
Japanese/Korean folklore, urban legends, yokai
→ Cao watch time → tốt cho AVD metric
```

### Ngách Psychology & Philosophy ($10-18 RPM)

```
Dark psychology, narcissism, cognitive biases
Stoicism daily, existentialism explained
```

### Ngách JP/KR Culture ($8-12 RPM)

```
Japanese history mysteries, Shinto explained
Korean history, K-drama cultural context
Visual novel / game lore (niche loyal audience)
→ Low competition, high watch time
```

---

## 21. Roadmap Implementation (Updated)

> **Trạng thái thực tế (2026-05-25):** ■ = Done, ▣ = Partial, □ = Chưa làm
> Xem chi tiết thay đổi so với thiết kế: `IMPLEMENTATION_DELTA.md`

```
Phase 0 — Compliance Foundation (Tuần 0-1) [BẮT BUỘC TRƯỚC]
  ■ Redesign Upload Pipeline → YouTube Data API v3
  ■ Bỏ ContentID bypass, chuyển 100% ACE-Step music gen
  ■ Thiết kế Error Recovery Architecture
  ■ Channel Identity Isolation Protocol
  ■ Secrets management (dotenv + SOPS)
  ■ Compliance Checker skeleton
  ■ Legal review: AI disclosure wording, FTC affiliate

Phase 1 — Core Infrastructure (Tuần 1-3) [▣ PARTIAL]
  ■ PostgreSQL + Alembic                  (src/omnicast/db/)
  ■ RabbitMQ consumer base               (src/omnicast/queue/)
  ■ Redis + rate limiter Token Bucket    (src/omnicast/cache/)
  ■ Config/Settings pydantic-settings    (src/omnicast/config/settings.py)
  ■ NAS storage abstraction              (src/omnicast/storage/)
  ■ Telegram bot alerts                  (src/omnicast/telegram/)
  ■ Circuit breaker Redis-backed         (src/omnicast/cache/circuit_breaker.py)
  ■ DryRunClient mock LLM [THÊM MỚI]    (src/omnicast/llm/fallback.py)
  □ OrbStack + Docker Compose (file có, chưa dùng production)
  □ ChromaDB + daily backup
  □ NAS mount + Synology backup
  □ Ollama + Llama 3.1 70B Workers
  □ launchd .plist tất cả services
  □ Prometheus + Grafana + Node Exporter
  □ Worker heartbeat + Standby Master setup
  □ Langfuse

  THAY ĐỔI SO VỚI THIẾT KẾ:
  + DryRunClient: mock LLM khi OMNICAST_MODE=dry_run (test không tốn API)
  + DeepSeek provider: LLMClient hỗ trợ Anthropic + DeepSeek (tiết kiệm chi phí)
  + CostCalculator: track chi phí per call, accumulate daily spend

Phase 2 — Agent Core (Tuần 3-4) [▣ PARTIAL — thiếu Media/Upload]
  ■ LLMClient: rate limiting, circuit breaker, prompt caching, cost tracking
  ■ BaseAgent pattern                    (src/omnicast/agents/base.py)
  ■ WriterAgent — scene JSON output, niche-specific injection
                                         (src/omnicast/agents/writer.py)
  ■ CriticAgent — two-stage VO/Prod split scoring
                                         (src/omnicast/agents/critic.py)
  ■ ThinkingAgent — self-critique nội bộ (src/omnicast/agents/thinking.py)
  ■ VisualDirectorAgent — fix visual/sfx only, lock VO [MỚI]
                                         (src/omnicast/agents/visual_director.py)
  ■ EvolutionAgent — combine variants, scene JSON output
                                         (src/omnicast/agents/evolution.py)
  ■ ComplianceChecker — YMYL gate        (src/omnicast/agents/compliance.py)
  ■ DebateOrchestrator — convergence + Elo tournament + two-stage routing
                                         (src/omnicast/agents/orchestrator.py)
  ■ Script models: ScriptDraft, ScriptSegment, ScriptScene, CriticFeedback
                                         (src/omnicast/models/script.py)
  ■ Budget Manager wire vào debate loop  (src/omnicast/services/budget.py)
  ■ N=3 variants + Elo tournament
  □ Audit trail logging đến PostgreSQL
  □ Prompt Version Control / canary deployment

  THAY ĐỔI SO VỚI THIẾT KẾ:
  + Script format: từ essay NARRATION → scene-based JSON (vo/visual/sfx per 3-5s scene)
  + Two-stage Critic routing: VO group / Production group tách biệt
  + VisualDirectorAgent mới: cheap DeepSeek Flash, chỉ fix visual — bảo toàn VO tốt
  + Niche-specific injection: Writer/Evolution inject SFX, broll, hook examples per niche
  + Thinking Agent: dùng DeepSeek Flash thay Haiku (rẻ hơn)
  + Compliance Checker: dùng DeepSeek Flash thay Haiku

Phase 3 — Topic Discovery Engine (Tuần 5) [⚠️ THAY ĐỔI KIẾN TRÚC LỚN]

  THAY ĐỔI: Tách thành 2 flow riêng biệt thay vì 1 flow:

  ── Flow A: Niche Discovery (HOÀN TOÀN MỚI — không có trong thiết kế gốc) ──
  ■ SeedQueryGenerator: 5 techniques (Reddit pain-point + Category-filtered trending + Trending/Broad-to-Specific/Google Trends)
  ■ NicheScanner: outlier detection, supernova signal, 90d filter, Shorts filter, langdetect, tiered breakout (T1/T2/T3)
  ■ NicheDiscovererAgent: LLM clustering, MERGE RULE, CATEGORY CAP, tiered breakout rule4
  ■ YouTubeKeyRotator: auto-rotate keys on 403/429 [THÊM MỚI]
  ■ ChannelBuilderAgent: tạo channel JSON từ niche
  ■ CLI: niche_flow.py (--scan/--list/--channels/--create)
  ■ Cache: output/niche_cache.json (niches + channels_raw)

  ── Flow B: Content Production (thiết kế gốc + mở rộng) ──
  ■ CLI: content_flow.py (--phase 1/2/3/4)
  ▣ Phase 1 Topic Discovery: DiscoveryOrchestrator + ChannelArchitectAgent
  ▣ Phase 2 Script: DebateOrchestrator (Writer ↔ Critic)
  □ Phase 3 Media: MediaPipelineOrchestrator (= Phase 4 roadmap gốc)
  □ Phase 4 Upload: UploadPipelineOrchestrator (= Phase 5 roadmap gốc)

  ── Từ Phase 3 spec gốc — CHƯA BUILD ──
  □ YouTube competitor scanner (topic discovery cho kênh đã có)
  □ Reddit scraper (PRAW)
  □ Podcast Index transcript mining
  □ News RSS
  □ Scoring pipeline → Brief Generator → RabbitMQ
  □ ChromaDB KB similarity check + decay
  □ Google Trends (pytrends) — có trong SeedQueryGenerator nhưng chưa wire vào Flow B

Phase 4 — Media Pipeline (Tuần 6-8)
  □ Kokoro-82M TTS (primary)
  □ XTTSv2 (voice cloning)
  □ SDXL + IP-Adapter FaceID Plus V2 + FaceDetailer
  □ FLUX.1 (hero shots)
  □ ACE-Step v1.5 (music gen, NO perturb)
  □ Wan 2.1 (video gen, VRAM permitting)
  □ WhisperX (subtitles)
  □ FFmpeg render + Brand Config
  □ Content Fingerprint Check (multi-modal)
  □ Asset Manager + rotation

Phase 5 — Upload Pipeline (Tuần 9-10) [REDESIGN]
  □ YouTube Data API v3 OAuth2 per channel
  □ videos.insert upload flow
  □ thumbnails.set integration
  □ Schedule publish via API
  □ A/B thumbnail swap via API
  □ Upload Scheduler (rate limiting)
  □ AdsPower warm-up only
  □ Compliance gate (mandatory before upload)

Phase 6 — Dashboard + Alerts (Tuần 11)
  □ Streamlit 7 tabs
  □ Cloudflare Tunnels + Cloudflare Access auth
  □ Telegram Bot
  □ DLQ viewer
  □ Worker health monitoring
  □ Compliance audit trail viewer

Phase 7 — Analytics Loop + Video Intelligence (Tuần 12-13)
  □ YouTube Analytics API crawler
  □ Health score + Diagnostic Engine
  □ Retention heatmap analysis
  □ Root Cause Analyst (LLM)
  □ ROI per video
  □ Strategist Agent + canary logic
  □ Content Diversification Engine (Shorts, TikTok)
  □ Knowledge Base decay system
  □ A/B test mở rộng (title, description, hook, length)
  □ Video Intelligence — competitor production analysis
  □ ProductionBlueprint generation (format, art style, pacing)

Phase 8 — Optimization (Tuần 14+)
  □ DSPy prompt optimization (Writer/Critic)
  □ Temporal.io migration (workflow orchestration)
  □ Qdrant migration (>500K vectors)
  □ FastAPI + React dashboard
  □ Chaos testing (kill Worker, verify recovery)
  □ Performance benchmarking pipeline (throughput, bottleneck)
```

---

## 22. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| YouTube Data API v3 (không Playwright upload) | ToS compliance, tránh terminate hàng loạt |
| ACE-Step v1.5, không perturb | ContentID bypass không hoạt động; AI music = safe |
| Inauthentic content checks trong Critic | YouTube policy 7/2025, protect YPP eligibility |
| Kokoro-82M thay XTTSv2 làm primary | Apache 2.0, CPU-friendly, top quality |
| ACE-Step thay AudioCraft | LoRA support, ComfyUI native, Apache 2.0 |
| Wan 2.1 thêm vào pipeline | 2026: AI video viable, nâng chất lượng đáng kể |
| WhisperX thay Whisper | Word-level alignment, subtitle không lệch sync |
| OrbStack thay Docker Desktop | Ít RAM trên Master (16GB), Apple Silicon optimized |
| 1 GCP project per channel | Quota isolation, một kênh bị block không ảnh hưởng kênh khác |
| Standby Master | SPOF mitigation cho Master Mac Mini |
| Circuit breaker → Ollama | Production không dừng khi Claude API outage |
| DLQ pattern | Không mất task khi crash, manual recovery có UI |
| Canary deployment (Spoke trước Hub) | Hub Channel không bao giờ là guinea pig |
| Knowledge Base decay | Writer học từ patterns còn fresh, không lỗi thời |
| Multi-modal content fingerprint | Tránh duplicate visual/audio cross-channel |
| Cloudflare Access cho dashboard | Dashboard không bao giờ public internet |

---

## 23. File structure dự án

```
PROJECT_CONTEXT.md     ← File này — đọc đầu tiên
omnicast_deep_analysis.md ← Phân tích kiến trúc, nguồn của v2.0
AGENTS.md              ← Rules cho AI agents

src/
├── master/
│   ├── agents/
│   │   ├── research_agent.py
│   │   ├── writer_agent.py
│   │   ├── critic_agent.py
│   │   ├── compliance_checker.py   ← MỚI
│   │   └── strategist_agent.py
│   ├── services/
│   │   ├── asset_manager.py
│   │   ├── budget_manager.py
│   │   ├── roi_tracker.py          ← MỚI
│   │   ├── topic_scorer.py
│   │   ├── upload_scheduler.py     ← MỚI
│   │   ├── circuit_breaker.py      ← MỚI
│   │   └── telegram_bot.py
│   ├── discovery/
│   │   ├── youtube_scanner.py
│   │   ├── trends_scraper.py
│   │   ├── reddit_scraper.py
│   │   ├── podcast_scraper.py
│   │   └── news_rss.py
│   ├── analytics/
│   │   ├── health_crawler.py
│   │   ├── diagnostic_engine.py
│   │   ├── retention_analyst.py    ← MỚI
│   │   ├── root_cause_analyst.py
│   │   └── competitor_benchmark.py
│   ├── upload/
│   │   └── youtube_api_uploader.py ← MỚI (thay Playwright upload)
│   └── dashboard/
│       └── dashboard.py
├── worker/
│   ├── media/
│   │   ├── tts_module.py           # Kokoro-82M + XTTSv2 + Piper
│   │   ├── image_gen_module.py     # SDXL + FLUX + IP-Adapter
│   │   ├── video_gen_module.py     ← MỚI (Wan 2.1)
│   │   ├── thumbnail_gen.py
│   │   ├── music_gen.py            # ACE-Step v1.5 (NO perturb)
│   │   ├── subtitle_module.py      # WhisperX
│   │   └── render.py
│   ├── upload/
│   │   └── warmup.py               # AdsPower warm-up only
│   └── heartbeat.py               ← MỚI
└── shared/
    ├── db.py
    ├── chromadb_client.py
    ├── rabbitmq_client.py
    ├── content_fingerprint.py     ← MỚI (multi-modal)
    ├── audit_trail.py             ← MỚI
    └── models.py
```

---

## 24. OAuth2 Token Lifecycle Management (CRITICAL)

### Vấn đề
Google OAuth2 refresh tokens có thể bị revoke bất kỳ lúc nào: user đổi password, app bị remove consent, 6 tháng inactive, hoặc Google security review. Token chết = channel ngừng upload silently.

### Token Health Monitor

```python
# Chạy mỗi 6h per channel
class TokenHealthMonitor:
    def check_all_channels():
        for channel in channels:
            token = decrypt_token(channel.oauth_token_ref)
            # 1. Verify token valid
            response = youtube.channels().list(part="id", mine=True)
            if response.status == 401:
                → Telegram CRITICAL: "Channel {name} token EXPIRED"
                → channel.status = "token_expired"
                → Pause upload queue cho channel này
                → Log re-auth URL → Dashboard "Token Management" tab
            
            # 2. Proactive refresh (trước khi expire)
            if token.expires_in < 3600:  # < 1 giờ
                new_token = refresh_oauth_token(token.refresh_token)
                encrypt_and_store(new_token)
                
            # 3. Check token scopes still valid
            if "youtube.upload" not in token.scopes:
                → Alert: scope bị thu hẹp
```

### Re-authorization Workflow

```
Token expired/revoked
  → Telegram alert + Dashboard banner
  → Generate OAuth consent URL (per channel)
  → User click → authorize → callback store new token
  → Auto-resume upload queue
  → KHÔNG auto-retry upload với token cũ (tránh rate limit ban)
```

### Token Storage

```
Encrypted storage: SOPS/age encrypted JSON per channel
Backup: Token backup trong NAS/backups/oauth/ (encrypted)
Rotation log: Mọi token refresh/re-auth đều logged (audit)
KHÔNG BAO GIỜ log token value ra Langfuse/Prometheus
```

---

## 25. GPU VRAM Scheduling & Worker Resource Management

### Vấn đề
Workers chạy nhiều model GPU-intensive đồng thời. Không có arbitration = OOM crash = pipeline halt.

### VRAM Requirements per Model

| Model | VRAM Required | Typical Duration | Priority |
|-------|---------------|------------------|----------|
| Wan 2.1 (video gen) | 16-24 GB | 5-15 min/clip | LOW (deferrable) |
| FLUX.1 (hero image) | 12-16 GB | 30-60s/image | MEDIUM |
| SDXL + IP-Adapter | 6-8 GB | 15-30s/image | HIGH (batch) |
| ACE-Step v1.5 (music) | 4-6 GB | 60-120s/track | MEDIUM |
| Kokoro-82M (TTS) | 1-2 GB (CPU ok) | 10-30s/segment | HIGH |
| WhisperX (subtitles) | 2-4 GB | 30-60s/file | HIGH |

### GPU Job Scheduler (Semaphore-based)

```python
class GPUScheduler:
    """Per-Worker GPU resource manager"""
    
    def __init__(self, total_vram_mb: int):
        self.total_vram = total_vram_mb
        self.allocated = 0
        self.queue = PriorityQueue()  # (priority, job)
        self.lock = asyncio.Lock()
    
    async def request_gpu(self, job: GPUJob) -> bool:
        """Returns True when GPU allocated, blocks if insufficient VRAM"""
        async with self.lock:
            if self.allocated + job.vram_required <= self.total_vram:
                self.allocated += job.vram_required
                return True
            else:
                # Queue job, will be released when current job finishes
                await self.queue.put((job.priority, job))
                return False  # Caller must await signal
    
    async def release_gpu(self, job: GPUJob):
        self.allocated -= job.vram_required
        # Wake next queued job if fits
        await self._try_dequeue()

# Rules:
# 1. Wan 2.1 EXCLUSIVE — khi chạy, không job GPU khác trên cùng Worker
# 2. SDXL batch có thể chạy song song Kokoro (CPU)
# 3. Nếu queue > 10 jobs, route sang Worker khác via RabbitMQ
```

### Thermal Throttling Protection

```
Worker monitor: mỗi 10s check CPU/GPU temp
> 90°C → throttle: pause GPU queue 60s, alert
> 95°C → emergency: kill non-critical GPU jobs, CRITICAL alert
Grafana dashboard: thermal history per Worker
```

### Model Loading Strategy

```
Problem: Loading/unloading models = 30-60s overhead per switch
Solution: "Model Residency" — keep most-used model loaded
  Worker 1: SDXL resident (batch images) + Kokoro (CPU)
  Worker 2: FLUX.1 resident (hero shots) + ACE-Step
  Worker N: Wan 2.1 dedicated (chỉ video gen jobs)
RabbitMQ routing: job.model_required → route tới Worker có model loaded
```

---

## 26. Dry-Run Mode & Testing Infrastructure

### Vấn đề
Không có cách test toàn bộ pipeline mà không upload thật. Mọi bug phát hiện trên production = rủi ro channel.

### Dry-Run Mode

```python
# Global flag: OMNICAST_MODE = "production" | "dry_run" | "staging"

class DryRunMode:
    """Khi enabled, thay thế mọi side-effect bằng simulation"""
    
    youtube_upload:    → Log "WOULD UPLOAD: {title} to {channel}" + save locally
    youtube_api:       → Return mock responses (cached from real API)
    telegram_alerts:   → Log to file thay vì send
    claude_api:        → Dùng cached responses hoặc Ollama (save cost)
    asset_generation:  → Chạy thật (test GPU pipeline)
    ffmpeg_render:     → Chạy thật (test output quality)
    database_writes:   → Write to staging schema (không đụng production)
```

### Integration Test Suite

```
tests/
├── unit/                    # Mỗi module riêng
├── integration/
│   ├── test_full_pipeline.py       # Topic → Render (no upload)
│   ├── test_writer_critic_loop.py  # 3 rounds debate
│   ├── test_upload_scheduler.py    # Rate limit logic
│   ├── test_circuit_breaker.py     # Failure injection
│   ├── test_token_refresh.py       # OAuth2 flow
│   └── test_gpu_scheduler.py       # VRAM contention
├── e2e/
│   ├── test_dry_run_full.py        # Full pipeline dry-run
│   └── test_disaster_recovery.py   # Kill Master, verify Standby
└── fixtures/
    ├── mock_youtube_api/            # Cached API responses
    ├── sample_scripts/              # Known-good scripts
    └── sample_media/                # Small test assets
```

### Chaos Testing (Phase 8)

```
Scenarios:
  1. Kill Worker mid-render → verify task requeue + resume
  2. NAS disconnect mid-write → verify local fallback
  3. Claude API 503 → verify circuit breaker → Ollama
  4. RabbitMQ crash → verify PostgreSQL state recovery
  5. Master crash → verify Standby promote < 5 min
  6. Token expire mid-upload → verify graceful retry
  
Tool: Custom chaos script + Prometheus alert verification
Schedule: Monthly (trước mỗi major rollout)
```

---

## 27. YMYL Compliance & Legal Protection

### Vấn đề
Finance + Health niches = "Your Money Your Life" (Google E-E-A-T). Sai factual content có thể dẫn đến lawsuit, không chỉ demonetization.

### YMYL Disclaimer Engine

```python
YMYL_NICHES = {
    "finance": {
        "disclaimers": [
            "This video is for educational purposes only and does not constitute financial advice.",
            "Always consult a qualified financial advisor before making investment decisions."
        ],
        "inject_in": ["description_top", "script_intro", "pinned_comment"],
        "required_sources": 2,  # Mỗi claim cần ≥ 2 source URLs
    },
    "health": {
        "disclaimers": [
            "This content is for informational purposes only and is not medical advice.",
            "Consult your healthcare provider before making any health-related decisions."
        ],
        "inject_in": ["description_top", "script_intro", "pinned_comment"],
        "required_sources": 3,  # Health claims cần ≥ 3 sources
    },
    "psychology": {
        "disclaimers": [
            "This video discusses psychological concepts for educational purposes only.",
            "If you're experiencing mental health issues, please seek professional help."
        ],
        "inject_in": ["description_top", "pinned_comment"],
        "required_sources": 2,
    }
}
```

### Source Attribution System

```python
class ResearchAgent:
    def research(self, topic, niche):
        findings = []
        for claim in extracted_claims:
            sources = self.find_sources(claim)
            if len(sources) < YMYL_NICHES[niche]["required_sources"]:
                claim.status = "UNVERIFIED"
                # Writer KHÔNG được dùng unverified claims
            else:
                claim.sources = sources
                claim.status = "VERIFIED"
        
        # Output: Brief với source URLs per claim
        # Writer phải include source links trong description
```

### Legal Entity Considerations (Scale Planning)

```
Khi revenue > $5K/tháng per channel cluster:
  → Cần LLC/entity riêng per cluster (liability isolation)
  → Adsense payment routing qua entity
  → Tax optimization: US LLC cho US-market channels
  → Insurance: Media liability insurance (E&O)
  → Record keeping: Mọi AI-generated content phải có audit trail
```

---

## 28. Disaster Recovery & Operational Excellence

### Disaster Recovery Plan (DRP)

```
RPO (Recovery Point Objective): 
  PostgreSQL: < 1 giờ (WAL streaming replication)
  ChromaDB:   < 24 giờ (daily backup)
  NAS assets: < 24 giờ (Hyper Backup → Backblaze B2)
  OAuth tokens: Real-time (encrypted backup on NAS + offsite)

RTO (Recovery Time Objective):
  Single Worker failure:  < 5 phút (auto-reroute)
  Master failure:         < 5 phút (Standby promote)
  NAS failure:            < 4 giờ (Backblaze B2 restore subset)
  Full site failure:      < 24 giờ (new hardware + Ansible + B2 restore)
```

### Infrastructure-as-Code (Ansible)

```yaml
# ansible/playbooks/setup_worker.yml
# Reproducible Worker setup: bare macOS → production-ready < 2 giờ
- name: Setup OmniCast Worker
  hosts: workers
  tasks:
    - name: Install Homebrew packages
      # python, ffmpeg, git, node
    - name: Install OrbStack
    - name: Pull ComfyUI container
    - name: Download models (SDXL, FLUX, IP-Adapter, Wan 2.1)
    - name: Configure launchd services
    - name: Mount NAS volumes
    - name: Install Prometheus Node Exporter
    - name: Configure heartbeat service
    - name: Run validation smoke test

# ansible/playbooks/setup_master.yml
# Master setup: PostgreSQL, RabbitMQ, Redis, Grafana, etc.
```

### Graceful Shutdown & Maintenance

```python
class MaintenanceManager:
    """Graceful shutdown for updates/maintenance"""
    
    def enter_maintenance(self, worker_id, reason):
        # 1. Stop accepting new jobs (remove from RabbitMQ consumers)
        # 2. Wait for current jobs to finish (max 30 min timeout)
        # 3. Checkpoint in-progress state to PostgreSQL
        # 4. Telegram: "Worker {id} entering maintenance: {reason}"
        # 5. Allow OS update / reboot
    
    def exit_maintenance(self, worker_id):
        # 1. Verify services healthy (ComfyUI, Ollama, heartbeat)
        # 2. Re-register as RabbitMQ consumer
        # 3. Resume queued jobs
        # 4. Telegram: "Worker {id} back online"

# Maintenance window: Tuesday 3AM local (lowest traffic)
# Auto-maintenance: macOS updates queue → apply during window
```

### Capacity Planning Model

```
Throughput estimates per Worker (M2 Pro 32GB):
  TTS (Kokoro):          ~60 segments/hour (CPU)
  Image Gen (SDXL):      ~120 images/hour (batch)
  Image Gen (FLUX):      ~30 images/hour (hero)
  Video Gen (Wan 2.1):   ~4 clips/hour (5s each)
  Music Gen (ACE-Step):  ~15 tracks/hour
  FFmpeg Render:         ~6 videos/hour (10 min each)

Bottleneck analysis:
  1 video = 15 images + 1 TTS + 1 music + 1 render
  Throughput: ~4-6 videos/Worker/day (conservative)
  
  With 2 Workers: 8-12 videos/day
  With 3 Workers: 12-18 videos/day
  
Scale trigger: Queue depth > 24h backlog → add Worker
```

### Content Lifecycle Management (Post-Upload)

```python
class ContentLifecycleManager:
    """Manage videos AFTER upload for ongoing optimization"""
    
    # Daily (7 ngày sau upload):
    def check_early_performance(self, video_id):
        if video.ctr < 1.0 and video.views < 100:
            → Consider unlist (protect channel health)
            → Telegram: "Low performer: {title}, recommend unlist?"
    
    # Weekly:
    def refresh_metadata(self, video_id):
        """Update tags/description nếu trend keywords thay đổi"""
        current_trends = get_trending_keywords(video.niche)
        if new_keywords_available:
            → videos.update API: thêm trending tags
            → Log: metadata_refresh event
    
    # Monthly:
    def manage_playlists(self, channel_id):
        """Auto-organize videos into topical playlists (SEO boost)"""
        videos = get_channel_videos(channel_id)
        clusters = cluster_by_topic(videos)
        for cluster in clusters:
            if len(cluster) >= 3:
                → Create/update playlist
    
    # Quarterly:
    def audit_old_content(self, channel_id):
        """Unlist content gây hại channel health"""
        for video in get_videos_older_than(90_days):
            if video.avg_view_percentage < 20 and video.ctr < 1.5:
                → Unlist
                → Log reason

    # End Screens & Cards:
    def update_end_screens(self, video_id):
        """Cross-promote mới nhất → cũ hơn (via API)"""
        latest_video = get_latest_published(video.channel_id)
        → Add end screen card pointing to latest_video
```

### Shadow Channel Strategy (Anti-Fragile Scaling)

```
Shadow Channels:
  - Channels tạo sẵn, warm-up 30-90 ngày (xem video, subscribe, community)
  - KHÔNG upload content (chỉ warm identity)
  - Mỗi niche duy trì 2-3 Shadow channels ready
  - Khi Spoke bị suspended → activate Shadow ngay (< 24h)
  
Warm-up protocol (AdsPower):
  Day 1-7:   Watch 5-10 videos/day trong niche
  Day 8-14:  Subscribe 10-20 channels, like videos
  Day 15-30: Comment (human-written templates), join community
  Day 31-60: Upload 1-2 test videos (low effort, gauge policy)
  Day 61-90: Ready for production activation
  
Inventory target: Always maintain ≥ 2 Shadow per active Spoke niche
```

### Prompt Version Control

```python
class PromptRegistry:
    """Version-controlled prompt management"""
    
    # Storage: PostgreSQL table
    # Schema: prompt_id, agent_name, version, content_hash, 
    #         created_at, is_active, performance_score
    
    def deploy_prompt(self, agent_name, new_prompt, strategy="canary"):
        if strategy == "canary":
            # 20% traffic dùng new prompt, 80% old
            # Monitor critic_score distribution 48h
            # If avg_score(new) >= avg_score(old) - 2: full rollout
            # Else: auto-rollback
            pass
        elif strategy == "immediate":
            # Full switch (chỉ cho hotfix)
            pass
    
    def rollback(self, agent_name, to_version):
        # Instant rollback về version cụ thể
        # Telegram: "Prompt rollback: {agent} v{new} → v{old}"
        pass
    
    # Weekly automated regression:
    # Chạy 20 sample topics qua Writer+Critic
    # Compare scores với baseline
    # Alert nếu avg_score drop > 5 points

# Git sync: Prompts ALSO stored in git repo (source of truth)
# DB = runtime cache cho fast switching
```

### Network Partition & NAS Resilience

```
NAS Mount Strategy:
  Protocol: SMB (native macOS, better than NFS for small files)
  Timeout:  soft mount, timeo=30s
  Fallback: Worker local SSD cache (256GB reserved)
  
  If NAS unreachable:
    → Write to local cache (SSD)
    → Flag files as "pending_sync"
    → When NAS returns: rsync local → NAS
    → Alert if local cache > 80% full

RabbitMQ Partition:
  Strategy: pause_minority (recommended cho 2-node)
  Quorum queues: Tất cả production queues
  
Worker ↔ Master disconnect:
  Worker continues processing local queue (max 10 jobs)
  Heartbeat failure → Worker enters "autonomous mode"
  When reconnected → sync state với Master PostgreSQL
```

### Multi-language Quality Gate

```python
class LanguageQualityGate:
    """Verify non-English content quality trước khi approve"""
    
    SUPPORTED_LANGUAGES = {
        "ja": {"model": "claude-sonnet", "checks": ["grammar", "keigo", "cultural"]},
        "ko": {"model": "claude-sonnet", "checks": ["grammar", "honorifics", "cultural"]},
    }
    
    def check(self, script, language):
        if language not in self.SUPPORTED_LANGUAGES:
            return PASS  # English = default, no extra check
        
        # Dedicated LLM call: "As a native {language} speaker, review..."
        review = llm_call(
            prompt=f"Review this {language} script for unnatural phrasing, "
                   f"cultural insensitivity, or grammar errors. "
                   f"Score 0-100 for naturalness.",
            text=script
        )
        
        if review.score < 70:
            return FAIL  # → Back to Writer for revision
        return PASS

# Cost: ~$0.01 per check (Haiku sufficient for grammar)
# Chỉ apply cho non-English content
```

### Video Intelligence — Competitor Production Analysis (Phase 7)

```
Mục tiêu: Học CÁCH đối thủ làm video, không chỉ topic gì.
Đầu vào:  Top-performing videos từ competitor_channel_ids (Discovery Phase 3)
Đầu ra:   ProductionBlueprint — feed vào Writer Agent + Media Pipeline

Phân tích per video:
  Structure Analysis:
    → YouTube transcript API → đo intro length, segment count, pacing tempo
    → Scene boundary detection (frame sampling + histogram diff)
    → Transition types inventory (cut, fade, zoom, slide)
    → Outro style + CTA placement

  Visual Style Analysis:
    → Sample N key frames → LLM describe art direction
    → Color palette extraction (dominant colors)
    → Text overlay frequency + style (font size, position, animation)
    → Detect: talking head ratio vs b-roll vs animation vs static image

  Audio Pattern Analysis:
    → Music energy curve (librosa RMS over time)
    → Voiceover pace (words/min from transcript)
    → Sound effect frequency
    → Music genre/mood classification

  Hook Pattern Analysis:
    → First 30s structure: question? shock stat? cold open? preview?
    → Correlate hook type with retention (từ Analytics Phase 7)
    → Build hook pattern library per niche

Aggregation:
  → Per-niche "winning formula" = weighted average of top 10% performers
  → Track formula drift over time (what worked 3 months ago ≠ now)
  → Seasonal adjustments (holiday content = different pacing)

Output: ProductionBlueprint
  video_format:       str   # listicle, documentary, story, explainer, comparison
  art_style:          str   # photorealistic, cinematic, anime, minimal, dark_gothic
  pacing_profile:
    scene_duration_range: tuple[float, float]
    crossfade_seconds:    float
    music_energy:         str
    text_overlay_freq:    float
    b_roll_ratio:         float
  hook_type:          str   # question, shock_stat, cold_open, preview
  intro_duration:     float
  target_duration:    int   # minutes
  color_mood:         str   # warm, cold, neutral, high_contrast

Feed targets:
  → Writer Agent: hook_type, video_format, target_duration, pacing
  → Media Pipeline: art_style, pacing_profile, color_mood
  → BrandConfig update: auto-suggest optimal settings per niche

Frequency: Weekly (cùng cycle Analytics Phase 7)
Model:     Sonnet (structure analysis) + Haiku (batch frame description)
```

### Viewer Intelligence (Phase 8+)

```
Comment Sentiment Analysis:
  → Pull comments via YouTube API (comments.list)
  → Batch sentiment analysis (Haiku, cheap)
  → Detect: audience confusion, requests, complaints
  → Feed Strategist: "Viewers asking for X" → auto-queue topic

Subscriber Cohort Tracking:
  → New vs returning viewer ratio (YouTube Analytics)
  → If returning < 30% → content not building loyal audience
  → Strategist: adjust toward series/episodic format

Audience Retention Correlation:
  → Map retention curves to script segments (WhisperX timestamps)
  → Build "engagement pattern library" per niche
  → Writer learns: "Finance audience drops at minute 7 if no new insight"
```

---

## 29. Updated File Structure (v3.1)

```
PROJECT_CONTEXT.md     ← File này — đọc đầu tiên
omnicast_deep_analysis.md ← Phân tích kiến trúc, nguồn của v2.0
AGENTS.md              ← Rules cho AI agents

src/
├── master/
│   ├── agents/
│   │   ├── research_agent.py
│   │   ├── writer_agent.py
│   │   ├── critic_agent.py
│   │   ├── compliance_checker.py
│   │   ├── strategist_agent.py
│   │   └── language_quality_gate.py    ← MỚI v3.1
│   ├── services/
│   │   ├── asset_manager.py
│   │   ├── budget_manager.py
│   │   ├── roi_tracker.py
│   │   ├── topic_scorer.py
│   │   ├── upload_scheduler.py
│   │   ├── circuit_breaker.py
│   │   ├── token_health_monitor.py     ← MỚI v3.1
│   │   ├── prompt_registry.py          ← MỚI v3.1
│   │   ├── content_lifecycle.py        ← MỚI v3.1
│   │   ├── maintenance_manager.py      ← MỚI v3.1
│   │   └── telegram_bot.py
│   ├── discovery/
│   │   ├── youtube_scanner.py
│   │   ├── trends_scraper.py
│   │   ├── reddit_scraper.py
│   │   ├── podcast_scraper.py
│   │   └── news_rss.py
│   ├── analytics/
│   │   ├── health_crawler.py
│   │   ├── diagnostic_engine.py
│   │   ├── retention_analyst.py
│   │   ├── root_cause_analyst.py
│   │   ├── competitor_benchmark.py
│   │   └── comment_sentiment.py        ← MỚI v3.1
│   ├── upload/
│   │   └── youtube_api_uploader.py
│   └── dashboard/
│       └── dashboard.py
├── worker/
│   ├── media/
│   │   ├── tts_module.py
│   │   ├── image_gen_module.py
│   │   ├── video_gen_module.py
│   │   ├── thumbnail_gen.py
│   │   ├── music_gen.py
│   │   ├── subtitle_module.py
│   │   └── render.py
│   ├── upload/
│   │   └── warmup.py
│   ├── gpu_scheduler.py                ← MỚI v3.1
│   └── heartbeat.py
├── shared/
│   ├── db.py
│   ├── chromadb_client.py
│   ├── rabbitmq_client.py
│   ├── content_fingerprint.py
│   ├── audit_trail.py
│   ├── ymyl_disclaimer.py             ← MỚI v3.1
│   └── models.py
├── infrastructure/
│   ├── ansible/                        ← MỚI v3.1
│   │   ├── playbooks/
│   │   │   ├── setup_master.yml
│   │   │   ├── setup_worker.yml
│   │   │   └── disaster_recovery.yml
│   │   └── inventory.yml
│   ├── chaos/                          ← MỚI v3.1
│   │   ├── kill_worker.py
│   │   ├── disconnect_nas.py
│   │   ├── expire_token.py
│   │   └── overload_gpu.py
│   └── monitoring/
│       ├── prometheus.yml
│       ├── grafana_dashboards/
│       └── alertmanager.yml
└── tests/                              ← MỚI v3.1
    ├── unit/
    ├── integration/
    ├── e2e/
    └── fixtures/
```

---

## 30. Updated Roadmap (v3.1 additions)

```
Phase 0-8: [Giữ nguyên như v3.0]

Phase 1 bổ sung:
  □ Ansible playbook: setup_worker.yml
  □ Dry-run mode flag + mock YouTube API
  □ GPU Scheduler skeleton (semaphore)
  □ Token Health Monitor (6h cron)

Phase 2 bổ sung:
  □ Prompt Registry (PostgreSQL + version control)
  □ YMYL Disclaimer Engine
  □ Language Quality Gate (JP/KR)

Phase 5 bổ sung:
  □ Content Lifecycle Manager (metadata refresh, playlists)
  □ Shadow Channel warm-up protocol

Phase 7 bổ sung:
  □ Comment Sentiment Analysis
  □ Viewer cohort tracking
  □ Prompt canary deployment

Phase 8 bổ sung:
  □ Chaos testing suite
  □ Full DRP drill (simulate full site failure)
  □ Capacity planning benchmark
  □ Shadow Channel inventory management
```

---

## 31. Key Design Decisions (v3.1 additions)

| Decision | Rationale |
|----------|-----------|
| Token Health Monitor mỗi 6h | Phát hiện token chết trước khi miss upload schedule |
| GPU Semaphore (không time-sharing) | Apple Silicon không hỗ trợ MPS; exclusive access = stable |
| Dry-run mode tách biệt schema DB | Test không bao giờ đụng production data |
| YMYL disclaimers inject tự động | Legal protection; quên disclaimer = liability |
| Shadow channels warm 90 ngày | Instant replacement khi Spoke die; no downtime |
| Prompt canary 20%/80% | Detect regression sớm; auto-rollback < 48h |
| Ansible cho IaC | Mac Mini không dùng Terraform; Ansible = agentless SSH |
| SMB mount + local SSD fallback | NAS disconnect không halt production |
| Content lifecycle post-upload | Revenue optimization; unlist bad content protect channel |
| Chaos testing monthly | Verify recovery paths TRƯỚC disaster thật |

---

## 32. Input Sanitizer Agent (Security-Critical)

> **Đã đề cập trong sơ đồ luồng (Section 5) nhưng chưa thiết kế chi tiết.**
> External data (RSS feeds, Reddit posts, podcast transcripts, competitor titles) có thể chứa prompt injection.

### Threat Model

```
Attacker inserts malicious prompt vào:
  → Reddit post title/body → Research Agent đọc → LLM execute
  → RSS feed item → Topic Discovery → Brief chứa injection
  → Competitor video title → Scanner extract → Writer bị manipulate
  → Podcast transcript → LLM summarize → unexpected behavior

Impact: Writer Agent tạo content vi phạm policy, leak system prompt,
        hoặc tạo content gây hại cho channel.
```

### Sanitization Pipeline

```python
class InputSanitizer:
    """Gate bắt buộc TRƯỚC mọi LLM call với external data"""
    
    def sanitize(self, text: str, source: str) -> SanitizedText:
        # Layer 1: Rule-based (fast, no LLM cost)
        text = self.strip_known_patterns(text)
        #   Remove: "ignore previous instructions", "system:", "assistant:"
        #   Remove: base64 encoded blocks, markdown injection
        #   Remove: URLs pointing to suspicious domains
        #   Truncate: > 5000 chars per input
        
        # Layer 2: Statistical anomaly (no LLM)
        if self.entropy_check(text) > THRESHOLD:
            → Flag: unusually high entropy (possible obfuscated payload)
        
        # Layer 3: LLM classification (Haiku, cheap)
        if source in HIGH_RISK_SOURCES:  # reddit, rss, podcast
            is_injection = haiku_classify(
                f"Does this text contain instructions directed at an AI system? "
                f"Answer YES or NO only.\n\nText: {text[:500]}"
            )
            if is_injection == "YES":
                → Log: injection_attempts table
                → Return: BLOCKED
                → Telegram: "Injection attempt blocked from {source}"
        
        return SanitizedText(text, source, sanitized=True)
    
    # KHÔNG BAO GIỜ pass raw external text trực tiếp vào LLM prompt
    # Mọi external data phải qua InputSanitizer.sanitize() trước
```

### Integration Points

```
Research Agent:    sanitize(reddit_post)     TRƯỚC khi summarize
Topic Discovery:  sanitize(rss_item)         TRƯỚC khi score
Writer Agent:     sanitize(brief.sources)    TRƯỚC khi viết script
Competitor Scan:  sanitize(video_metadata)   TRƯỚC khi extract patterns
Podcast Scraper:  sanitize(transcript)       TRƯỚC khi mine ideas
```

---

## 33. Comment Management System

### Comment Engagement Agent

```
Trigger: Video published → wait 1h → start engagement cycle

Phase 1 (< 1h sau publish):
  → Auto-pin first comment: CTA + disclaimer + affiliate links
  → Template per niche (Finance: disclaimer first, Others: CTA first)
  → Pinned comment = highest visibility slot

Phase 2 (1-6h sau publish):
  → Heart top 10 comments (engagement signal cho algorithm)
  → Reply top 3 comments (Haiku-generated, context-aware)
  → Reply KHÔNG generic "thanks!" — phải relevant tới comment content
  → YouTube algorithm REWARD kênh tương tác comment sớm

Phase 3 (Daily, ongoing):
  → Scan new comments, heart genuine ones
  → Hide spam (comments.setModerationStatus API)
  → Detect viewer questions → feed Topic Discovery (bonus source)
  → Track comment sentiment trend per video

YouTube API costs:
  commentThreads.list:           1 unit (read)
  comments.insert (reply):       50 units
  comments.setModerationStatus:  50 units
```

### Pinned Comment Templates

```python
PINNED_TEMPLATES = {
    "finance": (
        "⚠️ Educational only — not financial advice.\n"
        "📚 Sources in description.\n"
        "💬 What's your take? Comment below!\n"
        "🔔 Subscribe: {channel_url}"
    ),
    "health": (
        "⚠️ Not medical advice — consult your healthcare provider.\n"
        "📚 Sources cited in description.\n"
        "❤️ Found this helpful? Like & subscribe!"
    ),
    "default": (
        "💬 What do you think? Let me know below!\n"
        "🔔 Subscribe: {channel_url}\n"
        "👍 Like if you found this valuable"
    ),
}
# Quota budget: ~450 units/channel/day (4.5% of 10K quota)
```

---

## 34. Community Post Agent

### Purpose

YouTube Community tab = free push notifications to subscribers. Algorithm rewards channel activity beyond video uploads.

### Post Types & Schedule

```
Type 1: Video Preview (24h trước publish)
  → Poll: "Which interests you more? A or B"
  → Teaser image from thumbnail
  → YouTube may boost video on release

Type 2: Engagement Poll (Weekly, Wednesday)
  → "What topic should we cover next?"
  → Options from Topic Discovery candidates
  → Winner gets +20 topic score boost

Type 3: Behind-the-Scenes (48h sau publish)
  → Research stats, interesting findings không vào video
  → Drives re-engagement with published video

Type 4: Milestone (auto-triggered)
  → Subscriber milestones (1K, 5K, 10K, 50K, 100K)
  → "Thank you" posts (humanize automated channel)

Type 5: Seasonal/Event (from Content Calendar)
  → Holiday greetings, event-related polls
```

### Implementation Note

```
YouTube Community API: LIMITED availability
  → Nếu API không hỗ trợ → AdsPower + Playwright
  → Community posts = Studio interaction, KHÔNG phải video upload
  → Nằm trong allowed use case của AdsPower

Rate: MAX 2 community posts/channel/day (tránh spam perception)
```

---

## 35. SEO Optimization Engine

### Keyword Research Module

```python
class SEOOptimizer:
    def research_keywords(self, topic, niche, market):
        # Source 1: YouTube Autocomplete (free, no quota)
        suggestions = youtube_autocomplete(topic)
        
        # Source 2: Google Trends related queries
        trends = pytrends.related_queries(topic, geo=market)
        
        # Source 3: Competitor video tags (videos.list, 1 unit)
        competitor_tags = self.extract_competitor_tags(topic, niche)
        
        # Source 4: Knowledge Base (proven keywords)
        proven = kb.search_keywords(niche, market)
        
        return KeywordBundle(
            primary=topic,
            secondary=top_10_related,
            long_tail=autocomplete_phrases,
            tags=competitor_tags_deduped,
            hashtags=self.select_hashtags(niche)
        )
    
    def optimize_title(self, title, keywords):
        # Primary keyword in first 40 chars
        # Power words: How, Why, Secret, Truth, number if applicable
        # Generate 2 variants for A/B testing
        return [title_variant_a, title_variant_b]
    
    def optimize_description(self, script, keywords, niche):
        # First 150 chars = search snippet (most important)
        # Auto-generate timestamps from script segments
        # Inject affiliate links + YMYL disclaimers
        return structured_description
    
    def generate_tags(self, keywords, max=30):
        # 500 char limit, mix broad + specific + long-tail + competitor
        return tag_list
```

### Title A/B Testing

```
Thêm vào A/B Test Agent (hiện chỉ test thumbnail):

1. Publish with Title A
2. After 24h: check CTR
3. If CTR < threshold → swap to Title B (videos.update, 50 units)
4. After 48h: compare, keep winner
5. Max 1 title swap per video (tránh confuse algorithm)
```

### Hashtag Strategy

```python
HASHTAG_RULES = {
    "long_form": {"max": 3, "position": "description_bottom"},
    "shorts":    {"max": 5, "position": "title_end", "mandatory": ["#shorts"]},
}
```

---

## 36. Content Calendar & Editorial Planning

### Seasonal Revenue Calendar

```python
SEASONAL_CALENDAR = {
    "q4_holiday": {
        "period": "Nov 15 - Dec 31",
        "rpm_multiplier": 2.0,
        "action": "Production rate x2, pre-produce content tháng 10",
        "niches": {
            "finance": ["Tax planning", "Year-end investing", "Holiday budgeting"],
            "health": ["Holiday stress", "New Year resolutions", "Winter health"],
            "psychology": ["Holiday anxiety", "Family dynamics", "Gift psychology"],
        }
    },
    "q1_resolution": {
        "period": "Jan 1 - Feb 15", "rpm_multiplier": 1.3,
        "niches": {"finance": ["Budget planning"], "health": ["Weight loss", "Gym"]}
    },
    "tax_season_us": {
        "period": "Feb 1 - Apr 15", "rpm_multiplier": 1.8,
        "niches": {"finance": ["Tax tips", "Deductions", "IRS changes"]}
    },
    "back_to_school": {
        "period": "Aug 1 - Sep 15", "rpm_multiplier": 1.5,
    },
    # JP Market
    "jp_new_year":    {"period": "Dec 20 - Jan 10", "rpm_multiplier": 1.5},
    "jp_golden_week": {"period": "Apr 28 - May 6",  "rpm_multiplier": 1.2},
    "jp_obon":        {"period": "Aug 10 - Aug 16",  "rpm_multiplier": 1.3},
    # KR Market
    "kr_chuseok":     {"period": "variable", "rpm_multiplier": 1.3},
    "kr_seollal":     {"period": "variable", "rpm_multiplier": 1.3},
}

# Strategist Agent tự động:
# 4 tuần trước mùa cao điểm → tăng production rate
# Trong mùa → ưu tiên seasonal topics
# Sau mùa → giảm về normal rate
```

### Content Diversity Guard

```python
class ContentDiversityGuard:
    def check_before_queue(self, new_topic, channel_id):
        recent = get_last_n_videos(channel_id, n=10)
        
        # Rule 1: Max 2 consecutive videos cùng sub-topic
        if count_similar(new_topic, recent, threshold=0.7) >= 2:
            → DEFER topic, chọn sub-niche khác
        
        # Rule 2: Rotate formats (listicle → narrative → data-driven)
        if all_same_format(recent[:5]):
            → Force different format
        
        # Rule 3: Balance evergreen vs trending
        trending_ratio = count_trending(recent[:10]) / 10
        if trending_ratio > 0.7: → Queue evergreen next
        if trending_ratio < 0.3: → Queue trending next
```

### Series / Episodic Content Planner

```
Series benefits: loyal returning viewers + session watch time + playlist auto-play

SeriesManager:
  - Define series: title, niche, episode count, frequency
  - Auto-generate episode briefs from outline
  - Maintain narrative continuity
  - Track series vs standalone performance
  - Auto-create playlist, add episodes sequentially

Examples:
  "7 Deadly Sins of Investing" (finance, 7 episodes)
  "Gods of Olympus" (mythology, 12 episodes)
  "Brain Hacks" (psychology, ongoing weekly)
```

---

## 37. Manual Override & Human-in-the-Loop

### Dashboard Quick Actions (Tab 2 additions)

```
[+ Create Video] button → form:
  - Topic (free text, REQUIRED)
  - Channel (dropdown)
  - Priority (normal/high/urgent)
  - Skip Critic? (checkbox, requires typed reason)
  - Custom brand config overrides (optional)
  → Creates brief directly in RabbitMQ, skips Topic Discovery

[Force Approve] per video card:
  - Bypasses Critic minimum score
  - Requires typed reason (audit trail)
  - Telegram: "Manual approve by operator: {reason}"

[Boost Priority]: Move video to front of queue
[Kill]: Cancel production, release resources → DLQ
```

### Telegram Bot Extended Commands

```
NEW commands:
  /create <channel> <topic>       → Queue manual video creation
  /boost <video_id>               → Priority boost
  /skip-critic <video_id>         → Force approve (requires YES confirm)
  /pause-all                      → Emergency: pause all production
  /resume-all                     → Resume all production
  /schedule <channel> <topic> <datetime>  → Schedule specific video
  /force-upload <video_id>        → Skip scheduler, upload NOW
  /unlist <video_id>              → Unlist published video
  /reprocess <video_id>           → Re-render from last checkpoint

Safety:
  → Destructive commands require "Type YES to confirm"
  → All overrides logged in audit trail
  → Override count tracked (> 5/day = warning)
```

### Emergency Content Pipeline

```
/emergency <channel> <topic>
  → Skip Topic Discovery scoring
  → Writer: 1 variant only (no tournament)
  → Critic threshold: 60 (reduced)
  → Media: stock images only (no AI generation)
  → TTS: fastest model (Piper)
  → Render: minimal effects
  → Upload: immediate (skip scheduler)

  ETA: Topic → Published in ~90 minutes

  Safeguards:
    → Max 1 emergency/channel/day
    → Compliance checker STILL runs (non-negotiable)
    → AI disclosure STILL required
    → Label as "EMERGENCY" in audit trail
```

---

## 38. Copyright Strike & Channel Legal Health

### Strike Tracking System

```python
class StrikeTracker:
    """3 strikes = channel terminated. Must track."""
    
    def daily_check(self, channel_id):
        # YouTube API: channels.list(part="status")
        # NOTE: Strike count NOT fully available via API
        # → AdsPower check YouTube Studio "Copyright" tab periodically
        
        # Check ContentID claims
        claims = self.check_contentid_claims(channel_id)
        for claim in claims:
            if claim.type == "STRIKE":
                → Telegram CRITICAL: "⚠️ COPYRIGHT STRIKE on {channel}"
                → Pause ALL uploads for this channel
                → Auto-generate dispute if eligible
            elif claim.type == "CLAIM":
                → Telegram WARNING: "ContentID claim on {video}"
                → Log for review
    
    # DB: channel_strikes table
    # channel_id, strike_type, received_date, expires_date,
    # status, video_id, details, dispute_status
```

### Strike Alert Escalation

```
0 strikes: ✅ Healthy
1 strike:  ⚠️ WARNING — reduce upload rate 50%, review all pending content
2 strikes: 🔴 CRITICAL — pause production, manual review EVERY video
3 strikes: 💀 TERMINATED — activate Shadow channel, migrate content plan

Auto-actions:
  1 strike → Tighten Compliance Checker threshold +10 points
  2 strikes → Pause production, Telegram escalation every 6h
  3 strikes → Channel marked DEAD, Shadow activation protocol
```

### ContentID Dispute Workflow

```
Claim types & response:
  Music claim   → Verify YouTube Audio Library source → Dispute with proof
  Visual claim  → Verify AI-generated → Dispute: "original AI-generated content"
  False claim   → Auto-generate dispute template with evidence
  Valid claim   → Accept, swap asset, re-upload if possible

Dispute template:
  → Collect evidence: asset source, license, generation logs
  → Fill dispute fields
  → Present to operator for review + submit
  → Track: 30-day YouTube review window
```

---

## 39. Monetization Lifecycle Management

### YPP Eligibility Tracker

```python
class YPPTracker:
    YPP_REQUIREMENTS = {
        "subscribers": 1000,
        "watch_hours_12m": 4000,  # OR shorts_views_90d: 10M
    }
    
    def check_eligibility(self, channel_id):
        metrics = get_channel_metrics(channel_id)
        progress = {
            "subscribers": metrics.subs / 1000 * 100,
            "watch_hours": metrics.watch_hours_12m / 4000 * 100,
        }
        
        if all(v >= 100 for v in progress.values()):
            → Telegram: "🎉 Channel {name} eligible for YPP! Apply now."
            → Dashboard: "Apply for Monetization" button
        else:
            → Dashboard: progress bars per requirement
            → ETA: "At current rate, eligible in ~{days} days"
    
    # Check: daily (part of Health Crawler)
    # Dashboard: Tab 4 sub-section
```

### Revenue Source Breakdown

```python
class RevenueTracker:
    def daily_revenue(self, channel_id):
        return {
            "adsense": youtube_analytics.get_revenue(channel_id),
            "affiliate_estimated": affiliate_tracker.clicks * avg_commission,
            "sponsorship": manual_entries.get(channel_id, 0),
            "total": sum_all,
        }
    
    # Dashboard Tab 5: Pie chart revenue by source + trend over time
```

### Affiliate Link Management

```
Link rotation system:
  → Each niche has affiliate programs pool
  → Rotate links across videos (avoid single-source dependency)
  → Track click-through rate per link
  → Auto-remove underperforming affiliates
  → A/B test link placement in description

Schema:
  affiliate_programs: id, niche, provider, commission_rate,
                      link_template, status, clicks, revenue
  video_affiliates:   video_id, affiliate_id, position, clicks
```

---

## 40. Multi-platform Distribution (Phase 7+)

### Platform Adapters

```python
PLATFORMS = {
    "youtube_long": {
        "aspect": "16:9", "duration": "8-15 min",
        "api": "YouTube Data API v3",
    },
    "youtube_shorts": {
        "aspect": "9:16", "duration": "< 60s",
        "api": "YouTube Data API v3",
        "auto_cut": True,
    },
    "tiktok": {
        "aspect": "9:16", "duration": "15-180s",
        "api": "TikTok Content Posting API",
        "adapt": "Faster hook, different CTA, no end screen",
    },
    "instagram_reels": {
        "aspect": "9:16", "duration": "15-90s",
        "api": "Instagram Graph API",
        "adapt": "Visual-first, minimal text overlay",
    },
}
```

### Auto-Cut Shorts Engine

```
Input:  Long-form video (8-15 min) + retention heatmap
Output: 3-5 Shorts (< 60s each)

Algorithm:
  1. Identify retention peaks (high engagement moments)
  2. Extract segments around peaks (±30s)
  3. Vertical crop (center face/action)
  4. Large subtitles (WhisperX timestamps)
  5. Fast hook (first 3s critical for Shorts)
  6. CTA overlay: "Full video → link in bio"

Quality gate:
  → Each Short = self-contained narrative
  → No mid-sentence cuts
  → Hook works standalone
```

### Cross-platform Analytics

```
Dashboard sub-tab:
  → Revenue per platform
  → Engagement per platform
  → Cross-platform funnel: Short → Long-form conversion rate
  → Optimal posting time per platform
```

---

## 41. Channel Onboarding Workflow

### Setup Wizard (Dashboard)

```
Step 1: Channel Identity
  □ Create Google Account (manual)
  □ Create YouTube channel
  □ Set name, description, category
  □ Upload channel art + profile picture
  → Verify: channel URL accessible

Step 2: Infrastructure
  □ Create Google Cloud Project
  □ Enable YouTube Data API v3
  □ Generate OAuth2 credentials + store encrypted token
  → Verify: API test call succeeds

Step 3: Isolation
  □ Create AdsPower browser profile
  □ Assign residential proxy IP
  □ Verify IP not shared with other channels
  □ Assign dedicated email + recovery phone
  → Verify: fingerprint check passes

Step 4: Brand Config
  □ Select niche + target market
  □ Configure voice profile, colors, fonts, transitions
  □ Upload intro/outro templates
  □ Set upload schedule
  → Verify: brand_config.json validates

Step 5: Warm-up
  □ Start Shadow Channel warm-up (90-day plan)
  □ OR skip (existing/purchased channel)

Step 6: Smoke Test
  □ Dry-run: create 1 test video (no upload)
  □ Verify: all pipeline stages pass
  □ API upload test (private video)
  → Status: READY FOR PRODUCTION

Total: ~2h manual setup + 90 days warm-up
```

### Channel Setup Verification

```python
class ChannelVerifier:
    def verify(self, channel_id):
        checks = {
            "api_access": self.test_api_call(channel_id),
            "token_valid": self.test_oauth_token(channel_id),
            "ip_unique": self.verify_unique_ip(channel_id),
            "profile_unique": self.verify_adspower_profile(channel_id),
            "brand_config": self.validate_brand_config(channel_id),
            "nas_access": self.verify_nas_paths(channel_id),
            "quota_available": self.check_api_quota(channel_id),
        }
        failed = [k for k, v in checks.items() if not v]
        if failed:
            → Telegram: "Channel setup INCOMPLETE: {failed}"
            → Dashboard: red indicators
        else:
            → channel.status = "ready"
```

---

## 42. Alert Management & Anti-Fatigue System

### Alert Architecture

```python
SEVERITY_CONFIG = {
    "CRITICAL": {
        "channels": ["telegram_immediate", "dashboard_banner", "push"],
        "dedupe_window": 0,        # Always send
        "quiet_hours": False,      # Override quiet hours
    },
    "WARNING": {
        "channels": ["telegram_immediate", "dashboard"],
        "dedupe_window": 3600,     # 1h between same alert
        "quiet_hours": True,       # Queue for digest
    },
    "INFO": {
        "channels": ["dashboard", "digest_only"],
        "dedupe_window": 86400,    # 24h between same alert
        "quiet_hours": True,
    },
}

QUIET_HOURS = {
    "start": "23:00", "end": "07:00",
    "timezone": "Asia/Ho_Chi_Minh",
    "digest_time": "07:30",
}
```

### Alert Deduplication

```
Problem: "Worker 2 heartbeat failed" → 100 alerts/hour

Solution:
  fingerprint = hash(alert_type + source + severity)
  
  If same fingerprint within dedupe_window:
    → Increment counter, do NOT send
    → When resolved: "Worker 2 recovered (down 47 min, 94 alerts suppressed)"
  
  Escalation:
    → Same alert 10+ times in 1h → escalate severity one level
    → CRITICAL unresolved > 30 min → re-alert with "UNRESOLVED" prefix
```

### Daily Digest (07:30)

```
📊 OmniCast Daily Digest — {date}

🟢 System Health: {score}/100
📹 Videos: {produced} produced | {uploaded} uploaded | {failed} failed
💰 Revenue: ${revenue} | Cost: ${cost} | ROI: {roi}x

⚠️ Warnings ({count}):
• Channel fin_us: CTR dropped to 2.1%
• Worker 2: GPU temp peaked 91°C
• Asset low stock: mythology/sfx (4 remaining)

📝 Pending actions ({count}):
• Learning Queue: {n} items awaiting approval
• DLQ: {n} videos failed QC

✅ Overnight: {n} alerts suppressed, {resolved} auto-resolved
```

### Alert History (Dashboard Tab 6 sub-tab)

```
→ Timeline: all alerts, filterable by severity/source
→ Stats: alerts/day, MTTR (mean time to resolve)
→ Top alert sources (find noisy components)
→ Alert response time tracking
```

---

## 43. Knowledge Base Cold Start Strategy

### Phase 0 Seeding (trước video đầu tiên)

```python
class KBSeeder:
    def seed_initial_kb(self):
        # Source 1: Competitor Analysis (automated)
        for niche in ACTIVE_NICHES:
            top_channels = find_top_channels(niche, subs="100K-1M", count=10)
            for channel in top_channels:
                top_videos = get_top_videos(channel, sort="views", limit=20)
                for video in top_videos:
                    transcript = get_transcript(video.id)
                    patterns = extract_patterns(transcript)
                    → Store in KB with source="competitor_seed", confidence=0.5
        
        # Source 2: Curated best practices per niche
        SEED_PATTERNS = {
            "finance": [
                "Open with specific dollar amount or percentage",
                "Pattern interrupt every 60-90 seconds",
                "End with actionable takeaway",
            ],
            # ... other niches
        }
        → Bulk insert with confidence=0.5 (unvalidated)
        
        # Source 3: Universal YouTube patterns
        UNIVERSAL = [
            "First 30 seconds determine 70% of retention",
            "Thumbnail: max 3 elements, readable at mobile size",
            "Title: primary keyword in first 40 characters",
        ]
        → Insert with confidence=0.7 (well-established)
```

### Cold Start Ramp-up Timeline

```
Week 1-2: Seeded KB + conservative Writer
  → Expected Critic score: 65-75 (acceptable for Spoke)
  → Produce 2-3 videos/day on Spoke ONLY
  → Critic threshold reduced: Spoke 65 (not 70)

Week 3-4: First Learning Loop data
  → 14-20 videos published → enough for Path 3 extraction
  → First patterns from OWN production data
  → Expected improvement: +3-5 Critic points

Week 5-8: Learning Loop active
  → Path 1 (auto-rules) starts firing
  → Path 2 (weekly diagnostic) first cycle
  → Hub channel production can begin (threshold: 80, not 85)
  → Expected Critic score: 75-82

Week 9-12: Full operation
  → KB has 50+ validated patterns
  → Normal thresholds restored (Hub 85, Spoke 70)
  → All 3 Learning Paths operational

Key metric: "Time to first Hub video" = ~4-6 weeks
```

### Bootstrap Quality Guard

```
During cold start (< 20 published videos):
  → Critic threshold: Hub 80 (not 85), Spoke 65 (not 70)
  → ALL videos get manual review notification (Telegram)
  → Learning Loop Path 2 runs DAILY (not weekly)
  → Revert to normal thresholds after 20 published videos
```

---

## 44. Financial Reporting & Tax Compliance

### Monthly P&L Report

```python
class FinancialReporter:
    def monthly_report(self, month, year):
        revenue = {
            "adsense": sum_channel_revenue(),
            "affiliate": sum_affiliate_revenue(),
            "sponsorship": sum_sponsorship(),
        }
        expenses = {
            "llm_api": claude_api_spend,
            "proxy_bandwidth": proxy_cost,
            "cloud_services": gcp_cost + cloudflare_cost,
            "electricity_gpu": gpu_hours * electricity_rate,
            "nas_storage": nas_prorated,
            "hardware_depreciation": hardware_cost / 36,  # 3-year
        }
        return PnLReport(
            revenue=revenue, expenses=expenses,
            net_profit=total_revenue - total_expenses,
            per_niche=breakdown, per_channel=breakdown,
        )
    
    def export(self, report, format="csv"):
        # CSV: compatible with QuickBooks, Xero, Wave
        # PDF: human-readable summary
        → Save to NAS/reports/{year}/{month}/

# Dashboard Tab 5 additions:
#   → Monthly P&L summary
#   → [Export CSV] [Export PDF] buttons
#   → Year-to-date running total
#   → Expense categorization for tax deduction
```

### Expense Tracking

```python
# Auto-tracked (no manual entry):
#   Claude API spend (from billing/token counting)
#   GPU electricity (gpu_hours × local_rate)
#   Proxy cost (from provider API)

# Manual entry (Dashboard form):
#   Hardware purchases
#   Software licenses
#   Domain/email costs
#   Legal/accounting fees

# Schema:
# expenses: id, category, amount, currency, date,
#           description, receipt_path, tax_deductible, auto_tracked
```

---

## 45. Backup Verification & Restore Drills

### Automated Backup Integrity Check

```python
class BackupVerifier:
    """Weekly verify backups are restorable"""
    
    def weekly_verify(self):
        # PostgreSQL
        latest = find_latest("NAS/backups/postgres/")
        test_db = pg_restore(latest, target="backup_test_db")
        if verify_table_counts(test_db) < expected * 0.95:
            → CRITICAL: "PostgreSQL backup corrupt"
        drop_database("backup_test_db")
        
        # ChromaDB
        verify_collection_count("NAS/backups/chromadb/")
        
        # OAuth tokens
        for channel in channels:
            if not decrypt_test("NAS/backups/oauth/{channel_id}"):
                → WARNING: "Missing token backup for {channel}"
        
        # Log: backup_verifications table
        # Dashboard Tab 6: "Last verified restore" per component
    
    # Schedule: Every Sunday 4AM
```

### Quarterly Restore Drill

```
Full DRP drill every quarter:
  1. Spin up fresh Worker (Ansible playbook)
  2. Restore PostgreSQL from backup
  3. Restore ChromaDB from backup
  4. Restore OAuth tokens
  5. Dry-run 1 full pipeline
  6. Log drill results with timing

Pass criteria:
  → Full restore < RTO targets
  → Data loss < RPO targets
  → Pipeline functional after restore

Report: NAS/drills/{date}/
Telegram: "DRP drill {passed|failed}: RTO={actual} vs target={target}"
```

---

## 46. Updated Roadmap (v3.2 additions)

```
Phase 0-8: [Giữ nguyên từ v3.1]

Phase 1 bổ sung v3.2:
  □ Input Sanitizer Agent (security gate)
  □ Alert deduplication + quiet hours
  □ KB Cold Start seeding script

Phase 2 bổ sung v3.2:
  □ Comment Manager Agent (auto-pin, heart, reply)
  □ SEO Optimizer (keyword research, tag gen)
  □ Content Diversity Guard
  □ Channel Onboarding wizard skeleton

Phase 5 bổ sung v3.2:
  □ Community Post Agent
  □ Strike Tracker + dispute workflow
  □ YPP Eligibility Tracker
  □ Manual Override: [Create Video] + [Force Approve] buttons
  □ Telegram Bot extended commands

Phase 6 bổ sung v3.2:
  □ Alert anti-fatigue system (digest, dedup, escalation)
  □ Dashboard: alert history sub-tab
  □ Financial P&L report + export

Phase 7 bổ sung v3.2:
  □ Content Calendar (seasonal + diversity guard)
  □ Series/Episodic planner
  □ Title A/B testing
  □ Affiliate link management + rotation
  □ Auto-Cut Shorts Engine
  □ Backup verification (weekly automated)

Phase 8 bổ sung v3.2:
  □ Multi-platform upload (TikTok, Instagram Reels)
  □ Cross-platform analytics
  □ Emergency content pipeline
  □ Quarterly DRP restore drills
```

---

## 47. Updated File Structure (v3.2 additions)

```
src/
├── master/
│   ├── agents/
│   │   ├── input_sanitizer.py          ← MỚI v3.2 (SECURITY)
│   │   ├── comment_manager.py          ← MỚI v3.2
│   │   ├── community_post_agent.py     ← MỚI v3.2
│   │   └── language_quality_gate.py
│   ├── services/
│   │   ├── seo_optimizer.py            ← MỚI v3.2
│   │   ├── content_calendar.py         ← MỚI v3.2
│   │   ├── diversity_guard.py          ← MỚI v3.2
│   │   ├── series_manager.py           ← MỚI v3.2
│   │   ├── strike_tracker.py           ← MỚI v3.2
│   │   ├── ypp_tracker.py              ← MỚI v3.2
│   │   ├── affiliate_manager.py        ← MỚI v3.2
│   │   ├── alert_manager.py            ← MỚI v3.2
│   │   ├── financial_reporter.py       ← MỚI v3.2
│   │   ├── expense_tracker.py          ← MỚI v3.2
│   │   ├── backup_verifier.py          ← MỚI v3.2
│   │   ├── channel_verifier.py         ← MỚI v3.2
│   │   └── kb_seeder.py               ← MỚI v3.2
│   ├── analytics/
│   │   └── comment_sentiment.py
│   └── dashboard/
│       └── dashboard.py
├── worker/
│   ├── media/
│   │   └── shorts_cutter.py            ← MỚI v3.2
│   └── platform_adapters/              ← MỚI v3.2
│       ├── tiktok_adapter.py
│       └── instagram_adapter.py
└── shared/
    └── models.py
```

---

## 48. Key Design Decisions (v3.2 additions)

| Decision | Rationale |
|----------|-----------|
| Input Sanitizer trước MỌI LLM call | External data = untrusted; prompt injection từ Reddit/RSS có thể manipulate agents |
| Comment engagement < 1h sau publish | YouTube algorithm reward early engagement rất mạnh |
| Community posts qua AdsPower (không API) | YouTube Community API limited; Studio interaction = allowed AdsPower use |
| Title A/B test (max 1 swap) | Quá nhiều title change confuse algorithm + viewer |
| Seasonal calendar pre-produce 4 tuần trước | Q4 RPM x2 = cơ hội lớn nhất, cần content sẵn sàng |
| Manual override với audit trail bắt buộc | Operator cần can thiệp nhưng phải traceable |
| Emergency pipeline vẫn qua Compliance | Legal protection > speed; compliance non-negotiable |
| Strike tracker conservative (1 strike → 50% rate) | 3 strikes = mất kênh; quá rủi ro để tiếp tục bình thường |
| Cold start Spoke trước Hub (4-6 tuần) | Hub = asset quý, không dùng làm guinea pig khi system chưa proven |
| Alert digest thay vì real-time cho non-critical | Alert fatigue = operator ignore tất cả = miss CRITICAL |
| Weekly backup verification | Backup không test = không tồn tại; Schrodinger's backup |
| Financial export CSV compatible | Tax compliance; kế toán cần data format chuẩn |

---

## 49. Channel Quality Diagnostics & Auto-Correction (Phase 3-4)

> Mở rộng Section 12/12B. Khi channel performance suy giảm, hệ thống PHẢI tự chẩn đoán
> hỏng ở đâu trong funnel và tự sửa. Không có framework này = channel chết mà không biết tại sao.

### YouTube Performance Funnel

```
Impressions → CTR → Views → AVD → Engagement → Revenue
     ↓          ↓       ↓       ↓        ↓          ↓
  Algorithm   Thumb/   Reach  Content  CTA/Value  Monetize
  Trust       Title           Quality   Quality    Fit
```

Mỗi tầng drop = nguyên nhân khác nhau. Diagnostic Engine tìm bottleneck layer.

### Diagnostic Decision Tree

```
Impressions thấp/giảm?
├── Upload frequency giảm → Scheduler issue
├── YouTube không push → SEO/keyword sai
├── Channel bị suppress → Policy violation
└── Niche đã saturate → Competitor analysis

CTR < 4%?
├── Thumbnail xấu → Image gen quality
├── Title không hấp dẫn → Copywriting prompt
└── Mismatch audience → Topic strategy

AVD < 40%?
├── Intro chậm → First 30s retention drop
├── TTS giọng robot → Voice quality score
├── Visual nhàm chán → Transition/image variety
├── Script lan man → Content structure score
└── Audio issues → Music/voice balance

Engagement thấp (AVD OK)?
├── Thiếu CTA → Script template check
├── Content generic → Uniqueness score
└── Wrong audience → Traffic source analysis

Mọi metrics giảm đồng loạt?
├── Algorithm change → YouTube API announcements
├── Topic fatigue → Repetition rate check
└── Seasonal trend → Historical pattern match
```

### 5 Components

#### 1. ChannelHealthMonitor — Thu thập metrics

```python
class ChannelHealthMonitor:
    """Pull metrics hàng ngày từ YouTube Analytics API."""

    async def collect_channel_metrics(self, channel_id: str) -> ChannelMetrics:
        """impressions, ctr, views, avd, watch_time, subscriber_change,
        revenue, rpm, top_traffic_sources, audience_retention_curve."""

    async def collect_video_metrics(self, video_id: str) -> VideoMetrics:
        """Per-video: views_24h/48h/7d (velocity), ctr, avd, retention_curve,
        likes, comments, shares, traffic_sources breakdown."""
```

#### 2. TrendAnalyzer — Phát hiện suy giảm

```python
class TrendAnalyzer:
    """Detect declining trends qua moving averages."""

    def analyze(self, metrics: list[ChannelMetrics]) -> HealthReport:
        """7-day MA vs 30-day MA vs 90-day MA.
        Severity levels:
          HEALTHY:  stable hoặc growing
          WARNING:  7d MA < 30d MA > 15%
          CRITICAL: 7d MA < 90d MA > 30%
          DEAD:     views < threshold 14 ngày liên tục"""

    def detect_anomaly(self, metric_series: list[float]) -> list[Anomaly]:
        """Z-score anomaly detection. Flag nếu > 2σ deviation."""
```

#### 3. ContentQualityScorer — Chấm điểm pre/post-publish

```python
class ContentQualityScorer:
    """Score mỗi video trên nhiều dimensions."""

    # PRE-PUBLISH (trước upload)
    async def score_script(self, script: str) -> ScriptScore:
        """hook_strength, structure, uniqueness, readability, estimated_avd (0-10)"""

    async def score_thumbnail(self, image: bytes) -> ThumbnailScore:
        """contrast, emotion, curiosity_gap, brand_consistency, predicted_ctr (0-10)"""

    async def score_audio(self, audio_path: Path) -> AudioScore:
        """voice_naturalness, pacing, music_balance, clipping_detected (0-10)"""

    async def score_video(self, video_path: Path) -> VideoScore:
        """visual_variety, transition_quality, text_readability, technical_quality (0-10)"""

    # POST-PUBLISH (so sánh predicted vs actual)
    async def score_performance(self, video_id: str) -> PerformanceScore:
        """actual_ctr vs predicted_ctr, actual_avd vs estimated_avd,
        views_velocity vs channel_average → effectiveness delta"""
```

#### 4. DiagnosticEngine — Root cause analysis

```python
class DiagnosticEngine:
    """Kết hợp tất cả signals để chẩn đoán."""

    async def diagnose(self, channel_id: str) -> Diagnosis:
        """1. Check funnel (impressions → CTR → AVD → engagement)
        2. Find bottleneck layer (biggest drop-off)
        3. Cross-reference content scores
        4. Compare performing vs underperforming videos
        5. Pattern match với known failure modes
        Output: ranked list of probable causes với confidence score"""

    async def compare_videos(
        self, good_videos: list[str], bad_videos: list[str]
    ) -> ComparisonReport:
        """Top 10% vs bottom 10%: script, thumbnail, upload time, audio diffs.
        Isolate biến nào correlate với performance."""

    async def run_correlation(self, channel_id: str) -> dict[str, float]:
        """Pearson correlation: content scores ↔ YouTube metrics.
        Ví dụ: {'script_hook_strength ↔ avd': 0.72, 'thumbnail_contrast ↔ ctr': 0.65}"""
```

#### 5. AutoCorrector — Tự sửa + A/B test

```python
class AutoCorrector:
    """Tự động điều chỉnh pipeline dựa trên diagnosis."""

    async def apply_correction(self, diagnosis: Diagnosis) -> list[Action]:
        """Map diagnosis → actions:
        THUMBNAIL_WEAK → đổi thumbnail_style trong BrandConfig
        SCRIPT_BORING_INTRO → update script_template hook strategy
        TTS_ROBOTIC → switch voice_profile
        TOPIC_FATIGUE → expand topic_pool, cap repeat frequency
        WRONG_UPLOAD_TIME → shift schedule to peak hours"""

    async def run_ab_test(
        self,
        channel_id: str,
        variable: str,          # "thumbnail_style" | "voice_profile" | ...
        variants: list[str],
        sample_size: int = 10,  # videos per variant
    ) -> ABTestResult:
        """A/B test: 1 biến thay đổi, còn lại giữ nguyên.
        Sau sample_size videos/variant → so sánh metrics.
        Statistical significance: chi-squared / t-test."""
```

### VideoScorecard Data Model

```python
class VideoScorecard(OmnicastSchema):
    """Scorecard đầy đủ cho mỗi video — pre và post publish."""
    video_id: int
    channel_id: int
    # Pre-publish scores
    script_score: ScriptScore
    thumbnail_score: ThumbnailScore
    audio_score: AudioScore
    video_score: VideoScore
    # Post-publish metrics (YouTube)
    impressions: int
    ctr: float
    views_24h: int
    views_7d: int
    avd_seconds: float
    avd_percent: float
    retention_curve: list[float]  # % tại mỗi 10s interval
    likes: int
    comments: int
    # Diagnostic
    predicted_ctr: float
    predicted_avd: float
    ctr_delta: float   # actual - predicted
    avd_delta: float   # actual - predicted
    performance_tier: str  # "top" | "average" | "poor" | "dead"
```

### Ví dụ: Channel chết → Hệ thống chẩn đoán

```
📊 Channel: hub_finance_us
📉 Status: CRITICAL (views -45% over 30 days)

🔍 Funnel Analysis:
  Impressions:  12,000/video → 8,000/video  ↓33%
  CTR:          4.2% → 3.1%                 ↓26%  ← BOTTLENECK
  Views:        504 → 248                    ↓51%
  AVD:          42% → 38%                    ↓10%

🎯 Diagnosis (ranked by confidence):
  1. THUMBNAIL_DEGRADATION (confidence: 0.82)
     - CTR dropped most → thumbnail/title issue
     - Thumbnail contrast score: 4.2 (was 7.1 three months ago)
     - Cause: image_gen_mode changed to "dalle" (worse for finance niche)
  2. TOPIC_SATURATION (confidence: 0.64)
     - "crypto regulation" appeared 8/20 last videos
  3. TTS_QUALITY_REGRESSION (confidence: 0.45)
     - voice_profile score: 5.8 (was 7.2)

🔧 Actions:
  1. [AUTO] Switch thumbnail_style → "high_contrast_finance"
  2. [AUTO] Cap same-topic to 3/20 videos
  3. [MANUAL] Evaluate alternative voice profiles
  4. [A/B TEST] 10 videos new thumbnail style → compare CTR after 7d
```

### Closed-Loop Feedback Cycle

```
PRODUCE (Pipeline) → video uploaded
    ↓
MEASURE (YouTube Analytics API) → metrics collected (daily)
    ↓
ANALYZE (TrendAnalyzer + ContentQualityScorer) → scores + trends
    ↓
DIAGNOSE (DiagnosticEngine) → ranked root causes
    ↓
CORRECT (AutoCorrector) → A/B test / config change / alert human
    ↓
PRODUCE (Pipeline with corrections applied) → loop back
```

### Phase Dependencies

```
Phase 2: Agent Core (Writer/Critic/debate) — có video content
Phase 3: YouTube Integration (upload + analytics pull) — có data thật
Phase 4: Quality Diagnostics (scoring + diagnosis + correction + A/B) — đây
```

Không thể build Phase 4 trước Phase 2-3 vì không có production data.

---

---

## 50. Niche Vault — Persistent Niche Library + Health Monitor (IMPLEMENTED 2026-05-25)

> Flow A output (niche_flow.py) → lưu lâu dài vào SQLite → health check định kỳ bằng YouTube API.
> CLI: `python vault.py [--save|--list|--health-check|--archive]`

### Mục đích
Scan tìm được niche tốt nhưng chưa cần mở kênh ngay → lưu vào vault → check định kỳ xem niche còn sống không → khi điều kiện đúng (score cao, micro-outlier xuất hiện) → HOT alert → mở kênh.

### Files implement
| File | Vai trò |
|------|---------|
| `vault.py` | CLI entry — save/list/health-check/archive commands |
| `src/omnicast/vault/models.py` | NicheRecord, HealthLog, HealthCheckResult, NicheStatus enum |
| `src/omnicast/vault/db.py` | SQLite CRUD (WAL mode, foreign keys) |
| `src/omnicast/vault/health.py` | Health check engine — YouTube API scan |
| `src/omnicast/vault/scoring.py` | calculate_health_score() + derive_status() |
| `src/omnicast/vault/display.py` | Rich terminal UI — table + HOT panels |
| `output/vault.db` | SQLite DB (tables: niches + health_logs) |

### CLI commands
```bash
python vault.py --save <niche_id>          # lưu từ output/niche_cache.json
python vault.py --save --all               # lưu tất cả top-10
python vault.py --list                     # bảng tổng quan (trend column)
python vault.py --list --status hot        # HOT panel chi tiết
python vault.py --list --market US         # filter market
python vault.py --health-check <niche_id>  # check 1 niche
python vault.py --health-check --all       # check tất cả (skip archived/active)
python vault.py --archive <niche_id>       # archive thủ công
```

### Status state machine
```
WATCHING → HOT     : micro_outlier=True AND score ≥ 75  (không còn score ≥ 90 alone)
WATCHING → STALE   : score < 50 OR dedicated_competitors ≥ 5
* → ACTIVE         : manual (channel đã launch)
* → ARCHIVED       : manual
```

### Health check logic (per niche, ~107 YouTube API units)
1. **Evidence channels** (top 2): channels → playlistItems → videos.list (contentDetails+statistics)
   - Lookback window: **21 ngày** (tăng từ 14d — silence 21d là tín hiệu nghiêm trọng)
   - **Shorts filter**: skip videos < 120s (Shorts inflate VPD, không phải long-form signal)
2. **Competitor search**: search.list (100u, order=viewCount) → channels.list (1u)
   - Dedicated competitor = channel ≥2 appearances in top 20, subs >50k
   - **Tiered micro-outlier** (content starvation signal):
     - Tier 1: subs <10k + views ≥50k, trong top-10 kết quả
     - Tier 2: subs <50k + views ≥100k, trong top-10 kết quả
     - Tier 3: subs <100k + views ≥500k, trong top-5 kết quả
3. **Scoring** (scoring.py):
   - Base = original_score
   - Freshness decay: −2 per 30 days (max −10)
   - **Silence penalty**: No new uploads 21d: **−30** (tăng từ −10 — signal nghiêm trọng)
   - VPD ratio <0.3×: −8 | >1.2×: +5
   - 1 competitor: −8 | 3-4: −20 | ≥5: −30
   - **Micro-outlier bonus: +10** (giảm từ +25, HOT gated riêng bởi derive_status)

### Display features
- **Vault table**: 8 columns — icon | Status | Score | Trend (↑/━/↓) | Niche | Mkt | Age | Checked
- **HOT panel**: WHY HOT notes + signal trend + top breakout + `youtu.be/{video_id}` link
- **Quota warning** (trước health check): green → yellow (>50% exhausted) → red (>80% exhausted ⛔)
- **Windows UTF-8 fix**: `Console(width=120, legacy_windows=False, file=utf8_wrapped_stdout)`

### video_id flow (từ scanner → HOT panel)
`NicheScanner.scan()` lưu `video_id` trong `top_videos[]` → `NicheDiscovererAgent` giữ trong `video_lookup` → `niche_cache.json` → vault `niche_data` → `print_hot_niches()` hiển thị link.
**Cần re-scan** để cache cũ có `video_id`.

### DB schema
```sql
niches(niche_id PK, niche_name, market, status, original_score, current_health,
       saved_at, last_checked, evidence_channel_ids JSON, seed_queries JSON, niche_data JSON)
health_logs(log_id AUTOINCREMENT, niche_id FK, scan_date, new_videos_count,
            avg_new_vpd, dedicated_competitors, micro_outlier_found BOOL,
            health_score, status_change, notes)
```

---

## 51. Niche Scanner — Filter Fixes (2026-05-25)

Các bộ lọc đã thêm vào `src/omnicast/discovery/niche_scanner.py` và `niche_discoverer.py`:

| Vấn đề | Fix | Nơi |
|--------|-----|-----|
| Indian ₹ content lọt qua (Latin script) | `_NON_US_CURRENCY = frozenset("₹₦₱৳₨")` trong `_is_english_content()` | `niche_scanner.py` |
| Spanish channels pass US filter | `_is_spanish_channel()` — 25% stop-word heuristic | `niche_discoverer.py` |
| Lyrics channels (kênh lời bài hát) | `LYRICS_KEYWORDS` frozenset, filter sau gaming check | `niche_scanner.py` |
| JSON truncation (10 unicorns/chunk) | `CHUNK_SIZE = 10 → 5` | `niche_discoverer.py` |

### LLM model change (niche_flow.py)
- **Trước:** `deepseek-v4-flash` (reasoning model → burn all tokens vào `<think>` → empty JSON)
- **Sau:** `deepseek-chat` (non-reasoning V3, `settings.deepseek_chat_model`)
- Cost: ~$0.020/scan (vs $0.063 Haiku = 3× rẻ hơn)

---

## 52. Niche Pipeline — Gemini Quality Fixes (2026-05-25)

Áp dụng 9 cải tiến từ Gemini audit về 4 lỗ hổng chí mạng + 5 pipeline improvements.

### A. Scoring & Health Fixes (scoring.py + health.py)

| Vấn đề | Fix | File |
|--------|-----|------|
| HOT inflation: score ≥ 90 alone = HOT | HOT chỉ khi `micro_outlier AND score ≥ 75` | `scoring.py` |
| Silence penalty quá nhẹ (−10) | Tăng thành **−30** — abandonment = RED FLAG | `scoring.py` |
| Micro-outlier bonus quá cao (+25) | Giảm thành **+10** — HOT gated riêng | `scoring.py` |
| Shorts inflate VPD signal | Fetch `contentDetails+statistics`, skip < 120s | `health.py` |
| Micro-outlier bất kỳ channel nhỏ nào trong top 20 | Tiered (Tier 1/2/3) + position top-K only | `health.py` |
| Lookback 14d quá ngắn | **21 ngày** — silence 21d là tín hiệu nghiêm trọng | `health.py` |

### B. Discovery Fixes (niche_scanner.py + niche_discoverer.py)

| Vấn đề | Fix | File |
|--------|-----|------|
| Over-segmentation (Dog×2, Fitness×5) | MERGE RULE + CATEGORY CAP prompt | `niche_discoverer.py` |
| RPM hard filter ≥ 10 loại sử history | Giảm ngưỡng xuống **≥ 8** (history rpm=7-8) | `niche_discoverer.py` |
| French/Indonesian lọt qua Latin check | `langdetect` probabilistic — P(en) ≥ 80% | `niche_scanner.py` |
| Gold mines bị lọc (subs 10k-100k) | **Tiered breakout**: T1 <10k+10x, T2 <50k+15x, T3 <100k+20x | `niche_scanner.py` |
| rule4 unicorn detection cho T2/T3 | `rule4 = is_breakout AND breakout_tier ≥ 2` | `niche_discoverer.py` |

### C. Seed Generator Enhancements (seed_generator.py)

| Kỹ thuật | Mô tả | Khi nào chạy |
|---------|-------|-------------|
| **Reddit pain-point hijack** | Top posts từ r/personalfinance, r/DIY, r/psychology, r/Dogtraining (no API key) → LLM convert → YouTube queries | Parallel với trending |
| **Category-filtered trending** | YouTube trending filtered to category 26=Howto, 27=Education, 28=Science&Tech (high-RPM categories) | Parallel với trending |
| **Parallel enrichment** | Cat-filtered + Reddit + Trending chạy song song → merge dedup → richer seed pool | Mặc định (Technique 1) |

### Tiered breakout constants
```python
# niche_scanner.py
BREAKOUT_T1_SUBS=10_000  BREAKOUT_T1_OUTLIER=10.0  BREAKOUT_T1_VIEWS=50_000
BREAKOUT_T2_SUBS=50_000  BREAKOUT_T2_OUTLIER=15.0
BREAKOUT_T3_SUBS=100_000 BREAKOUT_T3_OUTLIER=20.0

# health.py (for health check competitor scan)
_BREAKOUT_T2_SUBS_MAX=50_000   _BREAKOUT_T2_MIN_VIEWS=100_000
_BREAKOUT_T3_SUBS_MAX=100_000  _BREAKOUT_T3_MIN_VIEWS=500_000
_BREAKOUT_T3_TOP_K=5
```

## 53. Script Quality Rework + Storage Chain Fix (2026-05-26)

### Script Format — Scene-Based JSON (thay thế essay NARRATION)

```
CŨ (broken):  Writer xuất essay text dài với [HOOK:] [VISUAL:] tags
              → Critic không thấy visual quality
              → AI video tools phải parse tay

MỚI (đúng):  Writer + Evolution xuất list ScriptScene per segment
              → Mỗi scene = 3-5 giây screen cut
              → vo, visual, sfx riêng biệt
              → AI video tools (InVideo, HeyGen) dùng trực tiếp

ScriptScene {
  voiceover:     str        # MAX 25 words, natural speech
  visual_prompt: str        # filmable stock query (subject + action + context)
  sfx:           str | None # niche SFX | whoosh | ting | null
  duration_s:    float      # ước tính giây
}
```

### Two-Stage Critic Architecture

```
VO GROUP (70 điểm):
  hook_quality:         25  (bold statement, NOT rhetorical question)
  anti_ai_cliche:       15  (blacklist 50+ banned phrases)
  retention_structure:  10  (pattern interrupts, natural open loops)
  human_editorial:      10  (unique insight, not pure AI regurgitation)
  niche_compliance:      5  (YMYL, fatal rules per niche)
  pacing_compliance:     5  (≤25 words/scene — VO problem not visual)

PRODUCTION GROUP (30 điểm):
  visual_concreteness:  25  (specific + filmable = searchable on Pexels)
  sfx_appropriateness:   5  (SFX timing matches VO key moments)

ROUTING (sau mỗi Critic round):
  VO < 53              → Writer.revise()      → fix VO text
  VO ≥ 53, PROD < 23   → VisualDirectorAgent  → fix visual/sfx ONLY
  total ≥ threshold    → APPROVED

VisualDirectorAgent (src/omnicast/agents/visual_director.py):
  → Model: DeepSeek Flash (cơ học, không cần reasoning sâu)
  → Input: list scenes với vo_locked field
  → Output: visual_prompt + sfx mới cho mỗi scene
  → VO text KHÔNG BAO GIỜ bị thay đổi
  → Safe fallback: nếu parse fail → trả draft gốc
```

### Niche-Specific Injection

```python
# Mỗi niche inject vào Writer + Evolution prompt:
NicheConfig {
  sfx_primary:    str   # e.g. "alarm" (finance), "heartbeat" (health)
  sfx_secondary:  str   # e.g. "cash-register", "whoosh"
  broll_style:    str   # "stock market charts, Wall Street footage"
  insider_angle:  str   # tone per niche ("trusted financial friend")
  proof_sources:  list  # where to cite: "Federal Reserve", "CDC"
}

# Critic cũng nhận NicheConfig → check fatal rules per niche
```

### Storage Chain — Niche → Channel → Script → Video

```
CHAIN ĐẦY ĐỦ (đã fix):

[niche_flow.py --scan]
  → output/niche_cache.json  (temporary scan results)

[vault.py --save <id>]  ← optional step
  → output/vault.db → niches table (status: watching/hot)

[niche_flow.py --create <id>]
  → channels/<channel_id>.json
    {
      "channel_id": "fin_retirement_us",
      "source_niche_id": "perimenopause_health",  ← MỚI: link back to niche
      ...
    }
  → vault.db: niche status → ACTIVE, niche_data["channel_id"] stored  ← MỚI

[content_flow.py --channel <id>]
  → output/runs/{channel_id}/{timestamp}/...
  → vault.db → scripts table
    {
      "script_id":  "fin_retirement_us_20260526_120000",
      "channel_id": "fin_retirement_us",   ← link to channel
      "youtube_video_id": null → "dQw4w9WgXcQ"  ← updated after upload
    }

TRUY VẾT ĐẦY ĐỦ:
  vault.db/niches.niche_id  →  channels/*.json["source_niche_id"]
                            →  vault.db/scripts.channel_id
                            →  vault.db/scripts.youtube_video_id

GAP VẪN CÒN:
  □ scripts.source_niche_id chưa có (channel_id đủ để join)
  □ PostgreSQL (production) chưa mirror vault.db (Phase 6+)
```

### Files Changed (2026-05-26)

```
MODIFIED:
  src/omnicast/agents/writer.py          ← scene JSON, niche injection, VO prohibition
  src/omnicast/agents/evolution.py       ← scene JSON, VO prohibition
  src/omnicast/agents/critic.py          ← two-stage VO/Prod scoring, 8 dimensions
  src/omnicast/agents/orchestrator.py    ← two-stage routing, VisualDirectorAgent
  src/omnicast/models/script.py          ← ScriptScene model, CriticFeedback VO/Prod fields
  src/omnicast/vault/db.py               ← add mark_niche_activated()
  niche_flow.py                          ← source_niche_id in channel JSON, vault sync
  content_flow.py                        ← VisualDirectorAgent wired (llm_flash)
  run_pipeline.py                        ← VisualDirectorAgent wired (llm_flash)
  tests/unit/test_critic.py              ← updated to VO_DIMS/PROD_DIMS imports
  tests/unit/test_writer.py              ← fixed angle constant

NEW:
  src/omnicast/agents/visual_director.py ← VisualDirectorAgent (DeepSeek Flash)
```

---

*Version: 4.0.0 — Last updated: 2026-07-22*
*v3.3 additions: Channel Quality Diagnostics & Auto-Correction (Section 49)*
*v3.4 additions: Niche Vault + Health Monitor (Section 50), Scanner filter fixes + deepseek-chat (Section 51)*
*v3.5 additions: Gemini quality fixes — scoring rework, Shorts filter, tiered breakout, seed enrichment (Section 52)*
*v3.6 additions: Scene-based script format, Two-stage Critic (VO/Prod split), VisualDirectorAgent, Storage chain fix (Section 53)*
*v4.0 additions: Current Runtime Truth (Section 0), unit-first narrative flow, bounded
self-improvement, fail-closed release gates, cross-video memory và hospital pass.*

**Quy tắc cập nhật context:**
Sau mỗi phiên có thay đổi code/kiến trúc đáng kể → AI agent PHẢI cập nhật file này (thêm section mới hoặc sửa section liên quan) + cập nhật memory files tại `C:\Users\Tailolicon\.claude\projects\E--Project-OmniCast-Engine\memory\`. Không được để context lỗi thời qua nhiều phiên.
