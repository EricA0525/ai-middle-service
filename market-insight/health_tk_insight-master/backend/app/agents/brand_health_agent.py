"""
Market Insight Agent - Brand Health Agent
==========================================
品牌健康度诊断 Agent，使用 LangGraph 编排工作流。

工作流程：
1. 解析模板 → 2. 采集数据 → 3. 生成内容 → 4. 渲染报告

后续开发方向：
1. 实现各节点的具体逻辑
2. 对接真实数据源 API
3. 优化 LLM 提示词模板
"""

from typing import Any, Callable, Dict, Optional

from loguru import logger

from app.agents.base import BaseAgent
from app.agents.nodes.content_generator import ContentGeneratorNode
from app.agents.nodes.data_collector import DataCollectorNode
from app.agents.nodes.report_renderer import ReportRendererNode
from app.agents.nodes.template_parser import TemplateParserNode
from app.data_sources.douyin import douyin_client
from app.data_sources.tavily_client import tavily_client
from app.data_sources.xiaohongshu import xiaohongshu_client


class BrandHealthAgent(BaseAgent):
    """
    品牌健康度诊断 Agent
    
    工作流节点：
    1. parse_template: 解析品牌健康度报告模板
    2. collect_data: 从各数据源采集品牌相关数据
    3. generate_content: 使用 LLM 生成各板块内容
    4. render_report: 渲染最终 HTML 报告
    """
    
    def __init__(
        self,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ):
        super().__init__(progress_callback)
        self.template_path = "app/templates/brand_health.html"
    
    def build_graph(self):
        """
        构建品牌健康度分析工作流
        
        TODO: 实现 LangGraph StateGraph
        
        预期结构：
        ```
        START
          │
          ▼
        [parse_template] ──→ 解析 HTML 模板结构
          │
          ▼
        [collect_data] ──→ 并行采集多数据源
          │                 ├─ Tavily 全网搜索
          │                 ├─ 小红书 API
          │                 └─ 抖音 API
          ▼
        [generate_content] ──→ LLM 生成各板块内容
          │                     ├─ 市场洞察
          │                     ├─ 消费者分析
          │                     └─ 策略建议
          ▼
        [render_report] ──→ 渲染 HTML + SVG 图表
          │
          ▼
        END
        ```
        """
        try:
            from langgraph.graph import END, StateGraph
        except Exception as e:
            logger.warning(f"LangGraph not available, falling back to sequential run: {e}")
            return None

        graph = StateGraph(dict)

        graph.add_node(
            "parse_template",
            TemplateParserNode(self.template_path, progress_callback=self.update_progress),
        )
        graph.add_node(
            "collect_data",
            DataCollectorNode(
                tavily_client=tavily_client,
                xiaohongshu_client=xiaohongshu_client,
                douyin_client=douyin_client,
                progress_callback=self.update_progress,
            ),
        )
        graph.add_node(
            "generate_content",
            ContentGeneratorNode(progress_callback=self.update_progress),
        )
        graph.add_node(
            "render_report",
            ReportRendererNode(progress_callback=self.update_progress),
        )

        graph.set_entry_point("parse_template")
        graph.add_edge("parse_template", "collect_data")
        graph.add_edge("collect_data", "generate_content")
        graph.add_edge("generate_content", "render_report")
        graph.add_edge("render_report", END)

        return graph.compile()
    
    async def run(self, params: Dict[str, Any]) -> str:
        """
        执行品牌健康度分析
        
        Args:
            params: {
                "brand_name": "品牌名称",
                "competitors": ["竞品1", "竞品2"],
                "region": "目标地区"
            }
            
        Returns:
            生成的 HTML 报告内容
        """
        logger.info(f"Starting brand health analysis for: {params.get('brand_name')}")

        task_id = params.get("task_id", "N/A")
        enriched_params = {**params, "task_id": task_id, "task_type": "brand_health"}

        state = self._create_initial_state(
            task_id=task_id,
            task_type="brand_health",
            params=enriched_params,
        )
        state["template_path"] = self.template_path

        if self.graph is None:
            self.graph = self.build_graph()

        if self.graph is not None:
            final_state = await self.graph.ainvoke(state)
            if final_state.get("error"):
                raise RuntimeError(final_state["error"])
            return final_state.get("html_report", "")

        # Fallback: sequential execution (keeps behavior if LangGraph unavailable)
        state = await TemplateParserNode(self.template_path, progress_callback=self.update_progress)(
            state
        )
        if state.get("error"):
            raise RuntimeError(state["error"])

        state = await DataCollectorNode(
            tavily_client=tavily_client,
            xiaohongshu_client=xiaohongshu_client,
            douyin_client=douyin_client,
            progress_callback=self.update_progress,
        )(state)
        if state.get("error"):
            raise RuntimeError(state["error"])

        state = await ContentGeneratorNode(progress_callback=self.update_progress)(state)
        if state.get("error"):
            raise RuntimeError(state["error"])

        state = await ReportRendererNode(progress_callback=self.update_progress)(state)
        if state.get("error"):
            raise RuntimeError(state["error"])

        return state.get("html_report", "")
