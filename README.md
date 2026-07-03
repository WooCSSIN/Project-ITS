<div align="center">

# 🚦 Hệ Thống Giao Thông Thông Minh (ITS)

**Nền tảng giám sát, phân tích giao thông đô thị ứng dụng AI theo thời gian thực**

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0-3178C6?style=for-the-badge&logo=typescript&logoColor=white)](https://typescriptlang.org)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://docker.com)
[![License](https://img.shields.io/badge/License-AGPL--3.0-red?style=for-the-badge)](LICENSE)

**Tác giả:** Hà Nhật Nguyên Vũ — vuhnn6145@gmail.com

*Chuyên đề Hệ thống Giao thông Thông minh — 2026*

</div>

---

## 📖 Tổng quan

**Smart Transportation System (ITS)** là hệ thống phân tích giao thông đô thị ứng dụng AI, xây dựng theo kiến trúc microservices. Hệ thống xử lý song song video từ **5 camera** giao thông tại Hà Nội, cung cấp dữ liệu đếm lưu lượng, ước tính vận tốc phương tiện, phát hiện vi phạm tự động, và hỗ trợ điều hành qua dashboard quản trị cùng trợ lý AI ngôn ngữ tự nhiên.

---

## Architecture Overview

![](./.github/architecture_system.png)

---

## Short Demo


---

## ✨ Tính năng chính

### 🔍 AI Nhận diện & Phân tích phương tiện
- **YOLOv8 custom-trained** cho giao thông Việt Nam — nhận diện ô tô, xe máy
- **Theo dõi đa đối tượng** — ByteTrack (CPU) / BoT-SORT (GPU với ReID)
- **Đo tốc độ thực tế** — Homography Transform (pixel → mét), làm mượt EMA giảm nhiễu
- **Phát hiện vi phạm tự động** — vượt tốc, vượt đèn đỏ, đỗ xe sai vị trí với cooldown debounce chống spam
- **Nhận dạng biển số (ANPR)** — EasyOCR với pipeline tiền xử lý ảnh (CLAHE → Gaussian Blur → Sharpen)

### 📡 Streaming & Realtime
- **WebRTC low-latency** — Truyền video P2P trực tiếp đến trình duyệt, độ trễ thấp
- **WebSocket multi-channel** — Frame video, thống kê traffic, biểu đồ time-series, chat
- **Đa camera song song** — 5 luồng camera xử lý độc lập bằng `multiprocessing`
- **Adaptive frame skipping** — Tự điều chỉnh tần suất inference theo tải CPU thực tế

### 🤖 AI Chatbot tư vấn giao thông
- Hỏi đáp **tiếng Việt** về tình trạng giao thông theo thời gian thực
- **LangGraph ReAct agent** với Google Gemini Flash — gọi tool để lấy dữ liệu live
- **Bộ nhớ ngắn hạn** per user (Redis) và **dài hạn** (PostgreSQL semantic store)
- Trả về **ảnh camera trực tiếp** từ MinIO khi người dùng yêu cầu
- Hỗ trợ **Web UI** tích hợp và **Discord Bot**

### 🛡️ Admin & Monitoring
- Dashboard giám sát **CPU / RAM / Disk** theo thời gian thực (WebSocket)
- Bật / Tắt từng luồng camera AI **độc lập** không cần restart server
- Quản lý vi phạm: xem danh sách, xác nhận, từ chối, thống kê theo loại
- **Prometheus metrics** endpoint, health check, readiness probe
- **Role-based access control** (admin / user)
- **Rate limiting** 60 req/min/IP, dead-letter queue cho vi phạm bị drop

---

## ⚡ CPU vs GPU

| Chỉ số | CPU Mode | GPU Mode (RTX 3050) |
|---|---|---|
| Tốc độ xử lý | ~5–8 FPS | **25–30 FPS** |
| Số camera đồng thời | 1–2 (giật lag) | **3–5 (mượt mà)** |
| CPU host sử dụng | 90–100% | **10–15%** |

---

## 🏗️ Tech Stack

| Layer | Công nghệ |
|---|---|
| **Frontend** | React 19 + TypeScript + Vite + TailwindCSS v4 + shadcn/ui + Recharts |
| **Backend** | FastAPI (Python 3.11) + SQLAlchemy async + Alembic |
| **AI / Vision** | YOLOv8 (Ultralytics) + ByteTrack / BoT-SORT + OpenCV + EasyOCR |
| **LLM / Chatbot** | LangGraph ReAct + LangChain + Google Gemini Flash |
| **Database** | PostgreSQL 16 |
| **Cache / Queue** | Redis 7 (AOF + RDB persistence, Pub/Sub) |
| **Object Storage** | MinIO (S3-compatible) |
| **Reverse Proxy** | Nginx Alpine |
| **Container** | Docker Compose |
| **Notifications** | Discord Bot (aiohttp async) + Telegram (optional) |

---

## 🗂️ Cấu trúc dự án

```
Project ITS/
├── backend/
│   ├── app/
│   │   ├── ai_models/          # YOLOv8 weights (.pt, .onnx, .mnn, OpenVINO, NCNN...)
│   │   ├── api/v1/             # FastAPI routers (auth, road, chatbot, admin, monitoring)
│   │   ├── core/               # Config, ANPR engine, ViolationEngine, Rate limiter
│   │   ├── models/             # SQLAlchemy ORM (users, violations, traffic_histories, chat)
│   │   ├── services/
│   │   │   ├── road_services/  # Video analysis, ViolationWorker, TrafficHistoryWorker
│   │   │   └── chat_services/  # LangGraph chatbot agent + tools
│   │   ├── utils/              # JWT, MinIO, WebRTC, polygon utils
│   │   └── main.py
│   ├── alembic/                # Database migrations
│   ├── tests/                  # Unit tests
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── pages/              # LoginPage, AnalyticsPage, ChatPage, Admin pages
│   │   ├── hooks/              # useWebSocket, useWebRTC
│   │   └── modules/features/   # Traffic, chat, auth, video modules
│   └── vite.config.ts
├── nginx/nginx.conf
├── docker-compose.yml
└── ARCHITECTURE.md             # Tài liệu kiến trúc chi tiết
```

---

## 🚀 Cài đặt & Chạy

### Yêu cầu
- Docker Desktop (WSL 2 trên Windows)
- *(Tùy chọn)* NVIDIA GPU + NVIDIA Container Toolkit để chạy GPU mode
- Python 3.11+ & Node.js 18+ (chỉ cần cho manual setup)

### Docker (Khuyến nghị)

**Bước 1 — Cấu hình môi trường**

```powershell
# Windows PowerShell
Copy-Item backend/.env.example backend/.env
```

Mở `backend/.env` và điền: `DATABASE_PASSWORD`, `JWT_SECRET_KEY`, `GOOGLE_API_KEY`, v.v.

**Bước 2 — Tải video test**

```bash
cd backend/app
gdown --folder https://drive.google.com/drive/folders/1gkac5U5jEs174p7V7VC3rCmgvO_cVwxH
```

**Bước 3 — Khởi động**

```bash
# CPU mode (mặc định)
docker compose up --build -d

# GPU mode (cần NVIDIA Container Toolkit, đặt GPU_ENABLED=true trong .env)
docker compose up --build -d
```

| Dịch vụ | URL |
|---|---|
| Frontend | http://localhost |
| Backend API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| MinIO Console | http://localhost:9001 |

### Manual Setup

```bash
# Backend
cd backend
pip install -r requirements_cpu.txt    # hoặc requirements_gpu.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Frontend
cd frontend
pnpm install
pnpm run dev
```

---

## 🔌 API chính (v1)

**Base prefix:** `/api/v1`

### REST

| Module | Endpoint | Mô tả |
|---|---|---|
| **Auth** | `POST /auth/register` | Đăng ký tài khoản |
| | `POST /auth/login` | Đăng nhập, nhận JWT |
| | `GET /auth/me` | Thông tin user hiện tại |
| **Traffic** | `GET /road/roads_name` | Danh sách tuyến đường |
| | `GET /road/info/{road}` | Thống kê traffic realtime |
| | `GET /road/history/{road}` | Lịch sử lưu lượng |
| | `POST /road/webrtc/offer/{road}` | Thiết lập WebRTC session |
| **Chatbot** | `POST /chatbot/chat` | Chat (có auth) |
| | `POST /chatbot/chat_no_auth` | Chat (không auth, per-IP thread) |
| **Admin** | `GET /admin/resources` | CPU / RAM / Disk server |
| | `GET /admin/traffic/status` | Trạng thái các luồng camera |
| | `POST /admin/traffic/roads/{road}/start` | Bật camera |
| | `POST /admin/traffic/roads/{road}/stop` | Tắt camera |
| | `GET /admin/violations` | Danh sách vi phạm (phân trang, lọc) |
| | `PATCH /admin/violations/{id}/status` | Xác nhận / từ chối vi phạm |
| | `GET /admin/violations/stats` | Thống kê vi phạm |
| **Monitoring** | `GET /health` | Liveness check |
| | `GET /ready` | Readiness check |
| | `GET /health/detailed` | Trạng thái chi tiết các component |
| | `GET /metrics` | Prometheus metrics |

### WebSocket / WebRTC

```
WS  /road/ws/frames/{road}      → JPEG frame stream realtime
WS  /road/ws/info/{road}        → Thống kê traffic (count, speed, status)
WS  /road/ws/chart/{road}       → Time-series data cho biểu đồ
WS  /chatbot/ws/chat            → Chat streaming
WS  /admin/ws/resources         → CPU/RAM/Disk realtime
```

---

## 🔐 Xác thực

```http
# HTTP Header
Authorization: Bearer <TOKEN>

# WebSocket query param
?token=<TOKEN>
```

Admin endpoints yêu cầu `role_id = 0`.

---

## 🤖 Discord Bot

```env
# backend/.env
DISCORD_BOT_TOKEN=your_token_here
DISCORD_ALERTS_ENABLED=true
```

| Lệnh | Mô tả |
|---|---|
| `!giaothong <câu hỏi>` | Hỏi AI về tình trạng giao thông |
| `!help_its` | Hướng dẫn sử dụng |
| `@mention bot` | Chat trực tiếp trong kênh bất kỳ |

---

## 📊 5 Tuyến đường giám sát (Hà Nội)

| Tuyến | Giới hạn tốc độ | Ngưỡng đông / tắc |
|---|---|---|
| Văn Quán | 40 km/h | 8 / 15 xe |
| Nguyễn Văn Trỗi | 60 km/h | 12 / 23 xe |
| Nguyễn Trãi | 60 km/h | 12 / 22 xe |
| Ngã Tư Sở | 40 km/h | 35 / 47 xe |
| Đường Láng | 60 km/h | 12 / 20 xe |

---

## 📚 Tài liệu thêm

- [ARCHITECTURE.md](./ARCHITECTURE.md) — Kiến trúc chi tiết, luồng dữ liệu, mô tả từng module
- [Swagger UI](http://localhost:8000/docs) — API reference đầy đủ (khi chạy local)

---

## Requirements

- Docker Desktop with WSL 2 (recommended)
- NVIDIA GPU + NVIDIA Container Toolkit (optional, for GPU mode)
- Python 3.11+ (for manual setup only)
- Node.js 18+ (for manual setup only)

---

## MinIO Object Storage

MinIO lưu trữ ảnh bằng chứng vi phạm và frames camera, phân phối qua public URL.

| Service | URL |
|---|---|
| MinIO Console | http://localhost:9001 |
| MinIO API | http://localhost:9000 |

---

<div align="center">

Made with ❤️ by **Hà Nhật Nguyên Vũ**

</div>
