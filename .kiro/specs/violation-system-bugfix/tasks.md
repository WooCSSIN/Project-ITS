# Implementation Plan

## Overview

Sửa 5 bug trong hệ thống xử phạt nguội theo thứ tự ưu tiên phụ thuộc: BUG 5 (camera_id) → BUG 2 (mock zone) → BUG 1 (evidence image) → BUG 3 (ANPR preprocessing) → BUG 4 (realtime WebSocket). BUG 5 được ưu tiên đầu vì camera_id nhất quán là điều kiện tiên quyết để zone load đúng, qua đó giải quyết BUG 2 triệt để.

## Task Dependency Graph

```json
{
  "waves": [
    {
      "wave": 1,
      "tasks": ["1", "2"],
      "description": "BUG 5 exploration and preservation tests"
    },
    {
      "wave": 2,
      "tasks": ["3", "4"],
      "description": "BUG 5 fix and checkpoint",
      "dependsOn": ["1", "2"]
    },
    {
      "wave": 3,
      "tasks": ["5", "6"],
      "description": "BUG 2 exploration and preservation tests",
      "dependsOn": ["3", "4"]
    },
    {
      "wave": 4,
      "tasks": ["7", "8"],
      "description": "BUG 2 fix and checkpoint",
      "dependsOn": ["5", "6"]
    },
    {
      "wave": 5,
      "tasks": ["9", "10"],
      "description": "BUG 1 exploration and preservation tests",
      "dependsOn": ["7", "8"]
    },
    {
      "wave": 6,
      "tasks": ["11", "12"],
      "description": "BUG 1 fix and checkpoint",
      "dependsOn": ["9", "10"]
    },
    {
      "wave": 7,
      "tasks": ["13", "14"],
      "description": "BUG 3 exploration and preservation tests",
      "dependsOn": ["11", "12"]
    },
    {
      "wave": 8,
      "tasks": ["15", "16"],
      "description": "BUG 3 fix and checkpoint",
      "dependsOn": ["13", "14"]
    },
    {
      "wave": 9,
      "tasks": ["17", "18"],
      "description": "BUG 4 exploration and preservation tests",
      "dependsOn": ["15", "16"]
    },
    {
      "wave": 10,
      "tasks": ["19", "20"],
      "description": "BUG 4 fix and checkpoint",
      "dependsOn": ["17", "18"]
    },
    {
      "wave": 11,
      "tasks": ["21"],
      "description": "Final validation across all 5 bugs",
      "dependsOn": ["19", "20"]
    }
  ]
}
```

## Tasks

<!-- BUG 5 FIRST — camera_id nhất quán là nền tảng cho tất cả bug khác -->
<!-- Khi camera_id sai, zone load sai → mock zone bug càng nghiêm trọng hơn -->

## BUG 5 — camera_id không nhất quán

- [x] 1. Write bug condition exploration test (BUG 5 — camera_id)
  - **Property 1: Bug Condition** - camera_id Hash vs Index Mismatch
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples showing camera_id từ hash không khớp với index+1
  - **Scoped PBT Approach**: Scope property tới tất cả index trong `PATH_VIDEOS` — deterministic với mọi video trong list
  - Test: Khởi tạo `AnalyzeOnRoadBase` cho từng `path_video` trong `PATH_VIDEOS`, assert `camera_id == idx + 1`
  - Bug Condition: `abs(hash(self.name)) % 10000 != idx + 1` với mọi idx
  - Expected Behavior sau fix: `camera_id` của `AnalyzeOnRoadBase` (index 0) SHALL bằng 1, (index 1) bằng 2, v.v.
  - Run test trên code CHƯA fix — **EXPECTED OUTCOME**: Test FAILS với counterexample như `camera_id=7823` thay vì `1`
  - Document counterexample cụ thể: "PATH_VIDEOS[0] ('Văn Quán') → backend camera_id=XXXX, expected=1"
  - Mark task complete khi test được viết, chạy, và failure được document
  - _Requirements: 1.13, 1.14, 1.15_

