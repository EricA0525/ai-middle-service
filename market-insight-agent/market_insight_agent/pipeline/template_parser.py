"""
HTML 模板解析器

解析 HTML 模板的结构，并支持缓存机制（MD5 Hash 校验）。
当模板文件未变化时，直接从缓存读取解析结果。
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from bs4 import BeautifulSoup

from ..config import settings


class TemplateSection:
    """模板模块"""
    
    def __init__(
        self,
        section_id: str,
        title: str,
        css_classes: List[str],
        html_content: str,
        child_elements: List[str],
        section_type: str = "generic"
    ):
        self.section_id = section_id
        self.title = title
        self.css_classes = css_classes
        self.html_content = html_content
        self.child_elements = child_elements
        self.section_type = section_type
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.section_id,
            "title": self.title,
            "css_classes": self.css_classes,
            "html_content": self.html_content,
            "child_elements": self.child_elements,
            "section_type": self.section_type
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemplateSection":
        return cls(
            section_id=data["id"],
            title=data["title"],
            css_classes=data["css_classes"],
            html_content=data["html_content"],
            child_elements=data["child_elements"],
            section_type=data.get("section_type", "generic")
        )


class TemplateParser:
    """HTML 模板解析器"""

    PARSER_SCHEMA_VERSION = 2

    def __init__(self, template_dir: Optional[Path] = None):
        self.template_dir = template_dir or settings.template_path
        self.cache_dir = self.template_dir / ".parsed_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _compute_hash(self, content: str) -> str:
        """计算内容的 MD5 Hash"""
        return hashlib.md5(content.encode("utf-8")).hexdigest()
    
    def _get_cache_path(self, template_name: str) -> Path:
        """获取缓存文件路径"""
        cache_name = template_name.replace(".html", ".json")
        return self.cache_dir / cache_name
    
    def _load_cache(self, template_name: str) -> Optional[Dict[str, Any]]:
        """加载缓存"""
        cache_path = self._get_cache_path(template_name)
        if not cache_path.exists():
            return None
        
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    
    def _save_cache(
        self,
        template_name: str,
        template_hash: str,
        sections: List[TemplateSection],
        full_structure: Dict[str, Any]
    ) -> None:
        """保存缓存"""
        cache_data = {
            "template_name": template_name,
            "template_hash": template_hash,
            "parser_schema_version": self.PARSER_SCHEMA_VERSION,
            "parsed_at": datetime.now().isoformat(),
            "sections": [s.to_dict() for s in sections],
            "full_structure": full_structure
        }
        
        cache_path = self._get_cache_path(template_name)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    
    def _parse_html(self, html_content: str) -> tuple[List[TemplateSection], Dict[str, Any]]:
        """解析 HTML 内容"""
        soup = BeautifulSoup(html_content, "lxml")
        sections = []
        
        # 提取 CSS 样式
        style_tag = soup.find("style")
        css_content = style_tag.string if style_tag else ""
        
        # 解析主要内容区域
        wrap_div = soup.find("div", class_="wrap")
        if not wrap_div:
            wrap_div = soup.find("body")
        
        # 解析 Hero 区域（兼容两种模板：.hero 或 header.header）
        hero = soup.find("div", class_="hero")
        hero_type = "div.hero"
        if not hero:
            hero = soup.find("header", class_="header")
            hero_type = "header.header"
        if hero:
            sections.append(TemplateSection(
                section_id="hero",
                title="报告头部",
                css_classes=["hero"] if hero_type == "div.hero" else ["header"],
                html_content=str(hero),
                child_elements=["h1", "meta", "chip", "card"] if hero_type == "div.hero" else ["h1", "p"],
                section_type="hero"
            ))
        
        # 解析各个 section-title 对应的模块
        section_titles = soup.find_all("h2", class_="section-title")
        seen_section_containers: set[int] = set()
        for idx, title_elem in enumerate(section_titles):
            section_id = f"section-{idx + 1}"
            title_text = title_elem.get_text(strip=True)

            # 优先提取完整 <section> 容器（海飞丝模板），避免只截取某一个 grid 造成模块缺失。
            section_container = title_elem.find_parent("section")
            if section_container:
                container_identity = id(section_container)
                if container_identity in seen_section_containers:
                    continue
                seen_section_containers.add(container_identity)

                sections.append(TemplateSection(
                    section_id=section_id,
                    title=title_text,
                    css_classes=section_container.get("class", []),
                    html_content=str(section_container),
                    child_elements=[],
                    section_type="content-section"
                ))
                continue

            # 兼容旧 AOS 模板：按标题后的首个同级 grid 抽取。
            next_grid = title_elem.find_next_sibling("div", class_="grid")
            if next_grid:
                cards = next_grid.find_all("div", class_="card")
                child_elements = []
                for card in cards:
                    card_title = card.find("h2")
                    if card_title:
                        child_elements.append(card_title.get_text(strip=True)[:30])

                sections.append(TemplateSection(
                    section_id=section_id,
                    title=title_text,
                    css_classes=["section-title", "grid"],
                    html_content=str(title_elem) + str(next_grid),
                    child_elements=child_elements,
                    section_type="content-section"
                ))
        
        # 构建完整结构
        full_structure = {
            "doctype": "html",
            "lang": soup.html.get("lang", "zh-CN") if soup.html else "zh-CN",
            "head": {
                "title": soup.title.string if soup.title else "",
                "has_style": bool(style_tag),
                "css_variables": self._extract_css_variables(css_content)
            },
            "body": {
                "sections_count": len(sections),
                "has_wrap": bool(soup.find("div", class_="wrap")),
                "has_hero": bool(hero)
            },
            "css_content": css_content
        }
        
        return sections, full_structure
    
    def _extract_css_variables(self, css_content: str) -> Dict[str, str]:
        """提取 CSS 变量"""
        variables = {}
        if not css_content:
            return variables
        
        # 简单解析 :root 中的 CSS 变量
        import re
        root_match = re.search(r":root\s*\{([^}]+)\}", css_content)
        if root_match:
            root_content = root_match.group(1)
            var_matches = re.findall(r"--([a-zA-Z0-9-]+)\s*:\s*([^;]+);", root_content)
            for name, value in var_matches:
                variables[name] = value.strip()
        
        return variables
    
    def parse(
        self,
        template_name: str = "海飞丝.html",
        force_reparse: bool = False
    ) -> Dict[str, Any]:
        """
        解析模板
        
        Args:
            template_name: 模板文件名
            force_reparse: 是否强制重新解析（忽略缓存）
            
        Returns:
            解析结果，包含 sections 和 full_structure
        """
        template_path = self.template_dir / template_name
        
        if not template_path.exists():
            raise FileNotFoundError(f"模板文件不存在: {template_path}")
        
        # 读取模板内容
        with open(template_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        
        current_hash = self._compute_hash(html_content)
        
        # 检查缓存
        if not force_reparse:
            cache = self._load_cache(template_name)
            if (
                cache
                and cache.get("template_hash") == current_hash
                and int(cache.get("parser_schema_version") or 0) == self.PARSER_SCHEMA_VERSION
            ):
                # 缓存有效，直接返回
                return {
                    "template_name": template_name,
                    "template_hash": current_hash,
                    "parsed_at": cache["parsed_at"],
                    "from_cache": True,
                    "sections": [
                        TemplateSection.from_dict(s) for s in cache["sections"]
                    ],
                    "full_structure": cache["full_structure"]
                }
        
        # 解析模板
        sections, full_structure = self._parse_html(html_content)
        
        # 保存缓存
        self._save_cache(template_name, current_hash, sections, full_structure)
        
        return {
            "template_name": template_name,
            "template_hash": current_hash,
            "parsed_at": datetime.now().isoformat(),
            "from_cache": False,
            "sections": sections,
            "full_structure": full_structure
        }
    
    def get_status(self, template_name: str = "海飞丝.html") -> Dict[str, Any]:
        """
        获取模板状态
        
        Args:
            template_name: 模板文件名
            
        Returns:
            模板状态信息
        """
        template_path = self.template_dir / template_name
        
        if not template_path.exists():
            return {
                "exists": False,
                "template_name": template_name,
                "template_path": str(template_path)
            }
        
        # 读取当前模板 hash
        with open(template_path, "r", encoding="utf-8") as f:
            current_hash = self._compute_hash(f.read())
        
        # 检查缓存状态
        cache = self._load_cache(template_name)
        cache_valid = bool(
            cache
            and cache.get("template_hash") == current_hash
            and int(cache.get("parser_schema_version") or 0) == self.PARSER_SCHEMA_VERSION
        )
        
        return {
            "exists": True,
            "template_name": template_name,
            "template_path": str(template_path),
            "current_hash": current_hash,
            "cache_valid": cache_valid,
            "parsed_at": cache.get("parsed_at") if cache else None,
            "sections_count": len(cache.get("sections", [])) if cache else 0
        }
    
    def update_template(self, template_name: str, html_content: str) -> Dict[str, Any]:
        """
        更新模板内容
        
        Args:
            template_name: 模板文件名
            html_content: 新的 HTML 内容
            
        Returns:
            更新后的解析结果
        """
        template_path = self.template_dir / template_name
        
        # 保存新模板
        with open(template_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        # 强制重新解析
        return self.parse(template_name, force_reparse=True)


# 单例模式
_parser_instance: Optional[TemplateParser] = None


def get_template_parser() -> TemplateParser:
    """获取模板解析器单例"""
    global _parser_instance
    if _parser_instance is None:
        _parser_instance = TemplateParser()
    return _parser_instance
