"""
Market Insight Agent - 品牌健康度诊断 API
==========================================
处理品牌健康度分析相关的 API 请求。

接口说明：
- POST /api/v1/brand-health：提交品牌分析任务
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException
from loguru import logger

from app.config import settings
from app.models.request import BrandHealthRequest
from app.models.response import TaskCreatedResponse
from app.services.task_manager import task_manager

router = APIRouter()


@router.post(
    "",
    response_model=TaskCreatedResponse,
    summary="提交品牌健康度分析任务",
    description="""
    提交一个品牌健康度分析任务。
    
    **输入参数**：
    - brand_name: 品牌名称（必填）
    - competitors: 竞品列表（可选）
    - region: 目标地区（必填）
    
    **返回**：
    - task_id: 任务唯一标识，用于后续查询任务状态
    - status: 当前状态（processing）
    
    **后续流程**：
    使用 task_id 轮询 GET /api/v1/tasks/{task_id} 获取任务状态和结果。
    """,
)
async def create_brand_health_task(
    request: BrandHealthRequest,
    background_tasks: BackgroundTasks,
) -> TaskCreatedResponse:
    """
    创建品牌健康度分析任务
    
    流程：
    1. 验证请求参数
    2. 创建任务记录
    3. 将任务加入后台队列
    4. 立即返回 task_id
    """
    logger.info(f"Received brand health analysis request: {request.brand_name}")
    
    try:
        # 创建任务
        task_id = await task_manager.create_task(
            task_type="brand_health",
            params=request.model_dump(),
        )

        if settings.celery_enabled:
            from app.celery_app import run_brand_health

            run_brand_health.delay(task_id, request.model_dump())
        else:
            # 当前使用 FastAPI BackgroundTasks 作为简化实现
            background_tasks.add_task(
                task_manager.execute_brand_health_task,
                task_id=task_id,
                params=request.model_dump(),
            )
        
        logger.info(f"Brand health task created: {task_id}")
        
        return TaskCreatedResponse(
            success=True,
            data={
                "task_id": task_id,
                "status": "processing",
            },
        )
        
    except Exception as e:
        logger.error(f"Failed to create brand health task: {e}")
        raise HTTPException(status_code=500, detail=str(e))
