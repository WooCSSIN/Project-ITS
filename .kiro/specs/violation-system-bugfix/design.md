# Violation System Bugfix — Technical Design

## Overview

Năm bug trong hệ thống xử phạt nguội được sửa theo thứ tự ưu tiên:

1. **BUG 1** — `evidence_image_url = null`: Thêm bước crop frame + upload MinIO vào `_run_anpr_and_push()` trước khi đẩy payload vào Redis queue.
2. **BUG 2** — Mock zone hardcode: Xóa toàn bộ block tạo `mock_red_light_zone` và `set_red_light_status(True)` khỏi `AnalyzeOnRoadBase.__init__()`.
3. **BUG 3** — ANPR accuracy khi không có LP model: Cải thiện preprocessing pipeline trong `_ocr_on_region()` (CLAHE + upscale + denoising).
4. **BUG 4** — Không có realtime: Kết nối `ViolationsList.tsx` với WebSocket `/api/v1/road/ws/violations` qua hook `useWebSocket` có sẵn.
5. **BUG 5** — `camera_id` không nhất quán: Thống nhất công thức `index + 1` (1-based index trong `PATH_VIDEOS`) thay thế `abs(hash(name)) % 10000`.

Chiến lược fix là **minimal và targeted**: mỗi bug chỉ sửa đúng file cần sửa, không refactor code không liên quan.

---

## Glossary

- **Bug_Condition (C)**: Điều kiện kích hoạt lỗi — input hoặc trạng thái dẫn đến hành vi sai
- **Property (P)**: Hành vi đúng mong đợi sau khi fix — assertion cần đúng với mọi input thuộc C
- **Preservation**: Hành vi không bị ảnh hưởng bởi fix — phải giữ nguyên với input không thuộc C
- **`_push_violations_to_queue()`**: Hàm trong `analyze_on_road.py` đẩy vi phạm vào Redis queue và pub/sub
- **`_run_anpr_and_push()`**: Closure trong `process_single_frame()` (base class) chạy trong ANPR ThreadPoolExecutor
- **`AnalyzeOnRoadBase.__init__()`**: Constructor trong `analyze_on_road_base.py` — nơi chứa mock zone hardcode
- **`ViolationEngine`**: `core/violation_engine.py` — engine phát hiện vi phạm, mặc định `is_red_light_on=False` và tất cả zones là `None`
- **`ANPREngine`**: `core/anpr.py` — engine đọc biển số, fallback về crop nửa dưới khi không có LP model
- **`MinioImageStore`**: `utils/minio_image_store.py` — singleton đã có sẵn, dùng `upload_road_frame()` để upload ảnh
- **`camera_id`**: Integer định danh camera, là 1-based index vị trí video trong `settings_metric_transport.PATH_VIDEOS`
- **`PATH_VIDEOS`**: Danh sách đường dẫn video trong `SettingMetricTransport`, thứ tự index = thứ tự camera

---

## Bug Details

### BUG 1 — evidence_image_url = null

#### Bug Condition

Upload ảnh bằng chứng bị bỏ qua hoàn toàn trong pipeline xử lý vi phạm. Frame tại thời điểm vi phạm có sẵn (`frame_copy`) nhưng không được crop và upload trước khi đẩy payload vào Redis.

```
FUNCTION isBugCondition_1(violation_payload)
  INPUT: dict được tạo trong _push_violations_to_queue()
  OUTPUT: boolean

  RETURN "evidence_image_url" NOT IN violation_payload
         OR violation_payload["evidence_image_url"] IS NULL
END FUNCTION
```

#### Examples

- **Input**: Vi phạm `red_light` với `box=(100,150,300,350)` trên frame 600×400 → **Bug**: `evidence_image_url = null` trong DB
- **Input**: Vi phạm `speeding` trên bất kỳ camera nào → **Bug**: `evidence_image_url = null`
- **Input**: Vi phạm với bounding box nằm ngoài frame (clip boundary) → **Expected after fix**: crop được clamp vào frame, upload thành công hoặc graceful `null`

---

### BUG 2 — Mock zone hardcode

#### Bug Condition

Constructor `AnalyzeOnRoadBase.__init__()` luôn tạo mock zone và bật đèn đỏ giả bất kể DB có zone thực hay không.

