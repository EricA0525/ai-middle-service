# -*- coding: utf-8 -*-
"""
AIGC 任务消费 Worker
从 Redis Stream 消费任务 → 控制并发 → 调腾讯云 API → 结果写回 Redis
"""

import hashlib
import hmac
import json
import os
import signal
import sys
import time
from datetime import datetime
from http.client import HTTPSConnection

import redis

from config import (
    REDIS_URL, STREAM_KEY, TASK_PREFIX, ACTIVE_COUNT_KEY,
    THRESHOLD_KEY, LAST_ERROR_KEY, CONSUMER_GROUP,
    TENCENTCLOUD_SECRET_ID, TENCENTCLOUD_SECRET_KEY,
    VOD_SUBAPP_ID, TENCENT_CLOUD_TIMEOUT,
    DEFAULT_THRESHOLD, MAX_THRESHOLD, MIN_THRESHOLD,
    THRESHOLD_DECREASE, THRESHOLD_INCREASE, RECOVERY_INTERVAL,
)

# ========== Redis 连接 ==========
r = redis.from_url(REDIS_URL, decode_responses=True)

# Worker 配置
CONSUMER_NAME = os.getenv("CONSUMER_NAME", "worker-1")
POLL_INTERVAL = int(os.getenv("WORKER_POLL_INTERVAL", "2"))
BLOCK_TIME = int(os.getenv("WORKER_BLOCK_TIME", "5000"))  # 毫秒

# 优雅退出
running = True

def handle_signal(signum, frame):
    global running
    print(f"[INFO] 收到信号 {signum}，准备退出...")
    running = False

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)


# ========== 腾讯云 API 调用 ==========

