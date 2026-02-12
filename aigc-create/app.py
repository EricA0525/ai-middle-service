# -*- coding: utf-8 -*-
"""
腾讯云VOD AIGC视频生成服务 API
核心修复：使用 Redis Lua 脚本保证「检查+入队」的原子性，防止并发超限
"""

import json
import os
import uuid
import time
from typing import Optional

import redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from config import (
    REDIS_URL, STREAM_KEY, TASK_PREFIX, ACTIVE_COUNT_KEY,
    THRESHOLD_KEY, DEFAULT_THRESHOLD, CONSUMER_GROUP,
    MAX_QUEUE_SIZE_KEY, DEFAULT_MAX_QUEUE_SIZE,
)

# ========== Redis 连接 ==========
r = redis.from_url(REDIS_URL, decode_responses=True)

# ========== FastAPI 应用 ==========
app = FastAPI(
    title="腾讯云AIGC视频生成服务",
    description="提供AIGC视频生成任务创建和状态查询接口（带排队功能）",
    version="2.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


# ========== Lua 原子脚本：检查队列容量 + 入队 ==========
# KEYS[1] = STREAM_KEY
# KEYS[2] = ACTIVE_COUNT_KEY
# KEYS[3] = MAX_QUEUE_SIZE_KEY
# ARGV[1] = task_id
# ARGV[2] = default_max_queue_size
# 返回: 1=入队成功, 0=队列繁忙
LUA_ATOMIC_ENQUEUE = r.register_script("""
local stream_key    = KEYS[1]
local active_key    = KEYS[2]
local max_queue_key = KEYS[3]
local task_id       = ARGV[1]
local default_max   = tonumber(ARGV[2])

local max_size = tonumber(redis.call('GET', max_queue_key)) or default_max
local queue_len = redis.call('XLEN', stream_key)
local active_count = tonumber(redis.call('GET', active_key)) or 0
local waiting = queue_len - active_count
if waiting < 0 then waiting = 0 end

if waiting >= max_size then
    return 0
end

redis.call('XADD', stream_key, '*', 'task_id', task_id)
return 1
""")


# ========== 统一响应模型 ==========

class AigcCreateResponse(BaseModel):
    """创建任务统一响应: queued / busy / rejected"""
    task_id: str
    status: str
    position: Optional[int] = None
    created_at: str
    message: str


class AigcStatusResponse(BaseModel):
    """任务状态统一响应: queued / processing / completed / failed / busy / rejected"""
    task_id: str
    status: str
    position: Optional[int] = None
    created_at: str
    message: str
    tencent_task_id: Optional[str] = None
    error: Optional[str] = None
    result: Optional[str] = None


# ========== 请求模型 ==========

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


# ========== 工具函数 ==========

def _save_task_hash(task_id: str, status: str, req: AigcRequest, created_at: str,
                    error: str = "", ttl: int = 86400):
    """写入/更新任务 Hash"""
    task_key = f"{TASK_PREFIX}{task_id}"
    r.hset(task_key, mapping={
        "task_id": task_id,
        "status": status,
        "params": json.dumps(req.model_dump(mode="json"), ensure_ascii=False),
        "created_at": created_at,
        "result": "",
        "error": error,
    })
    r.expire(task_key, ttl)


def _get_queue_position(task_id: str) -> int:
    """计算任务在队列中的位置"""
    try:
        messages = r.xrange(STREAM_KEY)
        for idx, (msg_id, data) in enumerate(messages, 1):
            if data.get("task_id") == task_id:
                return idx
        return 0
    except Exception:
        return -1


# ========== 接口 ==========

@app.post("/aigc/create", response_model=AigcCreateResponse)
def create_aigc_task(req: AigcRequest):
    """
    创建AIGC视频生成任务（原子性防并发）

    返回三种状态:
      1. queued   — 成功进入队列
      2. busy     — 队列繁忙
      3. rejected — 入队异常
    """
    task_id = f"aigc-{uuid.uuid4().hex[:12]}"
    now = str(time.time())

    # ---- 原子性检查 + 入队（Lua 脚本） ----
    try:
        result = LUA_ATOMIC_ENQUEUE(
            keys=[STREAM_KEY, ACTIVE_COUNT_KEY, MAX_QUEUE_SIZE_KEY],
            args=[task_id, DEFAULT_MAX_QUEUE_SIZE],
        )
    except Exception as e:
        _save_task_hash(task_id, "rejected", req, now,
                        error=f"入队失败：{str(e)}", ttl=3600)
        return AigcCreateResponse(
            task_id=task_id, status="rejected", position=None,
            created_at=now, message=f"任务创建失败，请重试：{str(e)}",
        )

    # ---- Lua 返回 0 → 队列繁忙 ----
    if result == 0:
        _save_task_hash(task_id, "busy", req, now,
                        error="当前服务器繁忙，请稍后再提交任务", ttl=3600)
        return AigcCreateResponse(
            task_id=task_id, status="busy", position=None,
            created_at=now, message="当前服务器繁忙，请稍后再提交任务",
        )

    # ---- 入队成功 ----
    _save_task_hash(task_id, "queued", req, now, ttl=86400)
    position = _get_queue_position(task_id)

    return AigcCreateResponse(
        task_id=task_id, status="queued", position=position,
        created_at=now,
        message=(f"任务已加入队列，前方有 {position - 1} 个任务"
                 if position > 1 else "任务已加入队列，即将处理"),
    )


@app.get("/aigc/status/{task_id}", response_model=AigcStatusResponse)
def get_task_status(task_id: str):
    """
    查询任务状态
    状态流转: queued → processing → completed / failed
             busy / rejected（终态）
    """
    task_key = f"{TASK_PREFIX}{task_id}"
    task = r.hgetall(task_key)

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")

    status = task.get("status", "unknown")
    created_at = task.get("created_at", "")

    resp = AigcStatusResponse(
        task_id=task_id, status=status, created_at=created_at, message="",
    )

    if status == "queued":
        position = _get_queue_position(task_id)
        resp.position = position
        resp.message = (f"排队中，前方有 {position - 1} 个任务"
                        if position > 1 else "排队中，即将处理")

    elif status == "processing":
        resp.message = "任务正在处理中"
        resp.tencent_task_id = task.get("tencent_task_id")

    elif status == "completed":
        resp.message = "任务已完成"
        resp.tencent_task_id = task.get("tencent_task_id")
        resp.result = task.get("result") or None

    elif status == "failed":
        resp.message = task.get("error", "任务处理失败")
        resp.error = task.get("error") or None
        resp.tencent_task_id = task.get("tencent_task_id")

    elif status == "busy":
        resp.message = task.get("error", "当前服务器繁忙，请稍后再提交任务")

    elif status == "rejected":
        resp.message = task.get("error", "任务入队失败，请重试")
        resp.error = task.get("error") or None

    else:
        resp.message = "未知状态"

    return resp


@app.post("/aigc/task")
def get_task_detail(req: TaskDetailRequest):
    """查询AIGC视频任务详情（腾讯云VOD DescribeTaskDetail）"""
    from tencentcloud.common import credential
    from tencentcloud.common.profile.http_profile import HttpProfile
    from tencentcloud.common.profile.client_profile import ClientProfile
    from tencentcloud.vod.v20180717 import vod_client, models
    from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException

    secret_id = os.getenv("TENCENTCLOUD_SECRET_ID")
    secret_key = os.getenv("TENCENTCLOUD_SECRET_KEY")
    if not secret_id or not secret_key:
        raise HTTPException(status_code=500, detail="Missing credentials")
    try:
        cred = credential.Credential(secret_id, secret_key)
        httpProfile = HttpProfile()
        httpProfile.endpoint = "vod.tencentcloudapi.com"
        clientProfile = ClientProfile()
        clientProfile.httpProfile = httpProfile
        client = vod_client.VodClient(cred, "", clientProfile)
        request = models.DescribeTaskDetailRequest()
        params = {"TaskId": req.task_id, "SubAppId": 1320866336}
        request.from_json_string(json.dumps(params))
        resp = client.DescribeTaskDetail(request)
        return json.loads(resp.to_json_string())
    except TencentCloudSDKException as err:
        raise HTTPException(status_code=500, detail=str(err))


@app.get("/aigc/queue/info")
def get_queue_info():
    """获取队列信息"""
    queue_length = r.xlen(STREAM_KEY)
    active = r.get(ACTIVE_COUNT_KEY)
    active_count = int(active) if active else 0
    threshold = r.get(THRESHOLD_KEY)
    current_threshold = int(threshold) if threshold else DEFAULT_THRESHOLD
    max_size = r.get(MAX_QUEUE_SIZE_KEY)
    max_queue_size = int(max_size) if max_size else DEFAULT_MAX_QUEUE_SIZE
    waiting_count = max(0, queue_length - active_count)

    return {
        "queue_length": queue_length,
        "active_count": active_count,
        "waiting_count": waiting_count,
        "max_concurrency": current_threshold,
        "max_queue_size": max_queue_size,
    }


@app.get("/health")
def health_check():
    """健康检查"""
    try:
        r.ping()
        return {"status": "ok", "redis": "connected"}
    except Exception:
        return {"status": "degraded", "redis": "disconnected"}