```
FUNCTION isBugCondition_2(engine_state_after_init)
  INPUT: ViolationEngine state sau khi __init__() hoàn thành
  OUTPUT: boolean

  RETURN engine_state_after_init.zones["red_light"] IS NOT NULL
         AND engine_state_after_init.is_red_light_on == True
         AND _load_zones_from_db() has NOT been called yet
END FUNCTION
```

#### Examples

- **Input**: DB không có zone nào cho camera 1 → **Bug**: Mock zone vẫn active, mọi xe đi qua nửa dưới ROI đều bị ghi vi phạm
- **Input**: DB có zone thực tế cho camera 1 → **Bug**: Mock zone được tạo trước, sau đó `_load_zones_from_db()` ghi đè — nhưng `is_red_light_on` vẫn `True` từ mock

---

### BUG 3 — ANPR accuracy khi không có LP model

#### Bug Condition

Khi `LicensePlateDetector.is_available` là `False`, fallback crop nửa dưới xe chạy trực tiếp trên frame có độ phân giải thấp (600×400) với preprocessing tối thiểu (chỉ grayscale + equalizeHist). EasyOCR không đọc được biển số nhỏ trong điều kiện này.

```
FUNCTION isBugCondition_3(anpr_input)
  INPUT: (frame, vehicle_box, lp_detector_available)
  OUTPUT: boolean

  RETURN lp_detector_available == False
         AND vehicle_box_area < 15000 pixels  -- xe nhỏ trên frame 600×400
         AND preprocessing chỉ dùng equalizeHist (không upscale, không CLAHE, không denoise)
END FUNCTION
```

#### Examples

- **Input**: Vehicle crop 80×60px (xe máy ở xa) → **Bug**: EasyOCR không nhận ra ký tự biển số → `license_plate = null`
- **Input**: Vehicle crop 200×120px với biển số nhòe → **Bug**: equalizeHist không đủ → `license_plate = null`

---

### BUG 4 — ViolationsList không realtime

#### Bug Condition

Component `ViolationsList.tsx` không subscribe WebSocket. Backend đã có endpoint `/api/v1/road/ws/violations` publish vi phạm mới qua Redis pub/sub nhưng frontend không lắng nghe.

```
FUNCTION isBugCondition_4(component_state)
  INPUT: ViolationsList React component state
  OUTPUT: boolean

  RETURN no WebSocket connection to "/api/v1/road/ws/violations" exists
         AND new violation published by backend is NOT reflected in UI
         WITHOUT user manual refresh
END FUNCTION
```

---

### BUG 5 — camera_id không nhất quán

#### Bug Condition

Backend và frontend dùng hai công thức khác nhau để tính `camera_id` cho cùng một đường, dẫn đến zone được lưu bởi frontend không bao giờ được load bởi backend.

```
FUNCTION isBugCondition_5(road_name)
  INPUT: road_name (string)
  OUTPUT: boolean

  backend_id  := abs(hash(road_name)) % 10000
  frontend_id := indexOf(road_name, PATH_VIDEOS_ORDER) + 1

  RETURN backend_id != frontend_id
END FUNCTION
```

#### Examples

- **Input**: `"Văn Quán"` (index 0 trong PATH_VIDEOS)
  - Frontend lưu với `camera_id = 1`
  - Backend hash: `abs(hash("Văn Quán")) % 10000` → không đoán trước được (ví dụ: `7823`)
  - **Bug**: `_load_zones_from_db()` query `WHERE camera_id = 7823` → không tìm thấy gì

---

## Expected Behavior

### Preservation Requirements

**Hành vi không được thay đổi sau tất cả các fix:**

- Các trường payload hiện có (`camera_id`, `violation_type`, `vehicle_track_id`, `license_plate`, `confidence`, `timestamp`) trong Redis queue KHÔNG bị thay đổi cấu trúc
- Khi upload MinIO thất bại (lỗi mạng, MinIO không khả dụng): vi phạm vẫn được ghi vào DB với `evidence_image_url = null` — **không crash, không mất vi phạm**
- ANPR vẫn chạy bất đồng bộ trong `ThreadPoolExecutor` — video processing loop KHÔNG bị block
- Khi `_load_zones_from_db()` thất bại do lỗi DB: log warning và tiếp tục — **không crash**
- Kiểm tra tốc độ (speeding) tiếp tục hoạt động độc lập với cấu hình zone
- Khi EasyOCR chưa được cài đặt: log warning và trả về `None` — **không crash**
- Chức năng "Làm mới" thủ công trên `ViolationsList` tiếp tục hoạt động via HTTP REST
- Filter trạng thái trên `ViolationsList` tiếp tục hoạt động via HTTP REST
- Nhiều camera/đường vẫn có `camera_id` riêng biệt không trùng nhau sau khi đổi sang `idx+1`