- [x] 2. Write preservation property tests (BUG 5 — camera_id, BEFORE implementing fix)
  - **Property 2: Preservation** - camera_id uniqueness across multiple cameras
  - **IMPORTANT**: Follow observation-first methodology
  - Observe: Trên code CHƯA fix, mỗi video path tạo ra camera_id khác nhau (hash khác nhau)
  - Observe: Không có hai camera_id nào trùng nhau trong danh sách PATH_VIDEOS hiện tại
  - Write property-based test: Với mọi cặp (idx_a, idx_b) trong PATH_VIDEOS, nếu idx_a != idx_b thì `camera_id_a != camera_id_b`
  - Verify test passes trên code CHƯA fix (uniqueness đang đúng, chỉ formula là sai)
  - **EXPECTED OUTCOME**: Tests PASS (confirms baseline uniqueness behavior to preserve)
  - Mark task complete khi tests được viết, chạy, và passing trên unfixed code
  - _Requirements: 3.9_

- [x] 3. Fix BUG 5 — Thống nhất camera_id về index + 1

  - [x] 3.1 Implement camera_id fix trong AnalyzeOnRoadBase.__init__()
    - File: `backend/app/services/road_services/analyze_on_road_base.py`
    - Tìm dòng `cam_id = abs(hash(self.name)) % (10 ** 4)` trong constructor
    - Thay thế bằng logic `cam_id = settings_metric_transport.PATH_VIDEOS.index(self.path_video) + 1`
    - Thêm try/except ValueError với fallback: `abs(hash(self.name)) % (10 ** 4) + len(PATH_VIDEOS)` kèm `logger.warning`
    - Đảm bảo `self.path_video` được truyền vào và accessible trong constructor
    - _Bug_Condition: `abs(hash(self.name)) % 10000 != idx + 1` với mọi video trong PATH_VIDEOS_
    - _Expected_Behavior: `camera_id = PATH_VIDEOS.index(path_video) + 1` (1-based index)_
    - _Preservation: Uniqueness được bảo toàn vì mỗi index trong list là duy nhất_
    - _Requirements: 2.14, 2.15, 3.9_

  - [x] 3.2 Verify bug condition exploration test (BUG 5) now passes
    - **Property 1: Expected Behavior** - camera_id Index Consistency
    - **IMPORTANT**: Re-run the SAME test from task 1 — do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - Run bug condition exploration test từ bước 1
    - **EXPECTED OUTCOME**: Test PASSES — `camera_id == idx + 1` với mọi video trong PATH_VIDEOS
    - _Requirements: 2.14, 2.15_

  - [x] 3.3 Verify preservation tests (BUG 5) still pass
    - **Property 2: Preservation** - camera_id uniqueness
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run preservation property tests từ bước 2
    - **EXPECTED OUTCOME**: Tests PASS — không có hai camera_id nào trùng nhau
    - Confirm multiple cameras vẫn có camera_id riêng biệt

- [x] 4. Checkpoint BUG 5 — Ensure all BUG 5 tests pass
  - Ensure tất cả test BUG 5 pass, hỏi user nếu có thắc mắc

---

## BUG 2 — Mock zone hardcode

- [x] 5. Write bug condition exploration test (BUG 2 — mock zone)
  - **Property 1: Bug Condition** - Mock Zone Active After Init
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexample showing violation_engine có mock zone active sau khi __init__() chạy xong
  - **Scoped PBT Approach**: Scope property tới bất kỳ khởi tạo nào của AnalyzeOnRoadBase — deterministic
  - Test: Khởi tạo `AnalyzeOnRoadBase` (mock DB connection), assert `violation_engine.zones["red_light"] is None`
  - Test thứ hai: Assert `violation_engine.is_red_light_on == False` ngay sau init (trước khi `_load_zones_from_db()` chạy)
  - Bug Condition: `engine.zones["red_light"] is not None AND engine.is_red_light_on == True` sau __init__() và trước khi _load_zones_from_db() được gọi
  - Expected Behavior sau fix: Cả hai assert SHALL pass — không có mock zone nào tồn tại từ constructor
  - Run test trên code CHƯA fix — **EXPECTED OUTCOME**: Test FAILS (`zones["red_light"]` là np.array thay vì None)
  - Document counterexample: "violation_engine.zones['red_light'] = [(x1,y1), ...] sau init, expected None"
  - Mark task complete khi test được viết, chạy, và failure được document
  - _Requirements: 1.5, 1.6_

