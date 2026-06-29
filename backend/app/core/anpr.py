"""ANPR (Automatic Number Plate Recognition) Engine.

Nhận diện biển số xe từ ảnh crop. Hỗ trợ 2 phương pháp:
    1. LP Detector (YOLO) + OCR (EasyOCR/Tesseract)
    2. OCR-only (chỉ dùng EasyOCR trực tiếp trên crop region)

Args:
    use_gpu: Bật CUDA cho YOLO + EasyOCR
    lp_model_path: Đường dẫn tới YOLO LP detector model (optional)
    languages: Danh sách ngôn ngữ cho EasyOCR (default ['en'])
"""
from typing import Optional, Tuple

import cv2
import numpy as np

from core.logging_config import get_logger

logger = get_logger(__name__)

Box = Tuple[int, int, int, int]  # (x1, y1, x2, y2)


class ANPREngine:
    """Engine nhận diện biển số xe."""

    def __init__(
        self,
        use_gpu: bool = False,
        lp_model_path: Optional[str] = None,
        languages: Optional[list] = None,
    ):
        self.use_gpu = use_gpu
        self.lp_model_path = lp_model_path
        self.languages = languages or ["en"]
        self.reader = None
        self.lp_detector = None
        # Lazy init - chỉ load model khi thực sự dùng
        self._initialized = False

    def _ensure_initialized(self) -> bool:
        """Khởi tạo EasyOCR + LP detector (nếu có). Returns True nếu thành công."""
        # Defensive: nếu __init__ chưa chạy (do __new__ bypass), set defaults
        if not hasattr(self, "_initialized"):
            self._initialized = False
        if not hasattr(self, "reader"):
            self.reader = None
        if not hasattr(self, "lp_detector"):
            self.lp_detector = None
        if not hasattr(self, "use_gpu"):
            self.use_gpu = False
        if not hasattr(self, "languages"):
            self.languages = ["en"]

        if self._initialized:
            return self.reader is not None or self.lp_detector is not None

        self._initialized = True

        # Defensive defaults
        if not hasattr(self, "lp_model_path"):
            self.lp_model_path = None

        # Init EasyOCR
        try:
            import easyocr  # type: ignore
            try:
                self.reader = easyocr.Reader(self.languages, gpu=self.use_gpu)
                logger.info("EasyOCR initialized with languages=%s", self.languages)
            except Exception:
                logger.exception("Failed to init EasyOCR with gpu=%s", self.use_gpu)
                # Fallback without GPU
                if self.use_gpu:
                    try:
                        self.reader = easyocr.Reader(self.languages, gpu=False)
                    except Exception:
                        self.reader = None
        except ImportError:
            logger.warning(
                "EasyOCR not installed. ANPR will work in detection-only mode. "
                "Install with: pip install easyocr"
            )
            self.reader = None

        # Init LP detector
        if self.lp_model_path:
            try:
                from ultralytics import YOLO  # type: ignore
                self.lp_detector = YOLO(self.lp_model_path)
                if self.use_gpu:
                    try:
                        self.lp_detector.to("cuda")
                    except Exception:
                        logger.warning("Failed to move LP detector to GPU")
                logger.info("LP detector initialized from %s", self.lp_model_path)
            except Exception:
                logger.exception("Failed to load LP detector from %s", self.lp_model_path)
                self.lp_detector = None
        else:
            # Mock LP detector
            class MockLPDetector:
                is_available = False
            self.lp_detector = MockLPDetector()

        return self.reader is not None or self.lp_detector is not None

    def crop_vehicle_image(
        self,
        frame: np.ndarray,
        box: Box,
        margin: float = 0.1,
    ) -> Optional[np.ndarray]:
        """Crop ảnh xe từ bounding box với margin.

        Args:
            frame: numpy array (H, W, 3) ảnh gốc.
            box: (x1, y1, x2, y2) bounding box.
            margin: Phần trăm mở rộng (0.1 = 10%).

        Returns:
            Cropped numpy array hoặc None nếu box invalid.
        """
        try:
            x1, y1, x2, y2 = box
            h, w = frame.shape[:2]

            # Margin
            box_w = x2 - x1
            box_h = y2 - y1
            dx = int(box_w * margin)
            dy = int(box_h * margin)

            x1 = max(0, x1 - dx)
            y1 = max(0, y1 - dy)
            x2 = min(w, x2 + dx)
            y2 = min(h, y2 + dy)

            if x2 <= x1 or y2 <= y1:
                return None

            return frame[y1:y2, x1:x2].copy()
        except Exception as exc:
            logger.exception("crop_vehicle_image failed: %s", exc)
            return None

    def _preprocess_for_ocr(self, region: np.ndarray) -> np.ndarray:
        """Tiền xử lý ảnh biển số trước OCR.

        Pipeline:
            1. Upscale nếu width < 120px
            2. Grayscale
            3. CLAHE (adaptive histogram equalization)
            4. Gaussian blur nhẹ
            5. Sharpen
        """
        h, w = region.shape[:2]

        # Step 1: Upscale nếu quá nhỏ
        if w < 120 and w > 0:
            scale = max(2.0, 120.0 / w)
            region = cv2.resize(
                region,
                (int(w * scale), int(h * scale)),
                interpolation=cv2.INTER_CUBIC,
            )

        # Step 2: Grayscale
        if len(region.shape) == 3:
            gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        else:
            gray = region

        # Step 3: CLAHE
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        gray = clahe.apply(gray)

        # Step 4: Gaussian blur
        gray = cv2.GaussianBlur(gray, (3, 3), 0)

        # Step 5: Sharpen
        kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
        gray = cv2.filter2D(gray, -1, kernel)

        return gray

    def read_license_plate(
        self,
        frame: np.ndarray,
        box: Box,
        margin: float = 0.1,
    ) -> Optional[str]:
        """Đọc biển số từ bounding box.

        Args:
            frame: numpy array ảnh gốc.
            box: bounding box của xe.
            margin: margin cho crop.

        Returns:
            Biển số string (cleaned) hoặc None nếu không đọc được.
        """
        if not self._ensure_initialized():
            return None

        # Quick check: nếu không có reader → return None
        if self.reader is None:
            return None

        crop = self.crop_vehicle_image(frame, box, margin=margin)
        if crop is None or crop.size == 0:
            return None

        try:
            processed = self._preprocess_for_ocr(crop)
            # EasyOCR expects BGR/RGB image; pass grayscale too (auto-handle)
            results = self.reader.readtext(processed)

            if not results:
                return None

            # Lấy kết quả có confidence cao nhất
            best = max(results, key=lambda r: r[2] if len(r) >= 3 else 0)
            text = best[1].strip() if len(best) >= 2 else ""

            # Clean: chỉ giữ alphanumeric + dấu gạch ngang
            import re
            cleaned = re.sub(r"[^A-Z0-9\-\.]", "", text.upper())
            return cleaned if cleaned else None

        except Exception as exc:
            logger.exception("EasyOCR failed: %s", exc)
            return None

    def close(self) -> None:
        """Cleanup resources."""
        self.reader = None
        self.lp_detector = None
        self._initialized = False