**Lưu ý về Preservation của BUG 2:** Sau khi xóa mock zone, nếu DB không có zone → hệ thống sẽ KHÔNG phát hiện vi phạm đèn đỏ. Đây là behavior đúng (không phải regression).

---

## Hypothesized Root Cause

### BUG 1

1. **Thiếu bước upload trong pipeline**: `_run_anpr_and_push()` (closure trong `process_single_frame()`) chỉ gọi `self.anpr_engine.read_license_plate()` rồi gọi `self._push_violations_to_queue()` — không có bước crop + upload MinIO ở giữa.
2. **`_push_violations_to_queue()` không nhận frame**: Hàm này chỉ serialize các field có trong dict `v`, không có `evidence_image_url` nào được thêm vào trước đó.
3. **MinIO upload chạy đồng bộ có thể block**: Nếu upload synchronous trong ANPR thread, sẽ làm chậm pipeline nhưng không crash — rủi ro chấp nhận được vì ANPR thread đã tách khỏi video loop.

### BUG 2

1. **Mock zone được tạo trong constructor cho mục đích testing**: Đây là code test được commit nhầm vào production.
2. **Thứ tự khởi tạo sai**: Mock zone được tạo trước khi `_load_zones_from_db()` được gọi (trong `AnalyzeOnRoad.__init__()`), nhưng ngay cả khi `_load_zones_from_db()` ghi đè zone thực tế, `is_red_light_on=True` vẫn tồn tại từ mock.

### BUG 3

1. **`equalizeHist` không đủ cho ảnh có độ phân giải thấp**: Khi biển số chiếm diện tích nhỏ trong frame 600×400, ký tự quá nhỏ cho EasyOCR nhận diện.
2. **Thiếu upscaling**: Không có bước phóng to ảnh trước khi OCR — tiêu chuẩn thực tế là upscale 2-4x trước EasyOCR cho biển số nhỏ.
3. **Thiếu denoising**: Ảnh từ video nén thường có JPEG artifact — cần làm mượt trước OCR.

### BUG 4

1. **Component dùng polling thủ công**: `ViolationsList` chỉ gọi `fetchViolations()` trong `useEffect([statusFilter])` — không có logic subscribe WebSocket nào.
2. **Hook `useWebSocket` đã có sẵn** nhưng chưa được import vào component này.

### BUG 5

1. **Hai context khác nhau về "ID của camera"**: Backend dùng hash của tên file (để tạo unique ID không đổi khi restart) nhưng hash không deterministic và không match với index. Frontend dùng index vì đó là cách tự nhiên nhất để map road → camera.
2. **Không có source of truth**: Không có API endpoint trả về `camera_id` thực tế của backend cho frontend sử dụng.

---

## Correctness Properties

Property 1: Bug Fix — evidence_image_url được upload trước khi push queue

_For any_ vi phạm mới được phát hiện có bounding box hợp lệ (x1 < x2, y1 < y2, nằm trong frame), hàm `_run_anpr_and_push()` sau khi fix SHALL crop frame theo bounding box, upload lên MinIO, và thêm trường `evidence_image_url` vào payload trước khi gọi `_push_violations_to_queue()`.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Bug Fix — ViolationEngine khởi tạo không có mock zone

_For any_ lần khởi tạo `AnalyzeOnRoadBase.__init__()` sau khi fix, `violation_engine.zones["red_light"]` SHALL là `None` và `violation_engine.is_red_light_on` SHALL là `False` trước khi `_load_zones_from_db()` được gọi.

**Validates: Requirements 2.5, 2.6**

Property 3: Bug Fix — camera_id nhất quán

_For any_ road name ở vị trí `idx` trong `settings_metric_transport.PATH_VIDEOS`, `camera_id` tính bởi backend sau khi fix SHALL bằng `idx + 1`, khớp với giá trị `cameraId` mà `ZoneConfig.tsx` dùng để lưu zone.

