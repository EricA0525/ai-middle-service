# -*- coding: utf-8 -*-
"""
腾讯云VOD AIGC视频生成服务 API
接收请求 → 写入 Redis Stream 队列 → 返回任务ID和排队位置
查询任务状态 → 从 Redis 读取
"""

import json
import uuid
import time
from typing import Optional

import redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from config import (
    REDIS_URL, STREAM_KEY, TASK_PREFIX, ACTIVE_COUNT_KEY,
    THRESHOLD_KEY, DEFAULT_THRESHOLD, CONSUMER_GROUP
)

# ========== Redis 连接 ==========
r = redis.from_url(REDIS_URL, decode_responses=True)

# ========== FastAPI 应用 ==========
app = FastAPI(
    title="腾讯云AIGC视频生成服务",
    description="提供AIGC视频生成任务创建和状态查询接口（带排队功能）",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


# ========== 请求/响应模型 ==========

class AigcRequest(BaseModel):
    """AIGC视频生成任务请求"""
    model_config = {"protected_namespaces": ()}

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


class TaskDetailRequest(BaseModel):
    """任务查询请求"""
    task_id: str


# ========== 接口 ==========

@app.post("/aigc/create")
def create_aigc_task(req: AigcRequest):
    """
    创建AIGC视频生成任务
    请求写入 Redis Stream 队列，返回 task_id 和排队位置
    """
    # 生成唯一任务ID
    task_id = f"aigc-{uuid.uuid4().hex[:12]}"

    # 把请求参数序列化
    task_data = req.model_dump(mode="json")

    # 在 Redis Hash 中创建任务记录
    task_key = f"{TASK_PREFIX}{task_id}"
    r.hset(task_key, mapping={
        "task_id": task_id,
        "status": "queued",
        "params": json.dumps(task_data, ensure_ascii=False),
        "created_at": str(time.time()),
        "result": "",
        "error": "",
    })
    # 任务记录 24 小时后自动过期
    r.expire(task_key, 86400)

    # 写入 Redis Stream 队列
    r.xadd(STREAM_KEY, {"task_id": task_id})

    # 计算排队位置：Stream 中未被消费的消息数量
    position = _get_queue_position(task_id)

    return {
        "task_id": task_id,
        "status": "queued",
        "position": position,
        "message": f"任务已加入队列，前方有 {position - 1} 个任务" if position > 1 else "任务已加入队列，即将处理"
    }


@app.get("/aigc/status/{task_id}")
def get_task_status(task_id: str):
    """
    查询任务状态
    返回任务当前状态、排队位置、结果等
    """
    task_key = f"{TASK_PREFIX}{task_id}"
    task = r.hgetall(task_key)

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")

    result = {
        "task_id": task_id,
        "status": task.get("status", "unknown"),
        "created_at": task.get("created_at", ""),
    }

    # 如果还在排队，返回位置
    if task.get("status") == "queued":
        result["position"] = _get_queue_position(task_id)

    # 返回腾讯云 TaskId（如果有）
    if task.get("tencent_task_id"):
        result["tencent_task_id"] = task["tencent_task_id"]

    # 如果失败，返回错误信息
    if task.get("status") == "failed" and task.get("error"):
        result["error"] = task["error"]

    return result


@app.post("/aigc/task")
def get_task_detail_legacy(req: TaskDetailRequest):
    """
    兼容旧接口：查询腾讯云任务详情
    通过 task_id 查询已完成任务中的腾讯云 TaskId，再查详情
    """
    task_key = f"{TASK_PREFIX}{req.task_id}"
    task = r.hgetall(task_key)

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")

    if task.get("status") != "completed":
        return {
            "task_id": req.task_id,
            "status": task.get("status", "unknown"),
            "message": "任务尚未完成"
        }

    if task.get("result"):
        return json.loads(task["result"])

    raise HTTPException(status_code=404, detail="任务结果不存在")


@app.get("/aigc/queue/info")
def get_queue_info():
    """
    获取队列信息
    返回当前队列长度、正在处理数量、并发上限
    """
    # 队列长度
    queue_length = r.xlen(STREAM_KEY)

    # 当前正在处理的任务数
    active = r.get(ACTIVE_COUNT_KEY)
    active_count = int(active) if active else 0

    # 当前动态阈值
    threshold = r.get(THRESHOLD_KEY)
    current_threshold = int(threshold) if threshold else DEFAULT_THRESHOLD

    return {
        "queue_length": queue_length,
        "active_count": active_count,
        "max_concurrency": current_threshold,
    }


@app.get("/health")
def health_check():
    """健康检查"""
    try:
        r.ping()
        return {"status": "ok", "redis": "connected"}
    except Exception:
        return {"status": "degraded", "redis": "disconnected"}


# ========== 工具函数 ==========

def _get_queue_position(task_id: str) -> int:
    """
    计算任务在队列中的位置
    遍历 Stream 中的消息，找到 task_id 的位置
    """
    try:
        # 读取 Stream 中所有待处理的消息
        messages = r.xrange(STREAM_KEY)
        for idx, (msg_id, data) in enumerate(messages, 1):
            if data.get("task_id") == task_id:
                return idx
        # 如果不在队列中（已被消费），返回 0
        return 0
    except Exception:
        return -1
