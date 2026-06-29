"""Model cho Violation - lưu các vi phạm giao thông được phát hiện."""
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Text

from db.base import Base


class Violation(Base):
    """Bảng lưu trữ các vi phạm giao thông.

    Schema được khởi tạo bởi alembic migration `violations_004_create_table.py`.
    """

    __tablename__ = "violations"

    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(Integer, nullable=False, index=True)

    # Thời gian vi phạm xảy ra (UTC)
    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    # Loại vi phạm: speeding, red_light, wrong_lane, no_helmet, illegal_parking
    violation_type = Column(String(50), nullable=False, index=True)

    # Track ID trong YOLO tracker
    vehicle_track_id = Column(Integer, nullable=True)

    # Biển số xe (nếu ANPR được bật)
    license_plate = Column(String(20), nullable=True, index=True)

    # Độ tin cậy của detection (0-1)
    confidence = Column(Float, nullable=True)

    # URL ảnh bằng chứng (lưu trên MinIO)
    evidence_image_url = Column(Text, nullable=True)
    # URL video bằng chứng (optional)
    evidence_video_url = Column(Text, nullable=True)

    # Trạng thái xử lý: pending | confirmed | rejected | fined
    status = Column(String(20), nullable=False, default="pending", index=True)

    # User confirm/reject (admin)
    confirmed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)

    # Số biên bản phạt
    fine_number = Column(String(50), nullable=True, index=True)

    # Metadata bổ sung (JSON string)
    extra_metadata = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    __table_args__ = (
        Index("ix_violations_camera_timestamp", "camera_id", "timestamp"),
        Index("ix_violations_status_timestamp", "status", "timestamp"),
    )

    def to_dict(self) -> dict:
        """Chuyển sang dict để trả về API."""
        return {
            "id": self.id,
            "camera_id": self.camera_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "violation_type": self.violation_type,
            "vehicle_track_id": self.vehicle_track_id,
            "license_plate": self.license_plate,
            "confidence": self.confidence,
            "evidence_image_url": self.evidence_image_url,
            "evidence_video_url": self.evidence_video_url,
            "status": self.status,
            "confirmed_by": self.confirmed_by,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "fine_number": self.fine_number,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }