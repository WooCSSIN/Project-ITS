import json
import logging
from datetime import datetime, timezone
from overrides import override
import cv2
import redis
from services.road_services.analyze_on_road_base import AnalyzeOnRoadBase
from core.config import settings_metric_transport

logger = logging.getLogger(__name__)

class AnalyzeOnRoad(AnalyzeOnRoadBase):
    """Class này kế thừa từ class Base (xử lý tuần tự). Class con này chưa phải là code để multiprocessing\
    mà chỉ là một chút cải tiến từ code base (class Base) để có thể vừa xử lý video đầu vào ở một process\
    khác vừa có thể truy xuất thông tin về kết quả mà không bị hiện tượng tranh chấp dữ liệu    
    """    
    def __init__(self, path_video, meter_per_pixel, redis_url, region,
                 model_path=settings_metric_transport.MODELS_PATH, time_step=30,
                 is_draw=True, device=settings_metric_transport.DEVICE,
                 iou=None, conf=None, show=True,
                 infer_every_n_frames=None, frame_size=None):
        """AnalyzeOnRoad — kế thừa Base, thêm Redis I/O và per-camera detection config.

        Args:
            path_video: Đường dẫn video / RTSP URL.
            meter_per_pixel: Tỉ lệ mét/pixel.
            redis_url: URL Redis.
            region: ROI polygon numpy array.
            model_path: Đường dẫn YOLOv8 model.
            time_step: Chu kỳ cập nhật thống kê (giây).
            is_draw: Vẽ annotation lên frame.
            device: 'cpu' hoặc 'cuda'.
            iou: IoU threshold. None = dùng per-camera config hoặc default.
            conf: Confidence threshold. None = dùng per-camera config hoặc default.
            show: Hiển thị cửa sổ OpenCV.
            infer_every_n_frames: Frame skip. None = dùng per-camera config hoặc default.
            frame_size: Kích thước resize trước inference. None = dùng per-camera config hoặc default.
        """
        super().__init__(path_video, meter_per_pixel, model_path, time_step,
                         is_draw, device, iou, conf, show, region,
                         infer_every_n_frames, frame_size)
        self.redis = redis.Redis.from_url(redis_url)
        self.info_key = f"traffic:road:{self.name}:info"
        self.frame_key = f"traffic:road:{self.name}:frame"
        self.frame_ttl_seconds = 10
        self.info_ttl_seconds = 120
        self.history_queue_key = "traffic:history:queue"



    # JPEG quality cho WebSocket stream (75 = balance giữa quality và Redis I/O)
    # WebRTC sử dụng quality riêng khi encode lại, nên 85 là đủ cho intermediate storage.
    _FRAME_JPEG_QUALITY: int = 85

    @override
    def update_for_frame(self):
        """Cập nhật frame đang xử lý hiện tại vào Redis để chia sẻ dữ liệu giữa các process.

        Quality 85 thay vì 98: tiết kiệm ~40% Redis I/O, WebRTC sẽ tự re-encode
        nên chất lượng cuối không bị ảnh hưởng đáng kể.
        """
        try:
            if self.frame_output is None:
                return
            _, jpeg = cv2.imencode(
                '.jpg',
                self.frame_output,
                [cv2.IMWRITE_JPEG_QUALITY, self._FRAME_JPEG_QUALITY],
            )
            self.redis.setex(self.frame_key, self.frame_ttl_seconds, jpeg.tobytes())
        except Exception:
            logger.exception("Loi khi cap nhat frame moi nhat cua %s", self.name)
    

    @override
    def update_for_vehicle(self):
        """Hàm cập nhật thông tin về processing đang xử lý hiện tại và gán vào Manage.dict() để chia sẽ với nhau."""
        try:
            payload = {
                "count_car": int(self.count_car_display),
                "count_motor": int(self.count_motor_display),
                "speed_car": float(self.speed_car_display),
                "speed_motor": float(self.speed_motor_display),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self.redis.setex(self.info_key, self.info_ttl_seconds, json.dumps(payload, ensure_ascii=False))
            # Giới hạn queue size để tránh OOM Redis (giữ tối đa 1000 records)
            # Nếu worker DB chậm, sẽ drop records cũ thay vì phình to queue
            self.redis.lpush(self.history_queue_key, json.dumps({"road_name": self.name, **payload}, ensure_ascii=False))
            self.redis.ltrim(self.history_queue_key, 0, 999)  # Giữ 1000 records mới nhất
        except Exception:
            logger.exception("Loi khi update thong tin phuong tien cua %s", self.name)

    @override
    def _push_violations_to_queue(self, new_violations: list):
        """Push violations vào Redis queue để ViolationWorker xử lý."""
        if not new_violations:
            return
        
        try:
            for violation in new_violations:
                payload = {
                    "camera_id": violation.get("camera_id"),
                    "violation_type": violation.get("violation_type"),
                    "vehicle_track_id": violation.get("vehicle_track_id"),
                    "license_plate": violation.get("license_plate"),
                    "confidence": violation.get("confidence"),
                    "timestamp": violation.get("timestamp"),
                    "speed_kmh": violation.get("speed_kmh"),
                    "speed_limit_kmh": violation.get("speed_limit_kmh"),
                    "box": violation.get("box"),
                    "evidence_image_url": violation.get("evidence_image_url"),
                }
                # Push vào Redis violations queue
                self.redis.lpush("violations:queue", json.dumps(payload, ensure_ascii=False))
                logger.info(
                    "Pushed violation to queue: type=%s camera_id=%s track_id=%s",
                    payload.get("violation_type"),
                    payload.get("camera_id"),
                    payload.get("vehicle_track_id"),
                )
            
            # Giới hạn queue size (giữ 1000 violations gần nhất)
            self.redis.ltrim("violations:queue", 0, 999)
        except Exception:
            logger.exception("Error pushing violations to queue for %s", self.name)



#************************************************************************ Script for testing *******************************************************
if __name__ == "__main__":
    from core.config import settings_server

    path_video = "./video_test/Đường Láng.mp4"
    meter_per_pixel = 0.04
    
    analyzer = AnalyzeOnRoad(
        path_video=path_video,
        meter_per_pixel=meter_per_pixel,
        redis_url=settings_server.REDIS_URL,
        show=True
    )
    
    analyzer.process_on_single_video()
    