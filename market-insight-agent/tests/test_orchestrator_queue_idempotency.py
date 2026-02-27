from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from types import MethodType

import pytest

from market_insight_agent.config import settings
from market_insight_agent.errors import AppError, ErrorCode
from market_insight_agent.pipeline.models import ReportJobSpec
from market_insight_agent.pipeline.orchestrator import ReportJobOrchestrator
from market_insight_agent.storage.job_store import JobStore


class _DummyReportGenerator:
    WASHCARE_CATEGORY_MARKERS: tuple[str, ...] = ()


class _DummyTemplateParser:
    pass


def _make_spec(seed: int = 1) -> ReportJobSpec:
    return ReportJobSpec(
        report_type="brand_health",
        brand_name=f"测试品牌-{seed}",
        category="耳机",
        competitors=["A", "B"],
        template_name="海飞丝.html",
        use_llm=False,
        strict_llm=False,
        enable_web_search=False,
    )


def _make_orchestrator(tmp_path: Path) -> ReportJobOrchestrator:
    store = JobStore(tmp_path / "jobs.db")
    return ReportJobOrchestrator(
        report_generator=_DummyReportGenerator(),  # type: ignore[arg-type]
        template_parser=_DummyTemplateParser(),  # type: ignore[arg-type]
        job_store=store,
    )


def test_queue_full_returns_backpressure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "max_concurrent_jobs", 1)
    monkeypatch.setattr(settings, "max_queued_jobs", 1)

    orchestrator = _make_orchestrator(tmp_path)
    orchestrator.submit_brand_health_job(_make_spec(1))

    with pytest.raises(AppError) as exc_info:
        orchestrator.submit_brand_health_job(_make_spec(2))

    assert exc_info.value.code == ErrorCode.JOB_QUEUE_FULL
    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after_seconds == 30


def test_idempotency_same_payload_returns_same_job(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "max_concurrent_jobs", 1)
    monkeypatch.setattr(settings, "max_queued_jobs", 10)
    monkeypatch.setattr(settings, "idempotency_ttl_seconds", 300)

    orchestrator = _make_orchestrator(tmp_path)
    first = orchestrator.submit_brand_health_job(_make_spec(1), idempotency_key="idem-key-1")
    second = orchestrator.submit_brand_health_job(_make_spec(1), idempotency_key="idem-key-1")

    assert first["job_id"] == second["job_id"]
    assert second.get("idempotent_hit") is True


def test_idempotency_conflict_returns_409(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "max_concurrent_jobs", 1)
    monkeypatch.setattr(settings, "max_queued_jobs", 10)
    monkeypatch.setattr(settings, "idempotency_ttl_seconds", 300)

    orchestrator = _make_orchestrator(tmp_path)
    orchestrator.submit_brand_health_job(_make_spec(1), idempotency_key="idem-conflict")

    conflict_spec = _make_spec(2)
    conflict_spec.category = "手机"

    with pytest.raises(AppError) as exc_info:
        orchestrator.submit_brand_health_job(conflict_spec, idempotency_key="idem-conflict")

    assert exc_info.value.code == ErrorCode.JOB_IDEMPOTENCY_CONFLICT
    assert exc_info.value.status_code == 409


def test_worker_pool_respects_max_concurrency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "max_concurrent_jobs", 2)
    monkeypatch.setattr(settings, "max_queued_jobs", 20)
    monkeypatch.setattr(settings, "shutdown_grace_period_seconds", 2)

    orchestrator = _make_orchestrator(tmp_path)
    state = {"running": 0, "peak": 0}
    state_lock = asyncio.Lock()

    async def fake_run_job(self: ReportJobOrchestrator, job_id: str, spec: ReportJobSpec) -> None:
        async with state_lock:
            state["running"] += 1
            state["peak"] = max(state["peak"], state["running"])
        self.job_store.mark_running(job_id)
        await asyncio.sleep(0.08)
        self.job_store.mark_succeeded(
            job_id,
            {
                "job_id": job_id,
                "report_id": f"report-{job_id}",
                "output_path": str(tmp_path / f"{job_id}.html"),
                "generated_at": datetime.now().isoformat(),
            },
        )
        async with state_lock:
            state["running"] -= 1

    orchestrator._run_job = MethodType(fake_run_job, orchestrator)

    async def scenario() -> None:
        await orchestrator.start()
        for index in range(6):
            orchestrator.submit_brand_health_job(_make_spec(index))
        await asyncio.wait_for(orchestrator._queue.join(), timeout=5.0)
        await orchestrator.shutdown()

    asyncio.run(scenario())
    assert state["peak"] <= 2


def test_shutdown_rejects_new_submissions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "max_concurrent_jobs", 1)
    monkeypatch.setattr(settings, "max_queued_jobs", 5)
    monkeypatch.setattr(settings, "shutdown_grace_period_seconds", 1)

    orchestrator = _make_orchestrator(tmp_path)

    async def scenario() -> None:
        await orchestrator.start()
        await orchestrator.shutdown()

    asyncio.run(scenario())

    with pytest.raises(AppError) as exc_info:
        orchestrator.submit_brand_health_job(_make_spec(1))
    assert exc_info.value.code == ErrorCode.SYSTEM_SHUTTING_DOWN


def test_cancel_running_job_updates_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "max_concurrent_jobs", 1)
    monkeypatch.setattr(settings, "max_queued_jobs", 10)
    monkeypatch.setattr(settings, "shutdown_grace_period_seconds", 1)

    orchestrator = _make_orchestrator(tmp_path)

    async def fake_run_job(self: ReportJobOrchestrator, job_id: str, spec: ReportJobSpec) -> None:
        self.job_store.mark_running(job_id)
        try:
            await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            raise

    orchestrator._run_job = MethodType(fake_run_job, orchestrator)

    async def scenario() -> str:
        await orchestrator.start()
        created = orchestrator.submit_brand_health_job(_make_spec(1))
        job_id = str(created["job_id"])
        await asyncio.sleep(0.2)
        assert orchestrator.cancel_job(job_id) is True
        await asyncio.sleep(0.2)
        await orchestrator.shutdown()
        return job_id

    cancelled_job_id = asyncio.run(scenario())
    job = orchestrator.get_job_status(cancelled_job_id)
    assert isinstance(job, dict)
    assert job["status"] == "cancelled"
