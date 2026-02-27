"""
结构化日志配置模块。

基于 structlog 提供 JSON / Console 两种输出格式，
自动注入 request_id 和 job_id 上下文字段。
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

from .config import settings

# ---------------------------------------------------------------------------
# 上下文变量：request_id / job_id 等由中间件或业务代码绑定
# ---------------------------------------------------------------------------

_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")
_job_id_ctx: ContextVar[str] = ContextVar("job_id", default="")


def bind_request_id(rid: str) -> None:
    _request_id_ctx.set(rid)


def bind_job_id(jid: str) -> None:
    _job_id_ctx.set(jid)


def _inject_context(
    _logger: Any, _method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """structlog processor: 自动注入上下文变量。"""
    rid = _request_id_ctx.get("")
    jid = _job_id_ctx.get("")
    if rid:
        event_dict.setdefault("request_id", rid)
    if jid:
        event_dict.setdefault("job_id", jid)
    return event_dict


# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------

_configured = False


def setup_logging() -> None:
    """配置 structlog + 标准 logging 集成。仅执行一次。"""
    global _configured
    if _configured:
        return
    _configured = True

    log_format = settings.log_format  # "auto" | "json" | "console"
    log_level = settings.log_level.upper()

    # 判断输出格式
    if log_format == "auto":
        use_json = not sys.stderr.isatty()
    else:
        use_json = log_format == "json"

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _inject_context,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if use_json:
        renderer: Any = structlog.processors.JSONRenderer(ensure_ascii=False)
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, log_level, logging.INFO))

    # 降低第三方库日志级别
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """获取 structlog 日志实例。"""
    if not _configured:
        setup_logging()
    return structlog.get_logger(name)  # type: ignore[return-value]
