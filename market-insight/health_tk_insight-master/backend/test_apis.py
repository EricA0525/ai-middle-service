"""
测试 API 连接 - Windows 兼容版本
"""
import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')

from app.data_sources.tavily_client import TavilyClient
from app.llm.openai_compat import OpenAICompatLLM
from app.config import get_settings


async def test_tavily():
    settings = get_settings()
    print("=" * 50)
    print("Testing Tavily API...")
    print("=" * 50)
    
    client = TavilyClient()
    has_key = bool(client.api_key)
    print(f"Tavily configured: {has_key}")
    
    if not has_key:
        print("Tavily API key not set, skipping...")
        return
    
    try:
        results = await client.search("牙膏品牌市场分析 2024", max_results=3)
        print(f"Results count: {len(results)}")
        for r in results[:2]:
            title = r.get("title", "No title")[:50]
            print(f"  - {title}")
        print("[OK] Tavily API works!")
    except Exception as e:
        print(f"[FAIL] Tavily error: {e}")


async def test_llm():
    # 重新加载配置以获取最新的环境变量
    from app.config import Settings
    settings = Settings()
    
    print("\n" + "=" * 50)
    print("Testing LLM API...")
    print("=" * 50)
    
    llm = OpenAICompatLLM(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    )
    print(f"LLM configured: {llm.is_configured()}")
    print(f"Base URL: {llm.base_url}")
    print(f"Model: {llm.model}")
    
    if not llm.is_configured():
        print("LLM API key not set, skipping...")
        return
    
    try:
        response = await llm.generate_html(
            "用简短的 HTML 片段总结：牙膏市场的三个主要趋势。只返回 HTML，不要 markdown。"
        )
        print(f"Response length: {len(response.content)} chars")
        print(f"Content preview: {response.content[:300]}...")
        print("[OK] LLM API works!")
    except Exception as e:
        print(f"[FAIL] LLM error: {e}")


async def main():
    await test_tavily()
    await test_llm()
    print("\n" + "=" * 50)
    print("API tests complete!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
