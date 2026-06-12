"""
Batch Inference Server — Kiến trúc GPU trung tâm cho multi-camera.

Thay vì mỗi camera process tự chạy inference riêng (tốn RAM, không tận dụng GPU batch),
kiến trúc này tách inference thành 1 process duy nhất nhận frame từ tất cả camera qua Redis queue,
chạy batch inference trên GPU, rồi trả kết quả về từng camera process.

Architecture:
    [Camera Process 1] → frame:queue:{cam} → [Inference Server] → results:queue:{cam} → [Camera Process 1]
    [Camera Process 2] ↗                                          ↘ [Camera Process 2]
    [Camera Process N] ↗                                          ↘ [Camera Process N]

Lợi ích:
- Batch inference trên GPU: throughput gấp 3-5x so với sequential
- 1 model instance duy nhất: tiết kiệm VRAM (mỗi camera ~1.5GB → chia sẻ ~2GB tổng)
- Camera process chỉ cần decode frame + post-process, không cần GPU access
"""
import json
import time
import logging
import numpy as np
import cv2
import redis
from typing import List, Dict, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Redis key patterns
INFERENCE_REQUEST_QUEUE = "inference:requests"          # Shared request queue
INFERENCE_RESULT_KEY = "inference:results:{camera_id}"  # Per-camera result key
INFERENCE_SERVER_STATUS = "inference:server:status"      # Server heartbeat


@dataclass
class InferenceRequest:
    """Một request inference từ camera process."""
    camera_id: str
    frame_shape: tuple          # (height, width, channels)
    timestamp: float = field(default_factory=time.time)


@dataclass
class InferenceResult:
    """Kết quả inference trả về cho camera process."""
    camera_id: str
    track_ids: list             # list[int]
    boxes: list                 # list[list[int]] — xyxy format
    classes: list               # list[int]
    speeds: dict                # dict[int, float] — track_id -> speed
    timestamp: float = field(default_factory=time.time)


