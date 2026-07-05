from abc import abstractmethod
import cvzone
import cv2
import os
import threading
import logging
import numpy as np
import psutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional
from ultralytics import solutions
from utils.transport_utils import avg_none_zero_batch
from core.config import settings_metric_transport
logger = logging.getLogger(__name__)

# Cờ bật/tắt kiểm tra fps (tránh ZeroDivisionError)
DEFAULT_FALLBACK_FPS = 30.0
# Số frame tối đa giữ trong SpeedSmoother (LRU eviction tránh memory leak)
_MAX_TRACKED_IDS = 500
# Ngưỡng retry kết nối camera offline (file)
MAX_OFFLINE_RETRY = 3


class SpeedSmoother:
    """Làm mượt tốc độ tức thời theo từng track_id bằng Exponential Moving Average (EMA).

    Lý do dùng EMA thay Kalman filter đơn giản:
    - Không cần state matrix phức tạp
    - Đủ mượt cho hiển thị dashboard
    - Zero overhead — chỉ một phép nhân + cộng

    Args:
        alpha (float): Hệ số EMA. alpha=1.0 → không smooth (raw speed).
                       alpha=0.25 → smooth nhiều hơn, phản ứng chậm hơn với thay đổi thực.
                       Mặc định 0.3 là balance tốt giữa độ mượt và độ nhạy.
        max_tracked (int): Số track_id tối đa lưu trong dict (LRU eviction).
    """

    def __init__(self, alpha: float = 0.3, max_tracked: int = _MAX_TRACKED_IDS):
        self.alpha = alpha
        self.max_tracked = max_tracked
        self._smoothed: dict[int, float] = {}
        self._lock = threading.Lock()  # Bảo vệ concurrent access từ nhiều thread

    def update(self, track_id: int, raw_speed: float) -> float:
        """Cập nhật và trả về tốc độ đã làm mượt cho một track_id."""
        with self._lock:
            if raw_speed <= 0:
                return self._smoothed.get(track_id, 0.0)
            prev = self._smoothed.get(track_id, raw_speed)
            smoothed = self.alpha * raw_speed + (1.0 - self.alpha) * prev
            # LRU eviction: nếu vượt quá max_tracked, xóa entry cũ nhất
            if len(self._smoothed) >= self.max_tracked and track_id not in self._smoothed:
                oldest_id = next(iter(self._smoothed))
                self._smoothed.pop(oldest_id, None)
            self._smoothed[track_id] = smoothed
            return smoothed

    def remove(self, track_id: int) -> None:
        """Xoá track_id khi không còn được theo dõi."""
        with self._lock:
            self._smoothed.pop(track_id, None)

    def clear(self) -> None:
        """Reset toàn bộ state (dùng khi reset chu kỳ)."""
        with self._lock:
            self._smoothed.clear()

    def prune(self, active_ids: set) -> int:
        """Xoá các track_id không còn hoạt động. Trả về số entry đã xoá.

        Args:
            active_ids: set các track_id hiện đang được track.
        """
        with self._lock:
            stale = [tid for tid in self._smoothed if tid not in active_ids]
            for tid in stale:
                self._smoothed.pop(tid, None)
            return len(stale)

class HomographySpeedTracker:
    def __init__(self, H: np.ndarray, fps: float = 30.0, max_hist: int = 15):
        # Validate H là numpy array hợp lệ
        if not isinstance(H, np.ndarray) or H.shape != (3, 3):
            raise ValueError(f"Homography matrix phải là np.ndarray shape (3, 3), nhận được: {type(H).__name__} shape={getattr(H, 'shape', None)}")
        self.H = H.astype(np.float32)
        # Validate fps: nếu <= 0 thì fallback về DEFAULT_FALLBACK_FPS
        self.fps = fps if fps > 0 else DEFAULT_FALLBACK_FPS
        self.max_hist = max_hist
        self.track_history = {}  # track_id -> list of (real_x, real_y)
        self.speeds = {}         # track_id -> speed in km/h

    def pixel_to_real(self, cx, cy):
        pt = np.array([[[cx, cy]]], dtype=np.float32)
        real = cv2.perspectiveTransform(pt, self.H)
        return real[0][0]

    def update(self, track_id: int, cx: float, cy: float) -> float:
        real_pt = self.pixel_to_real(cx, cy)
        hist = self.track_history.setdefault(track_id, [])
        hist.append(real_pt)
        if len(hist) > self.max_hist:
            hist.pop(0)

        if len(hist) < 2:
            self.speeds[track_id] = 0.0
            return 0.0

        # Khoảng cách lũy kế qua các điểm (path length) thay vì đường thẳng (displacement)
        dist_m = sum(np.sqrt((hist[i][0]-hist[i-1][0])**2 + (hist[i][1]-hist[i-1][1])**2) for i in range(1, len(hist)))

        time_elapsed = (len(hist) - 1) / self.fps
        # Validate time_elapsed tránh ZeroDivisionError và giá trị vô cùng
        if not np.isfinite(time_elapsed) or time_elapsed <= 0:
            self.speeds[track_id] = 0.0
            return 0.0
        speed_mps = dist_m / time_elapsed
        # Bound speed để tránh outlier (xe không thể đi > 200 km/h trong nội đô)
        speed_mps = min(speed_mps, 55.56)  # ~200 km/h
        speed_kmh = speed_mps * 3.6
        self.speeds[track_id] = speed_kmh
        return speed_kmh

    def set_fps(self, fps: float):
        if fps is not None and np.isfinite(fps) and fps > 0:
            self.fps = fps

    def remove(self, track_id: int) -> None:
        """Xoá track_id khi không còn được theo dõi."""
        self.track_history.pop(track_id, None)
        self.speeds.pop(track_id, None)


