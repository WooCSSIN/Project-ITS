# Bugfix Requirements Document

## Introduction

Hệ thống xử phạt nguội (Violations) có 5 lỗi nghiêm trọng được phát hiện qua phân tích code thực tế, ảnh hưởng toàn bộ pipeline từ phát hiện vi phạm đến hiển thị kết quả cho CSGT. Cụ thể: ảnh bằng chứng không được lưu (`evidence_image_url = null`), mock zone hardcode tạo hàng nghìn vi phạm giả, ANPR không nhận dạng được biển số (`license_plate = null`), danh sách vi phạm không tự cập nhật theo thời gian thực, và `camera_id` tính không nhất quán giữa frontend và backend khiến zone cấu hình từ UI không được nạp đúng vào ViolationEngine.

## Bug Analysis

### Current Behavior (Defect)

**BUG 1 — Ảnh bằng chứng không được lưu (`evidence_image_url = null`)**

1.1 WHEN hệ thống phát hiện vi phạm mới THEN hàm `_push_violations_to_queue()` trong `analyze_on_road.py` đẩy payload vào Redis mà không bao gồm trường `evidence_image_url`

1.2 WHEN ViolationWorker đọc payload từ Redis queue và ghi vào PostgreSQL THEN trường `evidence_image_url` trong bảng `violations` luôn là `null` vì không có giá trị nào được truyền vào

1.3 WHEN frame tại thời điểm vi phạm xảy ra THEN frame đó không được crop vùng bounding box của xe vi phạm và không được upload lên MinIO bucket `road-frames`

1.4 WHEN CSGT truy cập trang chi tiết vi phạm THEN giao diện hiển thị "Chưa có ảnh bằng chứng" thay vì ảnh chụp phương tiện vi phạm

**BUG 2 — Mock zone hardcode tạo vi phạm giả**

1.5 WHEN `AnalyzeOnRoadBase.__init__()` được khởi tạo THEN code tạo `mock_red_light_zone` dựa trên `region_bbox` và gọi `set_red_light_status(True)` cứng, bất kể DB có zone thực tế hay không

1.6 WHEN `_load_zones_from_db()` được gọi và DB không có zone nào cho camera này THEN mock zone vẫn active với `is_red_light_on = True`, khiến mọi phương tiện di chuyển qua nửa dưới vùng ROI đều bị ghi nhận là vi phạm đèn đỏ

