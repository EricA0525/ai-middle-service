"""
Market Insight Agent - Configuration
========================================
统一配置管理，使用 Pydantic Settings 实现类型安全的配置加载。

设计思想：
1. 所有配置集中管理，避免散落在代码各处
2. 支持环境变量覆盖，便于不同环境部署
3. 类型安全，启动时即可发现配置错误
"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置类"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    # ========== 应用配置 ==========
    app_name: str = "market-insight-agent"
    app_env: str = "development"
    debug: bool = True
    log_level: str = "INFO"
    log_to_file: bool = True
    log_file_path: str = "logs/app.log"
    
    # ========== API 服务 ==========
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api/v1"
    
    # ========== LLM 配置 ==========
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4-turbo"
    
    # ========== Tavily 搜索 API ==========
    tavily_api_key: str = ""
    tavily_cache_enabled: bool = True
    tavily_cache_ttl_seconds: int = 3600
    
    # ========== 小红书 API（预留）==========
    xiaohongshu_api_url: Optional[str] = None
    xiaohongshu_api_key: Optional[str] = None
    
    # ========== 抖音 API（预留）==========
    douyin_api_url: Optional[str] = None
    douyin_api_key: Optional[str] = None
    
    # ========== Redis 配置 ==========
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    celery_enabled: bool = False
    
    # ========== 数据库配置 ==========
    database_url: str = "sqlite+aiosqlite:///./data/tasks.db"
    task_store_backend: str = "memory"  # memory | sqlite
    
    # ========== 任务配置 ==========
    task_timeout_seconds: int = 300
    task_result_expire_seconds: int = 3600
    
    @property
    def is_production(self) -> bool:
        """是否为生产环境"""
        return self.app_env == "production"
    
    @property
    def is_development(self) -> bool:
        """是否为开发环境"""
        return self.app_env == "development"


@lru_cache()
def get_settings() -> Settings:
    """
    获取配置单例
    
    使用 lru_cache 确保配置只加载一次，提高性能。
    """
    return Settings()


# 导出配置实例，便于直接引用
settings = get_settings()
