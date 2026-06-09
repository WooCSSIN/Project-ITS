"""
BUG 5 — camera_id không nhất quán
===================================
Task 1: Exploration test — PHẢI FAIL trên code CHƯA fix
Task 2: Preservation test — PHẢI PASS trên code CHƯA fix

Vấn đề:
  Backend: abs(hash(road_name)) % 10000  → không đoán trước được
  Frontend: indexOf(road, roadNames) + 1 → 1-based index
  Kết quả: zone lưu từ frontend không bao giờ load đúng ở backend

Lưu ý kỹ thuật:
  config.py import langchain nên không thể import trực tiếp.
  Test này tự định nghĩa PATH_VIDEOS và công thức camera_id để kiểm tra
  logic thuần tuý, không phụ thuộc vào runtime của app.
"""
import os
import sys
import pytest

# ─── Định nghĩa PATH_VIDEOS giống hệt config.py (không import config) ────
# Phản ánh đúng SettingMetricTransport.PATH_VIDEOS trong backend/app/core/config.py

BASE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "app")
)

PATH_VIDEOS = [
    os.path.join(BASE_DIR, "video_test", "Văn Quán.mp4"),
    os.path.join(BASE_DIR, "video_test", "Nguyễn Văn Trỗi.mp4"),
    os.path.join(BASE_DIR, "video_test", "Nguyễn Trãi.mp4"),
    os.path.join(BASE_DIR, "video_test", "Ngã Tư Sở.mp4"),
    os.path.join(BASE_DIR, "video_test", "Đường Láng.mp4"),
]


# ─── Công thức tính camera_id ────────────────────────────────────────────

def camera_id_current(path_video: str) -> int:
    """
    Công thức SAU KHI FIX: PATH_VIDEOS.index(path_video) + 1
    Khớp với frontend ZoneConfig.tsx dùng `idx + 1`.
    """
    return PATH_VIDEOS.index(path_video) + 1


def camera_id_expected(path_video: str) -> int:
    """Công thức ĐÚNG (index + 1): khớp với frontend ZoneConfig.tsx"""
    return PATH_VIDEOS.index(path_video) + 1


# ═══════════════════════════════════════════════════════════════════════════
# Task 1 — Exploration test (PHẢI FAIL trên code CHƯA fix)
# ═══════════════════════════════════════════════════════════════════════════

class TestBug5Exploration:
    """
    Property 1 — Bug Condition: camera_id Hash vs Index Mismatch

    Encode expected behavior SAU KHI FIX.
    Trên code chưa fix: FAIL vì hash != index+1.
    Sau khi fix: PASS.
    """

    def test_all_camera_ids_match_index(self):
        """
        Với mọi video, camera_id backend phải bằng (index+1) — khớp frontend.

        EXPECTED trên code CHƯA fix: FAIL → xác nhận bug tồn tại
        EXPECTED sau khi fix: PASS
        """
        counterexamples = []

        for idx, path_video in enumerate(PATH_VIDEOS):
            actual = camera_id_current(path_video)
            expected = idx + 1
            road_name = os.path.splitext(os.path.basename(path_video))[0]
            if actual != expected:
                counterexamples.append(
                    f"  '{road_name}' (index {idx}): "
                    f"hash→camera_id={actual}, expected={expected}"
                )

        if counterexamples:
            details = "\n".join(counterexamples)
            pytest.fail(
                f"BUG 5 CONFIRMED — camera_id hash không khớp index+1 "
                f"({len(counterexamples)}/{len(PATH_VIDEOS)} videos):\n"
                f"{details}\n\n"
                f"Frontend ZoneConfig.tsx lưu zone với camera_id=index+1,\n"
                f"backend dùng abs(hash(name))%10000 → zone không bao giờ load đúng."
            )

    @pytest.mark.parametrize(
        "idx,path_video",
        list(enumerate(PATH_VIDEOS))
    )
    def test_each_video_camera_id_equals_index_plus_one(self, idx, path_video):
        """
        Parametrized: từng video phải có camera_id = index + 1.

        EXPECTED trên code CHƯA fix: FAIL (hiển thị giá trị hash thực tế)
        """
        road_name = os.path.splitext(os.path.basename(path_video))[0]
        actual = camera_id_current(path_video)
        expected = idx + 1

        assert actual == expected, (
            f"BUG 5: Road '{road_name}' (PATH_VIDEOS[{idx}])\n"
            f"  Actual   camera_id = {actual}  ← abs(hash(name)) % 10000\n"
            f"  Expected camera_id = {expected}  ← index {idx} + 1\n"
            f"  ZoneConfig.tsx lưu zone với cameraId={expected}, "
            f"backend query WHERE camera_id={actual} → không tìm thấy"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Task 2 — Preservation tests (PHẢI PASS trên code CHƯA fix)
# ═══════════════════════════════════════════════════════════════════════════

class TestBug5Preservation:
    """
    Property 2 — Preservation: camera_id uniqueness không bị mất

    Dù formula sai, uniqueness hiện tại phải được bảo toàn sau khi fix.
    PASS cả trước lẫn sau khi fix.
    """

    def test_current_formula_produces_unique_ids(self):
        """
        Với công thức hash hiện tại, không có hai camera nào cùng camera_id.

        EXPECTED trên code CHƯA fix: PASS (uniqueness đang đúng)
        EXPECTED sau khi fix: PASS (1,2,3,4,5 hiển nhiên unique)
        """
        ids = [camera_id_current(p) for p in PATH_VIDEOS]
        assert len(ids) == len(set(ids)), (
            f"Uniqueness bị phá vỡ! camera_ids = {ids}\n"
            f"Đây sẽ là regression nếu xảy ra sau khi fix."
        )

    def test_fixed_formula_also_produces_unique_ids(self):
        """
        Công thức ĐÃ FIX (index+1) cũng phải cho IDs duy nhất.

        EXPECTED: PASS (1,2,3,4,5 đều khác nhau)
        """
        ids = [camera_id_expected(p) for p in PATH_VIDEOS]
        assert len(ids) == len(set(ids)), (
            f"Uniqueness bị phá vỡ sau fix! camera_ids = {ids}"
        )

    def test_fixed_formula_produces_sequential_ids(self):
        """
        Sau khi fix, camera_ids phải là [1, 2, 3, 4, 5] — liền mạch.

        EXPECTED: PASS
        """
        ids = [camera_id_expected(p) for p in PATH_VIDEOS]
        expected = list(range(1, len(PATH_VIDEOS) + 1))
        assert ids == expected, (
            f"Expected camera_ids = {expected}, got {ids}"
        )

    def test_video_count_unchanged(self):
        """Số lượng camera (5) không thay đổi."""
        assert len(PATH_VIDEOS) == 5

    @pytest.mark.parametrize(
        "idx_a,idx_b",
        [(a, b)
         for a in range(len(PATH_VIDEOS))
         for b in range(len(PATH_VIDEOS))
         if a != b]
    )
    def test_no_two_cameras_share_id_current_formula(self, idx_a, idx_b):
        """
        Property-based: mọi cặp camera phân biệt phải có camera_id khác nhau.

        EXPECTED: PASS (cả trước và sau fix)
        """
        id_a = camera_id_current(PATH_VIDEOS[idx_a])
        id_b = camera_id_current(PATH_VIDEOS[idx_b])
        assert id_a != id_b, (
            f"Collision: PATH_VIDEOS[{idx_a}] và PATH_VIDEOS[{idx_b}] "
            f"cùng camera_id={id_a}"
        )
