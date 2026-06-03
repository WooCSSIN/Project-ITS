import cv2
import numpy as np
import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False
    logger.warning("Thư viện easyocr chưa được cài đặt. Module ANPR sẽ không hoạt động. Vui lòng cài đặt: pip install easyocr")


class ANPREngine:
    """
    Automatic Number Plate Recognition Engine
    Sử dụng EasyOCR để nhận diện biển số xe từ hình ảnh bị cắt (cropped image).
    """
    
    def __init__(self, use_gpu: bool = False):
        self.use_gpu = use_gpu
        self.reader = None
        
        if EASYOCR_AVAILABLE:
            # Khởi tạo EasyOCR với ngôn ngữ tiếng Anh (đọc số và chữ cái)
            logger.info(f"Khởi tạo EasyOCR model (GPU={use_gpu})...")
            try:
                self.reader = easyocr.Reader(['en'], gpu=use_gpu)
                logger.info("EasyOCR đã sẵn sàng!")
            except Exception as e:
                logger.error(f"Lỗi khi khởi tạo EasyOCR: {e}")

    def clean_plate_text(self, text: str) -> str:
        """
        Làm sạch chuỗi nhận diện được để loại bỏ các ký tự thừa
        Biển số VN thường có dạng: 30A-123.45 hoặc 30A12345
        """
        # Xoá các ký tự không phải chữ và số
        cleaned = re.sub(r'[^A-Z0-9]', '', text.upper())
        return cleaned

    def validate_vietnamese_plate(self, plate_text: str) -> bool:
        """
        Kiểm tra độ dài và format có phù hợp với biển số Việt Nam không
        Thông thường biển số dài từ 7 đến 9 ký tự (Vd: 30A12345)
        """
        if len(plate_text) < 7 or len(plate_text) > 9:
            return False
            
        # 2 ký tự đầu thường là số (mã tỉnh, vd: 29, 30, 51...)
        if not plate_text[:2].isdigit():
            return False
            
        return True

    def crop_vehicle_image(
        self, 
        frame: np.ndarray, 
        box: Tuple[int, int, int, int], 
        margin: float = 0.1
    ) -> np.ndarray:
        """
        Cắt ảnh xe từ frame dựa vào bounding box với một chút lề (margin).
        Để OCR có nhiều không gian nhận diện hơn.
        """
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = box
        
        # Thêm margin
        box_w = x2 - x1
        box_h = y2 - y1
        
        mx = int(box_w * margin)
        my = int(box_h * margin)
        
        nx1 = max(0, x1 - mx)
        ny1 = max(0, y1 - my)
        nx2 = min(w, x2 + mx)
        ny2 = min(h, y2 + my)
        
        return frame[ny1:ny2, nx1:nx2]

    def read_license_plate(self, frame: np.ndarray, vehicle_box: Tuple[int, int, int, int]) -> Optional[str]:
        """
        Hàm chính để đọc biển số từ frame và toạ độ xe.
        """
        if not self.reader:
            return None

        try:
            # 1. Cắt ảnh xe
            cropped_img = self.crop_vehicle_image(frame, vehicle_box, margin=0.0)
            
            # (Tuỳ chọn) Bạn có thể dùng 1 model YOLO chuyên detect biển số (plate detector) 
            # để cắt chính xác vào biển số trước khi OCR để tăng độ chính xác.
            # Ở đây ta dùng OCR quét toàn bộ ảnh xe hoặc nửa dưới của xe.
            
            # Cắt nửa dưới của xe vì biển số thường nằm ở dưới
            h, w = cropped_img.shape[:2]
            lower_half = cropped_img[int(h*0.3):h, 0:w]
            
            # 2. Xử lý ảnh cơ bản để tăng độ nét (tuỳ chọn)
            gray = cv2.cvtColor(lower_half, cv2.COLOR_BGR2GRAY)
            # Tăng độ tương phản
            gray = cv2.equalizeHist(gray)
            
            # 3. Đọc chữ bằng EasyOCR
            results = self.reader.readtext(gray)
            
            best_text = ""
            best_conf = 0.0
            
            for (bbox, text, prob) in results:
                cleaned_text = self.clean_plate_text(text)
                
                # Ưu tiên các đoạn text giống biển số và có độ tự tin cao
                if len(cleaned_text) >= 4 and prob > best_conf:
                    if self.validate_vietnamese_plate(cleaned_text):
                        best_text = cleaned_text
                        best_conf = prob
                        
            if best_text:
                logger.info(f"Đọc được biển số: {best_text} (Tự tin: {best_conf:.2f})")
                return best_text
                
            return None
            
        except Exception as e:
            logger.error(f"Lỗi xử lý ANPR: {e}")
            return None
