import os
from dotenv import load_dotenv
import numpy as np
import cv2
from urllib.parse import quote_plus

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

load_dotenv(override=False)
DATABASE_USERNAME = os.getenv("DATABASE_USERNAME")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD")
DATABASE_PORT = os.getenv("DATABASE_PORT")
DATABASE_HOST = os.getenv("DATABASE_HOST")
DATABASE_NAME = os.getenv("DATABASE_NAME")
_DB_PASSWORD_ENCODED = quote_plus(DATABASE_PASSWORD or "")


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


class SettingServer:
    PROJECT_NAME = "FastAPI CRUD with JWT"
    DATABASE_URL = f"postgresql+asyncpg://{DATABASE_USERNAME}:{_DB_PASSWORD_ENCODED}@{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}"
    SQL_ECHO = _env_bool("SQL_ECHO", "false")
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", os.getenv("ACCESS_KEY", "minioadmin"))
    MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", os.getenv("SECRET_KEY", "minioadmin"))
    MINIO_SECURE = _env_bool("MINIO_SECURE", "false")
    MINIO_BUCKET = os.getenv("MINIO_BUCKET", "road-frames")
    MINIO_URL_EXPIRY_SECONDS = max(60, _env_int("MINIO_URL_EXPIRY_SECONDS", 3600))
    MINIO_PUBLIC_ENDPOINT = os.getenv("MINIO_PUBLIC_ENDPOINT", MINIO_ENDPOINT)
    MINIO_PUBLIC_SCHEME = os.getenv("MINIO_PUBLIC_SCHEME", "https" if MINIO_SECURE else "http")
    MINIO_IMAGE_URL_MODE = os.getenv("MINIO_IMAGE_URL_MODE", "presigned").strip().lower()
    MINIO_AUTO_SET_PUBLIC_READ = _env_bool("MINIO_AUTO_SET_PUBLIC_READ", "false")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    LOG_FILE_NAME = os.getenv("LOG_FILE_NAME", "app.log")
    LOG_FILE_MAX_BYTES = _env_int("LOG_FILE_MAX_BYTES", 5242880)
    LOG_FILE_BACKUP_COUNT = _env_int("LOG_FILE_BACKUP_COUNT", 5)
    LOG_TO_CONSOLE = _env_bool("LOG_TO_CONSOLE", "false")
    CHAT_MAX_SHORT_TERM_MESSAGES = max(6, _env_int("CHAT_MAX_SHORT_TERM_MESSAGES", 24))
    CHAT_LONG_TERM_MEMORY_LIMIT = max(1, _env_int("CHAT_LONG_TERM_MEMORY_LIMIT", 3))
    CHAT_MEMORY_DB_URI = os.getenv(
        "CHAT_MEMORY_DB_URI",
        DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://"),
    )
    OPENCV_VIDEOIO_PRIORITY_MSMF = os.getenv("OPENCV_VIDEOIO_PRIORITY_MSMF", "0")
    OPENCV_VIDEOIO_PRIORITY_DSHOW = os.getenv("OPENCV_VIDEOIO_PRIORITY_DSHOW", "1")
    KMP_DUPLICATE_LIB_OK = os.getenv("KMP_DUPLICATE_LIB_OK", "TRUE")
    # DATABASE_URL = 'postgresql+psycopg_async://neondb_owner:npg_JEOMv5puo3wz@ep-mute-glade-ad2qnbo9-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require'
    JWT_SECRET = os.getenv("JWT_SECRET_KEY")
    JWT_ALGORITHM = os.getenv("JWT_ALGORITHM")
    ACCESS_TOKEN_EXPIRE_DAYS = int(os.getenv("ACCESS_TOKEN_EXPIRE_DAYS"))

