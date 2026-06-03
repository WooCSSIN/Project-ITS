from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from sqlalchemy.sql import func
from db.base import Base

class Violation(Base):
    __tablename__ = "violations"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    camera_id = Column(Integer, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    violation_type = Column(String(50), nullable=False)  # 'red_light', 'wrong_lane', 'no_parking'
    vehicle_track_id = Column(Integer)
    license_plate = Column(String(20))
    confidence = Column(Float)
    evidence_image_url = Column(Text)      # đường dẫn MinIO
    evidence_video_url = Column(Text)
    status = Column(String(20), server_default='pending')  # pending, confirmed, rejected, fined
    confirmed_by = Column(Integer, nullable=True)     # user_id của cán bộ
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    fine_number = Column(String(50), nullable=True)  # số biên bản
    created_at = Column(DateTime(timezone=True), server_default=func.now())
