"""
FastAPI 应用入口

提供报告生成、模板管理等 API 端点。
"""

import asyncio
import json
import re
import time
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .config import settings
from .errors import AppError, ErrorCode, register_error_handlers
from .logging_config import get_logger, setup_logging
from .middleware import RequestIDMiddleware, APIKeyAuthMiddleware, RequestBodyLimitMiddleware
from .llm.client import get_llm_client
from .pipeline import (
    ReportJobSpec,
    get_orchestrator,
    get_report_generator,
    get_template_parser,
)

logger = get_logger(__name__)

# ── 速率限制器 ──
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri="memory://",
)


# ============== Pydantic 模型 ==============

ReportType = Literal["brand_health", "tiktok_social_insight"]
JobStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "failed",
    "failed_quality_gate",
    "cancelled",
]
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "failed_quality_gate", "cancelled"}

_RUNTIME_PING_CACHE_LOCK = threading.Lock()
_RUNTIME_PING_CACHE: dict[str, Any] = {"ts": 0.0, "ping": None}
_RUNTIME_PING_TTL_SECONDS = 30.0


class GenerateBrandHealthReportRequest(BaseModel):
    """生成品牌健康度诊断报告请求"""

    brand_name: str = Field(..., description="品牌名称")
    category: str = Field(..., description="品类（用于消歧与限定范围）")
    recommended_competitors: List[str] = Field(default_factory=list, description="推荐竞品列表")
    template_name: str = Field("海飞丝.html", description="HTML 模板文件名")
    use_llm: bool = Field(True, description="是否使用 LLM 生成内容")
    strict_llm: bool = Field(False, description="use_llm 为 True 时，LLM 调用失败是否直接报错")
    enable_web_search: bool = Field(True, description="是否尝试使用 Tavily Web Search")


class GenerateTikTokSocialInsightRequest(BaseModel):
    """生成 TikTok 社媒洞察报告请求"""

    category_name: str = Field(..., description="品类名")
    product_selling_points: List[str] = Field(..., description="商品卖点（多条）")
    template_name: str = Field("tiktok-toothpaste-report.html", description="HTML 模板文件名")
    use_llm: bool = Field(True, description="是否使用 LLM 生成内容")
    strict_llm: bool = Field(False, description="use_llm 为 True 时，LLM 调用失败是否直接报错")
    enable_web_search: bool = Field(True, description="是否尝试使用 Tavily Web Search")


class GenerateReportResponse(BaseModel):
    """生成报告响应（统一结构）"""

    report_id: str
    report_type: ReportType
    generated_at: str
    output_path: str
    inputs: dict
    llm: Optional[dict] = None


class CreateReportJobRequest(BaseModel):
    """创建 v2 报告任务请求（首期 brand_health）。"""

    report_type: Literal["brand_health"] = Field("brand_health", description="报告类型")
    brand_name: str = Field(..., description="品牌名称")
    category: str = Field(..., description="品类")
    recommended_competitors: List[str] = Field(default_factory=list, description="推荐竞品列表")
    template_name: str = Field("海飞丝.html", description="模板文件名")
    use_llm: bool = Field(True, description="是否使用 LLM")
    strict_llm: bool = Field(False, description="LLM 失败是否中断")
    enable_web_search: bool = Field(True, description="是否启用联网搜索")


class CreateReportJobResponse(BaseModel):
    """创建 v2 报告任务响应。"""

    job_id: str
    report_type: str
    status: JobStatus
    created_at: str


class ReportJobStatusResponse(BaseModel):
    """任务状态响应。"""

    job_id: str
    report_type: str
    status: JobStatus
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    current_stage: Optional[str] = None
    progress: Dict[str, Any] = Field(default_factory=dict)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    section_logs: List[Dict[str, Any]] = Field(default_factory=list)


class ReportJobResultResponse(BaseModel):
    """任务结果响应。"""

    job_id: str
    report_id: str
    output_path: str
    generated_at: str
    llm_diagnostics: Optional[dict] = None
    quality_gate: Optional[dict] = None


class CancelReportJobResponse(BaseModel):
    """取消任务响应。"""

    job_id: str
    cancelled: bool


