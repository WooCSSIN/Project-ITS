"""Rate limiting middleware sử dụng in-memory sliding window.

Đơn giản, không cần Redis (vì Redis đã có nhiều việc phải làm).
Phù hợp cho single-instance deployment. Với multi-instance, có thể
chuyển sang Redis-based rate limiter.

Cấu hình qua env:
    RATE_LIMIT_PER_MINUTE: số requests tối đa / phút / IP (default 60)
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from core.config import settings_security
from core.logging_config import get_logger

logger = get_logger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware giới hạn số request / phút cho mỗi IP.

    Strategy: Sliding window với deque.
    Mỗi IP có một deque chứa timestamps của các request gần đây.
    Khi có request mới, ta loại bỏ các timestamp cũ hơn 60 giây và
    đếm số còn lại. Nếu vượt quá limit → trả về 429.
    """

    # Paths không áp dụng rate limit (health checks, static files, websocket)
    EXCLUDED_PATHS = {
        "/api/v1/health",
        "/api/v1/ready",
        "/api/v1/health/detailed",
        "/api/v1/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/",
    }

    def __init__(self, app, requests_per_minute: int = None):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute or settings_security.RATE_LIMIT_PER_MINUTE
        self.window_seconds = 60

        # IP -> deque of timestamps
        self._request_log: Dict[str, Deque[float]] = defaultdict(deque)

        # Lock để thread-safe (multi-thread event loop)
        self._lock = asyncio.Lock()

        # Cleanup task sẽ chạy mỗi 5 phút
        self._last_cleanup = time.time()
        self._cleanup_interval = 300  # 5 phút

    def _get_client_ip(self, request: Request) -> str:
        """Lấy IP của client, ưu tiên X-Forwarded-For nếu có proxy."""
        # Check X-Forwarded-For header (từ proxy/load balancer)
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Lấy IP đầu tiên (original client)
            return forwarded.split(",")[0].strip()

        # Check X-Real-IP
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

        # Fallback về client.host
        if request.client:
            return request.client.host

        return "unknown"

    def _is_excluded(self, path: str) -> bool:
        """Check path có được exempt khỏi rate limit không."""
        if path in self.EXCLUDED_PATHS:
            return True
        # Exempt static files & websocket
        if path.startswith(("/static/", "/ws/", "/_next/")):
            return True
        return False

    async def _cleanup_old_entries(self) -> None:
        """Dọn các IP không hoạt động để giải phóng memory."""
        now = time.time()
        cutoff = now - self.window_seconds

        async with self._lock:
            stale_ips = []
            for ip, timestamps in self._request_log.items():
                # Loại bỏ timestamps cũ
                while timestamps and timestamps[0] < cutoff:
                    timestamps.popleft()
                # Nếu deque rỗng → có thể xóa IP
                if not timestamps:
                    stale_ips.append(ip)

            for ip in stale_ips:
                del self._request_log[ip]

            if stale_ips:
                logger.debug("RateLimit cleanup: removed %d stale IPs", len(stale_ips))

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method

        # Skip rate limit cho:
        # - Excluded paths
        # - WebSocket upgrade requests
        if self._is_excluded(path) or method == "OPTIONS":
            return await call_next(request)

        # Periodic cleanup (chạy async, không block request)
        now = time.time()
        if now - self._last_cleanup > self._cleanup_interval:
            self._last_cleanup = now
            asyncio.create_task(self._cleanup_old_entries())

        client_ip = self._get_client_ip(request)
        cutoff = now - self.window_seconds

        async with self._lock:
            timestamps = self._request_log[client_ip]

            # Loại bỏ timestamps cũ
            while timestamps and timestamps[0] < cutoff:
                timestamps.popleft()

            # Check limit
            if len(timestamps) >= self.requests_per_minute:
                # Tính Retry-After: thời gian cần đợi cho timestamp cũ nhất ra khỏi window
                retry_after = int(timestamps[0] + self.window_seconds - now) + 1

                logger.warning(
                    "Rate limit exceeded for IP=%s path=%s (count=%d)",
                    client_ip, path, len(timestamps),
                )

                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "detail": f"Rate limit exceeded: {self.requests_per_minute} requests per minute",
                        "retry_after_seconds": retry_after,
                    },
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(self.requests_per_minute),
                        "X-RateLimit-Remaining": "0",
                    },
                )

            # Thêm timestamp hiện tại
            timestamps.append(now)
            remaining = self.requests_per_minute - len(timestamps)

        # Gọi handler tiếp theo
        response = await call_next(request)

        # Thêm rate limit headers
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(remaining)

        return response