- [x] 6. Write preservation property tests (BUG 2 — mock zone, BEFORE implementing fix)
  - **Property 2: Preservation** - Speeding detection independent of zone state
  - **IMPORTANT**: Follow observation-first methodology
  - Observe: Trên code CHƯA fix, với speeds > limit, `speeding` violation vẫn được detect ngay cả khi mock zone active
  - Observe: `_check_speeding()` không đọc `zones["red_light"]` — độc lập hoàn toàn
  - Write property-based test: Với mọi vehicle track có speed > limit * 1.2 trong N consecutive frames, `process_frame_tracking()` SHALL return ít nhất 1 violation có `violation_type == "speeding"`, bất kể trạng thái của `zones["red_light"]` và `is_red_light_on`
  - Verify test passes trên code CHƯA fix (speeding đang hoạt động đúng)
  - **EXPECTED OUTCOME**: Tests PASS (confirms speeding detection baseline to preserve)
  - Mark task complete khi tests được viết, chạy, và passing trên unfixed code
  - _Requirements: 3.5_

- [x] 7. Fix BUG 2 — Xóa mock zone khỏi constructor

  - [x] 7.1 Implement mock zone removal trong AnalyzeOnRoadBase.__init__()
    - File: `backend/app/services/road_services/analyze_on_road_base.py`
    - Tìm và XÓA HOÀN TOÀN 4 dòng tạo mock zone:
      ```
      # bx, by, bw, bh = self.region_bbox
      # mock_red_light_zone = [(bx, by + bh//2), ...]
      # self.violation_engine.set_zone("red_light", mock_red_light_zone)
      # self.violation_engine.set_red_light_status(True)
      ```
    - Sau khi xóa, `ViolationEngine` giữ trạng thái mặc định: `zones["red_light"] = None`, `is_red_light_on = False`
    - Zone thực tế sẽ được load bởi `_load_zones_from_db()` trong `AnalyzeOnRoad.__init__()`
    - _Bug_Condition: `zones["red_light"] is not None AND is_red_light_on == True` sau init, trước khi DB được query_
    - _Expected_Behavior: ViolationEngine khởi tạo với mọi zones là None và is_red_light_on=False_
    - _Preservation: Speeding detection không phụ thuộc vào zone, tiếp tục hoạt động bình thường_
    - _Requirements: 2.5, 2.6, 2.7, 3.5_

  - [x] 7.2 Verify bug condition exploration test (BUG 2) now passes
    - **Property 1: Expected Behavior** - Clean ViolationEngine Init
    - **IMPORTANT**: Re-run the SAME test from task 5 — do NOT write a new test
    - Run bug condition exploration test từ bước 5
    - **EXPECTED OUTCOME**: Test PASSES — `zones["red_light"] is None` và `is_red_light_on == False` sau init
    - _Requirements: 2.5, 2.6_

  - [x] 7.3 Verify preservation tests (BUG 2) still pass
    - **Property 2: Preservation** - Speeding detection
    - **IMPORTANT**: Re-run the SAME tests from task 6 — do NOT write new tests
    - Run preservation property tests từ bước 6
    - **EXPECTED OUTCOME**: Tests PASS — speeding detection không bị ảnh hưởng bởi việc xóa mock zone
    - Confirm vi phạm tốc độ vẫn được detect với speed > limit * 1.2

- [x] 8. Checkpoint BUG 2 — Ensure all BUG 2 tests pass
  - Ensure tất cả test BUG 2 pass, hỏi user nếu có thắc mắc

---

