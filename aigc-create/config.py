# -*- coding: utf-8 -*-
"""
共享配置模块
API 和 Worker 都会用到的配置项
"""
import os
# Redis 配置
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
# 腾讯云配置
TENCENTCLOUD_SECRET_ID = os.getenv("TENCENTCLOUD_SECRET_ID", "")
TENCENTCLOUD_SECRET_KEY = os.getenv("TENCENTCLOUD_SECRET_KEY", "")
VOD_SUBAPP_ID = int(os.getenv("VOD_SUBAPP_ID", "1320866336"))
TENCENT_CLOUD_TIMEOUT = int(os.getenv("TENCENT_CLOUD_TIMEOUT", "1800"))
# 并发控制配置
DEFAULT_THRESHOLD = int(os.getenv("DEFAULT_THRESHOLD", "10"))
MAX_THRESHOLD = int(os.getenv("MAX_THRESHOLD", "10"))
MIN_THRESHOLD = int(os.getenv("MIN_THRESHOLD", "2"))
THRESHOLD_DECREASE = int(os.getenv("THRESHOLD_DECREASE", "2"))
THRESHOLD_INCREASE = int(os.getenv("THRESHOLD_INCREASE", "1"))
RECOVERY_INTERVAL = int(os.getenv("RECOVERY_INTERVAL", "60"))
# Redis Key
STREAM_KEY = "aigc:queue"
TASK_PREFIX = "aigc:task:"
ACTIVE_COUNT_KEY = "aigc:active_count"
THRESHOLD_KEY = "aigc:current_threshold"
LAST_ERROR_KEY = "aigc:last_limit_error_time"
CONSUMER_GROUP = "aigc-workers"
MAX_QUEUE_SIZE_KEY = "aigc:max_queue_size"
DEFAULT_MAX_QUEUE_SIZE = 10
