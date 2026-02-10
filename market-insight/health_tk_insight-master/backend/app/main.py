"""
Market Insight Agent - FastAPI Application Entry
=================================================
应用主入口，负责初始化 FastAPI 应用和注册路由。

设计思想：
1. 职责单一：此文件只负责应用初始化和启动配置
2. 模块化：路由、中间件、事件处理器分离到各自模块
3. 可测试：通过工厂函数创建应用，便于测试时使用不同配置
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from loguru import logger

from app.config import settings
from app.api.v1.router import api_router
from app.db.session import init_db
from app.middleware.logging import LoggingMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    应用生命周期管理
    
    - startup: 初始化资源（数据库连接、缓存等）
    - shutdown: 清理资源
    """
    # ========== Startup ==========
    logger.info(f"Starting {settings.app_name} in {settings.app_env} mode...")

    if settings.log_to_file:
        from pathlib import Path

        log_path = Path(settings.log_file_path)
        if not log_path.is_absolute():
            log_path = Path.cwd() / log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            str(log_path),
            rotation="10 MB",
            retention="7 days",
            level=settings.log_level,
            backtrace=True,
            diagnose=False,
        )

    if settings.task_store_backend == "sqlite":
        await init_db()

    # TODO: 初始化 Redis 连接
    # TODO: 预加载模板文件
    
    logger.info("Application startup complete.")
    
    yield  # 应用运行中
    
    # ========== Shutdown ==========
    logger.info("Shutting down application...")

    # TODO: 关闭 Redis 连接
    
    logger.info("Application shutdown complete.")


def create_app() -> FastAPI:
    """
    应用工厂函数
    
    使用工厂模式创建应用，便于：
    1. 测试时使用不同配置
    2. 按需初始化不同组件
    """
    app = FastAPI(
        title="Market Insight Agent API",
        description="""
        ## 🎯 市场洞察报告自动生成系统

        基于 AI Agent 的市场洞察报告生成服务，支持：
        - **品牌健康度诊断**：分析品牌市场健康状况
        - **TikTok 社媒洞察**：分析 TikTok 爆款视频趋势

        ### 使用流程
        1. 提交分析任务，获取 `task_id`
        2. 轮询任务状态
        3. 任务完成后获取 HTML 报告内容
        """,
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ========== 全局异常处理 ==========
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(_request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"success": False, "data": {"error": exc.detail}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"success": False, "data": {"error": "Validation Error", "details": exc.errors()}},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_request, exc: Exception):
        logger.exception("Unhandled exception")
        return JSONResponse(
            status_code=500,
            content={"success": False, "data": {"error": "Internal Server Error"}},
        )
    
    # ========== 注册中间件 ==========
    # 日志中间件（应该最先注册，以便记录所有请求）
    app.add_middleware(LoggingMiddleware)
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 生产环境应限制具体域名
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 体积较大的 JSON / HTML 报告建议开启压缩
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    
    # ========== 注册路由 ==========
    app.include_router(api_router, prefix=settings.api_prefix)
    
    # ========== 健康检查端点 ==========
    @app.get("/health", tags=["System"])
    async def health_check():
        """健康检查端点"""
        return {
            "status": "healthy",
            "app_name": settings.app_name,
            "environment": settings.app_env,
        }
    
    return app


# 创建应用实例
app = create_app()


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.is_development,
    )
