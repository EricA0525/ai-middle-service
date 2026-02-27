from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

from market_insight_agent.pipeline import get_report_generator, get_template_parser


def _count_glass_cards(html_content: str) -> int:
    soup = BeautifulSoup(html_content, "lxml")
    return len(soup.find_all("div", class_=lambda x: isinstance(x, str) and "glass-card" in x))


def test_template_parser_prefers_full_section_container() -> None:
    parser = get_template_parser()
    parsed = parser.parse("海飞丝.html", force_reparse=True)

    sections = parsed.get("sections") or []
    section_titles = {section.title: section for section in sections}

    assert "竞品深度攻防" in section_titles
    target = section_titles["竞品深度攻防"]

    # 若只截取了某个 grid，这里会非常短且卡片数很少。
    assert len(target.html_content) > 10000
    assert _count_glass_cards(target.html_content) >= 8


def test_rule_based_fallback_keeps_section_card_skeleton() -> None:
    parser = get_template_parser()
    parsed = parser.parse("海飞丝.html", force_reparse=True)
    sections = parsed.get("sections") or []
    section_titles = {section.title: section for section in sections}

    target = section_titles["竞品深度攻防"]
    generator = get_report_generator()

    fallback_html = generator._render_rule_based_fallback_section(
        section=target,
        brand="索尼",
        category="耳机",
        competitors=["Bose", "森海塞尔"],
        error_code="skipped_budget_exceeded",
        context_data={
            "brand": "索尼",
            "category": "耳机",
            "competitors": ["Bose", "森海塞尔"],
            "sources": {},
            "llm_search": {
                "brand_overview": "索尼在高端降噪耳机市场仍具备品牌溢价和技术认知优势。"
            },
        },
    )

    # 兜底应至少保留原有 glass-card 数量，避免模块骨架缩水。
    assert _count_glass_cards(fallback_html) >= _count_glass_cards(target.html_content)

    fallback_soup = BeautifulSoup(fallback_html, "lxml")
    assert fallback_soup.find("h2", class_="section-title") is not None
    assert "此处内容由AI生成" in fallback_soup.get_text(" ", strip=True)


def test_finalize_with_skipped_sections_still_keeps_part4_structure() -> None:
    parser = get_template_parser()
    parsed = parser.parse("海飞丝.html", force_reparse=True)
    sections = parsed.get("sections") or []

    template_html = Path("templates/海飞丝.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(template_html, "lxml")

    generator = get_report_generator()
    generator._prepare_template_for_llm(soup, sections, "索尼")

    simulated_statuses = [
        {
            "section_id": section.section_id,
            "ok": False,
            "error": "skipped_budget_exceeded",
        }
        for section in sections
        if section.section_id != "hero"
    ]

    generator._finalize_sections_after_llm(
        soup=soup,
        sections=sections,
        llm_sections=simulated_statuses,
        brand="索尼",
        category="耳机",
        competitors=["Bose", "森海塞尔"],
        context_data={
            "brand": "索尼",
            "category": "耳机",
            "competitors": ["Bose", "森海塞尔"],
            "sources": {},
            "llm_search": {
                "brand_overview": "索尼在高端降噪耳机市场保持较高品牌认知与产品溢价。",
                "market_trends": "无线化、降噪、长续航与多设备协同是核心需求。",
            },
        },
    )

    part4 = soup.find("section", id="part4")
    assert part4 is not None
    assert _count_glass_cards(str(part4)) >= 8
    assert "此处内容由AI生成" in part4.get_text(" ", strip=True)