def tc3_sign(key: bytes, msg: str) -> bytes:
    """TC3 HMAC-SHA256 签名"""
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def call_tencent_create_aigc(task_params: dict) -> dict:
    """
    调用腾讯云 CreateAigcVideoTask 接口
    返回腾讯云的原始响应
    """
    secret_id = TENCENTCLOUD_SECRET_ID
    secret_key = TENCENTCLOUD_SECRET_KEY

    if not secret_id or not secret_key:
        return {"error": "Missing credentials"}

    service = "vod"
    host = "vod.tencentcloudapi.com"
    version = "2018-07-17"
    action = "CreateAigcVideoTask"

    # 构建请求体
    payload_data = {
        "SubAppId": VOD_SUBAPP_ID,
        "ModelName": task_params.get("model_name", "Hailuo"),
        "ModelVersion": task_params.get("model_version", "2.3"),
        "Prompt": task_params.get("prompt", ""),
    }

    if task_params.get("file_id"):
        payload_data["FileInfos"] = [
            {"ReferenceType": "File", "FileId": task_params["file_id"]}
        ]

    if task_params.get("enhance_prompt"):
        payload_data["EnhancePrompt"] = task_params["enhance_prompt"]

    output_config = {}
    if task_params.get("duration") is not None:
        output_config["Duration"] = task_params["duration"]
    if task_params.get("resolution"):
        output_config["Resolution"] = task_params["resolution"]
    if task_params.get("aspect_ratio"):
        output_config["AspectRatio"] = task_params["aspect_ratio"]
    if task_params.get("enhance_switch"):
        output_config["EnhanceSwitch"] = task_params["enhance_switch"]
    if task_params.get("frame_interpolate"):
        output_config["FrameInterpolate"] = task_params["frame_interpolate"]
    if task_params.get("audio_generation"):
        output_config["AudioGeneration"] = task_params["audio_generation"]
    output_config["PersonGeneration"] = "AllowAdult"

    if output_config:
        payload_data["OutputConfig"] = output_config

    if task_params.get("tasks_priority") is not None:
        payload_data["TasksPriority"] = task_params["tasks_priority"]
    if task_params.get("scene_type"):
        payload_data["SceneType"] = task_params["scene_type"]

    payload = json.dumps(payload_data)
    print(f"[DEBUG] CreateAigcVideoTask payload: {payload}")

    # TC3 签名
    algorithm = "TC3-HMAC-SHA256"
    timestamp = int(time.time())
    date = datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")

    ct = "application/json; charset=utf-8"
    canonical_headers = f"content-type:{ct}\nhost:{host}\nx-tc-action:{action.lower()}\n"
    signed_headers = "content-type;host;x-tc-action"
    hashed_request_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = f"POST\n/\n\n{canonical_headers}\n{signed_headers}\n{hashed_request_payload}"

    credential_scope = f"{date}/{service}/tc3_request"
    hashed_canonical_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    string_to_sign = f"{algorithm}\n{timestamp}\n{credential_scope}\n{hashed_canonical_request}"

    secret_date = tc3_sign(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = tc3_sign(secret_date, service)
    secret_signing = tc3_sign(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"{algorithm} Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    headers = {
        "Authorization": authorization,
        "Content-Type": ct,
        "Host": host,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": version,
    }

    try:
        conn = HTTPSConnection(host, timeout=TENCENT_CLOUD_TIMEOUT)
        conn.request("POST", "/", headers=headers, body=payload.encode("utf-8"))
        resp = conn.getresponse()
        result = json.loads(resp.read().decode("utf-8"))
        return result
    except Exception as e:
        return {"error": str(e)}


# ========== 并发控制 ==========

def get_active_count() -> int:
    """获取当前正在处理的任务数"""
    val = r.get(ACTIVE_COUNT_KEY)
    return int(val) if val else 0


def get_current_threshold() -> int:
    """获取当前动态阈值"""
    val = r.get(THRESHOLD_KEY)
    return int(val) if val else DEFAULT_THRESHOLD


def decrease_threshold():
    """报错后降低阈值"""
    current = get_current_threshold()
    new_val = max(MIN_THRESHOLD, current - THRESHOLD_DECREASE)
    r.set(THRESHOLD_KEY, new_val)
    r.set(LAST_ERROR_KEY, str(time.time()))
    print(f"[WARN] 并发阈值降低: {current} → {new_val}")


def try_recover_threshold():
    """如果一段时间没报错，尝试恢复阈值"""
    last_error = r.get(LAST_ERROR_KEY)
    if not last_error:
        return

    elapsed = time.time() - float(last_error)
    if elapsed > RECOVERY_INTERVAL:
        current = get_current_threshold()
        if current < MAX_THRESHOLD:
            new_val = min(MAX_THRESHOLD, current + THRESHOLD_INCREASE)
            r.set(THRESHOLD_KEY, new_val)
            r.set(LAST_ERROR_KEY, str(time.time()))
            print(f"[INFO] 并发阈值恢复: {current} → {new_val}")


# ========== 任务处理 ==========

def process_task(task_id: str):
    """
    处理单个任务：调腾讯云 API，把结果写回 Redis
    """
    task_key = f"{TASK_PREFIX}{task_id}"

    # 读取任务参数
    params_json = r.hget(task_key, "params")
    if not params_json:
        print(f"[ERROR] 任务 {task_id} 参数不存在")
        r.hset(task_key, "status", "failed")
        r.hset(task_key, "error", "任务参数不存在")
        return

    task_params = json.loads(params_json)

    # 更新状态为处理中
    r.hset(task_key, "status", "processing")

    # 增加活跃计数
    r.incr(ACTIVE_COUNT_KEY)

    try:
        # 调用腾讯云
        result = call_tencent_create_aigc(task_params)

        # 检查是否触发并发限制
        response = result.get("Response", {})
        error_info = response.get("Error", {})
        error_code = error_info.get("Code", "")
        error_message = error_info.get("Message", "")

        if "RequestLimitExceeded" in error_code or "RequestLimitExceeded" in error_message:
            # 触发限制 → 降低阈值，任务重新排队
            print(f"[WARN] 任务 {task_id} 触发并发限制，重新排队")
            decrease_threshold()
            r.hset(task_key, "status", "queued")
            r.xadd(STREAM_KEY, {"task_id": task_id})
            return

        if error_code:
            # 其他错误
            print(f"[ERROR] 任务 {task_id} 失败: {error_code} - {error_message}")
            r.hset(task_key, "status", "failed")
            r.hset(task_key, "error", f"{error_code}: {error_message}")
            return

        if "error" in result:
            # 网络/连接错误
            print(f"[ERROR] 任务 {task_id} 请求失败: {result['error']}")
            r.hset(task_key, "status", "failed")
            r.hset(task_key, "error", result["error"])
            return

        # 成功：提取腾讯云的 TaskId
        tencent_task_id = response.get("TaskId", "")
        print(f"[INFO] 任务 {task_id} 提交成功，腾讯云TaskId: {tencent_task_id}")
        r.hset(task_key, mapping={
            "status": "completed",
            "result": json.dumps(result, ensure_ascii=False),
            "tencent_task_id": tencent_task_id,
        })

    except Exception as e:
        print(f"[ERROR] 任务 {task_id} 异常: {e}")
        r.hset(task_key, "status", "failed")
        r.hset(task_key, "error", str(e))

    finally:
        # 减少活跃计数
        r.decr(ACTIVE_COUNT_KEY)
        # 防止计数变为负数
        if int(r.get(ACTIVE_COUNT_KEY) or 0) < 0:
            r.set(ACTIVE_COUNT_KEY, 0)


# ========== 主循环 ==========

def init_consumer_group():
    """初始化 Consumer Group，如果已存在则忽略"""
    try:
        r.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True)
        print(f"[INFO] 创建 Consumer Group: {CONSUMER_GROUP}")
    except redis.exceptions.ResponseError as e:
        if "BUSYGROUP" in str(e):
            print(f"[INFO] Consumer Group 已存在: {CONSUMER_GROUP}")
        else:
            raise


