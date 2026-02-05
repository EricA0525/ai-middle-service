"""
Market Insight Agent - Task Model
==================================
任务数据模型，用于任务状态管理。

设计思想：
1. 完整的任务生命周期管理
2. 支持进度追踪
3. 可持久化到数据库
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """任务状态枚举"""
    
    PENDING = "pending"        # 等待处理
    PROCESSING = "processing"  # 处理中
    COMPLETED = "completed"    # 已完成
    FAILED = "failed"          # 失败


class TaskType(str, Enum):
    """任务类型枚举"""
    
    BRAND_HEALTH = "brand_health"      # 品牌健康度诊断
    TIKTOK_INSIGHT = "tiktok_insight"  # TikTok 社媒洞察


class Task(BaseModel):
    """任务模型"""
    
    task_id: str = Field(..., description="任务唯一标识")
    task_type: TaskType = Field(..., description="任务类型")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="任务状态")
    
    # 输入参数
    params: Dict[str, Any] = Field(default_factory=dict, description="任务参数")
    
    # 进度信息
    progress: int = Field(default=0, ge=0, le=100, description="进度百分比")
    message: Optional[str] = Field(default=None, description="当前步骤描述")
    
    # 结果
    result: Optional[str] = Field(default=None, description="生成的 HTML 报告内容")
    
    # 错误信息
    error_message: Optional[str] = Field(default=None, description="错误信息")
    error_details: Optional[str] = Field(default=None, description="错误详情")
    
    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    started_at: Optional[datetime] = Field(default=None, description="开始处理时间")
    completed_at: Optional[datetime] = Field(default=None, description="完成时间")
    
    def start(self) -> None:
        """开始处理任务"""
        self.status = TaskStatus.PROCESSING
        self.started_at = datetime.utcnow()
        self.progress = 0
        self.message = "任务开始处理..."
    
    def update_progress(self, progress: int, message: str) -> None:
        """更新任务进度"""
        self.progress = min(max(progress, 0), 100)
        self.message = message
    
    def complete(self, result: str) -> None:
        """完成任务"""
        self.status = TaskStatus.COMPLETED
        self.result = result
        self.progress = 100
        self.message = "任务完成"
        self.completed_at = datetime.utcnow()
    
    def fail(self, error_message: str, error_details: Optional[str] = None) -> None:
        """任务失败"""
        self.status = TaskStatus.FAILED
        self.error_message = error_message
        self.error_details = error_details
        self.completed_at = datetime.utcnow()
