# BỐI CẢNH — Đối chiếu OmniCast reup vs pyvideotrans

Bạn là research agent cho **OmniCast Engine** (`E:\Project\OmniCast Engine`).
Chúng tôi đã port pipeline reup Douyin (zh→vi) từ `_refs/Tool_Reup_Douyin` vào
`implementation/src/omnicast/reup/`, và dùng `_refs/pyvideotrans` làm chuẩn tham chiếu
cho phần căn tốc độ. Thực tế chạy cho thấy **chúng tôi đã tự chế nhiều chỗ đáng ra
nên lấy nguyên của pyvideotrans**, và mỗi chỗ tự chế đều đẻ ra bug thật.

## Bug ĐÃ tìm ra (để bạn biết loại lỗi cần soi)

1. ASR gọi `model.transcribe()` chỉ với 4 tham số, để mặc định hết. pyvideotrans truyền
   `condition_on_previous_text=False`, VAD `min_silence_duration_ms=140`, `threshold=0.5`,
   `no_speech_threshold`. Hậu quả: VAD mặc định 2000ms cắt mất 2 phút 13 giây audio
   trên video 9 phút 44 giây, và người dùng báo **mất câu thoại**.
2. `build_align_plan` cho mỗi ô thời gian chạy từ đầu câu này tới đầu câu sau, nhưng
   **không ô nào phủ đoạn trước câu đầu tiên** — mất 6,1 giây mở đầu của video.

Cả hai đều là loại lỗi "đáng ra không phát sinh nếu bám pyvideotrans". Hãy tìm những
lỗi CÙNG LOẠI mà chúng tôi chưa phát hiện.

## Nhiệm vụ

ĐỌC CODE THẬT của `_refs\pyvideotrans` (KHÔNG đoán từ README hay docs; nhiều comment
tiếng Trung — vẫn phải đọc, dịch ý chính) và đối chiếu với code OmniCast được giao:

- **Bỏ sót**: pyvideotrans có bước / tham số / guard mà ta không có.
- **Chế cháo**: ta tự viết khác trong khi pyvideotrans đã có cách làm chín hơn.
- **Sai lệch âm thầm**: cùng ý tưởng nhưng hằng số / thứ tự / điều kiện khác nên ra
  kết quả khác, không ai báo lỗi.

## Định dạng report BẮT BUỘC

Mỗi phát hiện là một mục:

### [MỨC] Tiêu đề ngắn
- **pyvideotrans**: `file.py:line` — nó làm gì, hằng số và tham số cụ thể.
- **OmniCast**: `file.py:line` — ta làm gì.
- **Hậu quả thực tế**: triệu chứng người dùng sẽ thấy, cụ thể, không nói chung chung.
- **Cách vá**: nhỏ nhất có thể, nêu rõ sửa file nào.

MỨC = CRITICAL (mất dữ liệu hoặc hỏng output) | MAJOR (chất lượng tệ thấy rõ) |
MINOR (tinh chỉnh).

Sắp xếp theo mức, CRITICAL trước. **Không bịa `file:line`** — chưa mở file kiểm chứng
thì ghi thẳng "chưa xác minh". Bỏ qua mọi thứ không ảnh hưởng chất lượng output cuối.
Viết tiếng Việt.
