from __future__ import annotations

from bs4 import BeautifulSoup

from market_insight_agent.pipeline import get_report_generator, get_template_parser


def test_section4_structure_threshold_relaxed() -> None:
    parser = get_template_parser()
    parsed = parser.parse("海飞丝.html", force_reparse=True)
    sections = parsed.get("sections") or []
    section4 = next(section for section in sections if section.section_id == "section-4")

    generator = get_report_generator()

    generated_html = """
    <section class="section relative" id="part4">
      <h2 class="section-title">竞品深度攻防</h2>
      <div class="grid grid-cols-2 gap-4">
        <div class="glass-card p-6">
          <h3 class="text-lg font-bold">结论A</h3>
          <div class="grid grid-cols-2 gap-2">
            <p class="text-sm">结论：聚焦场景体验。</p>
            <p class="text-sm">建议：突出差异化卖点。</p>
          </div>
          <ul>
            <li><span>要点1</span></li>
            <li><span>要点2</span></li>
            <li><span>要点3</span></li>
            <li><span>要点4</span></li>
            <li><span>要点5</span></li>
            <li><span>要点6</span></li>
          </ul>
        </div>
        <div class="glass-card p-6">
          <h3 class="text-lg font-bold">结论B</h3>
          <div class="grid grid-cols-2 gap-2">
            <p class="text-sm">结论：关注通勤降噪。</p>
            <p class="text-sm">建议：用对比评测降低决策成本。</p>
          </div>
          <ul>
            <li><span>要点1</span></li>
            <li><span>要点2</span></li>
            <li><span>要点3</span></li>
            <li><span>要点4</span></li>
            <li><span>要点5</span></li>
            <li><span>要点6</span></li>
          </ul>
        </div>
        <div class="glass-card p-6">
          <h3 class="text-lg font-bold">结论C</h3>
          <div class="grid grid-cols-2 gap-2">
            <p class="text-sm">结论：重视舒适佩戴。</p>
            <p class="text-sm">建议：分层表达核心客群。</p>
          </div>
          <ul>
            <li><span>要点1</span></li>
            <li><span>要点2</span></li>
            <li><span>要点3</span></li>
            <li><span>要点4</span></li>
            <li><span>要点5</span></li>
            <li><span>要点6</span></li>
          </ul>
        </div>
        <div class="glass-card p-6">
          <h3 class="text-lg font-bold">结论D</h3>
          <div class="grid grid-cols-2 gap-2">
            <p class="text-sm">结论：抢占高意图入口。</p>
            <p class="text-sm">建议：优化搜索词与内容标签。</p>
          </div>
          <ul>
            <li><span>要点1</span></li>
            <li><span>要点2</span></li>
            <li><span>要点3</span></li>
            <li><span>要点4</span></li>
            <li><span>要点5</span></li>
            <li><span>要点6</span></li>
          </ul>
        </div>
        <div class="glass-card p-6">
          <h3 class="text-lg font-bold">结论E</h3>
          <div class="grid grid-cols-2 gap-2">
            <p class="text-sm">结论：强调生态联动。</p>
            <p class="text-sm">建议：把体验证据前置。</p>
          </div>
          <ul>
            <li><span>要点1</span></li>
            <li><span>要点2</span></li>
            <li><span>要点3</span></li>
            <li><span>要点4</span></li>
            <li><span>要点5</span></li>
            <li><span>要点6</span></li>
          </ul>
        </div>
        <div class="glass-card p-6">
          <h3 class="text-lg font-bold">结论F</h3>
          <div class="grid grid-cols-2 gap-2">
            <p class="text-sm">结论：内容更需要可验证。</p>
            <p class="text-sm">建议：减少泛化夸赞。</p>
          </div>
          <ul>
            <li><span>要点1</span></li>
            <li><span>要点2</span></li>
            <li><span>要点3</span></li>
            <li><span>要点4</span></li>
            <li><span>要点5</span></li>
            <li><span>要点6</span></li>
          </ul>
        </div>
        <div class="glass-card p-6">
          <h3 class="text-lg font-bold">结论G</h3>
          <div class="grid grid-cols-2 gap-2">
            <p class="text-sm">结论：用户更看重稳定性。</p>
            <p class="text-sm">建议：以场景案例支撑。</p>
          </div>
          <ul>
            <li><span>要点1</span></li>
            <li><span>要点2</span></li>
            <li><span>要点3</span></li>
            <li><span>要点4</span></li>
            <li><span>要点5</span></li>
            <li><span>要点6</span></li>
          </ul>
        </div>
        <div class="glass-card p-6">
          <h3 class="text-lg font-bold">结论H</h3>
          <div class="grid grid-cols-2 gap-2">
            <p class="text-sm">结论：竞争正在加速。</p>
            <p class="text-sm">建议：建立周度迭代机制。</p>
          </div>
          <ul>
            <li><span>要点1</span></li>
            <li><span>要点2</span></li>
            <li><span>要点3</span></li>
            <li><span>要点4</span></li>
            <li><span>要点5</span></li>
            <li><span>要点6</span></li>
          </ul>
        </div>
      </div>
    </section>
    """

    structure_ratio, _ = generator._compute_structure_completeness(generated_html, section4.html_content)
    assert structure_ratio < 0.90
    assert structure_ratio >= 0.70

    ok, error_code, _ = generator._validate_generated_section(
        generated_html=generated_html,
        section=section4,
        expected_title=section4.title,
        brand="索尼",
        competitors=["Bose", "森海塞尔"],
        category="耳机",
        source_links=[],
    )
    assert ok is True
    assert error_code is None


def test_video_mock_placeholder_text_is_removed() -> None:
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
              <div class="text-white/70 text-xs font-semibold px-3 py-2 rounded bg-black/40">示意位：不展示模板视频素材（避免误导）</div>
              <div class="absolute inset-0 opacity-50 bg-[url('https://images.unsplash.com/photo-test')] bg-cover bg-center"></div>
              <div class="w-12 h-12 rounded-full bg-white/20"><i data-lucide="play"></i></div>
              <div class="absolute bottom-2 left-2 text-white text-xs font-bold bg-black/50 px-2 py-1 rounded">Spes</div>
              <img src="https://images.unsplash.com/photo-test-2"/>
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


def test_blank_text_nodes_keeps_numbered_headings() -> None:
    generator = get_report_generator()

    html = """
    <section class="section relative">
      <h2 class="section-title">竞品深度攻防</h2>
      <div>
        <h3>4.1 竞品矩阵定义</h3>
        <h3>无编号标题</h3>
        <p>示例文案</p>
      </div>
    </section>
    """

    soup = BeautifulSoup(html, "lxml")
    section = soup.find("section")
    assert section is not None

    generator._blank_text_nodes(section, keep_section_title=True)

    h3s = section.find_all("h3")
    assert h3s[0].get_text(" ", strip=True) == "4.1 竞品矩阵定义"
    assert h3s[1].get_text(" ", strip=True) == ""
    assert section.find("p") is not None
    assert section.find("p").get_text(" ", strip=True) == ""
