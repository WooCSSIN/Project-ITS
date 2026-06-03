import asyncio
import importlib
import json
import logging
import multiprocessing
from datetime import datetime, timezone

from fastapi.concurrency import run_in_threadpool
from core.config import settings_server
from db.base import AsyncSessionLocal
from models.violation import Violation

logger = logging.getLogger(__name__)

VIOLATION_QUEUE_KEY = "violations:queue"


async def _insert_violation_row(payload: dict):
    """Chuyển payload vi phạm từ Redis queue thành bản ghi Violation trong DB."""
    try:
        ts_raw = payload.get("timestamp")
        if isinstance(ts_raw, (int, float)):
            timestamp = datetime.fromtimestamp(ts_raw, tz=timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)
    except Exception:
        timestamp = datetime.now(timezone.utc)

    row = Violation(
        camera_id=int(payload.get("camera_id", 0)),
        timestamp=timestamp,
        violation_type=str(payload.get("violation_type", "unknown")),
        vehicle_track_id=payload.get("vehicle_track_id"),
        license_plate=payload.get("license_plate"),
        confidence=payload.get("confidence"),
        evidence_image_url=payload.get("evidence_image_url"),
        evidence_video_url=payload.get("evidence_video_url"),
        status="pending",
    )

    async with AsyncSessionLocal() as session:
        session.add(row)
        await session.commit()
        logger.info(
            "Đã lưu vi phạm vào DB: %s - Biển số: %s",
            row.violation_type,
            row.license_plate,
        )


async def _run_worker_loop(redis_url: str, queue_key: str, stop_event):
    """Vòng lặp worker chạy nền: đọc queue Redis và ghi vi phạm vào DB."""
    redis_module = importlib.import_module("redis")
    redis_client = redis_module.Redis.from_url(redis_url, decode_responses=True)

    try:
        while not stop_event.is_set():
            try:
                item = await run_in_threadpool(redis_client.brpop, queue_key, 1)
                if not item:
                    continue
                _, payload_str = item
                data = json.loads(payload_str)
                await _insert_violation_row(data)
            except Exception as exc:
                logger.exception("ViolationWorker process error: %s", exc)
                await asyncio.sleep(0.5)
    finally:
        await run_in_threadpool(redis_client.close)


def _process_entrypoint(redis_url: str, queue_key: str, stop_event):
    """Điểm vào của process con dùng để chạy asyncio loop."""
    try:
        asyncio.run(
            _run_worker_loop(redis_url=redis_url, queue_key=queue_key, stop_event=stop_event)
        )
    except Exception as exc:
        logger.exception("ViolationWorker crashed: %s", exc)


class ViolationWorker:
    """Worker chạy nền trong process riêng: đọc Redis queue và ghi vi phạm vào DB."""

    def __init__(
        self,
        redis_url: str = settings_server.REDIS_URL,
        queue_key: str = VIOLATION_QUEUE_KEY,
    ):
        self.redis_url = redis_url
        self.queue_key = queue_key
        self._process = None
        self._stop_event = None

    async def start(self):
        """Khởi động process worker nếu chưa tồn tại."""
        if self._process is not None and self._process.is_alive():
            return
        ctx = multiprocessing.get_context("spawn")
        self._stop_event = ctx.Event()
        self._process = ctx.Process(
            target=_process_entrypoint,
            args=(self.redis_url, self.queue_key, self._stop_event),
            name="violation-worker",
        )
        self._process.start()
        logger.info("ViolationWorker đã khởi động.")

    async def stop(self):
        """Dừng worker một cách an toàn và giải phóng process."""
        if self._process is None:
            return
        if self._stop_event is not None:
            self._stop_event.set()
        await run_in_threadpool(self._process.join, 5)
        if self._process.is_alive():
            self._process.terminate()
            await run_in_threadpool(self._process.join, 2)
        self._process = None
        self._stop_event = None
        logger.info("ViolationWorker đã dừng.")
