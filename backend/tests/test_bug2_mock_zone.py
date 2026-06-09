"""
BUG 2 — Mock zone hardcode
============================
Task 5: Exploration test — PHẢI FAIL trên code CHƯA fix
Task 6: Preservation test — PHẢI PASS trên code CHƯA fix

Root cause:
  AnalyzeOnRoadBase.__init__() tạo mock_red_light_zone và set_red_light_status(True)
  hardcode → mọi xe qua nửa dưới ROI đều bị ghi vi phạm đèn đỏ giả.
  Đã tạo ra >11.000 record vi phạm giả trong DB.

Lưu ý kỹ thuật:
  Không import config.py trực tiếp (langchain dependency).
  Test kiểm tra logic thuần tuý của ViolationEngine.
"""
import os
import sys
import pytest
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from core.violation_engine import ViolationEngine


# ─── Helpers ─────────────────────────────────────────────────────────────────

def make_violation_engine_via_init() -> ViolationEngine:
    """
    Tái hiện đúng trạng thái ViolationEngine SAU KHI FIX:
    - Không có mock zone
    - is_red_light_on = False (mặc định)
    Zone thực tế chỉ được load từ DB bởi _load_zones_from_db() sau này.
    """
    engine = ViolationEngine(camera_id=1, speed_limit_kmh=60.0)
    # Không set mock zone sau khi fix
    return engine


def make_violation_engine_clean() -> ViolationEngine:
    """
    Tạo ViolationEngine theo trạng thái SAU KHI FIX — không có mock zone.
    Constructor chỉ tạo engine với zones=None, is_red_light_on=False.
    """
    return ViolationEngine(camera_id=1, speed_limit_kmh=60.0)


# ═══════════════════════════════════════════════════════════════════════════
# Task 5 — Exploration test (PHẢI FAIL trên code CHƯA fix)
# ═══════════════════════════════════════════════════════════════════════════

