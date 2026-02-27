from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from bs4 import BeautifulSoup

from market_insight_agent.pipeline import get_report_generator, get_template_parser
from market_insight_agent.utils.html_utils import clean_llm_html_response


def test_prepare_template_strips_count_up_placeholders() -> None:
    parser = get_template_parser()
    parsed = parser.parse("海飞丝.html", force_reparse=True)
    sections = parsed.get("sections") or []

    template_html = Path("templates/海飞丝.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(template_html, "lxml")

    generator = get_report_generator()
    generator._prepare_template_for_llm(soup, sections, "索尼")

    assert soup.find(attrs={"data-target": True}) is None
    assert not soup.select(".count-up")


def test_merge_micro_nodes_fills_tag_pills_and_chart_bars() -> None:
    generator = get_report_generator()

    target_html = """
    <section class="section">
      <h2 class="section-title">人群洞察与画像</h2>
      <div class="glass-card p-8">
        <div class="flex justify-between text-sm font-semibold mb-1">
          <span></span>
          <span class="text-gray-500"></span>
        </div>
        <div class="flex flex-wrap gap-2">
          <span class="tag-pill red"></span>
          <span class="tag-pill orange"></span>
        </div>
        <div class="space-y-1">
          <div class="chart-bar-fill bg-orange-500 text-white text-xs font-bold p-2 rounded w-full flex justify-between"><span></span></div>
          <div class="bg-orange-300 text-white text-xs font-bold p-2 rounded w-[70%]"></div>
        </div>
      </div>
    </section>
    """

    generated_html = """
    <section class="section">
      <h2 class="section-title">人群洞察与画像</h2>
      <div class="glass-card p-8">
        <div class="flex justify-between text-sm font-semibold mb-1">
          <span>内容与服务收入</span>
          <span class="text-gray-500">趋势：提升</span>
        </div>
        <div class="flex flex-wrap gap-2">
          <span class="tag-pill red">对比测评</span>
          <span class="tag-pill orange">通勤降噪</span>
        </div>
        <div class="space-y-1">
          <div class="chart-bar-fill bg-orange-500 text-white text-xs font-bold p-2 rounded w-full flex justify-between"><span>降噪效果</span></div>
          <div class="bg-orange-300 text-white text-xs font-bold p-2 rounded w-[70%]">佩戴舒适</div>
        </div>
      </div>
    </section>
    """

    target_section = BeautifulSoup(target_html, "lxml").find("section")
    generated_section = BeautifulSoup(generated_html, "lxml").find("section")
    assert target_section is not None
    assert generated_section is not None

    merged, metrics = generator._merge_generated_into_template_section(
        target_section=target_section,
        generated_section=generated_section,
        expected_title="人群洞察与画像",
    )
    assert merged is True

    assert target_section.select_one("span.tag-pill.red").get_text(" ", strip=True) == "对比测评"
    assert target_section.select_one("span.tag-pill.orange").get_text(" ", strip=True) == "通勤降噪"
    assert "降噪效果" in target_section.get_text(" ", strip=True)
    assert "佩戴舒适" in target_section.get_text(" ", strip=True)

    assert metrics.get("micro_slots_total", 0) >= 4
    assert metrics.get("micro_slots_empty", 0) == 0


def test_fill_key_micro_blanks_adds_qual_note_and_names() -> None:
    generator = get_report_generator()

    html = """
    <section id="part3" class="section relative">
      <h2 class="section-title">人群洞察与画像</h2>
      <div class="glass-card p-8">
        <div class="flex justify-between text-sm mb-2 font-bold text-gray-600">
          <span></span><span></span>
        </div>
        <div class="flex h-6 rounded-full overflow-hidden">
          <div class="bg-pink-400 w-[55%] flex items-center justify-center text-xs text-white font-bold"></div>
          <div class="bg-blue-400 w-[45%] flex items-center justify-center text-xs text-white font-bold"></div>
        </div>
        <div class="flex gap-2 text-sm mt-1">
          <span class="bg-pink-50 text-pink-600 px-2 py-0.5 rounded text-xs border border-pink-100"></span>
          <span class="bg-blue-50 text-blue-600 px-2 py-0.5 rounded text-xs border border-blue-100"></span>
        </div>
        <div class="space-y-1">
          <div class="bg-orange-500 text-white text-xs font-bold p-2 rounded w-full flex justify-between chart-bar-fill" data-width="100%"><span></span></div>
          <div class="bg-orange-400 text-white text-xs font-bold p-2 rounded w-[85%] flex justify-between chart-bar-fill" data-width="85%"><span></span></div>
          <div class="bg-orange-300 text-white text-xs font-bold p-2 rounded w-[70%]"></div>
          <div class="bg-orange-200 text-white text-xs font-bold p-2 rounded w-[55%]"></div>
        </div>
      </div>
    </section>
    """
    soup = BeautifulSoup(html, "lxml")
    section_root = soup.find("section")
    assert section_root is not None

    result = generator._fill_key_micro_blanks_in_section(
        soup=soup,
        section_root=section_root,
        section_id="section-3",
        brand="索尼",
        category="耳机",
        competitors=["Bose", "森海塞尔"],
        search_degraded=True,
    )

    assert result.get("micro_fallback_filled", 0) > 0
    assert soup.find("p", class_=lambda x: isinstance(x, str) and "qualitative-note" in x) is not None
    text = soup.get_text(" ", strip=True)
    assert "通勤降噪党" in text
    assert "影音内容党" in text
    assert "降噪效果" in text
    assert "佩戴舒适" in text


def test_fill_section4_stepper_nodes_are_filled() -> None:
    generator = get_report_generator()

    html = """
    <section id="part4" class="section relative">
      <h2 class="section-title">竞品深度攻防</h2>
      <div class="glass-card p-8">
        <h3 class="font-bold text-gray-800 mb-6 border-b border-gray-100 pb-2">索尼对森海塞尔攻防点</h3>
        <div class="mb-6">
          <span class="text-xs font-bold text-gray-400 uppercase"></span>
          <div class="flex flex-col gap-2 mt-2">
            <div class="flex items-center gap-3 text-sm text-gray-600">
              <span class="w-6 h-6 rounded-full bg-gray-200 flex items-center justify-center text-xs font-bold shrink-0"></span>
              <span></span>
            </div>
            <div class="h-4 border-l-2 border-dashed border-gray-300 ml-3"></div>
            <div class="flex items-center gap-3 text-sm text-gray-600">
              <span class="w-6 h-6 rounded-full bg-orange-100 text-orange-600 flex items-center justify-center text-xs font-bold shrink-0"></span>
              <span></span>
            </div>
            <div class="h-4 border-l-2 border-dashed border-gray-300 ml-3"></div>
            <div class="flex items-center gap-3 text-sm text-gray-600">
              <span class="w-6 h-6 rounded-full bg-red-100 text-red-600 flex items-center justify-center text-xs font-bold shrink-0"></span>
              <span><i class="inline w-3 h-3" data-lucide="arrow-right"></i></span>
            </div>
          </div>
        </div>
      </div>
    </section>
    """

    soup = BeautifulSoup(html, "lxml")
    section_root = soup.find("section")
    assert section_root is not None

    generator._fill_key_micro_blanks_in_section(
        soup=soup,
        section_root=section_root,
        section_id="section-4",
        brand="索尼",
        category="耳机",
        competitors=["Bose", "森海塞尔"],
        search_degraded=False,
    )

    numbers = [
        span.get_text(" ", strip=True)
        for span in section_root.select("span.w-6.h-6.rounded-full")
    ]
    assert numbers[:3] == ["1", "2", "3"]

    # Ensure the three step text nodes are filled and keep the arrow icon.
    steps = [
        row.find_all("span", recursive=False)[1]
        for row in section_root.select("div.flex.items-center.gap-3")
    ]
    assert len(steps) >= 3
    assert steps[0].get_text(" ", strip=True)
    assert steps[1].get_text(" ", strip=True)
    assert steps[2].find("i", attrs={"data-lucide": "arrow-right"}) is not None
    assert "音质优先" in steps[2].get_text(" ", strip=True)
    assert "转向" in steps[2].get_text(" ", strip=True)
    assert "决策路径演化" in section_root.get_text(" ", strip=True)

    assert section_root.find("p", class_=lambda x: isinstance(x, str) and "qualitative-note" in x) is not None


def test_merge_generated_section_does_not_fill_h3_from_fallback_pool() -> None:
    generator = get_report_generator()

    target_html = """
    <section class="section">
      <h2 class="section-title">竞品深度攻防</h2>
      <div class="glass-card">
        <h3 class="font-bold text-gray-800"></h3>
        <p class="text-sm"></p>
      </div>
    </section>
    """
    generated_html = """
    <section class="section">
      <h2 class="section-title">竞品深度攻防</h2>
      <div class="glass-card">
        <p>关键结论：攻防从参数竞争转向场景体验。</p>
        <li>建议：优先覆盖高意图检索词。</li>
      </div>
    </section>
    """

    target_section = BeautifulSoup(target_html, "lxml").find("section")
    generated_section = BeautifulSoup(generated_html, "lxml").find("section")
    assert target_section is not None
    assert generated_section is not None

    merged, _ = generator._merge_generated_into_template_section(
        target_section=target_section,
        generated_section=generated_section,
        expected_title="竞品深度攻防",
    )
    assert merged is True

    h3 = target_section.find("h3")
    assert h3 is not None
    assert h3.get_text(" ", strip=True) == ""


def test_build_fallback_lines_no_evidence_summary_phrase() -> None:
    generator = get_report_generator()
    section = SimpleNamespace(section_id="section-4", title="竞品深度攻防")

    lines = generator._build_fallback_lines(
        section=section,
        brand="索尼",
        category_text="耳机",
        competitors_text="Bose、森海塞尔",
        context_data={
            "llm_search": {
                "parsed_summary": "证据摘要：不应进入 fallback 行文",
            }
        },
    )
    assert lines
    assert all("证据摘要" not in line for line in lines)


def test_clean_llm_html_response_strips_think_and_prefix_text() -> None:
    raw = """
思考：先整理结构
<think>
内部推理内容
</think>
<section><h2 class="section-title">竞品深度攻防</h2></section>
"""
    cleaned = clean_llm_html_response(raw)
    assert cleaned.startswith("<section>")
    assert "<think" not in cleaned.lower()
    assert "思考：" not in cleaned


def test_sanitize_video_mock_removes_background_and_play_icon() -> None:
    generator = get_report_generator()

    html = """
    <section class="section">
      <div class="reveal">
        <div class="flex items-center gap-3 mb-6">
          <div class="bg-gray-900 text-white p-2 rounded-lg"><i data-lucide="video"></i></div>
          <h4 class="text-2xl font-bold text-gray-900">视频渠道攻防（转化端）</h4>
        </div>
        <div class="relative overflow-hidden rounded-2xl border border-gray-200 bg-white group">
          <div class="grid md:grid-cols-12 h-full">
            <div class="md:col-span-7 p-6"></div>
            <div class="md:col-span-5 bg-black relative min-h-[200px] flex items-center justify-center overflow-hidden group">
              <div class="absolute inset-0 opacity-50 bg-[url('https://images.unsplash.com/photo-test')] bg-cover bg-center"></div>
              <div class="w-12 h-12 rounded-full bg-white/20"><i data-lucide="play"></i></div>
              <div class="absolute bottom-2 left-2 text-white text-xs font-bold bg-black/50 px-2 py-1 rounded">Spes</div>
            </div>
          </div>
        </div>
      </div>
    </section>
    """

    sanitized = generator._sanitize_video_mock_placeholders(html, category="耳机")
    assert "images.unsplash.com" not in sanitized
    assert "data-lucide=\"play\"" not in sanitized
    assert "不展示模板视频素材" not in sanitized


def test_fix_strategy_resource_matrix_removes_h64() -> None:
    generator = get_report_generator()
    html = """
    <section class="section" id="part5">
      <h2 class="section-title">战略总结与资源</h2>
      <div class="grid grid-cols-2 gap-4 h-64">
        <div class="bg-gray-800"></div>
        <div class="bg-gray-800"></div>
      </div>
    </section>
    """
    fixed = generator._fix_strategy_resource_matrix_layout(html)
    soup = BeautifulSoup(fixed, "lxml")
    grid = soup.select_one("div.grid.grid-cols-2.gap-4")
    assert grid is not None
    classes = grid.get("class") or []
    assert "h-64" not in classes
    assert "h-auto" in classes
    assert "min-h-[16rem]" in classes
