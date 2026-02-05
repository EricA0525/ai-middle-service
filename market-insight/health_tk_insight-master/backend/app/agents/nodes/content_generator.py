"""
Market Insight Agent - Content Generator Node
==============================================
内容生成节点，使用 LLM 生成报告各板块的内容。

功能：
1. 根据采集的数据生成各板块内容
2. 生成洞察性文本
3. 生成图表数据点

设计思想：
1. 分板块生成，便于并行和重试
2. 结构化提示词模板
3. 支持多 LLM 后端（OpenAI 兼容）

后续开发方向：
1. 优化提示词模板
2. 添加 Few-shot 示例
3. 实现内容质量校验
"""

import html
from typing import Any, Dict, List, Optional

from loguru import logger

from app.utils.svg_generator import svg_generator
from app.llm.openai_compat import OpenAICompatLLM


class ContentGeneratorNode:
    """
    内容生成节点
    
    使用 LLM 根据采集的数据生成报告内容。
    """
    
    def __init__(self, llm_client=None, progress_callback=None):
        """
        初始化内容生成器
        
        Args:
            llm_client: LLM 客户端（OpenAI 兼容）
            progress_callback: 可选进度回调 (progress, message)
        """
        self.llm = llm_client
        self._default_llm = None
        self.progress_callback = progress_callback
    
    async def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        节点执行入口（LangGraph 调用）
        """
        logger.info("Generating report content...")
        
        template_structure = state.get("template_structure", {})
        collected_data = state.get("collected_data", {})
        
        try:
            # 生成各板块内容
            generated_content = await self.generate_all_sections(
                template_structure,
                collected_data,
            )
            
            # 生成图表数据
            svg_charts = await self.generate_chart_data(
                template_structure,
                collected_data,
            )
            
            updated = {
                **state,
                "generated_content": generated_content,
                "svg_charts": svg_charts,
                "current_step": "内容生成完成",
                "progress": 80,
            }
            if self.progress_callback:
                self.progress_callback(updated["progress"], updated["current_step"])
            return updated
            
        except Exception as e:
            logger.error(f"Content generation failed: {e}")
            updated = {
                **state,
                "error": f"内容生成失败: {str(e)}",
            }
            if self.progress_callback:
                self.progress_callback(state.get("progress", 0), "内容生成失败")
            return updated
    
    async def generate_all_sections(
        self,
        template_structure: Dict,
        collected_data: Dict,
    ) -> Dict[str, str]:
        """
        生成所有板块内容
        
        Args:
            template_structure: 模板结构
            collected_data: 采集的数据
            
        Returns:
            各板块的生成内容
        """
        sections = template_structure.get("sections", [])
        generated = {}
        
        for section in sections:
            section_id = section.get("id")
            section_name = section.get("name")
            
            logger.debug(f"Generating content for section: {section_name}")
            
            # 检查是否为禁用板块
            if section.get("status") == "disabled":
                generated[section_id] = self._get_disabled_content(section_name)
                continue
            
            # 生成板块内容
            generated[section_id] = await self._generate_section(
                section,
                collected_data,
            )
        
        return generated
    
    async def _generate_section(
        self,
        section: Dict,
        collected_data: Dict,
    ) -> str:
        """
        生成单个板块内容
        
        TODO: 实现真实 LLM 调用
        
        实现步骤：
        1. 根据板块类型选择提示词模板
        2. 注入采集的数据
        3. 调用 LLM 生成
        4. 后处理（格式化、校验）
        """
        section_id = section.get("id")
        section_type = section.get("type")
        
        prompt = self._build_prompt(section, collected_data)

        llm = self.llm or self._get_default_llm()
        if llm is not None and getattr(llm, "is_configured", lambda: True)():
            try:
                resp = await llm.generate_html(prompt)
                if resp.content:
                    return self._sanitize_html_fragment(resp.content)
            except Exception as e:
                logger.warning(f"LLM generation failed, fallback to deterministic: {e}")

        return self._fallback_section_html(section_id, section.get("name"), collected_data)
    
    async def generate_chart_data(
        self,
        template_structure: Dict,
        collected_data: Dict,
    ) -> Dict[str, str]:
        """
        生成 SVG 图表代码
        
        当前为开发阶段：使用少量 mock 数据生成占位图表，
        后续可根据 collected_data 生成真实数据点。
        """
        charts = template_structure.get("charts", [])
        svg_map: Dict[str, str] = {}
        
        for chart in charts:
            chart_id = chart.get("id")
            chart_type = chart.get("type")
            
            if not chart_id:
                continue

            svg_map[chart_id] = self._generate_svg_chart(chart_type, chart_id)
        
        return svg_map

    def _generate_svg_chart(self, chart_type: str, chart_id: str) -> str:
        """根据图表类型生成 SVG（开发阶段使用 mock 数据）"""
        if chart_type == "line":
            data = [{"x": f"W{i}", "y": 40 + i * 3} for i in range(1, 9)]
            return svg_generator.generate_line_chart(data, title=chart_id)
        if chart_type == "bar":
            data = [
                {"label": "18-24", "value": 28},
                {"label": "25-34", "value": 36},
                {"label": "35-44", "value": 22},
                {"label": "45+", "value": 14},
            ]
            return svg_generator.generate_bar_chart(data)
        if chart_type == "radar":
            dims = ["声量", "内容活跃", "渠道覆盖", "产品力", "口碑"]
            data = [{"name": "Brand", "values": [78, 66, 54, 82, 70]}]
            return svg_generator.generate_radar_chart(data, dimensions=dims)
        if chart_type == "donut":
            data = [
                {"label": "核心人群", "value": 55},
                {"label": "潜力人群", "value": 30},
                {"label": "其他", "value": 15},
            ]
            return svg_generator.generate_donut_chart(data)
        if chart_type == "scatter":
            data = [
                {"x": 20, "y": 30, "label": "低价"},
                {"x": 60, "y": 40, "label": "口碑"},
                {"x": 80, "y": 75, "label": "成分"},
                {"x": 40, "y": 85, "label": "便携"},
            ]
            return svg_generator.generate_scatter_chart(data)

        return svg_generator.generate_line_chart([], title=f"{chart_id} (unknown)")
    
    def _get_disabled_content(self, section_name: str) -> str:
        """获取禁用板块的占位内容"""
        return f"""
        <div class="disabled-section">
            <p>🚧 {section_name} - 此功能暂未启用，敬请期待</p>
        </div>
        """
    
    def _build_prompt(
        self,
        section: Dict,
        collected_data: Dict,
    ) -> str:
        """
        构建 LLM 提示词
        
        TODO: 实现结构化提示词模板
        
        提示词设计原则：
        1. 明确角色定义
        2. 清晰的任务描述
        3. 输出格式规范
        4. 提供上下文数据
        5. Few-shot 示例（可选）
        """
        section_id = section.get("id")
        section_name = section.get("name")
        
        # 采集数据格式化 - 提取所有数据源
        tavily_data = collected_data.get("tavily_results", [])
        xiaohongshu_data = collected_data.get("xiaohongshu_data", [])
        douyin_data = collected_data.get("douyin_data", [])
        
        data_summary = self._format_data_for_prompt(tavily_data, xiaohongshu_data, douyin_data)
        params = collected_data.get("params", {})
        brand_name = params.get("brand_name", "目标品牌")
        region = params.get("region", "未指定")
        credibility_rules = self._get_credibility_rules()
        
        # 完整提示词模板（包含数据可信度规则）
        prompt_templates = {
            "executive_summary": f"""
