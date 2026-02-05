"""
Market Insight Agent - Base Data Source
========================================
数据源基类，定义统一的数据源接口。

设计思想：
1. 所有数据源继承自 BaseDataSource
2. 统一的异步接口
3. 内置重试和错误处理机制
4. 便于后续扩展新数据源

后续开发方向：
1. 添加缓存机制
2. 添加请求限流
3. 添加健康检查
"""

from abc import ABC, abstractmethod
import asyncio
from typing import Any, Dict, List, Optional

from loguru import logger


class BaseDataSource(ABC):
    """
    数据源基类
    
    所有外部数据源都应继承此类，实现统一的接口。
    """
    
    def __init__(
        self,
        name: str,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        """
        初始化数据源
        
        Args:
            name: 数据源名称
            api_url: API 地址
            api_key: API 密钥
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
        """
        self.name = name
        self.api_url = api_url
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        
        self._is_available = False
    
    @abstractmethod
    async def search(self, query: str, **kwargs) -> List[Dict[str, Any]]:
        """
        搜索数据
        
        Args:
            query: 搜索查询
            **kwargs: 额外参数
            
        Returns:
            搜索结果列表
        """
        pass
    
    @abstractmethod
    async def get_detail(self, item_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        """
        获取详情
        
        Args:
            item_id: 项目 ID
            **kwargs: 额外参数
            
        Returns:
            详情数据
        """
        pass
    
    async def check_availability(self) -> bool:
        """
        检查数据源可用性
        
        Returns:
            是否可用
        """
        try:
            # 子类可以重写此方法进行更详细的检查
            if not self.api_url or not self.api_key:
                logger.warning(f"Data source {self.name} not configured")
                self._is_available = False
                return False
            
            self._is_available = True
            return True
            
        except Exception as e:
            logger.error(f"Data source {self.name} availability check failed: {e}")
            self._is_available = False
            return False
    
    @property
    def is_available(self) -> bool:
        """数据源是否可用"""
        return self._is_available
    
    async def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        带重试的 HTTP 请求

        Args:
            method: HTTP 方法
            url: 请求 URL
            **kwargs: 请求参数
            
        Returns:
            响应数据
        """
        import httpx

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.request(method, url, **kwargs)
                    response.raise_for_status()
                    if response.headers.get("content-type", "").lower().startswith(
                        "application/json"
                    ):
                        return response.json()
                    return {"text": response.text}
            except Exception as e:
                last_error = e
                if attempt == self.max_retries - 1:
                    break
                wait_seconds = 2 ** attempt
                logger.warning(
                    f"Retry {attempt + 1}/{self.max_retries} for {url} (wait {wait_seconds}s): {e}"
                )
                await asyncio.sleep(wait_seconds)

        raise RuntimeError(f"HTTP request failed: {url}") from last_error
