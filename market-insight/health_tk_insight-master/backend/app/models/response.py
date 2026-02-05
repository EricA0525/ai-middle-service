"""
Market Insight Agent - Response Models
=======================================
API 响应数据模型定义。

设计思想：
1. 统一响应格式：{ success: bool, data: {...} }
2. 明确的状态区分：processing / completed / failed
3. 完整的类型定义，便于前端对接
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class BaseResponse(BaseModel):
    """基础响应模型"""
    
    success: bool = Field(
        ...,
        description="请求是否成功",
    )
    
    data: Dict[str, Any] = Field(
        default_factory=dict,
        description="响应数据",
    )


class TaskCreatedResponse(BaseResponse):
    """任务创建响应模型"""
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "data": {
                    "task_id": "task_abc123",
                    "status": "processing",
                },
            }
        }


class TaskStatusResponse(BaseResponse):
    """任务状态查询响应模型
    
    响应内容根据任务状态不同而变化：
    
    1. 处理中 (processing):
    {
        "success": true,
        "data": {
            "task_id": "task_abc123",
            "status": "processing",
            "progress": 60,
            "message": "正在采集小红书数据..."
        }
    }
    
    2. 已完成 (completed):
    {
        "success": true,
        "data": {
            "task_id": "task_abc123",
            "status": "completed",
            "report_type": "brand_health",
            "report_url": "/api/v1/tasks/task_abc123/report",
            "created_at": "2026-02-02T12:00:00Z",
            "completed_at": "2026-02-02T12:02:15Z"
        }
    }
    
    3. 失败 (failed):
    {
        "success": false,
        "data": {
            "task_id": "task_abc123",
            "status": "failed",
            "error": "外部API调用失败",
            "details": "Tavily API 超时"
        }
    }
    """
    pass


class ErrorResponse(BaseModel):
    """错误响应模型"""
    
    success: bool = Field(default=False)
    error: str = Field(..., description="错误信息")
    details: Optional[str] = Field(default=None, description="错误详情")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": False,
                "error": "请求参数错误",
                "details": "brand_name 不能为空",
            }
        }
