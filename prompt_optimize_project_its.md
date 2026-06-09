# Prompt: Tối ưu hệ thống giám sát giao thông thông minh (Project-ITS)

---

## 🧠 Vai trò của AI

Bạn là một **Senior AI/Computer Vision Engineer** với chuyên môn sâu về:
- Object detection và multi-object tracking trong giao thông thực tế
- Tối ưu hoá inference pipeline cho hệ thống real-time
- Kiến trúc backend xử lý đa luồng và đa camera
- Triển khai mô hình AI trên phần cứng hạn chế (edge/embedded)

---

## 📦 Bối cảnh dự án

**Tên dự án:** Project-ITS — Hệ Thống Giao Thông Thông Minh  
**Nguồn:** https://github.com/WooCSSIN/Project-ITS  
**Mục tiêu:** Giám sát giao thông thời gian thực — nhận diện, theo dõi phương tiện và **ước tính tốc độ** qua camera IP tĩnh, triển khai tại Việt Nam.

### Tech stack hiện tại

| Thành phần       | Công nghệ                                          |
|------------------|----------------------------------------------------|
| Object detection | YOLO (phiên bản chưa xác định rõ)                 |
| Tracking         | ByteTrack                                          |
| Backend          | FastAPI, Python 3.11, multiprocessing              |
| Frontend         | React + TypeScript + Vite                          |
| Streaming        | WebSocket + WebRTC                                 |
| Cache / Queue    | Redis                                              |
| Database         | PostgreSQL 16                                      |
| Object storage   | MinIO (lưu frame snapshot)                         |
| AI chatbot       | LangGraph ReAct Agent                              |
| Tối ưu model     | INT8 OpenVINO, TensorRT, torch-pruning             |
| Containerisation | Docker + Docker Compose                            |

### Hiệu năng hiện tại (theo README)

| Chế độ     | FPS phát hiện | Camera đồng thời | CPU host  |
|------------|---------------|------------------|-----------|
| CPU only   | 5–8 FPS       | 1–2 (lag)        | 90–100%   |
| GPU (RTX 3050) | 25–30 FPS  | 3–5 (mượt)       | 10–15%    |

---

## ⚠️ Vấn đề và điểm yếu đã xác định

### 1. Mô hình detection (YOLO)
- FPS trên CPU quá thấp (5–8 FPS) — không đáp ứng real-time nếu không có GPU
- Chưa rõ đã fine-tune cho xe máy mật độ cao (đặc thù giao thông Việt Nam) hay chưa
- Mất detection khi phương tiện bị che khuất (occlusion) ở giao lộ đông
- Không tối ưu cho AMD GPU hoặc Apple Silicon

### 2. Tracking (ByteTrack)
- ID switching khi hai xe giao nhau → tính tốc độ bị sai tại điểm chuyển tiếp
- Không dùng appearance feature → khó phân biệt xe cùng màu, cùng loại đi sát nhau
- Khi YOLO miss detection nhiều frame liên tiếp → ByteTrack tạo ID mới → đếm xe sai

### 3. Ước tính tốc độ
- Chưa có mô tả rõ về phương pháp calibrate camera (pixel → mét thực)
- FPS không ổn định khi xử lý 3–5 camera đồng thời → công thức v = Δd/Δt bị ảnh hưởng
- Không có cơ chế làm mượt (smoothing) tốc độ → số nhảy loạn khi tracking không ổn định

### 4. Hệ thống tổng thể
- Multi-camera dùng Python multiprocessing — dễ bottleneck ở IPC (Inter-Process Communication) khi nhiều camera
- Snapshot lưu MinIO nhưng chưa rõ chiến lược retention / cleanup
- Không có cơ chế alert khi phương tiện vượt tốc độ (chỉ hiển thị dashboard)

---

## 🎯 Mục tiêu tối ưu (ưu tiên theo thứ tự)

### Ưu tiên 1 — Độ chính xác tốc độ
Cải thiện độ chính xác ước tính tốc độ phương tiện. Yêu cầu:
- Sai số mục tiêu: ±5 km/h so với tốc độ thực
- Ổn định trên nhiều điều kiện: ban ngày, ban đêm, mưa, mật độ cao

### Ưu tiên 2 — Hiệu năng CPU mode
Cải thiện FPS khi chạy không có GPU để hỗ trợ triển khai chi phí thấp:
- Mục tiêu: ≥15 FPS/camera trên CPU hiện đại
- Hỗ trợ ít nhất 2 camera đồng thời mà không lag