class TemplateStatusResponse(BaseModel):
    """模板状态响应"""

    exists: bool
    template_name: str
    template_path: str
    current_hash: Optional[str] = None
    cache_valid: Optional[bool] = None
    parsed_at: Optional[str] = None
    sections_count: int = 0


class UpdateTemplateRequest(BaseModel):
    """更新模板请求"""

    html_content: str = Field(..., description="新的 HTML 模板内容")
    template_name: str = Field("海飞丝.html", description="模板文件名")


class ReportListItem(BaseModel):
    """报告列表项"""

    report_id: str
    output_path: str
    created_at: str


class LLMStatusResponse(BaseModel):
    """LLM 状态响应"""

    ok: bool
    base_url: str
    model: str
    api_key_set: bool
    ping: dict
    web_search: Optional[dict] = None


class RuntimeServiceStatusResponse(BaseModel):
    """运行时单服务状态响应。"""

    ok: bool
    state: Literal["online", "offline", "degraded"]
    error: Optional[str] = None
    latency_ms: Optional[int] = None
    timestamp: Optional[str] = None


class RuntimeStatusResponse(BaseModel):
    """运行时聚合状态响应。"""

    api: RuntimeServiceStatusResponse
    llm: RuntimeServiceStatusResponse


# ============== FastAPI 应用 ==============

# ── 模板名校验：禁止路径遍历 ──
_SAFE_TEMPLATE_NAME_RE = re.compile(r"^[\w\u4e00-\u9fa5. -]{1,100}\.html$")


def _validate_template_name(name: str) -> None:
    if not _SAFE_TEMPLATE_NAME_RE.match(name) or ".." in name:
        raise AppError(
            ErrorCode.VALIDATION_INVALID_TEMPLATE_NAME,
            f"模板名不合法: {name!r}",
        )


def _validate_brand_health_input(request: CreateReportJobRequest) -> None:
    if len(request.brand_name) > 100:
        raise AppError(ErrorCode.VALIDATION_FIELD_TOO_LONG, "brand_name 超过 100 字符")
    if len(request.category) > 100:
        raise AppError(ErrorCode.VALIDATION_FIELD_TOO_LONG, "category 超过 100 字符")
    if len(request.recommended_competitors) > 10:
        raise AppError(
            ErrorCode.VALIDATION_TOO_MANY_COMPETITORS,
            f"竞品数超过限制: {len(request.recommended_competitors)}/10",
        )
    _validate_template_name(request.template_name)


# ── Lifespan ──
@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    # 启动阶段
    setup_logging()
    warnings = settings.validate_startup()
    for w in warnings:
        logger.warning("config_warning", detail=w)
    logger.info(
        "app_starting",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )
    orchestrator = get_orchestrator()
    await orchestrator.start()
    yield
    # 关闭阶段
    logger.info("app_shutting_down")
    await orchestrator.shutdown()
    logger.info("app_stopped")


app = FastAPI(
    title="Market Insight Agent API",
    description="AI 自动化市场洞察报告生成器",
    version="0.2.0",
    lifespan=lifespan,
)

# 注册错误处理器
register_error_handlers(app)

# 速率限制异常处理器
@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    error = AppError(
        ErrorCode.RATE_LIMIT_EXCEEDED,
        f"请求频率超限，请稍后重试",
        retry_after_seconds=60,
    )
    return JSONResponse(
        status_code=error.status_code,
        content={"error": error.to_dict(), "detail": error.message},
        headers={"Retry-After": str(error.retry_after_seconds)} if error.retry_after_seconds else None,
    )

app.state.limiter = limiter

# 中间件注册（注意顺序：后加的先执行）
app.add_middleware(RequestBodyLimitMiddleware, max_content_length=2 * 1024 * 1024)
app.add_middleware(APIKeyAuthMiddleware)
app.add_middleware(RequestIDMiddleware)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_url,
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    # Dev-friendly: allow local origins on any port (e.g. 3001/3002) and the
    # Codex/WSL bridge host used in some environments.
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|198\.18\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============== 辅助函数 ==============


async def _wait_for_job_completion(job_id: str, timeout_s: int) -> dict:
    orchestrator = get_orchestrator()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s

    while True:
        job = orchestrator.get_job_status(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"任务不存在: {job_id}")

        status = str(job.get("status") or "")
        if status in TERMINAL_JOB_STATUSES:
            return job

        if loop.time() > deadline:
            raise TimeoutError(f"任务等待超时: {job_id}")

        await asyncio.sleep(1.0)