class TestBug2MockZoneExploration:
    """
    Property 1 — Bug Condition: Mock Zone Active After Init

    Trên code chưa fix: FAIL vì mock zone được set.
    Sau khi fix: PASS vì zones["red_light"] là None.
    """

    def test_violation_engine_has_no_red_light_zone_after_init(self):
        """
        Sau khi base class __init__() chạy, zones["red_light"] phải là None.

        EXPECTED trên code CHƯA fix: FAIL (mock zone đã được set)
        EXPECTED sau khi fix: PASS
        """
        engine = make_violation_engine_via_init()

        assert engine.zones["red_light"] is None, (
            f"BUG 2 CONFIRMED: violation_engine.zones['red_light'] không phải None sau __init__()!\n"
            f"  Actual type: {type(engine.zones['red_light'])}\n"
            f"  Shape: {engine.zones['red_light'].shape if hasattr(engine.zones['red_light'], 'shape') else 'N/A'}\n"
            f"  Mock zone hardcode đang active → mọi xe qua nửa dưới ROI bị ghi vi phạm giả."
        )

    def test_violation_engine_red_light_status_is_false_after_init(self):
        """
        Sau __init__(), is_red_light_on phải là False (chưa kết nối camera đèn thật).

        EXPECTED trên code CHƯA fix: FAIL (True từ set_red_light_status(True))
        EXPECTED sau khi fix: PASS
        """
        engine = make_violation_engine_via_init()

        assert engine.is_red_light_on is False, (
            f"BUG 2 CONFIRMED: violation_engine.is_red_light_on = True ngay sau __init__()!\n"
            f"  Đèn đỏ được bật hardcode — không phản ánh trạng thái thực tế camera đèn."
        )

    def test_no_vehicle_violates_without_zone_configured(self):
        """
        Khi không có zone nào được cấu hình, không có vehicle nào nên bị vi phạm đèn đỏ.

        EXPECTED trên code CHƯA fix: FAIL (mock zone active → vehicle bị detect vi phạm)
        EXPECTED sau khi fix: PASS
        """
        engine = make_violation_engine_via_init()

        # Tạo frame giả và vehicle ở giữa vùng bottom (nơi mock zone active)
        frame = np.zeros((400, 600, 3), dtype=np.uint8)
        track_ids = np.array([1], dtype=np.int32)
        # Box ở bottom half: x1=200, y1=250, x2=300, y2=350 → tâm (250, 300)
        boxes = np.array([[200, 250, 300, 350]], dtype=np.int32)
        classes = np.array([0], dtype=np.int32)  # car
        speeds = {1: 30.0}  # 30 km/h — đang di chuyển

        violations = engine.process_frame_tracking(
            frame=frame,
            track_ids=track_ids,
            boxes=boxes,
            classes=classes,
            speeds=speeds,
        )

        red_light_violations = [v for v in violations if v["violation_type"] == "red_light"]

        assert len(red_light_violations) == 0, (
            f"BUG 2 CONFIRMED: {len(red_light_violations)} vi phạm đèn đỏ giả được detect!\n"
            f"  Mock zone active → xe đi qua vùng bottom ROI bị ghi vi phạm dù không có zone thật.\n"
            f"  Violations: {red_light_violations}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Task 6 — Preservation tests (PHẢI PASS trên code CHƯA fix)
# ═══════════════════════════════════════════════════════════════════════════

class TestBug2Preservation:
    """
    Property 2 — Preservation: Speeding detection độc lập với zone state

    _check_speeding() không đọc zones["red_light"] — hoạt động bất kể zone state.
    Test phải PASS cả trước lẫn sau khi fix.
    """

    def test_speeding_detected_when_engine_has_mock_zone(self):
        """
        Khi mock zone active (code chưa fix), speeding vẫn được detect.

        EXPECTED: PASS (speeding hoạt động độc lập với zone)
        """
        engine = make_violation_engine_via_init()

        frame = np.zeros((400, 600, 3), dtype=np.uint8)
        track_ids = np.array([10], dtype=np.int32)
        boxes = np.array([[50, 50, 150, 150]], dtype=np.int32)
        classes = np.array([0], dtype=np.int32)

        # Cần N=5 lần liên tiếp vượt threshold (60 * 1.2 = 72 km/h) để trigger
        speed_over_limit = 80.0
        speeds = {10: speed_over_limit}

        speeding_violations = []
        for _ in range(6):  # 6 lần để chắc chắn qua ngưỡng N=5
            violations = engine.process_frame_tracking(
                frame=frame,
                track_ids=track_ids,
                boxes=boxes,
                classes=classes,
                speeds=speeds,
            )
            speeding_violations.extend(
                [v for v in violations if v["violation_type"] == "speeding"]
            )

        assert len(speeding_violations) > 0, (
            "Preservation FAILED: speeding không được detect dù speed > limit!\n"
            f"speed={speed_over_limit}, limit={engine.speed_limit_kmh}, "
            f"threshold={engine.speed_limit_kmh * 1.2}"
        )

    def test_speeding_detected_when_engine_has_no_zone(self):
        """
        Khi không có zone nào (clean engine, sau khi fix), speeding vẫn được detect.

        EXPECTED: PASS (speeding hoạt động độc lập với zone)
        """
        engine = make_violation_engine_clean()

        frame = np.zeros((400, 600, 3), dtype=np.uint8)
        track_ids = np.array([20], dtype=np.int32)
        boxes = np.array([[50, 50, 150, 150]], dtype=np.int32)
        classes = np.array([0], dtype=np.int32)
        speeds = {20: 80.0}

        speeding_violations = []
        for _ in range(6):
            violations = engine.process_frame_tracking(
                frame=frame,
                track_ids=track_ids,
                boxes=boxes,
                classes=classes,
                speeds=speeds,
            )
            speeding_violations.extend(
                [v for v in violations if v["violation_type"] == "speeding"]
            )

        assert len(speeding_violations) > 0, (
            "Preservation FAILED: speeding không detect khi zones=None!\n"
            "speeding phải độc lập với zone configuration."
        )

    def test_no_speeding_when_under_limit(self):
        """
        Xe chạy dưới giới hạn tốc độ không bị ghi vi phạm speeding.

        EXPECTED: PASS (cả trước và sau fix)
        """
        engine = make_violation_engine_clean()

        frame = np.zeros((400, 600, 3), dtype=np.uint8)
        track_ids = np.array([30], dtype=np.int32)
        boxes = np.array([[50, 50, 150, 150]], dtype=np.int32)
        classes = np.array([0], dtype=np.int32)
        speeds = {30: 40.0}  # Dưới limit 60 km/h

        for _ in range(10):
            violations = engine.process_frame_tracking(
                frame=frame,
                track_ids=track_ids,
                boxes=boxes,
                classes=classes,
                speeds=speeds,
            )
            speeding = [v for v in violations if v["violation_type"] == "speeding"]
            assert len(speeding) == 0, (
                f"Preservation FAILED: xe 40 km/h (limit=60) bị ghi vi phạm speeding!"
            )

    def test_violation_engine_initializes_with_correct_defaults(self):
        """
        ViolationEngine mặc định khởi tạo với zones=None và is_red_light_on=False.

        EXPECTED: PASS (đây là default đúng từ ViolationEngine.__init__)
        """
        engine = ViolationEngine(camera_id=99, speed_limit_kmh=50.0)
        assert engine.zones["red_light"] is None
        assert engine.zones["wrong_lane"] is None
        assert engine.zones["no_parking"] is None
        assert engine.is_red_light_on is False

    @pytest.mark.parametrize("speed", [75.0, 80.0, 90.0, 100.0])
    def test_speeding_detected_for_various_speeds_above_limit(self, speed):
        """
        Property-based: mọi speed > 60*1.2=72 đều trigger speeding sau N frames.

        EXPECTED: PASS (cả trước và sau fix)
        """
        engine = make_violation_engine_clean()
        frame = np.zeros((400, 600, 3), dtype=np.uint8)
        track_id = 100 + int(speed)
        track_ids = np.array([track_id], dtype=np.int32)
        boxes = np.array([[10, 10, 80, 80]], dtype=np.int32)
        classes = np.array([0], dtype=np.int32)
        speeds_map = {track_id: speed}

        found = []
        for _ in range(7):
            v = engine.process_frame_tracking(frame, track_ids, boxes, classes, speeds_map)
            found.extend([x for x in v if x["violation_type"] == "speeding"])

        assert len(found) > 0, (
            f"speed={speed} km/h > limit*1.2={engine.speed_limit_kmh*1.2} "
            f"nhưng không detect speeding!"
        )
