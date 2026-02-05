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
        json_schema_extra={"example": "索尼"},
    )
    
    category: Optional[str] = Field(
        default=None,
        max_length=100,
        description="品牌下的具体品类（可选）。当品牌涉及多个品类时建议指定，如'索尼'可指定'耳机'或'游戏机'",
        json_schema_extra={"example": "耳机"},
    )
    
    competitors: Optional[List[str]] = Field(
        default=None,
        description="推荐竞品列表",
        json_schema_extra={"example": ["Bose", "Apple AirPods"]},
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
                "brand_name": "索尼",
                "category": "耳机",
                "competitors": ["Bose", "Apple AirPods"],
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
