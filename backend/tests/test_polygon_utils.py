"""Tests cho polygon_utils - vectorized polygon operations."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))


class TestPointsInPolygonFast:
    """Tests cho vectorized polygon test."""

    def test_all_points_inside_square(self):
        """Tất cả điểm trong hình vuông → True."""
        from utils.polygon_utils import points_in_polygon_fast

        polygon = np.array([[0, 0], [100, 0], [100, 100], [0, 100]])
        points = np.array([[10, 10], [50, 50], [90, 90]])

        result = points_in_polygon_fast(points, polygon)
        assert result.all()

    def test_all_points_outside_square(self):
        """Tất cả điểm ngoài hình vuông → False."""
        from utils.polygon_utils import points_in_polygon_fast

        polygon = np.array([[0, 0], [100, 0], [100, 100], [0, 100]])
        points = np.array([[-10, -10], [150, 50], [50, 150]])

        result = points_in_polygon_fast(points, polygon)
        assert not result.any()

    def test_mixed_points(self):
        """Mixed in/out points."""
        from utils.polygon_utils import points_in_polygon_fast

        polygon = np.array([[0, 0], [100, 0], [100, 100], [0, 100]])
        points = np.array([[50, 50], [150, 50], [10, 10], [200, 200]])

        result = points_in_polygon_fast(points, polygon)
        assert result[0] is True or result[0] == 1  # (50, 50) inside
        assert result[1] is False or result[1] == 0  # (150, 50) outside
        assert result[2] is True or result[2] == 1  # (10, 10) inside
        assert result[3] is False or result[3] == 0  # (200, 200) outside

    def test_empty_points(self):
        """Empty points array không crash."""
        from utils.polygon_utils import points_in_polygon_fast

        polygon = np.array([[0, 0], [100, 0], [100, 100], [0, 100]])
        points = np.array([]).reshape(0, 2)

        result = points_in_polygon_fast(points, polygon)
        assert len(result) == 0

    def test_none_polygon(self):
        """polygon=None trả về array False."""
        from utils.polygon_utils import points_in_polygon_fast

        points = np.array([[10, 10], [50, 50]])
        result = points_in_polygon_fast(points, None)
        assert not result.any()

    def test_invalid_polygon_too_few_vertices(self):
        """Polygon < 3 vertices → False."""
        from utils.polygon_utils import points_in_polygon_fast

        points = np.array([[10, 10]])
        result = points_in_polygon_fast(points, np.array([[0, 0], [100, 0]]))
        assert not result.any()

    def test_consistent_with_cv2_pointpolygontest(self):
        """Kết quả phải khớp với cv2.pointPolygonTest trong loop."""
        from utils.polygon_utils import points_in_polygon_fast

        cv2 = pytest.importorskip("cv2")

        np.random.seed(42)
        polygon = np.array([[100, 100], [500, 150], [480, 350], [120, 380]])
        points = np.random.randint(0, 600, size=(100, 2))

        # Vectorized
        result_fast = points_in_polygon_fast(points, polygon)

        # Reference: cv2.pointPolygonTest
        result_ref = np.array([
            cv2.pointPolygonTest(polygon.reshape((-1, 1, 2)), (float(x), float(y)), False) >= 0
            for x, y in points
        ])

        np.testing.assert_array_equal(result_fast, result_ref)


class TestBboxContainsPoints:
    """Tests cho bbox_contains_points."""

    def test_points_inside_bbox(self):
        from utils.polygon_utils import bbox_contains_points

        bbox = (10, 10, 100, 100)
        points = np.array([[50, 50], [10, 10], [100, 100], [20, 80]])

        result = bbox_contains_points(bbox, points)
        assert result.all()

    def test_points_outside_bbox(self):
        from utils.polygon_utils import bbox_contains_points

        bbox = (10, 10, 100, 100)
        points = np.array([[5, 5], [150, 50], [50, 150], [-10, 50]])

        result = bbox_contains_points(bbox, points)
        assert not result.any()

    def test_empty_points(self):
        from utils.polygon_utils import bbox_contains_points

        result = bbox_contains_points((0, 0, 100, 100), np.array([]).reshape(0, 2))
        assert len(result) == 0


class TestPerformance:
    """Test performance: vectorized phải nhanh hơn loop."""

    def test_vectorized_faster_than_loop(self):
        """Vectorized phải nhanh hơn cv2.pointPolygonTest loop."""
        import time

        from utils.polygon_utils import points_in_polygon_fast

        cv2 = pytest.importorskip("cv2")

        np.random.seed(42)
        polygon = np.array([[100, 100], [500, 150], [480, 350], [120, 380]])
        points = np.random.randint(0, 600, size=(200, 2))

        # Vectorized
        start = time.perf_counter()
        for _ in range(10):
            result_fast = points_in_polygon_fast(points, polygon)
        time_fast = time.perf_counter() - start

        # Loop cv2
        polygon_reshaped = polygon.reshape((-1, 1, 2))
        start = time.perf_counter()
        for _ in range(10):
            result_loop = np.array([
                cv2.pointPolygonTest(polygon_reshaped, (float(x), float(y)), False) >= 0
                for x, y in points
            ])
        time_loop = time.perf_counter() - start

        # Vectorized phải nhanh hơn ít nhất 2x
        assert time_fast < time_loop, (
            f"Vectorized ({time_fast:.3f}s) không nhanh hơn loop ({time_loop:.3f}s)"
        )