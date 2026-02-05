"""
Market Insight Agent - API Router
===================================
API v1 路由汇总，将各模块路由注册到统一入口。

设计思想：
1. 模块化路由：每个功能模块有独立的路由文件
2. 版本控制：通过 /api/v1 前缀区分版本
3. 标签分组：便于 API 文档组织
"""

from fastapi import APIRouter

from app.api.v1 import brand_health, tiktok_insight, tasks

# 创建 v1 版本路由
api_router = APIRouter()

# 注册各模块路由
api_router.include_router(
    brand_health.router,
    prefix="/brand-health",
    tags=["品牌健康度诊断"],
)

api_router.include_router(
    tiktok_insight.router,
    prefix="/tiktok-insight",
    tags=["TikTok社媒洞察"],
)

api_router.include_router(
    tasks.router,
    prefix="/tasks",
    tags=["任务管理"],
)
