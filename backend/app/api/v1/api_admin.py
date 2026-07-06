import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocketDisconnect, status, WebSocket
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from api import v1
from db.base import get_db
from models.violation import Violation
from utils.jwt_handler import get_current_user, get_current_user_ws
from models.user import User
from utils.system_metrics import get_system_metrics
from core.logging_config import get_logger


router = APIRouter(prefix="/admin")
logger = get_logger(__name__)


def _require_admin(user: User):
    if user.role_id != 0:
        logger.warning("Access denied for non-admin user_id=%s role_id=%s", user.id, user.role_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ admin mới được phép truy cập tài nguyên hệ thống.",
        )


@router.get(
    path= "/resources",
    summary="Lấy thông tin tài nguyên hệ thống",
    description="API trả về metrics hệ thống (CPU, RAM, Disk, Network). Chỉ admin (role_id = 0) mới có quyền truy cập."
)
async def get_resources(current_user: User = Depends(get_current_user)):
    """Return basic system metrics. Admin only (role_id = 0)."""
    _require_admin(current_user)
    logger.info("Admin user_id=%s requested system resources", current_user.id)
    return get_system_metrics()


@router.get(
    path="/traffic/status",
    summary="Lấy trạng thái process traffic theo tuyến",
    description="Admin xem trạng thái subprocess traffic (đang chạy/dừng) của từng tuyến đường.",
)
async def get_traffic_process_status(current_user: User = Depends(get_current_user)):
    _require_admin(current_user)

    analyzer = v1.state.analyzer
    if analyzer is None:
        logger.error("Traffic status requested but analyzer is unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Traffic service is unavailable.",
        )

    statuses = await run_in_threadpool(analyzer.get_roads_runtime_status)
    logger.info("Admin user_id=%s fetched traffic process status", current_user.id)
    return {"roads": statuses}


@router.post(
    path="/traffic/roads/{road_name}/stop",
    summary="Dừng subprocess theo tuyến",
    description="Admin dừng hoàn toàn subprocess xử lý của một tuyến đường.",
)
async def stop_traffic_road_process(road_name: str, current_user: User = Depends(get_current_user)):
    _require_admin(current_user)

    analyzer = v1.state.analyzer
    if analyzer is None:
        logger.error("Stop road request for %s failed: analyzer unavailable", road_name)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Traffic service is unavailable.",
        )

    result = await run_in_threadpool(analyzer.stop_road, road_name)
    if not result.get("ok"):
        logger.warning("Stop road request failed for %s: %s", road_name, result.get("detail"))
        error_status = status.HTTP_404_NOT_FOUND if result.get("detail") == "Road not found." else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=error_status, detail=result.get("detail", "Unable to stop road process."))
    logger.info("Admin user_id=%s stopped road process %s", current_user.id, road_name)
    return result


@router.post(
    path="/traffic/roads/{road_name}/start",
    summary="Khởi động subprocess theo tuyến",
    description="Admin khởi động lại subprocess xử lý của một tuyến đường đã dừng.",
)
async def start_traffic_road_process(road_name: str, current_user: User = Depends(get_current_user)):
    _require_admin(current_user)

    analyzer = v1.state.analyzer
    if analyzer is None:
        logger.error("Start road request for %s failed: analyzer unavailable", road_name)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Traffic service is unavailable.",
        )

    result = await run_in_threadpool(analyzer.start_road, road_name)
    if not result.get("ok"):
        logger.warning("Start road request failed for %s: %s", road_name, result.get("detail"))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result.get("detail", "Road not found."))
    logger.info("Admin user_id=%s started road process %s", current_user.id, road_name)
    return result

@router.websocket(
    path= "/ws/resources",
    name="WebSocket thông báo hệ thống cho admin"
)
async def websocket_resources(websocket: WebSocket, current_user: User = Depends(get_current_user_ws)):
    """
    WebSocket endpoint để gửi thông tin tài nguyên hệ thống theo thời gian thực cho admin.
    """
    _require_admin(current_user)
    logger.info("Admin user_id=%s opened system metrics websocket", current_user.id)
        
    await websocket.accept()
    
    try:
        while True:
            metrics = get_system_metrics()
            await websocket.send_json(metrics)
            await asyncio.sleep(2) 
    except WebSocketDisconnect:
        logger.info("Admin user_id=%s closed system metrics websocket", current_user.id)


