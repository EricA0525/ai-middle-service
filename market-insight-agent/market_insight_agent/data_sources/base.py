"""
数据源抽象基类

定义数据源接口规范，所有具体数据源实现都需要继承此基类。
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class DataSource(ABC):
    """数据源抽象基类"""
    
    # 数据源名称
    name: str = "base"
    
    # 数据源描述
    description: str = "Base data source"
    
    # 是否可用（用于标记预留接口）
    available: bool = True
    
    @abstractmethod
    def fetch(
        self,
        brand: str,
        competitors: list[str],
        **kwargs
    ) -> Dict[str, Any]:
        """
        获取品牌相关数据
        
        Args:
            brand: 目标品牌名称
            competitors: 竞品品牌列表
            **kwargs: 其他可选参数
            
        Returns:
            包含数据的字典
        """
        pass
    
    def is_available(self) -> bool:
        """检查数据源是否可用"""
        return self.available
    
    def get_metadata(self) -> Dict[str, Any]:
        """获取数据源元数据"""
        return {
            "name": self.name,
            "description": self.description,
            "available": self.available
        }


class MockDataSource(DataSource):
    """Mock 数据源基类"""
    
    def __init__(self, data_file: Optional[str] = None):
        """
        初始化 Mock 数据源
        
        Args:
            data_file: Mock 数据文件路径
        """
        self.data_file = data_file
        self._data: Optional[Dict[str, Any]] = None
    
    def _load_data(self) -> Dict[str, Any]:
        """加载 Mock 数据"""
        if self._data is not None:
            return self._data
        
        if self.data_file is None:
            return {}
        
        import json
        from pathlib import Path
        
        data_path = Path(self.data_file)
        if not data_path.exists():
            return {}
        
        with open(data_path, "r", encoding="utf-8") as f:
            self._data = json.load(f)
        
        return self._data
    
    def fetch(
        self,
        brand: str,
        competitors: list[str],
        **kwargs
    ) -> Dict[str, Any]:
        """
        获取 Mock 数据
        
        注意：Mock 数据是静态的，不会根据品牌变化。
        后续接入真实 API 时需要替换此实现。
        """
        data = self._load_data()
        
        # 添加查询上下文
        data["query_context"] = {
            "brand": brand,
            "competitors": competitors,
            "is_mock": True
        }
        
        return data
