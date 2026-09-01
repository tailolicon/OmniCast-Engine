# Script Farm — sinh script trên cloud, không cần laptop

Repo này chính là orchestrator (mô hình học từ `tailolicon/hachimi-tl-vi`): queue, claim,
brief kênh, script và validation đều sống trong Git. **Worker là chính model AI đang chat**
(ChatGPT qua GitHub tooling/Codex cloud, hoặc bất kỳ assistant nào ghi được GitHub) — không
API key, không máy cá nhân.

## Dùng thế nào

Một câu duy nhất cho ChatGPT:

> Run `tailolicon/OmniCast-Engine/scriptfarm/WORKER_START.md` from `main`.

Hoặc gộp luôn đề bài (enqueue + draft trong một phiên):

> Sinh script cho `money_blueprint_us`: "Why your 401k loses to inflation" — run
> `tailolicon/OmniCast-Engine/scriptfarm/WORKER_START.md` from `main`.

Worker sẽ: đọc queue → claim → nạp `channels/<id>/SYSTEM.md` + `TASK.md` (render tự động từ
prompt builder thật của pipeline) → tự viết script đúng `FORMAT.md` → commit
`scripts/<channel>/<item>/script.md` + `result.json` → cập nhật queue → nhả claim. GitHub
Actions (`validate-scriptfarm.yml`) chấm cấu trúc trên mỗi push.

## Laptop nhận script khi render

```bash
git pull
OMNICAST_SCRIPT_FARM=1  # thêm vào .env hoặc export trước khi chạy pipeline
```

Bước script của pipeline sẽ tìm draft `drafted`/`approved` khớp đúng channel+topic, parse
bằng chính `WriterAgent._parse_draft`, chấm lại bằng critic local rồi đi tiếp render như
thường — mọi quality gate hạ nguồn giữ nguyên. Không có draft khớp thì pipeline tự viết như
cũ.

## Cấu trúc

```
scriptfarm/
  WORKER_START.md      # giao thức worker (điểm vào duy nhất)
  FORMAT.md            # contract định dạng script + checklist CI
  queue.json           # hàng đợi đề tài
  claims/              # khoá lạc quan: 1 file = 1 claim
  channels/<id>/       # SYSTEM.md + TASK.md + meta.json (GENERATED — đừng sửa tay,
                       #   chạy implementation/scripts/gen_scriptfarm_templates.py)
  scripts/<ch>/<item>/ # script.md + result.json do worker commit
  tools/validate_script.py
```