@router.get(
    path="/violations",
    summary="Lấy danh sách vi phạm giao thông",
    description="Admin xem danh sách vi phạm có phân trang, lọc theo loại, trạng thái, camera.",
)
async def get_violations(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    violation_type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    camera_id: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(current_user)

    stmt = select(Violation).order_by(desc(Violation.timestamp))

    if violation_type:
        stmt = stmt.where(Violation.violation_type == violation_type)
    if status_filter:
        stmt = stmt.where(Violation.status == status_filter)
    if camera_id is not None:
        stmt = stmt.where(Violation.camera_id == camera_id)

    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)

    result = await db.execute(stmt)
    rows = result.scalars().all()

    logger.info(
        "Admin user_id=%s fetched violations page=%s size=%s",
        current_user.id, page, page_size,
    )
    return {
        "page": page,
        "page_size": page_size,
        "data": [v.to_dict() for v in rows],
    }


@router.patch(
    path="/violations/{violation_id}/status",
    summary="Cập nhật trạng thái vi phạm",
    description="Admin xác nhận (confirmed), từ chối (rejected) hoặc phạt (fined) một vi phạm.",
)
async def update_violation_status(
    violation_id: int,
    new_status: str = Query(..., pattern="^(confirmed|rejected|fined|pending)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(current_user)

    result = await db.execute(select(Violation).where(Violation.id == violation_id))
    violation = result.scalar_one_or_none()

    if violation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Violation not found.")

    from datetime import datetime, timezone
    violation.status = new_status
    violation.confirmed_by = current_user.id
    violation.confirmed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(violation)

    logger.info(
        "Admin user_id=%s updated violation_id=%s to status=%s",
        current_user.id, violation_id, new_status,
    )
    return violation.to_dict()


@router.post(
    path="/traffic/roads/{road_name}/red-light",
    summary="Set trạng thái đèn đỏ cho camera",
    description="Admin bật/tắt đèn đỏ thủ công hoặc theo lịch để ViolationEngine phát hiện vi phạm.",
)
async def set_red_light(
    road_name: str,
    is_red: bool = Query(..., description="True = đèn đỏ, False = đèn xanh"),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)

    analyzer = v1.state.analyzer
    if analyzer is None:
        raise HTTPException(status_code=503, detail="Traffic service unavailable.")

    # Tìm violation engine của road này qua subprocess không trực tiếp được
    # → lưu trạng thái vào Redis để subprocess đọc
    try:
        import redis as redis_lib
        from core.config import settings_server
        r = redis_lib.Redis.from_url(settings_server.REDIS_URL, decode_responses=True)
        r.set(f"traffic:road:{road_name}:red_light", "1" if is_red else "0", ex=300)
        logger.info("Admin user_id=%s set red_light=%s for road=%s", current_user.id, is_red, road_name)
        return {"ok": True, "road_name": road_name, "is_red": is_red}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    path="/violations/stats",
    summary="Thống kê vi phạm",
    description="Tổng hợp số lượng vi phạm theo loại và trạng thái.",
)
async def get_violation_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(current_user)

    from sqlalchemy import func
    # Đếm theo violation_type
    by_type_result = await db.execute(
        select(Violation.violation_type, func.count(Violation.id))
        .group_by(Violation.violation_type)
    )
    by_type = {row[0]: row[1] for row in by_type_result.all()}

    # Đếm theo status
    by_status_result = await db.execute(
        select(Violation.status, func.count(Violation.id))
        .group_by(Violation.status)
    )
    by_status = {row[0]: row[1] for row in by_status_result.all()}

    return {
        "by_type": by_type,
        "by_status": by_status,
        "total": sum(by_status.values()),
    }