"""
HTML 工具函数
"""

import re
from bs4 import BeautifulSoup


def sanitize_html(html_content: str) -> str:
    """
    清理 HTML 内容，移除潜在的危险标签
    
    Args:
        html_content: 原始 HTML 内容
        
    Returns:
        清理后的 HTML 内容
    """
    soup = BeautifulSoup(html_content, "lxml")
    
    # 移除 script 标签
    for script in soup.find_all("script"):
        script.decompose()
    
    # 移除 onclick 等事件属性
    for tag in soup.find_all(True):
        for attr in list(tag.attrs.keys()):
            if attr.startswith("on"):
                del tag[attr]
    
    return str(soup)


def extract_text_content(html_content: str) -> str:
    """
    从 HTML 中提取纯文本内容
    
    Args:
        html_content: HTML 内容
        
    Returns:
        纯文本内容
    """
    soup = BeautifulSoup(html_content, "lxml")
    return soup.get_text(separator=" ", strip=True)


def clean_llm_html_response(response: str) -> str:
    """
    清理 LLM 返回的 HTML 响应
    
    移除可能的 markdown 代码块标记等
    
    Args:
        response: LLM 响应
        
    Returns:
        清理后的 HTML
    """
    clean = response.strip()
    
    # 移除 markdown 代码块
    if clean.startswith("```html"):
        clean = clean[7:]
    elif clean.startswith("```"):
        clean = clean[3:]
    
    if clean.endswith("```"):
        clean = clean[:-3]

    # 清理模型可能泄漏的思维链标签
    clean = re.sub(
        r"<\s*think\b[^>]*>.*?<\s*/\s*think\s*>",
        "",
        clean,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # 若 HTML 前存在非结构化前缀文本（如“思考：/分析：”），仅保留首个标签后的内容
    first_tag_index = clean.find("<")
    if first_tag_index > 0:
        clean = clean[first_tag_index:]

    return clean.strip()


def validate_html_structure(html_content: str) -> dict:
    """
    验证 HTML 结构
    
    Args:
        html_content: HTML 内容
        
    Returns:
        验证结果
    """
    soup = BeautifulSoup(html_content, "lxml")
    
    return {
        "has_doctype": html_content.lower().startswith("<!doctype"),
        "has_html_tag": soup.html is not None,
        "has_head": soup.head is not None,
        "has_body": soup.body is not None,
        "has_title": soup.title is not None,
        "title": soup.title.string if soup.title else None
    }
