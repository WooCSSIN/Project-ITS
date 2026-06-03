from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete
from typing import List, Optional
from pydantic import BaseModel

from db.base import get_db
from models.zone_config import ZoneConfig as ZoneConfigModel

router = APIRouter()


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class ZoneConfigCreate(BaseModel):
    camera_id: int
    zone_type: str
    points: List[List[float]]           # [[x1,y1],[x2,y2],...]
    zone_name: Optional[str] = None
    is_active: bool = True


class ZoneConfigResponse(BaseModel):
    id: int
    camera_id: int
    zone_type: str
    points: List[List[float]]
    zone_name: Optional[str]
    is_active: bool

    class Config:
        from_attributes = True


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[ZoneConfigResponse])
async def list_zones(
    camera_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db)
):
    """Lấy danh sách tất cả zone configs, có thể lọc theo camera_id."""
    query = select(ZoneConfigModel).where(ZoneConfigModel.is_active == True)
    if camera_id is not None:
        query = query.where(ZoneConfigModel.camera_id == camera_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/", response_model=ZoneConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_zone(
    zone_in: ZoneConfigCreate,
    db: AsyncSession = Depends(get_db)
):
    """Tạo mới hoặc cập nhật zone cho camera (upsert: xoá zone cũ cùng loại trước)."""
    # Xoá zone cũ cùng loại của cùng camera trước khi tạo mới
    await db.execute(
        delete(ZoneConfigModel).where(
            ZoneConfigModel.camera_id == zone_in.camera_id,
            ZoneConfigModel.zone_type == zone_in.zone_type,
        )
    )
    db_zone = ZoneConfigModel(**zone_in.model_dump())
    db.add(db_zone)
    await db.commit()
    await db.refresh(db_zone)
    return db_zone


@router.delete("/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_zone(zone_id: int, db: AsyncSession = Depends(get_db)):
    """Xoá một zone config theo ID."""
    result = await db.execute(select(ZoneConfigModel).where(ZoneConfigModel.id == zone_id))
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    await db.delete(zone)
    await db.commit()
