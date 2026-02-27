"""
配置管理模块

使用 Pydantic Settings 从 .env 文件读取配置，支持自定义 OpenAI API 端点。
"""

from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


PACKAGE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = PACKAGE_DIR.parent


class Settings(BaseSettings):
    """应用配置类"""

    # OpenAI API 配置
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    model_name: str = "gpt-4o"

    # Tavily 搜索 API 配置
    tavily_api_key: str = ""
    tavily_request_timeout_seconds: int = 20
    tavily_total_search_budget_seconds: int = 45
    search_total_timeout_seconds: int = 90

    # 路径配置
    # Default to paths relative to the backend directory so the app works even if
    # the process is started from the project root (or elsewhere).
    template_dir: str = str(BACKEND_DIR / "templates")
    output_dir: str = str(BACKEND_DIR / "output")
    mock_data_dir: str = str(BACKEND_DIR / "mock_data")
    include_mock_prompt_data: bool = False

    # v2 作业系统配置
    job_db_path: str = ""
    report_job_soft_timeout_seconds: int = 720
    section_min_text_len: int = 180
    structure_fidelity_threshold: float = 0.90
    allow_publish_on_quality_gate_failure: bool = True
    llm_total_budget_seconds: int = 0
    inline_source_link_strict: bool = True
    inline_source_link_auto_inject: bool = True
    section_llm_timeout_seconds: int = 120
    section_retry_timeout_seconds: int = 75
    search_degrade_on_error: bool = True
    retry_relax_inline_source_coverage: float = 0.70
    retry_context_compression_ratio: float = 0.55

    # 服务器配置
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # 前端配置
    frontend_url: str = "http://localhost:3000"

    # ── Phase 1: 稳定性配置 ──────────────────────────

    # 并发控制
    max_concurrent_jobs: int = 2
    max_queued_jobs: int = 10
    shutdown_grace_period_seconds: int = 30

    # 认证（空值 = 跳过认证，方便开发）
    api_secret_key: str = ""

    # 速率限制（slowapi 格式）
    rate_limit_generate: str = "1/3minutes"
    rate_limit_query: str = "60/minute"
    rate_limit_template: str = "10/minute"

    # 日志
    log_level: str = "INFO"
    log_format: str = "auto"  # "auto" | "json" | "console"

    # 幂等
    idempotency_ttl_seconds: int = 300  # 5 分钟

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def validate_startup(self) -> list[str]:
        """启动时校验关键配置，返回警告列表。"""
        warnings: list[str] = []
        if not self.openai_api_key:
            warnings.append("OPENAI_API_KEY 未设置，LLM 功能将不可用")
        tpl = Path(self.template_dir)
        if not tpl.exists():
            warnings.append(f"TEMPLATE_DIR 不存在: {tpl}")
        out = Path(self.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        if not out.exists():
            warnings.append(f"OUTPUT_DIR 无法创建: {out}")
        return warnings

    @property
    def template_path(self) -> Path:
        """获取模板目录的绝对路径"""
        return Path(self.template_dir).resolve()

    @property
    def output_path(self) -> Path:
        """获取输出目录的绝对路径"""
        return Path(self.output_dir).resolve()

    @property
    def mock_data_path(self) -> Path:
        """获取 Mock 数据目录的绝对路径"""
        return Path(self.mock_data_dir).resolve()


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例（带缓存）"""
    return Settings()


# 导出全局配置实例
settings = get_settings()