def _build_v1_llm_payload(request: GenerateBrandHealthReportRequest, diagnostics: dict) -> dict:
    return {
        "use_llm": request.use_llm,
        "strict_llm": request.strict_llm,
        "enable_web_search": request.enable_web_search,
        "ping": diagnostics.get("ping"),
        "search_meta": diagnostics.get("search_meta"),
        "error": diagnostics.get("error"),
        "sections": diagnostics.get("sections"),
    }


# ============== API 端点 ==============


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "Market Insight Agent API",
        "version": "0.2.0",
        "status": "running",
        "docs_url": "/docs",
    }


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/llm/status", response_model=LLMStatusResponse)
async def llm_status(do_web_search: bool = False):
    """
    检查 LLM API 是否可用（会发起一次最小 LLM 调用）。
    """
    llm = get_llm_client()
    ping = llm.ping()

    web_search: Optional[dict] = None
    if do_web_search and ping.get("ok"):
        try:
            web_search = llm.search_and_generate(
                query="OpenAI 最新动态",
                brand="(probe)",
                competitors=["(probe)"],
            ).get("_meta", {})
        except Exception as e:
            web_search = {"ok": False, "error": f"{type(e).__name__}: {str(e)}"}

    return LLMStatusResponse(
        ok=bool(ping.get("ok")),
        base_url=llm.base_url,
        model=llm.model,
        api_key_set=bool(llm.api_key),
        ping=ping,
        web_search=web_search,
    )


@app.get("/api/runtime/status", response_model=RuntimeStatusResponse)
async def runtime_status():
    """聚合 API 与 LLM 运行时状态。"""
    now = datetime.now().isoformat()
    llm = get_llm_client()
    ping: dict
    now_ts = time.time()
    with _RUNTIME_PING_CACHE_LOCK:
        cached_ts = float(_RUNTIME_PING_CACHE.get("ts") or 0.0)
        cached_ping = _RUNTIME_PING_CACHE.get("ping")
        if isinstance(cached_ping, dict) and (now_ts - cached_ts) < _RUNTIME_PING_TTL_SECONDS:
            ping = cached_ping
        else:
            ping = {}

    if not ping:
        ping = await asyncio.to_thread(llm.ping, 6.0)
        with _RUNTIME_PING_CACHE_LOCK:
            _RUNTIME_PING_CACHE["ts"] = now_ts
            _RUNTIME_PING_CACHE["ping"] = ping
    llm_ok = bool(ping.get("ok"))

    return RuntimeStatusResponse(
        api=RuntimeServiceStatusResponse(
            ok=True,
            state="online",
            error=None,
            latency_ms=None,
            timestamp=now,
        ),
        llm=RuntimeServiceStatusResponse(
            ok=llm_ok,
            state="online" if llm_ok else "degraded",
            error=ping.get("error"),
            latency_ms=ping.get("latency_ms"),
            timestamp=now,
        ),
    )


# -------------- v2 异步任务 API --------------


@app.post("/api/v2/report-jobs", response_model=CreateReportJobResponse)
@limiter.limit(settings.rate_limit_generate)
async def create_report_job(request_body: CreateReportJobRequest, request: Request):
    """创建 v2 报告任务（首期支持 brand_health）。"""
    _validate_brand_health_input(request_body)
    idempotency_key = request.headers.get("Idempotency-Key")
    try:
        orchestrator = get_orchestrator()
        spec = ReportJobSpec(
            report_type=request_body.report_type,
            brand_name=request_body.brand_name,
            category=request_body.category,
            competitors=request_body.recommended_competitors,
            template_name=request_body.template_name,
            use_llm=request_body.use_llm,
            strict_llm=request_body.strict_llm,
            enable_web_search=request_body.enable_web_search,
        )
        result = orchestrator.submit_brand_health_job(spec, idempotency_key=idempotency_key)
        return CreateReportJobResponse(**result)
    except AppError:
        raise  # 已被 error handler 处理
    except Exception as e:
        logger.error("create_job_failed", error=str(e), exc_info=True)
        raise AppError(
            ErrorCode.SYSTEM_INTERNAL_ERROR,
            f"创建任务失败: {type(e).__name__}: {str(e)}",
        )


