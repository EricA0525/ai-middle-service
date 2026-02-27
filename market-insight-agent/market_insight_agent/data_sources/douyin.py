"""
抖音数据源（Mock 实现）

提供抖音平台的模拟数据，包括达人列表、热门视频、直播电商数据等。
"""

from typing import Dict, Any
from pathlib import Path

from .base import MockDataSource
from ..config import settings


class DouyinSource(MockDataSource):
    """抖音数据源"""
    
    name = "douyin"
    description = "抖音平台数据（Mock）"
    available = True
    
    def __init__(self):
        data_file = settings.mock_data_path / "douyin_sample.json"
        super().__init__(str(data_file))
    
    def fetch(
        self,
        brand: str,
        competitors: list[str],
        **kwargs
    ) -> Dict[str, Any]:
        """
        获取抖音数据
        
        Args:
            brand: 目标品牌
            competitors: 竞品列表
            
        Returns:
            包含以下数据的字典：
            - creator_list: 达人列表
            - hot_videos: 热门视频
            - live_commerce_data: 直播电商数据
            - content_trends: 内容趋势
            - audience_analytics: 受众分析
        """
        data = super().fetch(brand, competitors, **kwargs)
        return data
    
    def get_creator_recommendations(
        self,
        brand: str,
        min_followers: int = 0,
        content_type: str = "all"
    ) -> list[Dict[str, Any]]:
        """
        获取达人推荐列表
        
        Args:
            brand: 目标品牌
            min_followers: 最低粉丝数
            content_type: 内容类型
            
        Returns:
            符合条件的达人列表
        """
        data = self._load_data()
        creators = data.get("creator_list", [])
        
        # 根据粉丝数过滤
        if min_followers > 0:
            creators = [c for c in creators if c.get("followers", 0) >= min_followers]
        
        return creators
    
    def get_hot_videos(self, limit: int = 10) -> list[Dict[str, Any]]:
        """
        获取热门视频
        
        Args:
            limit: 返回数量限制
            
        Returns:
            热门视频列表
        """
        data = self._load_data()
        videos = data.get("hot_videos", [])
        return videos[:limit]
    
    def get_content_trends(self) -> Dict[str, Any]:
        """
        获取内容趋势
        
        Returns:
            内容趋势数据
        """
        data = self._load_data()
        return data.get("content_trends", {})
    
    def get_audience_analytics(self) -> Dict[str, Any]:
        """
        获取受众分析数据
        
        Returns:
            受众分析数据
        """
        data = self._load_data()
        return data.get("audience_analytics", {})
