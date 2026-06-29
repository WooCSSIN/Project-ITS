"""Middleware gắn request_id vào mỗi request để trace logs.

Request ID có thể được:
    - Lấy từ header `X-Request-ID` (nếu upstream proxy/service đã set)
    - Auto-generate UUID nếu không có

Request ID sẽ được:
    - Set vào contextvar để mọi log trong request đều có
    - Trả về trong response header `X-Request-ID`
"""
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from core.logging_config import (
    clear_request_id,
    get_logger,
    set_request_id,
)

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware thêm X-Request-ID cho mỗi request.

    Workflow:
        1. Lấy/generate request_id
        2. Set vào contextvar
        3. Log request start
        4. Process request
        5. Log request end (với status code + duration)
        6. Clear contextvar
        7. Trả response với X-Request-ID header
    """

    async def dispatch(self, request: Request, call_next):
        # Lấy request_id từ header hoặc generate mới
        incoming_id = request.headers.get(REQUEST_ID_HEADER)
        request_id = set_request_id(incoming_id if incoming_id else uuid.uuid4().hex[:16])

        start_time = time.perf_counter()
        client_ip = request.client.host if request.client else "unknown"
        method = request.method
        path = request.url.path

        logger.info("→ %s %s from=%s", method, path, client_ip)

        try:
            response = await call_next(request)
            duration_ms = (time.perf_counter() - start_time) * 1000

            # Log kết thúc request
            logger.info(
                "← %s %s status=%d duration=%.2fms",
                method, path, response.status_code, duration_ms,
            )

            # Gắn request_id vào response header để client có thể debug
            response.headers[REQUEST_ID_HEADER] = request_id
            response.headers["X-Response-Time-MS"] = f"{duration_ms:.2f}"
            return response

        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.exception(
                "✗ %s %s failed duration=%.2fms error=%s",
                method, path, duration_ms, exc,
            )
            raise
        finally:
            # Cleanup contextvar
            clear_request_id()