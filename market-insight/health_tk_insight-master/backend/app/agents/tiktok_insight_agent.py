"""
Market Insight Agent - TikTok Insight Agent
============================================
TikTok 社媒洞察 Agent，使用 LangGraph 编排工作流。

工作流程：
1. 解析模板 → 2. 采集 TikTok 数据 → 3. 分析卖点策略 → 4. 渲染报告

后续开发方向：
1. 对接 TikTok/抖音数据 API
2. 实现视频内容分析
3. 优化卖点策略提取算法
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


class TikTokInsightAgent(BaseAgent):
    """
    TikTok 社媒洞察 Agent
    
    工作流节点：
    1. parse_template: 解析 TikTok 洞察报告模板
    2. collect_tiktok_data: 采集 TikTok 热门视频数据
    3. analyze_selling_points: 分析卖点策略
    4. generate_insights: 生成创意洞察
    5. render_report: 渲染最终 HTML 报告
    """
    
    def __init__(
        self,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ):
        super().__init__(progress_callback)
        self.template_path = "app/templates/tiktok_insight.html"
    
    def build_graph(self):
        """
        构建 TikTok 洞察工作流
        
        预期结构：
        ```
        START
          │
          ▼
        [parse_template]
          │
          ▼
        [collect_tiktok_data] ──→ 采集热门视频
          │
          ▼
        [analyze_selling_points] ──→ 卖点策略分析
          │
          ▼
        [generate_insights] ──→ 生成创意洞察
          │
          ▼
        [render_report]
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
        执行 TikTok 社媒洞察分析
        
        Args:
            params: {
                "category": "商品品类",
                "selling_points": ["卖点1", "卖点2"]
            }
            
        Returns:
            生成的 HTML 报告内容
        """
        logger.info(f"Starting TikTok insight analysis for: {params.get('category')}")

        task_id = params.get("task_id", "N/A")
        enriched_params = {**params, "task_id": task_id, "task_type": "tiktok_insight"}

        state = self._create_initial_state(
            task_id=task_id,
            task_type="tiktok_insight",
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
