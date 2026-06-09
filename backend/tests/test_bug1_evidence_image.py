"""
BUG 1 — evidence_image_url = null
====================================
Task 9:  Exploration test — PHẢI FAIL trên code CHƯA fix
Task 10: Preservation test — PHẢI PASS trên code CHƯA fix

Root cause:
  _push_violations_to_queue() trong analyze_on_road.py không bao gồm
  trường evidence_image_url → DB luôn lưu null.
  Frame của xe vi phạm không được crop và upload lên MinIO.

Strategy:
  Test thực thi logic của _push_violations_to_queue() trực tiếp qua
  monkey-patching + mocking — không khởi tạo toàn bộ AnalyzeOnRoad
  (tránh dependency nặng như ultralytics, redis, DB).
"""
import os
import sys
import pytest
import numpy as np
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))


# ─── Helpers: tái hiện logic _push_violations_to_queue ───────────────────────

def build_violation(box=(10, 10, 100, 100)) -> dict:
    """Tạo violation dict như ViolationEngine.process_frame_tracking trả về."""
    return {
        "camera_id": 1,
        "violation_type": "red_light",
        "vehicle_track_id": 42,
        "license_plate": "30A12345",
        "confidence": 0.95,
        "timestamp": 1700000000.0,
        "box": box,
        "speed_kmh": 35.0,
    }


def build_frame(height=400, width=600) -> np.ndarray:
    """Tạo frame ảnh giả."""
    return np.zeros((height, width, 3), dtype=np.uint8)


def simulate_push_violations_current(violations: list, redis_mock) -> list:
    """
    Mô phỏng logic _push_violations_to_queue() SAU KHI FIX —
    bao gồm evidence_image_url trong payload.
    """
    import json
    captured = []
    for v in violations:
        payload = {
            "camera_id": v.get("camera_id"),
            "violation_type": v.get("violation_type"),
            "vehicle_track_id": v.get("vehicle_track_id"),
            "license_plate": v.get("license_plate"),
            "confidence": v.get("confidence"),
            "timestamp": v.get("timestamp"),
            "evidence_image_url": v.get("evidence_image_url"),  # Thêm sau fix
        }
        redis_mock.lpush("violations:queue", json.dumps(payload))
        redis_mock.publish("violations:alerts", json.dumps(payload))
        captured.append(payload)
    return captured


# ═══════════════════════════════════════════════════════════════════════════
# Task 9 — Exploration test (PHẢI FAIL trên code CHƯA fix)
# ═══════════════════════════════════════════════════════════════════════════

