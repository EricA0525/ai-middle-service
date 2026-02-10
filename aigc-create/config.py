# -*- coding: utf-8 -*-
"""
共享配置模块
提供Redis连接、腾讯云配置、并发控制等参数
"""

import os
import redis
from typing import Optional

class Config:
    """应用配置类"""
    
    # Redis配置
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
    REDIS_PASSWORD: Optional[str] = os.getenv("REDIS_PASSWORD")
    
    # Redis Stream配置
    STREAM_KEY: str = "aigc:tasks"  # 任务队列Stream key
    CONSUMER_GROUP: str = "aigc-workers"  # 消费者组名称
    CONSUMER_NAME: str = os.getenv("CONSUMER_NAME", "worker-1")  # 消费者名称
    
    # 任务状态存储
    TASK_STATUS_PREFIX: str = "aigc:task:"  # 任务状态hash key前缀
    ACTIVE_COUNT_KEY: str = "aigc:active_count"  # 活跃任务计数器
    THRESHOLD_KEY: str = "aigc:threshold"  # 当前并发阈值
    LAST_ERROR_TIME_KEY: str = "aigc:last_error_time"  # 上次错误时间
    
    # 并发控制配置
    DEFAULT_THRESHOLD: int = int(os.getenv("DEFAULT_THRESHOLD", "12"))  # 默认并发阈值
    MAX_THRESHOLD: int = int(os.getenv("MAX_THRESHOLD", "12"))  # 最大并发阈值
    MIN_THRESHOLD: int = int(os.getenv("MIN_THRESHOLD", "2"))  # 最小并发阈值
    THRESHOLD_DECREASE: int = int(os.getenv("THRESHOLD_DECREASE", "2"))  # 触发限流时降低值
    THRESHOLD_INCREASE: int = int(os.getenv("THRESHOLD_INCREASE", "1"))  # 恢复时增加值
    RECOVERY_INTERVAL: int = int(os.getenv("RECOVERY_INTERVAL", "60"))  # 阈值恢复间隔(秒)
    
    # Worker配置
    WORKER_POLL_INTERVAL: int = int(os.getenv("WORKER_POLL_INTERVAL", "2"))  # worker轮询间隔(秒)
    WORKER_BLOCK_TIME: int = int(os.getenv("WORKER_BLOCK_TIME", "5000"))  # Redis阻塞读取时间(毫秒)
    
    # 腾讯云配置
    TENCENTCLOUD_SECRET_ID: str = os.getenv("TENCENTCLOUD_SECRET_ID", "")
    TENCENTCLOUD_SECRET_KEY: str = os.getenv("TENCENTCLOUD_SECRET_KEY", "")
    VOD_SUBAPP_ID: int = int(os.getenv("VOD_SUBAPP_ID", "1320866336"))
    
    @classmethod
    def get_redis_client(cls) -> redis.Redis:
        """
        创建Redis客户端连接
        
        Returns:
            Redis客户端实例
        """
        return redis.Redis(
            host=cls.REDIS_HOST,
            port=cls.REDIS_PORT,
            db=cls.REDIS_DB,
            password=cls.REDIS_PASSWORD,
            decode_responses=True  # 自动解码返回值为字符串
        )