@app.get("/api/v2/report-jobs/{job_id}", response_model=ReportJobStatusResponse)
async def get_report_job(job_id: str):
    """查询任务状态。"""
    orchestrator = get_orchestrator()
    job = orchestrator.get_job_status(job_id)
    if job is None:
        raise AppError(ErrorCode.JOB_NOT_FOUND, f"任务不存在: {job_id}")
    return ReportJobStatusResponse(**job)


@app.get("/api/v2/report-jobs/{job_id}/events")
async def stream_report_job_events(job_id: str, request: Request):
    """任务进度事件流（SSE）。"""
    orchestrator = get_orchestrator()
    if orchestrator.get_job_status(job_id) is None:
        raise AppError(ErrorCode.JOB_NOT_FOUND, f"任务不存在: {job_id}")

    async def event_generator():
        last_seq = 0
        while True:
            if await request.is_disconnected():
                break

            events = orchestrator.get_events(job_id, after_seq=last_seq)
            for event in events:
                last_seq = int(event.get("seq") or last_seq)
                payload = json.dumps(event, ensure_ascii=False)
                yield f"event: job_event\ndata: {payload}\n\n"

            job = orchestrator.get_job_status(job_id)
            if job and str(job.get("status") or "") in TERMINAL_JOB_STATUSES:
                terminal_payload = json.dumps(
                    {
                        "job_id": job_id,
                        "status": job.get("status"),
                        "finished_at": job.get("finished_at"),
                    },
                    ensure_ascii=False,
                )
                yield f"event: job_terminal\ndata: {terminal_payload}\n\n"
                break

            yield ": heartbeat\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/v2/report-jobs/{job_id}/result", response_model=ReportJobResultResponse)
async def get_report_job_result(job_id: str):
    """查询任务结果。"""
    orchestrator = get_orchestrator()
    job = orchestrator.get_job_status(job_id)
    if job is None:
        raise AppError(ErrorCode.JOB_NOT_FOUND, f"任务不存在: {job_id}")

    status = str(job.get("status") or "")
    if status != "succeeded":
        raise AppError(
            ErrorCode.JOB_NOT_COMPLETED,
            f"任务尚未成功完成: status={status}",
        )

    result = orchestrator.get_job_result(job_id)
    if not isinstance(result, dict):
        raise AppError(ErrorCode.SYSTEM_INTERNAL_ERROR, "任务结果缺失")

    return ReportJobResultResponse(
        job_id=job_id,
        report_id=str(result.get("report_id") or ""),
        output_path=str(result.get("output_path") or ""),
        generated_at=str(result.get("generated_at") or datetime.now().isoformat()),
        llm_diagnostics=result.get("llm_diagnostics"),
        quality_gate=result.get("quality_gate"),
    )


@app.post("/api/v2/report-jobs/{job_id}/cancel", response_model=CancelReportJobResponse)
async def cancel_report_job(job_id: str):
    """取消任务（仅 queued/running 生效）。"""
    orchestrator = get_orchestrator()
    if orchestrator.get_job_status(job_id) is None:
        raise AppError(ErrorCode.JOB_NOT_FOUND, f"任务不存在: {job_id}")
    cancelled = orchestrator.cancel_job(job_id)
    return CancelReportJobResponse(job_id=job_id, cancelled=cancelled)


# -------------- 报告生成（v1 兼容）--------------