## BUG 1 — evidence_image_url = null

- [x] 9. Write bug condition exploration test (BUG 1 — evidence_image_url)
  - **Property 1: Bug Condition** - Evidence Image URL Missing From Payload
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples showing payload thiếu trường `evidence_image_url`
  - **Scoped PBT Approach**: Scope property tới mọi violation có bounding box hợp lệ (x1 < x2, y1 < y2, nằm trong frame)
  - Test: Mock `_push_violations_to_queue()` để capture payload, gọi `_run_anpr_and_push()` với violation có `box=(10,10,100,100)` trên frame 600×400
  - Assert `"evidence_image_url" in payload AND payload["evidence_image_url"] is not None`
  - Bug Condition: `"evidence_image_url" NOT IN violation_payload OR violation_payload["evidence_image_url"] IS NULL`
  - Expected Behavior sau fix: Mọi payload với bounding box hợp lệ SHALL có `evidence_image_url` bắt đầu bằng "http" hoặc là `null` (MinIO down case)
  - Run test trên code CHƯA fix — **EXPECTED OUTCOME**: Test FAILS (KeyError hoặc None value)
  - Document counterexample: "Payload sau _push_violations_to_queue() không có key 'evidence_image_url'"
  - Mark task complete khi test được viết, chạy, và failure được document
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 10. Write preservation property tests (BUG 1 — evidence_image_url, BEFORE implementing fix)
  - **Property 2: Preservation** - MinIO failure does not lose violation record
  - **IMPORTANT**: Follow observation-first methodology
  - Observe: Trên code CHƯA fix, khi `_push_violations_to_queue()` được gọi, vi phạm LUÔN được đẩy vào Redis kể cả khi có exception
  - Observe: Các trường hiện có (`camera_id`, `violation_type`, `vehicle_track_id`, `license_plate`, `confidence`, `timestamp`) luôn có mặt trong payload
  - Write property-based test: Mock `minio_image_store.upload_road_frame()` để raise exception với mọi loại Exception, verify `_push_violations_to_queue()` vẫn được gọi 1 lần với đầy đủ 6 trường cũ, không raise exception ra ngoài
  - Write property-based test: Generate random violation dicts với các trường cũ, verify structure được bảo toàn sau fix
  - Verify tests pass trên code CHƯA fix (MinIO failure case chưa tồn tại trong code cũ, test sẽ setup môi trường giả để verify)
  - **EXPECTED OUTCOME**: Tests PASS (confirms baseline payload structure to preserve)
  - Mark task complete khi tests được viết, chạy, và passing trên unfixed code
  - _Requirements: 3.1, 3.2_

