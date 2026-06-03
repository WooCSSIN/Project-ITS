from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class ViolationBase(BaseModel):
    camera_id: int
    violation_type: str
    vehicle_track_id: Optional[int] = None
    license_plate: Optional[str] = None
    confidence: Optional[float] = None
    evidence_image_url: Optional[str] = None
    evidence_video_url: Optional[str] = None
    status: Optional[str] = 'pending'

class ViolationCreate(ViolationBase):
    pass

class ViolationUpdate(BaseModel):
    status: Optional[str] = None
    confirmed_by: Optional[int] = None
    fine_number: Optional[str] = None

class ViolationInDBBase(ViolationBase):
    id: int
    timestamp: datetime
    confirmed_by: Optional[int] = None
    confirmed_at: Optional[datetime] = None
    fine_number: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class Violation(ViolationInDBBase):
    pass
