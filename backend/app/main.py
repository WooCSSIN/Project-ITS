import os
import sys
import signal
from contextlib import asynccontextmanager
from types import FrameType
from fastapi import FastAPI
from api import v1
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from db.base import create_tables
from core.config import settings_network, settings_server
from core.logging_config import get_logger, setup_logging
from fastapi.concurrency import run_in_threadpool

os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_MSMF", settings_server.OPENCV_VIDEOIO_PRIORITY_MSMF)
os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_DSHOW", settings_server.OPENCV_VIDEOIO_PRIORITY_DSHOW)
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", settings_server.KMP_DUPLICATE_LIB_OK)

setup_logging()
logger = get_logger(__name__)

# Danh sách origins được phép CORS - nên dùng biến môi trường để linh hoạt giữa dev/prod
_allowed_origins_raw = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173")
_allowed_origins = [o.strip() for o in _allowed_origins_raw.split(",") if o.strip()]


async def _start_traffic_runtime() -> None:
    """Khởi động analyzer + worker trong threadpool để không block event loop."""
    try:
        from services.road_services.analyze_on_road_for_multi_processing import AnalyzeOnRoadForMultiprocessing
        from services.road_services.traffic_history_worker import TrafficHistoryWorker

        if v1.state.analyzer is None:
            analyzer = AnalyzeOnRoadForMultiprocessing()
            # Chạy multiprocessing trong threadpool vì nó blocking
            await run_in_threadpool(analyzer.run_multiprocessing)
            v1.state.analyzer = analyzer

        if v1.state.traffic_history_worker is None:
            worker = TrafficHistoryWorker()
            await worker.start()
            v1.state.traffic_history_worker = worker

        # Khởi động violation worker (stub hoặc thật)
        if getattr(v1.state, "violation_worker", None) is None:
            try:
                from services.road_services.violation_worker import ViolationWorker
                vw = ViolationWorker(redis_url=settings_server.REDIS_URL)
                await vw.start()
                v1.state.violation_worker = vw
            except Exception as exc:
                logger.warning("ViolationWorker not started: %s", exc)

        logger.info("Traffic runtime started successfully")
    except Exception as exc:
        if v1.state.analyzer is not None:
            try:
                v1.state.analyzer.cleanup_processes()
            except Exception:
                pass
        logger.exception("Traffic startup degraded (Redis unavailable): %s", exc)
        v1.state.analyzer = None
        v1.state.traffic_history_worker = None


async def _shutdown_traffic_runtime() -> None:
    """Dọn dẹp tài nguyên traffic khi shutdown."""
    # Đóng WebRTC peer connections
    from api.v1.api_road import active_peer_connections
    from utils.webrtc_utils import close_peer_connection
    for pc in list(active_peer_connections):
        try:
            await close_peer_connection(pc)
        except Exception:
            pass

    if getattr(v1.state, "violation_worker", None):
        try:
            await v1.state.violation_worker.stop()
        except Exception:
            logger.exception("Failed to stop violation worker")

    if v1.state.traffic_history_worker:
        try:
            await v1.state.traffic_history_worker.stop()
        except Exception:
            logger.exception("Failed to stop traffic history worker")

    if v1.state.analyzer:
        try:
            v1.state.analyzer.cleanup_processes()
        except Exception:
            logger.exception("Failed to cleanup analyzer processes")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Quản lý vòng đời ứng dụng: startup và shutdown."""
    logger.info("Creating database tables...")
    try:
        await create_tables()
        logger.info("Database tables initialized.")
    except Exception as e:
        logger.exception("Failed to initialize database tables: %s", e)
        raise

    # Khởi tạo chat agent (không block event loop vì create_agent là sync nhưng nhẹ)
    try:
        from services.chat_services.chat_bot_agent import ChatBotAgent
        from api.v1.api_chatbot import _ensure_chat_agent_initialized
        if getattr(v1.state, 'agent', None) is None:
            logger.info("Đang khởi tạo Chat Agent...")
            v1.state.agent = ChatBotAgent()
            logger.info("Khởi tạo Chat Agent thành công")
        _ensure_chat_agent_initialized()
    except Exception:
        logger.exception("Không thể khởi tạo Chat Agent")
        v1.state.agent = None

    # Khởi động traffic runtime
    await _start_traffic_runtime()

    try:
        yield
    finally:
        logger.info("Shutting down application resources...")
        await _shutdown_traffic_runtime()

        if getattr(v1.state, "agent", None):
            try:
                v1.state.agent.close()
            except Exception:
                logger.exception("Failed to close chat agent resources")


app = FastAPI(
    title="Smart Transportation System API",
    description="""
    Real-time Traffic Monitoring & AI Assistant

    API cung cấp:
    - Real-time video streaming và phân tích giao thông
    - AI Chatbot hỗ trợ thông tin giao thông
    - Analytics và metrics về lưu lượng xe
    - User authentication và management
    - Admin tools và system monitoring
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    contact={
        "name": "Hà Nhật Nguyên Vũ",
        "email": "vuhnn6145@gmail.com",
    },
)

app.add_middleware(
    CORSMiddleware,
    # Chỉ cho phép các origins cụ thể - KHÔNG dùng "*" với allow_credentials=True
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

# Rate limiting middleware - chống spam/brute-force
from core.rate_limiter import RateLimitMiddleware
app.add_middleware(RateLimitMiddleware)

# Request ID middleware - thêm SAU cùng để nó là middleware NGOÀI CÙNG
# (Starlette middleware chạy theo thứ tự LIFO: add sau = chạy đầu tiên trên request)
from core.request_id_middleware import RequestIDMiddleware
app.add_middleware(RequestIDMiddleware)

def _signal_handler(signum: int, frame: FrameType | None):
    """Xử lý Ctrl+C"""
    _ = frame
    logger.warning("Received signal %s. Stopping server...", signum)
    if v1.state.analyzer:
        v1.state.analyzer.cleanup_processes()
    sys.exit(0)

signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

@app.get(
    path='/',
    tags=["Root"],
    summary="Redirect to Frontend",
    description="Redirect người dùng đến trang Frontend"
)
def direct_home():
    return RedirectResponse(url= settings_network.URL_FRONTEND)

app.include_router(
    router= v1.api_auth.router, 
    prefix="/api/v1/auth", 
    tags=["Authentication"],
)
app.include_router(
    router= v1.api_user.router, 
    prefix="/api/v1", 
    tags=["User Management"],
)
app.include_router(
    router= v1.api_road.router, 
    prefix="/api/v1", 
    tags=["Road Monitoring"],
)
app.include_router(
    router= v1.api_chatbot.router, 
    prefix="/api/v1", 
    tags=["AI Chatbot"],
)
app.include_router(
    router= v1.api_chat_history.router,
    prefix="/api/v1",
    tags=["Chat History"],
)
app.include_router(
    router= v1.api_admin.router,
    prefix="/api/v1",
    tags=["Admin Tools"],
)
app.include_router(
    router=v1.api_monitoring.router,
    prefix="/api/v1",
    tags=["Monitoring"],
)


