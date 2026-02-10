# -*- coding: utf-8 -*-
"""
腾讯云VOD AIGC视频生成服务 API
本模块提供了创建AIGC视频任务和查询任务状态的FastAPI接口
基于Redis Stream的任务队列系统
"""

import json
import time
import uuid
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from config import Config

# 创建FastAPI应用实例
app = FastAPI(
    title="腾讯云AIGC视频生成服务",
    description="提供基于队列的AIGC视频生成任务创建和状态查询接口",
    version="2.0.0",
    docs_url="/docs",      # Swagger UI
    redoc_url="/redoc",    # ReDoc UI
)

# Redis客户端
redis_client = Config.get_redis_client()

# ============ 请求/响应模型 ============

class AigcRequest(BaseModel):
    """
    AIGC视频生成任务请求模型
    
    Attributes:
        prompt: 视频生成的提示词（必填）
        file_id: 参考文件ID，用于图生视频等场景（可选）
        model_name: 模型名称（可选）
            - "Hailuo": 海螺模型
            - "Kling": 可灵模型
            - "OS": 默认模型
        model_version: 模型版本（可选）
            - Hailuo: "02", "2.3", "2.3-fast"
            - Kling: "1.6", "2.0", "2.1", "2.5", "O1"
        duration: 输出视频时长（可选）
            - Hailuo: 6, 10（默认6）
            - Kling: 5, 10（默认5）
        resolution: 视频分辨率（可选）
            - Hailuo: "768P", "1080P"（默认768P）
            - Kling: "720P", "1080P"（默认720P）
        aspect_ratio: 宽高比，仅Kling文生视频支持（可选）
            - "16:9", "9:16", "1:1"（默认16:9）
        enhance_switch: 是否开启超分增强（可选）
            - "Enabled": 开启
            - "Disabled": 关闭
        enhance_prompt: 是否增强提示词（可选）
            - "Enabled": 开启
            - "Disabled": 关闭
        frame_interpolate: 智能插帧，仅Vidu支持（可选）
            - "Enabled": 开启
            - "Disabled": 关闭
        tasks_priority: 任务优先级，-10到10，数值越大优先级越高（可选，默认0）
        scene_type: 场景类型，仅Kling支持（可选）
    """
    prompt: str = "一个小男孩在街上跑步"
    file_id: Optional[str] = Field(default=None, examples=[None])
    model_name: Optional[str] = "Hailuo"
    model_version: Optional[str] = "2.3"
    duration: Optional[int] = 6
    resolution: Optional[str] = "768P"
    aspect_ratio: Optional[str] = "16:9"
    audio_generation: str = "Enabled"
    enhance_switch: Optional[str] = "Disabled"
    enhance_prompt: Optional[str] = "Enabled"
    frame_interpolate: Optional[str] = "Disabled"
    tasks_priority: Optional[int] = 10
    scene_type: Optional[str] = Field(default=None, examples=[None])


@app.post("/aigc/create")
def create_aigc_task(req: AigcRequest):
    """
    创建AIGC视频生成任务（入队）
    
    将任务添加到Redis Stream队列，由Worker异步处理
    
    Args:
        req: AIGC任务请求参数
    
    Returns:
        包含task_id, position, status的响应
    
    Raises:
        HTTPException: 当Redis操作失败时抛出
    """
    try:
        # 生成任务ID
        task_id = str(uuid.uuid4())
        
        # 准备任务数据
        task_data = {
            "prompt": req.prompt,
            "file_id": req.file_id,
            "model_name": req.model_name,
            "model_version": req.model_version,
            "duration": req.duration,
            "resolution": req.resolution,
            "aspect_ratio": req.aspect_ratio,
            "audio_generation": req.audio_generation,
            "enhance_switch": req.enhance_switch,
            "enhance_prompt": req.enhance_prompt,
            "frame_interpolate": req.frame_interpolate,
            "tasks_priority": req.tasks_priority,
            "scene_type": req.scene_type
        }
        
        # 添加到Redis Stream
        message_id = redis_client.xadd(
            Config.STREAM_KEY,
            {
                "task_id": task_id,
                "task_data": json.dumps(task_data, ensure_ascii=False)
            }
        )
        
        # 初始化任务状态
        task_key = f"{Config.TASK_STATUS_PREFIX}{task_id}"
        redis_client.hset(task_key, mapping={
            "task_id": task_id,
            "status": "queued",
            "created_at": str(int(time.time())),
            "updated_at": str(int(time.time()))
        })
        
        # 计算队列位置
        # 获取Stream长度
        stream_info = redis_client.xinfo_stream(Config.STREAM_KEY)
        position = stream_info.get("length", 0)
        
        return {
            "task_id": task_id,
            "position": position,
            "status": "queued"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create task: {str(e)}")


# ============ 查询任务状态接口 ============

@app.get("/aigc/status/{task_id}")
def get_task_status(task_id: str):
    """
    查询AIGC视频任务状态
    
    Args:
        task_id: 任务ID
    
    Returns:
        包含task_id, status, position, result的响应
        - status: queued / processing / completed / failed
        - position: 排队位置（processing和completed时为0）
    
    Raises:
        HTTPException: 当任务不存在时抛出
    """
    try:
        # 获取任务状态
        task_key = f"{Config.TASK_STATUS_PREFIX}{task_id}"
        task_info = redis_client.hgetall(task_key)
        
        if not task_info:
            raise HTTPException(status_code=404, detail="Task not found")
        
        status = task_info.get("status", "unknown")
        
        # 计算位置
        position = 0
        if status == "queued":
            # 获取队列中的位置（估算）
            try:
                stream_info = redis_client.xinfo_stream(Config.STREAM_KEY)
                position = stream_info.get("length", 0)
            except Exception:
                # Stream可能不存在或其他Redis错误
                position = 0
        
        # 准备响应
        response = {
            "task_id": task_id,
            "status": status,
            "position": position
        }
        
        # 如果有结果，添加到响应
        if "result" in task_info:
            try:
                response["result"] = json.loads(task_info["result"])
            except (json.JSONDecodeError, TypeError):
                # 如果解析失败，直接返回原始字符串
                response["result"] = task_info["result"]
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query task: {str(e)}")


# ============ 查询队列信息接口 ============

@app.get("/aigc/queue/info")
def get_queue_info():
    """
    查询队列信息
    
    Returns:
        包含queue_length, active_count, max_concurrency的响应
    """
    try:
        # 获取队列长度
        try:
            stream_info = redis_client.xinfo_stream(Config.STREAM_KEY)
            queue_length = stream_info.get("length", 0)
        except Exception:
            # Stream可能不存在或其他Redis错误
            queue_length = 0
        
        # 获取活跃任务数
        active_count = redis_client.get(Config.ACTIVE_COUNT_KEY)
        active_count = int(active_count) if active_count else 0
        
        # 获取当前并发阈值
        max_concurrency = redis_client.get(Config.THRESHOLD_KEY)
        max_concurrency = int(max_concurrency) if max_concurrency else Config.DEFAULT_THRESHOLD
        
        return {
            "queue_length": queue_length,
            "active_count": active_count,
            "max_concurrency": max_concurrency
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get queue info: {str(e)}")


# ============ 健康检查接口 ============

@app.get("/health")
def health_check():
    """健康检查接口"""
    try:
        # 测试Redis连接
        redis_client.ping()
        return {"status": "healthy", "redis": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Service unhealthy: {str(e)}")
