# Dataset clone giọng Việt từ TTS của CapCut

> STATUS: ACTIVE (2026-08-08) — sinh dataset qua **CapCut editor API** (lệnh `api`).
> Đường cũ "ghi vào draft rồi bấm trong app" vẫn còn trong tool nhưng **BLOCKED**,
> giữ lại làm phương án dự phòng; xem §Đường draft (blocked).

3 giọng mục tiêu (tab **Vietnamese** trong CapCut):

| slug | giọng CapCut | `voice_type` | ghi chú |
|---|---|---|---|
| `co_gai_hoat_ngon` | Cô Gái Hoạt Ngôn | `BV074_streaming` | nữ trẻ, hoạt ngôn — giọng chính |
| `nguon_nho_ngot_ngao` | Nhỏ Ngọt Ngào | `BV421_vivn_streaming` | nữ ngọt, nhãn **Free** trong app |
| `thanh_nien_tu_tin` | Thanh Niên Tự Tin | `BV075_streaming` | nam trẻ |

`BV074`/`BV075` chính là 2 id đã có sẵn trong `media/capcut_voices.py` (trước chỉ
ghi "Vietnamese Female/Male"); `Voice.json` của SDK cho biết tên hiển thị thật.

## Đường đang dùng: CapCut editor API

```bash
python scripts/capcut_clone_dataset.py api --voice co_gai_hoat_ngon
```

Một lệnh, không cần mở CapCut. Với mỗi câu: tạo TTS task → poll tới `succeed` →
tải mp3 từ CDN → ffmpeg cắt lặng + mono 24kHz 16-bit → `wav/001.wav`… → sinh
`train.list` + `metadata.csv` + `qc_report.txt`. Chạy lại chỉ bù file còn thiếu
(dùng `--overwrite` nếu muốn làm lại hết).

SDK nằm ở `_refs/capcut-tts-api` (read-only): ký request + mã hoá payload RSA
thuần Python, định danh thiết bị trong `config.py`, không cần đăng nhập.

> **Hai cái bẫy đã xử lý.** `CapCutClient.generate_speech()` của SDK **luôn timeout**:
> nó chờ status `"success"` trong khi API trả `"succeed"` — `synthesize_one()` trong
> tool tự poll nên không dính. Và `speech_url` nằm trong `payload`, vốn là một chuỗi
> JSON lồng trong JSON, phải decode hai lần.

> Dùng endpoint này và dùng output để train model clone là chuyện điều khoản của
> CapCut. Đây là quyết định của bạn; tool chỉ lo phần kỹ thuật.

## Fine-tune từ dataset này

Dataset sinh ra ở đây là hàng lý tưởng để fine-tune: một speaker, thu từ TTS nên
sạch tuyệt đối, transcript đúng 100% không cần ASR, prosody nhất quán.

| Đường | Chất lượng | License base | Chạy được ở đâu |
|---|---|---|---|
| **F5-TTS** + `hynt/F5-TTS-Vietnamese-ViVoice` (1000h) | cao nhất | ❌ **CC-BY-NC-SA-4.0** — cấm thương mại, ShareAlike lây sang model con | Colab T4 16GB |
| **Piper VITS** + `vi_VN-vais1000-medium` | thấp hơn | ✅ **CC-BY-4.0** — thương mại OK | máy local, 4GB VRAM đủ |

Đã kiểm tra cả 4 base F5 tiếng Việt trên HuggingFace (`hynt`, `nst1511`,
`ngoctan91`, `yukiakai`) — **tất cả đều non-commercial**. OmniCast là hệ thống
kiếm tiền, nên với giọng dùng cho kênh thật thì phải đi đường Piper.

```bash
python scripts/capcut_clone_dataset.py export-f5    --voice co_gai_hoat_ngon   # zip ~92MB cho Colab
python scripts/capcut_clone_dataset.py export-piper --voice co_gai_hoat_ngon   # 22.05kHz cho piper train
```

