"""
Tests cho SpeedSmoother và HomographySpeedTracker.

Để tránh import toàn bộ analyze_on_road_base.py (yêu cầu cvzone, ultralytics, etc.),
file này copy-paste các class cần test và kiểm thử độc lập.

Khi project có đầy đủ dependencies (cvzone, ultralytics), có thể chuyển sang import
trực tiếp từ analyze_on_road_base.
"""
import os
import sys
import threading
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

# Import trực tiếp các class từ file nguồn (sẽ fail nếu thiếu cvzone)
# Nếu fail, skip tests để không block CI
try:
    from services.road_services.analyze_on_road_base import (
        SpeedSmoother,
        HomographySpeedTracker,
        _MAX_TRACKED_IDS,
        DEFAULT_FALLBACK_FPS,
    )
    _HAS_DEPS = True
except ImportError as e:
    _HAS_DEPS = False
    _IMPORT_ERROR = str(e)

# Skip tất cả tests nếu thiếu deps
pytestmark = pytest.mark.skipif(
    not _HAS_DEPS,
    reason=f"Missing dependencies for analyze_on_road_base: {_IMPORT_ERROR if not _HAS_DEPS else ''}",
)


class TestSpeedSmootherBackwardCompat:
    """Backward compatibility tests - phải PASS."""

    def test_default_alpha_still_works(self):
        smoother = SpeedSmoother(alpha=0.3)
        smoothed = smoother.update(track_id=1, raw_speed=60.0)
        assert smoothed > 0
        assert isinstance(smoothed, float)

    def test_default_max_tracked_is_500(self):
        smoother = SpeedSmoother(alpha=0.3)
        assert smoother.max_tracked == _MAX_TRACKED_IDS

    def test_explicit_alpha_param_works(self):
        smoother_raw = SpeedSmoother(alpha=1.0)
        assert smoother_raw.update(track_id=1, raw_speed=50.0) == 50.0
        assert smoother_raw.update(track_id=1, raw_speed=70.0) == 70.0

        smoother_med = SpeedSmoother(alpha=0.5)
        first = smoother_med.update(track_id=1, raw_speed=50.0)
        second = smoother_med.update(track_id=1, raw_speed=70.0)
        assert first == 50.0
        assert 50.0 < second < 70.0


class TestSpeedSmootherLRUEviction:
    """Tests cho LRU eviction mới."""

    def test_max_tracked_enforced(self):
        smoother = SpeedSmoother(alpha=0.3, max_tracked=10)
        for i in range(15):
            smoother.update(track_id=i, raw_speed=60.0)
        with smoother._lock:
            assert len(smoother._smoothed) == 10

    def test_lru_evicts_oldest_first(self):
        smoother = SpeedSmoother(alpha=0.3, max_tracked=3)
        smoother.update(track_id=1, raw_speed=50.0)
        smoother.update(track_id=2, raw_speed=50.0)
        smoother.update(track_id=3, raw_speed=50.0)
        smoother.update(track_id=4, raw_speed=50.0)
        with smoother._lock:
            assert 1 not in smoother._smoothed
            assert 2 in smoother._smoothed
            assert 3 in smoother._smoothed
            assert 4 in smoother._smoothed

    def test_updating_existing_track_does_not_evict(self):
        smoother = SpeedSmoother(alpha=0.3, max_tracked=3)
        smoother.update(track_id=1, raw_speed=50.0)
        smoother.update(track_id=2, raw_speed=50.0)
        smoother.update(track_id=3, raw_speed=50.0)
        for _ in range(10):
            smoother.update(track_id=1, raw_speed=60.0)
        with smoother._lock:
            assert len(smoother._smoothed) == 3
            assert 1 in smoother._smoothed


class TestSpeedSmootherThreadSafety:
    """Tests cho thread safety."""

    def test_concurrent_updates_no_crash(self):
        smoother = SpeedSmoother(alpha=0.3, max_tracked=100)
        errors = []

        def worker(thread_id: int):
            try:
                for i in range(100):
                    smoother.update(track_id=thread_id * 1000 + i, raw_speed=50.0 + i)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)
        assert len(errors) == 0
        with smoother._lock:
            assert len(smoother._smoothed) <= 100

    def test_concurrent_clear_and_update(self):
        smoother = SpeedSmoother(alpha=0.3, max_tracked=100)
        errors = []

        def updater():
            try:
                for i in range(100):
                    smoother.update(track_id=i, raw_speed=50.0)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def clearer():
            try:
                for _ in range(50):
                    smoother.clear()
                    time.sleep(0.002)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=updater)
        t2 = threading.Thread(target=clearer)
        t1.start()
        t2.start()
        t1.join(timeout=10.0)
        t2.join(timeout=10.0)
        assert len(errors) == 0