@app.post("/api/generate/brand_health", response_model=GenerateReportResponse)
@limiter.limit(settings.rate_limit_generate)
async def generate_brand_health_report(request_body: GenerateBrandHealthReportRequest, request: Request):
    """生成品牌健康度诊断报告（v1 兼容：内部走 v2 任务编排）。"""
    try:
        _validate_template_name(request_body.template_name)
        orchestrator = get_orchestrator()
        spec = ReportJobSpec(
            report_type="brand_health",
            brand_name=request_body.brand_name,
            category=request_body.category,
            competitors=request_body.recommended_competitors,
            template_name=request_body.template_name,
            use_llm=request_body.use_llm,
            strict_llm=request_body.strict_llm,
            enable_web_search=request_body.enable_web_search,
        )
        submit = orchestrator.submit_brand_health_job(spec)
        job_id = str(submit["job_id"])

        try:
            job = await _wait_for_job_completion(
                job_id=job_id,
                timeout_s=int(getattr(settings, "report_job_soft_timeout_seconds", 720) or 720),
            )
        except TimeoutError:
            raise AppError(ErrorCode.JOB_TIMEOUT, f"报告生成超时: {job_id}")

        status = str(job.get("status") or "")
        if status != "succeeded":
            error_code = job.get("error_code") or "generate_failed"
            error_message = job.get("error_message") or "报告生成失败"
            if status == "failed_quality_gate":
                raise AppError(
                    ErrorCode.QUALITY_GATE_FAILED,
                    f"报告生成失败: status={status}, error_code={error_code}, error={error_message}",
                )
            raise AppError(
                ErrorCode.LLM_GENERATION_FAILED,
                f"报告生成失败: status={status}, error_code={error_code}, error={error_message}",
            )

        result = orchestrator.get_job_result(job_id)
        if not isinstance(result, dict):
            raise AppError(ErrorCode.SYSTEM_INTERNAL_ERROR, "报告生成成功但结果缺失")

        diagnostics = result.get("llm_diagnostics") if isinstance(result.get("llm_diagnostics"), dict) else {}

        return GenerateReportResponse(
            report_id=str(result.get("report_id") or ""),
            report_type="brand_health",
            generated_at=str(result.get("generated_at") or datetime.now().isoformat()),
            output_path=str(result.get("output_path") or ""),
            inputs={
                "brand_name": request_body.brand_name,
                "category": request_body.category,
                "recommended_competitors": request_body.recommended_competitors,
                "template_name": request_body.template_name,
            },
            llm=_build_v1_llm_payload(request_body, diagnostics) if request_body.use_llm else None,
        )
    except (HTTPException, AppError):
        raise
    except Exception as e:
        logger.error("generate_brand_health_failed", error=str(e), exc_info=True)
        raise AppError(
            ErrorCode.SYSTEM_INTERNAL_ERROR,
            f"报告生成失败: {type(e).__name__}: {str(e)}",
        )


@app.post("/api/generate/tiktok_social_insight", response_model=GenerateReportResponse)
async def generate_tiktok_social_insight_report(request: GenerateTikTokSocialInsightRequest):
    """生成 TikTok 社媒洞察报告"""
    try:
        generator = get_report_generator()
        result = generator.generate_tiktok_social_insight(
            category_name=request.category_name,
            product_selling_points=request.product_selling_points,
            template_name=request.template_name,
            use_llm=request.use_llm,
            strict_llm=request.strict_llm,
            enable_web_search=request.enable_web_search,
        )

        return GenerateReportResponse(
            report_id=result["report_id"],
            report_type="tiktok_social_insight",
            generated_at=result["generated_at"],
            output_path=result["output_path"],
            inputs={
                "category_name": request.category_name,
                "product_selling_points": request.product_selling_points,
                "template_name": request.template_name,
            },
            llm=(
                {
                    "use_llm": request.use_llm,
                    "strict_llm": request.strict_llm,
                    "enable_web_search": request.enable_web_search,
                    "ping": result.get("context_data", {}).get("llm_ping"),
                    "search_meta": (result.get("context_data", {}).get("llm_search") or {}).get("_meta"),
                    "error": result.get("context_data", {}).get("llm_error"),
                    "sections": result.get("context_data", {}).get("llm_sections"),
                }
                if request.use_llm
                else None
            ),
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"报告生成失败: {str(e)}")


# Back-compat: 旧接口 /api/generate 作为品牌健康度诊断的别名（仅接收旧字段时会报 422）
@app.post("/api/generate", response_model=GenerateReportResponse)
@limiter.limit(settings.rate_limit_generate)
async def generate_report_compat(request_body: GenerateBrandHealthReportRequest, request: Request):
    return await generate_brand_health_report(request_body, request)