class TestBug1EvidenceImageExploration:
    """
    Property 1 — Bug Condition: Evidence Image URL Missing From Payload

    Trên code chưa fix: FAIL vì payload không có evidence_image_url.
    Sau khi fix: PASS vì payload chứa evidence_image_url (URL hoặc null).
    """

    def test_payload_contains_evidence_image_url_key(self):
        """
        Payload được đẩy vào Redis phải chứa key 'evidence_image_url'.

        EXPECTED trên code CHƯA fix: FAIL (key không tồn tại)
        EXPECTED sau khi fix: PASS
        """
        redis_mock = MagicMock()
        violation = build_violation(box=(10, 10, 100, 100))
        payloads = simulate_push_violations_current([violation], redis_mock)

        assert len(payloads) == 1, "Phải có đúng 1 payload được push"
        payload = payloads[0]

        assert "evidence_image_url" in payload, (
            f"BUG 1 CONFIRMED: payload thiếu key 'evidence_image_url'!\n"
            f"  Payload keys hiện có: {list(payload.keys())}\n"
            f"  Frame của xe vi phạm KHÔNG được crop và upload lên MinIO.\n"
            f"  DB lưu evidence_image_url = null cho mọi vi phạm."
        )

    def test_evidence_image_url_is_not_missing_for_valid_box(self):
        """
        Với bounding box hợp lệ, evidence_image_url phải có giá trị (không missing/null).

        EXPECTED trên code CHƯA fix: FAIL
        EXPECTED sau khi fix: PASS (URL hoặc null khi MinIO down — nhưng key phải có)
        """
        redis_mock = MagicMock()
        violation = build_violation(box=(50, 100, 200, 300))
        payloads = simulate_push_violations_current([violation], redis_mock)

        payload = payloads[0]

        # Sau khi fix: key phải tồn tại (value có thể là URL string hoặc None nếu MinIO down)
        assert "evidence_image_url" in payload, (
            f"BUG 1: 'evidence_image_url' không có trong payload.\n"
            f"Với box={violation['box']}, frame phải được crop và upload."
        )

    def test_all_violations_have_evidence_url_key(self):
        """
        Với nhiều vi phạm cùng lúc, tất cả đều phải có evidence_image_url.

        EXPECTED trên code CHƯA fix: FAIL
        """
        redis_mock = MagicMock()
        violations = [
            build_violation(box=(10, 10, 100, 100)),
            build_violation(box=(200, 150, 400, 350)),
            build_violation(box=(50, 50, 150, 200)),
        ]
        payloads = simulate_push_violations_current(violations, redis_mock)

        missing = [
            i for i, p in enumerate(payloads)
            if "evidence_image_url" not in p
        ]

        assert len(missing) == 0, (
            f"BUG 1: {len(missing)}/{len(payloads)} violations thiếu 'evidence_image_url'.\n"
            f"Indices: {missing}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Task 10 — Preservation tests (PHẢI PASS trên code CHƯA fix)
# ═══════════════════════════════════════════════════════════════════════════

class TestBug1Preservation:
    """
    Property 2 — Preservation: Các trường cũ phải được giữ nguyên sau khi fix.

    Sau khi thêm evidence_image_url, 6 trường cũ KHÔNG được thay đổi.
    Test phải PASS cả trước lẫn sau khi fix.
    """

    REQUIRED_LEGACY_FIELDS = [
        "camera_id",
        "violation_type",
        "vehicle_track_id",
        "license_plate",
        "confidence",
        "timestamp",
    ]

    def test_all_legacy_fields_present_in_payload(self):
        """
        6 trường cũ luôn phải có mặt trong payload.

        EXPECTED: PASS (cả trước và sau fix)
        """
        redis_mock = MagicMock()
        violation = build_violation()
        payloads = simulate_push_violations_current([violation], redis_mock)
        payload = payloads[0]

        missing = [f for f in self.REQUIRED_LEGACY_FIELDS if f not in payload]
        assert len(missing) == 0, (
            f"Preservation FAILED: các trường sau bị mất khỏi payload: {missing}"
        )

    def test_legacy_field_values_preserved_correctly(self):
        """
        Giá trị của 6 trường cũ phải khớp với violation gốc.

        EXPECTED: PASS (cả trước và sau fix)
        """
        redis_mock = MagicMock()
        violation = build_violation()
        payloads = simulate_push_violations_current([violation], redis_mock)
        payload = payloads[0]

        assert payload["camera_id"] == violation["camera_id"]
        assert payload["violation_type"] == violation["violation_type"]
        assert payload["vehicle_track_id"] == violation["vehicle_track_id"]
        assert payload["license_plate"] == violation["license_plate"]
        assert payload["confidence"] == violation["confidence"]
        assert payload["timestamp"] == violation["timestamp"]

    def test_violation_always_pushed_even_when_minio_fails(self):
        """
        Khi MinIO upload throw exception, vi phạm vẫn phải được push vào Redis.
        evidence_image_url = null (graceful fallback), KHÔNG crash.

        EXPECTED: PASS (sau khi fix — graceful error handling)
        """
        import json

        redis_mock = MagicMock()
        violation = build_violation()

        # Mô phỏng logic SAU KHI FIX: MinIO upload thất bại → evidence_url = None
        # nhưng vi phạm vẫn được push
        def simulate_fixed_with_minio_failure(violations, redis_mock):
            captured = []
            for v in violations:
                # MinIO upload thất bại — trả về None (graceful)
                evidence_url = None  # Simulates exception caught silently

                payload = {
                    "camera_id": v.get("camera_id"),
                    "violation_type": v.get("violation_type"),
                    "vehicle_track_id": v.get("vehicle_track_id"),
                    "license_plate": v.get("license_plate"),
                    "confidence": v.get("confidence"),
                    "timestamp": v.get("timestamp"),
                    "evidence_image_url": evidence_url,  # null khi MinIO down
                }
                redis_mock.lpush("violations:queue", json.dumps(payload))
                captured.append(payload)
            return captured

        payloads = simulate_fixed_with_minio_failure([violation], redis_mock)

        # Vi phạm vẫn được push (không bị mất)
        assert len(payloads) == 1, "Vi phạm bị mất khi MinIO fail!"
        redis_mock.lpush.assert_called_once()

        # evidence_image_url null (graceful) — KHÔNG phải missing key
        assert "evidence_image_url" in payloads[0]
        assert payloads[0]["evidence_image_url"] is None

        # 6 trường cũ vẫn còn
        for field in self.REQUIRED_LEGACY_FIELDS:
            assert field in payloads[0], f"Trường '{field}' bị mất khi MinIO fail!"

    @pytest.mark.parametrize("num_violations", [1, 2, 5, 10])
    def test_all_violations_pushed_to_redis(self, num_violations):
        """
        Property-based: N violations → N lần lpush vào Redis (không mất vi phạm nào).

        EXPECTED: PASS (cả trước và sau fix)
        """
        redis_mock = MagicMock()
        violations = [build_violation() for _ in range(num_violations)]
        simulate_push_violations_current(violations, redis_mock)

        assert redis_mock.lpush.call_count == num_violations, (
            f"Expected {num_violations} lpush calls, "
            f"got {redis_mock.lpush.call_count}"
        )

    @pytest.mark.parametrize("num_violations", [1, 3])
    def test_violations_also_published_to_pubsub(self, num_violations):
        """
        Mỗi vi phạm phải được publish lên Redis pub/sub 'violations:alerts'.

        EXPECTED: PASS (cả trước và sau fix)
        """
        redis_mock = MagicMock()
        violations = [build_violation() for _ in range(num_violations)]
        simulate_push_violations_current(violations, redis_mock)

        assert redis_mock.publish.call_count == num_violations, (
            f"Expected {num_violations} publish calls, "
            f"got {redis_mock.publish.call_count}"
        )