class TestSpeedSmootherPrune:
    """Tests cho prune() method."""

    def test_prune_removes_stale_tracks(self):
        smoother = SpeedSmoother(alpha=0.3)
        smoother.update(track_id=1, raw_speed=50.0)
        smoother.update(track_id=2, raw_speed=60.0)
        smoother.update(track_id=3, raw_speed=70.0)

        removed = smoother.prune({1, 2})

        assert removed == 1
        with smoother._lock:
            assert 1 in smoother._smoothed
            assert 2 in smoother._smoothed
            assert 3 not in smoother._smoothed

    def test_prune_keeps_all_when_all_active(self):
        smoother = SpeedSmoother(alpha=0.3)
        smoother.update(track_id=1, raw_speed=50.0)
        smoother.update(track_id=2, raw_speed=60.0)
        removed = smoother.prune({1, 2})
        assert removed == 0

    def test_prune_empty_active_ids_removes_all(self):
        smoother = SpeedSmoother(alpha=0.3)
        smoother.update(track_id=1, raw_speed=50.0)
        smoother.update(track_id=2, raw_speed=60.0)
        removed = smoother.prune(set())
        assert removed == 2
        with smoother._lock:
            assert len(smoother._smoothed) == 0


class TestSpeedSmootherEdgeCases:

    def test_zero_speed_returns_previous(self):
        smoother = SpeedSmoother(alpha=0.3)
        first = smoother.update(track_id=1, raw_speed=50.0)
        second = smoother.update(track_id=1, raw_speed=0.0)
        assert first == 50.0
        assert second == 50.0

    def test_negative_speed_returns_previous(self):
        smoother = SpeedSmoother(alpha=0.3)
        smoother.update(track_id=1, raw_speed=50.0)
        result = smoother.update(track_id=1, raw_speed=-10.0)
        assert result == 50.0

    def test_clear_empties_dict(self):
        smoother = SpeedSmoother(alpha=0.3)
        smoother.update(track_id=1, raw_speed=50.0)
        smoother.update(track_id=2, raw_speed=60.0)
        smoother.clear()
        with smoother._lock:
            assert len(smoother._smoothed) == 0

    def test_remove_nonexistent_track_does_not_raise(self):
        smoother = SpeedSmoother(alpha=0.3)
        smoother.remove(track_id=999)


class TestHomographySpeedTrackerFPSValidation:

    def test_zero_fps_fallback(self):
        H = np.array([[0.1, 0, 0], [0, 0.1, 0], [0, 0, 1]], dtype=np.float32)
        tracker = HomographySpeedTracker(H=H, fps=0.0)
        assert tracker.fps == DEFAULT_FALLBACK_FPS

    def test_negative_fps_fallback(self):
        H = np.array([[0.1, 0, 0], [0, 0.1, 0], [0, 0, 1]], dtype=np.float32)
        tracker = HomographySpeedTracker(H=H, fps=-5.0)
        assert tracker.fps == DEFAULT_FALLBACK_FPS

    def test_invalid_homography_raises(self):
        with pytest.raises(ValueError):
            HomographySpeedTracker(H=np.zeros((4, 4)), fps=30.0)
        with pytest.raises(ValueError):
            HomographySpeedTracker(H=[[1, 0], [0, 1]], fps=30.0)

    def test_speed_bounded_to_200_kmh(self):
        H = np.array([[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1]], dtype=np.float32)
        tracker = HomographySpeedTracker(H=H, fps=30.0)
        for i in range(20):
            tracker.update(track_id=1, cx=float(i * 1000), cy=float(i * 1000))
        assert tracker.speeds[1] <= 200.0

    def test_remove_clears_track_history(self):
        H = np.array([[0.1, 0, 0], [0, 0.1, 0], [0, 0, 1]], dtype=np.float32)
        tracker = HomographySpeedTracker(H=H, fps=30.0)
        tracker.update(track_id=1, cx=100.0, cy=100.0)
        tracker.update(track_id=1, cx=110.0, cy=100.0)
        assert 1 in tracker.track_history
        tracker.remove(track_id=1)
        assert 1 not in tracker.track_history
        assert 1 not in tracker.speeds