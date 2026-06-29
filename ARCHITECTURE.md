# Kiến Trúc Hệ Thống ITS (Intelligent Transportation System)

> **Phiên bản:** 1.0.0 | **Cập nhật:** 2026-06-29

---

## Sơ Đồ Kiến Trúc Hệ Thống

![Architecture ITS](.github/architecture_system.png)

---

## 1. Tổng quan

Hệ thống giám sát giao thông thông minh theo thời gian thực, tích hợp:
- Phân tích video từ 5 camera giao thông (Hà Nội)
- Phát hiện và đếm phương tiện bằng AI (YOLOv8)
- Đo tốc độ xe qua Homography Transform
- Phát hiện vi phạm tự động (vượt tốc, đèn đỏ, đỗ xe sai)
- Nhận dạng biển số xe (ANPR - EasyOCR)
- Chatbot AI tư vấn giao thông (Google Gemini)
- Dashboard quản trị theo thời gian thực

---

## 2. Stack Công Nghệ

| Layer | Công nghệ |
|-------|-----------|
| **Frontend** | React 19 + TypeScript + Vite + TailwindCSS v4 + shadcn/ui |
| **Backend** | FastAPI (Python) + SQLAlchemy async + Alembic |
| **AI / Vision** | YOLOv8 (Ultralytics) + OpenCV + EasyOCR |
| **LLM / Chatbot** | LangGraph + LangChain + Google Gemini Flash |
| **Database** | PostgreSQL 16 |
| **Cache / Queue** | Redis 7 (AOF + RDB persistence) |
| **Object Storage** | MinIO |
| **Reverse Proxy** | Nginx Alpine |
| **Container** | Docker Compose |
| **Notifications** | Discord Bot + Telegram Bot (optional) |

---

