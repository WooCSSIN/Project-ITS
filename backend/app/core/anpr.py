import cv2
import os
import numpy as np
import logging
import re
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)

try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False
    logger.warning("Thư viện easyocr chưa được cài đặt. Module ANPR sẽ không hoạt động. Vui lòng cài đặt: pip install easyocr")


class LicensePlateDetector:
    """
    YOLOv8n-lp: Model YOLO nhỏ (~6MB) chuyên detect vùng biển số trước khi OCR.
    Tăng accuracy EasyOCR đáng kể vì OCR chỉ chạy trên vùng biển số thay vì toàn bộ xe.

    Nếu không có model LP, class này trả về None và ANPREngine sẽ fallback
    về phương pháp cũ (crop nửa dưới xe).
    """

    def __init__(self, model_path: str = None, device: str = "cpu", conf: float = 0.3):
        """
        Args:
            model_path: Đường dẫn đến model YOLOv8n-lp (.pt hoặc .onnx).
                        Nếu None, tự tìm trong thư mục ai_models/license_plate/.
            device: 'cpu' hoặc 'cuda'
            conf: Confidence threshold cho LP detection
        """
        self._model = None
        self._device = device
        self._conf = conf

        if model_path is None:
            # Tìm model LP trong thư mục mặc định
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            candidates = [
                os.path.join(base_dir, "ai_models", "license_plate", "best.pt"),
                os.path.join(base_dir, "ai_models", "license_plate", "best.onnx"),
                os.path.join(base_dir, "ai_models", "license_plate", "yolov8n-lp.pt"),
            ]
            for path in candidates:
                if os.path.exists(path):
                    model_path = path
                    break

        if model_path and os.path.exists(model_path):
            try:
                from ultralytics import YOLO
                self._model = YOLO(model_path)
                logger.info("LicensePlateDetector: Loaded LP model from %s", model_path)
            except Exception as e:
                logger.warning("LicensePlateDetector: Lỗi load model LP (%s). Sẽ fallback.", e)
        else:
            logger.info("LicensePlateDetector: Không tìm thấy model LP. Sẽ dùng phương pháp crop nửa dưới.")

    @property
    def is_available(self) -> bool:
        return self._model is not None

    def detect(self, vehicle_crop: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """
        Detect vùng biển số trong ảnh xe đã crop.
        Returns: list of (x1, y1, x2, y2) boxes cho từng biển số tìm thấy.
        """
        if self._model is None:
            return []

        try:
            results = self._model.predict(
                vehicle_crop,
                device=self._device,
                conf=self._conf,
                verbose=False,
            )
            boxes = []
            for r in results:
                if r.boxes is not None:
                    for box in r.boxes.xyxy.cpu().numpy().astype(int):
                        boxes.append(tuple(box.tolist()))
            return boxes
        except Exception as e:
            logger.warning("LP detection error: %s", e)
            return []


class ANPREngine:
    """
    Automatic Number Plate Recognition Engine — Phiên bản nâng cấp Giai đoạn 3.

    Cải tiến so với phiên bản cũ:
    1. Hỗ trợ LicensePlateDetector (YOLOv8n-lp) để detect vùng biển số trước khi OCR
       → tăng accuracy EasyOCR đáng kể
    2. Fallback về phương pháp crop nửa dưới khi không có LP model
    3. Chỉ trigger khi có violation mới (on_violation_only mode) — không chạy mọi frame
    """
    
    def __init__(self, use_gpu: bool = False, lp_model_path: str = None):
        """
        Args:
            use_gpu: Dùng GPU cho EasyOCR và LP detection
            lp_model_path: Đường dẫn model LP detection (None = tự tìm hoặc bỏ qua)
        """
        self.use_gpu = use_gpu
        self.reader = None

        # License Plate Detector (YOLO model riêng)
        device = "cuda" if use_gpu else "cpu"
        self.lp_detector = LicensePlateDetector(model_path=lp_model_path, device=device)

        if EASYOCR_AVAILABLE:
            # Khởi tạo EasyOCR với ngôn ngữ tiếng Anh (đọc số và chữ cái)
            logger.info("Khởi tạo EasyOCR model (GPU=%s)...", use_gpu)
            try:
                self.reader = easyocr.Reader(['en'], gpu=use_gpu)
                logger.info("EasyOCR đã sẵn sàng!")
            except Exception as e:
                logger.error("Lỗi khi khởi tạo EasyOCR: %s", e)

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

    def _ocr_on_region(self, region: np.ndarray) -> Optional[str]:
        """Chạy EasyOCR trên một vùng ảnh và trả về biển số tốt nhất."""
        if region is None or region.size == 0:
            return None

        h, w = region.shape[:2]

        # Step 1: Upscale nếu ảnh quá nhỏ
        if w < 120:
            scale = max(2.0, 120.0 / w)
            region = cv2.resize(
                region,
                (int(w * scale), int(h * scale)),
                interpolation=cv2.INTER_CUBIC
            )

        # Step 2: Grayscale
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)

        # Step 3: CLAHE thay equalizeHist
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        gray = clahe.apply(gray)

        # Step 4: Gaussian blur nhẹ
        gray = cv2.GaussianBlur(gray, (3, 3), 0)

        # Step 5: Sharpen
        kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
        gray = cv2.filter2D(gray, -1, kernel)

        results = self.reader.readtext(gray)

        best_text = ""
        best_conf = 0.0

        for (bbox, text, prob) in results:
            cleaned_text = self.clean_plate_text(text)
            if len(cleaned_text) >= 4 and prob > best_conf:
                if self.validate_vietnamese_plate(cleaned_text):
                    best_text = cleaned_text
                    best_conf = prob

        if best_text:
            logger.info("Đọc được biển số: %s (Tự tin: %.2f)", best_text, best_conf)
            return best_text

        return None

    def read_license_plate(self, frame: np.ndarray, vehicle_box: Tuple[int, int, int, int]) -> Optional[str]:
        """
        Hàm chính để đọc biển số từ frame và toạ độ xe.
        
        Flow:
        1. Crop ảnh xe từ frame
        2. Nếu có LP detector → detect vùng biển số → OCR vùng đó
        3. Nếu không có LP detector → crop nửa dưới xe → OCR (fallback)
        """
        if not self.reader:
            return None

        try:
            # 1. Cắt ảnh xe
            cropped_img = self.crop_vehicle_image(frame, vehicle_box, margin=0.0)

            if cropped_img is None or cropped_img.size == 0:
                return None

            # 2. Thử detect biển số bằng LP model trước
            if self.lp_detector.is_available:
                lp_boxes = self.lp_detector.detect(cropped_img)

                if lp_boxes:
                    # Sắp xếp theo diện tích giảm dần, ưu tiên box lớn nhất
                    lp_boxes.sort(key=lambda b: (b[2]-b[0]) * (b[3]-b[1]), reverse=True)

                    for lp_box in lp_boxes:
                        x1, y1, x2, y2 = lp_box
                        h, w = cropped_img.shape[:2]
                        # Clamp to image bounds
                        x1, y1 = max(0, x1), max(0, y1)
                        x2, y2 = min(w, x2), min(h, y2)

                        plate_region = cropped_img[y1:y2, x1:x2]
                        result = self._ocr_on_region(plate_region)
                        if result:
                            return result

                    # LP detected nhưng OCR failed — vẫn thử fallback
                    logger.debug("LP detected nhưng OCR không đọc được. Thử fallback.")

            # 3. Fallback: crop nửa dưới xe
            h, w = cropped_img.shape[:2]
            lower_half = cropped_img[int(h * 0.3):h, 0:w]
            return self._ocr_on_region(lower_half)
            
        except Exception as e:
            logger.error("Lỗi xử lý ANPR: %s", e)
            return None
