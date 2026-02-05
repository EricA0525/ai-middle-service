"""
Market Insight Agent - TikTok 社媒洞察 API
==========================================
处理 TikTok 社媒分析相关的 API 请求。

接口说明：
- POST /api/v1/tiktok-insight：提交 TikTok 分析任务
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException
from loguru import logger

from app.config import settings
from app.models.request import TikTokInsightRequest
from app.models.response import TaskCreatedResponse
from app.services.task_manager import task_manager

router = APIRouter()


@router.post(
    "",
    response_model=TaskCreatedResponse,
    summary="提交 TikTok 社媒洞察任务",
    description="""
    提交一个 TikTok 社媒洞察分析任务。
    
    **输入参数**：
    - category: 商品品类（必填）
    - selling_points: 商品卖点列表（必填）
    
    **返回**：
    - task_id: 任务唯一标识
    - status: 当前状态（processing）
    
    **后续流程**：
    使用 task_id 轮询 GET /api/v1/tasks/{task_id} 获取任务状态和结果。
    """,
)
async def create_tiktok_insight_task(
    request: TikTokInsightRequest,
    background_tasks: BackgroundTasks,
) -> TaskCreatedResponse:
    """
    创建 TikTok 社媒洞察任务
    """
    logger.info(f"Received TikTok insight request: {request.category}")
    
    try:
        # 创建任务
        task_id = await task_manager.create_task(
            task_type="tiktok_insight",
            params=request.model_dump(),
        )

        if settings.celery_enabled:
            from app.celery_app import run_tiktok_insight

            run_tiktok_insight.delay(task_id, request.model_dump())
        else:
            background_tasks.add_task(
                task_manager.execute_tiktok_insight_task,
                task_id=task_id,
                params=request.model_dump(),
            )
        
        logger.info(f"TikTok insight task created: {task_id}")
        
        return TaskCreatedResponse(
            success=True,
            data={
                "task_id": task_id,
                "status": "processing",
            },
        )
        
    except Exception as e:
        logger.error(f"Failed to create TikTok insight task: {e}")
        raise HTTPException(status_code=500, detail=str(e))
