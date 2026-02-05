"""
Market Insight Agent - Data Sources Package
============================================
外部数据源包。

数据源状态：
- ✅ Tavily: 全网搜索（待完成真实 API 对接）
- 🚧 小红书: 预留接口
- 🚧 抖音: 预留接口
- ⏳ Facebook: 预留接口（暂不实现）
- ⏳ Instagram: 预留接口（暂不实现）
- ⏳ Twitter: 预留接口（暂不实现）
"""

from app.data_sources.base import BaseDataSource
from app.data_sources.tavily_client import tavily_client, TavilyClient
from app.data_sources.xiaohongshu import xiaohongshu_client, XiaoHongShuClient
from app.data_sources.douyin import douyin_client, DouyinClient

__all__ = [
    "BaseDataSource",
    "TavilyClient",
    "tavily_client",
    "XiaoHongShuClient",
    "xiaohongshu_client",
    "DouyinClient",
    "douyin_client",
]
