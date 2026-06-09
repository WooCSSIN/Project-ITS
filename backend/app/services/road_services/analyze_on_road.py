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
    def __init__(self, path_video, meter_per_pixel, redis_url, region, model_path = settings_metric_transport.MODELS_PATH, time_step=30,
                 is_draw=True, device= settings_metric_transport.DEVICE, iou=0.3, conf=0.2, show=True):
        """Class này kế thừa từ class Base (xử lý tuần tự). Class con này chưa phải là code để multiprocessing\
        mà chỉ là một chút cải tiến từ code base (class Base) để có thể vừa xử lý video đầu vào ở một process\
        khác vừa có thể truy xuất thông tin về kết quả mà không bị hiện tượng tranh chấp dữ liệu

        Args:
            path_video (str): Đường dẫn đến video
            meter_per_pixel (float): Tỉ lệ 1 mét ngoài đời với 1 pixel
            redis_url (str): URL kết nối Redis để chia sẻ dữ liệu realtime và queue lịch sử.
            model_path (str): Đường dẫn đến model. Defaults to "best.pt".
            time_step (int): Khoảng thời gian giữa 2 lần cập nhật thông tin các phương tiện. Defaults to 30.
            is_draw (bool): Biến chỉ định có vẽ các thông tin xử lý được lên frame hay không. Defaults to True.
            device (str): Dùng GPU hoặc CPU. Defaults to 'cpu'.
            iou (float): Ngưỡng tin cậy về bounding box . Defaults to 0.3.
            conf (float): Ngưỡng tin cậy về nhãn được dự đoán. Defaults to 0.2.
            show (bool): Hiển thị video xử lý qua opencv, đặt là False khi tích làm server tránh lãng phí tài nguyên.\
            Defaults to True.
            
        Examples:`
        Hướng dẫn chạy xử lý 1 video đơn
        >>> analyzer = AnalyzeOnRoad(
        >>>     path_video=path_video,
        >>>     meter_per_pixel=meter_per_pixel,
        >>>     redis_url=redis_url,
        >>>     **kwargs
        >>> )
        >>> analyzer.process_on_single_video()
        """
        super().__init__(path_video, meter_per_pixel, model_path, time_step,
                 is_draw, device, iou, conf, show, region)
        self.redis = redis.Redis.from_url(redis_url)
        self.info_key = f"traffic:road:{self.name}:info"
        self.frame_key = f"traffic:road:{self.name}:frame"
        self.violation_queue_key = "violations:queue"
        self.frame_ttl_seconds = 10
        self.info_ttl_seconds = 120
        self._load_zones_from_db()

    def _load_zones_from_db(self):
        """Tải cấu hình zone thực tế từ DB khi process khởi động."""
        try:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            from models.zone_config import ZoneConfig
            from core.config import settings_server

            sync_url = settings_server.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
            engine = create_engine(sync_url)
            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

            with SessionLocal() as db:
                db_zones = db.query(ZoneConfig).filter(
                    ZoneConfig.camera_id == self.violation_engine.camera_id,
                    ZoneConfig.is_active == True
                ).all()

                for z in db_zones:
                    self.violation_engine.set_zone(z.zone_type, z.points)
                    logger.info("Camera %s (ID: %s): Loaded zone %s", self.name, self.violation_engine.camera_id, z.zone_type)
        except Exception as e:
            logger.warning("Camera %s: Không thể load zone từ DB (%s). Dùng mock zone.", self.name, str(e))

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
            self.redis.lpush(self.history_queue_key, json.dumps({"road_name": self.name, **payload}, ensure_ascii=False))
        except Exception:
            logger.exception("Loi khi update thong tin phuong tien cua %s", self.name)

    def _push_violations_to_queue(self, new_violations: list):
        """Đẩy các vi phạm mới phát hiện vào Redis queue để ViolationWorker ghi vào DB."""
        for v in new_violations:
            payload = {
                "camera_id": v.get("camera_id"),
                "violation_type": v.get("violation_type"),
                "vehicle_track_id": v.get("vehicle_track_id"),
                "license_plate": v.get("license_plate"),
                "confidence": v.get("confidence"),
                "timestamp": v.get("timestamp"),
                "evidence_image_url": v.get("evidence_image_url"),  # URL MinIO hoặc None nếu upload thất bại
            }
            try:
                payload_str = json.dumps(payload)
                self.redis.lpush(self.violation_queue_key, payload_str)
                # Publish to pub/sub for realtime websocket alerts
                self.redis.publish("violations:alerts", payload_str)
            except Exception:
                logger.exception("Lỗi khi đẩy vi phạm vào Redis queue/pubsub")

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
    