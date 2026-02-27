"""
测试会话级别配置。

- 测试环境禁用速率限制器，避免限流对测试的干扰。
"""
from __future__ import annotations

import pytest

from market_insight_agent.main import limiter


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    """在测试环境中禁用速率限制。"""
    limiter.enabled = False
    yield
    limiter.enabled = True
