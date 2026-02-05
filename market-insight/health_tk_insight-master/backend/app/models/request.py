"""
Market Insight Agent - Request Models
======================================
API 请求数据模型定义。

设计思想：
1. 使用 Pydantic 进行数据验证
2. 明确的字段描述和示例，自动生成 API 文档
3. 类型安全，编译时即可发现类型错误
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class BrandHealthRequest(BaseModel):
    """品牌健康度诊断请求模型"""
    
    brand_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="目标分析品牌名称",
        json_schema_extra={"example": "AOS"},
    )
    
    competitors: Optional[List[str]] = Field(
        default=None,
        description="推荐竞品列表",
        json_schema_extra={"example": ["BrandX", "BrandY", "BrandZ"]},
    )
    
    region: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="目标分析地区，用于地区针对性决策",
        json_schema_extra={"example": "中国大陆"},
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "brand_name": "AOS",
                "competitors": ["BrandX", "BrandY", "BrandZ"],
                "region": "中国大陆",
            }
        }


class TikTokInsightRequest(BaseModel):
    """TikTok 社媒洞察请求模型"""
    
    category: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="商品品类名称",
        json_schema_extra={"example": "美妆"},
    )
    
    selling_points: List[str] = Field(
        ...,
        min_length=1,
        description="商品卖点列表",
        json_schema_extra={"example": ["长效控油", "便携式设计"]},
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "category": "美妆",
                "selling_points": ["长效控油", "便携式设计"],
            }
        }
