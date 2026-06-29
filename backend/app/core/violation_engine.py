"""ViolationEngine - Engine phát hiện vi phạm giao thông.

Class này nhận tracking data từ YOLO + Homography speeds và phát hiện:
    1. Speeding: xe vượt quá tốc độ cho phép theo SPEED_LIMITS
    2. Red light: xe đi qua vạch dừng khi đèn đỏ
    3. Wrong lane: xe đi sai làn đường (reserved cho tương lai)
    4. Illegal parking: xe đứng yên trong vùng cấm

Mỗi loại vi phạm có một polygon zone tương ứng (load từ DB).
Khi detect vi phạm, engine trả về dict chứa thông tin để push vào Redis queue.

Ví dụ violation dict:
    {
        "camera_id": 1,
        "violation_type": "speeding",
        "vehicle_track_id": 42,
        "license_plate": "30A12345",
        "confidence": 0.95,
        "timestamp": 1700000000.0,
        "speed_kmh": 85.0,
        "box": (x1, y1, x2, y2),  # bounding box trên frame gốc
        "evidence_image_url": None  # sẽ được set sau khi crop + upload MinIO
    }
"""
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import time

from core.config import (
    DEFAULT_SPEED_LIMIT,
    SPEED_LIMITS,
    settings_metric_transport,
    settings_violation,
)
from core.logging_config import get_logger

logger = get_logger(__name__)

Box = Tuple[int, int, int, int]  # (x1, y1, x2, y2)


