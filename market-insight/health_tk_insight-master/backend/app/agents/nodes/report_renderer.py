"""
Market Insight Agent - Report Renderer Node
============================================
报告渲染节点，将生成的内容渲染为最终 HTML 报告。

功能：
1. 将各板块内容填充到 HTML 模板
2. 渲染 SVG 图表
3. 输出完整的自包含 HTML 文件

设计思想：
1. 使用 Jinja2 模板引擎
2. SVG 图表内联（无需 JS）
3. 完全自包含的 HTML（便于分发）

后续开发方向：
1. 实现完整的 SVG 图表生成
2. 添加更多图表类型支持
3. 优化 HTML 输出体积
"""

from datetime import datetime
from typing import Any, Dict, Optional

from loguru import logger

from app.utils.html_renderer import html_renderer


class ReportRendererNode:
    """
    报告渲染节点
    
    将生成的内容渲染为最终的 HTML 报告。
    """
    
    def __init__(self, renderer=None, progress_callback=None):
        """
        初始化报告渲染器
        
        Args:
            renderer: HTMLRenderer 实例（默认使用全局 html_renderer）
            progress_callback: 可选进度回调 (progress, message)
        """
        self.renderer = renderer or html_renderer
        self.progress_callback = progress_callback
    
    async def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        节点执行入口（LangGraph 调用）
        """
        logger.info("Rendering HTML report...")
        
        try:
            template_structure = state.get("template_structure", {})
            generated_content = state.get("generated_content", {})
            svg_charts = state.get("svg_charts", {})
            params = state.get("params", {})
            
            # 渲染 HTML 报告
            html_report = await self.render(
                template_structure,
                generated_content,
                svg_charts,
                params,
            )
            
            updated = {
                **state,
                "html_report": html_report,
                "current_step": "报告渲染完成",
                "progress": 100,
            }
            if self.progress_callback:
                self.progress_callback(updated["progress"], updated["current_step"])
            return updated
            
        except Exception as e:
            logger.error(f"Report rendering failed: {e}")
            updated = {
                **state,
                "error": f"报告渲染失败: {str(e)}",
            }
            if self.progress_callback:
                self.progress_callback(state.get("progress", 0), "报告渲染失败")
            return updated
    
    async def render(
        self,
        template_structure: Dict,
        generated_content: Dict[str, str],
        svg_charts: Dict[str, Any],
        params: Dict,
    ) -> str:
        """
        渲染完整 HTML 报告
        
        TODO: 实现完整的渲染逻辑
        
        实现步骤：
        1. 加载 HTML 模板
        2. 填充各板块内容
        3. 渲染 SVG 图表
        4. 内联 CSS 样式
        5. 输出完整 HTML
        """
        template_name = self._resolve_template_name(template_structure, params)
        context = {
            "params": params,
            "sections": generated_content,
            "charts": svg_charts,
            "metadata": {
                "task_id": params.get("task_id"),
                "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            },
        }

        return self.renderer.render(template_name, context)

    def _resolve_template_name(self, template_structure: Dict, params: Dict) -> str:
        """
        根据模板结构或任务类型选择模板文件名。
        """
        name = template_structure.get("template_name")
        if name:
            if not str(name).endswith(".html"):
                return f"{name}.html"
            return str(name)

        task_type = params.get("task_type")
        if task_type == "tiktok_insight":
            return "tiktok_insight.html"
        return "brand_health.html"
    
    def _generate_mock_html(
        self,
        template_structure: Dict,
        generated_content: Dict[str, str],
        params: Dict,
    ) -> str:
        """
        生成模拟 HTML 报告（开发用）
        
        保持与参考模板一致的视觉风格。
        """
        brand_name = params.get("brand_name", "Unknown")
        region = params.get("region", "N/A")
        competitors = params.get("competitors", [])
        
        # 构建板块 HTML
        sections_html = ""
        for section in template_structure.get("sections", []):
            section_id = section.get("id")
            section_name = section.get("name")
            content = generated_content.get(section_id, "[待生成]")
            
            sections_html += f"""
            <div class="card" id="{section_id}">
                <h2>{section_name}</h2>
                <div class="content">{content}</div>
            </div>
            """
        
        # 返回完整 HTML
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>品牌洞察报告 - {brand_name}</title>
    <style>
        :root {{
            --bg: #0b0d12;
            --panel: #111522;
            --text: #e9ecf3;
            --muted: #aab3c5;
            --border: rgba(255,255,255,.10);
            --accent: #7aa2ff;
            --good: #5ee38f;
            --warn: #ffd36b;
            --bad: #ff6b6b;
            --radius: 14px;
            --shadow: 0 12px 40px rgba(0,0,0,.35);
        }}
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            font-family: system-ui, -apple-system, sans-serif;
            color: var(--text);
            background: radial-gradient(1200px 600px at 30% -10%, rgba(122,162,255,.25), transparent 55%),
                        radial-gradient(900px 500px at 80% 10%, rgba(94,227,143,.12), transparent 50%),
                        linear-gradient(180deg, #07080c, var(--bg));
            min-height: 100vh;
        }}
        .wrap {{ max-width: 1100px; margin: 0 auto; padding: 36px 18px 80px; }}
        .hero {{
            padding: 28px 22px;
            background: linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.03));
            border: 1px solid var(--border);
            border-radius: var(--radius);
            box-shadow: var(--shadow);
            margin-bottom: 20px;
        }}
        .hero h1 {{ margin: 0 0 12px; font-size: 28px; }}
        .meta {{ color: var(--muted); font-size: 13px; }}
        .meta span {{ margin-right: 20px; }}
        .card {{
            background: linear-gradient(180deg, rgba(255,255,255,.05), rgba(255,255,255,.02));
            border: 1px solid var(--border);
            border-radius: var(--radius);
            box-shadow: var(--shadow);
            padding: 20px;
            margin-bottom: 16px;
        }}
        .card h2 {{
            margin: 0 0 16px;
            font-size: 18px;
            color: var(--accent);
        }}
        .content {{ color: var(--muted); line-height: 1.7; }}
        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid var(--border);
            text-align: center;
            color: var(--muted);
            font-size: 12px;
        }}
        .dev-notice {{
            background: rgba(255,211,107,.15);
            border: 1px solid rgba(255,211,107,.3);
            border-radius: 8px;
            padding: 16px;
            margin: 20px 0;
        }}
    </style>
</head>
<body>
    <div class="wrap">
        <div class="hero">
            <h1>🎯 品牌洞察报告</h1>
            <div class="meta">
                <span><strong>品牌：</strong>{brand_name}</span>
                <span><strong>地区：</strong>{region}</span>
                <span><strong>竞品：</strong>{', '.join(competitors) if competitors else 'N/A'}</span>
            </div>
        </div>
        
        <div class="dev-notice">
            <p><strong>⚠️ 开发版本</strong></p>
            <p>此报告由 Agent 框架生成，内容为占位数据。完整功能需要：</p>
            <ul>
                <li>完成 LangGraph 节点实现</li>
                <li>对接真实数据源 API（小红书、抖音、Tavily）</li>
                <li>优化 LLM 提示词模板</li>
                <li>实现 SVG 动态图表生成</li>
            </ul>
        </div>
        
        {sections_html}
        
        <div class="footer">
            <p>Generated by Market Insight Agent | {params.get('task_id', 'N/A')}</p>
        </div>
    </div>
</body>
</html>"""