def main():
    """Worker 主循环"""
    print(f"[INFO] Worker 启动: {CONSUMER_NAME}")
    print(f"[INFO] Redis: {REDIS_URL}")
    print(f"[INFO] 初始并发阈值: {DEFAULT_THRESHOLD}")

    # 初始化
    init_consumer_group()

    # 初始化阈值
    if not r.exists(THRESHOLD_KEY):
        r.set(THRESHOLD_KEY, DEFAULT_THRESHOLD)

    # 初始化活跃计数
    if not r.exists(ACTIVE_COUNT_KEY):
        r.set(ACTIVE_COUNT_KEY, 0)

    while running:
        try:
            # 尝试恢复阈值
            try_recover_threshold()

            # 检查并发
            active = get_active_count()
            threshold = get_current_threshold()

            if active >= threshold:
                # 并发已满，等待
                time.sleep(POLL_INTERVAL)
                continue

            # 从 Stream 读取任务
            messages = r.xreadgroup(
                CONSUMER_GROUP, CONSUMER_NAME,
                {STREAM_KEY: ">"},
                count=1,
                block=BLOCK_TIME,
            )

            if not messages:
                continue

            for stream_name, stream_messages in messages:
                for msg_id, data in stream_messages:
                    task_id = data.get("task_id")
                    if not task_id:
                        r.xack(STREAM_KEY, CONSUMER_GROUP, msg_id)
                        r.xdel(STREAM_KEY, msg_id)
                        continue

                    print(f"[INFO] 消费任务: {task_id} (活跃: {active}/{threshold})")

                    # 处理任务
                    process_task(task_id)

                    # 确认消息
                    r.xack(STREAM_KEY, CONSUMER_GROUP, msg_id)
                    r.xdel(STREAM_KEY, msg_id) 

        except redis.exceptions.ConnectionError as e:
            print(f"[ERROR] Redis 连接失败: {e}，{POLL_INTERVAL}秒后重试...")
            time.sleep(POLL_INTERVAL)

        except Exception as e:
            print(f"[ERROR] Worker 异常: {e}")
            time.sleep(POLL_INTERVAL)

    print("[INFO] Worker 已停止")


if __name__ == "__main__":
    main()