**Validates: Requirements 2.14, 2.15**

Property 4: Preservation — upload failure không làm mất vi phạm

_For any_ trường hợp MinIO không khả dụng (exception khi gọi `upload_road_frame()`), `_push_violations_to_queue()` SHALL vẫn được gọi với payload đầy đủ các trường cũ, với `evidence_image_url = null`, và không raise exception ra ngoài ANPR thread.

**Validates: Requirements 3.2**

Property 5: Preservation — speeding detection độc lập với zone

_For any_ trạng thái zone của `ViolationEngine` (tất cả zones là `None`, không có zone nào active), `_check_speeding()` SHALL tiếp tục trả về `True` khi xe vượt ngưỡng tốc độ và `violation_type = "speeding"` SHALL được thêm vào danh sách vi phạm.

**Validates: Requirements 3.5**

---

## Fix Implementation

### BUG 1 — Thêm MinIO upload vào ANPR thread

**File**: `backend/app/services/road_services/analyze_on_road_base.py`

**Function**: `process_single_frame()` → closure `_run_anpr_and_push()`

**Flow sau khi fix:**

```
BEFORE (buggy):
  _run_anpr_and_push(frame, violations):
    FOR each violation:
      plate = anpr_engine.read_license_plate(frame, v["box"])
      v["license_plate"] = plate
    _push_violations_to_queue(violations)

AFTER (fixed):
  _run_anpr_and_push(frame, violations):
    FOR each violation:
      plate = anpr_engine.read_license_plate(frame, v["box"])
      v["license_plate"] = plate
      
      # NEW: crop và upload evidence image
      evidence_url = _crop_and_upload_evidence(frame, v["box"], v["camera_id"])
      v["evidence_image_url"] = evidence_url  # None nếu upload thất bại
    
    _push_violations_to_queue(violations)
```

**Hàm mới cần thêm vào `AnalyzeOnRoadBase`:**

```python
def _crop_and_upload_evidence(
    self,
    frame: np.ndarray,
    box: tuple,           # (x1, y1, x2, y2)
    camera_id: int,
    margin: float = 0.05  # 5% padding quanh bounding box
) -> Optional[str]:
    """
    Crop vùng xe vi phạm từ frame và upload lên MinIO.
    Trả về URL ảnh trên MinIO, hoặc None nếu upload thất bại.
    Hàm này chạy trong ANPR ThreadPoolExecutor — không block video loop.
    """
    FUNCTION _crop_and_upload_evidence(frame, box, camera_id, margin=0.05):
      TRY:
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = box
        
        # Thêm margin và clamp vào bounds của frame
        bw = x2 - x1
        bh = y2 - y1
        mx = int(bw * margin)
        my = int(bh * margin)
        cx1 = max(0, x1 - mx)
        cy1 = max(0, y1 - my)
        cx2 = min(w, x2 + mx)
        cy2 = min(h, y2 + my)
        
        # Validate crop area không rỗng
        IF cx2 <= cx1 OR cy2 <= cy1:
          RETURN None
        
        crop = frame[cy1:cy2, cx1:cx2]
        
        # Encode sang JPEG bytes (quality 85 — balance giữa size và quality)
        success, jpeg_buf = cv2.imencode('.jpg', crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
        IF NOT success:
          RETURN None
        
        # Upload lên MinIO qua singleton minio_image_store
        road_name = self.name
        url = minio_image_store.upload_road_frame(road_name, jpeg_buf.tobytes())
        RETURN url
        
      EXCEPT Exception as e:
        logger.warning("evidence upload failed for camera %s: %s", camera_id, e)
        RETURN None
    END FUNCTION
```

**Thay đổi trong `_push_violations_to_queue()` (analyze_on_road.py):**

```python
# THÊM trường evidence_image_url vào payload dict (đã được set trong _run_anpr_and_push)
payload = {
    "camera_id": v.get("camera_id"),
    "violation_type": v.get("violation_type"),
    "vehicle_track_id": v.get("vehicle_track_id"),
    "license_plate": v.get("license_plate"),
    "confidence": v.get("confidence"),
    "timestamp": v.get("timestamp"),
    "evidence_image_url": v.get("evidence_image_url"),  # NEW — None nếu upload failed
}
```

