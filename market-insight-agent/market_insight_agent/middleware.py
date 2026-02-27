"""
FastAPI 中间件集合。

- RequestIDMiddleware:   生成 X-Request-ID 并注入 structlog 上下文
- APIKeyAuthMiddleware:  X-API-Key 认证（空 secret 时跳过）
- RequestBodyLimitMiddleware: Content-Length 上限
"""

from __future__ import annotations

import uuid
from typing import Callable, Sequence

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from .config import settings
from .errors import ErrorCode
from .logging_config import bind_request_id, get_logger

logger = get_logger(__name__)

# 不需要认证的路径前缀
_PUBLIC_PATHS: Sequence[str] = (
    "/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/health",
    "/api/llm/status",
)


# ---------------------------------------------------------------------------
# Request ID
# ---------------------------------------------------------------------------

class RequestIDMiddleware(BaseHTTPMiddleware):
    """为每个请求生成唯一 ID，注入 structlog 上下文并写入响应头。"""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        bind_request_id(request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# ---------------------------------------------------------------------------
# API Key 认证
# ---------------------------------------------------------------------------

class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """校验 X-API-Key 请求头。

    - ``API_SECRET_KEY`` 配置为空时，认证被禁用（开发模式）。
    - 匹配 ``_PUBLIC_PATHS`` 的请求免认证。
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        secret = settings.api_secret_key
        if not secret:
            return await call_next(request)

        path = request.url.path.rstrip("/") or "/"
        if self._is_public(path):
            return await call_next(request)

        api_key = request.headers.get("X-API-Key", "")
        if not api_key:
            return self._deny(ErrorCode.AUTH_MISSING_KEY, "缺少 X-API-Key 请求头")
        if api_key != secret:
            logger.warning("auth_rejected", path=path)
            return self._deny(ErrorCode.AUTH_INVALID_KEY, "API Key 无效")

        return await call_next(request)

    @staticmethod
    def _is_public(path: str) -> bool:
        for prefix in _PUBLIC_PATHS:
            if path == prefix or path.startswith(prefix + "/"):
                return True
        return False

    @staticmethod
    def _deny(code: ErrorCode, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "code": code.value,
                    "message": message,
                    "retriable": False,
                },
                "detail": message,
            },
        )


# ---------------------------------------------------------------------------
# 请求体大小限制
# ---------------------------------------------------------------------------

class RequestBodyLimitMiddleware(BaseHTTPMiddleware):
    """限制请求体大小，默认 2 MB。"""

    MAX_BYTES = 2 * 1024 * 1024  # 2 MB

    def __init__(self, app, max_content_length: int = MAX_BYTES):
        super().__init__(app)
        self._max_bytes = max_content_length

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self._max_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": ErrorCode.VALIDATION_BODY_TOO_LARGE.value,
                        "message": f"请求体超过 {self._max_bytes // (1024*1024)} MB 上限",
                        "retriable": False,
                    },
                    "detail": f"请求体超过 {self._max_bytes // (1024*1024)} MB 上限",
                },
            )
        return await call_next(request)
