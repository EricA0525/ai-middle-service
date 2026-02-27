"""
Tavily 搜索客户端模块

使用 Tavily API 进行网络搜索，获取实时市场数据。
"""

import time
from typing import Optional
from tavily import TavilyClient

from ..config import settings


class TavilySearchClient:
    """Tavily 搜索客户端封装类"""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        初始化 Tavily 搜索客户端
        
        Args:
            api_key: Tavily API Key，默认从配置读取
        """
        self.api_key = api_key or settings.tavily_api_key
        
        if not self.api_key:
            raise ValueError("Tavily API Key 未配置，请在 .env 中设置 TAVILY_API_KEY")
        
        self.client = TavilyClient(api_key=self.api_key)
    
    def search(
        self,
        query: str,
        search_depth: str = "advanced",
        max_results: int = 10,
        include_answer: bool = True,
        include_raw_content: bool = False
    ) -> dict:
        """
        执行搜索查询
        
        Args:
            query: 搜索查询字符串
            search_depth: 搜索深度，"basic" 或 "advanced"
            max_results: 最大返回结果数
            include_answer: 是否包含 AI 生成的答案摘要
            include_raw_content: 是否包含原始网页内容
            
        Returns:
            搜索结果字典，包含 results, answer 等字段
        """
        start = time.perf_counter()
        
        try:
            timeout_s = float(getattr(settings, "tavily_request_timeout_seconds", 20) or 20)
            response = self.client.search(
                query=query,
                search_depth=search_depth,
                max_results=max_results,
                include_answer=include_answer,
                include_raw_content=include_raw_content,
                timeout=timeout_s,
            )
            
            latency_ms = int((time.perf_counter() - start) * 1000)
            
            return {
                "ok": True,
                "query": query,
                "answer": response.get("answer", ""),
                "results": response.get("results", []),
                "latency_ms": latency_ms,
                "error": None
            }
        except Exception as e:
            latency_ms = int((time.perf_counter() - start) * 1000)
            return {
                "ok": False,
                "query": query,
                "answer": "",
                "results": [],
                "latency_ms": latency_ms,
                "error": f"{type(e).__name__}: {str(e)}"
            }
    
    def search_brand_info(
        self,
        brand: str,
        competitors: list[str],
        topics: list[str] = None
    ) -> dict:
        """
        搜索品牌相关信息
        
        Args:
            brand: 目标品牌名称
            competitors: 竞品品牌列表
            topics: 要搜索的话题列表
            
        Returns:
            结构化的品牌信息字典
        """
        if topics is None:
            topics = [
                "市场趋势",
                "消费者评价",
                "竞品对比",
                "品牌定位"
            ]
        
        all_results = {
            "brand": brand,
            "competitors": competitors,
            "searches": [],
            "total_latency_ms": 0
        }
        
        total_start = time.perf_counter()
        total_budget_s = float(getattr(settings, "tavily_total_search_budget_seconds", 45) or 45)
        budget_exhausted = False
        
        # 搜索品牌相关的各个话题
        for topic in topics:
            if (time.perf_counter() - total_start) > total_budget_s:
                budget_exhausted = True
                break
            query = f"{brand} {topic} 最新 2024 2025"
            result = self.search(query, max_results=5)
            all_results["searches"].append({
                "topic": topic,
                "query": query,
                "answer": result.get("answer", ""),
                "results": result.get("results", [])[:5],
                "ok": result.get("ok", False)
            })
        
        # 搜索竞品对比
        if competitors and (not budget_exhausted) and (time.perf_counter() - total_start) <= total_budget_s:
            competitors_str = " ".join(competitors[:3])  # 最多取3个竞品
            query = f"{brand} vs {competitors_str} 对比 评测"
            result = self.search(query, max_results=5)
            all_results["searches"].append({
                "topic": "竞品对比",
                "query": query,
                "answer": result.get("answer", ""),
                "results": result.get("results", [])[:5],
                "ok": result.get("ok", False)
            })

        all_results["total_latency_ms"] = int((time.perf_counter() - total_start) * 1000)
        all_results["ok"] = any(s.get("ok", False) for s in all_results["searches"])
        all_results["budget_exhausted"] = budget_exhausted
        all_results["budget_seconds"] = total_budget_s
        
        return all_results
    
    def get_formatted_context(self, search_results: dict) -> str:
        """
        将搜索结果格式化为 LLM 可用的上下文文本
        
        Args:
            search_results: search_brand_info 的返回结果
            
        Returns:
            格式化的上下文字符串
        """
        context_parts = []
        
        context_parts.append(f"# {search_results['brand']} 品牌洞察搜索数据\n")
        context_parts.append(f"竞品: {', '.join(search_results['competitors'])}\n")
        context_parts.append(f"数据获取时间: 实时搜索\n\n")
        
        for search in search_results.get("searches", []):
            topic = search.get("topic", "")
            answer = search.get("answer", "")
            results = search.get("results", [])
            
            context_parts.append(f"## {topic}\n")
            
            if answer:
                context_parts.append(f"**AI 摘要**: {answer}\n\n")
            
            if results:
                context_parts.append("**搜索结果**:\n")
                for i, result in enumerate(results[:5], 1):
                    title = result.get("title", "")
                    url = result.get("url", "")
                    content = result.get("content", "")[:500]  # 截取前500字符
                    context_parts.append(f"{i}. [{title}]({url})\n   {content}\n\n")
            
            context_parts.append("\n")
        
        return "".join(context_parts)


def get_tavily_client() -> TavilySearchClient:
    """获取 Tavily 搜索客户端实例"""
    return TavilySearchClient()
