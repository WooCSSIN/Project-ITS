import cv2
import time
import numpy as np
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

class ViolationEngine:
    """
    Core Engine để phát hiện các vi phạm giao thông dựa trên toạ độ tracking và cấu hình zone.
    Các loại vi phạm:
    - red_light: Vượt đèn đỏ
    - wrong_lane: Đi sai làn
    - no_parking: Dừng đỗ sai quy định
    """
    
    def __init__(self, camera_id: int):
        self.camera_id = camera_id
        
        # Cấu hình các vùng vi phạm (Polygon) cho camera này
        # Mặc định trống, sẽ được cập nhật thông qua API hoặc config
        self.zones = {
            "red_light": None,  # np.array of polygon points
            "wrong_lane": None,
            "no_parking": None
        }
        
        # Trạng thái hiện tại của đèn tín hiệu (True = Đỏ, False = Xanh/Vàng)
        self.is_red_light_on = False
        
        # Tracking lịch sử để xử lý lỗi dừng đỗ quá thời gian (no_parking)
        # dict: track_id -> {"start_time": float, "last_pos": (cx, cy)}
        self.stopped_vehicles = {}
        
        # Lưu vết các xe đã bị ghi nhận vi phạm để tránh record nhiều lần
        self.recorded_violations = set()
        
        # Thời gian (giây) tối đa được dừng đỗ trước khi tính là vi phạm
        self.max_stop_time = 30.0

    def set_zone(self, violation_type: str, polygon_points: List[Tuple[int, int]]):
        """Cập nhật vùng vi phạm"""
        if violation_type in self.zones:
            self.zones[violation_type] = np.array(polygon_points, np.int32).reshape((-1, 1, 2))
            
    def set_red_light_status(self, status: bool):
        """Cập nhật trạng thái đèn đỏ"""
        self.is_red_light_on = status

    def check_point_in_zone(self, pt: Tuple[int, int], zone_name: str) -> bool:
        """Kiểm tra xem toạ độ pt có nằm trong zone không"""
        zone_polygon = self.zones.get(zone_name)
        if zone_polygon is None:
            return False
        # pointPolygonTest trả về >= 0 nếu điểm nằm trong hoặc trên cạnh polygon
        return cv2.pointPolygonTest(zone_polygon, pt, False) >= 0

    def process_frame_tracking(
        self, 
        frame: np.ndarray, 
        track_ids: np.ndarray, 
        boxes: np.ndarray, 
        classes: np.ndarray,
        speeds: Dict[int, float]
    ) -> List[Dict]:
        """
        Xử lý thông tin tracking của 1 frame để phát hiện vi phạm.
        Trả về danh sách các vi phạm mới phát hiện.
        """
        new_violations = []
        current_time = time.time()
        
        if len(track_ids) == 0:
            return new_violations

        # Tính tâm của tất cả bounding box
        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 2]
        y2 = boxes[:, 3]
        cx = ((x1 + x2) // 2).astype(np.int32)
        cy = ((y1 + y2) // 2).astype(np.int32)

        for i, track_id in enumerate(track_ids):
            # Nếu xe đã vi phạm rồi thì bỏ qua
            if track_id in self.recorded_violations:
                continue

            pt = (int(cx[i]), int(cy[i]))
            class_id = classes[i]
            speed = speeds.get(track_id, 0.0)
            
            violation_type = None
            
            # 1. Phát hiện vượt đèn đỏ (Red light)
            if self.is_red_light_on and self.check_point_in_zone(pt, "red_light"):
                # Nếu đèn đang đỏ và xe di chuyển vào vùng vạch cấm
                if speed > 5.0:  # Ngưỡng vận tốc cho thấy xe không dừng
                    violation_type = "red_light"

            # 2. Phát hiện đi sai làn (Wrong lane)
            elif self.check_point_in_zone(pt, "wrong_lane"):
                # Tùy logic: Ví dụ làn chỉ dành cho oto(class_id=0), nếu xe máy(class_id=1) đi vào là vi phạm
                if class_id == 1: 
                    violation_type = "wrong_lane"

            # 3. Phát hiện dừng đỗ sai quy định (No parking)
            elif self.check_point_in_zone(pt, "no_parking"):
                if speed < 2.0: # Coi như xe đang dừng
                    if track_id not in self.stopped_vehicles:
                        self.stopped_vehicles[track_id] = {"start_time": current_time, "last_pos": pt}
                    else:
                        stop_duration = current_time - self.stopped_vehicles[track_id]["start_time"]
                        if stop_duration > self.max_stop_time:
                            violation_type = "no_parking"
                else:
                    # Xe đang di chuyển thì xoá khỏi danh sách dừng
                    if track_id in self.stopped_vehicles:
                        del self.stopped_vehicles[track_id]
            
            else:
                # Nếu không ở trong zone no_parking, xoá tracking dừng đỗ (nếu có)
                if track_id in self.stopped_vehicles:
                    del self.stopped_vehicles[track_id]

            # Ghi nhận vi phạm
            if violation_type:
                new_violations.append({
                    "camera_id": self.camera_id,
                    "violation_type": violation_type,
                    "vehicle_track_id": int(track_id),
                    "confidence": 0.95, # Có thể lấy từ model object detection
                    # Ảnh bằng chứng sẽ được cắt từ frame gốc (crop bounding box + margin)
                    "box": (int(x1[i]), int(y1[i]), int(x2[i]), int(y2[i])),
                    "timestamp": current_time
                })
                self.recorded_violations.add(track_id)
                logger.info(f"Phát hiện vi phạm: {violation_type} (Track ID: {track_id})")

        return new_violations

    def draw_zones(self, frame: np.ndarray) -> np.ndarray:
        """Vẽ các zone lên frame (dùng để debug)"""
        draw_frame = frame.copy()
        colors = {
            "red_light": (0, 0, 255),    # Đỏ
            "wrong_lane": (0, 255, 255), # Vàng
            "no_parking": (255, 0, 0)    # Xanh biển
        }
        
        for zone_name, polygon in self.zones.items():
            if polygon is not None:
                color = colors.get(zone_name, (255, 255, 255))
                cv2.polylines(draw_frame, [polygon], isClosed=True, color=color, thickness=2)
                
                # Ghi tên zone
                M = cv2.moments(polygon)
                if M["m00"] != 0:
                    cX = int(M["m10"] / M["m00"])
                    cY = int(M["m01"] / M["m00"])
                    cv2.putText(draw_frame, zone_name, (cX - 20, cY), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                    
        return draw_frame