class ViolationEngine:
    """Engine phát hiện vi phạm giao thông.

    Args:
        camera_id: ID của camera (để map với speed limit).
        speed_limit_kmh: Tốc độ tối đa cho phép (km/h). Nếu None sẽ lookup từ SPEED_LIMITS.
        road_name: Tên tuyến đường (để lookup speed limit).
    """

    # Ngưỡng để coi là đứng yên (cho illegal_parking detection)
    STATIONARY_SPEED_THRESHOLD = 2.0  # km/h
    STATIONARY_DURATION_SEC = 30.0    # đứng yên liên tục N giây

    # Track lịch sử stationary time cho mỗi track_id
    STATIONARY_HISTORY_MAX = 100  # giữ tối đa 100 track

    # Cooldown time cho mỗi loại vi phạm (giây) - tránh spam
    VIOLATION_COOLDOWN_SEC = 30.0  # Chỉ tạo 1 violation mỗi 30s cho cùng 1 xe + loại vi phạm

    def __init__(
        self,
        camera_id: int,
        speed_limit_kmh: Optional[float] = None,
        road_name: Optional[str] = None,
    ):
        self.camera_id = camera_id
        self.road_name = road_name

        # Tốc độ giới hạn: ưu tiên tham số truyền vào, sau đó lookup theo road_name, cuối cùng default
        if speed_limit_kmh is not None:
            self.speed_limit_kmh = float(speed_limit_kmh)
        elif road_name and road_name in SPEED_LIMITS:
            self.speed_limit_kmh = SPEED_LIMITS[road_name]
        else:
            self.speed_limit_kmh = DEFAULT_SPEED_LIMIT

        # Zones cho các loại vi phạm — load từ DB hoặc config
        # Sau init, zones["red_light"] phải là None (không hardcode mock zone)
        self.zones: Dict[str, Optional[np.ndarray]] = {
            "red_light": None,
            "no_parking": None,
            "wrong_lane": None,
        }

        # Trạng thái đèn đỏ — False mặc định (chưa kết nối camera đèn thật)
        self.is_red_light_on = False

        # Tracking stationary time cho từng track_id
        self._stationary_started: Dict[int, float] = {}
        self._stationary_history: Dict[int, List[float]] = {}

        # Cooldown tracking: {track_id: {violation_type: last_timestamp}}
        self._last_violation_time: Dict[int, Dict[str, float]] = {}

    def set_red_light_status(self, is_on: bool) -> None:
        """Set trạng thái đèn đỏ (từ external camera hoặc manual override)."""
        self.is_red_light_on = bool(is_on)
        logger.info("Red light status changed: %s", self.is_red_light_on)

    def set_red_light_zone(self, polygon: Optional[np.ndarray]) -> None:
        """Set polygon zone cho vạch dừng đèn đỏ.

        Args:
            polygon: numpy array shape (N, 2) định nghĩa vùng vạch dừng.
                     None để tắt detection.
        """
        if polygon is not None and not isinstance(polygon, np.ndarray):
            polygon = np.array(polygon, dtype=np.int32)
        self.zones["red_light"] = polygon
        logger.info("Red light zone updated: %s", "None" if polygon is None else f"shape={polygon.shape}")

    def set_no_parking_zone(self, polygon: Optional[np.ndarray]) -> None:
        """Set polygon zone cấm đỗ xe."""
        if polygon is not None and not isinstance(polygon, np.ndarray):
            polygon = np.array(polygon, dtype=np.int32)
        self.zones["no_parking"] = polygon

    def _should_create_violation(self, track_id: int, violation_type: str, timestamp: float) -> bool:
        """Check xem có nên tạo violation mới không (cooldown debounce).

        Args:
            track_id: ID của xe.
            violation_type: Loại vi phạm (speeding, red_light, illegal_parking).
            timestamp: Unix timestamp hiện tại.

        Returns:
            True nếu đã qua cooldown time, False nếu chưa.
        """
        if track_id not in self._last_violation_time:
            self._last_violation_time[track_id] = {}
        
        last_time = self._last_violation_time[track_id].get(violation_type)
        if last_time is None:
            # Chưa có vi phạm loại này cho track_id này → tạo mới
            self._last_violation_time[track_id][violation_type] = timestamp
            return True
        
        # Kiểm tra cooldown
        if (timestamp - last_time) >= self.VIOLATION_COOLDOWN_SEC:
            self._last_violation_time[track_id][violation_type] = timestamp
            return True
        
        return False

    def _point_in_zone(self, point: Tuple[int, int], zone: Optional[np.ndarray]) -> bool:
        """Check xem 1 điểm có nằm trong zone polygon không.

        Args:
            point: (x, y) trên ảnh gốc.
            zone: polygon numpy array hoặc None.

        Returns:
            True nếu điểm nằm trong zone, False nếu không hoặc zone=None.
        """
        if zone is None or len(zone) < 3:
            return False

        try:
            # pointPolygonTest trả về > 0 nếu trong, = 0 nếu trên biên, < 0 nếu ngoài
            result = cv2.pointPolygonTest(zone.reshape((-1, 1, 2)), point, measureDist=False)
            return result >= 0
        except Exception:
            return False

    def _get_center_box(self, box: Box) -> Tuple[int, int]:
        """Lấy tâm của bounding box."""
        x1, y1, x2, y2 = box
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    def process_frame_tracking(
        self,
        *args,
        **kwargs,
    ) -> List[Dict]:
        """Phân tích tracking data của 1 frame và trả về list violations.

        Hỗ trợ cả 2 signatures:
            - Mới: classes, ids, boxes, speeds, timestamp, frame
            - Cũ: frame, track_ids, boxes, classes, speeds_map (positional từ test bug2)

        Args:
            classes: numpy array shape (N,) class_id (0=car, 1=motor).
            ids: numpy array shape (N,) track_id.
            boxes: numpy array shape (N, 4).
            speeds: dict track_id -> speed (km/h).
            timestamp: Unix timestamp.
            frame: numpy array ảnh gốc (optional).
            track_ids: Alias cho `ids` (backward-compat).
            speeds_map: Alias cho `speeds` (backward-compat).

        Returns:
            List các dict violation.
        """
        # ── Parse arguments ─────────────────────────────────────────────────
        # Signature mới: (classes, ids, boxes, speeds, timestamp)
        # Signature cũ:  (frame, track_ids, boxes, classes, speeds_map)
        # Heuristic: args[0] phân biệt qua ndim/size
        #            args[1]: nếu là array 1D nhỏ → ids; nếu là array 2D lớn → track_ids (giống ids)
        classes = kwargs.pop("classes", None)
        ids = kwargs.pop("ids", None)
        boxes = kwargs.pop("boxes", None)
        speeds = kwargs.pop("speeds", None)
        timestamp = kwargs.pop("timestamp", None)
        frame = kwargs.pop("frame", None)
        track_ids = kwargs.pop("track_ids", None)
        speeds_map = kwargs.pop("speeds_map", None)

        # Phát hiện signature dựa trên args[0]
        if len(args) >= 1 and classes is None and frame is None:
            first = args[0]
            if first is None:
                # Không rõ → default signature mới
                pass
            elif hasattr(first, "ndim"):
                # Frame ảnh: ndim >= 2 và size lớn (>10000 pixels)
                if first.ndim >= 3 or (first.ndim == 2 and first.size > 10000):
                    frame = first  # Signature cũ
                else:
                    classes = first  # Signature mới
            elif isinstance(first, dict):
                # args[0] là dict speeds → signature cũ speeds_map đặt ở đầu (không hợp lệ)
                # Hoặc signature mới với speeds ở đầu (cũng không hợp lệ)
                # Không nên gặp case này, skip
                pass
            elif isinstance(first, (int, float)):
                # args[0] là timestamp (signature mới với speeds đặt trước timestamp)
                # Không hợp lý, nhưng xử lý defensive
                timestamp = first
            else:
                classes = first

        # args[1]: ids vs track_ids (đều là array 1D nên detect qua args[0])
        if len(args) >= 2 and ids is None and track_ids is None:
            if frame is not None:
                track_ids = args[1]  # Signature cũ
            else:
                ids = args[1]  # Signature mới

        # args[2]: boxes (cả 2 signature đều là boxes)
        if len(args) >= 3 and boxes is None:
            boxes = args[2]

        # args[3]: classes (cũ) vs speeds (mới) - detect qua việc đã set frame hay chưa
        if len(args) >= 4:
            if frame is not None and classes is None:
                classes = args[3]  # Signature cũ: classes ở vị trí 4
            elif frame is None and speeds is None:
                speeds = args[3]  # Signature mới: speeds ở vị trí 4

        # args[4]: speeds_map (cũ) vs timestamp (mới)
        if len(args) >= 5 and timestamp is None:
            if frame is not None and speeds_map is None:
                speeds_map = args[4]  # Signature cũ
            elif frame is None:
                timestamp = args[4]  # Signature mới

        # Normalize aliases
        if ids is None and track_ids is not None:
            ids = track_ids
        if speeds is None and speeds_map is not None:
            speeds = speeds_map
        if speeds is None:
            speeds = {}
        if timestamp is None:
            timestamp = time.time()

        violations: List[Dict] = []

        if ids is None or len(ids) == 0:
            self._cleanup_stationary_tracking(set())
            return violations

        try:
            classes = np.asarray(classes).flatten() if classes is not None else np.array([])
            ids = np.asarray(ids).flatten()
            boxes = np.asarray(boxes).reshape(-1, 4) if boxes is not None and len(boxes) > 0 else np.array([]).reshape(0, 4)

            # Đảm bảo classes có cùng length với ids
            if len(classes) != len(ids):
                if len(classes) == 0:
                    classes = np.zeros(len(ids), dtype=np.int32)
                elif classes.size == len(ids):
                    classes = classes.flatten()
                else:
                    # Có thể classes là một image 2D (frame shape) → lỗi cũ
                    logger.warning(
                        "Tracking data length mismatch: classes=%d ids=%d boxes=%d",
                        len(classes), len(ids), len(boxes),
                    )
                    return violations

            if len(boxes) != len(ids):
                logger.warning(
                    "Tracking data length mismatch: classes=%d ids=%d boxes=%d",
                    len(classes), len(ids), len(boxes),
                )
                return violations

            active_track_ids = set()
            for i in range(len(ids)):
                track_id = int(ids[i])
                active_track_ids.add(track_id)
                speed = float(speeds.get(track_id, 0.0))
                box = tuple(int(v) for v in boxes[i])

                # 1. Speeding detection
                if speed > self.speed_limit_kmh and speed > 0:
                    if self._should_create_violation(track_id, "speeding", timestamp):
                        violations.append({
                            "camera_id": self.camera_id,
                            "violation_type": "speeding",
                            "vehicle_track_id": track_id,
                            "license_plate": None,
                            "confidence": 0.95,
                            "timestamp": float(timestamp),
                            "speed_kmh": speed,
                            "speed_limit_kmh": self.speed_limit_kmh,
                            "box": box,
                            "evidence_image_url": None,
                        })

                # 2. Red light detection
                if self.is_red_light_on and self.zones["red_light"] is not None:
                    center = self._get_center_box(box)
                    if self._point_in_zone(center, self.zones["red_light"]):
                        if self._should_create_violation(track_id, "red_light", timestamp):
                            violations.append({
                                "camera_id": self.camera_id,
                                "violation_type": "red_light",
                                "vehicle_track_id": track_id,
                                "license_plate": None,
                                "confidence": 0.90,
                                "timestamp": float(timestamp),
                                "speed_kmh": speed,
                                "box": box,
                                "evidence_image_url": None,
                            })

                # 3. Illegal parking detection
                if self.zones["no_parking"] is not None:
                    center = self._get_center_box(box)
                    in_no_parking = self._point_in_zone(center, self.zones["no_parking"])
                    if in_no_parking and speed < self.STATIONARY_SPEED_THRESHOLD:
                        self._update_stationary(track_id, timestamp)
                        if self._is_stationary_long_enough(track_id):
                            if self._should_create_violation(track_id, "illegal_parking", timestamp):
                                violations.append({
                                    "camera_id": self.camera_id,
                                    "violation_type": "illegal_parking",
                                    "vehicle_track_id": track_id,
                                    "license_plate": None,
                                    "confidence": 0.85,
                                    "timestamp": float(timestamp),
                                    "speed_kmh": speed,
                                    "box": box,
                                    "evidence_image_url": None,
                                })
                    else:
                        self._stationary_started.pop(track_id, None)
                        self._stationary_history.pop(track_id, None)

            self._cleanup_stationary_tracking(active_track_ids)

        except Exception as exc:
            logger.exception("ViolationEngine.process_frame_tracking error: %s", exc)

        return violations

    def _update_stationary(self, track_id: int, timestamp: float) -> None:
        """Cập nhật tracking thời gian đứng yên."""
        if track_id not in self._stationary_started:
            self._stationary_started[track_id] = timestamp
            self._stationary_history[track_id] = []

        # Lưu history (giới hạn size để tránh memory leak)
        history = self._stationary_history[track_id]
        history.append(timestamp)
        if len(history) > self.STATIONARY_HISTORY_MAX:
            history.pop(0)

    def _is_stationary_long_enough(self, track_id: int) -> bool:
        """Check xem track_id đã đứng yên đủ lâu chưa."""
        start = self._stationary_started.get(track_id)
        if start is None:
            return False
        history = self._stationary_history.get(track_id, [])
        if not history:
            return False
        return (history[-1] - start) >= self.STATIONARY_DURATION_SEC

    def _cleanup_stationary_tracking(self, active_ids: set) -> None:
        """Dọn tracking cho các track_id không còn hoạt động."""
        stale = set(self._stationary_started.keys()) - active_ids
        for tid in stale:
            self._stationary_started.pop(tid, None)
            self._stationary_history.pop(tid, None)
        
        # Cleanup cooldown tracking cho tracks không còn hoạt động
        stale_cooldown = set(self._last_violation_time.keys()) - active_ids
        for tid in stale_cooldown:
            self._last_violation_time.pop(tid, None)

    def reset(self) -> None:
        """Reset toàn bộ state (dùng khi reset camera)."""
        self._stationary_started.clear()
        self._stationary_history.clear()
        self._last_violation_time.clear()
        logger.info("ViolationEngine reset: camera_id=%s", self.camera_id)

    def get_stats(self) -> Dict:
        """Lấy thống kê engine (cho debug/monitoring)."""
        return {
            "camera_id": self.camera_id,
            "road_name": self.road_name,
            "speed_limit_kmh": self.speed_limit_kmh,
            "is_red_light_on": self.is_red_light_on,
            "zones_configured": {
                k: v is not None for k, v in self.zones.items()
            },
            "tracked_stationary": len(self._stationary_started),
        }