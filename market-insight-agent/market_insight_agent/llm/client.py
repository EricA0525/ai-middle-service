"""
LLM 客户端模块

封装 OpenAI SDK，支持自定义 base_url，用于调用兼容 OpenAI 格式的大语言模型。
集成 Tavily 搜索用于获取实时数据。
"""

import json
import random
import time
from typing import Any, Optional
from openai import OpenAI

from ..config import settings
from ..logging_config import get_logger

logger = get_logger(__name__)


class LLMClient:
    """LLM 客户端封装类"""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        """
        初始化 LLM 客户端
        
        Args:
            api_key: OpenAI API Key，默认从配置读取
            base_url: API Base URL，默认从配置读取
            model: 模型名称，默认从配置读取
        """
        self.api_key = api_key or settings.openai_api_key
        self.base_url = base_url or settings.openai_base_url
        self.model = model or settings.model_name
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
        
        # 延迟加载 Tavily 客户端
        self._tavily_client = None

        # ── Phase 1: Token 用量追踪 ──
        self._total_prompt_tokens: int = 0
        self._total_completion_tokens: int = 0
        self._total_tokens: int = 0
        self._total_calls: int = 0

    def _call_with_retries(self, fn, *, max_attempts: int = 3, base_sleep_s: float = 1.0):
        """
        对常见的瞬时网络/网关错误做重试，采用指数退避 + jitter。
        """
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return fn()
            except Exception as e:
                last_exc = e
                name = type(e).__name__
                msg = str(e)
                transient = (
                    "Connection error" in msg
                    or "Read timed out" in msg
                    or "timed out" in msg.lower()
                    or name in {"APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError"}
                )
                if (not transient) or attempt >= max_attempts:
                    raise
                sleep_s = base_sleep_s * (2 ** (attempt - 1))
                jitter = random.uniform(0, sleep_s * 0.3)
                total_sleep = sleep_s + jitter
                logger.warning(
                    "llm_retry",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    sleep_s=round(total_sleep, 2),
                    error=f"{name}: {msg[:120]}",
                )
                time.sleep(total_sleep)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Unknown retry error")

    def _track_usage(self, response: Any) -> None:
        """累加 token 用量。"""
        usage = getattr(response, "usage", None)
        if usage:
            self._total_prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            self._total_completion_tokens += getattr(usage, "completion_tokens", 0) or 0
            self._total_tokens += getattr(usage, "total_tokens", 0) or 0
        self._total_calls += 1

    def get_token_usage(self) -> dict[str, int]:
        """取得累计 token 用量。"""
        return {
            "total_prompt_tokens": self._total_prompt_tokens,
            "total_completion_tokens": self._total_completion_tokens,
            "total_tokens": self._total_tokens,
            "total_calls": self._total_calls,
        }

    def _get_tavily_client(self):
        """获取 Tavily 客户端（懒加载）"""
        if self._tavily_client is None:
            try:
                from ..search import get_tavily_client
                self._tavily_client = get_tavily_client()
            except Exception as e:
                logger.warning("tavily_init_failed", error=str(e))
                self._tavily_client = None
        return self._tavily_client

    def ping(self, timeout_s: float = 30.0) -> dict:
        """
        检查 LLM 是否可用（最小调用）。

        Returns:
            dict: { ok, latency_ms, error }
        """
        start = time.perf_counter()
        try:
            resp = self._call_with_retries(
                lambda: self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "Reply with exactly: pong"},
                        {"role": "user", "content": "ping"},
                    ],
                    temperature=0,
                    max_tokens=10,
                    timeout=timeout_s,
                ),
                max_attempts=3,
                base_sleep_s=0.8,
            )
            content = (resp.choices[0].message.content or "").strip()
            lower = content.lower()
            # Connectivity check: some OpenAI-compatible gateways may echo the user
            # message ("ping") or add extra text. Treat a successful response as
            # online, while keeping the unexpected reply for debugging.
            ok = bool(content) and (lower == "pong" or lower == "ping" or "pong" in lower)
            return {
                "ok": ok,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "reply": content,
                "error": None if ok else f"Unexpected reply: {content!r}",
            }
        except Exception as e:
            return {
                "ok": False,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "error": f"{type(e).__name__}: {str(e)}",
            }

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout_s: float = 90.0,
        retry_attempts: int = 3,
    ) -> str:
        """
        生成文本
        
        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大 token 数
            
        Returns:
            生成的文本内容
        """
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        response = self._call_with_retries(
            lambda: self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout_s,
            ),
            max_attempts=max(1, int(retry_attempts)),
            base_sleep_s=1.0,
        )

        self._track_usage(response)
        content = response.choices[0].message.content or ""
        logger.debug(
            "llm_generate",
            model=self.model,
            prompt_len=len(prompt),
            response_len=len(content),
            tokens=getattr(getattr(response, "usage", None), "total_tokens", None),
        )
        return content

    def generate_report_section(
        self,
        section_name: str,
        section_description: str,
        brand: str,
        competitors: list[str],
        context_data: dict,
        template_structure: dict,
        temperature: float = 0.3,
        retry_reason: Optional[str] = None,
        timeout_s: float = 90.0,
        retry_attempts: int = 1,
        context_compression_ratio: float = 1.0,
    ) -> str:
        """
        生成报告的某个模块内容
        
        Args:
            section_name: 模块名称
            section_description: 模块描述
            brand: 目标品牌
            competitors: 竞品列表
            context_data: 上下文数据（来自数据源）
            template_structure: 模板结构信息
            
        Returns:
            生成的 HTML 内容片段
        """
        source_links: list[dict] = []
        try:
            llm_search = context_data.get("llm_search") if isinstance(context_data, dict) else None
            meta = llm_search.get("_meta") if isinstance(llm_search, dict) else None
            links = meta.get("source_links") if isinstance(meta, dict) else None
            if isinstance(links, list):
                source_links = links[:10]
        except Exception:
            source_links = []

        # 轻量压缩：仅在极端超长输入时截断，避免常规场景丢失关键信息。
        def _compact(value: dict, limit: int = 120000):
            text = json.dumps(value, ensure_ascii=False)
            if len(text) <= limit:
                return value
            return {
                "_truncated": True,
                "head": text[: int(limit * 0.7)],
                "tail": text[-int(limit * 0.25):],
                "original_chars": len(text),
            }

        ratio = float(context_compression_ratio or 1.0)
        if ratio <= 0 or ratio > 1:
            ratio = 1.0
        context_limit = max(int(120000 * ratio), 6000)
        template_limit = max(int(180000 * ratio), 8000)

        compact_context_data = _compact(
            context_data if isinstance(context_data, dict) else {"raw": context_data},
            limit=context_limit,
        )
        compact_template_structure = _compact(
            template_structure if isinstance(template_structure, dict) else {"raw": template_structure},
            limit=template_limit,
        )

        system_prompt = """你是一个专业的市场分析师，擅长撰写品牌洞察报告。
你需要根据提供的数据和模板结构，生成对应的 HTML 内容片段。

要求：
1. 保持专业、客观的语气
2. 量化原则（避免伪数据）：
   - 只有在上下文中存在可核验来源/证据时才给出具体数字/百分比，并在同一句末尾内嵌来源链接
   - 若缺乏权威量化数据：改用定性描述（主力/次主力/高-中-低/排序），不要编造百分比/规模数字
3. 生成的 HTML 必须符合给定的结构（仅复用结构和 class，不得复用模板原句）
4. 使用中文撰写
5. 只输出该模块的 HTML 片段，不要输出完整 HTML 文档（不要包含 <html>/<head>/<body>）
6. 不要包含 <script> 标签或任何可执行代码
7. 直接输出 HTML 代码，不要包含 markdown 代码块标记
8. 仅输出一个模块，不得输出多个 section
9. 若模块不是 hero，输出中必须包含且仅包含一个 <h2 class=\"section-title\">，并保证文本等于给定 section_name
10. 禁止复用模板示例品牌/示例文案；若数据不足，生成与目标品牌相关的通用分析句
11. 优先复用 section_shell_html 的布局骨架（id/class/grid/card 结构），在该骨架内填充新内容
12. 每个模块至少输出 3 个要点或 2 个信息块，不得只输出错误提示/占位语
13. 若上下文较长，请优先使用“模块描述 + section_shell_html + llm_search摘要”完成内容
14. 必须覆盖模板模块中的全部关键卡片位点（至少保持与 section_shell_html 同等的 glass-card/card 主体数量）
15. 不允许留空模块；若证据不足，可使用AI推断补全，但仍需输出完整信息块
16. 不允许留下空白微模块：
   - `span`（如 tag-pill、检索词行、徽标/短标签）不得为空
   - 条形图文字位（如 `div.chart-bar-fill`）必须包含可见名词/短语；若为定性，则不要写百分比
17. 禁止保留或输出模板数字占位结构（例如 `.count-up` / `data-target`），也不要复述“621/691”等模板占位数字
18. 若内容引用了实时搜索数据/来源，请把外链引用“嵌入在引用原句位置”，不要只在文末汇总：
   - 在引用句末尾紧跟一个可点击来源链接，例如：
     <a class="source-link" href="https://example.com" target="_blank" rel="noopener noreferrer">[来源]</a>
   - href 必须来自“可用来源链接”列表（或上下文中明确出现的 URL），不得编造 URL
19. 禁止输出任何思考/推理/步骤说明（包括 `<think>` 标签或“思考：”“分析：”等前缀），只输出最终 HTML"""

        prompt = f"""请为以下品牌生成报告的「{section_name}」模块：

## 目标品牌
{brand}

## 竞品品牌
{', '.join(competitors)}

## 模块描述
{section_description}

## 模块标题约束
- section_name 必须为：{section_name}

## 重试原因（如有）
{retry_reason or '（无）'}

## 可用来源链接（仅用于外链引用；请勿编造 URL）
{json.dumps(source_links, ensure_ascii=False, indent=2)}

## 参考数据
{json.dumps(compact_context_data, ensure_ascii=False, indent=2)}

## 模板结构
{json.dumps(compact_template_structure, ensure_ascii=False, indent=2)}

请根据以上信息，生成符合模板结构的 HTML 内容。直接输出 HTML 代码，不需要 markdown 代码块包裹。"""

        return self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=8192,
            timeout_s=timeout_s,
            retry_attempts=retry_attempts,
        )

    def generate_tiktok_insight_section(
        self,
        section_name: str,
        section_description: str,
        category_name: str,
        product_selling_points: list[str],
        context_data: dict,
        template_structure: dict,
        temperature: float = 0.3,
        retry_reason: Optional[str] = None,
        timeout_s: float = 90.0,
        retry_attempts: int = 1,
        context_compression_ratio: float = 1.0,
    ) -> str:
        """
        生成 TikTok 社媒洞察报告的某个模块内容（HTML 片段）。
        """
        source_links: list[dict] = []
        try:
            llm_search = context_data.get("llm_search") if isinstance(context_data, dict) else None
            meta = llm_search.get("_meta") if isinstance(llm_search, dict) else None
            links = meta.get("source_links") if isinstance(meta, dict) else None
            if isinstance(links, list):
                source_links = links[:10]
        except Exception:
            source_links = []

        def _compact(value: dict, limit: int = 120000):
            text = json.dumps(value, ensure_ascii=False)
            if len(text) <= limit:
                return value
            return {
                "_truncated": True,
                "head": text[: int(limit * 0.7)],
                "tail": text[-int(limit * 0.25):],
                "original_chars": len(text),
            }

        ratio = float(context_compression_ratio or 1.0)
        if ratio <= 0 or ratio > 1:
            ratio = 1.0
        context_limit = max(int(120000 * ratio), 6000)
        template_limit = max(int(180000 * ratio), 8000)

        compact_context_data = _compact(
            context_data if isinstance(context_data, dict) else {"raw": context_data},
            limit=context_limit,
        )
        compact_template_structure = _compact(
            template_structure if isinstance(template_structure, dict) else {"raw": template_structure},
            limit=template_limit,
        )

        system_prompt = """你是一个专业的社媒策略与内容分析师，擅长撰写 TikTok 社媒洞察报告。
你需要根据提供的数据和模板结构，生成对应的 HTML 内容片段。

要求：
1. 保持专业、客观、可执行的语气
2. 结论要可落地：包含动作建议、优先级或衡量指标
3. 生成的 HTML 必须符合给定的结构（仅复用结构和 class，不得复用模板原句）
3.1 如果模板的 section_id 为 "hero"，必须输出 <header class="header"> 作为根节点（不要输出 div.hero）
3.2 如果模板的 section_id 不是 "hero"，必须输出 <section class="section"> 作为根节点，并包含 <h2 class="section-title">
4. 使用中文撰写
5. 只输出该模块的 HTML 片段，不要输出完整 HTML 文档（不要包含 <html>/<head>/<body>）
6. 不要包含 <script> 标签或任何可执行代码
7. 直接输出 HTML 代码，不要包含 markdown 代码块标记
8. 仅输出一个模块，不得输出多个 section
9. 若模块不是 hero，输出中必须包含且仅包含一个 <h2 class=\"section-title\">，并保证文本等于给定 section_name
10. 优先复用 section_shell_html 的布局骨架（id/class/grid/card 结构），在该骨架内填充新内容
11. 必须覆盖模板模块中的全部关键卡片位点（至少保持与 section_shell_html 同等的 glass-card/card 主体数量）
12. 每个模块至少输出 3 个要点或 2 个信息块，不得只输出错误提示/占位语
13. 不允许留空模块；若证据不足，可使用AI推断补全，但仍需输出完整信息块
14. 若内容引用了实时搜索数据/来源，请把外链引用“嵌入在引用原句位置”，不要只在文末汇总：
   - 在引用句末尾紧跟一个可点击来源链接，例如：
     <a class="source-link" href="https://example.com" target="_blank" rel="noopener noreferrer">[来源]</a>
   - href 必须来自“可用来源链接”列表（或上下文中明确出现的 URL），不得编造 URL"""

        selling_points = [p.strip() for p in product_selling_points if p and p.strip()]
        prompt = f"""请为以下信息生成报告的「{section_name}」模块：

## 品类
{category_name}

## 商品卖点
{'、'.join(selling_points) if selling_points else '（未提供）'}

## 模块描述
{section_description}

## 模块标题约束
- section_name 必须为：{section_name}

## 重试原因（如有）
{retry_reason or '（无）'}

## 可用来源链接（仅用于外链引用；请勿编造 URL）
{json.dumps(source_links, ensure_ascii=False, indent=2)}

## 参考数据
{json.dumps(compact_context_data, ensure_ascii=False, indent=2)}

## 模板结构
{json.dumps(compact_template_structure, ensure_ascii=False, indent=2)}

请根据以上信息，生成符合模板结构的 HTML 内容。直接输出 HTML 代码，不需要 markdown 代码块包裹。"""

        return self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=8192,
            timeout_s=timeout_s,
            retry_attempts=retry_attempts,
        )

    def search_and_generate(
        self,
        query: str,
        brand: str,
        competitors: list[str]
    ) -> dict:
        """
        使用 Tavily 搜索获取实时数据，然后让 LLM 分析生成结构化结果
        
        流程：
        1. 调用 Tavily API 搜索品牌相关信息
        2. 将搜索结果作为上下文提供给 LLM
        3. LLM 基于实时数据生成结构化分析
        
        Args:
            query: 搜索查询
            brand: 目标品牌
            competitors: 竞品列表
            
        Returns:
            结构化的分析结果
        """
        start = time.perf_counter()
        
        # Step 1: 使用 Tavily 获取实时搜索数据
        tavily = self._get_tavily_client()
        search_context = ""
        search_meta: dict = {
            "ok": False,
            "used_tavily": False,
            "source_links": [],
            "search_degraded": False,
            "search_error_type": None,
            "search_error_message": None,
        }
        
        if not tavily:
            search_meta.update(
                {
                    "ok": False,
                    "used_tavily": False,
                    "search_degraded": True,
                    "search_error_type": "TavilyUnavailable",
                    "search_error_message": "Tavily client unavailable (missing key or init failure)",
                }
            )
        else:
            try:
                search_results = tavily.search_brand_info(
                    brand=brand,
                    competitors=competitors,
                    topics=["市场趋势", "消费者评价", "产品特点", "品牌新闻"]
                )
                search_context = tavily.get_formatted_context(search_results)
                # 汇总来源链接（去重）
                source_links: list[dict] = []
                seen: set[str] = set()
                for s in search_results.get("searches", []):
                    for r in (s.get("results") or [])[:10]:
                        url = (r.get("url") or "").strip()
                        title = (r.get("title") or "").strip()
                        if not url or url in seen:
                            continue
                        seen.add(url)
                        source_links.append({"title": title, "url": url})
                search_ok = bool(search_results.get("ok", False))
                budget_exhausted = bool(search_results.get("budget_exhausted", False))
                search_meta = {
                    "ok": search_ok,
                    "used_tavily": True,
                    "search_latency_ms": search_results.get("total_latency_ms", 0),
                    "topics_searched": len(search_results.get("searches", [])),
                    "source_links": source_links,
                    "search_degraded": (not search_ok) or budget_exhausted,
                    "search_error_type": None if search_ok else "TavilySearchError",
                    "search_error_message": None if search_ok else "Tavily search returned no usable result",
                    "budget_exhausted": budget_exhausted,
                }
            except Exception as e:
                degrade_on_error = bool(getattr(settings, "search_degrade_on_error", True))
                search_meta.update(
                    {
                        "ok": False,
                        "used_tavily": False,
                        "search_degraded": degrade_on_error,
                        "search_error_type": type(e).__name__,
                        "search_error_message": str(e),
                        "error": f"Tavily search failed: {str(e)}",
                    }
                )
        
        # Step 2: 让 LLM 基于搜索结果进行分析
        system_prompt = """你是一个专业的市场研究分析师。

你的任务是基于提供的【实时搜索数据】，分析品牌的市场信息，并生成结构化的 JSON 报告。

重要要求：
- 必须基于提供的搜索数据，不要编造信息
- 引用具体的来源和数据
- 分析要专业、客观
- 只返回纯 JSON，不要包含 markdown 代码块标记（不要用 ```json）
- 使用中文回答"""

        prompt = f"""请基于以下实时搜索数据，分析品牌的市场信息：

【分析任务】
{query}

【目标品牌】
{brand}

【竞品品牌】
{', '.join(competitors)}

【实时搜索数据】
{search_context if search_context else "未能获取搜索数据，请基于通用市场知识进行分析"}

【输出要求】
请基于上述搜索数据分析该品牌，返回以下 JSON 结构：

{{
    "brand_overview": "品牌概述（基于搜索结果的事实描述）",
    "market_trends": [
        "趋势1：具体描述，引用搜索结果中的数据",
        "趋势2：具体描述，引用搜索结果中的数据"
    ],
    "brand_positioning": "品牌的市场定位分析",
    "consumer_insights": [
        "洞察1：消费者行为/偏好分析",
        "洞察2：消费者行为/偏好分析"
    ],
    "competitive_analysis": "与竞品的对比分析",
    "key_metrics": {{
        "market_position": "市场地位描述",
        "brand_strength": "品牌优势",
        "growth_potential": "增长潜力"
    }},
    "recommendations": [
        "建议1",
        "建议2"
    ],
    "data_sources": [
        "引用的数据来源1",
        "引用的数据来源2"
    ]
}}

只返回 JSON，不要有任何其他文字。"""

        response = self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.5,
            max_tokens=2500,
            timeout_s=60.0,
            retry_attempts=2,
        )
        
        total_latency_ms = int((time.perf_counter() - start) * 1000)

        try:
            clean_response = response.strip()
            # 清理可能的 markdown 标记
            if clean_response.startswith("```"):
                first_newline = clean_response.find("\n")
                if first_newline > 0:
                    clean_response = clean_response[first_newline + 1:]
            if clean_response.endswith("```"):
                clean_response = clean_response[:-3].strip()

            data = json.loads(clean_response)
            data["_meta"] = {
                "ok": True,
                "used_web_search": bool(search_meta.get("used_tavily", False) and search_meta.get("ok", False)),
                "tool_type": "tavily" if search_meta.get("used_tavily") else "none",
                "latency_ms": total_latency_ms,
                "search_latency_ms": search_meta.get("search_latency_ms", 0),
                "source_links": search_meta.get("source_links", []),
                "error": search_meta.get("error"),
                "search_degraded": bool(search_meta.get("search_degraded", False)),
                "search_error_type": search_meta.get("search_error_type"),
                "search_error_message": search_meta.get("search_error_message"),
                "budget_exhausted": bool(search_meta.get("budget_exhausted", False)),
            }
            return data
        except json.JSONDecodeError as e:
            return {
                "_meta": {
                    "ok": False,
                    "used_web_search": False,
                    "tool_type": "tavily" if search_meta.get("used_tavily") else "none",
                    "latency_ms": total_latency_ms,
                    "source_links": search_meta.get("source_links", []),
                    "error": f"JSON 解析失败: {str(e)}",
                    "search_degraded": True,
                    "search_error_type": search_meta.get("search_error_type"),
                    "search_error_message": search_meta.get("search_error_message")
                    or f"Search analysis parse failed: {str(e)}",
                    "budget_exhausted": bool(search_meta.get("budget_exhausted", False)),
                },
                "raw_response": response,
                "parse_error": True,
            }


# 创建默认客户端实例
def get_llm_client() -> LLMClient:
    """获取 LLM 客户端实例"""
    return LLMClient()