你是一位专业的市场分析师。请根据以下采集数据，生成一份执行摘要。

品牌：{brand_name}
地区：{region}

采集数据：
{data_summary}

{credibility_rules}

要求：
1. 提炼 3-5 个核心发现
2. 每个发现必须有数据支撑（引用采集数据中的内容）
3. 风格简洁专业
4. 字数控制在 300 字以内

输出格式（纯 HTML 片段）：
<ul>
<li><b>发现1</b>：描述... <span class="small">证据：引自采集数据</span></li>
...
</ul>
""",
            "risk_redlines": f"""
你是风险管理专家。请根据采集数据，识别 {brand_name} 可能面临的风险。

采集数据：
{data_summary}

{credibility_rules}

要求：
1. 识别 2-4 个潜在风险点（如口碑波动、竞品动态、政策变化等）
2. 每个风险点说明触发信号和建议对策
3. 不要编造具体损失金额或百分比

输出格式（纯 HTML）：
<p>当前存在明显风险：...</p>
<ul>
<li>风险1：说明...</li>
...
</ul>
<p>建议...</p>
""",
            "market_insights": f"""
你是市场洞察专家。请分析 {brand_name} 的市场表现。

采集数据：
{data_summary}

{credibility_rules}

要求：
1. 基于公开数据分析市场趋势
2. 不要编造市场份额、排名等具体数字
3. 可以描述相对趋势（如"市场地位稳固"、"竞争压力增大"）
4. 100-200字

