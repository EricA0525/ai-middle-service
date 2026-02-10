# -*- coding: utf-8 -*-
"""
AIGC Worker - Redis Stream消费者
负责从Redis Stream读取任务，控制并发，调用腾讯云API
"""

import os
import sys
import json
import time
import hashlib
import hmac
import logging
from datetime import datetime
from http.client import HTTPSConnection
from typing import Dict, Any, Optional
import redis

from config import Config

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AigcWorker:
    """AIGC任务处理Worker"""
    
    def __init__(self):
        """初始化Worker"""
        self.redis_client = Config.get_redis_client()
        self.running = True
        
        # 初始化消费者组（如果不存在）
        self._init_consumer_group()
        
        # 初始化阈值
        if not self.redis_client.exists(Config.THRESHOLD_KEY):
            self.redis_client.set(Config.THRESHOLD_KEY, Config.DEFAULT_THRESHOLD)
        
        # 初始化活跃计数
        if not self.redis_client.exists(Config.ACTIVE_COUNT_KEY):
            self.redis_client.set(Config.ACTIVE_COUNT_KEY, 0)
        
        logger.info(f"Worker initialized: {Config.CONSUMER_NAME}")
    
    def _init_consumer_group(self):
        """初始化Redis Stream消费者组"""
        try:
            # 创建消费者组，从最新消息开始消费
            self.redis_client.xgroup_create(
                Config.STREAM_KEY,
                Config.CONSUMER_GROUP,
                id='0',
                mkstream=True
            )
            logger.info(f"Created consumer group: {Config.CONSUMER_GROUP}")
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.info(f"Consumer group already exists: {Config.CONSUMER_GROUP}")
            else:
                raise
    
    def _sign(self, key: bytes, msg: str) -> bytes:
        """HMAC-SHA256签名"""
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()
    
    def _call_tencent_cloud(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        调用腾讯云API创建AIGC任务
        
        Args:
            task_data: 任务数据
            
        Returns:
            腾讯云API响应
        """
        # 腾讯云API配置
        service = "vod"
        host = "vod.tencentcloudapi.com"
        version = "2018-07-17"
        action = "CreateAigcVideoTask"
        
        # 构建请求体
        payload_data = {
            "SubAppId": Config.VOD_SUBAPP_ID,
            "ModelName": task_data.get("model_name", "Hailuo"),
            "ModelVersion": task_data.get("model_version", "2.3"),
            "Prompt": task_data.get("prompt", "")
        }
        
        # 可选参数
        if task_data.get("file_id"):
            payload_data["FileInfos"] = [{
                "ReferenceType": "File",
                "FileId": task_data["file_id"]
            }]
        
        if task_data.get("enhance_prompt"):
            payload_data["EnhancePrompt"] = task_data["enhance_prompt"]
        
        # 输出配置
        output_config = {}
        
        if task_data.get("duration") is not None:
            output_config["Duration"] = task_data["duration"]
        
        if task_data.get("resolution"):
            output_config["Resolution"] = task_data["resolution"]
        
        if task_data.get("aspect_ratio"):
            output_config["AspectRatio"] = task_data["aspect_ratio"]
        
        if task_data.get("enhance_switch"):
            output_config["EnhanceSwitch"] = task_data["enhance_switch"]
        
        if task_data.get("frame_interpolate"):
            output_config["FrameInterpolate"] = task_data["frame_interpolate"]
        
        if task_data.get("audio_generation"):
            output_config["AudioGeneration"] = task_data["audio_generation"]
        
        output_config["PersonGeneration"] = "AllowAdult"
        
        if output_config:
            payload_data["OutputConfig"] = output_config
        
        if task_data.get("tasks_priority") is not None:
            payload_data["TasksPriority"] = task_data["tasks_priority"]
        
        if task_data.get("scene_type"):
            payload_data["SceneType"] = task_data["scene_type"]
        
        payload = json.dumps(payload_data)
        
        # TC3签名
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
        
        secret_date = self._sign(f"TC3{Config.TENCENTCLOUD_SECRET_KEY}".encode("utf-8"), date)
        secret_service = self._sign(secret_date, service)
        secret_signing = self._sign(secret_service, "tc3_request")
        signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        
        authorization = (f"{algorithm} Credential={Config.TENCENTCLOUD_SECRET_ID}/{credential_scope}, "
                        f"SignedHeaders={signed_headers}, Signature={signature}")
        
        headers = {
            "Authorization": authorization,
            "Content-Type": ct,
            "Host": host,
            "X-TC-Action": action,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Version": version
        }
        
        # 发送请求
        conn = HTTPSConnection(host, timeout=1800)
        conn.request("POST", "/", headers=headers, body=payload.encode("utf-8"))
        resp = conn.getresponse()
        result = json.loads(resp.read().decode("utf-8"))
        
        return result
    
    def _get_current_threshold(self) -> int:
        """获取当前并发阈值"""
        threshold = self.redis_client.get(Config.THRESHOLD_KEY)
        return int(threshold) if threshold else Config.DEFAULT_THRESHOLD
    
    def _get_active_count(self) -> int:
        """获取当前活跃任务数"""
        count = self.redis_client.get(Config.ACTIVE_COUNT_KEY)
        return int(count) if count else 0
    
    def _decrease_threshold(self):
        """降低并发阈值"""
        current = self._get_current_threshold()
        new_threshold = max(Config.MIN_THRESHOLD, current - Config.THRESHOLD_DECREASE)
        self.redis_client.set(Config.THRESHOLD_KEY, new_threshold)
        logger.warning(f"Threshold decreased: {current} -> {new_threshold}")
    
    def _try_recover_threshold(self):
        """尝试恢复阈值"""
        last_error_time = self.redis_client.get(Config.LAST_ERROR_TIME_KEY)
        current_threshold = self._get_current_threshold()
        
        # 如果已经达到最大阈值，无需恢复
        if current_threshold >= Config.MAX_THRESHOLD:
            return
        
        # 如果有错误记录，检查是否超过恢复间隔
        if last_error_time:
            elapsed = time.time() - float(last_error_time)
            if elapsed >= Config.RECOVERY_INTERVAL:
                # 增加阈值
                new_threshold = min(Config.MAX_THRESHOLD, current_threshold + Config.THRESHOLD_INCREASE)
                self.redis_client.set(Config.THRESHOLD_KEY, new_threshold)
                logger.info(f"Threshold recovered: {current_threshold} -> {new_threshold}")
        else:
            # 没有错误记录，直接恢复到最大值
            if current_threshold < Config.MAX_THRESHOLD:
                self.redis_client.set(Config.THRESHOLD_KEY, Config.MAX_THRESHOLD)
                logger.info(f"Threshold restored to max: {Config.MAX_THRESHOLD}")
    
    def _update_task_status(self, task_id: str, status: str, result: Optional[Dict] = None):
        """
        更新任务状态
        
        Args:
            task_id: 任务ID
            status: 状态 (queued/processing/completed/failed)
            result: 结果数据（可选）
        """
        task_key = f"{Config.TASK_STATUS_PREFIX}{task_id}"
        
        data = {
            "task_id": task_id,
            "status": status,
            "updated_at": str(int(time.time()))
        }
        
        if result:
            data["result"] = json.dumps(result, ensure_ascii=False)
        
        self.redis_client.hset(task_key, mapping=data)
        logger.info(f"Task {task_id} status updated: {status}")
    
    def _process_task(self, task_id: str, task_data: Dict[str, Any]) -> bool:
        """
        处理单个任务
        
        Args:
            task_id: 任务ID
            task_data: 任务数据
            
        Returns:
            是否成功处理
        """
        try:
            # 更新状态为processing
            self._update_task_status(task_id, "processing")
            
            # 调用腾讯云API
            logger.info(f"Calling Tencent Cloud API for task {task_id}")
            result = self._call_tencent_cloud(task_data)
            
            # 检查响应
            if "Response" in result:
                response = result["Response"]
                
                # 检查是否有错误
                if "Error" in response:
                    error = response["Error"]
                    error_code = error.get("Code", "")
                    error_msg = error.get("Message", "")
                    
                    logger.error(f"Task {task_id} failed: {error_code} - {error_msg}")
                    
                    # 检查是否是RequestLimitExceeded
                    if error_code == "RequestLimitExceeded":
                        logger.warning(f"Rate limit exceeded for task {task_id}")
                        # 降低阈值
                        self._decrease_threshold()
                        # 记录错误时间
                        self.redis_client.set(Config.LAST_ERROR_TIME_KEY, time.time())
                        # 任务失败，不重新入队（根据需求，可以选择重新入队）
                        self._update_task_status(task_id, "failed", {"error": error_msg})
                        return False
                    else:
                        # 其他错误
                        self._update_task_status(task_id, "failed", {"error": error_msg})
                        return False
                else:
                    # 成功
                    logger.info(f"Task {task_id} completed successfully")
                    self._update_task_status(task_id, "completed", response)
                    return True
            else:
                # 响应格式错误
                logger.error(f"Invalid response format for task {task_id}")
                self._update_task_status(task_id, "failed", {"error": "Invalid response format"})
                return False
                
        except Exception as e:
            logger.error(f"Error processing task {task_id}: {str(e)}", exc_info=True)
            self._update_task_status(task_id, "failed", {"error": str(e)})
            return False
    
    def run(self):
        """运行Worker主循环"""
        logger.info("Worker started")
        
        while self.running:
            try:
                # 尝试恢复阈值
                self._try_recover_threshold()
                
                # 检查当前活跃数
                active_count = self._get_active_count()
                threshold = self._get_current_threshold()
                
                logger.debug(f"Active: {active_count}/{threshold}")
                
                # 如果超过阈值，等待后继续
                if active_count >= threshold:
                    logger.info(f"Active count ({active_count}) >= threshold ({threshold}), waiting...")
                    time.sleep(Config.WORKER_POLL_INTERVAL)
                    continue
                
                # 从Stream读取任务
                messages = self.redis_client.xreadgroup(
                    Config.CONSUMER_GROUP,
                    Config.CONSUMER_NAME,
                    {Config.STREAM_KEY: '>'},
                    count=1,
                    block=Config.WORKER_BLOCK_TIME
                )
                
                if not messages:
                    # 没有新消息
                    continue
                
                # 处理消息
                for stream_name, message_list in messages:
                    for message_id, message_data in message_list:
                        try:
                            # 增加活跃计数
                            self.redis_client.incr(Config.ACTIVE_COUNT_KEY)
                            
                            # 解析任务数据
                            task_id = message_data.get("task_id")
                            task_data_str = message_data.get("task_data", "{}")
                            task_data = json.loads(task_data_str)
                            
                            logger.info(f"Processing task: {task_id}")
                            
                            # 处理任务
                            success = self._process_task(task_id, task_data)
                            
                            # 确认消息
                            self.redis_client.xack(Config.STREAM_KEY, Config.CONSUMER_GROUP, message_id)
                            logger.info(f"Message {message_id} acknowledged")
                            
                        except Exception as e:
                            logger.error(f"Error handling message {message_id}: {str(e)}", exc_info=True)
                        finally:
                            # 减少活跃计数
                            self.redis_client.decr(Config.ACTIVE_COUNT_KEY)
                
            except KeyboardInterrupt:
                logger.info("Worker stopping...")
                self.running = False
            except Exception as e:
                logger.error(f"Worker error: {str(e)}", exc_info=True)
                time.sleep(Config.WORKER_POLL_INTERVAL)
        
        logger.info("Worker stopped")


if __name__ == "__main__":
    # 加载环境变量
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    
    worker = AigcWorker()
    worker.run()