## 3. Sơ Đồ Kiến Trúc Tổng Thể

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT (Browser)                         │
│  React SPA: Dashboard | Chat | Analytics | Admin | Profile      │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP / WebSocket
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      NGINX :80  (Reverse Proxy)                 │
│  /api/v1/road/ws/*  ──► WebSocket (video/traffic)               │
│  /api/v1/chatbot/ws/ ─► WebSocket (chatbot)                     │
│  /api/v1/admin/ws/  ──► WebSocket (system metrics)              │
│  /api/*             ──► HTTP REST → backend:8000                │
│  /                  ──► SPA     → frontend:80                   │
└───────────┬─────────────────────────────────────────────────────┘
            │
   ┌────────┴──────────────────────────────────────┐
   │                                               │
   ▼                                               ▼
```
```
┌────────────────────────────────┐     ┌──────────────────────────┐
│    FastAPI Backend :8000       │     │   Inference Server (GPU) │
│                                │     │  batch_inference_server  │
│  Middleware:                   │     │  YOLOv8 batch infer      │
│   RequestIDMiddleware          │     │  (optional, GPU only)    │
│   RateLimitMiddleware (60/min) │     └──────────┬───────────────┘
│   CORSMiddleware               │                │
│                                │                │ Redis (frames queue)
│  Routers (REST + WS):          │                │
│   /auth    → api_auth          │◄───────────────┘
│   /        → api_user          │
│   /road    → api_road          │
│   /chatbot → api_chatbot       │
│   /        → api_chat_history  │
│   /admin   → api_admin         │
│   /        → api_monitoring    │
│                                │
│  Background Workers:           │
│   AnalyzeOnRoadForMultiProc    │
│   TrafficHistoryWorker         │
│   ViolationWorker (subprocess) │
│   ChatBotAgent (LangGraph)     │
└────────────┬───────────────────┘
             │
   ┌─────────┼──────────┬──────────────┐
   ▼         ▼          ▼              ▼
┌──────┐  ┌──────┐  ┌───────┐  ┌──────────┐
│ PgSQL│  │Redis │  │ MinIO │  │ Gemini   │
│:5432 │  │:6379 │  │:9000  │  │ API      │
└──────┘  └──────┘  └───────┘  └──────────┘
```

---

## 4. Docker Services

| Container | Image | Port | Tài nguyên | Mô tả |
|-----------|-------|------|------------|-------|
| `sts-database` | postgres:16-alpine | 5433→5432 | — | PostgreSQL, encoding UTF8 |
| `sts-redis` | redis:7-alpine | 6379 | 512MB maxmemory | AOF + RDB persistence, LRU eviction |
| `sts-minio` | minio/minio:latest | 9000 (API), 9001 (Console) | — | Object storage cho evidence images |
| `sts-backend` | custom (Dockerfile) | 8000 | CPU 4 core, RAM 4GB | FastAPI app chính |
| `sts-inference` | custom (Dockerfile) | — | GPU (NVIDIA all) | Batch inference server (optional) |
| `sts-frontend` | custom (Dockerfile) | 5173→80 | — | React SPA served by Nginx |
| `sts-nginx` | nginx:alpine | 80 | — | Reverse proxy tổng |

**Network:** `sts-net` (bridge)  
**Volumes:** `pgdata`, `minio-data`, `redis-data`

---

## 5. Backend — Cấu Trúc Chi Tiết

### 5.1 API Layer (`/app/api/v1/`)

| File | Prefix | Protocol | Chức năng chính |
|------|--------|----------|-----------------|
| `api_auth.py` | `/api/v1/auth` | HTTP | Đăng ký, đăng nhập (JWT HS256 + httponly cookie), lấy thông tin user hiện tại |
| `api_user.py` | `/api/v1` | HTTP | CRUD quản lý người dùng (admin only) |
| `api_road.py` | `/api/v1/road` | HTTP + WS | Danh sách đường, thống kê traffic, stream video (WS + WebRTC), lịch sử |
| `api_chatbot.py` | `/api/v1/chatbot` | HTTP + WS | Chat với AI (có auth / không auth), WebSocket streaming |
| `api_chat_history.py` | `/api/v1` | HTTP | Lấy lịch sử chat của user |
| `api_admin.py` | `/api/v1/admin` | HTTP + WS | Tài nguyên hệ thống, điều khiển camera, WebSocket metrics realtime |
| `api_monitoring.py` | `/api/v1` | HTTP | Health check, readiness probe, Prometheus metrics |

**WebSocket Endpoints:**
```
WS /api/v1/road/ws/frames/{road_name}  → Binary JPEG frames realtime
WS /api/v1/road/ws/info/{road_name}    → JSON traffic stats (count, speed, status)
WS /api/v1/road/ws/chart/{road_name}   → JSON time-series data cho Recharts
WS /api/v1/chatbot/ws/chat             → Streaming chat response
WS /api/v1/admin/ws/resources          → CPU/RAM/Disk metrics realtime
```

### 5.2 Core Layer (`/app/core/`)

| Module | Class | Chức năng |
|--------|-------|-----------|
| `config.py` | `SettingServer` | Database URL, Redis, MinIO, JWT, logging config |
| `config.py` | `SettingMetricTransport` | 5 camera configs: ROI polygon, homography matrix, video path, model path |
| `config.py` | `SettingChatBot` | LLM lazy-load (Gemini Flash) |
| `config.py` | `SettingViolation` | Redis queue key, speed limits, worker toggle |
| `config.py` | `SettingSecurity` | CORS, rate limit, WS max connections |
| `config.py` | `SettingFeatures` | Feature flags: ANPR, Discord alerts |
| `config.py` | `TRAFFIC_THRESHOLDS` | Ngưỡng tốc độ/mật độ per-road (5 tuyến) |
| `config.py` | `SPEED_LIMITS` | Giới hạn tốc độ per-road (40–60 km/h) |
| `violation_engine.py` | `ViolationEngine` | Phát hiện 3 loại vi phạm từ tracking data |
| `anpr.py` | `ANPREngine` | YOLO LP detector + EasyOCR (CLAHE preprocessing, lazy-init) |
| `rate_limiter.py` | `RateLimitMiddleware` | Sliding window 60 req/min/IP, X-RateLimit-* headers |
| `request_id_middleware.py` | `RequestIDMiddleware` | Gắn X-Request-ID cho mỗi request (trace) |
| `security.py` | — | bcrypt hash password, JWT encode/decode |
| `logging_config.py` | — | Rotating file logger + console logger |


### 5.3 Services Layer (`/app/services/`)

#### Road Services

```
AnalyzeOnRoadBase (base class)
├── YOLOv8 model loading (best.pt custom)
├── ByteTrack / BoT-SORT tracker
├── HomographySpeedTracker
│     └── cv2.getPerspectiveTransform (pixel → mét thực tế)
│         SpeedSmoother (EMA α=0.3, giảm nhiễu tốc độ)
├── Adaptive frame skipping (CPU load aware)
└── ViolationEngine per camera

AnalyzeOnRoad (extends Base)
├── Tích hợp push violations → Redis queue
└── Gọi ANPREngine để đọc biển số khi vi phạm

AnalyzeOnRoadForMultiprocessing
├── Quản lý pool: 1 subprocess / camera (5 cameras mặc định)
├── multiprocessing.Manager → shared Dict (frame_dict, info_dict)
├── Lock per camera (thread-safe)
├── get_frame_road(road_name) → JPEG bytes
└── get_info_road(road_name) → dict {count_car, count_motor, speed_car, speed_motor, status}

TrafficHistoryWorker (async background task)
└── Định kỳ đọc info_dict → INSERT traffic_histories DB

ViolationWorker (multiprocessing.Process riêng)
├── brpop Redis violations:queue (blocking pop, timeout 1s)
├── Validate + parse JSON payload
├── INSERT violations table (retry x3, exponential backoff)
├── Crop evidence frame → upload MinIO → cập nhật evidence_image_url
└── PUBLISH violations:alerts (Redis pub/sub) → Discord/Telegram bot

BatchInferenceServer (optional, GPU container)
├── Subscribe Redis frames channel
├── Gom batch từ nhiều cameras (max wait 40ms, batch size 5)
├── YOLOv8 batch inference trên GPU
└── Publish kết quả về Redis (InferenceClient nhận)
```

#### Chat Services

```
ChatBotAgent (LangGraph ReAct agent)
├── LLM: Google Gemini gemini-3.1-flash-lite-preview
├── Tools:
│     get_roads()              → danh sách tên đường
│     get_info_road(road)      → thống kê traffic realtime
│     get_frame_road(road)     → ảnh camera realtime (upload MinIO)
├── Short-term memory: RedisSaver (fallback InMemorySaver)
│     Thread per user_id, window 24 messages
│     Sanitize tool-call order cho Gemini constraint
├── Long-term memory: PostgresStore (semantic search)
│     Lưu khi user nói "ghi nhớ / nhớ rằng"
│     Inject vào system prompt tự động
└── @before_model: cắt ngắn lịch sử, @dynamic_prompt: inject memories
```

### 5.4 Data Models — PostgreSQL

| Bảng | Cột chính | Mô tả |
|------|-----------|-------|
| `users` | id, username, email, password (bcrypt), phone_number, role_id | 0=admin, 1=user |
| `violations` | id, camera_id, timestamp, violation_type, vehicle_track_id, license_plate, confidence, evidence_image_url, status, confirmed_by, fine_number, extra_metadata | Vi phạm giao thông |
| `traffic_histories` | id, road_name, recorded_at, avg_count_car, avg_count_motor, avg_speed_car, avg_speed_motor | Lịch sử lưu lượng |
| `chat_messages` | id, user_id, message, is_user, images (JSON), created_at | Lịch sử chat |
| `token_llm` | — | Theo dõi token LLM |

**Alembic migrations** (`/alembic/versions/`):
- `54be4477c094` — users + token_llm (initial)
- `chat_messages_001` — chat_messages table
- `traffic_histories_002` — traffic_histories table
- `chat_messages_003` — user + created_at index
- `violations_004` — violations table
- `zone_configs_005` — zone_configs table


### 5.5 Utils Layer (`/app/utils/`)

| Module | Chức năng |
|--------|-----------|
| `jwt_handler.py` | Tạo/verify JWT, FastAPI dependency `get_current_user` / `get_current_user_ws` |
| `minio_image_store.py` | Upload ảnh evidence lên MinIO, tạo presigned URL |
| `minio_retention_cleanup.py` | Auto cleanup ảnh cũ > MINIO_RETENTION_DAYS ngày |
| `polygon_utils.py` | Vectorized point-in-polygon test (nhanh hơn 50x so với cv2 loop) |
| `system_metrics.py` | psutil CPU/RAM/Disk cho admin dashboard |
| `webrtc_utils.py` | aiortc WebRTC peer connections (tạo/đóng) |
| `chatbot_utils.py` | Lưu messages vào DB, quản lý private images per thread |

---

## 6. Frontend — Cấu Trúc Chi Tiết

**Framework:** React 19 + TypeScript + Vite + TailwindCSS v4 + shadcn/ui (Radix UI)

### 6.1 Pages

| Page | Route | Mô tả |
|------|-------|-------|
| `LoginPage` | `/login` | Đăng nhập, form auth |
| `AnalyticsPage` | `/analytics` | Dashboard chính: video stream + traffic stats + chart realtime |
| `ChatPage` | `/chat` | Chat với AI chatbot |
| `ProfilePage` | `/profile` | Thông tin tài khoản |
| `AdminLayout` | `/admin` | Layout wrapper admin |
| `AdminResourcesPage` | `/admin/resources` | CPU/RAM/Disk monitoring realtime |
| `AdminRoadsPage` | `/admin/roads` | Điều khiển camera (start/stop per road) |

### 6.2 Key Components & Hooks

```
hooks/
  useWebSocket.ts     → WS client (frames / info / chart per road)
  useWebRTC.ts        → WebRTC offer/answer flow với backend
  useTrafficStore.tsx → Zustand-like store traffic data
  TrafficContext.ts   → React Context chia sẻ traffic state

services/
  chatHistoryService.ts → HTTP calls lấy lịch sử chat
  authService.ts        → login/logout/getMe

config/
  settings.ts           → API base URL, WS endpoints
  trafficThresholds.ts  → Ngưỡng màu sắc UI theo tình trạng giao thông
```

**UI Libraries:** recharts (biểu đồ), framer-motion (animation), react-markdown + rehype-highlight (tin nhắn chat), sonner (toast notifications), react-router-dom v7

---

## 7. Luồng Dữ Liệu Chính

### 7.1 Video & Traffic Monitoring

```
Video file (MP4) / RTSP stream
    │
    ├─► cv2.VideoCapture (subprocess per camera)
    │
    ├─► YOLOv8 tracking (ByteTrack CPU | BoT-SORT GPU)
    │       └─► detect: car (0), motorbike (1)
    │
    ├─► HomographySpeedTracker
    │       ├─► cv2.getPerspectiveTransform (pixel → mét)
    │       └─► SpeedSmoother EMA (α=0.3)
    │
    ├─► ViolationEngine.process_frame_tracking()
    │       ├─► speeding  → lpush Redis violations:queue
    │       ├─► red_light → lpush Redis violations:queue
    │       └─► illegal_parking → lpush Redis violations:queue
    │
    ├─► shared Dict (frame_dict, info_dict) via multiprocessing.Manager
    │
    └─► API WebSocket
            ├─► WS /road/ws/frames/{road} → Frontend video display
            ├─► WS /road/ws/info/{road}   → Frontend traffic stats
            └─► WS /road/ws/chart/{road}  → Frontend Recharts realtime
                                    │
                    TrafficHistoryWorker → INSERT traffic_histories DB
```

### 7.2 Phát Hiện Vi Phạm

```
Redis violations:queue  ◄── ViolationEngine (lpush)
    │
    └─► ViolationWorker (brpop, separate process)
            │
            ├─► ANPREngine (optional)
            │       ├─► YOLO LP detector (detect vùng biển số)
            │       └─► EasyOCR (CLAHE → GaussianBlur → Sharpen → OCR)
            │
            ├─► Crop evidence frame → MinIO upload → presigned URL
            │
            ├─► INSERT violations (PostgreSQL, retry x3)
            │
            └─► PUBLISH violations:alerts (Redis pub/sub)
                        │
                        └─► Discord Bot / Telegram Bot → send notification
```


### 7.3 AI Chatbot

```
User message
    │
    ├─► POST /chatbot/chat (HTTP)  hoặc  WS /chatbot/ws/chat (WebSocket)
    │
    └─► ChatBotAgent.get_response(user_input, user_id)
            │
            ├─► @before_model: trim/sanitize messages window (24 msgs)
            ├─► @dynamic_prompt: inject long-term memories từ PostgresStore
            │
            ├─► LangGraph ReAct agent invoke
            │       │
            │       ├─► LLM: Gemini Flash (langchain_google_genai)
            │       │
            │       └─► Tools (nếu cần):
            │               get_roads()         → analyzer.names (5 tuyến)
            │               get_info_road(road) → analyzer.get_info_road()
            │               get_frame_road(road)→ frame bytes → MinIO → URL
            │
            ├─► Redis RedisSaver (short-term memory, per thread_id=user_id)
            │       fallback: InMemorySaver
            │
            ├─► PostgresStore (long-term memory, semantic search)
            │       trigger: "ghi nhớ" / "nhớ rằng" / "tôi tên là"
            │
            ├─► save_message() → chat_messages DB
            │
            └─► return { message: str, image: [MinIO URLs] }
```

### 7.4 Authentication Flow

```
POST /auth/login
    │
    ├─► Verify username + bcrypt password (PostgreSQL)
    ├─► Tạo JWT HS256 (expire = ACCESS_TOKEN_EXPIRE_DAYS)
    ├─► Set httponly cookie access_token
    └─► Return Bearer token
                │
                ▼
    Subsequent requests:
    ├─► HTTP: Authorization: Bearer <token>  hoặc  cookie
    └─► WebSocket: ?token=<token> (query param)
                │
                ▼
    Dependency get_current_user / get_current_user_ws
    └─► Decode JWT → load user từ DB → inject vào handler
```

---

## 8. AI Models

### 8.1 Vehicle Detection & Tracking

- **Model:** YOLOv8 custom (trained riêng cho giao thông Việt Nam)
- **Path:** `backend/app/ai_models/model N/original model/best.pt`
- **Classes:** car (0), motorbike (1)
- **Tracker:** ByteTrack (CPU mode) / BoT-SORT (GPU mode, có ReID)
- **Export formats:** `.pt`, `.onnx` (int8), `.mnn` (int8), OpenVINO (int8), NCNN, TorchScript, TensorRT

### 8.2 License Plate Recognition (ANPR)

```
Input: JPEG crop của xe vi phạm
    │
    ├─► YOLO LP Detector (optional, LP_MODEL_PATH)
    │       └─► detect vùng biển số → crop tiếp
    │
    └─► EasyOCR Pipeline:
            1. Upscale (nếu width < 120px, scale ≥ 2x)
            2. Grayscale
            3. CLAHE (clipLimit=2.0, tileGrid=4x4)
            4. Gaussian Blur (3x3)
            5. Sharpen kernel [[-1,-1,-1],[-1,9,-1],[-1,-1,-1]]
            6. EasyOCR readtext → lấy kết quả confidence cao nhất
            7. Clean: chỉ giữ [A-Z0-9\-\.] → biển số cuối
```

### 8.3 Speed Measurement

```
Camera pixel coordinates
    │
    └─► Homography Matrix (cv2.getPerspectiveTransform)
            Source: 4 điểm ROI trên ảnh camera (pixel)
            Dest:   tọa độ mét thực tế (top-down view)
            Đường rộng ~10-12m, chiều sâu ~28-35m
                │
                ▼
            pixel displacement → mét displacement → km/h
                │
                ▼
            SpeedSmoother EMA (α=0.3) → loại bỏ nhiễu
```

---

## 9. Cấu Hình 5 Camera

| ID | Tên đường | Giới hạn tốc độ | Ngưỡng đông (c1/c2) |
|----|-----------|-----------------|---------------------|
| 0 | Văn Quán | 40 km/h | 8 / 15 xe |
| 1 | Nguyễn Văn Trỗi | 60 km/h | 12 / 23 xe |
| 2 | Nguyễn Trãi | 60 km/h | 12 / 22 xe |
| 3 | Ngã Tư Sở | 40 km/h | 35 / 47 xe |
| 4 | Đường Láng | 60 km/h | 12 / 20 xe |

**Trạng thái traffic:**
- `Thông thoáng` — số xe < c1 VÀ tốc độ TB ≥ v
- `Đông đúc` — số xe ≥ c1 HOẶC tốc độ TB < v
- `Tắc nghẽn` — số xe ≥ c2


---

## 10. Bảo Mật

| Cơ chế | Chi tiết |
|--------|---------|
| **Authentication** | JWT HS256, httponly cookie + Bearer token |
| **Password** | bcrypt hash (không lưu plaintext) |
| **Rate Limiting** | 60 req/min/IP (sliding window, in-memory deque) |
| **CORS** | Whitelist origins cụ thể (không dùng `*` khi có credentials) |
| **WebSocket** | Giới hạn 5 connections/IP, auth qua query param token |
| **Request Tracing** | X-Request-ID gắn vào mỗi request (RequestIDMiddleware) |
| **Secrets** | Qua env vars / `.env` (không commit lên git) |
| **File upload** | `client_max_body_size 100M` (Nginx), MinIO pre-signed URL |

---

## 11. Monitoring & Observability

| Endpoint | Mô tả |
|----------|-------|
| `GET /api/v1/health` | Health check cơ bản (liveness probe) |
| `GET /api/v1/ready` | Readiness probe (DB + Redis connected?) |
| `GET /api/v1/health/detailed` | Chi tiết DB, Redis, MinIO, workers |
| `GET /api/v1/metrics` | Prometheus metrics |
| `WS /api/v1/admin/ws/resources` | CPU/RAM/Disk realtime (psutil) |

**Logging:**
- Rotating file log: `logs/backend/app.log` (5MB × 5 files)
- Named logger per module (`get_logger(__name__)`)
- Chat agent log riêng: `chat_agent.log`
- Nginx access/error logs: `logs/nginx/`
- Docker JSON logs: max 20MB × 5 files (backend), 10MB × 3 files (DB/Redis)

---

## 12. Deployment

### Môi trường biến quan trọng

| Nhóm | Biến | Mặc định |
|------|------|---------|
| Database | `DATABASE_USERNAME/PASSWORD/HOST/PORT/NAME` | — |
| Auth | `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_DAYS` | HS256, 30 |
| Redis | `REDIS_URL` | `redis://localhost:6379/0` |
| MinIO | `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET` | `road-frames` |
| AI | `GPU_ENABLED`, `TRACKER_MODE`, `BATCH_INFERENCE_ENABLED` | false, bytetrack, false |
| Chatbot | `GOOGLE_API_KEY` | — (bắt buộc) |
| Violations | `VIOLATION_WORKER_ENABLED`, `DEFAULT_SPEED_LIMIT` | true, 50 km/h |
| Feature flags | `ANPR_ENABLED`, `DISCORD_ALERTS_ENABLED` | false, false |
| Security | `CORS_ALLOWED_ORIGINS`, `RATE_LIMIT_PER_MINUTE` | localhost:5173, 60 |

### Khởi động

```bash
# CPU mode (mặc định)
docker compose up -d

# GPU mode (cần NVIDIA Docker runtime)
GPU_ENABLED=true DEVICE=cuda docker compose up -d

# Scale inference server
docker compose up -d --scale inference-server=1
```

### Health checks

```bash
# Liveness
curl http://localhost:8000/api/v1/health

# Readiness (kiểm tra DB + Redis)
curl http://localhost:8000/api/v1/ready

# Detailed
curl http://localhost:8000/api/v1/health/detailed
```

---

## 13. Cấu Trúc Thư Mục

```
Project ITS/
├── backend/
│   ├── app/
│   │   ├── ai_models/model N/      # YOLOv8 weights (pt, onnx, mnn, openvino...)
│   │   ├── api/v1/                 # FastAPI routers
│   │   │   ├── api_auth.py
│   │   │   ├── api_road.py
│   │   │   ├── api_chatbot.py
│   │   │   ├── api_admin.py
│   │   │   ├── api_monitoring.py
│   │   │   └── api_user.py
│   │   ├── core/                   # Config, security, middleware, engines
│   │   │   ├── config.py
│   │   │   ├── anpr.py
│   │   │   ├── violation_engine.py
│   │   │   ├── rate_limiter.py
│   │   │   └── security.py
│   │   ├── db/                     # SQLAlchemy session, base
│   │   ├── models/                 # ORM models (users, violations, traffic...)
│   │   ├── schemas/                # Pydantic schemas
│   │   ├── services/
│   │   │   ├── road_services/      # Video analysis, violation worker, batch infer
│   │   │   └── chat_services/      # LangGraph chatbot agent
│   │   ├── utils/                  # JWT, MinIO, WebRTC, polygon utils...
│   │   ├── video_test/             # Video test files (5 tuyến đường)
│   │   └── main.py                 # FastAPI app entry point
│   ├── alembic/                    # DB migrations
│   ├── tests/                      # Unit + integration tests
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── pages/                  # LoginPage, AnalyticsPage, ChatPage, Admin...
│   │   ├── modules/features/       # Feature modules (traffic, chat, auth, video)
│   │   ├── hooks/                  # useWebSocket, useWebRTC, useTrafficStore
│   │   ├── services/               # HTTP API clients
│   │   ├── config/                 # Settings, thresholds
│   │   └── ui/                     # Shared UI components
│   ├── Dockerfile
│   └── vite.config.ts
├── nginx/
│   └── nginx.conf                  # Reverse proxy config
├── docker-compose.yml
├── .env                            # Root env (DB credentials)
└── ARCHITECTURE.md                 # File này
```

---

*Tài liệu được tạo tự động từ phân tích codebase — cập nhật khi có thay đổi kiến trúc.*