输出格式（纯 HTML）：简短分析段落
""",
            "consumer_insights": f"""
你是消费者研究专家。请分析 {brand_name} 的消费者画像。

采集数据：
{data_summary}

{credibility_rules}

要求：
1. 描述目标消费者特征（基于采集数据推断）
2. 不要编造人口统计数据（如"25-35岁女性占比68%"）
3. 可以用定性描述（如"核心用户偏向年轻群体"）

输出格式（纯 HTML）：简短分析段落
""",
            "brand_health": f"""
你是品牌诊断专家。请评估 {brand_name} 的品牌健康状况。

采集数据：
{data_summary}

{credibility_rules}

要求：
1. 从品牌认知、口碑、竞争力等维度分析
2. 不要编造健康度评分或指数
3. 使用定性描述（如"品牌认知度较高"、"口碑表现稳定"）

输出格式（纯 HTML）：包含简短段落和可选表格
""",
            "strategy": f"""
你是战略咨询专家。请为 {brand_name} 提供策略建议。

采集数据：
{data_summary}

{credibility_rules}

要求：
1. 提供 2-4 条可执行的策略建议
2. 建议应基于前述分析，不要空泛
3. 不要承诺具体效果数字（如"预计提升ROI 30%"）

输出格式（纯 HTML）：简短建议列表
""",
        }
        
        template = prompt_templates.get(section_id)
        if template is None:
            # 通用兜底模板 - 也应该使用所有数据源
            return f"""
你是市场分析师。请为 {brand_name} 生成 {section_name} 内容。

采集数据：
{data_summary}

{credibility_rules}

输出格式：纯 HTML 片段，100-200字
"""
        
        # 直接返回模板（已使用 f-string）
        return template

    def _get_credibility_rules(self) -> str:
        """获取通用数据可信度规则"""
        return """
【重要：数据可信度与权威度规则】

数据源优先级（从高到低）：
1. 小红书/抖音官方API数据（用户真实互动、内容表现）- 最权威
2. 其他社交媒体平台官方数据
3. 联网搜索数据（新闻报道、行业报告）- 参考价值，需交叉验证
4. 推断性数据 - 需明确标注为"推断"

