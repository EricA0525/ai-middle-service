"""
标准化错误码与统一异常处理。

定义全局错误码枚举、应用异常类、FastAPI 异常处理器注册。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


# ---------------------------------------------------------------------------
# 错误码枚举
# ---------------------------------------------------------------------------

class ErrorCode(str, Enum):
    """应用级标准错误码。

    命名规则: 全大写 + 下划线，前缀表示模块。
    """

    # ── 认证 & 授权 ──
    AUTH_MISSING_KEY = "AUTH_MISSING_KEY"
    AUTH_INVALID_KEY = "AUTH_INVALID_KEY"

    # ── 速率限制 ──
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"

    # ── 任务管理 ──
    JOB_QUEUE_FULL = "JOB_QUEUE_FULL"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    JOB_NOT_COMPLETED = "JOB_NOT_COMPLETED"
    JOB_ALREADY_CANCELLED = "JOB_ALREADY_CANCELLED"
    JOB_TIMEOUT = "JOB_TIMEOUT"
    JOB_IDEMPOTENT_HIT = "JOB_IDEMPOTENT_HIT"
    JOB_IDEMPOTENCY_CONFLICT = "JOB_IDEMPOTENCY_CONFLICT"

    # ── LLM ──
    LLM_CONNECTION_ERROR = "LLM_CONNECTION_ERROR"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_RATE_LIMITED = "LLM_RATE_LIMITED"
    LLM_GENERATION_FAILED = "LLM_GENERATION_FAILED"
    LLM_API_KEY_INVALID = "LLM_API_KEY_INVALID"

    # ── 质量闸门 ──
    QUALITY_GATE_FAILED = "QUALITY_GATE_FAILED"

    # ── 模板 ──
    TEMPLATE_NOT_FOUND = "TEMPLATE_NOT_FOUND"
    TEMPLATE_PARSE_ERROR = "TEMPLATE_PARSE_ERROR"
    TEMPLATE_UPDATE_FAILED = "TEMPLATE_UPDATE_FAILED"

    # ── 输入校验 ──
    VALIDATION_INVALID_TEMPLATE_NAME = "VALIDATION_INVALID_TEMPLATE_NAME"
    VALIDATION_FIELD_TOO_LONG = "VALIDATION_FIELD_TOO_LONG"
    VALIDATION_TOO_MANY_COMPETITORS = "VALIDATION_TOO_MANY_COMPETITORS"
    VALIDATION_BODY_TOO_LARGE = "VALIDATION_BODY_TOO_LARGE"

    # ── 系统 ──
    SYSTEM_INTERNAL_ERROR = "SYSTEM_INTERNAL_ERROR"
    SYSTEM_SHUTTING_DOWN = "SYSTEM_SHUTTING_DOWN"


# ---------------------------------------------------------------------------
# 错误码元信息（默认 HTTP 状态码 & retriable 标记）
# ---------------------------------------------------------------------------

_ERROR_META: dict[ErrorCode, dict[str, Any]] = {
    # 认证
    ErrorCode.AUTH_MISSING_KEY:              {"status": 401, "retriable": False},
    ErrorCode.AUTH_INVALID_KEY:              {"status": 401, "retriable": False},
    # 速率
    ErrorCode.RATE_LIMIT_EXCEEDED:           {"status": 429, "retriable": True},
    # 任务
    ErrorCode.JOB_QUEUE_FULL:               {"status": 429, "retriable": True},
    ErrorCode.JOB_NOT_FOUND:                {"status": 404, "retriable": False},
    ErrorCode.JOB_NOT_COMPLETED:            {"status": 409, "retriable": True},
    ErrorCode.JOB_ALREADY_CANCELLED:        {"status": 409, "retriable": False},
    ErrorCode.JOB_TIMEOUT:                  {"status": 504, "retriable": True},
    ErrorCode.JOB_IDEMPOTENT_HIT:           {"status": 200, "retriable": False},
    ErrorCode.JOB_IDEMPOTENCY_CONFLICT:     {"status": 409, "retriable": False},
    # LLM
    ErrorCode.LLM_CONNECTION_ERROR:         {"status": 502, "retriable": True},
    ErrorCode.LLM_TIMEOUT:                  {"status": 504, "retriable": True},
    ErrorCode.LLM_RATE_LIMITED:             {"status": 429, "retriable": True},
    ErrorCode.LLM_GENERATION_FAILED:        {"status": 500, "retriable": True},
    ErrorCode.LLM_API_KEY_INVALID:          {"status": 401, "retriable": False},
    # 质量
    ErrorCode.QUALITY_GATE_FAILED:          {"status": 422, "retriable": False},
    # 模板
    ErrorCode.TEMPLATE_NOT_FOUND:           {"status": 404, "retriable": False},
    ErrorCode.TEMPLATE_PARSE_ERROR:         {"status": 500, "retriable": False},
    ErrorCode.TEMPLATE_UPDATE_FAILED:       {"status": 500, "retriable": True},
    # 校验
    ErrorCode.VALIDATION_INVALID_TEMPLATE_NAME: {"status": 422, "retriable": False},
    ErrorCode.VALIDATION_FIELD_TOO_LONG:    {"status": 422, "retriable": False},
    ErrorCode.VALIDATION_TOO_MANY_COMPETITORS:  {"status": 422, "retriable": False},
    ErrorCode.VALIDATION_BODY_TOO_LARGE:    {"status": 413, "retriable": False},
    # 系统
    ErrorCode.SYSTEM_INTERNAL_ERROR:        {"status": 500, "retriable": True},
    ErrorCode.SYSTEM_SHUTTING_DOWN:          {"status": 503, "retriable": True},
}


# ---------------------------------------------------------------------------
# 应用异常类
# ---------------------------------------------------------------------------

class AppError(Exception):
    """统一应用异常。

    使用方式::

        raise AppError(
            ErrorCode.JOB_QUEUE_FULL,
            "任务队列已满（当前 10/10），请稍后重试",
            retry_after_seconds=30,
        )
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        status_code: Optional[int] = None,
        retriable: Optional[bool] = None,
        retry_after_seconds: Optional[int] = None,
        extra: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message)
        meta = _ERROR_META.get(code, {"status": 500, "retriable": False})
        self.code = code
        self.message = message
        self.status_code = status_code or meta["status"]
        self.retriable = retriable if retriable is not None else meta["retriable"]
        self.retry_after_seconds = retry_after_seconds
        self.extra = extra or {}

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "code": self.code.value,
            "message": self.message,
            "retriable": self.retriable,
        }
        if self.retry_after_seconds is not None:
            body["retry_after_seconds"] = self.retry_after_seconds
        if self.extra:
            body.update(self.extra)
        return body


# ---------------------------------------------------------------------------
# FastAPI 异常处理器
# ---------------------------------------------------------------------------

async def _app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    headers = {}
    if exc.retry_after_seconds is not None:
        headers["Retry-After"] = str(exc.retry_after_seconds)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.to_dict(), "detail": exc.message},
        headers=headers or None,
    )


async def _generic_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """兜底异常处理器，将未捕获异常转为标准格式。"""
    detail = f"内部服务器错误: {type(exc).__name__}"
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": ErrorCode.SYSTEM_INTERNAL_ERROR.value,
                "message": detail,
                "retriable": True,
            },
            "detail": detail,
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    """向 FastAPI 应用注册统一异常处理器。"""
    app.add_exception_handler(AppError, _app_error_handler)  # type: ignore[arg-type]
    # 注意: 仅在非 debug 模式下注册兜底处理器，debug 时保留默认堆栈
    from .config import settings
    if not settings.debug:
        app.add_exception_handler(Exception, _generic_error_handler)  # type: ignore[arg-type]
