"""
Market Insight Agent - Tavily Client
=====================================
Tavily 搜索 API 客户端，用于全网搜索。

Tavily 是专为 AI Agent 设计的搜索 API，提供：
1. 实时网络搜索
2. 结构化搜索结果
3. AI 优化的内容提取

使用方式：
1. 在 .env 中配置 TAVILY_API_KEY
2. 调用 tavily_client.search(query) 进行搜索

后续开发方向：
1. 完成真正的 API 对接
2. 添加搜索结果缓存
3. 优化搜索查询构建
"""

import time
from typing import Any, Dict, List, Optional

from loguru import logger

from app.config import settings
from app.data_sources.base import BaseDataSource


class TavilyClient(BaseDataSource):
    """
    Tavily 搜索客户端
    
    官方文档: https://docs.tavily.com/
    """
    
    def __init__(self):
        super().__init__(
            name="tavily",
            api_url="https://api.tavily.com",
            api_key=settings.tavily_api_key,
        )
        self._cache: Dict[str, tuple[float, List[Dict[str, Any]]]] = {}
    
    async def search(
        self,
        query: str,
        search_depth: str = "advanced",
        max_results: int = 10,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        执行 Tavily 搜索
        
        Args:
            query: 搜索查询
            search_depth: 搜索深度 ("basic" | "advanced")
            max_results: 最大结果数
            include_domains: 限定域名
            exclude_domains: 排除域名
            
        Returns:
            搜索结果列表
        """
        logger.info(f"Tavily search: {query}")

        cache_key = self._cache_key(
            query=query,
            search_depth=search_depth,
            max_results=max_results,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
        )
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        if not self.api_key:
            logger.warning("Tavily API not configured, returning mock data")
            results = self._get_mock_results(query)
            self._set_cache(cache_key, results)
            return results

        payload: Dict[str, Any] = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": search_depth,
            "max_results": max_results,
        }
        if include_domains:
            payload["include_domains"] = include_domains
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains

        try:
            data = await self._request_with_retry(
                "POST",
                f"{self.api_url}/search",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            results = data.get("results", [])
            if not isinstance(results, list):
                return []

            # Normalize for downstream usage: provide both `snippet` and `content` shape
            normalized: List[Dict[str, Any]] = []
            for r in results:
                if not isinstance(r, dict):
                    continue
                normalized.append(
                    {
                        "title": r.get("title"),
                        "url": r.get("url"),
                        "content": r.get("content") or r.get("snippet"),
                        "snippet": r.get("snippet") or r.get("content"),
                        "score": r.get("score"),
                        "published_date": r.get("published_date"),
                        "source": r.get("source") or r.get("domain"),
                    }
                )
            self._set_cache(cache_key, normalized)
            return normalized
        except Exception as e:
            logger.warning(f"Tavily request failed, fallback to mock data: {e}")
            results = self._get_mock_results(query)
            self._set_cache(cache_key, results)
            return results
    
    async def get_detail(self, item_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        """
        获取详情（Tavily 搜索不支持详情获取，直接返回 None）
        """
        return None
    
    def _get_mock_results(self, query: str) -> List[Dict[str, Any]]:
        """生成模拟搜索结果"""
        return [
            {
                "title": f"关于 {query} 的市场分析报告",
                "url": "https://example.com/market-report",
                "content": f"这是一篇关于 {query} 的详细市场分析...",
                "score": 0.95,
                "published_date": "2026-01-15",
            },
            {
                "title": f"{query} 行业趋势洞察 2026",
                "url": "https://example.com/industry-trends",
                "content": "行业数据显示，该领域正在快速发展...",
                "score": 0.88,
                "published_date": "2026-01-10",
            },
            {
                "title": f"消费者对 {query} 的态度调研",
                "url": "https://example.com/consumer-survey",
                "content": "调研结果表明，消费者对该品类的关注度持续上升...",
                "score": 0.82,
                "published_date": "2026-01-05",
            },
        ]

    def _cache_key(
        self,
        *,
        query: str,
        search_depth: str,
        max_results: int,
        include_domains: Optional[List[str]],
        exclude_domains: Optional[List[str]],
    ) -> str:
        inc = ",".join(include_domains or [])
        exc = ",".join(exclude_domains or [])
        return f"{query}||{search_depth}||{max_results}||inc:{inc}||exc:{exc}"

    def _get_cache(self, key: str) -> Optional[List[Dict[str, Any]]]:
        if not settings.tavily_cache_enabled:
            return None

        item = self._cache.get(key)
        if not item:
            return None
        expires_at, value = item
        if time.time() >= expires_at:
            self._cache.pop(key, None)
            return None
        return value

    def _set_cache(self, key: str, value: List[Dict[str, Any]]) -> None:
        if not settings.tavily_cache_enabled:
            return
        ttl = max(1, int(settings.tavily_cache_ttl_seconds))
        self._cache[key] = (time.time() + ttl, value)


# 创建全局客户端实例
tavily_client = TavilyClient()
