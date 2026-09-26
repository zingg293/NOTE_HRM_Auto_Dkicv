# NOTE HRM – Tool tự động đăng ký kế hoạch công việc

## Mục tiêu
Ứng dụng Windows có giao diện để:
1. Nhập nhiều tài khoản + mật khẩu.
2. Gán 1 file Excel cho từng tài khoản.
3. Nhấn **RUN** để chạy lần lượt.
4. Đọc sheet `Kế hoạch công việc cá nhân`.
5. Kiểm tra ngày thực hiện trong Excel phải nằm trong quý 3/2026 và trong khoảng ngày đã nhập.
6. Đăng nhập `https://notehrm.vn/`.
7. Vào `Công việc → Đăng ký → Thêm`.
8. Điền:
   - Ngày bắt đầu phiếu: mặc định `01/07/2026`, cho phép sửa trong giao diện.
   - Ngày kết thúc phiếu: mặc định `30/09/2026`, cho phép sửa trong giao diện.
   - Tên kế hoạch: `Kế hoạch công việc quý 3`
   - Nội dung: `Kế hoạch công việc quý 3`
9. Dán bảng B:I từ Excel vào bảng chi tiết.
10. Tìm/chọn mã công việc theo tên công việc.
11. Đặt hạn hoàn thành toàn bộ dòng theo ô trong giao diện (mặc định `30/09/2026`).
12. Lưu.
13. Nếu lỗi hoặc không tìm thấy mã công việc: dừng toàn bộ hàng đợi và báo dòng/tài khoản/lỗi.

## Lưu ý quan trọng
- Tool **không lưu mật khẩu** ra file.
- Tool không tự vượt CAPTCHA/OTP. Nếu xuất hiện, tool dừng và báo cần xử lý thủ công.
- Nên chạy ở chế độ hiện trình duyệt trong giai đoạn kiểm thử.
- Trước khi chạy thật nên thử 1 tài khoản + 1 file nhỏ.
- Nếu giao diện NOTE thay đổi, các hàm locator trong `notehrm_adapter.py` là nơi cần chỉnh.

## File Excel mẫu hiện tại
File mẫu người dùng cung cấp có:
- Sheet chính: `Kế hoạch công việc cá nhân`
- Dòng tiêu đề bảng chi tiết: dòng 14
- Dữ liệu bắt đầu: dòng 15
- Các cột cần dùng:
  - B: Ngày thực hiện
  - C: Mã công việc
  - D: Tên công việc
  - E: Hệ số SPC
  - F: Số lượng giao
  - G: Số lượng giao quy đổi
  - H: Thời hạn hoàn thành
  - I: Mô tả công việc

### Kiểm tra ngày trước khi chạy
Nhập ba ô ngày theo dạng `DD/MM/YYYY`. Ngày bắt đầu phiếu phải không muộn hơn
ngày thực hiện của bất kỳ dòng Excel nào; hạn hoàn thành phải không sớm hơn
ngày thực hiện và phải nằm trong khoảng ngày bắt đầu/kết thúc phiếu.
Quy tắc riêng của file Excel vẫn yêu cầu **Ngày thực hiện** trong `01/07/2026–30/09/2026`.
Nếu có lỗi, tool báo trước khi đăng nhập bất kỳ tài khoản nào.

## Chạy bằng Python
PowerShell:
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
python main.py
```

## Đóng gói EXE
Trong thư mục chứa `main.py`, mở CMD và chạy:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

### Cập nhật bản sửa trên máy Windows
1. Đóng ứng dụng NOTE_HRM_Auto_Register.exe đang chạy (nếu đang nhập dữ liệu,
   nhấn **DỪNG** trước). Giải nén toàn bộ ZIP mới vào một thư mục nguồn; hoặc
   chép đè `notehrm_adapter.py` và `build.ps1` vào thư mục cũ chứa `main.py`.
2. Mở CMD tại thư mục nguồn và chạy lệnh build phía trên. `build.ps1` tự cài
   các thư viện trong `requirements.txt`, Chromium tương ứng và đóng gói EXE.
3. Chỉ chạy `dist\NOTE_HRM_Auto_Register.exe` được tạo sau thông báo
   `Build complete`. EXE cũ không tự nhận thay đổi trong tệp Python.
4. Kiểm tra phiếu đã lưu trên NOTE HRM trước khi chạy lại cùng Excel để tránh
   tạo trùng. Nếu build báo EXE đang chạy, đóng cửa sổ ứng dụng rồi build lại.

Sau khi chọn mã công việc, NOTE HRM có thể đóng danh mục trước khi cập nhật
ô trong bảng. Bản này chờ tối đa 15 giây để cả mã và tên xuất hiện đúng dòng,
và báo giá trị thực tế nếu NOTE HRM không cập nhật.

Sau khi build, file dự kiến:
`dist\NOTE_HRM_Auto_Register.exe`

Build script cài Chromium vào `%LOCALAPPDATA%\ms-playwright`; EXE tìm browser
ở đúng thư mục này thay vì thư mục tạm của PyInstaller. Khi chuyển EXE sang
máy Windows khác, máy đó cũng cần cài phiên bản Chromium phù hợp với phiên bản
Playwright của bộ mã nguồn. Mật khẩu được che trên giao diện và chỉ giữ trong
bộ nhớ trong phiên chạy.

## Quy trình sử dụng bản EXE
1. Mở EXE và kiểm tra ba ô ngày ở đầu cửa sổ; chỉnh nếu cần.
2. Nhập tài khoản, mật khẩu, chọn Excel cho từng dòng.
3. Nhấn **Kiểm tra Excel**, sau đó **RUN**.
4. Tool chạy lần lượt. Nếu một tài khoản lỗi, hàng đợi dừng; kiểm tra
   phiếu trên NOTE HRM trước khi chạy lại để tránh tạo trùng.

## Cơ chế matching mã công việc
- Ưu tiên tên công việc khớp chính xác.
- Nếu không có tên khớp chính xác, so tên Excel với cột **Công việc chi tiết**
  trong danh mục bằng `rapidfuzz` và chọn ứng viên gần nhất.
- Chỉ tự chọn theo Công việc chi tiết khi điểm tương đồng đủ cao và chênh lệch
  với ứng viên thứ 2 đủ rõ.
- Nếu không chắc chắn hoặc không có ứng viên, dừng để tránh chọn sai mã.
- Sau khi chọn trên danh mục, nếu NOTE chưa ghi mã vào dòng, tool nhập chính
  mã đã xác nhận vào ô rồi rời ô để NOTE tự tra cứu lại tên và hệ số SPC.