- [x] 11. Fix BUG 1 — Thêm MinIO upload vào ANPR thread

  - [x] 11.1 Thêm hàm `_crop_and_upload_evidence()` vào AnalyzeOnRoadBase
    - File: `backend/app/services/road_services/analyze_on_road_base.py`
    - Thêm import: `from utils.minio_image_store import minio_image_store`
    - Thêm hàm mới `_crop_and_upload_evidence(self, frame, box, camera_id, margin=0.05)`:
      - Tính margin 5% quanh bounding box
      - Clamp tọa độ vào bounds frame (max(0, ...), min(w/h, ...))
      - Validate crop area không rỗng (cx2 > cx1 và cy2 > cy1)
      - Encode sang JPEG quality 85 bằng `cv2.imencode()`
      - Gọi `minio_image_store.upload_road_frame(road_name, jpeg_bytes)`
      - Wrap toàn bộ trong try/except Exception: log warning, return None
      - Return URL string (hoặc None nếu thất bại)
    - _Bug_Condition: Payload được push vào Redis thiếu evidence_image_url cho mọi violation_
    - _Expected_Behavior: Payload chứa evidence_image_url = URL (nếu thành công) hoặc null (nếu MinIO down)_
    - _Preservation: Khi upload fail, exception KHÔNG được raise ra ngoài ANPR thread, vi phạm vẫn được ghi vào DB_
    - _Requirements: 2.1, 2.2, 3.2_

  - [x] 11.2 Sửa closure `_run_anpr_and_push()` trong `process_single_frame()`
    - File: `backend/app/services/road_services/analyze_on_road_base.py`
    - Trong vòng lặp `for v in violations:`, SAU khi gọi `read_license_plate()`:
      - Thêm: `evidence_url = self._crop_and_upload_evidence(frame, v["box"], v["camera_id"])`
      - Thêm: `v["evidence_image_url"] = evidence_url`
    - Đảm bảo step này chạy trong ANPR ThreadPoolExecutor — không block video loop
    - _Requirements: 2.1, 2.2, 3.3_

  - [x] 11.3 Cập nhật `_push_violations_to_queue()` trong analyze_on_road.py
    - File: `backend/app/services/road_services/analyze_on_road.py`
    - Tìm dict `payload` được tạo trong `_push_violations_to_queue()`
    - Thêm trường: `"evidence_image_url": v.get("evidence_image_url"),`
    - Đảm bảo 6 trường cũ không bị thay đổi cấu trúc
    - _Requirements: 2.2, 2.3, 3.1_

  - [x] 11.4 Verify bug condition exploration test (BUG 1) now passes
    - **Property 1: Expected Behavior** - Evidence Image URL In Payload
    - **IMPORTANT**: Re-run the SAME test from task 9 — do NOT write a new test
    - Run bug condition exploration test từ bước 9
    - **EXPECTED OUTCOME**: Test PASSES — `payload["evidence_image_url"]` tồn tại và là string URL hoặc None (không phải missing key)
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 11.5 Verify preservation tests (BUG 1) still pass
    - **Property 2: Preservation** - MinIO failure does not lose violation
    - **IMPORTANT**: Re-run the SAME tests from task 10 — do NOT write new tests
    - Run preservation property tests từ bước 10
    - **EXPECTED OUTCOME**: Tests PASS — khi MinIO throw exception, `_push_violations_to_queue()` vẫn được gọi với `evidence_image_url=null`, không crash

- [x] 12. Checkpoint BUG 1 — Ensure all BUG 1 tests pass
  - Ensure tất cả test BUG 1 pass, hỏi user nếu có thắc mắc

---

## BUG 3 — ANPR accuracy khi không có LP model

- [x] 13. Write bug condition exploration test (BUG 3 — ANPR preprocessing)
  - **Property 1: Bug Condition** - EasyOCR Fails on Low-Resolution Vehicle Crop
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples showing `_ocr_on_region()` trả về None/rỗng cho ảnh biển số nhỏ
  - **Scoped PBT Approach**: Scope property tới vehicle crop có `width < 120px` — điều kiện kích hoạt bug
  - Test: Tạo vehicle crop 80×60px (xe máy ở xa) với biển số giả có thể đọc được, gọi `_ocr_on_region()` trên code chưa fix, assert kết quả khác None/rỗng
  - Bug Condition: `LicensePlateDetector.is_available == False AND vehicle_box_width < 120px AND preprocessing chỉ dùng equalizeHist`
  - Expected Behavior sau fix: Với crop nhỏ (< 120px), hệ thống SHALL upscale 2x+ trước OCR, CLAHE thay equalizeHist, GaussianBlur + sharpen
  - Run test trên code CHƯA fix — **EXPECTED OUTCOME**: Test FAILS (OCR trả về None hoặc empty string)
  - Document counterexample: "crop 80×60px → _ocr_on_region() returns None, expected non-null plate"
  - Mark task complete khi test được viết, chạy, và failure được document
  - _Requirements: 1.8, 1.9, 1.10_