class AnalyzeOnRoadBase:
    """Class gói gọn script xử lý tuần tự nhưng đảm bảo tính đóng gói OOP
        Attributes:
            count_car_display (int): số lượng xe oto trung bình
            speed_car_display (int): trung bình tốc độ tức thời của oto
            count_moto_display (int): số lượng xe xe máy trung bình
            speed_moto_display (int): trung bình tốc độ tức thời của xe máy
            speed_tool (solutions.SpeedEstimator()): đối tượng SpeedEstimator của YOLO
            frame_output (np.array): ảnh đã qua xử lý được vẽ hoặc không vẽ (tuỳ vào biến is_draw)\
            các thông tin được chuẩn đoán
        Examples:
            Hướng dẫn chạy xử lý 1 video đơn
            >>> analyzer = AnalyzeOnRoadBase(
            >>>     path_video=path_video,
            >>>     meter_per_pixel=meter_per_pixel,
            >>>     info_dict=info_dict,
            >>>     frame_dict=frame_dict,
            >>>     lock_info=lock_info,
            >>>     lock_frame=lock_frame,
            >>> )
            >>> analyzer.process_on_single_video()
    """
    def __init__(self, path_video = "./video_test/Đường Láng.mp4", meter_per_pixel = 0.06,
                 model_path= settings_metric_transport.MODELS_PATH, time_step=30,
                 is_draw=True, device= settings_metric_transport.DEVICE, iou=None, conf=None, show=False,
                 region = np.array([[50, 400], [50, 265], [370, 130], [600, 130], [600, 400]]),
                 infer_every_n_frames=None, frame_size=None):
        """Hàm xử lý tuần tự như một Script đơn giản áp dụng YOLO và cải tiến hơn là ở việc gói gọn trong 1 class

        Args:
            path_video (str): Đường dẫn đến video
            meter_per_pixel (float): Tỉ lệ 1 mét ngoài đời với 1 pixel
            model_path (str): Đường dẫn đến model. Defaults to "best.pt".
            time_step (int): Khoảng thời gian giữa 2 lần cập nhật thông tin các phương tiện. Defaults to 30.
            is_draw (bool): Biến chỉ định có vẽ các thông tin xử lý được lên frame hay không. Defaults to True.
            device (str): Dùng GPU hoặc CPU. Defaults to 'cpu'.
            iou (float): Ngưỡng tin cậy về bounding box. None = dùng per-camera override hoặc default.
            conf (float): Ngưỡng tin cậy về nhãn được dự đoán. None = dùng per-camera override hoặc default.
            show (bool): Hiển thị video xử lý qua opencv, đặt là False khi tích hợp làm server.
            infer_every_n_frames (int): Số frame cho mỗi lần infer. None = dùng per-camera override hoặc default.
            frame_size (tuple): Kích thước frame khi infer. None = dùng per-camera override hoặc default.
        """
        # ── Resolve per-camera config ────────────────────────────────────────
        road_name_tmp = os.path.splitext(os.path.basename(path_video))[0]
        _cam_overrides = getattr(settings_metric_transport, 'CAMERA_OVERRIDES', {}).get(road_name_tmp, {})

        _resolved_conf = conf if conf is not None else _cam_overrides.get(
            'conf', getattr(settings_metric_transport, 'DEFAULT_CONF', 0.15))
        _resolved_iou = iou if iou is not None else _cam_overrides.get(
            'iou', getattr(settings_metric_transport, 'DEFAULT_IOU', 0.3))
        _resolved_infer_n = infer_every_n_frames if infer_every_n_frames is not None else _cam_overrides.get(
            'infer_every_n', getattr(settings_metric_transport, 'DEFAULT_INFER_EVERY_N', 2))
        _resolved_frame_size = frame_size if frame_size is not None else _cam_overrides.get(
            'frame_size', getattr(settings_metric_transport, 'DEFAULT_FRAME_SIZE', (800, 600)))

        # Store resolved frame size on instance
        self._frame_size: tuple = _resolved_frame_size

        logger.info(
            "Camera %s config: conf=%.2f iou=%.2f infer_n=%d frame_size=%s",
            road_name_tmp, _resolved_conf, _resolved_iou, _resolved_infer_n, _resolved_frame_size,
        )
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # Giai đoạn 3: Chọn tracker dựa trên config (bytetrack cho CPU, botsort cho GPU)
        tracker_mode = settings_metric_transport.TRACKER_MODE
        if tracker_mode == "botsort":
            tracker_path = os.path.join(current_dir, 'tracker_botsort.yaml')
            if not os.path.exists(tracker_path):
                tracker_path = os.path.join(current_dir, 'tracker.yaml')
                logger.warning("BoT-SORT config not found, falling back to ByteTrack")
        else:
            tracker_path = os.path.join(current_dir, 'tracker.yaml')
        self.speed_tool = solutions.SpeedEstimator(
            model=model_path,
            tracker=tracker_path,
            verbose=False,
            show=False,
            device=device,
            iou=_resolved_iou,
            conf=_resolved_conf,
            meter_per_pixel=meter_per_pixel,
            max_hist=15,
            region=region.tolist(),  # region gốc (tọa độ full frame) — sẽ bị override khi infer
        )

        self.region = region
        self.region_pts = region.reshape((-1, 1, 2))
        # Bounding box (x, y, w, h) for fast pre-filtering before polygon test
        self.region_bbox = cv2.boundingRect(self.region_pts)

        # Pre-compute: polygon dịch về tọa độ crop (trừ bx, by)
        # Dùng để truyền vào SpeedEstimator khi infer trên crop nhỏ
        # → YOLO chạy nhẹ hơn, tọa độ vẫn khớp chính xác
        bx, by, _, _ = self.region_bbox
        self._region_in_crop = (region - np.array([bx, by])).astype(np.int32)

        self.show = show
        self.path_video = path_video
        self.name = os.path.splitext(os.path.basename(path_video))[0]

        self.count_car_display = 0
        self.list_count_car = []
        self.speed_car_display = 0
        self.list_speed_car = []

        self.count_motor_display = 0
        self.list_count_motor = []
        self.speed_motor_display = 0
        self.list_speed_motor = []

        self.time_pre = datetime.now()
        self.frame_output = None
        self.time_step = time_step
        self.frame_predict = None
        self.is_draw = is_draw
        self.infer_every_n_frames = max(1, int(_resolved_infer_n))
        self.frame_count = 0
        self.delta_time = 0
        self.time_pre_for_fps = datetime.now()

        # --- Adaptive frame skipping ---
        self._base_infer_every_n = max(1, int(_resolved_infer_n))

        # --- Adaptive resolution flag ---
        self._cpu_downscaled: bool = False

        # Draw
        self.font = cv2.FONT_HERSHEY_SIMPLEX
        self.font_scale = 0.5
        self.font_thickness = 1
        self.color_motor = (0, 0, 255)  # Red for motorcycles
        self.color_car = (255, 0, 0)    # Blue for cars
        self.color_region = (0, 255, 255)  # Yellow for region

        # Tracking
        self.ids = None
        self.speeds = {}
        self.boxes = None
        self.classes = None
        # Bảo vệ ids_old bằng lock để tránh RuntimeError khi clear() trong khi iterate
        self._ids_old_lock = threading.Lock()
        self.ids_old = set()

        # --- Speed smoother: EMA per track_id ---
        self.speed_smoother = SpeedSmoother(alpha=0.3)

        # --- FPS tracking thực tế để cập nhật SpeedEstimator ---
        self._actual_fps: float = DEFAULT_FALLBACK_FPS  # Khởi tạo mặc định, sẽ được đo thực tế

        # --- Homography Speed Tracker ---
        # Tạm thời dùng identity matrix nếu không có (ví dụ cho test video)
        # Trong thực tế, truyền H từ config hoặc DB vào đây

        # Thử lấy matrix tương ứng với video, nếu không thì fallback
        H_matrix = None
        try:
            path_videos = getattr(settings_metric_transport, 'PATH_VIDEOS', None)
            h_matrices = getattr(settings_metric_transport, 'HOMOGRAPHY_MATRICES', None)
            if path_videos and h_matrices and self.path_video in path_videos:
                idx = path_videos.index(self.path_video)
                if idx < len(h_matrices):
                    H_matrix = h_matrices[idx]
        except Exception:
            H_matrix = None

        if H_matrix is None or not isinstance(H_matrix, np.ndarray):
            # Fallback matrix với scale hợp lý (không phải 0.05 quá nhỏ gây sai số lớn)
            H_matrix = np.array([[0.1, 0, 0], [0, 0.1, 0], [0, 0, 1]], dtype=np.float32)

        try:
            self.homography_tracker = HomographySpeedTracker(H=H_matrix, fps=self._actual_fps, max_hist=15)
        except ValueError as exc:
            logger.error("Invalid homography matrix for %s: %s. Using fallback.", self.name, exc)
            fallback_H = np.array([[0.1, 0, 0], [0, 0.1, 0], [0, 0, 1]], dtype=np.float32)
            self.homography_tracker = HomographySpeedTracker(H=fallback_H, fps=self._actual_fps, max_hist=15)

        # --- Inference Client (GPU Batch Mode) ---
        self.inference_client = None
        if settings_metric_transport.BATCH_INFERENCE_ENABLED:
            try:
                from services.road_services.batch_inference_server import InferenceClient
                from core.config import settings_server
                self.inference_client = InferenceClient(camera_id=self.name, redis_url=settings_server.REDIS_URL)
            except Exception as exc:
                logger.warning("Failed to init InferenceClient for %s: %s. Fallback to local.", self.name, exc)
                self.inference_client = None

        # --- Violation Engine ---
        # Lấy camera_id từ PATH_VIDEOS index (nếu có)
        camera_id = 0
        road_name_for_violation = self.name
        try:
            path_videos = getattr(settings_metric_transport, 'PATH_VIDEOS', None)
            if path_videos and self.path_video in path_videos:
                camera_id = path_videos.index(self.path_video)
        except Exception:
            pass

        self.violation_engine = None
        try:
            from core.violation_engine import ViolationEngine
            from core.config import SPEED_LIMITS
            speed_limit = SPEED_LIMITS.get(road_name_for_violation, None)
            self.violation_engine = ViolationEngine(
                camera_id=camera_id,
                speed_limit_kmh=speed_limit,
                road_name=road_name_for_violation,
            )
            logger.info("ViolationEngine initialized for %s (camera_id=%s, speed_limit=%s)", 
                       self.name, camera_id, speed_limit)
        except Exception as exc:
            logger.warning("Failed to init ViolationEngine for %s: %s", self.name, exc)

    @abstractmethod
    def update_for_frame(self):
        pass

    @abstractmethod
    def update_for_vehicle(self):
        pass

    def _push_violations_to_queue(self, new_violations: list):
        """No-op mặc định. Được override bởi AnalyzeOnRoad (có Redis) để đẩy vi phạm vào queue."""
        pass

    def _get_adaptive_skip_factor(self) -> int:
        """Tự động điều chỉnh số frame bỏ qua dựa trên CPU load hiện tại.

        Khi CPU quá tải → tăng skip để giữ responsiveness của server.
        Khi CPU nhàn → dùng skip mặc định để tăng chất lượng tracking.

        Returns:
            int: Số frame skip (cao hơn = ít inference hơn = nhẹ hơn)
        """
        try:
            cpu = psutil.cpu_percent(interval=None)  # Non-blocking, dùng cached value
            if cpu > 85:
                return min(self._base_infer_every_n + 2, 6)  # Max skip = 6
            elif cpu > 70:
                return self._base_infer_every_n + 1
        except Exception:
            pass
        return self._base_infer_every_n

    def update_data(self):
        """Hàm này sẽ được gọi để cập nhật dữ liệu cho frame và thông tin phương tiện sau một khoảng thời gian
            đã thiết lập là time_step"""

        # Gọi hàm này để cập nhật dữ liệu cho frame (luôn được cập nhật đảm bảo tính realtime)
        self.update_for_frame()

        # Tính toán thời gian đã trôi qua kể từ lần cập nhật trước
        time_now = datetime.now()
        self.delta_time = (time_now - self.time_pre).total_seconds()

        # Khi đủ thời gian đã thiết lập, cập nhật thông tin phương tiện
        if self.delta_time >= self.time_step:
            self.time_pre = time_now

            # Tính toán trung bình các giá trị theo chu kỳ (bỏ qua 0)
            (
                self.count_car_display,
                self.speed_car_display,
                self.count_motor_display,
                self.speed_motor_display,
            ) = avg_none_zero_batch(
                self.list_count_car,
                self.list_speed_car,
                self.list_count_motor,
                self.list_speed_motor,
            )

            # Cập nhật thông tin phương tiện vào info_dict
            self.update_for_vehicle()

            # Reset danh sách để chuẩn bị cho lần cập nhật tiếp theo
            self.list_count_car.clear()
            self.list_count_motor.clear()
            self.list_speed_car.clear()
            self.list_speed_motor.clear()
            # Bảo vệ clear() bằng lock để tránh RuntimeError với _update_display_counts
            with self._ids_old_lock:
                self.ids_old.clear()

            # Cleanup SpeedSmoother: xoá các track_id không còn hoạt động
            if hasattr(self, 'ids') and self.ids is not None and len(self.ids) > 0:
                active_ids = set(int(i) for i in self.ids.tolist())
                self.speed_smoother.prune(active_ids)
            else:
                self.speed_smoother.clear()

    def process_single_frame(self, frame_input):
        """Hàm này xử lý từng frame một
        Args:
            frame_input (np.array): Ảnh được đọc từ opencv
        """
        try:
            self.frame_output = frame_input

            # Crop theo bounding rect để YOLO xử lý vùng nhỏ hơn → nhẹ CPU
            bx, by, bw, bh = self.region_bbox
            self.frame_predict = self.frame_output[by:by + bh, bx:bx + bw]

            # Giai đoạn 3: Tích hợp Batch Inference Server
            use_local = True
            if self.inference_client and self.inference_client.is_server_available():
                success = self.inference_client.submit_frame(self.frame_predict.copy())
                if success:
                    res = self.inference_client.get_result(timeout_ms=100)
                    if res:
                        self._apply_server_results(res)
                    use_local = False

            if use_local:
                # TỐI ƯU: crop nhỏ (nhẹ CPU) + region đã dịch tọa độ về crop space
                # → YOLO thấy đúng polygon, không bị miss xe trong vùng vàng
                self.speed_tool.region = self._region_in_crop.tolist()
                self.speed_tool.process(self.frame_predict.copy())
                self.post_processing()

            if self.is_draw:
                self.draw_info_to_frame_output()

            self.update_data()

        except Exception:
            logger.exception("Lỗi khi xử lý single frame %s", self.name)

    def _apply_server_results(self, res: dict):
        """Áp dụng kết quả tracking từ Batch Inference Server."""
        bx, by, _, _ = self.region_bbox
        
        raw_ids = res.get("track_ids", [])
        raw_classes = res.get("classes", [])
        raw_boxes = res.get("boxes", [])

        if not raw_ids:
            self.speeds = {}
            self.ids = np.empty((0,), dtype=np.int32)
            self.classes = np.empty((0,), dtype=np.int32)
            self.boxes = np.empty((0, 4), dtype=np.int32)
            return

        ids = np.array(raw_ids, dtype=np.int32)
        classes = np.array(raw_classes, dtype=np.int32)
        boxes = np.array(raw_boxes, dtype=np.int32)

        # Map box từ tọa độ crop rect về tọa độ ảnh gốc
        boxes[:, [0, 2]] += bx
        boxes[:, [1, 3]] += by

        # Tính toán tâm box
        cx_arr = (boxes[:, 0] + boxes[:, 2]) / 2.0
        cy_arr = (boxes[:, 1] + boxes[:, 3]) / 2.0

        # Cập nhật FPS thực tế theo tốc độ infer (frame skip)
        skip = getattr(self, 'current_skip', 1)
        self.homography_tracker.set_fps(self._actual_fps / skip)

        smoothed_speeds: dict[int, float] = {}
        for i, track_id in enumerate(ids):
            raw_spd = self.homography_tracker.update(int(track_id), cx_arr[i], cy_arr[i])
            smoothed_speeds[int(track_id)] = self.speed_smoother.update(int(track_id), float(raw_spd))

        self.speeds = smoothed_speeds
        self.ids = ids
        self.classes = classes
        self.boxes = boxes

        self._update_display_counts(classes, ids, smoothed_speeds)

    def _update_display_counts(self, classes, ids, smoothed_speeds):
        # Đếm mật độ tức thời
        car_mask = (classes == 0)
        motor_mask = (classes == 1)
        self.list_count_car.append(int(np.sum(car_mask)))
        self.list_count_motor.append(int(np.sum(motor_mask)))

        car_ids = ids[car_mask]
        motor_ids = ids[motor_mask]

        def collect_speeds(new_ids: np.ndarray, ids_old_snapshot: set):
            if new_ids.size == 0:
                return []
            if ids_old_snapshot:
                mask_new = ~np.isin(new_ids, list(ids_old_snapshot), assume_unique=False)
                new_ids = new_ids[mask_new]
            if new_ids.size == 0:
                return []
            # Dùng smoothed speeds thay vì raw speeds
            spd_arr = np.array([smoothed_speeds.get(int(i), 0.0) for i in new_ids], dtype=np.float32)
            valid_mask = spd_arr > 0.0
            if not np.any(valid_mask):
                return []
            return spd_arr[valid_mask].tolist()

        # Lấy snapshot của ids_old dưới lock, sau đó update dưới lock để tránh race condition
        with self._ids_old_lock:
            ids_old_snapshot = set(self.ids_old)
            car_speeds = collect_speeds(car_ids, ids_old_snapshot)
            motor_speeds = collect_speeds(motor_ids, ids_old_snapshot)
            if car_speeds:
                self.list_speed_car.extend(car_speeds)
            if motor_speeds:
                self.list_speed_motor.extend(motor_speeds)
            # Cập nhật ids_old với các track mới có speed hợp lệ
            if ids_old_snapshot or len(ids) > 0:
                valid_mask = np.array([
                    smoothed_speeds.get(int(tid), 0.0) > 0.0
                    for tid in ids
                ])
                new_valid_ids = set(int(tid) for tid in ids[valid_mask].tolist())
                self.ids_old.update(new_valid_ids - ids_old_snapshot)

    def post_processing(self):
        if self.speed_tool.track_data is not None:
            track_data = self.speed_tool.track_data
            # bx, by: offset của crop so với full frame
            # Cần cộng lại để box tọa độ khớp với frame_output khi vẽ
            bx, by, _, _ = self.region_bbox

            raw_ids = getattr(track_data, "id", None)
            raw_classes = getattr(track_data, "cls", None)
            raw_boxes = getattr(track_data, "xyxy", None)

            if raw_ids is None or raw_classes is None or raw_boxes is None:
                self.speeds = {}
                self.ids = np.empty((0,), dtype=np.int32)
                self.classes = np.empty((0,), dtype=np.int32)
                self.boxes = np.empty((0, 4), dtype=np.int32)
                return

            ids = raw_ids.cpu().numpy().astype(np.int32)
            classes = raw_classes.cpu().numpy().astype(np.int32)
            boxes = raw_boxes.cpu().numpy().astype(np.int32)

            # Cộng lại offset: box trong crop space → box trong full frame space
            # (cần cho draw_info_to_frame_output và ViolationEngine)
            boxes[:, [0, 2]] += bx
            boxes[:, [1, 3]] += by

            # Tâm box trong full frame space
            cx_arr = (boxes[:, 0] + boxes[:, 2]) / 2.0
            cy_arr = (boxes[:, 1] + boxes[:, 3]) / 2.0

            skip = getattr(self, 'current_skip', 1)
            self.homography_tracker.set_fps(self._actual_fps / skip)

            smoothed_speeds: dict[int, float] = {}
            for i, track_id in enumerate(ids):
                raw_spd = self.homography_tracker.update(int(track_id), cx_arr[i], cy_arr[i])
                smoothed_speeds[int(track_id)] = self.speed_smoother.update(int(track_id), float(raw_spd))

            self.speeds = smoothed_speeds
            self.ids = ids
            self.classes = classes
            self.boxes = boxes

            self._update_display_counts(classes, ids, smoothed_speeds)

            # --- Violation Detection ---
            if self.violation_engine is not None:
                violations = self.violation_engine.process_frame_tracking(
                    classes=classes,
                    ids=ids,
                    boxes=boxes,
                    speeds=smoothed_speeds,
                    timestamp=datetime.now().timestamp(),
                    frame=self.frame_output,
                )
                if violations:
                    self._push_violations_to_queue(violations)
        else:
            # Không có track_data ở frame này -> xóa track cũ để tránh hiển thị sai
            self.speeds = {}
            self.ids = np.empty((0,), dtype=np.int32)
            self.classes = np.empty((0,), dtype=np.int32)
            self.boxes = np.empty((0, 4), dtype=np.int32)


    def draw_info_to_frame_output(self):
        """Hàm này để vẽ các thông tin lên ảnh - optimized version với vectorized polygon test."""
        try:
            if self.ids is not None and len(self.ids) > 0:
                # Vectorized center calculation
                x1 = self.boxes[:, 0]
                y1 = self.boxes[:, 1]
                x2 = self.boxes[:, 2]
                y2 = self.boxes[:, 3]

                cx = ((x1 + x2) // 2).astype(np.int32)
                cy = ((y1 + y2) // 2).astype(np.int32)

                # Prefilter bằng bounding box (vectorized)
                bx, by, bw, bh = self.region_bbox
                in_bbox_mask = (
                    (cx >= bx) & (cx < bx + bw) &
                    (cy >= by) & (cy < by + bh)
                )
                candidate_idx = np.nonzero(in_bbox_mask)[0]

                # Vectorized polygon test thay vì vòng lặp cv2.pointPolygonTest
                # 50x nhanh hơn khi có nhiều vehicle
                if len(candidate_idx) > 0:
                    candidate_points = np.column_stack([cx[candidate_idx], cy[candidate_idx]])
                    try:
                        from utils.polygon_utils import points_in_polygon_fast
                        in_polygon = points_in_polygon_fast(candidate_points, self.region.reshape(-1, 2))
                    except ImportError:
                        # Fallback: dùng cv2.pointPolygonTest nếu polygon_utils chưa available
                        in_polygon = np.array([
                            cv2.pointPolygonTest(self.region_pts, (float(cx[i]), float(cy[i])), False) >= 0
                            for i in candidate_idx
                        ], dtype=bool)
                    valid_indices = candidate_idx[in_polygon]
                else:
                    valid_indices = np.empty((0,), dtype=np.int32)

                for idx in valid_indices:
                    track_id = self.ids[idx]
                    class_id = self.classes[idx]
                    speed_id = self.speeds.get(track_id, 0)

                    color = self.color_motor if class_id == 1 else self.color_car
                    label = f"{speed_id:.1f} km/h"

                    cx_global = cx[idx]
                    cy_global = cy[idx]

                    cv2.putText(
                        self.frame_output,
                        label,
                        (cx_global - 50, cy_global - 15),
                        self.font,
                        self.font_scale,
                        color,
                        self.font_thickness,
                    )
                    cv2.circle(self.frame_output, (cx_global, cy_global), 5, color, -1)
                    cv2.rectangle(self.frame_output, (int(x1[idx]), int(y1[idx])), (int(x2[idx]), int(y2[idx])), color, 2)

            cv2.polylines(self.frame_output, [self.region_pts],
                         isClosed=True, color=self.color_region, thickness=4)

            info = [
                f"Xe may: {self.count_motor_display} xe, Vtb = {self.speed_motor_display} km/h",
                f"Oto: {self.count_car_display} xe, Vtb = {self.speed_car_display} km/h"
            ]

            colors = [(0, 0, 200), (200, 0, 0)]

            for i, t in enumerate(info):
                cvzone.putTextRect(
                    self.frame_output, t,
                    (10, 25 + i * 35),
                    scale=1.5, thickness=2,
                    colorT=colors[i],
                    colorR=(50, 50, 50),
                    border=2,
                    colorB=(255, 255, 255)
                )

        except Exception:
            logger.exception("Lỗi khi vẽ frame cho %s", self.name)

    def process_on_single_video(self):
        """Hàm này sẽ được gọi để xử lý video bằng việc đọc từng frame và xử lý từng frame một (hỗ trợ tự động kết nối lại luồng online)"""
        import time

        is_network_stream = any(
            isinstance(self.path_video, str) and self.path_video.startswith(prefix)
            for prefix in ("rtsp://", "rtmp://", "http://", "https://")
        )

        logger.info("Khởi động bộ thu nhận camera: %s (Luồng mạng: %s)", self.path_video, is_network_stream)

        cam = None
        consecutive_failures = 0
        # Sử dụng configured frame size từ per-camera config thay vì hardcode (600, 400)
        _fallback_size = (600, 400)
        # Cờ để worker dừng hẳn (tránh vòng lặp vô hạn khi camera lỗi liên tục)
        should_stop = False

        # Hàm helper kết nối/tái kết nối camera an toàn
        def connect_camera(max_retry: int = MAX_OFFLINE_RETRY if not is_network_stream else None):
            nonlocal cam, consecutive_failures, should_stop
            if cam is not None:
                try:
                    cam.release()
                except Exception:
                    pass

            retry_count = 0
            while True:
                logger.info("Đang kết nối tới nguồn camera %s...", self.name)
                cam = cv2.VideoCapture(self.path_video)
                if cam.isOpened():
                    logger.info("Kết nối thành công nguồn camera %s!", self.name)
                    consecutive_failures = 0
                    return True

                # Camera offline file - giới hạn retry để tránh lặp vô hạn
                if not is_network_stream:
                    logger.error("Không thể mở video file offline: %s. Worker %s dừng.", self.path_video, self.name)
                    should_stop = True
                    return False

                # Camera network stream: retry vô hạn nhưng có thể stop từ bên ngoài
                retry_count += 1
                if max_retry is not None and retry_count > max_retry:
                    logger.error("Đã vượt quá max_retry=%d cho camera %s. Dừng worker.", max_retry, self.name)
                    should_stop = True
                    return False

                logger.warning("Kết nối camera %s thất bại (lần %d). Thử lại sau 5 giây...", self.name, retry_count)
                time.sleep(5)

        # Lần kết nối đầu tiên
        if not connect_camera():
            return

        try:
            while not should_stop:
                check, cap = cam.read()

                if not check:
                    if is_network_stream:
                        consecutive_failures += 1
                        if consecutive_failures >= 15:
                            logger.warning(
                                "Mất kết nối luồng camera %s (15 frames không phản hồi). Tiến hành tự động kết nối lại...",
                                self.name
                            )
                            time.sleep(3)
                            if not connect_camera():
                                break
                        else:
                            time.sleep(0.1) # Tránh loop quá nhanh làm nghẽn CPU khi mất mạng tạm thời
                        continue
                    else:
                        # Đối với video offline: tự động lặp lại từ đầu (loop video)
                        cam.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue

                # Đọc thành công -> reset bộ đếm lỗi
                consecutive_failures = 0

                # ── Adaptive frame resolution (Task 3.2 - 3.4) ──────────────
                try:
                    _cpu_now = psutil.cpu_percent(interval=None)
                    if _cpu_now > 70:
                        target_size = _fallback_size  # downscale sớm hơn khi CPU > 70%
                        if not self._cpu_downscaled:
                            self._cpu_downscaled = True
                            logger.warning(
                                "CPU high (%.0f%%), downscaling frame to %s for %s",
                                _cpu_now, _fallback_size, self.name,
                            )
                    else:
                        target_size = self._frame_size  # dùng configured size
                        if _cpu_now < 55 and self._cpu_downscaled:
                            self._cpu_downscaled = False  # reset flag khi CPU ổn định lại
                except Exception:
                    target_size = self._frame_size

                cap = cv2.resize(cap, target_size)

                if cam is not None and cam.isOpened():
                    vid_fps = cam.get(cv2.CAP_PROP_FPS)
                    if vid_fps > 0 and not is_network_stream:
                        # Giới hạn FPS tối đa 30fps để tránh quá tải CPU
                        # Video 60fps (Văn Quán) hay 50fps (Nguyễn Văn Trỗi) đọc quá nhanh
                        capped_fps = min(vid_fps, 30.0)
                        self._actual_fps = capped_fps
                        fps = round(capped_fps)

                        # Frame throttle: nếu video FPS > 30, bỏ qua frame dư
                        # Ví dụ: 60fps → đọc 1 frame, bỏ 1 frame (ratio = 60/30 = 2)
                        if vid_fps > 30:
                            skip_ratio = round(vid_fps / 30)
                            if self.frame_count % skip_ratio != 0:
                                self.frame_count += 1
                                continue
                    else:
                        time_now = datetime.now()
                        delta_time = (time_now - self.time_pre_for_fps).total_seconds()
                        fps = round(1 / delta_time) if delta_time > 0 else 0
                        self.time_pre_for_fps = time_now
                        self._actual_fps = fps if fps > 0 else DEFAULT_FALLBACK_FPS
                else:
                    fps = 30
                    self._actual_fps = DEFAULT_FALLBACK_FPS

                cvzone.putTextRect(cap, f"FPS: {fps}",
                                 (516, 20),
                                 scale=1.1, thickness=2,
                                 colorT=(0, 255, 100),
                                 colorR=(50, 50, 50),
                                 border=2,
                                 colorB=(255, 255, 255))

                # Chỉ infer mỗi N frame để giảm tải (N được điều chỉnh tự động theo CPU load)
                self.frame_count += 1
                self.current_skip = self._get_adaptive_skip_factor()  # ← FIX: gán trước khi dùng
                if self.frame_count % self.current_skip == 0:
                    self.process_single_frame(cap)
                else:
                    # Không infer ở frame này, ghi đè frame mới nhưng vẫn giữ trace cũ
                    # Sử dụng copy để tránh aliasing với cap gốc (cv2.release() sẽ free buffer)
                    if self.frame_output is None or self.frame_output.shape != cap.shape:
                        self.frame_output = cap.copy()
                    else:
                        # Copy nội dung frame mới vào frame_output để giữ các annotation đã vẽ
                        np.copyto(self.frame_output, cap)
                    if self.is_draw:
                        self.draw_info_to_frame_output()

                # Hiển thị frame nếu show là True
                if self.show:
                    cv2.imshow(f'{self.name}', self.frame_output)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break

        except KeyboardInterrupt:
            logger.info("Đã dừng xử lý %s", self.name)
        except Exception:
            logger.exception("Lỗi khi xử lý single video %s", self.name)
        finally:
            # Giải phóng tài nguyên
            if cam is not None:
                cam.release()
            if self.show:
                cv2.destroyAllWindows()


#************************************************************************ Script for testing *******************************************************
if __name__ == "__main__":
    # Example usage
    path_video = settings_metric_transport.PATH_VIDEOS[3]
    meter_per_pixel = settings_metric_transport.METER_PER_PIXELS[3]

    analyzer = AnalyzeOnRoadBase(
        path_video=path_video,
        meter_per_pixel=meter_per_pixel,
        region=settings_metric_transport.REGIONS[3],
        show=True
    )

    analyzer.process_on_single_video()