"""
报告生成器

整合模板解析、数据源和 LLM，生成完整的品牌洞察报告。
"""

import re
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable, Tuple
import time
from bs4 import BeautifulSoup, NavigableString

from ..config import settings
from ..llm.client import LLMClient, get_llm_client
from ..data_sources import XiaohongshuSource, DouyinSource
from ..utils.html_utils import clean_llm_html_response, sanitize_html
from .template_parser import TemplateParser, get_template_parser


class ReportGenerator:
    """报告生成器"""

    TEMPLATE_SIMILARITY_THRESHOLD = 0.65
    SECTION_STRUCTURE_COMPLETENESS_THRESHOLD = 0.90
    INLINE_SOURCE_MIN_COVERAGE = 0.90
    WASHCARE_CATEGORY_MARKERS = {
        "洗发", "去屑", "头皮", "护发", "洗护", "发膜", "发丝", "控油", "止痒", "蓬松"
    }
    WASHCARE_LEAK_MARKERS = {
        "清扬", "kono", "spes", "洗发", "去屑", "头皮", "控油", "止痒", "蓬松", "毛囊"
    }
    DARK_BG_MARKERS = {
        "bg-gray-900",
        "bg-gray-950",
        "bg-slate-900",
        "bg-slate-950",
        "bg-zinc-900",
        "bg-zinc-950",
        "bg-black",
    }

    def _coerce_inline_source_min_coverage(self, value: Optional[float], default: Optional[float] = None) -> float:
        base = self.INLINE_SOURCE_MIN_COVERAGE if default is None else default
        try:
            v = float(value if value is not None else base)
        except Exception:
            v = float(base)
        if v < 0:
            return 0.0
        if v > 1:
            return 1.0
        return v

    def _call_with_timeout(self, func: Callable[[], str], timeout_s: float) -> str:
        timeout = float(timeout_s or 0)
        if timeout <= 0:
            return func()
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(func)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError as exc:
            future.cancel()
            raise TimeoutError(f"section generation exceeded {timeout:.1f}s") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    
    def __init__(
        self,
        template_parser: Optional[TemplateParser] = None,
        llm_client: Optional[LLMClient] = None
    ):
        self.template_parser = template_parser or get_template_parser()
        self.llm_client = llm_client or get_llm_client()
        self.output_dir = settings.output_path
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化数据源
        self.data_sources = {
            "xiaohongshu": XiaohongshuSource(),
            "douyin": DouyinSource()
        }

    def _strip_text_content(self, html_content: str) -> str:
        """
        移除 HTML 文本，只保留结构和 class，供 LLM 参考骨架，避免照抄示例文案。
        """
        soup = BeautifulSoup(html_content, "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        for text_node in soup.find_all(string=True):
            try:
                if isinstance(text_node, str) and text_node.strip():
                    text_node.replace_with("")
            except Exception:
                continue
        self._sanitize_numeric_placeholders(soup)
        return str(soup)

    def _blank_text_nodes(self, root: Any, keep_section_title: bool = True) -> None:
        """清空节点内文本，保留结构标签。"""
        for tag in root.find_all(["script", "style"]):
            tag.decompose()

        for text_node in list(root.find_all(string=True)):
            if not isinstance(text_node, str):
                continue
            if not text_node.strip():
                continue
            parent = text_node.parent
            if (
                parent is not None
                and getattr(parent, "name", None) in {"h3", "h4", "h5", "h6"}
                and re.match(r"^\s*\d+(?:\.\d+)?\s*", text_node)
            ):
                # 保留编号型结构标题（如 4.1 / 1. / 2.），避免被清空导致模块骨架空白。
                continue
            if (
                keep_section_title
                and parent is not None
                and getattr(parent, "name", None) == "h2"
                and "section-title" in (parent.get("class") or [])
            ):
                continue
            text_node.replace_with("")

    def _sanitize_numeric_placeholders(self, root: Any) -> None:
        """
        清理模板中的数字占位符，避免 data-target 等属性在输出中“渗漏”为伪数据。

        目前主要针对海飞丝模板中的 `.count-up[data-target]` 结构：
        - 模板脚本会读取 data-target 并在页面滚动时写回数字；
        - 若不清理，LLM 未填充也会自动显示出模板数字（如 621/691）。
        """
        try:
            # 1) 移除 count-up 节点（脚本会根据 data-target 自动写入数字）
            for node in list(root.select(".count-up")):
                try:
                    node.decompose()
                except Exception:
                    try:
                        node.extract()
                    except Exception:
                        continue

            # 2) 兜底：移除遗留的 data-target 属性
            for node in root.find_all(attrs={"data-target": True}):
                try:
                    del node["data-target"]
                except Exception:
                    continue
        except Exception:
            return

    def _strip_numeric_placeholders_from_html(self, html_content: str) -> str:
        soup = BeautifulSoup(html_content or "", "lxml")
        self._sanitize_numeric_placeholders(soup)
        return str(soup)

    def _extract_section_shell(self, html_content: str, title_text: str) -> str:
        """
        提取模块骨架：保留标题与主要布局容器，去除示例文案，降低上下文体积。
        """
        wrapped = f'<section class="section relative">{html_content}</section>'
        soup = BeautifulSoup(wrapped, "lxml")
        root = soup.find("section")
        if root is None:
            return self._strip_text_content(html_content)

        title = root.find("h2", class_="section-title")
        if title is not None:
            for text_node in title.find_all(string=True):
                if isinstance(text_node, str):
                    text_node.replace_with("")
            title.append(NavigableString(title_text or ""))

        self._blank_text_nodes(root, keep_section_title=True)
        self._sanitize_numeric_placeholders(root)
        return str(root)

    def _build_template_structure(self, section: Any) -> Dict[str, Any]:
        """为 LLM 提供精简后的模板结构，避免携带示例文案。"""
        original_html = section.html_content
        structure_only = self._strip_text_content(original_html)
        section_shell = self._extract_section_shell(original_html, section.title)
        html_l = original_html.lower()
        if section.section_id == "hero":
            required_root_tag = "header" if "<header" in html_l else "div"
        else:
            required_root_tag = "section" if "<section" in html_l else "div"
        return {
            "section_id": section.section_id,
            "title": section.title,
            "required_title": section.title,
            "required_root_tag": required_root_tag,
            "css_classes": section.css_classes,
            "child_elements": section.child_elements,
            "structure_only_html": structure_only,
            "section_shell_html": section_shell,
            "output_requirements": (
                "仅输出该模块的 HTML 片段，保持现有 class/层级，但必须替换所有示例文本；"
                "不要输出完整 HTML 文档；不要包含 <script>；使用中文撰写；"
                "如无数据也需基于常识写出与品牌相关的要点，禁止保留模板示例或占位符。"
            ),
        }

    def _match_expected_title(self, expected_title: Optional[str], candidate_title: Optional[str]) -> bool:
        expected = re.sub(r"\s+", "", expected_title or "").strip().lower()
        candidate = re.sub(r"\s+", "", candidate_title or "").strip().lower()
        return bool(expected and candidate and expected == candidate)

    def _normalize_for_similarity(
        self,
        text: str,
        brand: str,
        competitors: List[str],
        category: Optional[str] = None,
    ) -> str:
        normalized = (text or "").lower()
        for token in [brand, category, "sony", "索尼", "海飞丝", "aos", "brandx", "brandy", "brandz"]:
            if token:
                normalized = normalized.replace(str(token).lower(), " ")
        for competitor in competitors:
            if competitor:
                normalized = normalized.replace(str(competitor).lower(), " ")
        normalized = re.sub(r"https?://\S+", " ", normalized)
        normalized = re.sub(r"\d+(?:\.\d+)?%?", " ", normalized)
        normalized = re.sub(r"[\W_]+", " ", normalized)
        return " ".join(normalized.split())

    def _compute_section_similarity(
        self,
        generated_html: str,
        template_section_html: str,
        brand: str,
        competitors: List[str],
        category: Optional[str] = None,
    ) -> float:
        generated_text = BeautifulSoup(generated_html, "lxml").get_text(" ", strip=True)
        template_text = BeautifulSoup(template_section_html, "lxml").get_text(" ", strip=True)
        norm_generated = self._normalize_for_similarity(generated_text, brand, competitors, category)
        norm_template = self._normalize_for_similarity(template_text, brand, competitors, category)
        if not norm_generated or not norm_template:
            return 0.0
        # 防止长文本触发 SequenceMatcher 极慢路径，造成服务线程阻塞。
        max_len = 6000
        if len(norm_generated) > max_len:
            norm_generated = norm_generated[:max_len]
        if len(norm_template) > max_len:
            norm_template = norm_template[:max_len]
        return SequenceMatcher(None, norm_generated, norm_template).ratio()

    def _extract_section_structure_counts(self, html_fragment: str) -> Dict[str, int]:
        fragment_soup = BeautifulSoup(html_fragment or "", "lxml")
        root = fragment_soup.body or fragment_soup
        glass_card = 0
        grid = 0
        table = 0
        list_count = 0
        nodes = root.find_all(True, limit=3000)
        for node in nodes:
            name = getattr(node, "name", None)
            if name in {"ul", "ol"}:
                list_count += 1
            elif name == "table":
                table += 1
            elif name == "div":
                classes = node.get("class") or []
                if not classes:
                    continue
                class_str = " ".join([c for c in classes if isinstance(c, str)])
                if "glass-card" in class_str:
                    glass_card += 1
                if "grid" in class_str:
                    grid += 1

        return {
            "glass_card": glass_card,
            "grid": grid,
            "table": table,
            "list": list_count,
            "dom_nodes": len(nodes),
        }

    def _compute_structure_completeness(
        self,
        generated_html: str,
        template_section_html: str,
    ) -> Tuple[float, Dict[str, Any]]:
        generated_counts = self._extract_section_structure_counts(generated_html)
        template_counts = self._extract_section_structure_counts(template_section_html)

        ratios: List[float] = []
        metrics: Dict[str, Any] = {}
        for key in ["glass_card", "grid", "table", "list", "dom_nodes"]:
            generated_value = int(generated_counts.get(key, 0))
            template_value = int(template_counts.get(key, 0))
            metrics[f"{key}_generated"] = generated_value
            metrics[f"{key}_template"] = template_value

            if template_value <= 0:
                continue
            ratios.append(min(generated_value / template_value, 1.0))

        completeness = (sum(ratios) / len(ratios)) if ratios else 1.0
        metrics["structure_completeness"] = round(completeness, 4)
        metrics["structure_retention_ratio"] = round(completeness, 4)
        return completeness, metrics

    def _compute_content_fill_metrics(self, html_fragment: str) -> Dict[str, Any]:
        soup = BeautifulSoup(html_fragment or "", "lxml")
        root = soup.body or soup

        cards = root.find_all(
            lambda node: getattr(node, "name", None) == "div"
            and any(token in {"glass-card", "card"} for token in (node.get("class") or []))
        )
        blocks = cards if cards else [root]

        filled_count = 0
        empty_count = 0
        for block in blocks:
            text = block.get_text(" ", strip=True)
            if len(text) >= 24:
                filled_count += 1
            else:
                empty_count += 1

        return {
            "filled_block_count": filled_count,
            "empty_block_count": empty_count,
            "total_block_count": len(blocks),
        }

    def _looks_like_claim_sentence(self, text: str) -> bool:
        content = (text or "").strip()
        if len(content) < 16:
            return False
        if re.search(r"\d", content):
            return True
        claim_markers = ["显示", "增长", "下降", "占比", "同比", "环比", "趋势", "市场", "份额", "数据"]
        return any(marker in content for marker in claim_markers)

    def _collect_allowed_source_urls(self, source_links: List[Dict[str, str]]) -> List[str]:
        urls: List[str] = []
        seen: set[str] = set()
        for item in source_links or []:
            if not isinstance(item, dict):
                continue
            url = (item.get("url") or "").strip()
            if not url or url in seen:
                continue
            if not (url.startswith("http://") or url.startswith("https://")):
                continue
            seen.add(url)
            urls.append(url)
        return urls

    def _inject_inline_source_links(self, html_content: str, source_links: List[Dict[str, str]]) -> str:
        allowed_urls = self._collect_allowed_source_urls(source_links)
        if not allowed_urls:
            return html_content

        soup = BeautifulSoup(html_content or "", "lxml")
        claim_nodes = []
        for node in soup.find_all(["p", "li"]):
            text = node.get_text(" ", strip=True)
            if not self._looks_like_claim_sentence(text):
                continue
            claim_nodes.append(node)

        url_cursor = 0
        for node in claim_nodes:
            has_inline_link = any(
                "source-link" in (a.get("class") or [])
                and (a.get("href") or "").strip() in allowed_urls
                for a in node.find_all("a", href=True)
            )
            if has_inline_link:
                continue

            source_url = allowed_urls[url_cursor % len(allowed_urls)]
            url_cursor += 1
            node.append(NavigableString(" "))
            link = soup.new_tag("a", href=source_url)
            link["class"] = ["source-link"]
            link["target"] = "_blank"
            link["rel"] = "noopener noreferrer"
            link.string = "[来源]"
            node.append(link)

        return str(soup)

    def _validate_inline_source_links(
        self,
        html_content: str,
        source_links: List[Dict[str, str]],
        min_coverage: Optional[float] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        target_min_coverage = self._coerce_inline_source_min_coverage(min_coverage)
        metrics: Dict[str, Any] = {
            "inline_source_ok": True,
            "inline_source_coverage": 1.0,
            "inline_source_claim_count": 0,
            "inline_source_linked_count": 0,
            "inline_source_min_coverage": round(target_min_coverage, 4),
        }
        if not source_links:
            return True, metrics

        allowed_urls = self._collect_allowed_source_urls(source_links)
        if not allowed_urls:
            return True, metrics

        soup = BeautifulSoup(html_content or "", "lxml")
        claim_nodes = []
        linked_count = 0
        for node in soup.find_all(["p", "li"]):
            text = node.get_text(" ", strip=True)
            if not self._looks_like_claim_sentence(text):
                continue
            claim_nodes.append(node)
            has_link = any(
                "source-link" in (a.get("class") or [])
                and (a.get("href") or "").strip() in allowed_urls
                for a in node.find_all("a", href=True)
            )
            if has_link:
                linked_count += 1

        if not claim_nodes:
            return True, metrics

        coverage = linked_count / max(len(claim_nodes), 1)
        metrics["inline_source_claim_count"] = len(claim_nodes)
        metrics["inline_source_linked_count"] = linked_count
        metrics["inline_source_coverage"] = round(coverage, 4)
        ok = coverage >= target_min_coverage
        metrics["inline_source_ok"] = ok
        return ok, metrics

    def _is_category_mismatch_leak(self, text: str, category: Optional[str]) -> bool:
        if not category:
            return False
        category_l = str(category).lower()
        if any(marker in category_l for marker in self.WASHCARE_CATEGORY_MARKERS):
            return False
        text_l = (text or "").lower()
        return any(marker.lower() in text_l for marker in self.WASHCARE_LEAK_MARKERS)

    def _validate_generated_section(
        self,
        generated_html: str,
        section: Any,
        expected_title: str,
        brand: str,
        competitors: List[str],
        category: Optional[str],
        source_links: Optional[List[Dict[str, str]]] = None,
        inline_source_min_coverage: Optional[float] = None,
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        metrics: Dict[str, Any] = {}
        fragment_soup = BeautifulSoup(generated_html, "lxml")

        if section.section_id == "hero":
            has_hero = fragment_soup.find("div", class_="hero") is not None
            has_header = fragment_soup.find("header", class_="header") is not None
            if not (has_hero or has_header):
                return False, "inject_failed", metrics
            if fragment_soup.find_all("h2", class_="section-title"):
                return False, "multi_section_output", metrics
        else:
            titles = fragment_soup.find_all("h2", class_="section-title")
            if len(titles) != 1:
                return False, "multi_section_output", metrics
            title_text = titles[0].get_text(strip=True)
            if not self._match_expected_title(expected_title, title_text):
                return False, "title_mismatch", metrics

        text = fragment_soup.get_text(" ", strip=True)
        if self._has_template_leak(generated_html, brand, competitors):
            return False, "template_leak", metrics
        if self._is_category_mismatch_leak(text, category):
            return False, "category_mismatch", metrics
        if self._is_template_numeric_leak(generated_html, category):
            metrics["template_numeric_leak"] = True
            return False, "template_numeric_leak", metrics
        metrics["template_numeric_leak"] = False

        similarity = self._compute_section_similarity(
            generated_html=generated_html,
            template_section_html=section.html_content,
            brand=brand,
            competitors=competitors,
            category=category,
        )
        metrics["similarity_ratio"] = round(similarity, 4)
        if similarity >= self.TEMPLATE_SIMILARITY_THRESHOLD:
            return False, "template_similarity_high", metrics

        if section.section_id != "hero":
            structure_completeness, structure_metrics = self._compute_structure_completeness(
                generated_html=generated_html,
                template_section_html=section.html_content,
            )
            metrics.update(structure_metrics)
            structure_threshold = self.SECTION_STRUCTURE_COMPLETENESS_THRESHOLD
            expected_plain = re.sub(r"\s+", "", expected_title or "").strip()
            if getattr(section, "section_id", None) == "section-4" and expected_plain == "竞品深度攻防":
                structure_threshold = 0.70
            metrics["structure_threshold"] = round(float(structure_threshold), 4)
            if structure_completeness < structure_threshold:
                return False, "structure_degraded", metrics

        fill_metrics = self._compute_content_fill_metrics(generated_html)
        metrics.update(fill_metrics)

        inline_ok, inline_metrics = self._validate_inline_source_links(
            html_content=generated_html,
            source_links=source_links or [],
            min_coverage=inline_source_min_coverage,
        )
        metrics.update(inline_metrics)
        if bool(getattr(settings, "inline_source_link_strict", True)) and (source_links or []) and not inline_ok:
            return False, "missing_inline_sources", metrics

        return True, None, metrics

    def _get_section_index(self, section_id: str) -> int:
        if isinstance(section_id, str) and section_id.startswith("section-"):
            try:
                return int(section_id.split("-", 1)[1]) - 1
            except Exception:
                return -1
        return -1

    def _has_template_leak(self, html_content: str, brand: str, competitors: list[str]) -> bool:
        """
        判断生成结果是否仍包含模板示例品牌/占位符，避免混入无关内容。
        """
        text = BeautifulSoup(html_content, "lxml").get_text(" ").lower()
        ignore = {brand.lower()}
        ignore.update(c.lower() for c in competitors if isinstance(c, str))
        markers = {
            "aos",
            "海飞丝",
            "brandx",
            "brandy",
            "brandz",
            "kono",
            "spes",
            "示例",
            "fake data",
            "占位",
            "{{category_name}}",
        }
        return any(m in text and m not in ignore for m in markers)

    def _is_template_numeric_leak(self, html_content: str, category: Optional[str]) -> bool:
        """
        检查模板数字占位符是否渗漏到输出。

        非洗护品类若出现 `.count-up[data-target]` 或 `data-target` 属性，通常意味着模板占位数字未被清理，
        会导致页面脚本自动写入“假数字”（如 621/691）。
        """
        category_l = str(category or "").lower()
        if any(marker in category_l for marker in self.WASHCARE_CATEGORY_MARKERS):
            return False

        fragment = BeautifulSoup(html_content or "", "lxml")
        if fragment.select(".count-up"):
            return True
        if fragment.find(attrs={"data-target": True}) is not None:
            return True
        return False

    def _finalize_sections_after_llm(
        self,
        soup: BeautifulSoup,
        sections: List[Any],
        llm_sections: List[Dict[str, Any]],
        brand: str,
        category: Optional[str] = None,
        competitors: Optional[List[str]] = None,
        context_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        确保所有 section 最终都有可读内容。
        优先注入规则化兜底模块，最后才做清空占位。
        """
        competitors = competitors or []
        status_map = {s.get("section_id"): s for s in llm_sections if isinstance(s, dict)}
        search_degraded = bool(
            (((context_data or {}).get("llm_search") or {}).get("_meta") or {}).get("search_degraded", False)
            if isinstance(context_data, dict) or context_data is None
            else False
        )
        for section in sections:
            sec_index = self._get_section_index(section.section_id)
            status = status_map.get(section.section_id)
            if not status or not status.get("ok"):
                fallback_html = self._render_rule_based_fallback_section(
                    section=section,
                    brand=brand,
                    category=category,
                    competitors=competitors,
                    error_code=(status or {}).get("error") if isinstance(status, dict) else "finalize_missing",
                    context_data=context_data,
                )
                injected, _, _ = self._inject_generated_section(
                    soup=soup,
                    section_id=section.section_id,
                    section_index=sec_index,
                    generated_html=fallback_html,
                    expected_title=getattr(section, "title", None),
                    preserve_structure=False,
                )
                if injected and sec_index >= 0:
                    section_root = self._find_section_root_by_index(soup, sec_index)
                    if section_root is not None:
                        self._fill_key_micro_blanks_in_section(
                            soup=soup,
                            section_root=section_root,
                            section_id=section.section_id,
                            brand=brand,
                            category=category,
                            competitors=competitors,
                            search_degraded=search_degraded,
                        )
                if injected:
                    continue

                self._clear_section_content(
                    soup=soup,
                    section_id=section.section_id,
                    section_index=sec_index,
                    brand=brand,
                    error_msg="内容未生成，已清空模板示例",
                )

    def _inject_generated_section(
        self,
        soup: BeautifulSoup,
        section_id: str,
        section_index: int,
        generated_html: str,
        expected_title: Optional[str] = None,
        preserve_structure: bool = True,
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        将 LLM 生成的模块 HTML 注入到完整页面中。

        注：采用尽量保守的替换策略，仅替换对应模块的根节点，避免破坏模板整体结构。

        Args:
            soup: 完整页面的 BeautifulSoup
            section_id: 模块 ID（hero/section-1...）
            section_index: content-section 的顺序索引（section-1 => 0）
            generated_html: LLM 返回的 HTML 片段（可能包含多余包裹）

        Returns:
            bool: 是否成功注入
        """
        fragment_soup = BeautifulSoup(generated_html, "lxml")

        if section_id == "hero":
            new_hero = fragment_soup.find("div", class_="hero")
            old_hero = soup.find("div", class_="hero")
            if new_hero and old_hero:
                old_hero.replace_with(new_hero)
                return True, None, {}

            # 兼容 TikTok 牙膏报告模板：<header class="header">
            new_header = fragment_soup.find("header", class_="header")
            old_header = soup.find("header", class_="header")
            if new_header and old_header:
                old_header.replace_with(new_header)
                return True, None, {}

            return False, "inject_failed", {}

        # content section: 优先做结构保真合并，保留模板原有视觉基建（id、背景层、辅助装饰等）。
        title_elems = soup.find_all("h2", class_="section-title")
        if section_index < 0 or section_index >= len(title_elems):
            return False, "inject_failed", {}
        old_title = title_elems[section_index]

        old_root_section = old_title.find_parent("section")

        candidate_titles = fragment_soup.find_all("h2", class_="section-title")
        selected_title: Optional[Any] = None
        if expected_title:
            for candidate in candidate_titles:
                candidate_text = candidate.get_text(strip=True)
                if self._match_expected_title(expected_title, candidate_text):
                    selected_title = candidate
                    break
            if selected_title is None:
                return False, "title_mismatch", {}

        if selected_title is None:
            if len(candidate_titles) == 1:
                selected_title = candidate_titles[0]
            elif len(candidate_titles) > 1:
                # LLM 可能误返回整页 HTML。多模块且无法匹配目标标题时，拒绝注入，走失败兜底。
                return False, "inject_failed", {}

        new_root_section: Optional[Any] = None
        if selected_title is not None:
            new_root_section = selected_title.find_parent("section")
        if new_root_section is None:
            new_root_section = fragment_soup.find("section")
        if new_root_section is None:
            fragment_body = fragment_soup.body or fragment_soup
            fragment_children = [
                node for node in list(fragment_body.contents)
                if getattr(node, "name", None) is not None
            ]
            if fragment_children:
                new_root_section = soup.new_tag("section")
                for child in fragment_children:
                    new_root_section.append(child)

        if old_root_section is not None and new_root_section is not None and preserve_structure:
            merged, merge_metrics = self._merge_generated_into_template_section(
                target_section=old_root_section,
                generated_section=new_root_section,
                expected_title=expected_title,
            )
            if merged:
                return True, None, merge_metrics

        # 回退：替换整节
        if old_root_section is not None and new_root_section is not None:
            for key, value in (old_root_section.attrs or {}).items():
                if key in {"id", "class"}:
                    continue
                if key not in new_root_section.attrs:
                    new_root_section.attrs[key] = value
            if old_root_section.get("class"):
                new_root_section["class"] = old_root_section.get("class")
            if old_root_section.get("id"):
                new_root_section["id"] = old_root_section.get("id")
            old_root_section.replace_with(new_root_section)
            return True, None, {}

        # 2) 回退：仅替换标题与第一层 grid
        old_grid = old_title.find_next_sibling("div", class_="grid")
        if old_grid is None:
            return False, "inject_failed", {}

        new_title = selected_title or fragment_soup.find("h2", class_="section-title")
        new_grid: Optional[Any] = None
        if new_title is not None:
            new_grid = new_title.find_next_sibling("div", class_="grid")
        if new_grid is None:
            # 尝试兜底：直接找第一个 grid
            new_grid = fragment_soup.find("div", class_="grid")
        if not (new_title and new_grid):
            return False, "inject_failed", {}

        old_title.replace_with(new_title)
        old_grid.replace_with(new_grid)
        return True, None, {}

    def _clone_tag_contents_to(self, target_tag: Any, source_tag: Any) -> None:
        cloned = BeautifulSoup(str(source_tag), "lxml").find(source_tag.name)
        if cloned is None:
            return
        target_tag.clear()
        for child in list(cloned.contents):
            target_tag.append(child)

    def _is_fillable_text_node(self, node: Any) -> bool:
        name = getattr(node, "name", None)
        if not name:
            return False

        direct_text = node.get_text(" ", strip=True)
        if name in {"h2"} and "section-title" in (node.get("class") or []):
            return False
        if name in {"p", "li", "h3", "h4", "h5", "h6", "td", "th"}:
            return True

        # 关键修复：避免把长文本塞进模板里用于标记/徽标的小 span，导致重叠错位。
        if name == "span":
            return False

        if name != "div":
            return False

        classes = [c for c in (node.get("class") or []) if isinstance(c, str)]
        if not classes:
            return False

        # 仅允许承载排版文本的 div（text/font），排除布局/装饰容器。
        has_typography_hint = any(c.startswith("text-") or c.startswith("font-") for c in classes)
        if not has_typography_hint:
            return False

        layout_tokens = (
            "grid",
            "flex",
            "absolute",
            "relative",
            "inset",
            "w-",
            "h-",
            "bg-",
            "border",
            "rounded",
            "group",
            "col-span",
            "row-span",
            "overflow",
        )
        if any(any(token in c for token in layout_tokens) for c in classes):
            return False

        # 避免把复杂容器当作文本节点填充。
        if node.find(["div", "section", "ul", "ol", "table"]):
            return False

        return bool(direct_text) or len(classes) > 0

    def _truncate_micro_text(self, text: str, max_chars: int) -> str:
        cleaned = re.sub(r"\s+", " ", (text or "").strip())
        if max_chars <= 0:
            return cleaned
        if len(cleaned) <= max_chars:
            return cleaned
        return cleaned[:max_chars]

    def _is_fillable_micro_node(self, node: Any) -> bool:
        """
        可填充“微位点”节点：
        - tag-pill（内容标签）
        - 搜索词/小徽标等 span
        - 条形图文字容器（chart-bar-fill）

        该层不替代正文合并，仅用于补齐模板中易出现空白的细粒度节点。
        """
        name = getattr(node, "name", None)
        if not name:
            return False

        if name == "span":
            if node.find(True):
                return False
            classes = [c for c in (node.get("class") or []) if isinstance(c, str)]
            if any(c.startswith("tag-pill") or c == "tag-pill" for c in classes):
                return True

            forbidden_tokens = ("w-", "h-", "rounded", "animate", "shrink-0", "inline-flex")
            if any(any(token in c for token in forbidden_tokens) for c in classes):
                return False

            parent = getattr(node, "parent", None)
            parent_classes = (
                [c for c in (parent.get("class") or []) if isinstance(c, str)] if parent is not None else []
            )
            has_typo = any(c.startswith("text-") or c.startswith("font-") for c in classes)
            parent_typo = any(c.startswith("text-") or c.startswith("font-") for c in parent_classes)
            if "justify-between" in parent_classes and (has_typo or parent_typo):
                return True
            if has_typo:
                return True
            return False

        if name == "div":
            classes = [c for c in (node.get("class") or []) if isinstance(c, str)]
            if "chart-bar-fill" in classes:
                return True

            # 比例条/条形块：允许承载短文本
            if any(c.startswith("bg-pink-") or c.startswith("bg-blue-") for c in classes) and any(
                c.startswith("text-") for c in classes
            ):
                if node.find(["div", "section", "ul", "ol", "table"]):
                    return False
                return True

            if any(c.startswith("bg-orange-") for c in classes) and any(c.startswith("text-") for c in classes):
                if node.find(["div", "section", "ul", "ol", "table"]):
                    return False
                return True

        return False

    def _micro_slot_type(self, node: Any) -> str:
        name = getattr(node, "name", None)
        classes = [c for c in (node.get("class") or []) if isinstance(c, str)]
        if name == "span" and any(c.startswith("tag-pill") or c == "tag-pill" for c in classes):
            return "tag_pill"
        if name == "div" and "chart-bar-fill" in classes:
            return "chart_bar"
        if name == "div" and any(c.startswith("bg-orange-") for c in classes):
            return "orange_bar"
        if name == "div" and any(c.startswith("bg-pink-") or c.startswith("bg-blue-") for c in classes):
            return "ratio_segment"
        if name == "span":
            return "span"
        return "other"

    def _micro_text_limit(self, node: Any) -> int:
        classes = [c for c in (node.get("class") or []) if isinstance(c, str)]
        if getattr(node, "name", None) == "span" and any(c.startswith("tag-pill") or c == "tag-pill" for c in classes):
            return 14
        if getattr(node, "name", None) == "div" and (
            "chart-bar-fill" in classes or any(c.startswith("bg-orange-") for c in classes)
        ):
            return 22
        return 18

    def _set_micro_text(self, target_node: Any, text: str) -> bool:
        limit = self._micro_text_limit(target_node)
        trimmed = self._truncate_micro_text(text, limit)
        if not trimmed:
            return False

        if getattr(target_node, "name", None) == "div" and "chart-bar-fill" in (target_node.get("class") or []):
            child_span = target_node.find("span")
            if child_span is not None and not child_span.get_text(" ", strip=True):
                child_span.clear()
                child_span.append(NavigableString(trimmed))
                return True

        target_node.clear()
        target_node.append(NavigableString(trimmed))
        return True

    def _merge_micro_nodes(self, target_section: Any, generated_section: Any) -> Dict[str, Any]:
        target_nodes = [
            node for node in target_section.find_all(True) if self._is_fillable_micro_node(node)
        ]
        generated_nodes = [
            node
            for node in generated_section.find_all(True)
            if self._is_fillable_micro_node(node) and node.get_text(" ", strip=True)
        ]

        generated_by_type: Dict[str, List[Any]] = {}
        for node in generated_nodes:
            generated_by_type.setdefault(self._micro_slot_type(node), []).append(node)

        fallback_pool = list(generated_nodes)
        for target_node in target_nodes:
            if target_node.get_text(" ", strip=True):
                continue
            slot_type = self._micro_slot_type(target_node)
            candidate = None

            pool = generated_by_type.get(slot_type) or []
            if pool:
                candidate = pool.pop(0)
            elif fallback_pool:
                # 兜底：同标签优先
                for idx, item in enumerate(list(fallback_pool)):
                    if getattr(item, "name", None) == getattr(target_node, "name", None):
                        candidate = item
                        fallback_pool.pop(idx)
                        break
                if candidate is None:
                    candidate = fallback_pool.pop(0)

            if candidate is None:
                continue
            self._set_micro_text(target_node, candidate.get_text(" ", strip=True))

        total = len(target_nodes)
        filled = sum(1 for node in target_nodes if node.get_text(" ", strip=True))
        empty = total - filled
        return {
            "micro_slots_total": total,
            "micro_slots_filled": filled,
            "micro_slots_empty": empty,
        }

    def _merge_generated_into_template_section(
        self,
        target_section: Any,
        generated_section: Any,
        expected_title: Optional[str],
    ) -> Tuple[bool, Dict[str, Any]]:
        target_title = target_section.find("h2", class_="section-title")
        generated_title = generated_section.find("h2", class_="section-title")
        if expected_title and generated_title is not None:
            candidate = generated_title.get_text(strip=True)
            if not self._match_expected_title(expected_title, candidate):
                return False, {}

        if target_title is not None and generated_title is not None:
            target_title.clear()
            target_title.append(NavigableString(generated_title.get_text(strip=True)))

        target_nodes = [node for node in target_section.find_all(True) if self._is_fillable_text_node(node)]
        target_micro_nodes = [
            node for node in target_section.find_all(True) if self._is_fillable_micro_node(node)
        ]
        generated_nodes = [
            node for node in generated_section.find_all(True)
            if self._is_fillable_text_node(node) and node.get_text(" ", strip=True)
        ]

        if not target_nodes and not target_micro_nodes:
            return False, {}

        generated_by_tag: Dict[str, List[Any]] = {}
        for node in generated_nodes:
            generated_by_tag.setdefault(node.name, []).append(node)

        fallback_pool = list(generated_nodes)
        fallback_index = 0

        for target_node in target_nodes:
            candidate = None
            same_type = generated_by_tag.get(target_node.name) or []
            if same_type:
                candidate = same_type.pop(0)
            elif fallback_pool and target_node.name not in {"h3", "h4", "h5", "h6"}:
                candidate = fallback_pool[fallback_index % len(fallback_pool)]
                fallback_index += 1

            if candidate is not None:
                self._clone_tag_contents_to(target_node, candidate)

        micro_metrics = self._merge_micro_nodes(target_section=target_section, generated_section=generated_section)
        return True, micro_metrics

    def _compute_micro_slot_metrics(self, section_root: Any) -> Dict[str, Any]:
        nodes = [node for node in section_root.find_all(True) if self._is_fillable_micro_node(node)]
        total = len(nodes)
        filled = sum(1 for node in nodes if node.get_text(" ", strip=True))
        empty = total - filled
        return {
            "micro_slots_total": total,
            "micro_slots_filled": filled,
            "micro_slots_empty": empty,
        }

    def _find_section_root_by_index(self, soup: BeautifulSoup, section_index: int) -> Optional[Any]:
        titles = soup.find_all("h2", class_="section-title")
        if section_index < 0 or section_index >= len(titles):
            return None
        return titles[section_index].find_parent("section")

    def _ensure_qualitative_note(
        self,
        soup: BeautifulSoup,
        container: Any,
        reason: str = "AI 推断/公开量化数据不足",
    ) -> bool:
        if container is None:
            return False
        if container.find("p", class_=lambda x: isinstance(x, str) and "qualitative-note" in x):
            return False
        note = soup.new_tag("p")
        note["class"] = ["text-xs", "text-gray-400", "mt-2", "qualitative-note"]
        note.string = f"注：此处为定性示意（{reason}）。"
        container.append(note)
        return True

    def _fill_key_micro_blanks_in_section(
        self,
        soup: BeautifulSoup,
        section_root: Any,
        section_id: str,
        brand: str,
        category: Optional[str],
        competitors: List[str],
        search_degraded: bool,
    ) -> Dict[str, Any]:
        """
        关键微模块兜底：即使 LLM 未填充，也避免出现“只有图形没有名词”的空白。

        仅填充短名词/短语，不输出百分比/规模数字。
        """
        filled = 0
        note_added = False

        def _set_if_empty(node: Any, value: str, max_chars: int = 18) -> bool:
            nonlocal filled
            if node is None:
                return False
            if node.get_text(" ", strip=True):
                return False
            node.clear()
            node.append(NavigableString(self._truncate_micro_text(value, max_chars)))
            filled += 1
            return True

        def _set_div_or_child_span(div: Any, value: str, max_chars: int = 22) -> bool:
            if div is None:
                return False
            child_span = div.find("span")
            if child_span is not None and not child_span.get_text(" ", strip=True):
                return _set_if_empty(child_span, value, max_chars=max_chars)
            return _set_if_empty(div, value, max_chars=max_chars)

        # section-1: 清理 count-up 后的宏观条形卡片
        if section_id == "section-1":
            cards = section_root.find_all(
                lambda node: getattr(node, "name", None) == "div"
                and any(token in {"glass-card", "card"} for token in (node.get("class") or []))
            )
            card = cards[0] if cards else None
            if card is not None:
                pairs = [
                    ("内容与服务收入", "趋势：提升"),
                    ("数字内容活跃度", "趋势：增强"),
                ]
                rows = []
                for row in card.find_all("div"):
                    classes = [c for c in (row.get("class") or []) if isinstance(c, str)]
                    if "justify-between" not in classes:
                        continue
                    spans = row.find_all("span", recursive=False)
                    if len(spans) != 2:
                        continue
                    if spans[0].get_text(" ", strip=True) or spans[1].get_text(" ", strip=True):
                        continue
                    rows.append((spans[0], spans[1]))
                for idx, (left, right) in enumerate(rows[:2]):
                    label, value = pairs[idx] if idx < len(pairs) else ("指标", "趋势")
                    _set_if_empty(left, label, max_chars=18)
                    _set_if_empty(right, value, max_chars=18)

                bars = [
                    div
                    for div in card.find_all("div")
                    if "chart-bar-fill" in (div.get("class") or [])
                ]
                bar_texts = ["提升", "增强"]
                for idx, bar in enumerate(bars[:2]):
                    _set_div_or_child_span(bar, bar_texts[idx] if idx < len(bar_texts) else "趋势", max_chars=12)

                badge = card.find(
                    lambda node: getattr(node, "name", None) == "div"
                    and "bg-green-50" in (node.get("class") or [])
                    and "text-green-700" in (node.get("class") or [])
                )
                _set_if_empty(badge, "定性：正向支撑", max_chars=18)
                note_added = self._ensure_qualitative_note(soup, card) or note_added

        # section-3: 人群洞察图表（核心客群结构/决策因子）
        if section_id == "section-3":
            cards = section_root.find_all(
                lambda node: getattr(node, "name", None) == "div"
                and any(token in {"glass-card", "card"} for token in (node.get("class") or []))
            )
            card = cards[0] if cards else None
            if card is not None:
                group_a = "通勤降噪党"
                group_b = "影音内容党"

                label_row = None
                for row in card.find_all("div"):
                    classes = [c for c in (row.get("class") or []) if isinstance(c, str)]
                    if "justify-between" not in classes:
                        continue
                    spans = row.find_all("span", recursive=False)
                    if len(spans) == 2:
                        label_row = spans
                        break
                if label_row:
                    _set_if_empty(label_row[0], group_a, max_chars=10)
                    _set_if_empty(label_row[1], group_b, max_chars=10)

                pink = card.find(lambda node: getattr(node, "name", None) == "div" and "bg-pink-400" in (node.get("class") or []))
                blue = card.find(lambda node: getattr(node, "name", None) == "div" and "bg-blue-400" in (node.get("class") or []))
                _set_if_empty(pink, group_a, max_chars=10)
                _set_if_empty(blue, group_b, max_chars=10)

                price_pink = card.find(lambda node: getattr(node, "name", None) == "span" and "bg-pink-50" in (node.get("class") or []))
                price_blue = card.find(lambda node: getattr(node, "name", None) == "span" and "bg-blue-50" in (node.get("class") or []))
                _set_if_empty(price_pink, "重体验/不强比价", max_chars=14)
                _set_if_empty(price_blue, "促销敏感/比价", max_chars=14)

                factor_names = ["降噪效果", "佩戴舒适", "音质表现", "续航/快充"]
                bars: List[Any] = []
                for div in card.find_all("div"):
                    classes = [c for c in (div.get("class") or []) if isinstance(c, str)]
                    if any(c.startswith("bg-orange-") for c in classes) and any(
                        c.startswith("text-") for c in classes
                    ):
                        bars.append(div)
                for idx, bar in enumerate(bars[:4]):
                    _set_div_or_child_span(bar, factor_names[idx] if idx < len(factor_names) else "因素", max_chars=14)

                note_added = self._ensure_qualitative_note(soup, card) or note_added

        # section-4: 社媒检索词与内容标签建议
        if section_id == "section-4":
            competitor_hint = competitors[0] if competitors else "竞品"
            filled_search_tag = 0
            filled_stepper = 0
            queries = [
                (f"{brand} {category or ''} 对比 {competitor_hint} 降噪", "对比测评"),
                (f"{brand} 耳机 佩戴 舒适 体验", "用户口碑"),
            ]
            search_rows: List[Any] = []
            for row in section_root.find_all("div"):
                classes = [c for c in (row.get("class") or []) if isinstance(c, str)]
                if "justify-between" not in classes:
                    continue
                spans = row.find_all("span", recursive=False)
                if len(spans) != 2:
                    continue
                if spans[0].get_text(" ", strip=True) or spans[1].get_text(" ", strip=True):
                    continue
                # 仅填充“检索词/标签”类行，避免误伤步骤条等结构
                span0_classes = [c for c in (spans[0].get("class") or []) if isinstance(c, str)]
                span1_classes = [c for c in (spans[1].get("class") or []) if isinstance(c, str)]
                if not (any(c.startswith("text-") for c in span0_classes) and ("font-bold" in span1_classes)):
                    continue
                search_rows.append(spans)

            for idx, spans in enumerate(search_rows[:2]):
                q, hint = queries[idx] if idx < len(queries) else (f"{brand} 耳机 评测", "测评")
                if _set_if_empty(spans[0], q, max_chars=18):
                    filled_search_tag += 1
                if _set_if_empty(spans[1], hint, max_chars=10):
                    filled_search_tag += 1

            tag_defaults = {
                "tag-pill-gray": f"品牌：{brand}",
                "red": f"对比：{brand} vs {competitor_hint}",
                "orange": "场景：通勤降噪",
                "blue": "痛点：舒适/通透",
                "green": "卖点：音质/多点",
            }
            tag_pills = [
                span
                for span in section_root.find_all("span")
                if any(c.startswith("tag-pill") or c == "tag-pill" for c in (span.get("class") or []))
            ]
            for pill in tag_pills:
                if pill.get_text(" ", strip=True):
                    continue
                classes = [c for c in (pill.get("class") or []) if isinstance(c, str)]
                key = next((c for c in classes if c in tag_defaults), None)
                if key is None:
                    continue
                if _set_if_empty(pill, tag_defaults[key], max_chars=14):
                    filled_search_tag += 1

            # 决策路径演化（stepper）兜底：填满 3 个节点（编号 + 文案），避免空白。
            def _extract_competitor_short(card_title: str) -> str:
                title = re.sub(r"\s+", "", (card_title or "")).strip()
                m = re.search(r"对(.+?)攻防", title)
                if m:
                    return m.group(1)
                if competitors:
                    return str(competitors[-1])
                return "竞品"

            def _classes(node: Any) -> List[str]:
                return [c for c in (node.get("class") or []) if isinstance(c, str)]

            def _is_step_row(node: Any) -> bool:
                cls = _classes(node)
                return "flex" in cls and "items-center" in cls and "gap-3" in cls

            def _is_dashed_connector(node: Any) -> bool:
                cls = _classes(node)
                return "border-l-2" in cls and "border-dashed" in cls

            def _resolve_competitor_short(card: Any) -> str:
                card_text = card.get_text(" ", strip=True)
                for candidate in competitors:
                    candidate_text = str(candidate or "").strip()
                    if candidate_text and candidate_text in card_text:
                        return candidate_text
                title_node = card.find(["h3", "h4"])
                title_text = title_node.get_text(" ", strip=True) if title_node is not None else card_text
                resolved = _extract_competitor_short(title_text)
                if resolved:
                    return resolved
                return str(competitors[-1]) if competitors else "竞品"

            def _find_stepper_container(card: Any) -> Optional[Any]:
                for container in card.find_all("div"):
                    cls = _classes(container)
                    if not {"flex", "flex-col", "gap-2", "mt-2"}.issubset(set(cls)):
                        continue
                    rows = [row for row in container.find_all("div", recursive=False) if _is_step_row(row)]
                    connectors = [
                        row for row in container.find_all("div", recursive=False) if _is_dashed_connector(row)
                    ]
                    if len(rows) >= 3 and len(connectors) >= 2:
                        return container
                return None

            def _fill_stepper_label(stepper: Any) -> bool:
                block = stepper.find_parent("div")
                if block is None:
                    return False
                for span in block.find_all("span"):
                    span_classes = _classes(span)
                    if not {"text-xs", "font-bold", "text-gray-400", "uppercase"}.issubset(
                        set(span_classes)
                    ):
                        continue
                    if span.get_text(" ", strip=True):
                        return False
                    span.clear()
                    span.append(NavigableString("决策路径演化"))
                    return True
                return False

            for card in section_root.find_all("div"):
                classes = _classes(card)
                if "glass-card" not in classes:
                    continue
                stepper = _find_stepper_container(card)
                if stepper is None:
                    continue

                if _fill_stepper_label(stepper):
                    filled += 1
                    filled_stepper += 1

                competitor_short = _resolve_competitor_short(card)
                competitor_short = self._truncate_micro_text(competitor_short, 10) or "竞品"
                step_texts = [
                    f"搜“{competitor_short} 音质”",
                    "看对比评测",
                ]

                step_rows = [
                    row
                    for row in stepper.find_all("div", recursive=False)
                    if _is_step_row(row)
                ]
                for idx, row in enumerate(step_rows[:3]):
                    spans = row.find_all("span", recursive=False)
                    if not spans:
                        continue

                    num_span: Optional[Any] = None
                    text_span: Optional[Any] = None
                    for span in spans:
                        span_classes = _classes(span)
                        if (
                            num_span is None
                            and "rounded-full" in span_classes
                            and "w-6" in span_classes
                            and "h-6" in span_classes
                        ):
                            num_span = span
                            continue
                        if text_span is None:
                            text_span = span

                    if num_span is None and len(spans) >= 1:
                        num_span = spans[0]
                    if text_span is None:
                        text_span = spans[-1] if len(spans) >= 2 else None
                    if num_span is None or text_span is None:
                        continue

                    if idx < 3 and not num_span.get_text(" ", strip=True):
                        num_span.clear()
                        num_span.append(NavigableString(str(idx + 1)))
                        filled += 1
                        filled_stepper += 1

                    if text_span.get_text(" ", strip=True):
                        continue

                    if idx < 2:
                        value = self._truncate_micro_text(step_texts[idx], 18)
                        text_span.clear()
                        text_span.append(NavigableString(value))
                        filled += 1
                        filled_stepper += 1
                        continue

                    icon = text_span.find("i", attrs={"data-lucide": "arrow-right"})
                    if icon is not None:
                        icon.extract()
                    else:
                        icon = soup.new_tag("i")
                        icon["data-lucide"] = "arrow-right"
                        icon["class"] = ["inline", "w-3", "h-3"]

                    prefix = self._truncate_micro_text("音质优先", 18)
                    suffix = self._truncate_micro_text(f"转向{competitor_short}", 18)
                    text_span.clear()
                    if prefix:
                        text_span.append(NavigableString(prefix))
                        filled += 1
                        filled_stepper += 1
                    text_span.append(icon)
                    if suffix:
                        text_span.append(NavigableString(suffix))
                        filled += 1
                        filled_stepper += 1

                if filled_stepper:
                    note_added = self._ensure_qualitative_note(
                        soup,
                        card,
                        reason="决策路径为定性推演",
                    ) or note_added

            if search_degraded or filled_search_tag:
                note_added = self._ensure_qualitative_note(
                    soup,
                    section_root,
                    reason="检索来源不足，部分关键词/标签为定性建议",
                ) or note_added

        return {"micro_fallback_filled": filled, "qualitative_note_added": note_added}

    def _sanitize_video_mock_placeholders(self, html_content: str, category: str) -> str:
        """
        非洗护品类：移除模板中仿“视频窗口”的背景图/播放按钮/角标，避免误导用户。

        保留布局骨架（grid/card），并用中性占位文字替代视觉素材。
        """
        category_l = str(category or "").lower()
        if any(marker in category_l for marker in self.WASHCARE_CATEGORY_MARKERS):
            return html_content

        soup = BeautifulSoup(html_content or "", "lxml")
        video_icon = soup.find("i", attrs={"data-lucide": "video"})
        if video_icon is None:
            return html_content

        scope = video_icon.find_parent("div", class_="reveal") or video_icon.find_parent("section") or soup
        panes: List[Any] = []
        for div in scope.find_all("div"):
            classes = [c for c in (div.get("class") or []) if isinstance(c, str)]
            if not {"md:col-span-5", "bg-black", "min-h-[200px]"}.issubset(set(classes)):
                continue
            panes.append(div)

        for pane in panes:
            # 移除历史占位提示文案（不再输出任何文字占位）。
            for node in list(pane.find_all(string=lambda s: isinstance(s, str) and "不展示模板视频素材" in s)):
                try:
                    parent = node.parent
                    if parent is not None:
                        parent.decompose()
                    else:
                        node.extract()
                except Exception:
                    continue

            # 背景图层（bg-[url(...)])
            for node in list(pane.find_all(True)):
                node_classes = [c for c in (node.get("class") or []) if isinstance(c, str)]
                if any("bg-[url(" in c for c in node_classes):
                    node.decompose()

            # style 内的 background-image
            for node in list(pane.find_all(True, attrs={"style": True})):
                style = str(node.get("style") or "")
                if "background-image" in style:
                    node.decompose()

            # img
            for img in list(pane.find_all("img")):
                img.decompose()

            # 播放按钮
            for play in list(pane.find_all("i", attrs={"data-lucide": "play"})):
                button = play.find_parent("div")
                if button is not None and button in pane.descendants:
                    button.decompose()
                else:
                    play.decompose()

            # 角标（左下角）
            for badge in list(pane.find_all("div")):
                classes = [c for c in (badge.get("class") or []) if isinstance(c, str)]
                if {"absolute", "bottom-2", "left-2"}.issubset(set(classes)):
                    badge.decompose()

        return str(soup)

    def _fix_strategy_resource_matrix_layout(self, html_content: str) -> str:
        """
        修复“战略总结与资源”里资源矩阵的固定高度（h-64）导致的文字被裁切问题。
        """
        soup = BeautifulSoup(html_content or "", "lxml")
        section_title = None
        for h2 in soup.find_all("h2", class_="section-title"):
            if "战略总结与资源" in h2.get_text(strip=True):
                section_title = h2
                break
        if section_title is None:
            return html_content

        section_root = section_title.find_parent("section")
        if section_root is None:
            return html_content

        for grid in section_root.find_all("div"):
            classes = [c for c in (grid.get("class") or []) if isinstance(c, str)]
            if not {"grid", "grid-cols-2", "gap-4", "h-64"}.issubset(set(classes)):
                continue
            classes = [c for c in classes if c != "h-64"]
            for token in ["min-h-[16rem]", "h-auto", "auto-rows-min"]:
                if token not in classes:
                    classes.append(token)
            grid["class"] = classes

        return str(soup)

    def _clear_section_content(
        self,
        soup: BeautifulSoup,
        section_id: str,
        section_index: int,
        brand: str,
        error_msg: str = "内容生成失败",
    ) -> bool:
        """
        当 LLM 注入失败时，清空模板中该 section 的原有内容，
        避免保留不相关的品类内容（如洗发水模板内容出现在耳机报告中）。

        Args:
            soup: 完整页面的 BeautifulSoup
            section_id: 模块 ID（hero/section-1...）
            section_index: content-section 的顺序索引
            brand: 当前品牌名称
            error_msg: 显示的错误信息

        Returns:
            bool: 是否成功清空
        """
        if section_id == "hero":
            # Hero 区域：保留结构但清空内容
            old_hero = soup.find("div", class_="hero")
            if old_hero is None:
                old_hero = soup.find("header", class_="header")
            if old_hero:
                old_hero.clear()
                placeholder = soup.new_tag("div")
                placeholder["class"] = "text-center py-12"
                placeholder_text = soup.new_tag("p")
                placeholder_text["class"] = "text-gray-400 text-lg"
                placeholder_text.string = f"{brand} 品牌摘要已触发兜底填充。"
                placeholder.append(placeholder_text)
                old_hero.append(placeholder)
                return True
            return False

        # 普通 section
        title_elems = soup.find_all("h2", class_="section-title")
        if section_index < 0 or section_index >= len(title_elems):
            return False
        old_title = title_elems[section_index]

        # 尝试找到整个 section 容器
        old_section = old_title.find_parent("section", class_="section")
        if old_section is not None:
            # 保留 section 容器和标题，但清空内部内容
            section_title = old_section.find("h2", class_="section-title")
            title_text = section_title.get_text(strip=True) if section_title else f"Section {section_index + 1}"
            
            # 清空并添加占位内容
            old_section.clear()
            
            # 重建标题
            new_h2 = soup.new_tag("h2")
            new_h2["class"] = [
                "section-title", "text-3xl", "font-bold", "mb-8", "flex", "items-center", "gap-3"
            ]
            new_h2.string = title_text
            old_section.append(new_h2)
            
            # 添加占位提示
            placeholder = soup.new_tag("div")
            placeholder["class"] = "glass-card p-8 text-center"
            placeholder_text = soup.new_tag("p")
            placeholder_text["class"] = "text-gray-400 text-lg"
            placeholder_text.string = f"{brand} 该模块已触发兜底填充。"
            placeholder.append(placeholder_text)
            old_section.append(placeholder)
            return True

        # 回退：尝试清空 grid 内容
        old_grid = old_title.find_next_sibling("div", class_="grid")
        if old_grid:
            old_grid.clear()
            placeholder_text = soup.new_tag("p")
            placeholder_text["class"] = "text-gray-400 text-center py-8 col-span-full"
            placeholder_text.string = "该模块已触发兜底填充。"
            old_grid.append(placeholder_text)
            return True

        return False

    def _prepare_template_for_llm(
        self,
        soup: BeautifulSoup,
        sections: List[Any],
        brand: str,
    ) -> None:
        """
        在 LLM 生成前，预先清空所有 section 的原始内容，只保留框架结构。
        
        这确保了即使 LLM 注入失败，也不会显示模板中不相关的原始内容（如洗发水内容出现在耳机报告中）。
        
        Args:
            soup: 完整页面的 BeautifulSoup
            sections: 解析出的 section 列表
            brand: 当前品牌名称
        """
        for section in sections:
            sec_index = -1
            if isinstance(section.section_id, str) and section.section_id.startswith("section-"):
                sec_index = int(section.section_id.split("-", 1)[1]) - 1

            if section.section_id == "hero":
                old_hero = soup.find("div", class_="hero")
                if old_hero is None:
                    old_hero = soup.find("header", class_="header")
                if old_hero is not None:
                    self._blank_text_nodes(old_hero, keep_section_title=False)
                    self._sanitize_numeric_placeholders(old_hero)
                continue

            title_elems = soup.find_all("h2", class_="section-title")
            if sec_index < 0 or sec_index >= len(title_elems):
                continue
            old_title = title_elems[sec_index]
            old_section = old_title.find_parent("section")
            if old_section is not None:
                self._blank_text_nodes(old_section, keep_section_title=True)
                self._sanitize_numeric_placeholders(old_section)

    def _extract_plain_title(self, section_title: str) -> str:
        return re.sub(r"\s+", "", section_title or "").strip()

    def _resolve_section_description(self, section: Any, report_type: str = "brand_health") -> str:
        title = self._extract_plain_title(getattr(section, "title", ""))
        if report_type == "brand_health":
            title_map = {
                "宏观趋势与格局": "宏观趋势与格局：市场规模、增速驱动、行业机会与风险。",
                "全球化洞察": "全球化洞察：区域差异、跨市场策略、国际化品牌打法。",
                "人群洞察与画像": "人群洞察与画像：核心客群、场景、需求与决策因子。",
                "竞品深度攻防": "竞品深度攻防：核心竞品定位、优劣势、内容与渠道打法。",
                "战略总结与资源": "战略总结与资源：优先级行动建议、资源分配与里程碑。",
            }
            if title in title_map:
                return title_map[title]
            id_map = {
                "hero": "报告头部，包含品牌名称、品类范围、时间范围和执行摘要。",
                "section-1": "宏观趋势与格局模块。",
                "section-2": "全球化洞察模块。",
                "section-3": "人群洞察与画像模块。",
                "section-4": "竞品深度攻防模块。",
                "section-5": "战略总结与资源模块。",
            }
            return id_map.get(getattr(section, "section_id", ""), f"报告模块：{section.title}")

        id_map_tiktok = {
            "hero": "报告头部，包含品类、商品卖点、时间范围与执行摘要",
            "section-1": "品类与平台概览模块：市场热度、受众画像、关键机会点",
            "section-2": "内容与话题趋势模块：热词/话题/内容形式趋势与样例拆解",
            "section-3": "创作者与投放打法模块：达人类型、脚本结构、投放建议与复用模板",
            "section-4": "行动建议与风险合规模块：可执行动作清单、合规红线、衡量指标",
        }
        return id_map_tiktok.get(getattr(section, "section_id", ""), f"报告模块：{section.title}")

    def _build_retry_reason(self, error_code: Optional[str]) -> str:
        reason_map = {
            "template_leak": "检测到模板示例品牌/占位词残留。",
            "title_mismatch": "模块标题与要求不一致。",
            "multi_section_output": "输出包含多个模块，超出单模块范围。",
            "template_similarity_high": "与模板原文相似度过高。",
            "structure_degraded": "结构完整度不足，缺少模板关键模块。",
            "category_mismatch": "出现与当前品类不匹配的词汇。",
            "inject_failed": "HTML 结构不符合注入要求。",
            "skipped_budget_exceeded": "超出本次生成预算。",
            "section_timeout": "单模块生成超时。",
            "missing_inline_sources": "缺少句内来源链接。",
        }
        return reason_map.get(error_code or "", "请严格按模块要求重写内容，不要复用模板原句。")

    def _collect_context_snippets(self, value: Any, output: List[str], limit: int = 8) -> None:
        if len(output) >= limit or value is None:
            return
        if isinstance(value, str):
            snippet = re.sub(r"\s+", " ", value).strip()
            if len(snippet) >= 24:
                output.append(snippet[:140])
            return
        if isinstance(value, dict):
            for key in ["summary", "insight", "analysis", "value", "text"]:
                if key in value and len(output) < limit:
                    self._collect_context_snippets(value.get(key), output, limit)
            for child in value.values():
                if len(output) >= limit:
                    break
                self._collect_context_snippets(child, output, limit)
            return
        if isinstance(value, (list, tuple, set)):
            for child in value:
                if len(output) >= limit:
                    break
                self._collect_context_snippets(child, output, limit)

    def _build_fallback_lines(
        self,
        section: Any,
        brand: str,
        category_text: str,
        competitors_text: str,
        context_data: Optional[Dict[str, Any]],
    ) -> List[str]:
        # 兜底模式：只给“可读结论/建议”，不拼接搜索片段（避免呈现为过程记录/证据碎片）。
        generic_lines = [
            f"• 结论：{brand}{category_text}的竞争正从“单点参数”转向“场景可感知体验”。",
            f"• 差异：对比{competitors_text}，优先突出“综合稳定性/通话与风噪/多场景降噪/生态联动”等可解释卖点。",
            "• 内容：以“场景对比评测 + 高频疑问答复”作为主内容形态，减少泛化夸赞。",
            "• 渠道：优先占位搜索/评测/直播等高意图入口，再用短视频与图文扩散种草。",
            "• 动作：按周复盘转化数据，持续迭代选题、脚本与卖点表达顺序。",
            "• 风险：缺乏可核验来源时只做定性表述，不编造数字/百分比。",
        ]

        combined = generic_lines
        deduped: List[str] = []
        seen: set[str] = set()
        for line in combined:
            normalized = re.sub(r"\s+", "", line)
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(line)
        return deduped

    def _render_rule_based_fallback_section(
        self,
        section: Any,
        brand: str,
        category: Optional[str],
        competitors: List[str],
        error_code: Optional[str] = None,
        context_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        section_title = getattr(section, "title", "模块洞察")
        category_text = category or "目标品类"
        competitors_text = "、".join([c for c in competitors if c]) if competitors else "主要竞品"
        error_hint = self._build_retry_reason(error_code)

        fallback_lines = self._build_fallback_lines(
            section=section,
            brand=brand,
            category_text=category_text,
            competitors_text=competitors_text,
            context_data=context_data,
        )
        if not any(marker in str(category_text).lower() for marker in self.WASHCARE_CATEGORY_MARKERS):
            blocked_words = ["清扬", "KONO", "Spes", "去屑", "头皮", "洗发"]
            for blocked in blocked_words:
                fallback_lines = [line.replace(blocked, "该赛道") for line in fallback_lines]

        if section.section_id == "hero":
            return f"""
<header class="header max-w-7xl mx-auto px-6 pt-20 pb-12 text-center relative z-10 reveal active">
  <h1 class="text-4xl md:text-6xl font-extrabold text-gray-900 mb-6 leading-tight">{brand} {category_text}市场洞察</h1>
  <p class="text-lg text-gray-500 max-w-3xl mx-auto">本模块使用兜底策略生成：{error_hint}。以下结论基于品牌基础信息与通用市场规律整理。</p>
</header>
""".strip()

        section_html = section.html_content or ""
        section_soup = BeautifulSoup(section_html, "lxml")

        root_section = section_soup.find("section", class_="section")
        if root_section is None:
            root_section = section_soup

        target_title = root_section.find("h2", class_="section-title")
        if target_title is not None:
            for text_node in target_title.find_all(string=True):
                if isinstance(text_node, str):
                    text_node.replace_with("")
            target_title.append(NavigableString(section_title))

        for text_node in list(root_section.find_all(string=True)):
            if not isinstance(text_node, str):
                continue
            if not text_node.strip():
                continue
            parent = text_node.parent
            if (
                parent is not None
                and getattr(parent, "name", None) in {"h3", "h4", "h5", "h6"}
                and re.match(r"^\s*\d+(?:\.\d+)?\s*", text_node)
            ):
                continue
            if (
                parent is not None
                and getattr(parent, "name", None) == "h2"
                and "section-title" in (parent.get("class") or [])
            ):
                continue
            text_node.replace_with("")

        cards = root_section.find_all("div", class_=lambda x: isinstance(x, str) and "glass-card" in x)
        dark_mode = self._is_dark_background_container(root_section)
        content_text_class = "text-gray-100" if dark_mode else "text-gray-700"
        title_text_class = "text-white" if dark_mode else "text-gray-800"
        note_text_class = "text-gray-300" if dark_mode else "text-gray-500"
        label_base = {
            "section-1": "趋势判断",
            "section-2": "关键发现",
            "section-3": "人群洞察",
            "section-4": "攻防结论",
            "section-5": "行动建议",
        }.get(str(getattr(section, "section_id", "")), "关键结论")
        if cards:
            for idx, card in enumerate(cards, start=1):
                payload = section_soup.new_tag("div")
                payload["class"] = ["fallback-content", "space-y-3", content_text_class]

                if idx == 1:
                    notice = section_soup.new_tag("p")
                    notice["class"] = ["text-sm", note_text_class, "mb-2"]
                    notice.string = f"注：此处内容由AI生成（原因：{error_hint}）"
                    payload.append(notice)

                subtitle = section_soup.new_tag("p")
                subtitle["class"] = ["font-semibold", title_text_class]
                subtitle.string = f"{label_base} {idx}"
                payload.append(subtitle)

                bullet_one = fallback_lines[(idx - 1) % len(fallback_lines)]
                bullet_two = fallback_lines[idx % len(fallback_lines)]

                ul = section_soup.new_tag("ul")
                ul["class"] = ["list-disc", "pl-5", "space-y-2", "text-sm", content_text_class]
                for line in [bullet_one, bullet_two]:
                    li = section_soup.new_tag("li")
                    li.string = line.lstrip("• ")
                    ul.append(li)
                payload.append(ul)

                card.clear()
                card.append(payload)

            if not any(marker in str(category_text).lower() for marker in self.WASHCARE_CATEGORY_MARKERS):
                polluted_markers = ["清扬", "KONO", "Spes", "去屑", "头皮", "洗发"]
                for node in root_section.find_all(string=True):
                    if not isinstance(node, str):
                        continue
                    new_text = node
                    for marker in polluted_markers:
                        new_text = new_text.replace(marker, "该赛道")
                    if new_text != node:
                        node.replace_with(new_text)
            return str(root_section)

        safe_title = section_title
        return f"""
<section class="section relative">
  <h2 class="section-title text-3xl font-bold mb-8 flex items-center gap-3 reveal">{safe_title}</h2>
  <div class="glass-card p-8 reveal">
    <p class="text-sm text-gray-500 mb-4">注：此处内容由AI生成（原因：{error_hint}）</p>
    <div class="space-y-3 text-gray-100">
      <p>{fallback_lines[0].replace("• ", "") if fallback_lines else "围绕品牌目标完成本模块要点补全。"}</p>
      <p>{fallback_lines[1].replace("• ", "") if len(fallback_lines) > 1 else "建议结合竞品与场景进行差异化表达。"}</p>
      <p>{fallback_lines[2].replace("• ", "") if len(fallback_lines) > 2 else "建议形成可执行的阶段性动作清单。"}</p>
      <p>{fallback_lines[3].replace("• ", "") if len(fallback_lines) > 3 else "建议在后续迭代中持续校验结论有效性。"}</p>
    </div>
  </div>
</section>
""".strip()

    def _is_dark_background_container(self, node: Any) -> bool:
        if node is None:
            return False
        for candidate in [node, *(node.find_parents() or [])]:
            classes = candidate.get("class") or []
            if any(cls in self.DARK_BG_MARKERS for cls in classes if isinstance(cls, str)):
                return True
        return False

    def _fix_dark_background_contrast(self, html_content: str) -> str:
        soup = BeautifulSoup(html_content or "", "lxml")
        dark_containers = soup.find_all(
            lambda tag: getattr(tag, "name", None)
            and any(cls in self.DARK_BG_MARKERS for cls in (tag.get("class") or []) if isinstance(cls, str))
        )

        replacements = {
            "text-gray-600": "text-gray-200",
            "text-gray-700": "text-gray-100",
            "text-gray-800": "text-white",
            "text-slate-600": "text-slate-200",
            "text-slate-700": "text-slate-100",
            "text-slate-800": "text-white",
        }

        for container in dark_containers:
            for node in container.find_all(True):
                classes = node.get("class") or []
                if not classes:
                    continue
                updated = [replacements.get(token, token) for token in classes]
                node["class"] = updated

        return str(soup)

    def _attempt_section_generation(
        self,
        section: Any,
        sec_index: int,
        brand: str,
        category: Optional[str],
        competitors: List[str],
        context_data: Dict[str, Any],
        source_links: List[Dict[str, str]],
        generate_once: Callable[[Optional[str], float, float, int, float], str],
        *,
        first_timeout_s: Optional[float] = None,
        retry_timeout_s: Optional[float] = None,
        max_attempts: int = 2,
    ) -> Tuple[str, bool, Optional[str], Dict[str, Any], int, Dict[str, Any]]:
        attempts_limit = max(1, int(max_attempts or 2))
        last_error: Optional[str] = None
        last_metrics: Dict[str, Any] = {}
        last_exception: Optional[Exception] = None
        diagnostics: Dict[str, Any] = {
            "provider_error_type": None,
            "provider_error_message": None,
            "timeout_hit": False,
            "fallback_reason": None,
            "search_degraded": bool(
                ((context_data.get("llm_search") or {}).get("_meta") or {}).get("search_degraded", False)
                if isinstance(context_data, dict)
                else False
            ),
            "attempts_detail": [],
        }

        first_timeout_value = float(
            first_timeout_s
            if first_timeout_s is not None
            else (getattr(settings, "section_llm_timeout_seconds", 120) or 120)
        )
        retry_timeout_value = float(
            retry_timeout_s
            if retry_timeout_s is not None
            else (getattr(settings, "section_retry_timeout_seconds", 75) or 75)
        )
        retry_relaxed_coverage = self._coerce_inline_source_min_coverage(
            getattr(settings, "retry_relax_inline_source_coverage", 0.70),
            default=0.70,
        )
        retry_compression_ratio = float(getattr(settings, "retry_context_compression_ratio", 0.55) or 0.55)
        if retry_compression_ratio <= 0 or retry_compression_ratio > 1:
            retry_compression_ratio = 0.55

        for attempt in range(1, attempts_limit + 1):
            retry_reason = self._build_retry_reason(last_error) if attempt > 1 else None
            temperature = 0.1 if attempt > 1 else 0.3
            timeout_s = retry_timeout_value if attempt > 1 else first_timeout_value
            inline_min_coverage = retry_relaxed_coverage if attempt > 1 else self.INLINE_SOURCE_MIN_COVERAGE
            compression_ratio = retry_compression_ratio if attempt > 1 else 1.0

            attempt_detail: Dict[str, Any] = {
                "attempt": attempt,
                "timeout_s": round(float(timeout_s), 4),
                "temperature": round(float(temperature), 4),
                "compression_ratio": round(float(compression_ratio), 4),
                "call_ok": None,
                "call_error_type": None,
                "call_error_message": None,
                "validation_ok": None,
                "validation_error_code": None,
            }

            try:
                generated = self._call_with_timeout(
                    lambda: generate_once(
                        retry_reason,
                        temperature,
                        timeout_s,
                        1,
                        compression_ratio,
                    ),
                    timeout_s=timeout_s,
                )
                attempt_detail["call_ok"] = True
            except TimeoutError as timeout_exc:
                diagnostics["timeout_hit"] = True
                diagnostics["provider_error_type"] = type(timeout_exc).__name__
                diagnostics["provider_error_message"] = str(timeout_exc) or "section timeout"
                attempt_detail["call_ok"] = False
                attempt_detail["call_error_type"] = type(timeout_exc).__name__
                attempt_detail["call_error_message"] = str(timeout_exc) or "section timeout"
                diagnostics["attempts_detail"].append(attempt_detail)
                last_exception = timeout_exc
                last_error = "section_timeout"
                last_metrics = {"timeout_s": timeout_s, "attempt": attempt}
                continue
            except Exception as call_exc:
                diagnostics["provider_error_type"] = type(call_exc).__name__
                diagnostics["provider_error_message"] = str(call_exc)
                attempt_detail["call_ok"] = False
                attempt_detail["call_error_type"] = type(call_exc).__name__
                attempt_detail["call_error_message"] = str(call_exc)
                diagnostics["attempts_detail"].append(attempt_detail)
                last_exception = call_exc
                last_error = "provider_error"
                last_metrics = {"attempt": attempt}
                continue

            cleaned = clean_llm_html_response(generated)
            cleaned = sanitize_html(cleaned)
            if bool(getattr(settings, "inline_source_link_auto_inject", True)) and source_links:
                cleaned = self._inject_inline_source_links(cleaned, source_links)

            ok, error_code, metrics = self._validate_generated_section(
                generated_html=cleaned,
                section=section,
                expected_title=section.title,
                brand=brand,
                competitors=competitors,
                category=category,
                source_links=source_links,
                inline_source_min_coverage=inline_min_coverage,
            )
            attempt_detail["validation_ok"] = bool(ok)
            attempt_detail["validation_error_code"] = error_code
            for key in [
                "structure_retention_ratio",
                "inline_source_coverage",
                "similarity_ratio",
                "filled_block_count",
                "empty_block_count",
            ]:
                if key in metrics:
                    attempt_detail[key] = metrics.get(key)
            diagnostics["attempts_detail"].append(attempt_detail)
            if ok:
                diagnostics["fallback_reason"] = None
                return cleaned, True, None, metrics, attempt, diagnostics
            last_error = error_code
            last_metrics = metrics

        fallback_reason = last_error or "validation_fail"
        if fallback_reason == "provider_error" and last_exception is None:
            fallback_reason = "provider_error"
        diagnostics["fallback_reason"] = fallback_reason

        fallback_html = self._render_rule_based_fallback_section(
            section=section,
            brand=brand,
            category=category,
            competitors=competitors,
            error_code=last_error,
            context_data=context_data,
        )
        return fallback_html, False, last_error, last_metrics, attempts_limit, diagnostics

    def _normalize_external_links(self, html_content: str) -> str:
        """
        统一外链跳转行为：外部链接新开窗口，并补齐 noopener/noreferrer。
        主要用于 LLM 生成的内嵌引用链接（.source-link）。
        """
        soup = BeautifulSoup(html_content, "lxml")
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if href.startswith("http://") or href.startswith("https://"):
                a["target"] = "_blank"
                rel = a.get("rel") or []
                if isinstance(rel, str):
                    rel = rel.split()
                rel_set = {r.strip() for r in rel if isinstance(r, str) and r.strip()}
                rel_set.update({"noopener", "noreferrer"})
                a["rel"] = sorted(rel_set)
        return str(soup)
    
    def _collect_data(
        self,
        brand: str,
        competitors: List[str]
    ) -> Dict[str, Any]:
        """
        收集所有数据源的数据
        
        Args:
            brand: 目标品牌
            competitors: 竞品列表
            
        Returns:
            聚合后的数据
        """
        collected_data = {
            "brand": brand,
            "competitors": competitors,
            "collected_at": datetime.now().isoformat(),
            "sources": {}
        }
        
        for source_name, source in self.data_sources.items():
            try:
                if source.is_available():
                    data = source.fetch(brand, competitors)
                    collected_data["sources"][source_name] = {
                        "status": "success",
                        "data": data
                    }
                else:
                    collected_data["sources"][source_name] = {
                        "status": "unavailable",
                        "data": None
                    }
            except Exception as e:
                collected_data["sources"][source_name] = {
                    "status": "error",
                    "error": str(e),
                    "data": None
                }
        
        return collected_data

    def _apply_replacements(self, html_content: str, replacements: Dict[str, str]) -> str:
        result = html_content
        for src, dst in replacements.items():
            if src:
                result = result.replace(src, dst)
        return result

    def _inject_source_links(self, html_content: str, source_links: List[Dict[str, str]]) -> str:
        """
        将来源链接注入到报告中的 “数据来源与可追溯性 / Sources” 区块。

        优先寻找 ul#sources-list；否则尝试在包含 “数据来源” 的 card 下创建一个列表。
        """
        if not source_links:
            return html_content

        soup = BeautifulSoup(html_content, "lxml")
        ul = soup.find("ul", id="sources-list")

        if ul is None:
            # 尝试定位 sources card
            sources_card = None
            for h2 in soup.find_all("h2"):
                if "数据来源" in h2.get_text(strip=True) or "Sources" in h2.get_text(strip=True):
                    parent = h2.find_parent("div", class_="card")
                    if parent:
                        sources_card = parent
                        break
            if sources_card is not None:
                ul = sources_card.find("ul")
                if ul is None:
                    ul = soup.new_tag("ul")
                    ul["class"] = "list"
                    sources_card.append(ul)

        if ul is None:
            # 兜底：模板未提供 sources 容器时，在 footer 前追加一个 Sources 区块
            container = (
                soup.find("div", class_="container")
                or soup.find("div", class_="wrap")
                or soup.body
            )
            if container is None:
                return html_content

            footer = soup.find("footer", class_="footer")

            section = soup.new_tag("section")
            section["class"] = "section"
            section["style"] = (
                "max-width: 860px; margin: 4rem auto 2rem; padding: 0 1.5rem;"
            )

            # 分隔线装饰
            divider = soup.new_tag("div")
            divider["style"] = (
                "text-align: center; margin-bottom: 1.5rem; "
                "font-size: 1.5rem; opacity: 0.5;"
            )
            divider.string = "· · ·"
            section.append(divider)

            h2 = soup.new_tag("h2")
            h2["style"] = (
                "text-align: center; font-size: 1.1rem; font-weight: 700; "
                "color: #ea8c00; margin-bottom: 1.2rem; letter-spacing: 0.05em;"
            )
            h2.string = "🔗 数据来源"
            section.append(h2)

            card = soup.new_tag("div")
            card["style"] = (
                "background: rgba(255,255,255,0.7); "
                "border: 1px solid rgba(255,165,0,0.25); "
                "border-radius: 16px; padding: 1.5rem 2rem; "
                "backdrop-filter: blur(12px); "
                "-webkit-backdrop-filter: blur(12px); "
                "box-shadow: 0 2px 12px rgba(255,140,0,0.06);"
            )
            section.append(card)

            ul = soup.new_tag("ul")
            ul["style"] = (
                "list-style: none; margin: 0; padding: 0; "
                "columns: 1; column-gap: 1.5rem; "
                "text-align: center;"
            )
            card.append(ul)

            if footer is not None:
                footer.insert_before(section)
            else:
                container.append(section)

        # 清空旧内容
        ul.clear()
        seen: set[str] = set()
        for item in source_links:
            url = (item.get("url") or "").strip()
            title = (item.get("title") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)

            li = soup.new_tag("li")
            li["style"] = (
                "padding: 0.4rem 0; font-size: 0.85rem; "
                "break-inside: avoid; line-height: 1.6;"
            )
            a = soup.new_tag("a", href=url)
            a.string = title or url
            a["target"] = "_blank"
            a["rel"] = "noopener noreferrer"
            a["style"] = (
                "color: #d97706; text-decoration: none; "
                "border-bottom: 1px dashed rgba(217,119,6,0.3); "
                "transition: color 0.2s, border-color 0.2s;"
            )
            li.append(a)
            ul.append(li)

        return str(soup)

    def _postprocess_brand_health_html(self, html_content: str, category: str) -> str:
        """
        不修改模板文件，仅对生成后的 HTML 做字段适配：
        - 删除 hero meta 中的“店铺：...” chip
        - 将“竞品：...” 改为“推荐竞品：...”
        - 在“品牌：...” chip 后插入“品类：{category}”
        """
        if not category:
            return html_content

        soup = BeautifulSoup(html_content, "lxml")
        hero = soup.find("div", class_="hero")
        if hero is None:
            return html_content
        meta = hero.find("div", class_="meta")
        if meta is None:
            return html_content

        chips = meta.find_all("span", class_="chip")
        # 1) remove shop chip
        for chip in chips:
            text = chip.get_text(strip=True)
            if "店铺：" in text:
                chip.decompose()

        # 2) rename competitors chip prefix
        chips = meta.find_all("span", class_="chip")
        for chip in chips:
            text = chip.get_text(strip=True)
            if text.startswith("竞品："):
                # Preserve original remainder
                chip.string = "推荐竞品：" + text[len("竞品：") :]
                break

        # 3) insert category chip after brand chip (avoid duplicates)
        chips = meta.find_all("span", class_="chip")
        if any("品类：" in c.get_text(strip=True) for c in chips):
            return str(soup)

        brand_chip = None
        for chip in chips:
            if chip.get_text(strip=True).startswith("品牌："):
                brand_chip = chip
                break

        new_chip = soup.new_tag("span")
        new_chip["class"] = "chip"
        new_chip.string = f"品类：{category}"

        if brand_chip is not None:
            brand_chip.insert_after(new_chip)
        else:
            meta.append(new_chip)

        return str(soup)

    def _postprocess_tiktok_header_html(
        self,
        html_content: str,
        category_name: str,
        product_selling_points: List[str],
    ) -> str:
        """
        不修改模板文件，仅对生成后的 HTML 做字段适配：
        - 修改 header.header 的 h1 文案为品类版本
        - 追加（或更新）一行“商品卖点：...”
        """
        soup = BeautifulSoup(html_content, "lxml")
        header = soup.find("header", class_="header")
        if header is None:
            return html_content

        h1 = header.find("h1")
        if h1 is not None and category_name:
            h1.string = f"🦷 TikTok 美区{category_name}品类市场洞察"

        selling_points = [p.strip() for p in product_selling_points if p and p.strip()]
        if not selling_points:
            return str(soup)

        sp_text = f"商品卖点：{'、'.join(selling_points)}"
        existing = None
        for p in header.find_all("p"):
            if "商品卖点：" in p.get_text(strip=True):
                existing = p
                break
        if existing is not None:
            existing.string = sp_text
        else:
            p = soup.new_tag("p")
            p.string = sp_text
            header.append(p)

        return str(soup)
    
    def _has_meaningful_value(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, dict):
            return any(self._has_meaningful_value(item) for item in value.values())
        if isinstance(value, (list, tuple, set)):
            return any(self._has_meaningful_value(item) for item in value)
        return True

    def _has_sufficient_section_evidence(self, section_id: str, context_data: Dict[str, Any]) -> bool:
        relevant_data = self._extract_relevant_data(section_id, context_data)
        llm_search = relevant_data.get("llm_search") if isinstance(relevant_data, dict) else None
        if isinstance(llm_search, dict):
            meta = llm_search.get("_meta")
            links = meta.get("source_links") if isinstance(meta, dict) else None
            if isinstance(links, list) and len(links) >= 2:
                return True

        evidence_key_map = {
            "hero": ["douyin_trends", "douyin_audience", "llm_search"],
            "section-1": ["douyin_trends", "douyin_audience", "llm_search"],
            "section-2": ["xhs_insights", "xhs_topics", "douyin_audience", "llm_search"],
            "section-3": ["xhs_notes", "douyin_videos", "llm_search"],
            "section-4": ["all_sources", "llm_search"],
            "section-5": ["strategic_summary", "llm_search"],
        }
        keys = evidence_key_map.get(section_id, ["llm_search", "all_sources"])
        return any(self._has_meaningful_value(relevant_data.get(key)) for key in keys)

    def _annotate_ai_generated_section(
        self,
        generated_html: str,
        reason: str = "实时检索信息不足",
    ) -> str:
        fragment = BeautifulSoup(generated_html or "", "lxml")

        if fragment.find("p", class_=lambda x: isinstance(x, str) and "ai-generated-note" in x):
            return generated_html

        note = fragment.new_tag("p")
        note["class"] = ["text-xs", "text-gray-400", "mt-2", "ai-generated-note"]
        note.string = f"注：此处内容由AI生成（{reason}）。"

        title = fragment.find("h2", class_="section-title")
        if title is not None:
            title.insert_after(note)
            return str(fragment)

        header = fragment.find("header")
        if header is not None:
            header.append(note)
            return str(fragment)

        root = fragment.body or fragment
        if root.contents:
            root.insert(0, note)
        else:
            root.append(note)
        return str(fragment)

    def _generate_section_content(
        self,
        section: Any,
        brand: str,
        competitors: List[str],
        context_data: Dict[str, Any],
        retry_reason: Optional[str] = None,
        temperature: float = 0.3,
        timeout_s: float = 90.0,
        retry_attempts: int = 1,
        context_compression_ratio: float = 1.0,
    ) -> str:
        """
        生成单个模块的内容
        
        Args:
            section: 模板模块
            brand: 目标品牌
            competitors: 竞品列表
            context_data: 上下文数据
            
        Returns:
            生成的 HTML 内容
        """
        section_desc = self._resolve_section_description(section, report_type="brand_health")
        
        # 提取相关数据
        relevant_data = self._extract_relevant_data(
            section.section_id,
            context_data
        )
        
        # 构建模板结构信息
        template_structure = self._build_template_structure(section)

        section_name = section.title
        if getattr(section, "section_id", None) == "hero":
            category_value = str((context_data or {}).get("category") or "").strip()
            # hero 的 section.title 固定为“报告头部”（内部标记），不应进入报告正文标题。
            section_name = f"{brand}{category_value}市场洞察" if category_value else f"{brand}市场洞察"
        
        # 调用 LLM 生成内容
        generated_content = self.llm_client.generate_report_section(
            section_name=section_name,
            section_description=section_desc,
            brand=brand,
            competitors=competitors,
            context_data=relevant_data,
            template_structure=template_structure,
            temperature=temperature,
            retry_reason=retry_reason,
            timeout_s=timeout_s,
            retry_attempts=retry_attempts,
            context_compression_ratio=context_compression_ratio,
        )
        
        return generated_content

    def _postprocess_brand_health_header_title(
        self,
        html_content: str,
        brand: str,
        category: Optional[str],
    ) -> str:
        soup = BeautifulSoup(html_content or "", "lxml")
        header = soup.find("header", class_="header")
        if header is None:
            return html_content

        h1 = header.find("h1")
        if h1 is None:
            return html_content

        current = h1.get_text(" ", strip=True)
        if current and current != "报告头部":
            return str(soup)

        category_value = str(category or "").strip()
        desired = f"{brand}{category_value}市场洞察" if category_value else f"{brand}市场洞察"
        h1.clear()
        h1.append(NavigableString(desired))
        return str(soup)
    
    def _extract_relevant_data(
        self,
        section_id: str,
        context_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        根据模块类型提取相关数据
        
        Args:
            section_id: 模块 ID
            context_data: 完整上下文数据
            
        Returns:
            与该模块相关的数据
        """
        relevant = {
            "brand": context_data.get("brand"),
            "competitors": context_data.get("competitors")
        }

        if context_data.get("category"):
            relevant["category"] = context_data.get("category")
        if context_data.get("category_name"):
            relevant["category_name"] = context_data.get("category_name")
        if context_data.get("product_selling_points"):
            relevant["product_selling_points"] = context_data.get("product_selling_points")
        
        sources = context_data.get("sources", {})
        llm_search = context_data.get("llm_search")
        if llm_search:
            # 仅保留高价值字段，避免 context 过大导致模型输出退化。
            if isinstance(llm_search, dict):
                compact_search = {
                    "brand_overview": llm_search.get("brand_overview"),
                    "market_trends": llm_search.get("market_trends"),
                    "consumer_insights": llm_search.get("consumer_insights"),
                    "competitive_analysis": llm_search.get("competitive_analysis"),
                    "recommendations": llm_search.get("recommendations"),
                    "_meta": llm_search.get("_meta"),
                }
                relevant["llm_search"] = compact_search
            else:
                relevant["llm_search"] = llm_search

        include_mock = bool(getattr(settings, "include_mock_prompt_data", False))
        usable_sources: Dict[str, Any] = {}
        skipped_mock_sources: List[str] = []
        for source_name, source_payload in sources.items():
            payload = source_payload or {}
            data = payload.get("data") if isinstance(payload, dict) else None
            is_mock = bool((data or {}).get("query_context", {}).get("is_mock")) if isinstance(data, dict) else False
            if is_mock and not include_mock:
                skipped_mock_sources.append(source_name)
                continue
            usable_sources[source_name] = payload

        if skipped_mock_sources:
            relevant["mock_sources_skipped"] = skipped_mock_sources
        sources = usable_sources
        
        if section_id in ["hero", "section-1"]:
            # 市场洞察需要趋势和竞品数据
            if "douyin" in sources and sources["douyin"].get("data"):
                relevant["douyin_trends"] = sources["douyin"]["data"].get("content_trends", {})
                relevant["douyin_audience"] = sources["douyin"]["data"].get("audience_analytics", {})
        
        if section_id == "section-2":
            # 消费者洞察需要用户画像和评论数据
            if "xiaohongshu" in sources and sources["xiaohongshu"].get("data"):
                relevant["xhs_insights"] = sources["xiaohongshu"]["data"].get("consumer_insights", {})
                relevant["xhs_topics"] = sources["xiaohongshu"]["data"].get("trending_topics", [])
            if "douyin" in sources and sources["douyin"].get("data"):
                relevant["douyin_audience"] = sources["douyin"]["data"].get("audience_analytics", {})
        
        if section_id == "section-3":
            # 健康度洞察需要社媒内容数据
            if "xiaohongshu" in sources and sources["xiaohongshu"].get("data"):
                relevant["xhs_notes"] = sources["xiaohongshu"]["data"].get("hot_notes", [])
            if "douyin" in sources and sources["douyin"].get("data"):
                relevant["douyin_videos"] = sources["douyin"]["data"].get("hot_videos", [])
        
        if section_id == "section-4":
            # 策略模块需要综合数据
            relevant["all_sources"] = sources

        if section_id == "section-5":
            relevant["strategic_summary"] = {
                "llm_search_summary": (llm_search or {}).get("brand_overview") if isinstance(llm_search, dict) else None,
                "all_sources": sources,
            }
        
        # 额外上下文压缩：避免把超大结构直接喂给 LLM。
        try:
            serialized = str(relevant)
            if len(serialized) > 24000:
                trimmed = {
                    "brand": relevant.get("brand"),
                    "competitors": relevant.get("competitors"),
                    "category": relevant.get("category") or relevant.get("category_name"),
                    "llm_search": (relevant.get("llm_search") or {}),
                    "strategic_summary": relevant.get("strategic_summary"),
                    "mock_sources_skipped": relevant.get("mock_sources_skipped"),
                }
                relevant = trimmed
        except Exception:
            pass

        return relevant

    def generate_brand_health(
        self,
        brand_name: str,
        category: str,
        competitors: List[str],
        template_name: str = "海飞丝.html",
        use_llm: bool = True,
        strict_llm: bool = False,
        enable_web_search: bool = True,
    ) -> Dict[str, Any]:
        return self.generate(
            brand=brand_name,
            competitors=competitors,
            template_name=template_name,
            use_llm=use_llm,
            strict_llm=strict_llm,
            enable_web_search=enable_web_search,
            extra_context={"category": category, "report_type": "brand_health"},
            web_search_query=f"{brand_name} {category} 品类 市场分析 消费者洞察 竞品分析",
        )

    def _generate_tiktok_section_content(
        self,
        section: Any,
        category_name: str,
        product_selling_points: List[str],
        context_data: Dict[str, Any],
        retry_reason: Optional[str] = None,
        temperature: float = 0.3,
        timeout_s: float = 90.0,
        retry_attempts: int = 1,
        context_compression_ratio: float = 1.0,
    ) -> str:
        section_desc = self._resolve_section_description(section, report_type="tiktok_social_insight")

        relevant_data = self._extract_relevant_data(section.section_id, context_data)
        template_structure = self._build_template_structure(section)

        generated_content = self.llm_client.generate_tiktok_insight_section(
            section_name=section.title,
            section_description=section_desc,
            category_name=category_name,
            product_selling_points=product_selling_points,
            context_data=relevant_data,
            template_structure=template_structure,
            temperature=temperature,
            retry_reason=retry_reason,
            timeout_s=timeout_s,
            retry_attempts=retry_attempts,
            context_compression_ratio=context_compression_ratio,
        )
        return generated_content

    def generate_tiktok_social_insight(
        self,
        category_name: str,
        product_selling_points: List[str],
        template_name: str = "tiktok-toothpaste-report.html",
        use_llm: bool = True,
        strict_llm: bool = False,
        enable_web_search: bool = True,
    ) -> Dict[str, Any]:
        report_id = f"tiktok-{category_name}-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4]}"

        parsed = self.template_parser.parse(template_name)

        # 复用现有 Mock 数据源（以 category 作为 key，不影响静态 mock 的结构）
        context_data = self._collect_data(category_name, [])
        context_data["report_type"] = "tiktok_social_insight"
        context_data["category_name"] = category_name
        context_data["product_selling_points"] = product_selling_points

        template_path = self.template_parser.template_dir / template_name
        with open(template_path, "r", encoding="utf-8") as f:
            original_html = f.read()

        result_html = self._apply_replacements(
            original_html,
            {
                "{{CATEGORY_NAME}}": category_name,
                "{{SELLING_POINTS}}": "、".join([p for p in product_selling_points if p]),
            },
        )
        # 无占位符模板：补一层 header 适配（不修改模板文件）
        result_html = self._postprocess_tiktok_header_html(
            html_content=result_html,
            category_name=category_name,
            product_selling_points=product_selling_points,
        )

        if use_llm:
            llm_started = time.perf_counter()
            ping = self.llm_client.ping()
            context_data["llm_ping"] = ping
            if not ping.get("ok"):
                message = (
                    "LLM API 调用失败（未能完成最小 ping）。"
                    f" base_url={getattr(self.llm_client, 'base_url', '')!r}"
                    f" model={getattr(self.llm_client, 'model', '')!r}"
                    f" error={ping.get('error')}"
                )
                if strict_llm:
                    raise RuntimeError(message)
                context_data["llm_error"] = message

            if enable_web_search and ping.get("ok"):
                query = (
                    f"TikTok {category_name} 品类 趋势 热词 话题 内容形式 "
                    f"卖点 {' '.join(product_selling_points[:5])}"
                )
                search_timeout_s = float(getattr(settings, "search_total_timeout_seconds", 90) or 90)
                try:
                    search_result = self._call_with_timeout(
                        lambda: self.llm_client.search_and_generate(
                            query=query,
                            brand=category_name,
                            competitors=[],
                        ),
                        timeout_s=search_timeout_s,
                    )
                except Exception as exc:
                    search_result = {
                        "_meta": {
                            "ok": False,
                            "used_web_search": False,
                            "tool_type": "tavily",
                            "latency_ms": int(search_timeout_s * 1000),
                            "source_links": [],
                            "error": f"{type(exc).__name__}: {str(exc)}",
                            "search_degraded": True,
                            "search_error_type": type(exc).__name__,
                            "search_error_message": str(exc),
                        },
                        "parse_error": True,
                    }
                if isinstance(search_result, dict) and search_result.get("parse_error"):
                    search_meta = (search_result.get("_meta") or {}) if isinstance(search_result, dict) else {}
                    search_degraded = bool(search_meta.get("search_degraded", False))
                    if strict_llm and not search_degraded:
                        raise RuntimeError(
                            "LLM 搜索返回结果无法解析为 JSON。"
                            f" base_url={getattr(self.llm_client, 'base_url', '')!r}"
                            f" model={getattr(self.llm_client, 'model', '')!r}"
                        )
                context_data["llm_search"] = search_result

            if ping.get("ok"):
                llm_sections: List[Dict[str, Any]] = []
                soup = BeautifulSoup(result_html, "lxml")
                sections = parsed.get("sections", [])
                category_value = category_name
                source_links: List[Dict[str, str]] = []
                llm_search_meta = (context_data.get("llm_search") or {}).get("_meta") if isinstance(context_data.get("llm_search"), dict) else None
                if isinstance(llm_search_meta, dict) and llm_search_meta.get("used_web_search"):
                    source_links = llm_search_meta.get("source_links") or []
                
                # 🔑 关键步骤：在 LLM 生成前，先清空所有 section 的原始内容
                self._prepare_template_for_llm(soup, sections, category_name)
                
                soft_timeout_s = float(getattr(settings, "report_job_soft_timeout_seconds", 720) or 720)
                safety_margin_s = 20.0
                llm_deadline_s = max(soft_timeout_s - safety_margin_s, 60.0)

                consecutive_failures = 0
                for idx, section in enumerate(sections):
                    sec_started = time.perf_counter()
                    elapsed_total = time.perf_counter() - llm_started
                    remaining_total_s = llm_deadline_s - elapsed_total
                    remaining_sections = max(len(sections) - idx, 1)
                    sec_index = -1
                    insufficient_evidence = False
                    section_search_degraded = bool(
                        ((context_data.get("llm_search") or {}).get("_meta") or {}).get("search_degraded", False)
                        if isinstance(context_data, dict)
                        else False
                    )
                    provider_error_type: Optional[str] = None
                    provider_error_message: Optional[str] = None
                    timeout_hit = False
                    fallback_reason: Optional[str] = None
                    try:
                        if isinstance(section.section_id, str) and section.section_id.startswith("section-"):
                            sec_index = int(section.section_id.split("-", 1)[1]) - 1

                        insufficient_evidence = not self._has_sufficient_section_evidence(
                            section.section_id,
                            context_data,
                        )

                        if remaining_total_s <= 6:
                            raise TimeoutError("job deadline reached before section generation")

                        section_budget_s = max(6.0, remaining_total_s / remaining_sections)
                        base_first_timeout = float(getattr(settings, "section_llm_timeout_seconds", 120) or 120)
                        base_retry_timeout = float(getattr(settings, "section_retry_timeout_seconds", 75) or 75)
                        first_timeout_s = min(base_first_timeout, max(8.0, section_budget_s * 0.7))
                        retry_timeout_s = min(base_retry_timeout, max(0.0, section_budget_s - first_timeout_s))
                        attempts_limit = 2 if retry_timeout_s >= 6.0 else 1

                        cleaned, validated_ok, validation_error, metrics, attempts, section_diag = self._attempt_section_generation(
                            section=section,
                            sec_index=sec_index,
                            brand=category_name,
                            category=category_value,
                            competitors=[],
                            context_data=context_data,
                            source_links=source_links,
                            generate_once=lambda retry_reason, temperature, timeout_s, retry_attempts, compression_ratio: self._generate_tiktok_section_content(
                                section=section,
                                category_name=category_name,
                                product_selling_points=product_selling_points,
                                context_data=context_data,
                                retry_reason=retry_reason,
                                temperature=temperature,
                                timeout_s=timeout_s,
                                retry_attempts=retry_attempts,
                                context_compression_ratio=compression_ratio,
                            ),
                            first_timeout_s=first_timeout_s,
                            retry_timeout_s=retry_timeout_s,
                            max_attempts=attempts_limit,
                        )
                        provider_error_type = section_diag.get("provider_error_type") if isinstance(section_diag, dict) else None
                        provider_error_message = section_diag.get("provider_error_message") if isinstance(section_diag, dict) else None
                        timeout_hit = bool(section_diag.get("timeout_hit")) if isinstance(section_diag, dict) else False
                        fallback_reason = section_diag.get("fallback_reason") if isinstance(section_diag, dict) else None
                        section_search_degraded = bool(section_diag.get("search_degraded")) if isinstance(section_diag, dict) else section_search_degraded

                        if insufficient_evidence:
                            cleaned = self._annotate_ai_generated_section(
                                cleaned,
                                reason="实时检索信息不足",
                            )

                        injected, inject_error, inject_metrics = self._inject_generated_section(
                            soup=soup,
                            section_id=section.section_id,
                            section_index=sec_index,
                            generated_html=cleaned,
                            expected_title=section.title,
                        )
                        error_reason = None if injected else (validation_error or inject_error or "inject_failed")
                        if not injected:
                            if strict_llm:
                                raise RuntimeError(
                                    f"LLM 返回的 HTML 无法注入到模板中: section_id={section.section_id}"
                                )
                        consecutive_failures = 0 if injected else (consecutive_failures + 1)
                        micro_final_metrics: Dict[str, Any] = (
                            inject_metrics if isinstance(inject_metrics, dict) else {}
                        )
                        if injected and sec_index >= 0:
                            section_root = self._find_section_root_by_index(soup, sec_index)
                            if section_root is not None:
                                self._fill_key_micro_blanks_in_section(
                                    soup=soup,
                                    section_root=section_root,
                                    section_id=section.section_id,
                                    brand=category_name,
                                    category=category_value,
                                    competitors=[],
                                    search_degraded=section_search_degraded,
                                )
                                micro_final_metrics = self._compute_micro_slot_metrics(section_root)
                        similarity_ratio = metrics.get("similarity_ratio") if isinstance(metrics, dict) else None
                        llm_sections.append(
                            {
                                "section_id": section.section_id,
                                "title": section.title,
                                "ok": bool(injected),
                                "latency_ms": int((time.perf_counter() - sec_started) * 1000),
                                "error": error_reason,
                                "attempts": attempts,
                                "validation_error": validation_error,
                                "similarity_ratio": similarity_ratio,
                                "used_fallback": bool(not validated_ok),
                                "fallback_reason": fallback_reason,
                                "ai_generated": bool(insufficient_evidence),
                                "inline_source_ok": metrics.get("inline_source_ok") if isinstance(metrics, dict) else None,
                                "inline_source_coverage": metrics.get("inline_source_coverage") if isinstance(metrics, dict) else None,
                                "structure_retention_ratio": metrics.get("structure_retention_ratio") if isinstance(metrics, dict) else None,
                                "filled_block_count": metrics.get("filled_block_count") if isinstance(metrics, dict) else None,
                                "empty_block_count": metrics.get("empty_block_count") if isinstance(metrics, dict) else None,
                                "micro_slots_total": micro_final_metrics.get("micro_slots_total"),
                                "micro_slots_filled": micro_final_metrics.get("micro_slots_filled"),
                                "micro_slots_empty": micro_final_metrics.get("micro_slots_empty"),
                                "provider_error_type": provider_error_type,
                                "provider_error_message": provider_error_message,
                                "timeout_hit": timeout_hit,
                                "search_degraded": section_search_degraded,
                            }
                        )
                    except Exception as e:
                        consecutive_failures += 1
                        provider_error_type = type(e).__name__
                        provider_error_message = str(e)
                        fallback_reason = "job_deadline_exceeded" if isinstance(e, TimeoutError) else "provider_error"
                        fallback_html = self._render_rule_based_fallback_section(
                            section=section,
                            brand=category_name,
                            category=category_value,
                            competitors=[],
                            error_code=f"{type(e).__name__}",
                            context_data=context_data,
                        )
                        if insufficient_evidence:
                            fallback_html = self._annotate_ai_generated_section(
                                fallback_html,
                                reason="实时检索信息不足，采用AI推断补全",
                            )

                        fallback_injected, fallback_inject_error, _ = self._inject_generated_section(
                            soup=soup,
                            section_id=section.section_id,
                            section_index=sec_index,
                            generated_html=fallback_html,
                            expected_title=section.title,
                        )
                        llm_sections.append(
                            {
                                "section_id": section.section_id,
                                "title": getattr(section, "title", section.section_id),
                                "ok": bool(fallback_injected),
                                "latency_ms": int((time.perf_counter() - sec_started) * 1000),
                                "error": (
                                    None
                                    if fallback_injected
                                    else f"{type(e).__name__}: {str(e)}; {fallback_inject_error or 'inject_failed'}"
                                ),
                                "attempts": 1,
                                "validation_error": "exception",
                                "similarity_ratio": None,
                                "used_fallback": True,
                                "fallback_reason": fallback_reason,
                                "ai_generated": bool(insufficient_evidence),
                                "inline_source_ok": None,
                                "inline_source_coverage": None,
                                "structure_retention_ratio": None,
                                "filled_block_count": None,
                                "empty_block_count": None,
                                "provider_error_type": provider_error_type,
                                "provider_error_message": provider_error_message,
                                "timeout_hit": timeout_hit,
                                "search_degraded": section_search_degraded,
                            }
                        )
                        consecutive_failures = 0 if fallback_injected else consecutive_failures
                        if strict_llm:
                            raise
                        if consecutive_failures >= 3:
                            break

                # 二次兜底：若有模块未生成或失败，清空模板示例内容
                self._finalize_sections_after_llm(
                    soup=soup,
                    sections=sections,
                    llm_sections=llm_sections,
                    brand=category_name,
                    category=category_value,
                    competitors=[],
                    context_data=context_data,
                )
                context_data["llm_sections"] = llm_sections
                result_html = str(soup)

        # Tavily 来源链接注入（仅在实际使用 web search 时）
        source_links: List[Dict[str, str]] = []
        llm_search_meta = (context_data.get("llm_search") or {}).get("_meta") if isinstance(context_data.get("llm_search"), dict) else None
        if isinstance(llm_search_meta, dict) and llm_search_meta.get("used_web_search"):
            source_links = llm_search_meta.get("source_links") or []
        if bool(getattr(settings, "inline_source_link_auto_inject", True)) and source_links:
            result_html = self._inject_inline_source_links(result_html, source_links)
        if source_links:
            result_html = self._inject_source_links(result_html, source_links)

        result_html = self._fix_dark_background_contrast(result_html)
        result_html = self._normalize_external_links(result_html)

        # 再做一遍 header 适配，防止 LLM 注入覆盖
        result_html = self._postprocess_tiktok_header_html(
            html_content=result_html,
            category_name=category_name,
            product_selling_points=product_selling_points,
        )

        output_path = self.output_dir / f"{report_id}.html"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result_html)

        return {
            "report_id": report_id,
            "template_name": template_name,
            "output_path": str(output_path),
            "generated_at": datetime.now().isoformat(),
            "html_content": result_html,
            "context_data": context_data,
            "use_llm": use_llm,
        }
    
    def _replace_brand_in_template(
        self,
        html_content: str,
        original_brand: str,
        new_brand: str,
        competitors: List[str]
    ) -> str:
        """
        替换模板中的品牌名称
        
        Args:
            html_content: HTML 内容
            original_brand: 原品牌名称
            new_brand: 新品牌名称
            competitors: 竞品列表
            
        Returns:
            替换后的 HTML 内容
        """
        result = html_content

        # 替换品牌名称（兼容不同参考模板的占位品牌）
        brand_placeholders = {original_brand, "AOS", "海飞丝"}
        for placeholder in brand_placeholders:
            if placeholder and placeholder != new_brand:
                result = result.replace(placeholder, new_brand)
        
        # 替换示例文本
        result = result.replace("（示例）", "")
        result = result.replace("（示例 / Fake Data）", "")
        if competitors:
            joined = " / ".join(competitors)
            result = result.replace("BrandX / BrandY / BrandZ", joined)
            result = result.replace("清扬 / KONO / Spes", joined)

        # 兼容模板中散落的占位竞品名称
        placeholder_competitors = ["BrandX", "BrandY", "BrandZ", "清扬", "KONO", "Spes"]
        for idx, placeholder in enumerate(placeholder_competitors):
            if idx < len(competitors) and competitors[idx]:
                result = result.replace(placeholder, competitors[idx])
        
        # 更新时间戳
        result = result.replace("2026-01-07", datetime.now().strftime("%Y-%m-%d"))
        result = re.sub(
            r"run_\d{8}_\d{6}",
            f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            result
        )
        
        return result
    
    def generate(
        self,
        brand: str,
        competitors: List[str],
        template_name: str = "海飞丝.html",
        use_llm: bool = True,
        strict_llm: bool = False,
        enable_web_search: bool = True,
        extra_context: Optional[Dict[str, Any]] = None,
        extra_replacements: Optional[Dict[str, str]] = None,
        web_search_query: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        生成报告
        
        Args:
            brand: 目标品牌
            competitors: 竞品列表
            template_name: 模板名称
            use_llm: 是否使用 LLM 生成内容（False 时仅做品牌替换）
            strict_llm: use_llm 为 True 时，LLM 调用失败是否直接报错
            enable_web_search: 是否尝试使用 Web Search 工具（若提供方支持）
            
        Returns:
            生成结果，包含报告 ID、路径、内容等
        """
        report_id = f"{brand}-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4]}"
        
        # 1. 解析模板
        parsed = self.template_parser.parse(template_name)
        
        # 2. 收集数据
        context_data = self._collect_data(brand, competitors)
        if extra_context:
            context_data.update(extra_context)
        
        # 3. 读取原始模板
        template_path = self.template_parser.template_dir / template_name
        with open(template_path, "r", encoding="utf-8") as f:
            original_html = f.read()
        
        # 先做基础替换（无论是否使用 LLM，保证基础信息正确）
        placeholder_brand = "海飞丝" if template_name == "海飞丝.html" else "AOS"
        result_html = self._replace_brand_in_template(
            original_html,
            placeholder_brand,
            brand,
            competitors,
        )
        if extra_replacements:
            result_html = self._apply_replacements(result_html, extra_replacements)

        if use_llm:
            llm_started = time.perf_counter()
            ping = self.llm_client.ping()
            context_data["llm_ping"] = ping
            if not ping.get("ok"):
                message = (
                    "LLM API 调用失败（未能完成最小 ping）。"
                    f" base_url={getattr(self.llm_client, 'base_url', '')!r}"
                    f" model={getattr(self.llm_client, 'model', '')!r}"
                    f" error={ping.get('error')}"
                )
                if strict_llm:
                    raise RuntimeError(message)
                context_data["llm_error"] = message

            # 使用 LLM 搜索获取实时信息
            if enable_web_search and ping.get("ok"):
                search_timeout_s = float(getattr(settings, "search_total_timeout_seconds", 90) or 90)
                try:
                    search_result = self._call_with_timeout(
                        lambda: self.llm_client.search_and_generate(
                            query=web_search_query or f"{brand} 品牌市场分析 消费者洞察 竞品分析",
                            brand=brand,
                            competitors=competitors,
                        ),
                        timeout_s=search_timeout_s,
                    )
                except Exception as exc:
                    search_result = {
                        "_meta": {
                            "ok": False,
                            "used_web_search": False,
                            "tool_type": "tavily",
                            "latency_ms": int(search_timeout_s * 1000),
                            "source_links": [],
                            "error": f"{type(exc).__name__}: {str(exc)}",
                            "search_degraded": True,
                            "search_error_type": type(exc).__name__,
                            "search_error_message": str(exc),
                        },
                        "parse_error": True,
                    }
                if isinstance(search_result, dict) and search_result.get("parse_error"):
                    search_meta = (search_result.get("_meta") or {}) if isinstance(search_result, dict) else {}
                    search_degraded = bool(search_meta.get("search_degraded", False))
                    if strict_llm and not search_degraded:
                        raise RuntimeError(
                            "LLM 搜索返回结果无法解析为 JSON。"
                            f" base_url={getattr(self.llm_client, 'base_url', '')!r}"
                            f" model={getattr(self.llm_client, 'model', '')!r}"
                        )
                context_data["llm_search"] = search_result

            # 生成并注入各模块内容（仅在 ping 通过时进行）
            if ping.get("ok"):
                llm_sections: List[Dict[str, Any]] = []
                soup = BeautifulSoup(result_html, "lxml")
                sections = parsed.get("sections", [])
                category_value = str(context_data.get("category") or "")
                source_links: List[Dict[str, str]] = []
                llm_search_meta = (context_data.get("llm_search") or {}).get("_meta") if isinstance(context_data.get("llm_search"), dict) else None
                if isinstance(llm_search_meta, dict) and llm_search_meta.get("used_web_search"):
                    source_links = llm_search_meta.get("source_links") or []
                
                # 🔑 关键步骤：在 LLM 生成前，先清空所有 section 的原始内容
                # 这确保了即使部分 section 生成失败，也不会显示不相关的模板原始内容
                self._prepare_template_for_llm(soup, sections, brand)
                
                soft_timeout_s = float(getattr(settings, "report_job_soft_timeout_seconds", 720) or 720)
                safety_margin_s = 20.0
                llm_deadline_s = max(soft_timeout_s - safety_margin_s, 60.0)

                consecutive_failures = 0
                for idx, section in enumerate(sections):
                    sec_started = time.perf_counter()
                    elapsed_total = time.perf_counter() - llm_started
                    remaining_total_s = llm_deadline_s - elapsed_total
                    remaining_sections = max(len(sections) - idx, 1)
                    # section-1..N 解析为顺序索引；hero 固定 -1
                    sec_index = -1
                    insufficient_evidence = False
                    section_search_degraded = bool(
                        ((context_data.get("llm_search") or {}).get("_meta") or {}).get("search_degraded", False)
                        if isinstance(context_data, dict)
                        else False
                    )
                    provider_error_type: Optional[str] = None
                    provider_error_message: Optional[str] = None
                    timeout_hit = False
                    fallback_reason: Optional[str] = None
                    try:
                        if isinstance(section.section_id, str) and section.section_id.startswith("section-"):
                            sec_index = int(section.section_id.split("-", 1)[1]) - 1

                        insufficient_evidence = not self._has_sufficient_section_evidence(
                            section.section_id,
                            context_data,
                        )

                        if remaining_total_s <= 6:
                            raise TimeoutError("job deadline reached before section generation")

                        section_budget_s = max(6.0, remaining_total_s / remaining_sections)
                        base_first_timeout = float(getattr(settings, "section_llm_timeout_seconds", 120) or 120)
                        base_retry_timeout = float(getattr(settings, "section_retry_timeout_seconds", 75) or 75)
                        first_timeout_s = min(base_first_timeout, max(8.0, section_budget_s * 0.7))
                        retry_timeout_s = min(base_retry_timeout, max(0.0, section_budget_s - first_timeout_s))
                        attempts_limit = 2 if retry_timeout_s >= 6.0 else 1

                        cleaned, validated_ok, validation_error, metrics, attempts, section_diag = self._attempt_section_generation(
                            section=section,
                            sec_index=sec_index,
                            brand=brand,
                            category=category_value,
                            competitors=competitors,
                            context_data=context_data,
                            source_links=source_links,
                            generate_once=lambda retry_reason, temperature, timeout_s, retry_attempts, compression_ratio: self._generate_section_content(
                                section=section,
                                brand=brand,
                                competitors=competitors,
                                context_data=context_data,
                                retry_reason=retry_reason,
                                temperature=temperature,
                                timeout_s=timeout_s,
                                retry_attempts=retry_attempts,
                                context_compression_ratio=compression_ratio,
                            ),
                            first_timeout_s=first_timeout_s,
                            retry_timeout_s=retry_timeout_s,
                            max_attempts=attempts_limit,
                        )
                        provider_error_type = section_diag.get("provider_error_type") if isinstance(section_diag, dict) else None
                        provider_error_message = section_diag.get("provider_error_message") if isinstance(section_diag, dict) else None
                        timeout_hit = bool(section_diag.get("timeout_hit")) if isinstance(section_diag, dict) else False
                        fallback_reason = section_diag.get("fallback_reason") if isinstance(section_diag, dict) else None
                        section_search_degraded = bool(section_diag.get("search_degraded")) if isinstance(section_diag, dict) else section_search_degraded
                        attempts_detail = section_diag.get("attempts_detail") if isinstance(section_diag, dict) else None

                        if insufficient_evidence:
                            cleaned = self._annotate_ai_generated_section(
                                cleaned,
                                reason="实时检索信息不足",
                            )

                        injected, inject_error, inject_metrics = self._inject_generated_section(
                            soup=soup,
                            section_id=section.section_id,
                            section_index=sec_index,
                            generated_html=cleaned,
                            expected_title=section.title,
                            preserve_structure=bool(validated_ok),
                        )
                        error_reason = None if injected else (validation_error or inject_error or "inject_failed")
                        if not injected:
                            if strict_llm:
                                raise RuntimeError(
                                    f"LLM 返回的 HTML 无法注入到模板中: section_id={section.section_id}"
                                )
                        consecutive_failures = 0 if injected else (consecutive_failures + 1)
                        micro_final_metrics: Dict[str, Any] = (
                            inject_metrics if isinstance(inject_metrics, dict) else {}
                        )
                        if injected and sec_index >= 0:
                            section_root = self._find_section_root_by_index(soup, sec_index)
                            if section_root is not None:
                                self._fill_key_micro_blanks_in_section(
                                    soup=soup,
                                    section_root=section_root,
                                    section_id=section.section_id,
                                    brand=brand,
                                    category=category_value,
                                    competitors=competitors,
                                    search_degraded=section_search_degraded,
                                )
                                micro_final_metrics = self._compute_micro_slot_metrics(section_root)
                        similarity_ratio = metrics.get("similarity_ratio") if isinstance(metrics, dict) else None
                        llm_sections.append(
                            {
                                "section_id": section.section_id,
                                "title": section.title,
                                "ok": bool(injected),
                                "latency_ms": int((time.perf_counter() - sec_started) * 1000),
                                "error": error_reason,
                                "attempts": attempts,
                                "validation_error": validation_error,
                                "similarity_ratio": similarity_ratio,
                                "used_fallback": bool(not validated_ok),
                                "fallback_reason": fallback_reason,
                                "ai_generated": bool(insufficient_evidence),
                                "attempts_detail": attempts_detail,
                                "inline_source_ok": metrics.get("inline_source_ok") if isinstance(metrics, dict) else None,
                                "inline_source_coverage": metrics.get("inline_source_coverage") if isinstance(metrics, dict) else None,
                                "structure_retention_ratio": metrics.get("structure_retention_ratio") if isinstance(metrics, dict) else None,
                                "filled_block_count": metrics.get("filled_block_count") if isinstance(metrics, dict) else None,
                                "empty_block_count": metrics.get("empty_block_count") if isinstance(metrics, dict) else None,
                                "micro_slots_total": micro_final_metrics.get("micro_slots_total"),
                                "micro_slots_filled": micro_final_metrics.get("micro_slots_filled"),
                                "micro_slots_empty": micro_final_metrics.get("micro_slots_empty"),
                                "provider_error_type": provider_error_type,
                                "provider_error_message": provider_error_message,
                                "timeout_hit": timeout_hit,
                                "search_degraded": section_search_degraded,
                            }
                        )
                    except Exception as e:
                        consecutive_failures += 1
                        provider_error_type = type(e).__name__
                        provider_error_message = str(e)
                        fallback_reason = "job_deadline_exceeded" if isinstance(e, TimeoutError) else "provider_error"
                        fallback_html = self._render_rule_based_fallback_section(
                            section=section,
                            brand=brand,
                            category=category_value,
                            competitors=competitors,
                            error_code=f"{type(e).__name__}",
                            context_data=context_data,
                        )
                        if insufficient_evidence:
                            fallback_html = self._annotate_ai_generated_section(
                                fallback_html,
                                reason="实时检索信息不足，采用AI推断补全",
                            )

                        fallback_injected, fallback_inject_error, _ = self._inject_generated_section(
                            soup=soup,
                            section_id=section.section_id,
                            section_index=sec_index,
                            generated_html=fallback_html,
                            expected_title=section.title,
                            preserve_structure=False,
                        )
                        micro_final_metrics: Dict[str, Any] = {}
                        if fallback_injected and sec_index >= 0:
                            section_root = self._find_section_root_by_index(soup, sec_index)
                            if section_root is not None:
                                self._fill_key_micro_blanks_in_section(
                                    soup=soup,
                                    section_root=section_root,
                                    section_id=section.section_id,
                                    brand=brand,
                                    category=category_value,
                                    competitors=competitors,
                                    search_degraded=section_search_degraded,
                                )
                                micro_final_metrics = self._compute_micro_slot_metrics(section_root)
                        llm_sections.append(
                            {
                                "section_id": section.section_id,
                                "title": getattr(section, "title", section.section_id),
                                "ok": bool(fallback_injected),
                                "latency_ms": int((time.perf_counter() - sec_started) * 1000),
                                "error": (
                                    None
                                    if fallback_injected
                                    else f"{type(e).__name__}: {str(e)}; {fallback_inject_error or 'inject_failed'}"
                                ),
                                "attempts": 1,
                                "validation_error": "exception",
                                "similarity_ratio": None,
                                "used_fallback": True,
                                "fallback_reason": fallback_reason,
                                "ai_generated": bool(insufficient_evidence),
                                "attempts_detail": None,
                                "inline_source_ok": None,
                                "inline_source_coverage": None,
                                "structure_retention_ratio": None,
                                "filled_block_count": None,
                                "empty_block_count": None,
                                "micro_slots_total": micro_final_metrics.get("micro_slots_total"),
                                "micro_slots_filled": micro_final_metrics.get("micro_slots_filled"),
                                "micro_slots_empty": micro_final_metrics.get("micro_slots_empty"),
                                "provider_error_type": provider_error_type,
                                "provider_error_message": provider_error_message,
                                "timeout_hit": timeout_hit,
                                "search_degraded": section_search_degraded,
                            }
                        )
                        consecutive_failures = 0 if fallback_injected else consecutive_failures
                        if strict_llm:
                            raise
                        if consecutive_failures >= 3:
                            break

                self._finalize_sections_after_llm(
                    soup=soup,
                    sections=sections,
                    llm_sections=llm_sections,
                    brand=brand,
                    category=category_value,
                    competitors=competitors,
                    context_data=context_data,
                )
                context_data["llm_sections"] = llm_sections
                result_html = str(soup)

        # 最终清理：LLM 可能会把占位符/示例文案带回输出里
        placeholder_brand = "海飞丝" if template_name == "海飞丝.html" else "AOS"
        result_html = self._replace_brand_in_template(
            result_html,
            placeholder_brand,
            brand,
            competitors,
        )
        if extra_replacements:
            result_html = self._apply_replacements(result_html, extra_replacements)

        # 非洗护品类的最终污染词清理（避免模板示例品牌残留）
        category_value = str(context_data.get("category") or "")
        if category_value and not any(marker in category_value.lower() for marker in self.WASHCARE_CATEGORY_MARKERS):
            result_html = self._apply_replacements(
                result_html,
                {
                    "清扬": "竞品A",
                    "KONO": "竞品B",
                    "Spes": "竞品C",
                    "去屑": "核心功效",
                    "头皮": "使用部位",
                    "洗发": "品类",
                },
            )

        # brand_health：不改模板文件，仅对输出做 meta 字段适配
        if context_data.get("report_type") == "brand_health" and context_data.get("category"):
            result_html = self._postprocess_brand_health_html(
                html_content=result_html,
                category=str(context_data.get("category") or ""),
            )
            result_html = self._postprocess_brand_health_header_title(
                html_content=result_html,
                brand=brand,
                category=str(context_data.get("category") or ""),
            )

        # 非洗护品类：移除模板数字占位符（count-up/data-target），避免残留 621/691 等伪数据。
        if category_value and not any(marker in category_value.lower() for marker in self.WASHCARE_CATEGORY_MARKERS):
            result_html = self._strip_numeric_placeholders_from_html(result_html)
            result_html = self._sanitize_video_mock_placeholders(result_html, category_value)

        # 战略模块：移除固定高度，避免长文被裁切。
        result_html = self._fix_strategy_resource_matrix_layout(result_html)

        # Tavily 来源链接注入（仅在实际使用 web search 时）
        source_links: List[Dict[str, str]] = []
        llm_search_meta = (context_data.get("llm_search") or {}).get("_meta") if isinstance(context_data.get("llm_search"), dict) else None
        if isinstance(llm_search_meta, dict) and llm_search_meta.get("used_web_search"):
            source_links = llm_search_meta.get("source_links") or []
        if bool(getattr(settings, "inline_source_link_auto_inject", True)) and source_links:
            result_html = self._inject_inline_source_links(result_html, source_links)
        if source_links:
            result_html = self._inject_source_links(result_html, source_links)

        result_html = self._fix_dark_background_contrast(result_html)
        result_html = self._normalize_external_links(result_html)
        
        # 4. 保存报告
        output_path = self.output_dir / f"{report_id}.html"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result_html)
        
        return {
            "report_id": report_id,
            "brand": brand,
            "competitors": competitors,
            "template_name": template_name,
            "output_path": str(output_path),
            "generated_at": datetime.now().isoformat(),
            "html_content": result_html,
            "context_data": context_data,
            "use_llm": use_llm
        }
    
    def get_report(self, report_id: str) -> Optional[Dict[str, Any]]:
        """
        获取已生成的报告
        
        Args:
            report_id: 报告 ID
            
        Returns:
            报告信息，如果不存在返回 None
        """
        # 查找匹配的报告文件
        for file in self.output_dir.glob(f"{report_id}*.html"):
            with open(file, "r", encoding="utf-8") as f:
                html_content = f.read()
            
            return {
                "report_id": report_id,
                "output_path": str(file),
                "html_content": html_content
            }
        
        return None
    
    def list_reports(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        列出已生成的报告
        
        Args:
            limit: 返回数量限制
            
        Returns:
            报告列表
        """
        reports = []
        for file in sorted(self.output_dir.glob("*.html"), reverse=True)[:limit]:
            reports.append({
                "report_id": file.stem,
                "output_path": str(file),
                "created_at": datetime.fromtimestamp(file.stat().st_mtime).isoformat()
            })
        
        return reports


# 单例模式
_generator_instance: Optional[ReportGenerator] = None


def get_report_generator() -> ReportGenerator:
    """获取报告生成器单例"""
    global _generator_instance
    if _generator_instance is None:
        _generator_instance = ReportGenerator()
    return _generator_instance
