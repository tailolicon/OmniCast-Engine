# OmniCast Mobile

App Android theo dõi & điều khiển OmniCast Engine từ điện thoại. Giao diện OmniCast Neon (kawaii pastel / neon-night), cùng token + font + icon với `implementation/frontend_v2`.

## Tính năng

| Tab | Chức năng | API |
|-----|-----------|-----|
| Tổng quan | KPI, chi tiêu ngày, hoạt động gần đây, **kill-switch pause/resume** | `/api/status`, `/api/system/state`, `/api/system/pause\|resume` |
| Kênh | Danh sách kênh + stats, **chạy/hủy pipeline**, xem live log | `/api/channels/overview`, `/api/run/{id}`, `/api/run/{id}/cancel`, `/api/run/{id}/log` |
| Duyệt | Duyệt/từ chối video chờ đăng (badge số lượng trên tab) | `/api/approvals`, `/api/approvals/{id}/{decision}` |
| Chi phí | Tổng chi + hạn mức + progress bar | `/api/budgets`, `/api/usage` |
| Cài đặt | Địa chỉ server (LAN), test kết nối, light/dark |  |

## Stack

Vite 8 + React 19 + TypeScript + Tailwind 4 + TanStack Query + **Capacitor 7** (project Android thật trong `android/`).

## Chạy dev

```bash
cd mobile
npm install
npm run dev        # vite dev, proxy /api → 127.0.0.1:8765
```

## Dùng ngay trên điện thoại (không cần APK)

Backend đã mount bản build tại **`/m`**:

1. PC: `cd implementation && python run_backend.py --host 0.0.0.0` (port 8767)
2. Điện thoại cùng Wi-Fi: mở `http://<IP-của-PC>:8767/m`
3. Chrome menu → **Thêm vào Màn hình chính** → chạy như app.

Cập nhật bản `/m` sau khi sửa code:

```bash
npm run build
# copy dist → implementation/src/omnicast/api/webui_mobile
```

## Build APK

Cần Android SDK (script cài tự động đặt tại `E:\Android\Sdk`, ghi vào `android/local.properties`).

```bash
npm run build
npx cap sync android
cd android
.\gradlew.bat assembleDebug
# APK: android/app/build/outputs/apk/debug/app-debug.apk
adb install app/build/outputs/apk/debug/app-debug.apk
```

Lần đầu mở app: vào tab **Cài đặt** → nhập `http://<IP-của-PC>:8767` → Lưu & kiểm tra.

## Ghi chú bảo mật

- App gọi backend qua **HTTP cleartext trong LAN** (`usesCleartextTraffic=true` + `androidScheme: http`). Chỉ dùng trong mạng nhà. Nếu expose ra ngoài Internet → bắt buộc đặt reverse proxy HTTPS (Caddy/Tailscale) và tắt cleartext.
- Backend không có auth — không mở port 8767 ra WAN.