- [x] 14. Write preservation property tests (BUG 3 — ANPR, BEFORE implementing fix)
  - **Property 2: Preservation** - ANPR does not block video loop
  - **IMPORTANT**: Follow observation-first methodology
  - Observe: Trên code CHƯA fix, ANPR chạy trong ThreadPoolExecutor — video loop không bị block
  - Observe: Khi EasyOCR chưa cài đặt, hệ thống log warning và return None (không crash)
  - Write property-based test: Verify `read_license_plate()` luôn return trong vòng timeout hợp lý (< 5s) và không raise exception ra ngoài ThreadPoolExecutor, bất kể input
  - Write test: Mock EasyOCR chưa cài đặt (ImportError), verify `read_license_plate()` returns None, không crash
  - Verify tests pass trên code CHƯA fix (bất đồng bộ đang hoạt động đúng)
  - **EXPECTED OUTCOME**: Tests PASS (confirms async baseline to preserve)
  - Mark task complete khi tests được viết, chạy, và passing trên unfixed code
  - _Requirements: 3.3, 3.6_

- [x] 15. Fix BUG 3 — Cải thiện preprocessing pipeline trong _ocr_on_region()

  - [x] 15.1 Implement improved preprocessing trong ANPREngine._ocr_on_region()
    - File: `backend/app/core/anpr.py`
    - Tìm hàm `_ocr_on_region()` (hiện tại: grayscale + equalizeHist + readtext)
    - Thêm bước 1 (TRƯỚC grayscale): Upscale nếu `width < 120px` → `scale = max(2.0, 120.0 / w)`, dùng `cv2.INTER_CUBIC`
    - Thay `equalizeHist` bằng CLAHE: `clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4,4))`, `gray = clahe.apply(gray)`
    - Thêm Gaussian blur nhẹ: `gray = cv2.GaussianBlur(gray, (3,3), 0)`
    - Thêm sharpening kernel: `kernel = np.array([[-1,-1,-1],[-1,9,-1],[-1,-1,-1]])`, `gray = cv2.filter2D(gray, -1, kernel)`
    - Thêm `allowlist='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'` vào `reader.readtext()`
    - _Bug_Condition: lp_detector_available==False AND vehicle_crop_width < 120px AND preprocessing chỉ dùng equalizeHist_
    - _Expected_Behavior: Upscale 2x+ → CLAHE → GaussianBlur → Sharpen → EasyOCR với allowlist_
    - _Preservation: ANPR vẫn bất đồng bộ trong ThreadPoolExecutor, không block video loop, không crash khi EasyOCR unavailable_
    - _Requirements: 2.8, 2.9, 2.10, 3.3, 3.6_

  - [x] 15.2 Verify bug condition exploration test (BUG 3) now passes
    - **Property 1: Expected Behavior** - Improved OCR on Small Crops
    - **IMPORTANT**: Re-run the SAME test from task 13 — do NOT write a new test
    - Run bug condition exploration test từ bước 13
    - **EXPECTED OUTCOME**: Test PASSES — `_ocr_on_region()` trả về kết quả khác None/rỗng cho ảnh 80×60px sau preprocessing fix
    - _Requirements: 2.8, 2.9, 2.10_

  - [x] 15.3 Verify preservation tests (BUG 3) still pass
    - **Property 2: Preservation** - Async ANPR execution
    - **IMPORTANT**: Re-run the SAME tests from task 14 — do NOT write new tests
    - Run preservation property tests từ bước 14
    - **EXPECTED OUTCOME**: Tests PASS — ANPR vẫn không block video loop, EasyOCR unavailable vẫn return None không crash

- [x] 16. Checkpoint BUG 3 — Ensure all BUG 3 tests pass
  - Ensure tất cả test BUG 3 pass, hỏi user nếu có thắc mắc

---

## BUG 4 — ViolationsList không tự cập nhật realtime

