from __future__ import annotations

"""Pipeline 领域模型。"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ReportJobSpec:
    """报告任务输入规格。"""

    report_type: str
    brand_name: str
    category: str
    competitors: list[str] = field(default_factory=list)
    template_name: str = "海飞丝.html"
    use_llm: bool = True
    strict_llm: bool = False
    enable_web_search: bool = True


@dataclass
class SectionPlan:
    """章节计划。"""

    section_id: str
    section_title: str
    objective: str
    required_information_blocks: list[str] = field(default_factory=list)
    min_density: int = 3
    forbidden_terms: list[str] = field(default_factory=list)


@dataclass
class EvidencePack:
    """章节证据包（压缩后）。"""

    section_id: str
    compressed_context: dict[str, Any]
    source_urls: list[str] = field(default_factory=list)
    source_names: list[str] = field(default_factory=list)
    mock_sources_skipped: list[str] = field(default_factory=list)
    budget_chars: int = 8000


@dataclass
class SectionDraft:
    """章节结构化草稿（JSON 语义层）。"""

    section_id: str
    section_title: str
    summary: str
    key_points: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    citations: list[dict[str, str]] = field(default_factory=list)
    attempt: int = 1
    retry_reason: str | None = None
    model_name: str | None = None


@dataclass
class SectionVerification:
    """章节校验结果。"""

    section_id: str
    passed: bool
    error_code: str | None = None
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class RenderArtifact:
    """最终渲染产物。"""

    job_id: str
    report_id: str
    output_path: str
    html_content: str
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    llm_diagnostics: dict[str, Any] = field(default_factory=dict)
    quality_gate: dict[str, Any] = field(default_factory=dict)