1.7 WHEN hệ thống hoạt động liên tục với mock zone active THEN hàng nghìn bản ghi vi phạm giả được tạo ra trong DB (đã có hơn 11.000 records theo vi phạm #11845)

**BUG 3 — ANPR accuracy rất thấp — biển số "Chưa rõ"**

1.8 WHEN `ANPREngine` được khởi tạo và thư mục `ai_models/license_plate/` không tồn tại THEN `LicensePlateDetector` không tải được model LP và `is_available` trả về `False`

1.9 WHEN `LicensePlateDetector.is_available` là `False` THEN `read_license_plate()` fallback về phương pháp crop nửa dưới xe trên frame gốc có độ phân giải thấp (600×400), khiến EasyOCR không đọc được biển số

1.10 WHEN ANPR không đọc được biển số THEN `license_plate` trong DB là `null` và frontend hiển thị "Chưa rõ" cho gần như tất cả vi phạm

**BUG 4 — ViolationsList không tự cập nhật — cần refresh thủ công**

1.11 WHEN có vi phạm mới được backend phát hiện và publish vào Redis pub/sub channel `violations:alerts` THEN frontend `ViolationsList.tsx` không nhận được thông báo realtime vì không có WebSocket subscription

1.12 WHEN CSGT đang xem trang `ViolationsList` THEN danh sách vi phạm chỉ được cập nhật khi người dùng bấm nút "Làm mới" thủ công, mặc dù backend đã có endpoint WebSocket `/api/v1/road/ws/violations` subscribe Redis pub/sub `violations:alerts`

**BUG 5 — `camera_id` không nhất quán giữa frontend và backend**

1.13 WHEN backend tính `camera_id` trong `AnalyzeOnRoadBase.__init__()` THEN dùng `abs(hash(self.name)) % (10 ** 4)` — hash của tên đường ra số 4 chữ số không thể đoán trước

1.14 WHEN `ZoneConfig.tsx` tính `cameraId` để lưu zone THEN dùng `idx + 1` (1-based index của đường trong danh sách `roadNames`)

1.15 WHEN CSGT lưu zone qua `ZoneConfig.tsx` và `_load_zones_from_db()` query zone theo `camera_id` của backend THEN hai `camera_id` khác nhau hoàn toàn nên không tìm thấy zone nào, zone cấu hình từ UI bị bỏ qua hoàn toàn

### Expected Behavior (Correct)

**BUG 1 — Ảnh bằng chứng**

2.1 WHEN hệ thống phát hiện vi phạm mới THEN frame tại thời điểm vi phạm SHALL được crop theo bounding box của xe vi phạm và upload lên MinIO bucket `road-frames`

2.2 WHEN ảnh bằng chứng đã được upload thành công lên MinIO THEN hàm `_push_violations_to_queue()` SHALL bao gồm trường `evidence_image_url` với URL trỏ đến ảnh trên MinIO trong payload gửi vào Redis queue

2.3 WHEN ViolationWorker ghi vi phạm vào PostgreSQL THEN trường `evidence_image_url` SHALL chứa URL hợp lệ trỏ đến ảnh bằng chứng trên MinIO

2.4 WHEN CSGT truy cập trang chi tiết vi phạm có `evidence_image_url` hợp lệ THEN giao diện SHALL hiển thị ảnh bằng chứng thực tế của phương tiện vi phạm

**BUG 2 — Mock zone**

2.5 WHEN `AnalyzeOnRoadBase.__init__()` được khởi tạo THEN `ViolationEngine` SHALL được khởi tạo với tất cả zones là `None` và `is_red_light_on = False`, không có mock zone nào được tạo

2.6 WHEN `_load_zones_from_db()` không tìm được zone nào trong DB cho camera này THEN hệ thống SHALL không phát hiện vi phạm đèn đỏ, `process_frame_tracking()` SHALL trả về danh sách vi phạm rỗng cho các loại vi phạm phụ thuộc zone

2.7 WHEN `_load_zones_from_db()` tải được zone thực tế từ DB THEN các zone đó SHALL là nguồn duy nhất để phát hiện vi phạm

**BUG 3 — ANPR**

2.8 WHEN model LP (`ai_models/license_plate/best.pt` hoặc tương đương) được cung cấp THEN `LicensePlateDetector` SHALL load model thành công và `is_available` SHALL trả về `True`

2.9 WHEN `LicensePlateDetector.is_available` là `True` THEN hệ thống SHALL dùng YOLO LP model để detect vùng biển số chính xác trước khi chạy EasyOCR

2.10 WHEN ANPR đọc được biển số hợp lệ theo format Việt Nam (7-9 ký tự, 2 số đầu) THEN `license_plate` SHALL được lưu vào DB với giá trị biển số thực tế thay vì `null`

**BUG 4 — Realtime updates**

2.11 WHEN CSGT mở trang `ViolationsList` THEN frontend SHALL thiết lập kết nối WebSocket tới `/api/v1/road/ws/violations`

2.12 WHEN backend publish vi phạm mới vào Redis pub/sub `violations:alerts` THEN frontend SHALL nhận được message qua WebSocket và tự động thêm vi phạm mới vào đầu danh sách mà không cần người dùng thao tác

2.13 WHEN kết nối WebSocket bị gián đoạn THEN frontend SHALL tự động thử kết nối lại và hiển thị trạng thái kết nối cho người dùng

**BUG 5 — camera_id nhất quán**

2.14 WHEN backend tính `camera_id` cho một đường THEN SHALL dùng `index + 1` (vị trí 1-based trong danh sách `PATH_VIDEOS`) thống nhất với cách tính của frontend

2.15 WHEN CSGT lưu zone với `cameraId = N` qua frontend THEN `_load_zones_from_db()` SHALL tìm được và load đúng zone đó vì backend cũng dùng `camera_id = N` cho cùng đường

### Unchanged Behavior (Regression Prevention)

3.1 WHEN vi phạm được phát hiện THEN hệ thống SHALL CONTINUE TO đẩy các trường hiện có (`camera_id`, `violation_type`, `vehicle_track_id`, `license_plate`, `confidence`, `timestamp`) vào Redis queue không thay đổi

3.2 WHEN upload MinIO thất bại (lỗi mạng, MinIO không khả dụng) THEN hệ thống SHALL CONTINUE TO ghi vi phạm vào DB với `evidence_image_url = null` thay vì crash hay mất vi phạm

3.3 WHEN ANPR chạy bất đồng bộ trong ThreadPoolExecutor THEN hệ thống SHALL CONTINUE TO không block video processing loop chính

3.4 WHEN `_load_zones_from_db()` thất bại do lỗi DB THEN hệ thống SHALL CONTINUE TO log warning và tiếp tục hoạt động mà không crash

3.5 WHEN kiểm tra tốc độ (speeding) không phụ thuộc zone THEN hệ thống SHALL CONTINUE TO phát hiện vi phạm tốc độ độc lập với cấu hình zone

3.6 WHEN EasyOCR chưa được cài đặt THEN hệ thống SHALL CONTINUE TO log warning và tiếp tục hoạt động mà không crash, trả về `None` cho biển số

3.7 WHEN người dùng bấm "Làm mới" thủ công trên `ViolationsList` THEN hệ thống SHALL CONTINUE TO fetch lại danh sách qua HTTP REST

3.8 WHEN người dùng thay đổi filter trạng thái trên `ViolationsList` THEN hệ thống SHALL CONTINUE TO filter và tải lại danh sách qua HTTP REST

3.9 WHEN camera_id được thống nhất THEN hệ thống SHALL CONTINUE TO hỗ trợ nhiều camera/đường với `camera_id` riêng biệt không trùng nhau

3.10 WHEN zone thực tế được load từ DB THEN hệ thống SHALL CONTINUE TO phát hiện vi phạm đúng khi xe đi vào zone được cấu hình