### Ưu tiên 3 — Độ ổn định tracking
Giảm ID switch rate, đặc biệt tại giao lộ đông phương tiện và điểm xe vào/ra khung hình.

### Ưu tiên 4 — Khả năng mở rộng
Hỗ trợ ≥8 camera đồng thời trên một server GPU tầm trung (RTX 3060 trở lên).

---

## 📋 Yêu cầu đầu ra từ AI

Hãy phân tích và đưa ra **kế hoạch tối ưu chi tiết** bao gồm các mục sau:

### Phần 1: Tối ưu mô hình detection
- Đề xuất phiên bản YOLO tốt nhất cho bài toán này (YOLOv8n/s/m, YOLOv9, YOLOv10, YOLOv11...)
- Chiến lược fine-tune với dataset giao thông Việt Nam (xe máy mật độ cao, điều kiện ánh sáng đa dạng)
- Kỹ thuật augmentation phù hợp (mosaic, mixup, random crop...)
- Cách áp dụng SAHI (Slicing Aided Hyper Inference) nếu cần phát hiện xe nhỏ từ xa
- Cấu hình tối ưu cho INT8 quantization với OpenVINO và TensorRT

### Phần 2: Cải thiện tracking
- Có nên giữ ByteTrack hay chuyển sang BoT-SORT / OC-SORT / StrongSORT không? Lý do?
- Cách cấu hình tham số ByteTrack (track_thresh, track_buffer, match_thresh) tối ưu cho giao thông đông
- Có cần thêm ReID module không? Nếu có, module nào nhẹ và phù hợp?

### Phần 3: Phương pháp ước tính tốc độ chính xác
- Quy trình calibrate camera cụ thể (homography matrix, perspective transform)
- Công thức tính tốc độ từ trajectory của ByteTrack (với FPS không ổn định)
- Kỹ thuật smoothing tốc độ (Kalman filter, exponential moving average...)
- Cách validate tốc độ tính được (ground truth collection)

### Phần 4: Tối ưu pipeline xử lý
- Có nên chuyển từ Python multiprocessing sang async/threading không?
- Cách tối ưu batch inference khi có nhiều camera
- Chiến lược frame skipping thông minh (không bỏ frame ngẫu nhiên)
- Giảm latency WebSocket khi stream nhiều camera đồng thời

### Phần 5: Roadmap triển khai
Đưa ra roadmap theo từng giai đoạn:
- **Giai đoạn 1 (1–2 tuần):** Những thay đổi nhanh nhất, tác động cao nhất (quick wins)
- **Giai đoạn 2 (1 tháng):** Cải tiến mô hình và pipeline
- **Giai đoạn 3 (2–3 tháng):** Tối ưu toàn diện và scale

---

## 🚧 Ràng buộc và giả định

- **Ngôn ngữ:** Python 3.11, không đổi sang ngôn ngữ khác
- **Framework backend:** Giữ nguyên FastAPI
- **Hardware target chính:** Server không có GPU (CPU deployment), GPU phụ là RTX 3050/3060
- **Dataset:** Chưa có dataset giao thông Việt Nam riêng — đề xuất cần tính đến việc tự thu thập hoặc dùng dataset mở
- **Ngân sách inference:** Không dùng cloud API cho detection (phải chạy local)
- **Môi trường thực tế:** Camera IP tĩnh, góc nhìn từ trên xuống hoặc ngang, điều kiện Việt Nam (mưa, bụi, ánh sáng thay đổi)
- **Không phá vỡ:** REST API hiện tại (`/api/v1/road/...`) và WebSocket contracts

---

## 💡 Câu hỏi bổ sung để AI trả lời

1. Có nên tích hợp depth estimation (ví dụ: MiDaS, Depth Anything) để cải thiện tốc độ ước tính không? Trade-off là gì?
2. Nếu chỉ có ngân sách mua 1 GPU, nên chọn GPU nào để tối ưu cho bài toán này?
3. Có thể dùng ONNX Runtime thay TensorRT để hỗ trợ nhiều loại GPU hơn không?
4. Cách xây dựng hệ thống tự động alert khi phương tiện vượt quá ngưỡng tốc độ cho phép?
5. Có thể tích hợp nhận diện biển số xe (LP detection) vào pipeline hiện tại mà không ảnh hưởng FPS không?

---

*Prompt được tạo bởi Claude để tối ưu hoá Project-ITS — Hệ Thống Giao Thông Thông Minh*  
*Repo: https://github.com/WooCSSIN/Project-ITS*