**Import cần thêm vào `analyze_on_road_base.py`:**

```python
from utils.minio_image_store import minio_image_store
```

---

### BUG 2 — Xóa mock zone khỏi constructor

**File**: `backend/app/services/road_services/analyze_on_road_base.py`

**Function**: `AnalyzeOnRoadBase.__init__()`

**Specific Changes**: Xóa 4 dòng tạo mock zone:

```python
# XÓA HOÀN TOÀN — đây là code test sai còn lại trong production:
# bx, by, bw, bh = self.region_bbox
# mock_red_light_zone = [(bx, by + bh//2), (bx + bw, by + bh//2), (bx + bw, by + bh), (bx, by + bh)]
# self.violation_engine.set_zone("red_light", mock_red_light_zone)
# self.violation_engine.set_red_light_status(True)
```

Sau khi xóa, `ViolationEngine` được khởi tạo với trạng thái mặc định đúng: tất cả zones là `None`, `is_red_light_on = False`. Zone thực tế sẽ được load từ DB bởi `_load_zones_from_db()` trong `AnalyzeOnRoad.__init__()`.

---

### BUG 3 — Cải thiện preprocessing trong ANPREngine

**File**: `backend/app/core/anpr.py`

**Function**: `_ocr_on_region()`

**Current flow (buggy):**
```
_ocr_on_region(region):
  gray = cvtColor(region, BGR2GRAY)
  gray = equalizeHist(gray)
  results = reader.readtext(gray)
```

**Fixed flow:**
```
FUNCTION _ocr_on_region_fixed(region):
  IF region IS NULL OR region.size == 0:
    RETURN None

  # Step 1: Upscale nếu ảnh quá nhỏ (biển số < 60px chiều rộng)
  h, w = region.shape[:2]
  IF w < 120:
    scale = max(2.0, 120.0 / w)  -- ít nhất 2x, đủ để chiều rộng >= 120px
    region = cv2.resize(region, (int(w * scale), int(h * scale)), 
                        interpolation=cv2.INTER_CUBIC)

  # Step 2: Chuyển sang grayscale
  gray = cvtColor(region, BGR2GRAY)

  # Step 3: CLAHE thay vì equalizeHist (bảo toàn local contrast tốt hơn)
  clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
  gray = clahe.apply(gray)

  # Step 4: Gaussian blur nhẹ để giảm JPEG noise
  gray = cv2.GaussianBlur(gray, (3, 3), 0)

  # Step 5: Sharpen để tăng rõ nét ký tự
  kernel = np.array([[-1,-1,-1], [-1, 9,-1], [-1,-1,-1]])
  gray = cv2.filter2D(gray, -1, kernel)

  results = reader.readtext(gray, detail=1, paragraph=False,
                            allowlist='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ')
  ...
END FUNCTION
```

**Lưu ý**: Thêm `allowlist` vào `readtext()` để giới hạn ký tự nhận diện về alphanumeric — giảm false positive.

---

### BUG 4 — Kết nối ViolationsList với WebSocket

**File**: `frontend/src/pages/ViolationsList.tsx`

**Changes Required:**

1. **Import `useWebSocket` hook** và type `Violation`
2. **Thêm WebSocket URL vào `endpoints`** trong `config.ts`:
   ```typescript
   violationsWs: `${apiConfig.API_WS_BASE}/road/ws/violations`,
   ```
3. **Trong component `ViolationsList`**: Subscribe WebSocket và prepend violation mới vào state

**Pseudocode:**

```
FUNCTION ViolationsList():
  [violations, setViolations] = useState([])
  [loading, setLoading] = useState(true)
  [statusFilter, setStatusFilter] = useState("")
  
  token = localStorage.getItem("access_token")
  
  # WebSocket subscription — THÊM MỚI
  { data: wsData, isConnected, error: wsError } = useWebSocket(
    endpoints.violationsWs,
    { authToken: token, maxReconnectAttempts: 10 }
  )
  
  # Khi nhận violation mới từ WebSocket
  useEffect(() => {
    IF wsData IS NOT NULL:
      newViolation = wsData as Violation
      
      # Chỉ prepend nếu không có filter đang active (để không phá vỡ filter UX)
      # Hoặc nếu violation mới match với filter hiện tại
      IF statusFilter == "" OR newViolation.status == statusFilter:
        setViolations(prev => [newViolation, ...prev])
  }, [wsData])
  
  # fetchViolations() giữ nguyên — dùng cho initial load và manual refresh
  ...
END FUNCTION
```

