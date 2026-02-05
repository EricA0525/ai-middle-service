"""
Market Insight Agent - Models Package
======================================
数据模型包，导出所有模型类。
"""

from app.models.request import BrandHealthRequest, TikTokInsightRequest
from app.models.response import (
    BaseResponse,
    ErrorResponse,
    TaskCreatedResponse,
    TaskStatusResponse,
)
from app.models.task import Task, TaskStatus, TaskType

__all__ = [
    # Request Models
    "BrandHealthRequest",
    "TikTokInsightRequest",
    # Response Models
    "BaseResponse",
    "ErrorResponse",
    "TaskCreatedResponse",
    "TaskStatusResponse",
    # Task Models
    "Task",
    "TaskStatus",
    "TaskType",
]
