# TỔNG QUAN KIẾN TRÚC HỆ THỐNG - SMART TRANSPORTATION SYSTEM (ITS)

Tài liệu này cung cấp cái nhìn toàn cảnh về kiến trúc, các thành phần công nghệ và các chức năng đã được xây dựng trong dự án Hệ thống Giao thông Thông minh (ITS).

---

## 1. MỤC TIÊU DỰ ÁN
Phát triển một hệ thống giám sát và phân tích lưu lượng giao thông theo thời gian thực ứng dụng Trí tuệ Nhân tạo (AI). Hệ thống có khả năng nhận diện phương tiện, đếm số lượng, ước tính vận tốc và cung cấp giao diện quản trị, giám sát trực quan cùng với một trợ lý ảo (Chatbot) hỗ trợ truy vấn thông tin.

---

## 2. PHÂN CHIA CƠ CẤU VÀ CÔNG NGHỆ (TECH STACK)

Hệ thống được thiết kế theo mô hình **Microservices/Containerized**, chia thành 3 lớp chính:

### A. Lớp Giao diện (Frontend Application)
- **Công nghệ**: ReactJS, TypeScript, Vite, Tailwind CSS.
- **Nhiệm vụ**: Tương tác trực tiếp với người dùng, hiển thị luồng video (WebRTC), bản đồ, biểu đồ thống kê và giao diện chat.
- **Các module chính**:
  - `Trang Chủ (Dashboard)`: Trình chiếu video trực tiếp (Livestream) từ các điểm cầu, kết hợp vẽ hộp nhận diện (Bounding Box) do AI phân tích.
  - `Trợ lý ảo (Chatbot)`: Giao diện trò chuyện thời gian thực qua WebSocket, cho phép người dùng hỏi đáp về dữ liệu giao thông.
  - `Trang Quản trị (Admin Panel)`: Khu vực dành riêng cho người quản lý để theo dõi tài nguyên server (CPU, RAM) và trạng thái các luồng camera/tuyến đường. Bắt buộc kiểm tra quyền truy cập (Role-based access).

### B. Lớp Xử lý Trung tâm (Backend API & Services)
- **Công nghệ**: Python, FastAPI, SQLAlchemy, WebRTC (aiortc).
- **Nhiệm vụ**: Cầu nối giao tiếp, xử lý logic nghiệp vụ, quản lý luồng dữ liệu video và luồng trí tuệ nhân tạo.
- **Các module chính**:
  - `API Server (FastAPI)`: Cung cấp RESTful API cho xác thực người dùng, lấy lịch sử, quản trị hệ thống.
  - `WebRTC Streaming`: Máy chủ truyền phát video độ trễ thấp, kết nối Peer-to-Peer với Frontend.
  - `Inference Server (AI)`: Tích hợp YOLO (Nhận diện phương tiện) và BotSORT (Theo dõi đa đối tượng - Tracking). Xử lý dữ liệu song song hoặc theo lô (Batch Inference) để tối ưu phần cứng (GPU/CPU).
  - `Background Workers`: Các tiến trình chạy ngầm phân tích tốc độ, đếm lưu lượng, và dọn dẹp bộ nhớ (Traffic History Worker, Violation Worker).
  - `LLM Agent`: Tích hợp mô hình ngôn ngữ lớn (Langchain / Llama) để trả lời câu hỏi của người dùng dựa trên cơ sở dữ liệu giao thông hiện hành.

### C. Lớp Lưu trữ & Hạ tầng (Data & Infrastructure)
- **Công nghệ**: PostgreSQL, Redis, MinIO, Docker Compose, Nginx.
- **Phân bổ**:
  - `PostgreSQL`: Lưu trữ dữ liệu quan hệ, thông tin người dùng, lịch sử chat, và dữ liệu cấu hình tuyến đường.
  - `Redis`: Đóng vai trò là Message Broker (Pub/Sub) truyền tải frame ảnh giữa các service, quản lý hàng đợi AI (Inference Queue), và Cache truy xuất nhanh.
  - `MinIO`: Máy chủ Object Storage (tương tự AWS S3) dùng để lưu trữ video, hình ảnh (ví dụ: ảnh bằng chứng vi phạm, ảnh avatar).
  - `Nginx`: Reverse Proxy chịu trách nhiệm định tuyến (routing) request tới Frontend (port 80) hoặc Backend (port 8000).

---

## 3. TỔNG HỢP CÁC CHỨC NĂNG ĐÃ HOÀN THIỆN

### Phía Frontend (Client-side)
1. **Hệ thống Đăng nhập / Phân quyền**: Đăng nhập bằng JWT, bảo mật các trang Admin thông qua custom hook `useAdminGuard`, tự động chuyển hướng khi hết hạn phiên đăng nhập.
2. **Giao diện Giám sát Giao thông**: Kết nối luồng video độ trễ thấp. Bật/tắt các lớp hiển thị (hiển thị tốc độ, đếm xe, hộp nhận diện).
3. **Biểu đồ thời gian thực (Charts)**: Theo dõi sự biến động của mật độ giao thông theo từng khung giờ.
4. **Chatbot thông minh**: Hỗ trợ markdown, cuộn tự động, và hiển thị trạng thái đang soạn tin (typing).
5. **Giao diện Admin**:
   - *Quản lý Tài nguyên*: Xem dung lượng CPU, RAM, ổ cứng (System Metrics) trực tiếp từ server.
   - *Quản lý Tuyến đường*: Liệt kê các luồng camera, trạng thái WebRTC, có khả năng Tắt (Stop) / Bật (Start) tiến trình AI của từng đường một cách độc lập để tiết kiệm tài nguyên.

### Phía Backend (Server-side)
1. **Kiến trúc Pipeline AI**: Đã tối ưu hóa luồng đọc Video -> Đẩy vào Redis -> Kéo ra Inference (Nhận diện/Tracking) -> Trả về Frontend.
2. **Đếm xe & Đo tốc độ**: Sử dụng thuật toán Polygon (Đa giác) vùng không gian để đếm số lượng xe chạy qua và quy đổi tọa độ 2D ra vận tốc ước tính dựa trên khoảng cách khung hình.
3. **Quản lý Tài khoản Admin**: Xây dựng script cấp quyền/reset mật khẩu qua môi trường Docker một cách an toàn.
4. **Khắc phục môi trường (Dockerization)**: 100% các dịch vụ (DB, Redis, API, Frontend, AI) đều được đóng gói thành Container, cấu hình proxy chung (Nginx) giúp triển khai hệ thống (deploy) chỉ bằng 1 lệnh.

---

## 4. ĐỊNH HƯỚNG / LƯU Ý PHÁT TRIỂN TIẾP THEO
- Hệ thống xử phạt (Violations) đã được dọn dẹp và ẩn đi để tập trung vào luồng tính năng lõi (Monitoring & Chatbot).
- Nếu cần chạy trên môi trường thực tế quy mô lớn, cần trang bị thêm máy chủ có GPU để Inference Server xử lý đa luồng (Multi-stream) mượt mà hơn (hiện tại có thể giới hạn FPS nếu chạy thuần CPU).
