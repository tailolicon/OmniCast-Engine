# Plans

## Active

| Task | 内容 | DoD | Depends | Status |
| --- | --- | --- | --- | --- |
| 1.1 | Tạo class EZFFMPEG (Builder Pattern) trong `media/render_engine.py` | Có class hỗ trợ add_video, add_audio, generate_filter_complex | - | cc:完了 [c53d100] |
| 1.2 | Viết Unit Test cho EZFFMPEG | Test case xuất ra string filter_complex hợp lệ | 1.1 | cc:完了 [c53d100] |
| 1.3 | Thay thế mock logic trong `media/ffmpeg.py` | `ffmpeg.py` sử dụng EZFFMPEG để sinh lệnh render thực tế | 1.1, 1.2 | cc:完了 [c53d100] |

## Archive
(Empty)