Notebook Colab: [`notebooks/F5TTS_Vietnamese_Finetune_Colab.ipynb`](../notebooks/F5TTS_Vietnamese_Finetune_Colab.ipynb).
Ba chỗ nó cố ý lệch khỏi `fine_tuning.sh` của tác giả:

* **Bỏ stage 2–3 (mở rộng vocab + embedding).** Hai stage đó dành cho đường đi từ
  base Emilia zh/en sang tiếng Việt; ta xuất phát từ base đã là tiếng Việt. Đã
  kiểm chứng: vocab base 2566 token phủ đủ 95 ký tự của corpus, thiếu 0. Notebook
  vẫn kiểm lại điều kiện này trước khi bỏ qua.
* **Warmup 20 000 → 200 update.** Con số gốc dành cho bộ 1000 giờ; giữ nguyên thì
  train xong vẫn chưa thoát giai đoạn khởi động.
* **Tạo alias `data/<name>_char`.** F5 gốc tìm dataset ở đường đó, fork này ghi vào
  `data/<name>`; alias để cả hai cách đều thấy, khỏi đoán fork đã sửa hay chưa.

## Kịch bản

`assets/voice_clone/vi_full_corpus.txt` — **517 câu**, không trùng, ghép từ:

* `vi_200_lines.txt` (200 câu) — phủ 6 thanh điệu, vần khó, chữ số/ngày tháng,
  câu hỏi, cảm thán, hội thoại trợ lý ảo, địa danh/tên riêng.
* `vi_extra_300_lines.txt` (317 câu) — câu dài (trung bình 108 ký tự), thiên về
  văn kể chuyện, tin tức, tài chính, hội thoại đời thường và lời dẫn video, khớp
  với luồng reup Douyin zh→vi.

**200 dòng đầu giữ nguyên thứ tự** so với file gốc, nên chỉ số wav ổn định và lần
chạy sau chỉ sinh phần còn thiếu. Văn bản trong file **chính là transcript**,
không cần ASR.

Kết quả thực tế mỗi giọng: **517/517 clip, 35.6–37.1 phút, 0 thiếu, 0 QC-flag.**

## Các đường khác tới cùng bộ giọng

* **Volcengine / Doubao seed-tts** (`media/providers/tts_volcengine.py`) — đường
  chính chủ ByteDance, cùng họ engine, nhưng catalog speaker là zh/en đọc tiếng
  Việt qua `explicit_language=crosslingual`, **không phải đúng 3 giọng này**.
* **Endpoint nội bộ TikTok** (`.../media/api/text/speech/invoke/` +
  `text_speaker=` + cookie session của một tài khoản thật) — phải mượn session
  người dùng nên rủi ro khoá tài khoản; `media/capcut_voices.py` cố ý chỉ liệt kê
  speaker id chứ không gọi. Endpoint mà tool này dùng là **editor API của app
  desktop** (`editor-api-sg.capcutapi.com`), không mượn session ai cả.

## Đường draft (blocked) — hiện trạng CapCut 9.1.0.3879, tài khoản Pro

Đã chạy thật trên máy, không phải suy đoán:

* **Chạy được:** `draft` sinh project, CapCut mở đúng, 200 câu hiện đủ và đúng thứ tự
  trên track text, không kéo theo media của template.
* **Đã sửa 1 bug thật:** mọi segment do `write_draft` sinh ra dùng chung một
  `sticker_animation` trong `extra_material_refs`. CapCut coi clip đó là chưa đủ hình
  hài và báo *"This text does not support text-to-speech"*. Bản vá cho mỗi clip một
  material riêng ([draft.py](../src/omnicast/reup/capcut/draft.py)) làm lỗi đó biến mất
  — luồng dub của WS8 reup cũng dính bug này.
* **Vẫn chặn:** sau khi vá, chọn giọng xong nút *Generate speech* sáng và CapCut còn
  hiện `Estimated credits needed 0 / Credits left 650`, nhưng bấm thì **không có gì xảy
  ra** — không track audio, không tiến trình, `materials.audios` vẫn rỗng. Đúng như vậy
  với cả 1 clip lẫn 40 clip, và với cả giọng Free (*Nguồn nhỏ ngọt ngào*) lẫn giọng
  badge xanh.
