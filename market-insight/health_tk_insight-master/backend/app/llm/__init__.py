"""
LLM clients and helpers.

This package provides a thin abstraction around OpenAI-compatible APIs.
"""

from app.llm.openai_compat import OpenAICompatLLM

__all__ = ["OpenAICompatLLM"]

