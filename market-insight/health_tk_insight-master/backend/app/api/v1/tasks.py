"""
Market Insight Agent - 任务状态查询 API
=======================================
查询任务执行状态和获取结果。

接口说明：
- GET /api/v1/tasks/{task_id}：查询任务状态
- GET /api/v1/tasks/{task_id}/report：获取任务报告（HTML 文件流）
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger

from app.models.response import TaskStatusResponse
from app.services.task_manager import task_manager

router = APIRouter()


@router.get(
    "",
    summary="列出最近任务",
    description="""
    返回最近任务列表（用于简单的历史记录/管理台）。

    - SQLite 持久化模式：从数据库按 created_at 倒序读取
    - Memory 模式：返回当前进程内已创建任务
    """,
)
async def list_tasks(limit: int = 50):
    tasks = await task_manager.list_tasks(limit=limit)
    items = []
    for t in tasks:
        items.append(
            {
                "task_id": t.task_id,
                "task_type": t.task_type,
                "status": t.status,
                "progress": t.progress,
                "message": t.message,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                "report_url": f"/api/v1/tasks/{t.task_id}/report"
                if t.status == "completed"
                else None,
            }
        )

    return {"success": True, "data": {"items": items}}


@router.get(
    "/{task_id}",
    response_model=TaskStatusResponse,
    summary="查询任务状态",
    description="""
    查询指定任务的执行状态和结果。
    
    **任务状态**：
    - `processing`: 处理中，前端应继续轮询
    - `completed`: 已完成，返回 report_url（用于下载 HTML 文件流）
    - `failed`: 失败，返回错误信息
    
    **轮询建议**：
    - 初始间隔：2 秒
    - 逐步增加：2s → 3s → 5s
    - 超时时间：5 分钟
    """,
)
async def get_task_status(task_id: str) -> TaskStatusResponse:
    """
    获取任务状态
    
    返回内容根据任务状态不同而变化：
    - processing: 返回进度信息
    - completed: 返回 report_url（用于下载 HTML 文件流）
    - failed: 返回错误详情
    """
    logger.info(f"Querying task status: {task_id}")
    
    try:
        task = await task_manager.get_task(task_id)
        
        if task is None:
            raise HTTPException(
                status_code=404,
                detail=f"Task not found: {task_id}",
            )
        
        # 根据任务状态构建响应
        if task.status == "processing":
            return TaskStatusResponse(
                success=True,
                data={
                    "task_id": task.task_id,
                    "status": "processing",
                    "progress": task.progress,
                    "message": task.message,
                },
            )
        elif task.status == "completed":
            return TaskStatusResponse(
                success=True,
                data={
                    "task_id": task.task_id,
                    "status": "completed",
                    "report_type": task.task_type,
                    "report_url": f"/api/v1/tasks/{task.task_id}/report",
                    "created_at": task.created_at.isoformat(),
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                },
            )
        else:  # failed
            return TaskStatusResponse(
                success=False,
                data={
                    "task_id": task.task_id,
                    "status": "failed",
                    "error": task.error_message,
                    "details": task.error_details,
                },
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get task status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/{task_id}/report",
    summary="获取任务报告（HTML 文件流）",
    description="""
    获取任务生成的 HTML 报告。

    - 当任务未完成时返回 409
    - 当任务失败时返回 400
    - 成功时返回 `text/html`，并带 `Content-Disposition` 便于浏览器下载
    """,
    responses={
        200: {"content": {"text/html": {}}},
        400: {"description": "任务失败"},
        404: {"description": "任务不存在"},
        409: {"description": "任务未完成"},
    },
)
async def download_task_report(task_id: str):
    logger.info(f"Downloading task report: {task_id}")

    task = await task_manager.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    if task.status == "processing":
        raise HTTPException(status_code=409, detail="Task not completed yet")

    if task.status == "failed":
        raise HTTPException(status_code=400, detail=task.error_message or "Task failed")

    html = task.result or ""
    filename = f"{task.task_type}_{task.task_id}.html"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

    return StreamingResponse(
        iter([html.encode("utf-8")]),
        media_type="text/html; charset=utf-8",
        headers=headers,
    )
