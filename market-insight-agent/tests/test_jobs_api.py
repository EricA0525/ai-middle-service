from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from market_insight_agent.main import app


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


def test_v2_brand_job_lifecycle_succeeds() -> None:
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
        created = create.json()
        assert created.get("status") == "queued"
        assert created.get("job_id")

        job_id = str(created["job_id"])
        final_status = _wait_for_terminal_status(client, job_id)
        assert final_status.get("status") == "succeeded"

        result = client.get(f"/api/v2/report-jobs/{job_id}/result")
        assert result.status_code == 200
        payload = result.json()
        assert payload.get("report_id")
        output_path = Path(str(payload.get("output_path") or ""))
        assert output_path.exists()


def test_v1_brand_health_compat_works() -> None:
    with TestClient(app) as client:

        response = client.post(
            "/api/generate/brand_health",
            json={
                "brand_name": "索尼",
                "category": "耳机",
                "recommended_competitors": ["Bose"],
                "template_name": "海飞丝.html",
                "use_llm": False,
                "strict_llm": False,
                "enable_web_search": False,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload.get("report_type") == "brand_health"
        assert payload.get("report_id")
        assert payload.get("output_path")


def test_v2_cancel_endpoint_available() -> None:
    with TestClient(app) as client:

        create = client.post(
            "/api/v2/report-jobs",
            json={
                "report_type": "brand_health",
                "brand_name": "索尼",
                "category": "耳机",
                "recommended_competitors": ["Bose"],
                "template_name": "海飞丝.html",
                "use_llm": False,
                "strict_llm": False,
                "enable_web_search": False,
            },
        )

        assert create.status_code == 200
        job_id = str(create.json()["job_id"])

        cancel = client.post(f"/api/v2/report-jobs/{job_id}/cancel")
        assert cancel.status_code == 200
        body = cancel.json()
        assert body.get("job_id") == job_id
        assert isinstance(body.get("cancelled"), bool)


def test_v2_idempotency_hit_returns_same_job_id() -> None:
    with TestClient(app) as client:
        payload = {
            "report_type": "brand_health",
            "brand_name": "索尼",
            "category": "耳机",
            "recommended_competitors": ["Bose"],
            "template_name": "海飞丝.html",
            "use_llm": False,
            "strict_llm": False,
            "enable_web_search": False,
        }
        headers = {"Idempotency-Key": "jobs-api-idem-hit"}

        first = client.post("/api/v2/report-jobs", json=payload, headers=headers)
        second = client.post("/api/v2/report-jobs", json=payload, headers=headers)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json().get("job_id") == second.json().get("job_id")


def test_v2_idempotency_conflict_returns_409() -> None:
    with TestClient(app) as client:
        headers = {"Idempotency-Key": "jobs-api-idem-conflict"}
        first_payload = {
            "report_type": "brand_health",
            "brand_name": "索尼",
            "category": "耳机",
            "recommended_competitors": ["Bose"],
            "template_name": "海飞丝.html",
            "use_llm": False,
            "strict_llm": False,
            "enable_web_search": False,
        }
        second_payload = {
            "report_type": "brand_health",
            "brand_name": "索尼",
            "category": "手机",
            "recommended_competitors": ["Bose"],
            "template_name": "海飞丝.html",
            "use_llm": False,
            "strict_llm": False,
            "enable_web_search": False,
        }

        first = client.post("/api/v2/report-jobs", json=first_payload, headers=headers)
        conflict = client.post("/api/v2/report-jobs", json=second_payload, headers=headers)

        assert first.status_code == 200
        assert conflict.status_code == 409
        body = conflict.json()
        assert body.get("error", {}).get("code") == "JOB_IDEMPOTENCY_CONFLICT"
