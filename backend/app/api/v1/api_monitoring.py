"""Health check endpoints cho monitoring.

Cung cấp:
    - /health: simple health check (alive/dead)
    - /health/detailed: chi tiết trạng thái các component
    - /metrics: Prometheus-compatible metrics
    - /ready: readiness check (sẵn sàng nhận traffic)
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict

from fastapi import APIRouter, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy import text

from api import v1
from core.config import settings_metrics, settings_server
from core.logging_config import get_logger
from db.base import AsyncSessionLocal

logger = get_logger(__name__)
router = APIRouter(tags=["Monitoring"])


# Track server start time để tính uptime
_SERVER_START_TIME = time.time()


async def _check_database() -> Dict[str, Any]:
    """Check database connection."""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT 1"))
            result.scalar()
        return {"status": "healthy", "latency_ms": 0}
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc)[:200]}


async def _check_redis() -> Dict[str, Any]:
    """Check Redis connection."""
    try:
        import redis.asyncio as redis_async

        client = redis_async.from_url(settings_server.REDIS_URL, decode_responses=True)
        try:
            pong = await client.ping()
            return {"status": "healthy" if pong else "unhealthy", "latency_ms": 0}
        finally:
            await client.aclose()
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc)[:200]}


async def _check_traffic_analyzer() -> Dict[str, Any]:
    """Check traffic analyzer state."""
    analyzer = v1.state.analyzer
    if analyzer is None:
        return {"status": "unhealthy", "error": "Analyzer not initialized"}

    return {
        "status": "healthy",
        "active_roads": len(analyzer.names) if hasattr(analyzer, "names") else 0,
        "processes_alive": sum(
            1 for p in analyzer.processes.values()
            if p is not None and p.is_alive()
        ) if hasattr(analyzer, "processes") else 0,
    }


async def _check_workers() -> Dict[str, Any]:
    """Check background workers state."""
    def _is_alive(obj) -> bool:
        return obj is not None and callable(getattr(obj, "is_alive", None)) and obj.is_alive()

    traffic_alive = _is_alive(getattr(v1.state, "traffic_history_worker", None))
    violation_alive = _is_alive(getattr(v1.state, "violation_worker", None))

    return {
        "status": "healthy" if (traffic_alive and violation_alive) else "degraded",
        "traffic_history_worker": {"alive": traffic_alive},
        "violation_worker": {"alive": violation_alive},
    }


@router.get("/health", summary="Simple health check")
async def health_check():
    """Endpoint đơn giản để check server còn sống không. Dùng cho load balancer."""
    return {"status": "alive", "uptime_seconds": round(time.time() - _SERVER_START_TIME, 2)}


@router.get("/ready", summary="Readiness check")
async def readiness_check():
    """Check server đã sẵn sàng nhận traffic chưa."""
    analyzer_ready = v1.state.analyzer is not None

    if analyzer_ready:
        return {"status": "ready"}
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "not_ready", "reason": "Analyzer not initialized"},
    )


@router.get("/health/detailed", summary="Detailed health check")
async def health_detailed():
    """Chi tiết trạng thái các component. Dùng cho monitoring dashboard."""
    if not settings_metrics.HEALTH_DETAILED_ENABLED:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": "Detailed health check disabled"},
        )

    # Chạy tất cả checks song song
    db_check, redis_check, analyzer_check, workers_check = await asyncio.gather(
        _check_database(),
        _check_redis(),
        _check_traffic_analyzer(),
        _check_workers(),
        return_exceptions=True,
    )

    # Convert exceptions to error dicts
    def safe(check):
        if isinstance(check, Exception):
            return {"status": "error", "error": str(check)[:200]}
        return check

    components = {
        "database": safe(db_check),
        "redis": safe(redis_check),
        "analyzer": safe(analyzer_check),
        "workers": safe(workers_check),
    }

    # Overall status: healthy nếu tất cả components healthy
    all_healthy = all(
        c.get("status") == "healthy" if isinstance(c, dict) else False
        for c in components.values()
    )

    overall_status = "healthy" if all_healthy else "degraded"
    http_code = status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(
        status_code=http_code,
        content={
            "status": overall_status,
            "uptime_seconds": round(time.time() - _SERVER_START_TIME, 2),
            "components": components,
            "version": "1.0.0",
        },
    )


@router.get("/metrics", summary="Prometheus-compatible metrics")
async def prometheus_metrics():
    """Metrics theo format Prometheus (text/plain)."""
    if not settings_metrics.METRICS_ENABLED:
        return Response(status_code=404)

    lines = []

    # Server uptime
    uptime = time.time() - _SERVER_START_TIME
    lines.append(f"# HELP its_server_uptime_seconds Server uptime in seconds")
    lines.append(f"# TYPE its_server_uptime_seconds gauge")
    lines.append(f"its_server_uptime_seconds {uptime:.2f}")

    # Analyzer metrics
    analyzer = v1.state.analyzer
    if analyzer and hasattr(analyzer, "names"):
        active_roads = len(analyzer.names)
        alive_procs = sum(
            1 for p in analyzer.processes.values()
            if p is not None and p.is_alive()
        ) if hasattr(analyzer, "processes") else 0

        lines.append(f"# HELP its_active_roads Number of active roads being monitored")
        lines.append(f"# TYPE its_active_roads gauge")
        lines.append(f"its_active_roads {active_roads}")

        lines.append(f"# HELP its_analyzer_processes_alive Number of alive analyzer processes")
        lines.append(f"# TYPE its_analyzer_processes_alive gauge")
        lines.append(f"its_analyzer_processes_alive {alive_procs}")

    # System metrics (CPU, memory) - chạy sync trong threadpool
    try:
        from utils.system_metrics import get_system_metrics
        sys_metrics = await run_in_threadpool(get_system_metrics)

        if sys_metrics.get("cpu_percent") is not None:
            lines.append(f"# HELP its_cpu_percent CPU usage percent")
            lines.append(f"# TYPE its_cpu_percent gauge")
            lines.append(f"its_cpu_percent {sys_metrics['cpu_percent']}")

        if sys_metrics.get("memory") and isinstance(sys_metrics["memory"], dict):
            mem = sys_metrics["memory"]
            lines.append(f"# HELP its_memory_percent Memory usage percent")
            lines.append(f"# TYPE its_memory_percent gauge")
            lines.append(f"its_memory_percent {mem['percent']}")

            lines.append(f"# HELP its_memory_used_bytes Memory used in bytes")
            lines.append(f"# TYPE its_memory_used_bytes gauge")
            lines.append(f"its_memory_used_bytes {mem['used']}")

        if sys_metrics.get("disk") and isinstance(sys_metrics["disk"], dict):
            disk = sys_metrics["disk"]
            lines.append(f"# HELP its_disk_percent Disk usage percent")
            lines.append(f"# TYPE its_disk_percent gauge")
            lines.append(f"its_disk_percent {disk['percent']}")
    except Exception as exc:
        logger.warning("Failed to collect system metrics: %s", exc)

    # Worker status
    def _is_alive(obj) -> bool:
        return obj is not None and callable(getattr(obj, "is_alive", None)) and obj.is_alive()

    traffic_worker_alive = _is_alive(getattr(v1.state, "traffic_history_worker", None))
    violation_worker_alive = _is_alive(getattr(v1.state, "violation_worker", None))

    lines.append(f"# HELP its_traffic_worker_alive Traffic history worker alive (1=yes, 0=no)")
    lines.append(f"# TYPE its_traffic_worker_alive gauge")
    lines.append(f"its_traffic_worker_alive {1 if traffic_worker_alive else 0}")

    lines.append(f"# HELP its_violation_worker_alive Violation worker alive (1=yes, 0=no)")
    lines.append(f"# TYPE its_violation_worker_alive gauge")
    lines.append(f"its_violation_worker_alive {1 if violation_worker_alive else 0}")

    return Response(
        content="\n".join(lines) + "\n",
        media_type="text/plain; version=0.0.4",
    )