"""ViolationWorker - xử lý queue vi phạm và lưu vào DB.

Worker này chạy trong background process, đọc queue Redis `violations:queue`,
parse các violation events, lưu vào bảng `violations` trong PostgreSQL,
và publish alerts qua Redis pub/sub channel `violations:alerts`.

Flow:
    Analyzer → push violation JSON → Redis queue
       ↓
    ViolationWorker (background) → pop từ queue → save vào DB → publish alert
       ↓
    Discord/Telegram bot subscribe → gửi notification

Retry logic:
    - DB error: retry tối đa 3 lần với exponential backoff
    - MinIO error: skip (graceful degradation), evidence_url = null
"""
import asyncio
import importlib
import json
import logging
import multiprocessing
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError, OperationalError

from core.config import settings_server, settings_violation
from core.logging_config import get_logger
from db.base import AsyncSessionLocal

logger = get_logger(__name__)

# Retry config
_DB_RETRY_MAX = 3
_DB_RETRY_BACKOFF_SEC = 0.5


async def _insert_violation_row(payload: Dict[str, Any]) -> Optional[int]:
    """Chèn một violation row vào DB.

    Args:
        payload: dict chứa các trường vi phạm.

    Returns:
        ID của row vừa insert, hoặc None nếu lỗi.
    """
    from models.violation import Violation

    # Validate required fields
    violation_type = payload.get("violation_type")
    if not violation_type:
        logger.warning("Skipping violation without violation_type: %s", payload)
        return None

    # Parse timestamp
    raw_ts = payload.get("timestamp")
    if isinstance(raw_ts, (int, float)):
        # Unix timestamp
        try:
            recorded_at = datetime.fromtimestamp(float(raw_ts), tz=timezone.utc)
        except (ValueError, OSError):
            recorded_at = datetime.now(timezone.utc)
    elif isinstance(raw_ts, str):
        try:
            normalized = raw_ts.replace("Z", "+00:00")
            recorded_at = datetime.fromisoformat(normalized)
        except Exception:
            recorded_at = datetime.now(timezone.utc)
    else:
        recorded_at = datetime.now(timezone.utc)

    row = Violation(
        camera_id=int(payload.get("camera_id", 0) or 0),
        timestamp=recorded_at,
        violation_type=str(violation_type)[:50],
        vehicle_track_id=payload.get("vehicle_track_id"),
        license_plate=str(payload.get("license_plate", "") or "")[:20] or None,
        confidence=float(payload.get("confidence", 0.0) or 0.0),
        evidence_image_url=payload.get("evidence_image_url"),
        evidence_video_url=payload.get("evidence_video_url"),
        status=str(payload.get("status", "pending"))[:20],
        extra_metadata=json.dumps(
            {k: v for k, v in payload.items() if k not in {
                "camera_id", "timestamp", "violation_type", "vehicle_track_id",
                "license_plate", "confidence", "evidence_image_url",
                "evidence_video_url", "status"
            }},
            ensure_ascii=False,
        ) if any(k in payload for k in ("speed_kmh", "fine_amount", "notes")) else None,
    )

    for attempt in range(_DB_RETRY_MAX):
        try:
            async with AsyncSessionLocal() as session:
                session.add(row)
                await session.commit()
                await session.refresh(row)
                logger.info(
                    "Violation inserted: id=%s type=%s camera_id=%s plate=%s",
                    row.id, row.violation_type, row.camera_id, row.license_plate,
                )
                return row.id
        except IntegrityError as exc:
            logger.warning("Violation insert IntegrityError (attempt %d): %s", attempt + 1, exc)
            return None
        except OperationalError as exc:
            if attempt < _DB_RETRY_MAX - 1:
                backoff = _DB_RETRY_BACKOFF_SEC * (2 ** attempt)
                logger.warning(
                    "DB OperationalError (attempt %d/%d), retry in %.2fs: %s",
                    attempt + 1, _DB_RETRY_MAX, backoff, exc,
                )
                await asyncio.sleep(backoff)
            else:
                logger.exception("Violation insert failed after %d retries: %s", _DB_RETRY_MAX, exc)
                return None
        except Exception as exc:
            logger.exception("Unexpected error inserting violation: %s", exc)
            return None
    return None


async def _publish_alert(redis_client, payload: Dict[str, Any]) -> None:
    """Publish alert lên Redis pub/sub channel.

    Args:
        redis_client: redis.asyncio client.
        payload: violation payload.
    """
    try:
        await redis_client.publish(
            settings_violation.ALERTS_CHANNEL,
            json.dumps(payload, ensure_ascii=False, default=str),
        )
    except Exception as exc:
        logger.warning("Failed to publish violation alert: %s", exc)


