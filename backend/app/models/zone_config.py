"""
Bảng lưu cấu hình vùng cảnh báo (polygon zones) cho từng camera.
Mỗi row = một zone (có thể có nhiều zone cho một camera).
"""
from sqlalchemy import Column, Integer, String, JSON, DateTime, Boolean
from sqlalchemy.sql import func
from db.base import Base


class ZoneConfig(Base):
    __tablename__ = "zone_configs"

    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(Integer, nullable=False, index=True)
    zone_name = Column(String(100), nullable=True)                # Tên gợi nhớ
    zone_type = Column(String(50), nullable=False)                # red_light, wrong_lane, no_parking
    points = Column(JSON, nullable=False)                         # [[x1,y1],[x2,y2],...]
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