**Hiển thị trạng thái kết nối WebSocket:**

```tsx
{/* Thêm indicator kết nối realtime vào header */}
<span className="flex items-center gap-1 text-xs text-muted-foreground">
  {isConnected
    ? <span className="text-green-500">● Realtime</span>
    : <span className="text-yellow-500">● Offline</span>}
</span>
```

---

### BUG 5 — Thống nhất công thức camera_id

**File**: `backend/app/services/road_services/analyze_on_road_base.py`

**Function**: `AnalyzeOnRoadBase.__init__()`

**Current (buggy):**
```python
cam_id = abs(hash(self.name)) % (10 ** 4)
```

**Fixed:**
```python
# Dùng index 1-based trong PATH_VIDEOS — nhất quán với ZoneConfig.tsx frontend
try:
    cam_idx = settings_metric_transport.PATH_VIDEOS.index(self.path_video)
    cam_id = cam_idx + 1  # 1-based: video[0] → camera_id=1, video[1] → camera_id=2, ...
except ValueError:
    # Fallback cho video không nằm trong PATH_VIDEOS (ví dụ: stream URL mới)
    # Dùng hash nhưng offset cao để tránh trùng với range 1-len(PATH_VIDEOS)
    cam_id = abs(hash(self.name)) % (10 ** 4) + len(settings_metric_transport.PATH_VIDEOS)
    logger.warning(
        "Video '%s' không tìm thấy trong PATH_VIDEOS. Dùng fallback camera_id=%d",
        self.path_video, cam_id
    )
```

**Tại sao `path_video` chứ không phải `name`?** Vì `PATH_VIDEOS` chứa đường dẫn đầy đủ và `self.path_video` là giá trị được truyền vào — đảm bảo match chính xác không cần normalize tên file.

**Frontend — không cần thay đổi**: `ZoneConfig.tsx` đã dùng `idx + 1` đúng rồi. Sau khi fix backend, hai bên sẽ tự động nhất quán.

---

## Testing Strategy

### Validation Approach

Pipeline kiểm tra 2 giai đoạn: (1) Surface counterexample trên code **CHƯA fix** để xác nhận root cause, (2) Verify fix đúng và preserve hành vi cũ.

---

### Exploratory Bug Condition Checking

**Mục tiêu**: Chạy trên code CHƯA fix để quan sát lỗi và xác nhận root cause analysis.

**Test Cases:**

1. **BUG 1 Exploration** — Kiểm tra payload thiếu `evidence_image_url` (sẽ fail trên code chưa fix):
   - Tạo mock `ViolationEngine` trả về một violation với `box=(10,10,100,100)`
   - Gọi `_push_violations_to_queue()` sau khi ANPR chạy xong
   - Assert `payload["evidence_image_url"]` tồn tại → **sẽ fail** (KeyError hoặc None)

2. **BUG 2 Exploration** — Kiểm tra mock zone sau `__init__()` (sẽ fail trên code chưa fix):
   - Khởi tạo `AnalyzeOnRoadBase` với một video path hợp lệ
   - Assert `violation_engine.zones["red_light"] is None` → **sẽ fail** (mock zone đã được set)
   - Assert `violation_engine.is_red_light_on == False` → **sẽ fail** (True từ mock)

3. **BUG 5 Exploration** — Kiểm tra camera_id không khớp (sẽ fail trên code chưa fix):
   - Tạo analyzer với `PATH_VIDEOS[0]` (index 0, expected `camera_id=1`)
   - Assert `violation_engine.camera_id == 1` → **sẽ fail** (`abs(hash("Văn Quán")) % 10000` ≠ 1)

**Expected Counterexamples:**
- BUG 1: `KeyError: 'evidence_image_url'` hoặc payload với `evidence_image_url` không tồn tại
- BUG 2: `violation_engine.zones["red_light"]` là `np.array(...)` thay vì `None`
- BUG 5: `camera_id` là giá trị hash không thể đoán trước, không phải 1

---

### Fix Checking

**Mục tiêu**: Sau khi fix, verify hành vi đúng với tất cả input thuộc bug condition.