class BatchInferenceServer:
    """
    GPU Inference Server chạy trong 1 process riêng.
    Nhận frames từ nhiều camera qua Redis, batch inference, trả kết quả.
    """

    def __init__(
        self,
        model_path: str,
        tracker_path: str,
        redis_url: str = "redis://localhost:6379/0",
        device: str = "cuda",
        batch_size: int = 4,
        max_wait_ms: int = 50,
        conf: float = 0.2,
        iou: float = 0.3,
    ):
        """
        Args:
            model_path: Đường dẫn đến YOLO model (.pt, .onnx, .engine)
            tracker_path: Đường dẫn đến tracker.yaml
            redis_url: Redis connection URL
            device: 'cuda', 'cuda:0', 'cpu'
            batch_size: Số frame tối đa trong 1 batch
            max_wait_ms: Thời gian chờ tối đa (ms) để gom đủ batch
            conf: Confidence threshold
            iou: IoU threshold
        """
        self.model_path = model_path
        self.tracker_path = tracker_path
        self.redis_url = redis_url
        self.device = device
        self.batch_size = batch_size
        self.max_wait_ms = max_wait_ms
        self.conf = conf
        self.iou = iou

        self._redis: Optional[redis.Redis] = None
        self._model = None
        self._running = False

    def _connect_redis(self):
        """Kết nối Redis."""
        self._redis = redis.Redis.from_url(self.redis_url, decode_responses=False)
        logger.info("BatchInferenceServer: Connected to Redis")

    def _load_model(self):
        """Load YOLO model."""
        from ultralytics import YOLO
        self._model = YOLO(self.model_path)
        # Warmup
        dummy = np.zeros((640, 640, 3), dtype=np.uint8)
        self._model.predict(dummy, device=self.device, verbose=False)
        logger.info("BatchInferenceServer: Model loaded and warmed up on %s", self.device)

    def _publish_heartbeat(self):
        """Ghi heartbeat để camera processes biết server còn sống."""
        if self._redis:
            self._redis.setex(
                INFERENCE_SERVER_STATUS,
                10,  # TTL 10s
                json.dumps({"status": "running", "timestamp": time.time(), "device": self.device})
            )

    def _collect_batch(self) -> List[Dict]:
        """
        Gom frames từ Redis queue, chờ tối đa max_wait_ms hoặc đủ batch_size.
        Returns list of {camera_id, frame_bytes, timestamp}
        """
        batch = []
        deadline = time.time() + self.max_wait_ms / 1000.0

        while len(batch) < self.batch_size and time.time() < deadline:
            # BRPOP với timeout ngắn
            remaining_ms = max(1, int((deadline - time.time()) * 1000))
            timeout_sec = remaining_ms / 1000.0

            result = self._redis.brpop(INFERENCE_REQUEST_QUEUE, timeout=min(timeout_sec, 0.1))
            if result is None:
                if batch:
                    break  # Đã có ít nhất 1 frame, xử lý luôn
                continue

            _, raw_data = result
            try:
                meta = json.loads(raw_data)
                camera_id = meta["camera_id"]

                # Frame bytes được lưu riêng (key tạm) để tránh JSON encode ảnh
                frame_key = f"inference:frame:{camera_id}"
                frame_bytes = self._redis.get(frame_key)
                if frame_bytes is None:
                    continue

                self._redis.delete(frame_key)

                # Decode frame
                nparr = np.frombuffer(frame_bytes, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if frame is None:
                    continue

                batch.append({
                    "camera_id": camera_id,
                    "frame": frame,
                    "shape": meta.get("frame_shape", frame.shape),
                    "timestamp": meta.get("timestamp", time.time()),
                })

            except Exception as e:
                logger.warning("BatchInferenceServer: Lỗi parse request: %s", e)

        return batch

    def _run_batch_inference(self, batch: List[Dict]) -> List[Dict]:
        """
        Chạy YOLO inference trên batch frames.
        Returns list of results per camera.
        """
        if not batch:
            return []

        frames = [item["frame"] for item in batch]
        camera_ids = [item["camera_id"] for item in batch]

        try:
            # Batch predict với tracking
            results = self._model.track(
                source=frames,
                device=self.device,
                conf=self.conf,
                iou=self.iou,
                persist=True,
                tracker=self.tracker_path,
                verbose=False,
            )

            output = []
            for i, (result, camera_id) in enumerate(zip(results, camera_ids)):
                track_data = result.boxes
                if track_data is None or len(track_data) == 0:
                    output.append({
                        "camera_id": camera_id,
                        "track_ids": [],
                        "boxes": [],
                        "classes": [],
                        "speeds": {},
                        "timestamp": batch[i]["timestamp"],
                    })
                    continue

                ids = track_data.id
                if ids is None:
                    output.append({
                        "camera_id": camera_id,
                        "track_ids": [],
                        "boxes": [],
                        "classes": [],
                        "speeds": {},
                        "timestamp": batch[i]["timestamp"],
                    })
                    continue

                output.append({
                    "camera_id": camera_id,
                    "track_ids": ids.cpu().numpy().astype(int).tolist(),
                    "boxes": track_data.xyxy.cpu().numpy().astype(int).tolist(),
                    "classes": track_data.cls.cpu().numpy().astype(int).tolist(),
                    "speeds": {},  # Speed tính bởi camera process (HomographySpeedTracker)
                    "timestamp": batch[i]["timestamp"],
                })

            return output

        except Exception as e:
            logger.exception("BatchInferenceServer: Lỗi batch inference: %s", e)
            return []

    def _publish_results(self, results: List[Dict]):
        """Đẩy kết quả inference về cho từng camera process qua Redis."""
        for result in results:
            camera_id = result["camera_id"]
            result_key = INFERENCE_RESULT_KEY.format(camera_id=camera_id)
            try:
                self._redis.setex(
                    result_key,
                    5,  # TTL 5s — nếu camera process không lấy kịp thì bỏ
                    json.dumps(result)
                )
            except Exception as e:
                logger.warning("Lỗi publish result cho camera %s: %s", camera_id, e)

    def run(self):
        """Main loop: collect → batch inference → publish results."""
        self._connect_redis()
        self._load_model()
        self._running = True

        logger.info("═" * 60)
        logger.info("BatchInferenceServer STARTED")
        logger.info("  Device: %s", self.device)
        logger.info("  Batch size: %d", self.batch_size)
        logger.info("  Max wait: %dms", self.max_wait_ms)
        logger.info("═" * 60)

        heartbeat_interval = 5.0
        last_heartbeat = 0.0
        batch_count = 0

        try:
            while self._running:
                # Heartbeat
                now = time.time()
                if now - last_heartbeat > heartbeat_interval:
                    self._publish_heartbeat()
                    last_heartbeat = now

                # Collect
                batch = self._collect_batch()
                if not batch:
                    continue

                # Inference
                results = self._run_batch_inference(batch)

                # Publish
                self._publish_results(results)

                batch_count += 1
                if batch_count % 100 == 0:
                    logger.info(
                        "BatchInferenceServer: %d batches processed (last batch size: %d)",
                        batch_count, len(batch)
                    )

        except KeyboardInterrupt:
            logger.info("BatchInferenceServer: Shutting down...")
        except Exception:
            logger.exception("BatchInferenceServer: Fatal error")
        finally:
            self._running = False
            if self._redis:
                self._redis.delete(INFERENCE_SERVER_STATUS)
                self._redis.close()
            logger.info("BatchInferenceServer: Stopped")

    def stop(self):
        """Dừng server (gọi từ thread khác)."""
        self._running = False


class InferenceClient:
    """
    Client chạy trong mỗi camera process.
    Gửi frame đến BatchInferenceServer và nhận kết quả.
    Fallback: nếu server không available, chạy inference local.
    """

    def __init__(self, camera_id: str, redis_url: str = "redis://localhost:6379/0"):
        self.camera_id = camera_id
        self._redis = redis.Redis.from_url(redis_url, decode_responses=False)
        self._server_available = False
        self._last_server_check = 0.0
        self._check_interval = 5.0  # Kiểm tra server mỗi 5s

    def is_server_available(self) -> bool:
        """Kiểm tra xem BatchInferenceServer có đang chạy không."""
        now = time.time()
        if now - self._last_server_check < self._check_interval:
            return self._server_available

        self._last_server_check = now
        try:
            status = self._redis.get(INFERENCE_SERVER_STATUS)
            self._server_available = status is not None
        except Exception:
            self._server_available = False

        return self._server_available

    def submit_frame(self, frame: np.ndarray) -> bool:
        """
        Gửi frame đến inference server.
        Returns True nếu gửi thành công.
        """
        if not self.is_server_available():
            return False

        try:
            # Encode frame
            _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            frame_bytes = jpeg.tobytes()

            # Lưu frame bytes vào key tạm và đẩy metadata qua pipeline để tránh race condition
            frame_key = f"inference:frame:{self.camera_id}"
            meta = json.dumps({
                "camera_id": self.camera_id,
                "frame_shape": list(frame.shape),
                "timestamp": time.time(),
            })
            
            pipe = self._redis.pipeline()
            pipe.setex(frame_key, 5, frame_bytes)
            pipe.lpush(INFERENCE_REQUEST_QUEUE, meta)
            pipe.execute()

            return True

        except Exception as e:
            logger.warning("InferenceClient %s: Lỗi gửi frame: %s", self.camera_id, e)
            return False

    def get_result(self, timeout_ms: int = 100) -> Optional[Dict]:
        """
        Lấy kết quả inference từ server.
        Returns None nếu không có kết quả.
        """
        result_key = INFERENCE_RESULT_KEY.format(camera_id=self.camera_id)
        deadline = time.time() + timeout_ms / 1000.0

        while time.time() < deadline:
            try:
                raw = self._redis.get(result_key)
                if raw:
                    self._redis.delete(result_key)
                    return json.loads(raw)
            except Exception:
                pass
            time.sleep(0.005)

        return None

    def close(self):
        """Đóng kết nối Redis."""
        try:
            self._redis.close()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# Script chạy Inference Server độc lập
# Usage: python -m services.road_services.batch_inference_server
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import sys
    sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))

    from core.config import settings_metric_transport, settings_server
    from core.logging_config import setup_logging
    setup_logging()

    # Mặc định dùng GPU model — khi có GPU thì export sang TensorRT (.engine) hoặc ONNX
    # Nếu chưa có model GPU, fallback sang OpenVINO model
    import os
    gpu_model_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'ai_models', 'model N', 'onnx models', 'best.onnx'
    )
    if not os.path.exists(gpu_model_path):
        gpu_model_path = settings_metric_transport.MODELS_PATH

    tracker_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tracker_botsort.yaml')
    if not os.path.exists(tracker_path):
        tracker_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tracker.yaml')

    server = BatchInferenceServer(
        model_path=gpu_model_path,
        tracker_path=tracker_path,
        redis_url=settings_server.REDIS_URL,
        device="cuda",
        batch_size=getattr(settings_metric_transport, 'INFERENCE_BATCH_SIZE', 5),
        max_wait_ms=getattr(settings_metric_transport, 'INFERENCE_MAX_WAIT_MS', 40),
    )
    server.run()