- [x] 17. Write bug condition exploration test (BUG 4 — realtime WebSocket)
  - **Property 1: Bug Condition** - New Violation Not Reflected Without Manual Refresh
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexample showing ViolationsList không update khi có wsData mới
  - **Scoped PBT Approach**: Scope property tới component state khi `wsData` thay đổi — deterministic
  - Test (React Testing Library): Render `ViolationsList` với mock `useWebSocket` ban đầu `{ data: null, isConnected: false }`, sau đó update `data` thành mock violation mới, assert violation mới xuất hiện trong danh sách mà không gọi lại `fetchViolations()`
  - Bug Condition: `no WebSocket subscription exists AND new wsData NOT reflected in UI list WITHOUT manual refresh`
  - Expected Behavior sau fix: Khi `wsData` thay đổi thành violation mới, `setViolations(prev => [newViolation, ...prev])` được gọi
  - Run test trên code CHƯA fix — **EXPECTED OUTCOME**: Test FAILS (danh sách không update khi wsData thay đổi)
  - Document counterexample: "wsData = {id: 123, ...} → violations list length không tăng, violation mới không xuất hiện"
  - Mark task complete khi test được viết, chạy, và failure được document
  - _Requirements: 1.11, 1.12_

- [x] 18. Write preservation property tests (BUG 4 — realtime, BEFORE implementing fix)
  - **Property 2: Preservation** - Manual refresh and filter continue to work
  - **IMPORTANT**: Follow observation-first methodology
  - Observe: Trên code CHƯA fix, `fetchViolations()` hoạt động độc lập và được gọi khi component mount và khi statusFilter thay đổi
  - Observe: Filter thay đổi trigger HTTP REST call, không liên quan đến WebSocket
  - Write property-based test: Verify `fetchViolations()` vẫn được gọi khi statusFilter thay đổi, bất kể trạng thái WebSocket (`isConnected = true/false`)
  - Write test: Verify button "Làm mới" thủ công vẫn gọi `fetchViolations()` kể cả khi WebSocket đang connected
  - Write test: Verify khi `statusFilter != ""` và violation mới từ wsData có status khác, violation đó KHÔNG được prepend vào list
  - Verify tests pass trên code CHƯA fix (manual refresh đang hoạt động đúng)
  - **EXPECTED OUTCOME**: Tests PASS (confirms manual refresh and filter baseline to preserve)
  - Mark task complete khi tests được viết, chạy, và passing trên unfixed code
  - _Requirements: 3.7, 3.8_

- [x] 19. Fix BUG 4 — Kết nối ViolationsList với WebSocket

  - [x] 19.1 Thêm WebSocket URL vào endpoints config
    - File: `frontend/src/config/endpoints.ts` (hoặc `config.ts` — xác nhận path thực tế)
    - Thêm entry: `violationsWs: \`\${apiConfig.API_WS_BASE}/road/ws/violations\``
    - Đảm bảo `API_WS_BASE` dùng protocol `ws://` hoặc `wss://` (không phải `http://`)
    - _Requirements: 2.11_

  - [x] 19.2 Import useWebSocket và thiết lập subscription trong ViolationsList
    - File: `frontend/src/pages/ViolationsList.tsx`
    - Thêm import `useWebSocket` hook (đã có sẵn trong codebase)
    - Thêm import type `Violation` nếu chưa có
    - Lấy `token = localStorage.getItem("access_token")`
    - Thêm: `const { data: wsData, isConnected, error: wsError } = useWebSocket(endpoints.violationsWs, { authToken: token, maxReconnectAttempts: 10 })`
    - _Bug_Condition: Không có WebSocket subscription nào tới /api/v1/road/ws/violations_
    - _Expected_Behavior: useWebSocket hook subscribed, isConnected phản ánh trạng thái kết nối_
    - _Preservation: fetchViolations() và statusFilter logic giữ nguyên_
    - _Requirements: 2.11, 3.7, 3.8_

  - [x] 19.3 Thêm useEffect xử lý wsData để prepend violation mới
    - File: `frontend/src/pages/ViolationsList.tsx`
    - Thêm useEffect với dependency `[wsData]`:
      ```
      if (wsData !== null) {
        const newViolation = wsData as Violation
        if (statusFilter === "" || newViolation.status === statusFilter) {
          setViolations(prev => [newViolation, ...prev])
        }
      }
      ```
    - Logic filter: Chỉ prepend nếu statusFilter rỗng HOẶC violation mới match filter hiện tại
    - _Requirements: 2.12, 3.7, 3.8_

  - [x] 19.4 Thêm WebSocket connection indicator vào UI header
    - File: `frontend/src/pages/ViolationsList.tsx`
    - Thêm indicator nhỏ cạnh title/header của trang:
      - `isConnected`: hiển thị `● Realtime` màu xanh
      - `!isConnected`: hiển thị `● Offline` màu vàng
    - Khi `wsError` tồn tại: hiển thị tooltip hoặc message ngắn
    - _Requirements: 2.13_

  - [x] 19.5 Verify bug condition exploration test (BUG 4) now passes
    - **Property 1: Expected Behavior** - Auto-prepend on WebSocket data
    - **IMPORTANT**: Re-run the SAME test from task 17 — do NOT write a new test
    - Run bug condition exploration test từ bước 17
    - **EXPECTED OUTCOME**: Test PASSES — violations list tự động cập nhật khi `wsData` thay đổi, không cần manual refresh
    - _Requirements: 2.11, 2.12_

  - [x] 19.6 Verify preservation tests (BUG 4) still pass
    - **Property 2: Preservation** - Manual refresh and filter
    - **IMPORTANT**: Re-run the SAME tests from task 18 — do NOT write new tests
    - Run preservation property tests từ bước 18
    - **EXPECTED OUTCOME**: Tests PASS — manual refresh và filter vẫn hoạt động độc lập với WebSocket
    - Confirm "Làm mới" button và statusFilter change vẫn trigger HTTP REST calls