class SettingMetricTransport:
    # ── Default detection parameters (apply to all cameras unless overridden) ──
    DEFAULT_CONF: float = 0.15
    DEFAULT_IOU: float = 0.3
    DEFAULT_INFER_EVERY_N: int = 5       # Tăng từ 4 → 5: giảm CPU thêm ~20%
    DEFAULT_FRAME_SIZE: tuple = (600, 400)

    # ── Per-camera overrides (partial dict — only specify what differs from defaults) ──
    # Example: {"Ngã Tư Sở": {"conf": 0.20, "frame_size": (640, 360)}}
    CAMERA_OVERRIDES: dict = {
        # "Nguyễn Trãi":  {"conf": 0.15},
        # "Ngã Tư Sở":    {"conf": 0.15},
        # "Đường Láng":   {"conf": 0.15},
        # "Văn Phú":      {"conf": 0.15},
    }

    REGIONS = [
        # 0: Nguyễn Trãi
        np.array([[0, 400], [0, 180], [150, 70], [480, 70], [600, 260], [600, 400]]),
        # 1: Ngã Tư Sở
        np.array([[140, 400], [400, 200], [550, 200], [530, 400]]),
        # 2: Đường Láng
        np.array([[150, 400], [300, 200], [580, 200], [600, 400]]),
        # 3: Văn Phú
        np.array([[0, 400], [0, 220], [600, 180], [600, 400]]),
    ]

    PATH_VIDEOS = [
        os.path.join(BASE_DIR, "video_test", "Nguyễn Trãi.mp4"),
        os.path.join(BASE_DIR, "video_test", "Ngã Tư Sở.mp4"),
        os.path.join(BASE_DIR, "video_test", "Đường Láng.mp4"),
        os.path.join(BASE_DIR, "video_test", "Văn Phú.mp4"),
    ]

    METER_PER_PIXELS = [
                        0.020,   # 0: Nguyễn Trãi — đường 6 làn ~24m, camera nhìn từ trên
                        0.055,   # 1: Ngã Tư Sở — giao lộ rộng ~18m, ROI nhỏ hơn
                        0.025,   # 2: Đường Láng — đường 4 làn ~16m
                        0.030,   # 3: Văn Phú — đường khu dân cư ~12m
                        ]
    HOMOGRAPHY_MATRICES = [
        # 0: Nguyễn Trãi — đường 6 làn, rộng ~24m, camera overhead
        # ROI: [[0,400],[0,180],[150,70],[480,70],[600,260],[600,400]]
        # Dùng 4 góc đại diện, dst = thực tế ~24m rộng, ~35m sâu
        cv2.getPerspectiveTransform(
            np.float32([[0, 400], [0, 180], [600, 260], [600, 400]]),
            np.float32([[0, 0],   [0, 35],  [24, 35],   [24, 0]])
        ),
        # 1: Ngã Tư Sở — giao lộ, camera góc cao nhìn chéo
        # ROI: [[140,400],[400,200],[550,200],[530,400]]
        # dst ~18m rộng, ~28m sâu
        cv2.getPerspectiveTransform(
            np.float32([[140, 400], [400, 200], [550, 200], [530, 400]]),
            np.float32([[0, 0],     [0, 28],    [18, 28],   [18, 0]])
        ),
        # 2: Đường Láng — đường 4 làn, rộng ~16m
        # ROI: [[150,400],[300,200],[580,200],[600,400]]
        cv2.getPerspectiveTransform(
            np.float32([[150, 400], [300, 200], [580, 200], [600, 400]]),
            np.float32([[0, 0],     [0, 30],    [16, 30],   [16, 0]])
        ),
        # 3: Văn Phú — đường khu dân cư, rộng ~12m
        # ROI: [[0,400],[0,220],[600,180],[600,400]]
        cv2.getPerspectiveTransform(
            np.float32([[0, 400], [0, 220], [600, 180], [600, 400]]),
            np.float32([[0, 0],   [0, 25],  [12, 25],   [12, 0]])
        ),
    ]
    MODELS_PATH = os.path.join(BASE_DIR, 'ai_models', 'model N', 'original model', 'best.pt')

    # ═══════════════ Giai đoạn 3: GPU & Advanced Settings ═══════════════
    # GPU mode: khi True, dùng CUDA device, BoT-SORT tracker, batch inference
    GPU_ENABLED = _env_bool("GPU_ENABLED", "false")
    DEVICE = 'cuda' if GPU_ENABLED else 'cpu'

    # Tracker mode: 'bytetrack' (CPU, nhẹ) hoặc 'botsort' (GPU, có ReID)
    # Tự động chọn theo GPU_ENABLED nếu không set
    TRACKER_MODE = os.getenv("TRACKER_MODE", "botsort" if GPU_ENABLED else "bytetrack")

    # License plate detection model riêng (YOLOv8n-lp)
    # Đặt None để tự tìm trong ai_models/license_plate/, hoặc đường dẫn cụ thể
    LP_MODEL_PATH = os.getenv("LP_MODEL_PATH", None)

    # MinIO retention: số ngày giữ lại frames/evidence images
    MINIO_RETENTION_DAYS = _env_int("MINIO_RETENTION_DAYS", 30)

    # Batch inference server: bật/tắt kiến trúc GPU trung tâm
    BATCH_INFERENCE_ENABLED = _env_bool("BATCH_INFERENCE_ENABLED", "false")

    # --- Tối ưu Batch Inference cho đa luồng (Multi-Camera) ---
    # Mặc định lấy theo số lượng camera đang cấu hình (len(PATH_VIDEOS))
    INFERENCE_BATCH_SIZE = _env_int("INFERENCE_BATCH_SIZE", len(PATH_VIDEOS))
    # Thời gian chờ gom batch tối đa: 40ms đủ gom 5 frames nếu các luồng chạy ~25-30fps
    INFERENCE_MAX_WAIT_MS = _env_int("INFERENCE_MAX_WAIT_MS", 40)