* **Quan sát phụ:** riêng 2 giọng badge xanh (*Cô Gái Hoạt Ngôn*, *Thanh niên Tự Tin*)
  còn hiện lại thông báo *"This text does not support text-to-speech"* và **không** hiện
  dòng credits — có thể là vấn đề gói (Pro vs Ultra), nhưng chưa kết luận được vì giọng
  Free cũng không sinh ra audio.
* **CapCut crash 3 lần** trong phiên (log: `User Data/Log/VECrashHandler_*.log`), 2 lần
  ở thao tác thêm text mặc định — không liên quan draft của ta. Vì vậy `--parts 5`
  (40 câu/draft) là mặc định nên dùng.

### Việc cần làm để gỡ chặn

Thiếu đúng một mẫu đối chứng: **một text clip do chính CapCut tạo ra và đã chạy TTS thành công**.

1. Trong CapCut mở một project bất kỳ, Text → Default text → gõ một câu tiếng Việt.
2. Chọn clip đó → Text to speech → *Nguồn nhỏ ngọt ngào* → Generate → đợi ra audio → `Ctrl+S`.
3. Chạy so sánh:

```bash
python scripts/capcut_clone_dataset.py diffref --draft "<tên project vừa làm>"
```

Diff sẽ chỉ ra field nào CapCut đặt trên text material/segment mà `write_draft` chưa
đặt. Vá field đó vào `draft.py` là mở được toàn bộ đường dây.

### Cách chạy đường draft (nếu API chết)

15 draft đã dựng sẵn (`VC_<slug>_p1..p5`, 40 câu mỗi cái). Dựng lại:

```bash
python scripts/capcut_clone_dataset.py draft --voice co_gai_hoat_ngon --parts 5 --force
```

Trong CapCut, **lặp cho từng draft**: mở project → click track text → `Ctrl+A` →
Text to speech → tab Vietnamese → chọn giọng → Generate → đợi tải xong → `Ctrl+S`.

Rồi rút audio ra:

```bash
python scripts/capcut_clone_dataset.py collect --voice co_gai_hoat_ngon
```

`collect` sẽ: đọc `draft_content.json` → khớp audio với câu theo vị trí trên
timeline → ffmpeg cắt lặng 2 đầu (chừa 60ms), mono 24kHz 16-bit → ghi
`wav/001.wav`…`200.wav` → sinh nhãn → in QC.

Chạy lại `collect` bao nhiêu lần cũng được: chỉ file nào mới hơn bản đã convert
mới bị ghi đè, nên sửa vài clip trong CapCut rồi collect lại là đủ.

## Kết quả mỗi giọng

```
output/voice_clone/<slug>/
├── plan.json        # draft nào chứa câu nào
├── wav/001.wav …    # mono 24kHz, đã trim
├── train.list       # GPT-SoVITS: path|speaker|vi|text
├── metadata.csv     # F5-TTS: audio_file|text
└── qc_report.txt
```

## Đọc QC

* **thiếu** — câu chưa có audio. CapCut sinh thiếu, chọn lại đúng clip đó và
  generate bù, rồi `collect` lại.
* **cần nghe lại** — clip có thời lượng lệch so với độ dài chữ (<28 hoặc >150
  ms/ký-tự). Thường là CapCut đọc nhầm dòng, cắt cụt, hoặc dính 2 câu.

Trước khi train, nghe ngẫu nhiên 10–20 file đối chiếu transcript. Mốc đủ tốt:
≥190/200 clip, tổng ≥30 phút.

## Nếu CapCut nghẹn với 200 clip

Chia nhỏ thành nhiều draft:

```bash
python scripts/capcut_clone_dataset.py draft --voice co_gai_hoat_ngon --parts 4 --force
```

`collect` tự gom lại theo `plan.json`, đánh số liên tục 001–200.

Nếu CapCut **không mở được** draft (do đã gỡ track media của template), dựng lại
với `--keep-media`.
