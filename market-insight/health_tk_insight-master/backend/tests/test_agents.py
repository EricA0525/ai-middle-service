"""
Market Insight Agent - Agent Tests
===================================
LangGraph Agent 测试
"""

import pytest

from app.agents.base import AgentState
from app.agents.brand_health_agent import BrandHealthAgent
from app.agents.tiktok_insight_agent import TikTokInsightAgent


class TestAgentState:
    """Agent 状态测试"""
    
    def test_create_initial_state(self):
        """测试创建初始状态"""
        state = AgentState(
            task_id="test_123",
            task_type="brand_health",
            params={"brand_name": "Test"},
        )
        
        assert state["task_id"] == "test_123"
        assert state["task_type"] == "brand_health"
        assert state["params"]["brand_name"] == "Test"


class TestBrandHealthAgent:
    """品牌健康度诊断 Agent 测试"""
    
    def test_agent_initialization(self):
        """测试 Agent 初始化"""
        agent = BrandHealthAgent()
        
        assert agent is not None
        assert agent.template_path == "app/templates/brand_health.html"
    
    def test_agent_with_progress_callback(self):
        """测试带进度回调的 Agent"""
        progress_log = []
        
        def callback(progress: int, message: str):
            progress_log.append((progress, message))
        
        agent = BrandHealthAgent(progress_callback=callback)
        agent.update_progress(50, "测试进度")
        
        assert len(progress_log) == 1
        assert progress_log[0] == (50, "测试进度")
    
    @pytest.mark.asyncio
    async def test_agent_run(self):
        """测试 Agent 执行（使用模拟数据）"""
        agent = BrandHealthAgent()
        
        result = await agent.run({
            "brand_name": "TestBrand",
            "region": "中国大陆",
            "competitors": ["CompetitorA"],
        })
        
        # 验证返回了 HTML 内容
        assert result is not None
        assert "<!DOCTYPE html>" in result or "<html" in result


class TestTikTokInsightAgent:
    """TikTok 社媒洞察 Agent 测试"""
    
    def test_agent_initialization(self):
        """测试 Agent 初始化"""
        agent = TikTokInsightAgent()
        
        assert agent is not None
        assert agent.template_path == "app/templates/tiktok_insight.html"
    
    @pytest.mark.asyncio
    async def test_agent_run(self):
        """测试 Agent 执行（使用模拟数据）"""
        agent = TikTokInsightAgent()
        
        result = await agent.run({
            "category": "美妆",
            "selling_points": ["长效控油"],
        })
        
        assert result is not None
        assert "html" in result.lower()


# ========== 节点测试 ==========

class TestAgentNodes:
    """Agent 节点测试"""
    
    @pytest.mark.asyncio
    async def test_template_parser_node(self):
        """测试模板解析节点"""
        from app.agents.nodes.template_parser import TemplateParserNode
        
        node = TemplateParserNode("app/templates/brand_health.html")
        result = await node.parse()
        
        assert "sections" in result
        assert len(result["sections"]) > 0
    
    @pytest.mark.asyncio
    async def test_data_collector_node(self):
        """测试数据采集节点"""
        from app.agents.nodes.data_collector import DataCollectorNode
        
        node = DataCollectorNode()
        result = await node.collect_all(
            {"brand_name": "TestBrand"},
            "brand_health",
        )
        
        assert "tavily_results" in result
        assert "xiaohongshu_data" in result
        assert "douyin_data" in result


# ========== 运行测试 ==========
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