class SettingChatBot:
    # Lazy import để tránh crash khi thiếu langchain (chỉ cần cho chatbot)
    LLM = None

    @classmethod
    def get_llm(cls):
        """Lazy load LLM - chỉ import khi thực sự cần dùng."""
        if cls.LLM is None:
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
                cls.LLM = ChatGoogleGenerativeAI(
                    model="gemini-3.1-flash-lite-preview",
                    temperature=0.4,
                    max_output_tokens=1024,
                )
            except ImportError:
                logger = __import__('logging').getLogger(__name__)
                logger.warning(
                    "langchain_google_genai not installed, chatbot will not work. "
                    "Install with: pip install langchain-google-genai"
                )
                cls.LLM = None
        return cls.LLM
    # Dùng ollama local api llm

    # from langchain_openai import ChatOpenAI
    # LLM = ChatOpenAI(
    #     model="gemma4:e4b",
    #     base_url="http://159.48.242.6:21209/v1",
    #     api_key="dummy"
    # )   


class SettingNetwork:
    BASE_URL_API = "http://localhost:8000"
    URL_FRONTEND = "http://localhost:5173"

settings_server = SettingServer()
settings_metric_transport = SettingMetricTransport()
settings_chatbot = SettingChatBot()  # Tên chuẩn duy nhất
settings_network = SettingNetwork()


class SettingViolation:
    """Cấu hình cho Violation Worker."""
    ENABLED = _env_bool("VIOLATION_WORKER_ENABLED", "true")
    QUEUE_KEY = os.getenv("VIOLATION_QUEUE_KEY", "violations:queue")
    ALERTS_CHANNEL = os.getenv("VIOLATION_ALERTS_CHANNEL", "violations:alerts")
    QUEUE_MAX_SIZE = max(100, _env_int("VIOLATION_QUEUE_MAX_SIZE", 1000))
    DEFAULT_SPEED_LIMIT = float(os.getenv("DEFAULT_SPEED_LIMIT", "50"))


class SettingMetrics:
    """Cấu hình cho monitoring."""
    METRICS_ENABLED = _env_bool("METRICS_ENABLED", "true")
    HEALTH_DETAILED_ENABLED = _env_bool("HEALTH_DETAILED_ENABLED", "true")


class SettingSecurity:
    """Cấu hình bảo mật."""
    RATE_LIMIT_PER_MINUTE = max(10, _env_int("RATE_LIMIT_PER_MINUTE", 60))
    WS_MAX_CONNECTIONS_PER_IP = max(1, _env_int("WS_MAX_CONNECTIONS_PER_IP", 5))
    # CORS allowed origins - lấy từ env, fallback default localhost
    CORS_ALLOWED_ORIGINS = [
        o.strip()
        for o in os.getenv(
            "CORS_ALLOWED_ORIGINS",
            "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173"
        ).split(",")
        if o.strip()
    ]


class SettingFeatures:
    """Feature flags."""
    ANPR_ENABLED = _env_bool("ANPR_ENABLED", "false")
    DISCORD_ALERTS_ENABLED = _env_bool("DISCORD_ALERTS_ENABLED", "false")


settings_violation = SettingViolation()
settings_metrics = SettingMetrics()
settings_security = SettingSecurity()
settings_features = SettingFeatures()

# ================= Traffic Thresholds (per-road) =================
# v: average speed threshold (km/h) - >= v => fast, else slow
# c1: vehicle count threshold for busy
# c2: vehicle count threshold for congested

from typing import Dict, TypedDict


class RoadThreshold(TypedDict):
    v: int
    c1: int
    c2: int


TRAFFIC_THRESHOLDS: Dict[str, RoadThreshold] = {
    "Đường Láng":    {"v": 18, "c1": 8,  "c2": 15},   # Hạ từ 12/20
    "Ngã Tư Sở":     {"v": 15, "c1": 10, "c2": 18},   # Hạ từ 35/47 — video test ít xe hơn thực
    "Nguyễn Trãi":   {"v": 15, "c1": 5,  "c2": 10},   # Hạ từ 12/22
    "Văn Phú":       {"v": 15, "c1": 5,  "c2": 10},   # Hạ từ 12/23
}

DEFAULT_THRESHOLD: RoadThreshold = {"v": 15, "c1": 15, "c2": 25}

# ================= Speed Limits (per-road) =================
# Ngưỡng tốc độ tối đa cho phép theo từng tuyến đường (km/h)
# Xe vượt quá ngưỡng này sẽ được ghi nhận vi phạm "speeding"
# Đặt 0 để tắt kiểm tra tốc độ cho tuyến đường đó
SPEED_LIMITS: Dict[str, float] = {
    "Đường Láng":  60.0,
    "Ngã Tư Sở":   40.0,
    "Nguyễn Trãi": 60.0,
    "Văn Phú":     40.0,
}

DEFAULT_SPEED_LIMIT: float = 50.0  # km/h — dùng khi không tìm thấy road name


