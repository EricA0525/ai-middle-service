"""
社交媒体数据源（预留接口）

为 Facebook、Instagram、Twitter 预留接口，当前为空实现。
后续接入真实 API 时需要实现这些类。
"""

from typing import Dict, Any

from .base import DataSource


class FacebookSource(DataSource):
    """Facebook 数据源（预留）"""
    
    name = "facebook"
    description = "Facebook 平台数据（预留接口）"
    available = False  # 标记为不可用
    
    def fetch(
        self,
        brand: str,
        competitors: list[str],
        **kwargs
    ) -> Dict[str, Any]:
        """
        获取 Facebook 数据
        
        当前为预留接口，调用时会抛出 NotImplementedError。
        """
        raise NotImplementedError(
            "Facebook 数据源尚未实现。请在后续版本中接入真实 API。"
        )


class InstagramSource(DataSource):
    """Instagram 数据源（预留）"""
    
    name = "instagram"
    description = "Instagram 平台数据（预留接口）"
    available = False
    
    def fetch(
        self,
        brand: str,
        competitors: list[str],
        **kwargs
    ) -> Dict[str, Any]:
        """
        获取 Instagram 数据
        
        当前为预留接口，调用时会抛出 NotImplementedError。
        """
        raise NotImplementedError(
            "Instagram 数据源尚未实现。请在后续版本中接入真实 API。"
        )


class TwitterSource(DataSource):
    """Twitter/X 数据源（预留）"""
    
    name = "twitter"
    description = "Twitter/X 平台数据（预留接口）"
    available = False
    
    def fetch(
        self,
        brand: str,
        competitors: list[str],
        **kwargs
    ) -> Dict[str, Any]:
        """
        获取 Twitter/X 数据
        
        当前为预留接口，调用时会抛出 NotImplementedError。
        """
        raise NotImplementedError(
            "Twitter/X 数据源尚未实现。请在后续版本中接入真实 API。"
        )
