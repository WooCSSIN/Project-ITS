"""Tests cho ViolationEngine."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

# Skip nếu thiếu opencv
_cv2 = pytest.importorskip("cv2", reason="OpenCV không có sẵn")


class TestViolationEngineInit:
    """Tests cho __init__ của ViolationEngine."""

    def test_no_mock_zone_after_init(self):
        """Sau init, zones['red_light'] phải là None (không hardcode mock)."""
        from core.violation_engine import ViolationEngine

        engine = ViolationEngine(camera_id=1, speed_limit_kmh=60.0)
        assert engine.zones["red_light"] is None

    def test_red_light_off_by_default(self):
        """is_red_light_on mặc định False (chưa kết nối camera đèn)."""
        from core.violation_engine import ViolationEngine

        engine = ViolationEngine(camera_id=1, speed_limit_kmh=60.0)
        assert engine.is_red_light_on is False

    def test_speed_limit_from_param(self):
        """speed_limit_kmh từ tham số được dùng."""
        from core.violation_engine import ViolationEngine

        engine = ViolationEngine(camera_id=1, speed_limit_kmh=40.0)
        assert engine.speed_limit_kmh == 40.0

    def test_speed_limit_from_road_name(self):
        """speed_limit_kmh lookup từ SPEED_LIMITS theo road_name."""
        from core.config import SPEED_LIMITS
        from core.violation_engine import ViolationEngine

        road = next(iter(SPEED_LIMITS.keys()))
        engine = ViolationEngine(camera_id=1, road_name=road)
        assert engine.speed_limit_kmh == SPEED_LIMITS[road]

    def test_speed_limit_default_fallback(self):
        """speed_limit_kmh fallback về DEFAULT_SPEED_LIMIT."""
        from core.config import DEFAULT_SPEED_LIMIT
        from core.violation_engine import ViolationEngine

        engine = ViolationEngine(camera_id=999, road_name="Unknown Road XYZ")
        assert engine.speed_limit_kmh == DEFAULT_SPEED_LIMIT


class TestViolationEngineSpeeding:
    """Tests cho speeding detection."""

    def test_speed_above_limit_triggers_violation(self):
        """Xe vượt tốc độ cho phép → violation type=speeding."""
        from core.violation_engine import ViolationEngine

        engine = ViolationEngine(camera_id=1, speed_limit_kmh=50.0)
        classes = np.array([0])  # car
        ids = np.array([42])
        boxes = np.array([[100, 100, 200, 200]])
        speeds = {42: 75.0}  # > 50

        violations = engine.process_frame_tracking(classes, ids, boxes, speeds, 1000.0)

        assert len(violations) == 1
        assert violations[0]["violation_type"] == "speeding"
        assert violations[0]["vehicle_track_id"] == 42
        assert violations[0]["speed_kmh"] == 75.0

    def test_speed_below_limit_no_violation(self):
        """Xe dưới tốc độ cho phép → không có violation."""
        from core.violation_engine import ViolationEngine

        engine = ViolationEngine(camera_id=1, speed_limit_kmh=50.0)
        classes = np.array([0])
        ids = np.array([42])
        boxes = np.array([[100, 100, 200, 200]])
        speeds = {42: 30.0}  # < 50

        violations = engine.process_frame_tracking(classes, ids, boxes, speeds, 1000.0)

        assert len(violations) == 0

    def test_speed_zero_no_violation(self):
        """speed=0 (chưa đo được) không trigger violation."""
        from core.violation_engine import ViolationEngine

        engine = ViolationEngine(camera_id=1, speed_limit_kmh=50.0)
        classes = np.array([0])
        ids = np.array([42])
        boxes = np.array([[100, 100, 200, 200]])
        speeds = {42: 0.0}

        violations = engine.process_frame_tracking(classes, ids, boxes, speeds, 1000.0)

        assert len(violations) == 0


class TestViolationEngineRedLight:
    """Tests cho red_light detection."""

    def test_red_light_off_no_violation_even_in_zone(self):
        """Đèn đỏ tắt → không có vi phạm dù trong zone."""
        from core.violation_engine import ViolationEngine

        engine = ViolationEngine(camera_id=1, speed_limit_kmh=60.0)
        engine.is_red_light_on = False
        # Set zone (vùng vạch dừng)
        engine.zones["red_light"] = np.array([[0, 300], [600, 300], [600, 400], [0, 400]])

        classes = np.array([0])
        ids = np.array([1])
        boxes = np.array([[100, 320, 200, 380]])  # center (150, 350) trong zone
        speeds = {1: 20.0}

        violations = engine.process_frame_tracking(classes, ids, boxes, speeds, 1000.0)

        assert len(violations) == 0

    def test_red_light_on_and_in_zone_triggers_violation(self):
        """Đèn đỏ + trong zone → violation."""
        from core.violation_engine import ViolationEngine

        engine = ViolationEngine(camera_id=1, speed_limit_kmh=60.0)
        engine.set_red_light_status(True)
        engine.zones["red_light"] = np.array([[0, 300], [600, 300], [600, 400], [0, 400]])

        classes = np.array([0])
        ids = np.array([1])
        boxes = np.array([[100, 320, 200, 380]])  # center (150, 350) trong zone
        speeds = {1: 20.0}

        violations = engine.process_frame_tracking(classes, ids, boxes, speeds, 1000.0)

        assert len(violations) == 1
        assert violations[0]["violation_type"] == "red_light"

    def test_red_light_on_but_outside_zone_no_violation(self):
        """Đèn đỏ nhưng ngoài zone → không vi phạm."""
        from core.violation_engine import ViolationEngine

        engine = ViolationEngine(camera_id=1, speed_limit_kmh=60.0)
        engine.set_red_light_status(True)
        engine.zones["red_light"] = np.array([[0, 300], [600, 300], [600, 400], [0, 400]])

        classes = np.array([0])
        ids = np.array([1])
        boxes = np.array([[100, 100, 200, 200]])  # center (150, 150) NGOÀI zone
        speeds = {1: 20.0}

        violations = engine.process_frame_tracking(classes, ids, boxes, speeds, 1000.0)

        assert len(violations) == 0


class TestViolationEngineEdgeCases:
    """Edge cases cho ViolationEngine."""

    def test_empty_tracking_data_no_crash(self):
        """Empty ids/boxes/classes không crash."""
        from core.violation_engine import ViolationEngine

        engine = ViolationEngine(camera_id=1, speed_limit_kmh=60.0)

        # Empty arrays
        violations = engine.process_frame_tracking(
            np.array([]), np.array([]), np.array([]).reshape(0, 4), {}, 1000.0
        )
        assert violations == []

    def test_none_ids_no_crash(self):
        """ids=None không crash."""
        from core.violation_engine import ViolationEngine

        engine = ViolationEngine(camera_id=1, speed_limit_kmh=60.0)
        violations = engine.process_frame_tracking(
            None, None, None, {}, 1000.0
        )
        assert violations == []

    def test_mismatched_array_lengths_no_crash(self):
        """Array lengths không khớp không crash (chỉ warning)."""
        from core.violation_engine import ViolationEngine

        engine = ViolationEngine(camera_id=1, speed_limit_kmh=60.0)
        # classes có 2, ids có 3, boxes có 3
        violations = engine.process_frame_tracking(
            np.array([0, 1]),
            np.array([1, 2, 3]),
            np.array([[0, 0, 10, 10], [20, 20, 30, 30], [40, 40, 50, 50]]),
            {1: 30.0, 2: 30.0, 3: 30.0},
            1000.0,
        )
        # Phải trả về list rỗng do mismatch
        assert violations == []

    def test_violation_dict_has_required_fields(self):
        """Violation dict phải có đủ các trường cần thiết."""
        from core.violation_engine import ViolationEngine

        engine = ViolationEngine(camera_id=5, speed_limit_kmh=40.0)
        classes = np.array([0])
        ids = np.array([10])
        boxes = np.array([[50, 50, 150, 150]])
        speeds = {10: 80.0}

        violations = engine.process_frame_tracking(classes, ids, boxes, speeds, 1234567890.0)

        assert len(violations) == 1
        v = violations[0]
        required_fields = [
            "camera_id", "violation_type", "vehicle_track_id",
            "license_plate", "confidence", "timestamp", "speed_kmh",
            "box", "evidence_image_url",
        ]
        for field in required_fields:
            assert field in v, f"Missing field: {field}"
        assert v["camera_id"] == 5
        assert v["timestamp"] == 1234567890.0


class TestViolationEngineStationary:
    """Tests cho illegal_parking detection."""

    def test_illegal_parking_after_duration(self):
        """Xe đứng yên trong vùng cấm quá thời gian → violation."""
        from core.violation_engine import ViolationEngine

        engine = ViolationEngine(camera_id=1, speed_limit_kmh=60.0)
        engine.zones["no_parking"] = np.array([[0, 0], [600, 0], [600, 400], [0, 400]])

        classes = np.array([0])
        ids = np.array([1])
        boxes = np.array([[100, 100, 200, 200]])
        speeds = {1: 0.5}  # < 2 km/h (stationary threshold)

        # Update nhiều frame để vượt STATIONARY_DURATION_SEC
        start_time = 1000.0
        for i in range(35):
            timestamp = start_time + i  # 35 giây
            violations = engine.process_frame_tracking(
                classes, ids, boxes, speeds, timestamp
            )

        # Phải có ít nhất 1 violation illegal_parking
        assert any(v["violation_type"] == "illegal_parking" for v in violations)

    def test_moving_vehicle_no_illegal_parking(self):
        """Xe di chuyển trong vùng cấm → không có illegal_parking violation."""
        from core.violation_engine import ViolationEngine

        engine = ViolationEngine(camera_id=1, speed_limit_kmh=60.0)
        engine.zones["no_parking"] = np.array([[0, 0], [600, 0], [600, 400], [0, 400]])

        classes = np.array([0])
        ids = np.array([1])
        boxes = np.array([[100, 100, 200, 200]])
        speeds = {1: 30.0}  # > 2 km/h → moving

        # Update nhiều frame
        for i in range(35):
            violations = engine.process_frame_tracking(
                classes, ids, boxes, speeds, 1000.0 + i
            )

        # Không có illegal_parking violation
        assert not any(v["violation_type"] == "illegal_parking" for v in violations)


class TestViolationEngineGetStats:
    """Tests cho get_stats() method."""

    def test_get_stats_returns_expected_fields(self):
        """get_stats() trả về các trường cần thiết."""
        from core.violation_engine import ViolationEngine

        engine = ViolationEngine(camera_id=3, speed_limit_kmh=60.0, road_name="Test Road")
        stats = engine.get_stats()

        assert stats["camera_id"] == 3
        assert stats["road_name"] == "Test Road"
        assert stats["speed_limit_kmh"] == 60.0
        assert stats["is_red_light_on"] is False
        assert "zones_configured" in stats
        assert stats["zones_configured"]["red_light"] is False
        assert stats["tracked_stationary"] == 0


class TestViolationEngineReset:
    """Tests cho reset() method."""

    def test_reset_clears_stationary_tracking(self):
        """reset() xóa stationary tracking."""
        from core.violation_engine import ViolationEngine

        engine = ViolationEngine(camera_id=1, speed_limit_kmh=60.0)
        engine._stationary_started[1] = 1000.0
        engine._stationary_history[1] = [1000.0, 1001.0]

        engine.reset()

        assert len(engine._stationary_started) == 0
        assert len(engine._stationary_history) == 0