- [x] 20. Checkpoint BUG 4 — Ensure all BUG 4 tests pass
  - Ensure tất cả test BUG 4 pass, hỏi user nếu có thắc mắc

---

## Final Validation

- [x] 21. Checkpoint cuối — Ensure all tests pass (toàn bộ 5 bugs)
  - Chạy lại toàn bộ test suite: BUG 5, BUG 2, BUG 1, BUG 3, BUG 4
  - Verify tích hợp: camera_id đúng → zone được load → không có mock zone → evidence image được lưu → CSGT thấy ảnh realtime
  - Verify integration scenario: Lưu zone qua frontend `ZoneConfig.tsx` với `cameraId=1`, backend `_load_zones_from_db()` tìm được zone đó
  - Ensure không có regression nào trong các hành vi đã document trong Preservation Requirements
  - Hỏi user nếu có câu hỏi hoặc cần điều chỉnh

## Notes

- **Thứ tự ưu tiên**: BUG 5 → BUG 2 → BUG 1 → BUG 3 → BUG 4. BUG 5 là nền tảng vì camera_id sai dẫn đến zone load sai, làm BUG 2 (mock zone) trầm trọng hơn.
- **Methodology**: Mỗi bug theo workflow: Exploration Test (fail on unfixed) → Preservation Test (pass on unfixed) → Implement Fix → Verify Both Pass.
- **Property 1** (Bug Condition): Phải FAIL trên code chưa fix. Không sửa test khi nó fail — đó là dấu hiệu đúng.
- **Property 2** (Preservation): Phải PASS trên code chưa fix để xác nhận baseline behavior trước khi fix.
- **Backend files chính cần sửa**: `analyze_on_road_base.py` (BUG 1, 2, 5), `analyze_on_road.py` (BUG 1), `anpr.py` (BUG 3).
- **Frontend files chính cần sửa**: `ViolationsList.tsx` (BUG 4), `endpoints config` (BUG 4).
- **Không cần sửa** `ZoneConfig.tsx` — frontend đã dùng `idx + 1` đúng rồi.
- **Database cleanup**: Sau khi fix BUG 2 và BUG 5 verified, có thể xem xét cleanup các vi phạm giả trong DB (hơn 11.000 records) — nhưng đây là tác vụ riêng, cần xác nhận user trước.
- **Test framework**: Sử dụng pytest (backend) và React Testing Library + Jest (frontend). Property-based testing có thể dùng Hypothesis (Python) cho BUG 3, 5.
