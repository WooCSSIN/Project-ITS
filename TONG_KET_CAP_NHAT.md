# Báo cáo Cập nhật & Sửa lỗi Dự án ITS (Smart Transportation System)
*Ngày cập nhật: 29/06/2026*

Dưới đây là tổng hợp toàn bộ các vấn đề đã được giải quyết và các cải tiến đã được áp dụng vào dự án trong phiên làm việc vừa qua. Tập trung chủ yếu vào việc tối ưu hóa giao diện Quản trị viên (Admin) và sửa các lỗi kết nối môi trường.

---

## 1. Tối ưu hóa xác thực quyền Admin (Authentication Refactoring)
**Vấn đề:** 
Trước đây, mỗi trang admin (`AdminResourcesPage`, `AdminRoadsPage`) đều tự động gọi API `/auth/me` một cách độc lập để kiểm tra quyền truy cập. Điều này dẫn đến việc gọi API trùng lặp thừa thãi và gây ra lỗi hiển thị (hoặc văng ứng dụng) ở nhiều nơi khi token hết hạn.

**Giải pháp đã triển khai:**
- **Tạo hook dùng chung `useAdminGuard.ts`**: Gom toàn bộ logic kiểm tra token, xác thực quyền (`role_id === 0`) và xử lý lỗi vào một nơi duy nhất.
- **Refactor các trang Admin**: Cập nhật `AdminResourcesPage` và `AdminRoadsPage` để sử dụng hook này. Giúp code ngắn gọn hơn, hiệu năng tốt hơn (chỉ gọi API 1 lần) và hiển thị thông báo lỗi đồng nhất, đẹp mắt khi người dùng không có quyền truy cập.

---

## 2. Sửa lỗi không cập nhật UI khi Start/Stop tiến trình Camera
**Vấn đề:** 
Trong trang **Quản lý tuyến đường** (`AdminRoadsPage`), khi Admin bấm nút "Dừng" (Stop) hoặc "Khởi động lại" (Start) luồng camera AI, giao diện không cập nhật trạng thái ngay lập tức mà phải đợi đến chu kỳ quét 8 giây tiếp theo của hệ thống.

**Giải pháp đã triển khai:**
- Bổ sung logic tự động làm mới giao diện ngay lập tức khi API phản hồi thành công.
- Thêm cơ chế **Delay Refresh (2 giây)**: Hệ thống sẽ tự động gọi lại API một lần nữa sau 2 giây để đảm bảo trạng thái thực tế của Docker container (đang khởi động/đang tắt) được đồng bộ chính xác 100% lên màn hình giao diện.

---

## 3. Khắc phục lỗi kết nối API khi chạy Local (Lỗi cấu hình Frontend)
**Vấn đề:** 
Người dùng bị báo "Lỗi kết nối tới server" và không thể đăng nhập do giao diện frontend chạy ở cổng `5173` (Vite Server) tự động gửi request đến chính nó thay vì gửi đến Backend (cổng `8000`). Nguyên nhân do biến môi trường `VITE_API_HTTP_BASE` bị bỏ trống.

**Giải pháp đã triển khai:**
- **Cập nhật `config.ts`**: Bổ sung cơ chế Fallback (dự phòng) thông minh. Nếu ứng dụng đang chạy ở môi trường phát triển (cổng `5173`) và không có biến môi trường nào được cài đặt, hệ thống sẽ tự động điều hướng tất cả các API requests về `http://localhost:8000` và WebSocket về `ws://localhost:8000`.
- Thiết lập này đảm bảo hệ thống hoạt động trơn tru cả khi chạy qua Docker Nginx (cổng 80) lẫn khi dev code cục bộ (cổng 5173).

---

## 4. Phục hồi và Cấp quyền Tài khoản Quản trị viên
**Vấn đề:** 
Không thể truy cập vào các trang Admin do thiếu tài khoản có quyền `role_id = 0`, và gặp lỗi sai cấu trúc mã băm mật khẩu (Hash Error) khi thao tác qua command line.

**Giải pháp đã triển khai:**
- Tạo các Script nội bộ (`create_admin.py`, `reset_pass.py`) để tương tác trực tiếp với Database PostgreSQL qua ORM của SQLAlchemy.
- Khôi phục thành công mật khẩu mặc định (`Admin@123`) cho tài khoản Quản trị viên hiện có (`bilunnguyen4747@gmail.com`).

---

## 5. Dọn dẹp Code thừa
- Xóa bỏ trang `AdminViolationsPage` (Quản lý vi phạm) theo đúng yêu cầu hủy bỏ tính năng xử phạt của hệ thống.
- Làm sạch các Sidebar Navigation và Routing liên quan trong `AdminLayout.tsx` và `App.tsx` để giữ hệ thống gọn gàng, tập trung hoàn toàn vào chức năng đếm xe và ước tính vận tốc.
