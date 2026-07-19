# Tạo 3 kênh YouTube — checklist thủ công (15–20 phút/kênh)

> AI **không thể** tự tạo tài khoản Google (vi phạm ToS Google, cần xác minh
> SĐT). Ba channel config đã sẵn sàng — làm theo checklist này cho từng kênh,
> điền `youtube_channel_id`, authorize OAuth là pipeline chạy được ngay.

## Kênh cần tạo

| channel_id | Tên kênh | Niche | Style | Config |
|---|---|---|---|---|
| `money_blueprint_us` | The Money Blueprint | Personal finance (RPM $15–30) | `footage` — 90% stock B-roll | `money_blueprint_us.json` |
| `forgotten_chronicles_us` | Forgotten Chronicles | History storytelling (RPM $6–14) | `storytelling` — ảnh AI Flow/Imagen | `forgotten_chronicles_us.json` |
| `true_dread_files_us` | True Dread Files | True scary stories (AVD cao) | `horror_real` — chỉ ảnh/footage thật | `true_dread_files_us.json` |

## Checklist mỗi kênh

1. **Tạo Google account** (hoặc dùng account có sẵn + Brand Account):
   - youtube.com → avatar → *Create a channel* → chọn **Use a business or other name** (Brand Account — 1 Google account quản được nhiều brand channel, KHÔNG cần 3 account riêng).
   - Đặt tên đúng theo bảng trên.
2. **Lấy channel ID**: YouTube Studio → Settings → Channel → Advanced settings → copy `UC...` id.
3. **Điền vào config**: mở `channels/<channel_id>.json`, set `"youtube_channel_id": "UC..."` và `"channel_created_at": "<ISO date hôm nay>"` (ChannelGuard dùng để giới hạn velocity kênh trẻ: 3 video/tuần).
4. **OAuth upload + analytics** (mỗi brand channel 1 lần):
   ```
   python scripts/youtube_authorize.py --channel <channel_id> --analytics
   ```
   Khi Google hỏi chọn account → **chọn đúng brand channel** (không chọn account gốc).
5. **Lưu credentials mã hoá** (email/password/channel id — Fernet vào vault.db, không plaintext):
   ```
   python scripts/store_channel_credentials.py --channel <channel_id> --email <email> --youtube-channel-id UC... --channel-name "<tên>"
   ```
   Cần `OMNICAST_CREDENTIAL_FERNET_KEY` trong `.env` (script tự hướng dẫn generate nếu thiếu).
6. **Verify**: `curl http://127.0.0.1:8767/api/channels/refresh-stats` → kênh phải `linked: true`.

## Sau khi đủ 3 kênh

- Chạy video đầu: qua WebUI Xưởng hoặc `python content_flow.py --channel <channel_id>`.
- Analytics thật: `POST /api/analytics/<channel_id>/collect` (cần token có `--analytics`).
- Lưu ý kênh mới: bật được kiếm tiền cần 1.000 subs + 4.000h watch time (YPP) — revenue trong analytics sẽ = 0 tới lúc đó (HealthScorer đã tự loại metric này khỏi điểm).