async def _run_worker_loop(redis_url: str, queue_key: str, alerts_channel: str, stop_event) -> None:
    """Vòng lặp worker chính: đọc queue → xử lý → insert DB → publish alert."""
    redis_asyncio = importlib.import_module("redis.asyncio")
    redis_client = redis_asyncio.from_url(redis_url, decode_responses=True)

    logger.info("ViolationWorker started: queue=%s alerts=%s", queue_key, alerts_channel)

    try:
        while not stop_event.is_set():
            try:
                # brpop với timeout 1s để có thể check stop_event
                item = await redis_client.brpop(queue_key, timeout=1)
                if not item:
                    continue

                _, raw_payload = item
                try:
                    payload = json.loads(raw_payload)
                except json.JSONDecodeError as exc:
                    logger.warning("Invalid JSON in violation queue: %s | payload=%s", exc, raw_payload[:200])
                    continue

                # Validate tối thiểu
                if not isinstance(payload, dict) or "violation_type" not in payload:
                    logger.warning("Invalid violation payload (missing violation_type): %s", payload)
                    continue

                # Insert DB
                violation_id = await _insert_violation_row(payload)
                if violation_id is None:
                    # Insert fail nhưng KHÔNG requeue để tránh loop vô hạn
                    # Violation sẽ mất, log warning để admin investigate
                    logger.warning("Violation dropped due to DB error: %s", payload)
                    continue

                # Publish alert (best-effort)
                enriched_payload = {**payload, "id": violation_id}
                await _publish_alert(redis_client, enriched_payload)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("ViolationWorker loop error: %s\n%s", exc, traceback.format_exc())
                await asyncio.sleep(0.5)
    finally:
        try:
            await redis_client.aclose()
        except Exception:
            pass
        logger.info("ViolationWorker stopped")


def _process_entrypoint(redis_url: str, queue_key: str, alerts_channel: str, stop_event) -> None:
    """Entry point cho multiprocessing.Process."""
    try:
        asyncio.run(_run_worker_loop(redis_url, queue_key, alerts_channel, stop_event))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logger.exception("ViolationWorker crashed: %s", exc)


class ViolationWorker:
    """Worker xử lý vi phạm giao thông chạy nền.

    Quản lý một multiprocessing.Process đọc Redis queue và ghi DB.
    Singleton pattern - mỗi app instance chỉ có 1 worker.
    """

    def __init__(
        self,
        redis_url: str = settings_server.REDIS_URL,
        queue_key: Optional[str] = None,
        alerts_channel: Optional[str] = None,
    ):
        self.redis_url = redis_url
        self.queue_key = queue_key or settings_violation.QUEUE_KEY
        self.alerts_channel = alerts_channel or settings_violation.ALERTS_CHANNEL
        self._process = None
        self._stop_event = None

    async def start(self) -> None:
        """Khởi động worker process."""
        if not settings_violation.ENABLED:
            logger.info("ViolationWorker disabled by config (VIOLATION_WORKER_ENABLED=false)")
            return

        if self._process is not None and self._process.is_alive():
            logger.info("ViolationWorker already running: pid=%s", self._process.pid)
            return

        ctx = multiprocessing.get_context("spawn")
        self._stop_event = ctx.Event()
        self._process = ctx.Process(
            target=_process_entrypoint,
            args=(self.redis_url, self.queue_key, self.alerts_channel, self._stop_event),
            name="violation-worker",
            daemon=False,  # Cho phép cleanup graceful khi shutdown
        )
        self._process.start()
        logger.info("ViolationWorker started: pid=%s", self._process.pid)

    async def stop(self) -> None:
        """Dừng worker một cách an toàn."""
        if self._process is None:
            return

        if self._stop_event is not None:
            self._stop_event.set()

        # Đợi worker kết thúc (timeout 5s)
        await run_in_threadpool(self._process.join, 5)
        if self._process.is_alive():
            logger.warning("ViolationWorker didn't stop gracefully, terminating...")
            self._process.terminate()
            await run_in_threadpool(self._process.join, 2)
            if self._process.is_alive():
                self._process.kill()
                await run_in_threadpool(self._process.join, 1)

        # Giải phóng handle
        try:
            self._process.close()
        except Exception:
            pass

        self._process = None
        self._stop_event = None
        logger.info("ViolationWorker stopped")

    def is_alive(self) -> bool:
        """Check worker có đang chạy không."""
        return self._process is not None and self._process.is_alive()