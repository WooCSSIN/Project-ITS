from abc import abstractmethod
import cvzone
import cv2
import os
import logging
import numpy as np
import psutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional
from ultralytics import solutions
from utils.transport_utils import avg_none_zero_batch
from core.config import settings_metric_transport
from core.violation_engine import ViolationEngine
from core.anpr import ANPREngine
logger = logging.getLogger(__name__)


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
    """

    def __init__(self, alpha: float = 0.3):
        self.alpha = alpha
        self._smoothed: dict[int, float] = {}

    def update(self, track_id: int, raw_speed: float) -> float:
        """Cập nhật và trả về tốc độ đã làm mượt cho một track_id."""
        if raw_speed <= 0:
            return self._smoothed.get(track_id, 0.0)
        prev = self._smoothed.get(track_id, raw_speed)
        smoothed = self.alpha * raw_speed + (1.0 - self.alpha) * prev
        self._smoothed[track_id] = smoothed
        return smoothed

    def remove(self, track_id: int) -> None:
        """Xoá track_id khi không còn được theo dõi."""
        self._smoothed.pop(track_id, None)

    def clear(self) -> None:
        """Reset toàn bộ state (dùng khi reset chu kỳ)."""
        self._smoothed.clear()

class HomographySpeedTracker:
    def __init__(self, H: np.ndarray, fps: float = 30.0, max_hist: int = 15):
        self.H = H
        self.fps = fps
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

        # Khoảng cách từ điểm đầu tới điểm cuối trong lịch sử
        dx = hist[-1][0] - hist[0][0]
        dy = hist[-1][1] - hist[0][1]
        dist_m = np.sqrt(dx*dx + dy*dy)

        time_elapsed = (len(hist) - 1) / self.fps
        speed_mps = dist_m / time_elapsed if time_elapsed > 0 else 0
        speed_kmh = speed_mps * 3.6
        self.speeds[track_id] = speed_kmh
        return speed_kmh

    def set_fps(self, fps: float):
        if fps > 0:
            self.fps = fps


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
                 is_draw=True, device= settings_metric_transport.DEVICE, iou=0.3, conf=0.2, show=False,
                 region = np.array([[50, 400], [50, 265], [370, 130], [600, 130], [600, 400]]),
                 infer_every_n_frames=3):
        """Hàm xử lý tuần tự như một Script đơn giản áp dụng YOLO và cải tiến hơn là ở việc gói gọn trong 1 class

        Args:
            path_video (str): Đường dẫn đến video
            meter_per_pixel (float): Tỉ lệ 1 mét ngoài đời với 1 pixel
            model_path (str): Đường dẫn đến model. Defaults to "best.pt".
            time_step (int): Khoảng thời gian giữa 2 lần cập nhật thông tin các phương tiện. Defaults to 30.
            is_draw (bool): Biến chỉ định có vẽ các thông tin xử lý được lên frame hay không. Defaults to True.
            device (str): Dùng GPU hoặc CPU. Defaults to 'cpu'.
            iou (float): Ngưỡng tin cậy về bounding box . Defaults to 0.3.
            conf (float): Ngưỡng tin cậy về nhãn được dự đoán. Defaults to 0.2.
            show (bool): Hiển thị video xử lý qua opencv, đặt là False khi tích hợp làm server tránh lãng phí tài nguyên.\
            Defaults to True.
            infer_every_n_frames (int): Số frame cho mỗi lần infer (ví dụ 5 = 5 frame infer 1 lần).
            max_buffer_size (int): Kích thước tối đa của buffer cho deque. Defaults to 900.
        """
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
            iou=iou,
            conf=conf,
            meter_per_pixel=meter_per_pixel,
            max_hist=15,  # Tăng từ 5 → 15: lấy trung bình trajectory dài hơn → speed ổn định hơn
        )

        self.region = region
        self.region_pts = region.reshape((-1, 1, 2))
        # Bounding box (x, y, w, h) for fast pre-filtering before polygon test
        self.region_bbox = cv2.boundingRect(self.region_pts)

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
        self.infer_every_n_frames = max(1, int(infer_every_n_frames))
        self.frame_count = 0
        self.delta_time = 0
        self.time_pre_for_fps = datetime.now()

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
        self.ids_old = set()

        # Khởi tạo Violation Engine & ANPR
        # camera_id = 1-based index trong PATH_VIDEOS — nhất quán với frontend ZoneConfig.tsx
        # Frontend dùng `idx + 1`, backend phải dùng cùng công thức để zone load đúng
        try:
            cam_idx = settings_metric_transport.PATH_VIDEOS.index(self.path_video)
            cam_id = cam_idx + 1
        except ValueError:
            # Fallback: video không nằm trong PATH_VIDEOS (stream URL hoặc camera mới)
            # Dùng hash offset cao để tránh trùng với range 1..len(PATH_VIDEOS)
            cam_id = abs(hash(self.name)) % (10 ** 4) + len(settings_metric_transport.PATH_VIDEOS)
            logger.warning(
                "Video '%s' không tìm thấy trong PATH_VIDEOS. Dùng fallback camera_id=%d",
                self.path_video, cam_id
            )
        
        # Lấy speed limit từ SPEED_LIMITS config per-road
        from core.config import SPEED_LIMITS, DEFAULT_SPEED_LIMIT
        speed_limit = SPEED_LIMITS.get(self.name, DEFAULT_SPEED_LIMIT)
        
        self.violation_engine = ViolationEngine(camera_id=cam_id, speed_limit_kmh=speed_limit)
        
        # ViolationEngine khởi tạo với mọi zones=None và is_red_light_on=False (mặc định đúng)
        # Zone thực tế sẽ được load từ DB bởi _load_zones_from_db() trong AnalyzeOnRoad.__init__()
        # KHÔNG tạo mock zone — đã gây ra >11.000 vi phạm giả trong production

        self.anpr_engine = ANPREngine(use_gpu=False)

        # --- Speed smoother: EMA per track_id ---
        self.speed_smoother = SpeedSmoother(alpha=0.3)

        # --- ANPR ThreadPoolExecutor: tách ANPR ra khỏi processing loop ---
        # max_workers=1: ANPR chạy tuần tự để không tranh CPU với YOLO inference
        self._anpr_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="anpr")

        # --- Adaptive frame skipping ---
        self._base_infer_every_n = max(1, int(infer_every_n_frames))

        # --- FPS tracking thực tế để cập nhật SpeedEstimator ---
        self._actual_fps: float = 30.0  # Khởi tạo mặc định, sẽ được đo thực tế

        # --- Homography Speed Tracker ---
        # Tạm thời dùng identity matrix nếu không có (ví dụ cho test video)
        # Trong thực tế, truyền H từ config hoặc DB vào đây
        
        # Thử lấy matrix tương ứng với video, nếu không thì identity
        try:
            idx = settings_metric_transport.PATH_VIDEOS.index(self.path_video)
            H_matrix = settings_metric_transport.HOMOGRAPHY_MATRICES[idx]
        except (ValueError, IndexError, AttributeError):
            H_matrix = np.array([[0.05, 0, 0], [0, 0.05, 0], [0, 0, 1]], dtype=np.float32)

        self.homography_tracker = HomographySpeedTracker(H=H_matrix, fps=self._actual_fps, max_hist=15)

        # --- Inference Client (GPU Batch Mode) ---
        if settings_metric_transport.BATCH_INFERENCE_ENABLED:
            from services.road_services.batch_inference_server import InferenceClient
            from core.config import settings_server
            self.inference_client = InferenceClient(camera_id=self.name, redis_url=settings_server.REDIS_URL)
        else:
            self.inference_client = None

    @abstractmethod
    def update_for_frame(self):
        pass

    @abstractmethod
    def update_for_vehicle(self):
        pass

    def _push_violations_to_queue(self, new_violations: list):
        """No-op mặc định. Được override bởi AnalyzeOnRoad (có Redis) để đẩy vi phạm vào queue."""
        pass

    def _crop_and_upload_evidence(
        self,
        frame: np.ndarray,
        box: tuple,
        camera_id: int,
        margin: float = 0.05,
    ) -> Optional[str]:
        """
        Crop vùng xe vi phạm từ frame và upload lên MinIO.
        Chạy trong ANPR ThreadPoolExecutor — không block video processing loop.

        Args:
            frame: Frame gốc (BGR numpy array)
            box: Bounding box (x1, y1, x2, y2) của xe vi phạm
            camera_id: ID camera (dùng cho log)
            margin: Padding quanh bounding box (5% mặc định)

        Returns:
            URL ảnh trên MinIO, hoặc None nếu upload thất bại (graceful fallback)
        """
        try:
            from utils.minio_image_store import minio_image_store

            if frame is None or frame.size == 0:
                return None

            h, w = frame.shape[:2]
            x1, y1, x2, y2 = box

            # Thêm margin và clamp vào bounds frame
            bw = x2 - x1
            bh = y2 - y1
            mx = int(bw * margin)
            my = int(bh * margin)
            cx1 = max(0, x1 - mx)
            cy1 = max(0, y1 - my)
            cx2 = min(w, x2 + mx)
            cy2 = min(h, y2 + my)

            # Validate crop area không rỗng
            if cx2 <= cx1 or cy2 <= cy1:
                logger.warning(
                    "evidence crop: invalid box after margin clamp "
                    "camera=%s box=%s → (%d,%d,%d,%d)",
                    camera_id, box, cx1, cy1, cx2, cy2
                )
                return None

            crop = frame[cy1:cy2, cx1:cx2]

            # Encode sang JPEG bytes (quality 85 — balance size và quality)
            success, jpeg_buf = cv2.imencode(
                ".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85]
            )
            if not success:
                logger.warning("evidence crop: cv2.imencode failed camera=%s", camera_id)
                return None

            url = minio_image_store.upload_road_frame(self.name, jpeg_buf.tobytes())
            logger.info(
                "evidence uploaded camera=%s url=%s", camera_id, url[:60] if url else None
            )
            return url

        except Exception as e:
            logger.warning(
                "evidence upload failed camera=%s: %s", camera_id, e
            )
            return None

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
            self.ids_old.clear()

    def process_single_frame(self, frame_input):
        """Hàm này xử lý từng frame một
        Args:
            frame_input (np.array): Ảnh được đọc từ opencv
        """
        try:
            # Tránh copy toàn bộ frame, chỉ tạo view
            self.frame_output = frame_input

            # Crop theo bounding rect của polygon trên hệ tọa độ ảnh gốc
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
                    # else: timeout → drop frame (khong chay fallback de giu FPS)
                
            if use_local:
                # Fallback: chạy inference local (như cũ)
                self.speed_tool.process(self.frame_predict.copy())
                self.post_processing()
            
            # --- TÍCH HỢP VIOLATION & ANPR ---
            if self.ids is not None and len(self.ids) > 0:
                new_violations = self.violation_engine.process_frame_tracking(
                    frame=self.frame_output,
                    track_ids=self.ids,
                    boxes=self.boxes,
                    classes=self.classes,
                    speeds=self.speeds
                )
                if new_violations:
                    # Chạy ANPR bất đồng bộ trong ThreadPoolExecutor
                    # → không block processing loop, tránh EasyOCR làm lag toàn bộ pipeline
                    frame_copy = self.frame_output.copy()  # Copy để tránh race condition
                    violations_copy = [v.copy() for v in new_violations]

                    def _run_anpr_and_push(frame, violations):
                        """Hàm chạy trong worker thread: đọc biển số, upload ảnh bằng chứng và push vi phạm."""
                        for v in violations:
                            try:
                                plate = self.anpr_engine.read_license_plate(frame, v["box"])
                                v["license_plate"] = plate
                                logger.warning(
                                    "🚨 PHÁT HIỆN VI PHẠM: %s - Biển số: %s - Camera: %s",
                                    v['violation_type'], plate, self.name
                                )
                            except Exception:
                                logger.exception("ANPR lỗi cho vi phạm %s", v.get("violation_type"))

                            # Upload ảnh bằng chứng lên MinIO (graceful — không block, không crash)
                            evidence_url = self._crop_and_upload_evidence(
                                frame, v["box"], v.get("camera_id", 0)
                            )
                            v["evidence_image_url"] = evidence_url

                        self._push_violations_to_queue(violations)

                    self._anpr_executor.submit(_run_anpr_and_push, frame_copy, violations_copy)
            
            # Vẽ đè lên hình các thông tin
            if self.is_draw:
                self.draw_info_to_frame_output()
                # Vẽ thêm các zone vi phạm (nếu có) để test
                self.frame_output = self.violation_engine.draw_zones(self.frame_output)

            # Cập nhật data
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

        self.homography_tracker.set_fps(self._actual_fps)

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
        ids_old = self.ids_old

        def collect_speeds(new_ids: np.ndarray):
            if new_ids.size == 0:
                return []
            if ids_old:
                mask_new = ~np.isin(new_ids, list(ids_old), assume_unique=False)
                new_ids = new_ids[mask_new]
            if new_ids.size == 0:
                return []
            # Dùng smoothed speeds thay vì raw speeds
            spd_arr = np.array([smoothed_speeds.get(int(i), 0.0) for i in new_ids], dtype=np.float32)
            valid_mask = spd_arr > 0.0
            if not np.any(valid_mask):
                return []
            ids_old.update(new_ids[valid_mask].tolist())
            return spd_arr[valid_mask].tolist()

        car_speeds = collect_speeds(car_ids)
        motor_speeds = collect_speeds(motor_ids)
        if car_speeds:
            self.list_speed_car.extend(car_speeds)
        if motor_speeds:
            self.list_speed_motor.extend(motor_speeds)

    def post_processing(self):
        if self.speed_tool.track_data is not None:
            # Batch convert to numpy một lần (giảm nhiều lần truy cập thuộc tính)
            track_data = self.speed_tool.track_data
            speeds_dict = self.speed_tool.spd  # dict: id -> speed (raw từ SpeedEstimator)
            bx, by, _, _ = self.region_bbox

            raw_ids = getattr(track_data, "id", None)
            raw_classes = getattr(track_data, "cls", None)
            raw_boxes = getattr(track_data, "xyxy", None)

            # Có frame detector có box nhưng tracker chưa gán track id
            if raw_ids is None or raw_classes is None or raw_boxes is None:
                self.speeds = {}
                self.ids = np.empty((0,), dtype=np.int32)
                self.classes = np.empty((0,), dtype=np.int32)
                self.boxes = np.empty((0, 4), dtype=np.int32)
                return

            ids = raw_ids.cpu().numpy().astype(np.int32)
            classes = raw_classes.cpu().numpy().astype(np.int32)
            boxes = raw_boxes.cpu().numpy().astype(np.int32)

            # Map box từ tọa độ crop rect về tọa độ ảnh gốc
            boxes[:, [0, 2]] += bx
            boxes[:, [1, 3]] += by

            # Tính toán tâm box
            cx_arr = (boxes[:, 0] + boxes[:, 2]) / 2.0
            cy_arr = (boxes[:, 1] + boxes[:, 3]) / 2.0

            # Cập nhật FPS thực tế cho tracker
            self.homography_tracker.set_fps(self._actual_fps)

            # Áp dụng SpeedSmoother (EMA) lên homography speeds để giảm jitter
            smoothed_speeds: dict[int, float] = {}
            for i, track_id in enumerate(ids):
                # Tính tốc độ từ Homography thay vì SpeedEstimator
                raw_spd = self.homography_tracker.update(int(track_id), cx_arr[i], cy_arr[i])
                smoothed_speeds[int(track_id)] = self.speed_smoother.update(int(track_id), float(raw_spd))

            # Lưu vào thuộc tính phục vụ vẽ và ViolationEngine
            self.speeds = smoothed_speeds
            self.ids = ids
            self.classes = classes
            self.boxes = boxes

            self._update_display_counts(classes, ids, smoothed_speeds)
        else:
            # Không có track_data ở frame này -> xóa track cũ để tránh hiển thị sai
            self.speeds = {}
            self.ids = np.empty((0,), dtype=np.int32)
            self.classes = np.empty((0,), dtype=np.int32)
            self.boxes = np.empty((0, 4), dtype=np.int32)


    def draw_info_to_frame_output(self):
        """Hàm này để vẽ các thông tin lên ảnh - optimized version"""
        try:
            if self.ids is not None and len(self.ids) > 0:
                # Vectorized center calculation
                x1 = self.boxes[:, 0]
                y1 = self.boxes[:, 1]
                x2 = self.boxes[:, 2]
                y2 = self.boxes[:, 3]

                cx = ((x1 + x2) // 2).astype(np.int32)
                cy = ((y1 + y2) // 2).astype(np.int32)

                # Tìm các điểm nằm trong vùng ROI: prefilter bằng bounding box để giảm số lần pointPolygonTest
                bx, by, bw, bh = self.region_bbox
                in_bbox_mask = (
                    (cx >= bx) & (cx < bx + bw) &
                    (cy >= by) & (cy < by + bh)
                )
                candidate_idx = np.nonzero(in_bbox_mask)[0]
                valid_list = []
                region_pts_local = self.region_pts  # local ref
                for idx in candidate_idx:
                    if cv2.pointPolygonTest(region_pts_local, (int(cx[idx]), int(cy[idx])), False) >= 0:
                        valid_list.append(idx)
                if valid_list:
                    valid_indices = np.asarray(valid_list, dtype=np.int32)
                else:
                    valid_indices = np.empty((0,), dtype=np.int32)

                for idx in valid_indices:
                    track_id = self.ids[idx]
                    class_id = self.classes[idx]
                    speed_id = self.speeds.get(track_id, 0)

                    color = self.color_motor if class_id == 1 else self.color_car
                    label = f"{speed_id} km/h"

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
        target_size = (600, 400)

        # Hàm helper kết nối/tái kết nối camera an toàn
        def connect_camera():
            nonlocal cam, consecutive_failures
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
                    break
                
                if not is_network_stream:
                    logger.error("Không thể mở video file offline: %s", self.path_video)
                    break
                
                retry_count += 1
                logger.warning("Kết nối camera %s thất bại (lần %d). Thử lại sau 5 giây...", self.name, retry_count)
                time.sleep(5)

        # Lần kết nối đầu tiên
        connect_camera()
        if cam is None or not cam.isOpened():
            return

        try:
            while True:
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
                            connect_camera()
                        else:
                            time.sleep(0.1) # Tránh loop quá nhanh làm nghẽn CPU khi mất mạng tạm thời
                        continue
                    else:
                        # Đối với video offline: tự động lặp lại từ đầu (loop video)
                        cam.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue

                # Đọc thành công -> reset bộ đếm lỗi
                consecutive_failures = 0

                cap = cv2.resize(cap, target_size)

                # FPS calculation - optimized
                time_now = datetime.now()
                delta_time = (time_now - self.time_pre_for_fps).total_seconds()
                fps = round(1 / delta_time) if delta_time > 0 else 0
                self.time_pre_for_fps = time_now

                self._actual_fps = fps if fps > 0 else 30.0

                cvzone.putTextRect(cap, f"FPS: {fps}",
                                 (516, 20),
                                 scale=1.1, thickness=2,
                                 colorT=(0, 255, 100),
                                 colorR=(50, 50, 50),
                                 border=2,
                                 colorB=(255, 255, 255))

                # Chỉ infer mỗi N frame để giảm tải (N được điều chỉnh tự động theo CPU load)
                self.frame_count += 1
                current_skip = self._get_adaptive_skip_factor()
                if self.frame_count % current_skip == 0:
                    self.process_single_frame(cap)
                else:
                    # Không infer ở frame này, ghi đè trace cũ lên frame mới
                    self.frame_output = cap
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
            # Tắt ANPR executor sạch sẽ (không cancel job đang chạy)
            try:
                self._anpr_executor.shutdown(wait=False, cancel_futures=False)
            except TypeError:
                # Python < 3.9 không có cancel_futures param
                self._anpr_executor.shutdown(wait=False)

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