@app.get("/api/reports", response_model=List[ReportListItem])
async def list_reports(limit: int = 20):
    """
    列出已生成的报告

    - **limit**: 返回数量限制（默认 20）
    """
    generator = get_report_generator()
    reports = generator.list_reports(limit=limit)

    return [
        ReportListItem(
            report_id=r["report_id"],
            output_path=r["output_path"],
            created_at=r["created_at"],
        )
        for r in reports
    ]


@app.get("/api/reports/{report_id}")
async def get_report(report_id: str):
    """
    获取指定报告

    - **report_id**: 报告 ID
    """
    generator = get_report_generator()
    report = generator.get_report(report_id)

    if report is None:
        raise HTTPException(status_code=404, detail=f"报告不存在: {report_id}")

    return report


@app.get("/api/reports/{report_id}/html", response_class=HTMLResponse)
async def get_report_html(report_id: str):
    """
    获取报告 HTML 内容（用于 iframe 预览）

    - **report_id**: 报告 ID
    """
    generator = get_report_generator()
    report = generator.get_report(report_id)

    if report is None:
        raise HTTPException(status_code=404, detail=f"报告不存在: {report_id}")

    return HTMLResponse(content=report["html_content"])


@app.get("/api/reports/{report_id}/download")
async def download_report(report_id: str):
    """
    下载报告文件

    - **report_id**: 报告 ID
    """
    generator = get_report_generator()
    report = generator.get_report(report_id)

    if report is None:
        raise HTTPException(status_code=404, detail=f"报告不存在: {report_id}")

    file_path = Path(report["output_path"])
    return FileResponse(
        path=file_path,
        filename=f"{report_id}.html",
        media_type="text/html",
    )


# -------------- 模板管理 --------------


@app.get("/api/template/status", response_model=TemplateStatusResponse)
async def get_template_status(template_name: str = "海飞丝.html"):
    """
    获取模板状态

    返回模板的当前状态，包括 hash、解析时间、缓存是否有效等。

    - **template_name**: 模板文件名（默认 海飞丝.html）
    """
    parser = get_template_parser()
    status = parser.get_status(template_name)

    return TemplateStatusResponse(**status)


@app.post("/api/template/update")
async def update_template(request: UpdateTemplateRequest):
    """
    更新模板

    保存新的 HTML 模板内容并重新解析。

    - **html_content**: 新的 HTML 模板内容
    - **template_name**: 模板文件名（默认 海飞丝.html）
    """
    try:
        _validate_template_name(request.template_name)
        parser = get_template_parser()
        result = parser.update_template(
            template_name=request.template_name,
            html_content=request.html_content,
        )

        return {
            "success": True,
            "template_name": result["template_name"],
            "template_hash": result["template_hash"],
            "parsed_at": result["parsed_at"],
            "sections_count": len(result["sections"]),
        }
    except AppError:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"模板更新失败: {str(e)}")


@app.get("/api/template/content")
async def get_template_content(template_name: str = "海飞丝.html"):
    """
    获取模板内容

    返回模板的 HTML 源代码，用于编辑器加载。

    - **template_name**: 模板文件名
    """
    parser = get_template_parser()
    template_path = parser.template_dir / template_name

    if not template_path.exists():
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_name}")

    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    return {
        "template_name": template_name,
        "content": content,
    }


@app.post("/api/template/parse")
async def parse_template(
    template_name: str = "海飞丝.html",
    force: bool = False,
):
    """
    解析模板

    解析指定模板并返回结构信息。如果缓存有效且不强制重新解析，将返回缓存结果。

    - **template_name**: 模板文件名
    - **force**: 是否强制重新解析（忽略缓存）
    """
    try:
        parser = get_template_parser()
        result = parser.parse(template_name, force_reparse=force)

        # 转换 sections 为可序列化格式
        sections_data = [s.to_dict() if hasattr(s, "to_dict") else s for s in result.get("sections", [])]

        return {
            "template_name": result["template_name"],
            "template_hash": result["template_hash"],
            "parsed_at": result["parsed_at"],
            "from_cache": result["from_cache"],
            "sections": sections_data,
            "full_structure": result.get("full_structure", {}),
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"模板解析失败: {str(e)}")


# ============== 启动入口 ==============


def start_server():
    """启动服务器"""
    import uvicorn

    uvicorn.run(
        "market_insight_agent.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    start_server()
