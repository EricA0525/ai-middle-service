from __future__ import annotations

import time

from fastapi.testclient import TestClient

from market_insight_agent.main import app
from market_insight_agent.pipeline import get_orchestrator, get_report_generator
from market_insight_agent.pipeline.orchestrator import ReportJobOrchestrator


def _wait_for_terminal_status(client: TestClient, job_id: str, timeout_s: float = 30.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        response = client.get(f"/api/v2/report-jobs/{job_id}")
        response.raise_for_status()
        payload = response.json()
        status = payload.get("status")
        if status in {"succeeded", "failed", "failed_quality_gate", "cancelled"}:
            return payload
        time.sleep(0.2)
    raise AssertionError(f"job timeout: {job_id}")


def test_quality_gate_failure_still_publishes_when_allowed(monkeypatch) -> None:
    orchestrator = get_orchestrator()
    orchestrator.allow_publish_on_quality_gate_failure = True

    def _forced_failed_gate(self, **_: object) -> dict:
        return {
            "passed": False,
            "failures": [
                {
                    "code": "forced_test_failure",
                    "detail": "force quality gate fail for regression test",
                }
            ],
        }

    monkeypatch.setattr(ReportJobOrchestrator, "_run_final_quality_gate", _forced_failed_gate)

    with TestClient(app) as client:
        create = client.post(
            "/api/v2/report-jobs",
            json={
                "report_type": "brand_health",
                "brand_name": "索尼",
                "category": "耳机",
                "recommended_competitors": ["Bose", "森海塞尔"],
                "template_name": "海飞丝.html",
                "use_llm": False,
                "strict_llm": False,
                "enable_web_search": False,
            },
        )

        assert create.status_code == 200
        job_id = str(create.json()["job_id"])

        final_status = _wait_for_terminal_status(client, job_id)
        assert final_status.get("status") == "succeeded"

        result = client.get(f"/api/v2/report-jobs/{job_id}/result")
        assert result.status_code == 200
        payload = result.json()

        llm_diagnostics = payload.get("llm_diagnostics") or {}
        assert llm_diagnostics.get("published_with_quality_warnings") is True
        assert isinstance(llm_diagnostics.get("quality_warning"), list)
        assert llm_diagnostics.get("quality_warning")


def test_ai_generated_note_annotation_and_evidence_detection() -> None:
    generator = get_report_generator()

    insufficient_ctx = {
        "brand": "索尼",
        "competitors": ["Bose"],
        "sources": {},
    }
    assert generator._has_sufficient_section_evidence("section-2", insufficient_ctx) is False

    sufficient_ctx = {
        "brand": "索尼",
        "competitors": ["Bose"],
        "sources": {},
        "llm_search": {
            "_meta": {
                "source_links": [
                    {"url": "https://example.com/a"},
                    {"url": "https://example.com/b"},
                ]
            }
        },
    }
    assert generator._has_sufficient_section_evidence("section-2", sufficient_ctx) is True

    base_html = "<section><h2 class='section-title'>人群洞察与画像</h2><p>内容</p></section>"
    annotated = generator._annotate_ai_generated_section(base_html)
    assert "ai-generated-note" in annotated
    assert "此处内容由AI生成" in annotated

    # 确保重复标注时不会叠加多条
    annotated_twice = generator._annotate_ai_generated_section(annotated)
    assert annotated_twice.count("ai-generated-note") == 1
