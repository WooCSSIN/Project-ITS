from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update
from typing import List, Optional
from datetime import datetime
import json

from db.base import get_db
from models.violation import Violation as ViolationModel
from schemas.violation import Violation, ViolationCreate, ViolationUpdate
from core.report_generator import generate_fine_pdf

router = APIRouter()


@router.post("/", response_model=Violation, status_code=status.HTTP_201_CREATED)
async def create_violation(
    violation_in: ViolationCreate,
    db: AsyncSession = Depends(get_db)
):
    """Tạo vi phạm mới (được gọi bởi AI engine hoặc thủ công)."""
    db_violation = ViolationModel(**violation_in.model_dump())
    db.add(db_violation)
    await db.commit()
    await db.refresh(db_violation)
    return db_violation


@router.get("/", response_model=List[Violation])
async def get_violations(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    violation_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Lấy danh sách vi phạm, có lọc theo trạng thái và loại."""
    query = select(ViolationModel).order_by(ViolationModel.timestamp.desc())
    if status:
        query = query.where(ViolationModel.status == status)
    if violation_type:
        query = query.where(ViolationModel.violation_type == violation_type)
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{violation_id}", response_model=Violation)
async def get_violation(violation_id: int, db: AsyncSession = Depends(get_db)):
    """Lấy chi tiết 1 vi phạm."""
    result = await db.execute(select(ViolationModel).where(ViolationModel.id == violation_id))
    violation = result.scalar_one_or_none()
    if not violation:
        raise HTTPException(status_code=404, detail="Violation not found")
    return violation


@router.put("/{violation_id}", response_model=Violation)
async def update_violation(
    violation_id: int,
    violation_update: ViolationUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Cập nhật trạng thái vi phạm (xác nhận / từ chối / lập biên bản)."""
    result = await db.execute(select(ViolationModel).where(ViolationModel.id == violation_id))
    db_violation = result.scalar_one_or_none()

    if not db_violation:
        raise HTTPException(status_code=404, detail="Violation not found")

    update_data = violation_update.model_dump(exclude_unset=True)
    if "status" in update_data and update_data["status"] in ("confirmed", "rejected"):
        update_data["confirmed_at"] = datetime.utcnow()

    for field, value in update_data.items():
        setattr(db_violation, field, value)

    db.add(db_violation)
    await db.commit()
    await db.refresh(db_violation)
    return db_violation


@router.get("/{violation_id}/export-pdf")
async def export_violation_pdf(
    violation_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Xuất biên bản xử phạt dưới dạng file PDF."""
    result = await db.execute(select(ViolationModel).where(ViolationModel.id == violation_id))
    db_violation = result.scalar_one_or_none()
    if not db_violation:
        raise HTTPException(status_code=404, detail="Violation not found")
    if db_violation.status != "confirmed":
        raise HTTPException(status_code=400, detail="Chỉ có thể xuất PDF cho vi phạm đã được xác nhận.")

    # Chuyển ORM object thành dict để truyền vào generator
    violation_dict = {
        "id": db_violation.id,
        "camera_id": db_violation.camera_id,
        "timestamp": db_violation.timestamp,
        "violation_type": db_violation.violation_type,
        "vehicle_track_id": db_violation.vehicle_track_id,
        "license_plate": db_violation.license_plate,
        "confidence": db_violation.confidence,
        "fine_number": db_violation.fine_number,
        "confirmed_at": db_violation.confirmed_at,
    }

    pdf_bytes = generate_fine_pdf(violation_dict)
    if not pdf_bytes:
        raise HTTPException(status_code=500, detail="Không thể tạo file PDF. Kiểm tra lại thư viện reportlab.")

    filename = f"bien-ban-{db_violation.fine_number or violation_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
