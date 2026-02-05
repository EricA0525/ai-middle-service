"""
Market Insight Agent - Douyin (抖音) Client
===========================================
抖音 API 客户端，用于获取视频热度和带货数据。

接口预留：
1. 搜索热门视频
2. 获取视频详情
3. 获取达人带货数据
4. 获取品类趋势数据

状态：🚧 预留接口，等待真实 API 接入

后续开发方向：
1. 对接公司内部抖音数据 API
2. 实现视频内容分析
3. 添加带货效果分析
"""

from typing import Any, Dict, List, Optional

from loguru import logger

from app.config import settings
from app.data_sources.base import BaseDataSource


class DouyinClient(BaseDataSource):
    """
    抖音 API 客户端
    
    当前状态：预留接口，使用模拟数据
    """
    
    def __init__(self):
        super().__init__(
            name="douyin",
            api_url=settings.douyin_api_url,
            api_key=settings.douyin_api_key,
        )
    
    async def search(
        self,
        query: str,
        video_type: str = "all",
        sort_by: str = "hot",
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        搜索抖音视频
        
        Args:
            query: 搜索关键词
            video_type: 视频类型
            sort_by: 排序方式 ("hot" | "latest")
            limit: 返回数量
            
        Returns:
            视频列表
        """
        logger.info(f"Douyin search: {query}")
        
        # TODO: 对接真实 API
        
        logger.warning("Douyin API not configured, returning mock data")
        return self._get_mock_videos(query, limit)
    
    async def get_detail(self, video_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        """
        获取视频详情
        
        Args:
            video_id: 视频 ID
            
        Returns:
            视频详情
        """
        logger.info(f"Douyin get video detail: {video_id}")
        
        # TODO: 实现真实 API 调用
        
        return None
    
    async def get_trending_videos(
        self,
        category: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        获取热门视频
        
        Args:
            category: 视频品类
            limit: 返回数量
            
        Returns:
            热门视频列表
        """
        logger.info(f"Douyin get trending videos: {category}")
        
        # TODO: 实现真实 API 调用
        
        return self._get_mock_trending(category, limit)
    
    async def get_ecommerce_data(
        self,
        product_category: str,
        date_range: int = 30,
    ) -> Dict[str, Any]:
        """
        获取电商带货数据
        
        Args:
            product_category: 商品品类
            date_range: 时间范围（天）
            
        Returns:
            带货数据
        """
        logger.info(f"Douyin get ecommerce data: {product_category}")
        
        # TODO: 实现真实 API 调用
        
        return self._get_mock_ecommerce_data(product_category)
    
    # ========== 模拟数据 ==========
    
    def _get_mock_videos(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """生成模拟视频数据"""
        return [
            {
                "video_id": f"dy_{i}",
                "title": f"#{query} 超实用分享",
                "description": f"今天给大家分享一下{query}的使用心得...",
                "author": {
                    "user_id": f"author_{i}",
                    "nickname": f"抖音达人{i}",
                    "followers": 50000 + i * 10000,
                    "is_verified": i % 2 == 0,
                },
                "stats": {
                    "views": 100000 + i * 20000,
                    "likes": 5000 + i * 1000,
                    "comments": 320 + i * 50,
                    "shares": 150 + i * 30,
                },
                "duration": 45 + i * 10,
                "cover_url": "https://example.com/cover.jpg",
                "tags": [query, "好物推荐"],
                "created_at": "2026-01-18T15:00:00Z",
            }
            for i in range(min(limit, 5))
        ]
    
    def _get_mock_trending(self, category: str, limit: int) -> List[Dict[str, Any]]:
        """生成模拟热门视频数据"""
        return self._get_mock_videos(category, limit)
    
    def _get_mock_ecommerce_data(self, product_category: str) -> Dict[str, Any]:
        """生成模拟电商数据"""
        return {
            "category": product_category,
            "period": "last_30_days",
            "summary": {
                "total_gmv": 5000000,
                "total_orders": 12000,
                "avg_price": 416.67,
                "top_products": [
                    {"name": "热销产品1", "sales": 3500},
                    {"name": "热销产品2", "sales": 2800},
                ],
            },
            "top_creators": [
                {"nickname": "达人A", "gmv": 800000, "orders": 2000},
                {"nickname": "达人B", "gmv": 650000, "orders": 1500},
            ],
            "trend": [
                {"date": "2026-01-01", "gmv": 150000},
                {"date": "2026-01-08", "gmv": 180000},
                {"date": "2026-01-15", "gmv": 210000},
                {"date": "2026-01-22", "gmv": 250000},
            ],
        }


# 创建全局客户端实例
douyin_client = DouyinClient()