数据使用规则：
1. 优先引用小红书/抖音API数据（互动量、内容数、用户反馈等），这些是真实消费者行为
2. 联网搜索数据作为补充背景，不作为核心论据
3. 只引用"采集数据"中明确提到的信息，必须标注来源
4. 禁止编造任何具体数字（如"市场份额32%"），除非数据中明确包含
5. 禁止捏造企业内部数据（财务、员工数等），这会严重降低报告可信度
6. 数据不足时用"根据公开信息..."或"有待进一步调研..."
7. 使用相对表述（如"呈上升趋势"），避免杜撰百分比
8. 引用格式：<span class="small">来源：小红书API/抖音API/搜索数据</span>
"""

    def _format_data_for_prompt(self, tavily_results: list, xiaohongshu_data: list = None, douyin_data: list = None) -> str:
        """将采集数据格式化为提示词可用的文本，按权威度分组"""
        sections = []
        
        # 最高权威：小红书API数据
        if xiaohongshu_data and len(xiaohongshu_data) > 0:
            sections.append("### 【最高权威】小红书官方API数据")
            for i, item in enumerate(xiaohongshu_data[:5], 1):
                title = item.get("title", "")
                content = item.get("content", "")[:150]
                likes = item.get("likes", 0)
                comments = item.get("comments", 0)
                sections.append(f"{i}. 【{title}】\n   内容：{content}\n   互动：{likes}赞 {comments}评论\n   来源：小红书API")
        
        # 次高权威：抖音API数据
        if douyin_data and len(douyin_data) > 0:
            sections.append("\n### 【高权威】抖音官方API数据")
            for i, item in enumerate(douyin_data[:5], 1):
                title = item.get("title", "")
                views = item.get("views", 0)
                likes = item.get("likes", 0)
                shares = item.get("shares", 0)
                sections.append(f"{i}. 【{title}】\n   互动：{views}播放 {likes}赞 {shares}分享\n   来源：抖音API")
        
        # 参考级别：联网搜索数据
        if tavily_results and len(tavily_results) > 0:
            sections.append("\n### 【参考背景】联网搜索数据")
            for i, item in enumerate(tavily_results[:5], 1):
                title = item.get("title", "")
                snippet = item.get("snippet", "")[:200]
                source = item.get("source", "")
                sections.append(f"{i}. 【{title}】\n   内容：{snippet}\n   来源：{source}（搜索数据，需交叉验证）")
        
        if not sections:
            return "（暂无采集数据）"
        
        return "\n".join(sections)

    def _get_default_llm(self) -> Optional[OpenAICompatLLM]:
        if self._default_llm is not None:
            return self._default_llm
        llm = OpenAICompatLLM()
        if not llm.is_configured():
            self._default_llm = None
            return None
        self._default_llm = llm
        return llm

    def _fallback_section_html(
        self, section_id: str, section_name: Optional[str], collected_data: Dict[str, Any]
    ) -> str:
        """
        无 LLM 时的兜底内容（确定性）。

        输出为 HTML 片段，便于直接插入模板。
        """
        safe_name = html.escape(section_name or section_id or "Section")
        tavily = collected_data.get("tavily_results", []) or []
        xhs = collected_data.get("xiaohongshu_data", []) or []
        douyin = collected_data.get("douyin_data", []) or []
        params = collected_data.get("params", {}) or {}

        def esc(v: Any) -> str:
            return html.escape(str(v)) if v is not None else ""

        if section_id in ("executive_summary", "category_trends"):
            return (
                f"<p><b>{safe_name}</b>（开发阶段：无 LLM，基于采集数据生成摘要）</p>"
                f"<ul>"
                f"<li>查询对象：{esc(params.get('brand_name') or params.get('category') or 'N/A')}</li>"
                f"<li>Tavily 结果：{len(tavily)} 条</li>"
                f"<li>小红书结果：{len(xhs)} 条</li>"
                f"<li>抖音结果：{len(douyin)} 条</li>"
                f"</ul>"
            )

        if section_id in ("market_insights", "hot_videos"):
            items = []
            for r in tavily[:5]:
                title = esc(r.get("title"))
                url = esc(r.get("url"))
                items.append(f'<li><a href="{url}" target="_blank">{title}</a></li>')
            li = "".join(items) or "<li>暂无可展示数据</li>"
            return f"<h3>{safe_name}</h3><ul>{li}</ul>"

        if section_id in ("consumer_insights", "creator_ecosystem"):
            return (
                f"<h3>{safe_name}</h3>"
                f"<p>小红书样本：{len(xhs)}，抖音样本：{len(douyin)}（mock 数据）。</p>"
            )

        if section_id in ("risk_redlines",):
            return (
                '<table class="table">'
                "<thead><tr><th>风险项</th><th>等级</th><th>触发信号</th><th>建议</th></tr></thead>"
                "<tbody>"
                "<tr><td>口碑波动</td><td>中</td><td>负面评论占比上升</td><td>优化FAQ与客服话术</td></tr>"
                "<tr><td>竞品加投</td><td>高</td><td>竞品频次/预算提升</td><td>调整素材与投放结构</td></tr>"
                "</tbody></table>"
            )

        return f"<p>{safe_name}：暂无内容（等待 LLM/规则引擎接入）。</p>"

    def _sanitize_html_fragment(self, fragment: str) -> str:
        """
        基础清洗：
        - 移除 <script>/<style>
        - 若误返回完整 HTML，则抽取 <body> 内容
        - 仅用于“报告内部片段”，不做完整的安全白名单
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(fragment or "", "lxml")

        for tag in soup.find_all(["script", "style"]):
            tag.decompose()

        body = soup.find("body")
        if body is not None:
            return "".join(str(x) for x in body.contents).strip()

        # If it is a full HTML doc without body, fallback to soup contents
        html_tag = soup.find("html")
        if html_tag is not None:
            return "".join(str(x) for x in html_tag.contents).strip()

        return str(soup).strip()
