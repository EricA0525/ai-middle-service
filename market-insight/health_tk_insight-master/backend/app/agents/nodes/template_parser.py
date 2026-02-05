"""
Market Insight Agent - Template Parser Node
============================================
模板解析节点，负责解析 HTML 报告模板结构。

功能：
1. 读取 HTML 模板文件
2. 解析 DOM 结构
3. 提取各报告板块定义
4. 生成结构化的模板骨架

后续开发方向：
1. 支持更复杂的模板结构识别
2. 添加模板验证逻辑
3. 支持动态板块配置
"""

from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

from bs4 import BeautifulSoup


class TemplateParserNode:
    """
    模板解析节点
    
    负责解析 HTML 模板，提取报告结构。
    """
    
    def __init__(self, template_path: str, progress_callback=None):
        """
        初始化模板解析器
        
        Args:
            template_path: 模板文件路径
            progress_callback: 可选进度回调 (progress, message)
        """
        self.template_path = Path(template_path)
        self.progress_callback = progress_callback
    
    async def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        节点执行入口（LangGraph 调用）
        
        Args:
            state: 当前工作流状态
            
        Returns:
            更新后的状态
        """
        logger.info(f"Parsing template: {self.template_path}")
        
        try:
            # 解析模板
            template_structure = await self.parse()
            
            # 更新状态
            updated = {
                **state,
                "template_structure": template_structure,
                "report_sections": template_structure.get("sections", []),
                "current_step": "模板解析完成",
                "progress": 20,
            }
            if self.progress_callback:
                self.progress_callback(updated["progress"], updated["current_step"])
            return updated
            
        except Exception as e:
            logger.error(f"Template parsing failed: {e}")
            updated = {
                **state,
                "error": f"模板解析失败: {str(e)}",
            }
            if self.progress_callback:
                self.progress_callback(state.get("progress", 0), "模板解析失败")
            return updated
    
    async def parse(self) -> Dict[str, Any]:
        """
        解析模板结构
        
        返回结构示例：
        {
            "template_name": "brand_health",
            "sections": [
                {
                    "id": "executive_summary",
                    "name": "执行摘要",
                    "type": "text",
                    "css_class": "hero",
                    "subsections": [...]
                },
                ...
            ],
            "styles": {...},
            "charts": [...]
        }
        """
        resolved = self._resolve_template_path(self.template_path)
        if not resolved.exists():
            logger.warning(f"Template file not found, using placeholder: {resolved}")
            return self._get_placeholder_structure()

        html_content = resolved.read_text(encoding="utf-8")
        soup = BeautifulSoup(html_content, "lxml")

        template_name = resolved.stem
        sections = self._extract_sections(soup)
        charts = self._extract_charts(html_content)

        if not sections:
            logger.warning("No sections detected in template, using placeholder structure")
            return self._get_placeholder_structure()

        return {
            "template_name": template_name,
            "sections": sections,
            "charts": charts,
        }

    def _resolve_template_path(self, template_path: Path) -> Path:
        """
        解析模板路径。

        兼容以下两类调用：
        - pytest / 本地开发：以 backend 为 CWD，传入 app/templates/xxx.html
        - 其他运行方式：CWD 不在 backend 时，按项目相对路径兜底解析
        """
        if template_path.is_absolute() and template_path.exists():
            return template_path
        if template_path.exists():
            return template_path

        backend_dir = Path(__file__).resolve().parents[3]
        candidate = backend_dir / template_path
        return candidate

    def _extract_sections(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        从模板中提取报告板块。

        规则：
        - 以 `.card[id]` 或 `.section[id]` 作为一个板块
        - 优先取 `.section-title` / `h2` 文本作为板块名称（保留 emoji）
        """
        sections: List[Dict[str, Any]] = []
        for el in soup.select("div.card[id], div.section[id]"):
            section_id = (el.get("id") or "").strip()
            if not section_id:
                continue
            title = el.select_one(".section-title")
            header = el.find(["h1", "h2", "h3"])
            name = (
                title.get_text(strip=True)
                if title is not None
                else (header.get_text(strip=True) if header else section_id)
            )
            sections.append(
                {
                    "id": section_id,
                    "name": name,
                    "type": "text",
                }
            )
        return sections

    def _extract_charts(self, html_content: str) -> List[Dict[str, Any]]:
        """
        从模板源码中提取 charts 变量引用。

        例如：`charts.trend_chart` -> {"id": "trend_chart", "type": "svg"}
        """
        import re

        chart_ids = sorted(set(re.findall(r"\\bcharts\\.([a-zA-Z0-9_]+)\\b", html_content)))
        charts: List[Dict[str, Any]] = []
        for chart_id in chart_ids:
            chart_type = "line"
            lowered = chart_id.lower()
            if "radar" in lowered:
                chart_type = "radar"
            elif "donut" in lowered or "ring" in lowered:
                chart_type = "donut"
            elif "scatter" in lowered or "matrix" in lowered:
                chart_type = "scatter"
            elif "bar" in lowered or "demo" in lowered:
                chart_type = "bar"
            charts.append({"id": chart_id, "type": chart_type})
        return charts
    
    def _get_placeholder_structure(self) -> Dict[str, Any]:
        """
        获取占位模板结构（开发用）
        
        根据参考 HTML 模板分析得到的结构。
        """
        return {
            "template_name": "brand_health",
            "sections": [
                {
                    "id": "hero",
                    "name": "报告头部",
                    "type": "header",
                    "fields": ["brand_name", "competitors", "region", "date_range"],
                },
                {
                    "id": "executive_summary",
                    "name": "执行摘要",
                    "type": "summary",
                    "subsections": [
                        {"id": "key_findings", "name": "核心发现"},
                        {"id": "kpis", "name": "关键指标"},
                    ],
                },
                {
                    "id": "risk_redlines",
                    "name": "风险红线",
                    "type": "table",
                    "columns": ["风险项", "等级", "触发信号", "建议"],
                },
                {
                    "id": "market_insights",
                    "name": "市场洞察",
                    "type": "mixed",
                    "subsections": [
                        {"id": "trend_chart", "name": "行业热度趋势", "chart_type": "line"},
                        {"id": "competitor_radar", "name": "竞品对比", "chart_type": "radar"},
                        {"id": "competitor_table", "name": "竞品打法对比"},
                        {"id": "market_conclusions", "name": "市场洞察结论"},
                    ],
                },
                {
                    "id": "consumer_insights",
                    "name": "消费者洞察",
                    "type": "mixed",
                    "subsections": [
                        {"id": "demographics", "name": "人群画像", "chart_type": "bar"},
                        {"id": "wordcloud", "name": "需求词云"},
                        {"id": "painpoint_matrix", "name": "痛点机会矩阵", "chart_type": "scatter"},
                    ],
                },
                {
                    "id": "brand_health",
                    "name": "健康度洞察",
                    "type": "dashboard",
                    "subsections": [
                        {"id": "seo_dashboard", "name": "SEO诊断", "status": "disabled"},
                        {"id": "social_audit", "name": "社媒内容审计"},
                    ],
                },
                {
                    "id": "strategy",
                    "name": "策略转化",
                    "type": "mixed",
                    "subsections": [
                        {"id": "swot", "name": "SWOT分析"},
                        {"id": "action_plan", "name": "行动计划"},
                    ],
                },
            ],
            "charts": [
                {"type": "line", "id": "trend_chart"},
                {"type": "radar", "id": "competitor_radar"},
                {"type": "bar", "id": "demographics_chart"},
                {"type": "scatter", "id": "painpoint_matrix"},
            ],
        }
