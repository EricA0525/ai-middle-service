"""
Market Insight Agent - Data Collector Node
===========================================
数据采集节点，负责从多个数据源采集品牌/品类相关数据。

数据源：
1. Tavily - 全网搜索
2. 小红书 API - 笔记、达人数据
3. 抖音 API - 视频、带货数据

设计思想：
1. 并行采集多数据源，提高效率
2. 统一数据格式，便于后续处理
3. 降级策略：单个数据源失败不影响整体

后续开发方向：
1. 对接真实 API
2. 添加数据缓存
3. 实现重试机制
"""

import asyncio
from typing import Any, Dict, List, Optional

from loguru import logger


class DataCollectorNode:
    """
    数据采集节点
    
    负责从多个数据源采集数据，并做统一格式化处理。
    """
    
    def __init__(
        self,
        tavily_client=None,
        xiaohongshu_client=None,
        douyin_client=None,
        progress_callback=None,
        *,
        xiaohongshu_enabled: bool = False,
        douyin_enabled: bool = False,
    ):
        """
        初始化数据采集器
        
        Args:
            tavily_client: Tavily 客户端
            xiaohongshu_client: 小红书客户端（预留）
            douyin_client: 抖音客户端（预留）
            progress_callback: 可选进度回调 (progress, message)
            xiaohongshu_enabled: 是否启用小红书数据采集（默认禁用）
            douyin_enabled: 是否启用抖音数据采集（默认禁用）
        """
        self.tavily = tavily_client
        self.xiaohongshu = xiaohongshu_client
        self.douyin = douyin_client
        self.progress_callback = progress_callback
        self.xiaohongshu_enabled = xiaohongshu_enabled
        self.douyin_enabled = douyin_enabled
    
    async def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        节点执行入口（LangGraph 调用）
        
        并行采集所有数据源，然后合并结果。
        """
        logger.info("Starting data collection...")
        
        params = state.get("params", {})
        task_type = state.get("task_type", "brand_health")
        
        try:
            # 并行采集多数据源
            collected_data = await self.collect_all(params, task_type)
            
            updated = {
                **state,
                "collected_data": collected_data,
                "current_step": "数据采集完成",
                "progress": 50,
            }
            if self.progress_callback:
                self.progress_callback(updated["progress"], updated["current_step"])
            return updated
            
        except Exception as e:
            logger.error(f"Data collection failed: {e}")
            updated = {
                **state,
                "collected_data": {},
                "error": f"数据采集失败: {str(e)}",
            }
            if self.progress_callback:
                self.progress_callback(state.get("progress", 0), "数据采集失败")
            return updated
    
    async def collect_all(
        self,
        params: Dict[str, Any],
        task_type: str,
    ) -> Dict[str, Any]:
        """
        并行采集所有数据源
        
        Args:
            params: 用户输入参数
            task_type: 任务类型
            
        Returns:
            采集到的所有数据
        """
        # 并行执行所有采集任务
        tasks = [
            self.collect_tavily(params, task_type),
            self.collect_xiaohongshu(params, task_type),
            self.collect_douyin(params, task_type),
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 合并结果
        collected_data = {
            "tavily_results": results[0] if not isinstance(results[0], Exception) else [],
            "xiaohongshu_data": results[1] if not isinstance(results[1], Exception) else [],
            "douyin_data": results[2] if not isinstance(results[2], Exception) else [],
            "params": params,
        }
        
        # 记录采集情况
        for source, result in zip(["tavily", "xiaohongshu", "douyin"], results):
            if isinstance(result, Exception):
                logger.warning(f"Failed to collect from {source}: {result}")
            else:
                logger.info(f"Collected {len(result)} items from {source}")
        
        return collected_data
    
    async def collect_tavily(
        self,
        params: Dict[str, Any],
        task_type: str,
    ) -> List[Dict]:
        """
        从 Tavily 搜索数据
        
        TODO: 对接真实 Tavily API
        
        实现步骤：
        1. 根据任务类型构建搜索查询
        2. 调用 Tavily API
        3. 格式化搜索结果
        """
        logger.info("Collecting data from Tavily...")

        query = self._build_tavily_query(params, task_type)
        if self.tavily is not None:
            raw = await self.tavily.search(query)
            return self._normalize_tavily_results(raw)

        return self._get_mock_tavily_data(params)
    
    async def collect_xiaohongshu(
        self,
        params: Dict[str, Any],
        task_type: str,
    ) -> List[Dict]:
        """
        从小红书采集数据
        
        预留接口，等待 API 接入。当前默认禁用。
        """
        if not self.xiaohongshu_enabled:
            logger.info("XiaoHongShu data collection disabled, skipping...")
            return []

        logger.info("Collecting data from XiaoHongShu...")
        query = params.get("brand_name") or params.get("category") or "Unknown"
        if self.xiaohongshu is not None and hasattr(self.xiaohongshu, "search"):
            return await self.xiaohongshu.search(query)

        # 如果启用但没有客户端，返回空列表
        return []
    
    async def collect_douyin(
        self,
        params: Dict[str, Any],
        task_type: str,
    ) -> List[Dict]:
        """
        从抖音采集数据
        
        预留接口，等待 API 接入。当前默认禁用。
        """
        if not self.douyin_enabled:
            logger.info("Douyin data collection disabled, skipping...")
            return []

        logger.info("Collecting data from Douyin...")
        query = params.get("brand_name") or params.get("category") or "Unknown"
        if self.douyin is not None and hasattr(self.douyin, "search"):
            return await self.douyin.search(query)

        # 如果启用但没有客户端，返回空列表
        return []

    def _build_tavily_query(self, params: Dict[str, Any], task_type: str) -> str:
        if task_type == "tiktok_insight":
            category = params.get("category", "")
            selling_points = params.get("selling_points", []) or []
            sp_text = " ".join(selling_points[:5])
            return f"TikTok {category} trend insights {sp_text}".strip()

        brand_name = params.get("brand_name", "")
        region = params.get("region", "")
        competitors = params.get("competitors", []) or []
        comp_text = " ".join(competitors[:5])
        return f"{brand_name} market analysis {region} competitors {comp_text}".strip()

    def _normalize_tavily_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        统一 Tavily 返回字段，供后续内容生成/渲染使用。

        输出字段：title, url, snippet, source, published_date, score
        """
        normalized: List[Dict[str, Any]] = []
        seen_urls: set[str] = set()
        for r in results or []:
            title = r.get("title") or ""
            url = r.get("url") or ""
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            snippet = r.get("snippet") or r.get("content") or r.get("raw_content") or ""
            source = r.get("source") or r.get("domain") or ""
            published_date = r.get("published_date") or r.get("publishedDate") or r.get("date") or None
            score = r.get("score")
            normalized.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "source": source,
                    "published_date": published_date,
                    "score": score,
                }
            )
        return normalized
    
    # ========== 模拟数据生成（开发用）==========
    
    def _get_mock_tavily_data(self, params: Dict) -> List[Dict]:
        """生成 Tavily 模拟数据"""
        brand_name = params.get("brand_name") or params.get("category") or "Unknown"
        return [
            {
                "title": f"{brand_name} 市场分析报告 2026",
                "url": "https://example.com/report1",
                "snippet": f"{brand_name} 在过去一年中保持了稳定的市场增长...",
                "source": "行业报告",
            },
            {
                "title": f"{brand_name} vs 竞品对比分析",
                "url": "https://example.com/report2",
                "snippet": "从市场份额来看，该品牌处于行业中游位置...",
                "source": "市场研究",
            },
        ]
    
    def _get_mock_xiaohongshu_data(self, params: Dict) -> List[Dict]:
        """生成小红书模拟数据"""
        return [
            {
                "note_id": "xhs_001",
                "title": "最近入手的好物分享",
                "content": "用了一个月的真实感受...",
                "likes": 1234,
                "comments": 89,
                "author": "小红书达人A",
            },
        ]
    
    def _get_mock_douyin_data(self, params: Dict) -> List[Dict]:
        """生成抖音模拟数据"""
        return [
            {
                "video_id": "dy_001",
                "title": "开箱测评",
                "views": 50000,
                "likes": 3200,
                "shares": 156,
                "author": "抖音达人B",
            },
        ]
