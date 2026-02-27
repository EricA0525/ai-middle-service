"""
小红书数据源（Mock 实现）

提供小红书平台的模拟数据，包括 KOL 列表、热门笔记、话题标签等。
"""

from typing import Dict, Any
from pathlib import Path

from .base import MockDataSource
from ..config import settings


class XiaohongshuSource(MockDataSource):
    """小红书数据源"""
    
    name = "xiaohongshu"
    description = "小红书平台数据（Mock）"
    available = True
    
    def __init__(self):
        data_file = settings.mock_data_path / "xiaohongshu_sample.json"
        super().__init__(str(data_file))
    
    def fetch(
        self,
        brand: str,
        competitors: list[str],
        **kwargs
    ) -> Dict[str, Any]:
        """
        获取小红书数据
        
        Args:
            brand: 目标品牌
            competitors: 竞品列表
            
        Returns:
            包含以下数据的字典：
            - kol_list: KOL 列表
            - hot_notes: 热门笔记
            - trending_topics: 热门话题
            - consumer_insights: 消费者洞察
        """
        data = super().fetch(brand, competitors, **kwargs)
        
        # 可以在这里对数据进行品牌相关的过滤或处理
        # 当前为 Mock 实现，直接返回静态数据
        
        return data
    
    def get_kol_recommendations(
        self,
        brand: str,
        budget_range: str = "all",
        content_type: str = "all"
    ) -> list[Dict[str, Any]]:
        """
        获取 KOL 推荐列表
        
        Args:
            brand: 目标品牌
            budget_range: 预算范围 ("low", "medium", "high", "all")
            content_type: 内容类型
            
        Returns:
            符合条件的 KOL 列表
        """
        data = self._load_data()
        kols = data.get("kol_list", [])
        
        # Mock 实现：直接返回所有 KOL
        # 真实实现应该根据参数进行过滤
        return kols
    
    def get_trending_topics(self, limit: int = 10) -> list[Dict[str, Any]]:
        """
        获取热门话题
        
        Args:
            limit: 返回数量限制
            
        Returns:
            热门话题列表
        """
        data = self._load_data()
        topics = data.get("trending_topics", [])
        return topics[:limit]
