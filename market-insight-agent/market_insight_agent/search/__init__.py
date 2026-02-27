"""
搜索模块

提供网络搜索能力，用于获取实时市场数据。
"""

from .tavily_client import TavilySearchClient, get_tavily_client

__all__ = ["TavilySearchClient", "get_tavily_client"]