```
FOR ALL violation WHERE isBugCondition_1(violation):
  result_payload = run_anpr_and_push_fixed(violation, frame)
  ASSERT "evidence_image_url" IN result_payload
  ASSERT result_payload["evidence_image_url"] starts_with "http"
         OR result_payload["evidence_image_url"] IS NULL  -- MinIO down case
END FOR

FOR ALL analyzer_instance WHERE isBugCondition_2(analyzer.violation_engine):
  ASSERT analyzer.violation_engine.zones["red_light"] IS NULL
  ASSERT analyzer.violation_engine.is_red_light_on == False
END FOR

FOR ALL (path_video, expected_id) in zip(PATH_VIDEOS, range(1, n+1)):
  analyzer = AnalyzeOnRoadBase(path_video=path_video, ...)
  ASSERT analyzer.violation_engine.camera_id == expected_id
END FOR
```

---

### Preservation Checking

**Mục tiêu**: Verify hành vi KHÔNG bị thay đổi với input không thuộc bug condition.

```
FOR ALL violation WHERE isBugCondition_1 is False (MinIO unavailable):
  result_payload = run_anpr_and_push_fixed(violation, frame)
  ASSERT "evidence_image_url" IN result_payload
  ASSERT result_payload["evidence_image_url"] IS NULL  -- graceful fallback
  ASSERT violation được ghi vào Redis queue  -- không mất vi phạm
END FOR

FOR ALL frame WITH speeds[track_id] > speed_limit * 1.2 for N consecutive readings:
  violations = violation_engine_fixed.process_frame_tracking(...)
  ASSERT any(v["violation_type"] == "speeding" for v in violations)
  -- speeding detection không bị ảnh hưởng bởi zone removal
END FOR
```

**Testing Approach cho Preservation**: Property-based testing phù hợp cho BUG 5 (có thể generate nhiều road names và verify formula nhất quán) và BUG 1 (generate random bounding boxes và verify upload failure path).

**Test Cases:**

1. **MinIO failure preservation** (BUG 1): Mock `minio_image_store.upload_road_frame` throw exception → verify vi phạm vẫn được push với `evidence_image_url=null`
2. **Speeding preservation** (BUG 2): Sau khi xóa mock zone, set speed > limit cho N frames → verify `speeding` vi phạm vẫn được detect
3. **Manual refresh preservation** (BUG 4): Verify `fetchViolations()` vẫn hoạt động độc lập với WebSocket state
4. **camera_id range preservation** (BUG 5): Verify 5 camera IDs sau fix là `[1, 2, 3, 4, 5]` — không trùng nhau

---

### Unit Tests

- Test `_crop_and_upload_evidence()` với: bounding box hợp lệ, box ngoài bounds frame, frame None, MinIO exception
- Test `AnalyzeOnRoadBase.__init__()`: verify `zones["red_light"] is None` và `is_red_light_on == False` sau init
- Test `_ocr_on_region()` với ảnh nhỏ (< 60px wide): verify upscaling được áp dụng
- Test `camera_id` formula: verify `PATH_VIDEOS[0]` → `camera_id=1`, `PATH_VIDEOS[4]` → `camera_id=5`
- Test `ViolationsList` WebSocket effect: khi `wsData` thay đổi, violation mới được prepend vào state

### Property-Based Tests

- **Property 3 (camera_id)**: Generate `idx in range(len(PATH_VIDEOS))` → `analyzer.violation_engine.camera_id == idx + 1` luôn đúng
- **Property 4 (upload failure)**: Generate random exceptions từ MinIO → payload luôn được push, không bao giờ raise ra ngoài thread
- **Property 5 (speeding)**: Generate `speed > limit * 1.2` với N lần liên tiếp → `speeding` violation luôn được detect bất kể zone state

### Integration Tests

- End-to-end: Chạy `AnalyzeOnRoad` với video test, verify DB nhận vi phạm với `evidence_image_url` khác null
- Zone loading: Lưu zone qua frontend với `camera_id=1`, verify backend load được zone đó
- Realtime: Publish vi phạm vào Redis `violations:alerts`, verify `ViolationsList` cập nhật không cần refresh
- ANPR: Test với ảnh biển số thực tế có độ phân giải thấp, verify tỷ lệ nhận diện cải thiện sau preprocessing fix
