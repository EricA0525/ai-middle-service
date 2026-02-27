from __future__ import annotations

"""v2 报告作业编排器（单进程多阶段）。"""

import asyncio
import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Any, Optional

from bs4 import BeautifulSoup

from ..config import settings
from ..errors import AppError, ErrorCode
from ..logging_config import bind_job_id, get_logger
from ..storage import JobStore, get_job_store
from .models import EvidencePack, RenderArtifact, ReportJobSpec, SectionDraft, SectionPlan
from .report_generator import ReportGenerator, get_report_generator
from .template_parser import TemplateParser, get_template_parser

logger = get_logger(__name__)


class ReportJobOrchestrator:
    """报告任务编排器。"""

    QUALITY_STATUS = "failed_quality_gate"

    def __init__(
        self,
        report_generator: Optional[ReportGenerator] = None,
        template_parser: Optional[TemplateParser] = None,
        job_store: Optional[JobStore] = None,
    ):
        self.report_generator = report_generator or get_report_generator()
        self.template_parser = template_parser or get_template_parser()
        self.job_store = job_store or get_job_store()

        self.soft_timeout_seconds = int(getattr(settings, "report_job_soft_timeout_seconds", 720) or 720)
        self.section_min_text_len = int(getattr(settings, "section_min_text_len", 180) or 180)
        self.structure_fidelity_threshold = float(
            getattr(settings, "structure_fidelity_threshold", 0.90) or 0.90
        )
        self.allow_publish_on_quality_gate_failure = bool(
            getattr(settings, "allow_publish_on_quality_gate_failure", True)
        )

        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._tasks_lock = threading.Lock()

        self._events: dict[str, list[dict[str, Any]]] = {}
        self._events_lock = threading.Lock()

        # ── Phase 1: 并发控制 ──
        self._worker_count = max(1, int(getattr(settings, "max_concurrent_jobs", 2) or 2))
        self._queue: asyncio.Queue[tuple[str, ReportJobSpec]] = asyncio.Queue(
            maxsize=settings.max_queued_jobs,
        )
        self._worker_tasks: list[asyncio.Task[None]] = []
        self._shutdown_event = asyncio.Event()
        self._shutdown_grace_period_s = float(getattr(settings, "shutdown_grace_period_seconds", 30) or 30.0)

        # ── 事件淘汰配置 ──
        self._max_events_per_job = 200
        self._terminal_event_ttl_seconds = 300  # 5 分钟

        recovered = self.job_store.recover_stale_running_jobs()
        if recovered:
            logger.warning("stale_jobs_recovered", count=recovered)

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        """启动固定 worker 池（在 FastAPI lifespan 中调用）。"""
        if any(not task.done() for task in self._worker_tasks):
            return
        self._shutdown_event.clear()
        self._queue = asyncio.Queue(maxsize=settings.max_queued_jobs)
        self._worker_tasks = [
            asyncio.create_task(self._worker_loop(worker_index + 1))
            for worker_index in range(self._worker_count)
        ]
        logger.info(
            "orchestrator_started",
            worker_count=self._worker_count,
            max_queued_jobs=settings.max_queued_jobs,
            shutdown_grace_period_s=self._shutdown_grace_period_s,
        )

    async def shutdown(self) -> None:
        """优雅停机：拒绝新任务、限时排空队列，超时后取消剩余任务。"""
        self._shutdown_event.set()
        logger.info("orchestrator_shutting_down", grace_period_s=self._shutdown_grace_period_s)

        drain_timeout_hit = False
        try:
            await asyncio.wait_for(self._queue.join(), timeout=self._shutdown_grace_period_s)
        except asyncio.TimeoutError:
            drain_timeout_hit = True
            logger.warning("shutdown_queue_drain_timeout")

        if drain_timeout_hit:
            self._cancel_queued_jobs_due_to_shutdown()
            with self._tasks_lock:
                running_job_ids = [job_id for job_id, task in self._tasks.items() if not task.done()]
            for job_id in running_job_ids:
                cancelled = self.cancel_job(job_id)
                if cancelled:
                    logger.info("task_cancelled_on_shutdown", job_id=job_id)

        for worker_task in self._worker_tasks:
            if worker_task.done():
                continue
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
        self._worker_tasks = []
        logger.info("orchestrator_stopped")

    def _cancel_queued_jobs_due_to_shutdown(self) -> None:
        """取消队列中尚未执行的任务，并同步状态到存储。"""
        while True:
            try:
                job_id, _ = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            try:
                self.job_store.mark_failed(
                    job_id,
                    error_code=ErrorCode.SYSTEM_SHUTTING_DOWN.value,
                    error_message="服务关闭导致任务未开始执行",
                    status="cancelled",
                    current_stage="cancelled",
                )
                self._emit_event(job_id, "cancelled", "服务关闭，任务已取消", level="warning")
            finally:
                self._queue.task_done()

    async def _worker_loop(self, worker_id: int) -> None:
        """固定 worker：从队列取任务并直接执行，不提前创建等待 task。"""
        logger.info("orchestrator_worker_started", worker_id=worker_id)
        while True:
            if self._shutdown_event.is_set() and self._queue.empty():
                break
            try:
                job_id, spec = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                self._evict_terminal_events()
                continue
            except asyncio.CancelledError:
                break

            if self._is_cancelled(job_id):
                self._queue.task_done()
                continue

            job_task = asyncio.create_task(self._run_job(job_id, spec))
            with self._tasks_lock:
                self._tasks[job_id] = job_task
            try:
                await job_task
            except asyncio.CancelledError:
                logger.warning("worker_job_cancelled", worker_id=worker_id, job_id=job_id)
            finally:
                with self._tasks_lock:
                    self._tasks.pop(job_id, None)
                self._queue.task_done()
        logger.info("orchestrator_worker_stopped", worker_id=worker_id)

    # ------------------------------------------------------------------ #
    # 提交任务
    # ------------------------------------------------------------------ #

    def submit_brand_health_job(
        self,
        spec: ReportJobSpec,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        if spec.report_type != "brand_health":
            raise ValueError(f"Unsupported report_type: {spec.report_type}")

        if self._shutdown_event.is_set():
            raise AppError(
                ErrorCode.SYSTEM_SHUTTING_DOWN,
                "服务正在关闭，无法接受新任务",
            )

        spec_payload = asdict(spec)
        job_id = f"job-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"

        # 幂等检查（同 key + 同 payload 命中；同 key + 不同 payload 冲突）
        if idempotency_key:
            payload_hash = self._canonical_payload_hash(spec_payload)
            claim = self.job_store.claim_idempotency(
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                job_id=job_id,
            )
            if claim["status"] == "replay":
                existing = self.job_store.get_job(claim["job_id"])
                if existing is None:
                    # 历史脏记录：释放后按新请求继续
                    self.job_store.release_idempotency(idempotency_key=idempotency_key)
                else:
                    logger.info(
                        "idempotent_hit",
                        idempotency_key=idempotency_key,
                        job_id=existing["job_id"],
                    )
                    return {
                        "job_id": existing["job_id"],
                        "status": existing["status"],
                        "report_type": existing["report_type"],
                        "created_at": existing["created_at"],
                        "idempotent_hit": True,
                    }
            elif claim["status"] == "conflict":
                logger.warning(
                    "idempotency_conflict",
                    idempotency_key=idempotency_key,
                    existing_job_id=claim.get("job_id"),
                )
                raise AppError(
                    ErrorCode.JOB_IDEMPOTENCY_CONFLICT,
                    "Idempotency-Key 与历史请求体不一致，请更换 Key 后重试",
                    extra={"existing_job_id": claim.get("job_id")},
                )

        try:
            self.job_store.create_job(
                job_id=job_id,
                report_type=spec.report_type,
                input_json=spec_payload,
                idempotency_key=idempotency_key,
            )
        except Exception:
            if idempotency_key:
                self.job_store.release_idempotency(idempotency_key=idempotency_key, job_id=job_id)
            raise

        self._emit_event(job_id, "queued", "任务已入队")

        try:
            self._queue.put_nowait((job_id, spec))
        except asyncio.QueueFull:
            self.job_store.mark_failed(job_id, "queue_full", "任务队列已满")
            if idempotency_key:
                self.job_store.release_idempotency(idempotency_key=idempotency_key, job_id=job_id)
            raise AppError(
                ErrorCode.JOB_QUEUE_FULL,
                f"任务队列已满（{settings.max_queued_jobs}/{settings.max_queued_jobs}），请稍后重试",
                retry_after_seconds=30,
            )

        return {
            "job_id": job_id,
            "status": "queued",
            "report_type": spec.report_type,
            "created_at": datetime.now().isoformat(),
        }

    @staticmethod
    def _canonical_payload_hash(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    async def _run_job(self, job_id: str, spec: ReportJobSpec) -> None:
        bind_job_id(job_id)
        logger.info("job_started", job_id=job_id)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._run_job_sync, job_id, spec),
                timeout=self.soft_timeout_seconds,
            )
        except asyncio.TimeoutError:
            self.job_store.mark_failed(
                job_id,
                error_code="timeout",
                error_message=f"任务超过软超时 {self.soft_timeout_seconds}s",
            )
            self._emit_event(job_id, "failed", "任务超时", level="error")
            logger.error("job_timeout", job_id=job_id, timeout_s=self.soft_timeout_seconds)
        except asyncio.CancelledError:
            if not self._is_cancelled(job_id):
                self.job_store.mark_failed(
                    job_id,
                    error_code="cancelled",
                    error_message="任务被取消",
                    status="cancelled",
                    current_stage="cancelled",
                )
            self._emit_event(job_id, "cancelled", "任务已取消", level="warning")
            raise
        except Exception as exc:
            self.job_store.mark_failed(
                job_id,
                error_code=type(exc).__name__,
                error_message=str(exc),
            )
            self._emit_event(
                job_id,
                "failed",
                f"任务异常：{type(exc).__name__}: {str(exc)}",
                level="error",
            )
            logger.error("job_failed", job_id=job_id, error=str(exc), exc_info=True)
        finally:
            bind_job_id("")


    def _run_job_sync(self, job_id: str, spec: ReportJobSpec) -> None:
        self.job_store.mark_running(job_id)
        self._update_stage(job_id, "planner", completed=0, total=0)
        if self._is_cancelled(job_id):
            return

        parsed = self.template_parser.parse(spec.template_name)
        sections = parsed.get("sections", [])
        section_plans = self._build_section_plans(sections, spec.category)
        self.job_store.save_artifact(
            job_id,
            artifact_type="plan",
            content=json.dumps([asdict(item) for item in section_plans], ensure_ascii=False),
        )
        self._emit_event(
            job_id,
            "planner",
            f"章节计划完成，共 {len(section_plans)} 个章节",
            data={"total_sections": len(section_plans)},
        )

        self._update_stage(job_id, "retriever", completed=0, total=len(section_plans))
        if self._is_cancelled(job_id):
            return

        raw_context = self.report_generator._collect_data(spec.brand_name, spec.competitors)
        raw_context.update(
            {
                "category": spec.category,
                "report_type": spec.report_type,
                "template_name": spec.template_name,
            }
        )
        self.job_store.save_artifact(
            job_id,
            artifact_type="retrieved_context",
            content=json.dumps(raw_context, ensure_ascii=False),
        )
        self._emit_event(job_id, "retriever", "数据检索完成")

        self._update_stage(job_id, "compressor", completed=0, total=len(section_plans))
        evidence_packs: list[EvidencePack] = []
        for idx, section in enumerate(sections):
            if self._is_cancelled(job_id):
                return
            compressed = self.report_generator._extract_relevant_data(section.section_id, raw_context)
            evidence = self._build_evidence_pack(section.section_id, compressed)
            evidence_packs.append(evidence)
            self.job_store.save_artifact(
                job_id,
                artifact_type="evidence",
                section_id=section.section_id,
                content=json.dumps(asdict(evidence), ensure_ascii=False),
            )
            self.job_store.append_section_log(
                job_id=job_id,
                section_id=section.section_id,
                stage="compressor",
                attempt=1,
                status="completed",
                metrics={"budget_chars": evidence.budget_chars, "source_count": len(evidence.source_urls)},
            )
            self._update_stage(job_id, "compressor", completed=idx + 1, total=len(section_plans))
        self._emit_event(job_id, "compressor", "证据压缩完成")

        if self._is_cancelled(job_id):
            return

        self._update_stage(job_id, "writer", completed=0, total=len(section_plans))
        self._emit_event(job_id, "writer", "开始章节生成与校验")
        generation_started = time.perf_counter()

        result = self.report_generator.generate_brand_health(
            brand_name=spec.brand_name,
            category=spec.category,
            competitors=spec.competitors,
            template_name=spec.template_name,
            use_llm=spec.use_llm,
            strict_llm=spec.strict_llm,
            enable_web_search=spec.enable_web_search,
        )
        generation_latency_ms = int((time.perf_counter() - generation_started) * 1000)

        html_content = result.get("html_content", "")
        context_data = result.get("context_data", {}) if isinstance(result.get("context_data"), dict) else {}
        llm_sections = context_data.get("llm_sections") if isinstance(context_data, dict) else None
        if not isinstance(llm_sections, list):
            llm_sections = []

        for index, item in enumerate(llm_sections):
            if not isinstance(item, dict):
                continue
            section_id = str(item.get("section_id") or f"section-{index + 1}")
            self.job_store.append_section_log(
                job_id=job_id,
                section_id=section_id,
                stage="writer",
                attempt=int(item.get("attempts") or 1),
                status="completed" if item.get("ok") else "failed",
                metrics={
                    "similarity_ratio": item.get("similarity_ratio"),
                    "validation_error": item.get("validation_error"),
                    "used_fallback": bool(item.get("used_fallback")),
                    "fallback_reason": item.get("fallback_reason"),
                    "attempts_detail": item.get("attempts_detail"),
                    "inline_source_ok": item.get("inline_source_ok"),
                    "inline_source_coverage": item.get("inline_source_coverage"),
                    "structure_retention_ratio": item.get("structure_retention_ratio"),
                    "filled_block_count": item.get("filled_block_count"),
                    "empty_block_count": item.get("empty_block_count"),
                    "micro_slots_total": item.get("micro_slots_total"),
                    "micro_slots_filled": item.get("micro_slots_filled"),
                    "micro_slots_empty": item.get("micro_slots_empty"),
                    "provider_error_type": item.get("provider_error_type"),
                    "provider_error_message": item.get("provider_error_message"),
                    "timeout_hit": item.get("timeout_hit"),
                    "search_degraded": item.get("search_degraded"),
                },
                error_code=item.get("error"),
                latency_ms=int(item.get("latency_ms") or 0),
            )
            self._update_stage(job_id, "writer", completed=index + 1, total=max(len(section_plans), 1))

        self._update_stage(job_id, "verifier", completed=0, total=max(len(section_plans), 1))
        section_drafts = self._extract_section_drafts(html_content=html_content, parsed_sections=sections)
        plan_map = {plan.section_id: plan for plan in section_plans}
        draft_verifications: list[dict[str, Any]] = []
        for index, draft in enumerate(section_drafts):
            self.job_store.save_artifact(
                job_id,
                artifact_type="draft",
                section_id=draft.section_id,
                content=json.dumps(asdict(draft), ensure_ascii=False),
            )
            verification = self._verify_section_draft(draft, plan_map.get(draft.section_id))
            draft_verifications.append(verification)
            self.job_store.append_section_log(
                job_id=job_id,
                section_id=draft.section_id,
                stage="verifier",
                attempt=int(draft.attempt),
                status="passed" if verification.get("passed") else "failed",
                metrics=verification.get("metrics") or {},
                error_code=verification.get("error_code"),
                latency_ms=0,
            )
            self._update_stage(job_id, "verifier", completed=index + 1, total=max(len(section_drafts), 1))

        self.job_store.save_artifact(
            job_id,
            artifact_type="render",
            content=html_content,
        )
        self._emit_event(
            job_id,
            "renderer",
            "章节渲染完成",
            data={"generation_latency_ms": generation_latency_ms},
        )

        self._emit_event(
            job_id,
            "verifier",
            "章节校验完成",
            data={
                "sections": len(section_drafts),
                "failed_sections": len([item for item in draft_verifications if not item.get("passed")]),
            },
        )

        self._update_stage(job_id, "final_guard", completed=len(section_plans), total=len(section_plans))
        quality_metrics = self._run_final_quality_gate(
            html_content=html_content,
            parsed_sections=sections,
            category=spec.category,
            llm_sections=llm_sections,
            draft_verifications=draft_verifications,
        )
        self.job_store.save_artifact(
            job_id,
            artifact_type="quality",
            content=json.dumps(quality_metrics, ensure_ascii=False),
        )

        quality_passed = bool(quality_metrics.get("passed", False))
        if not quality_passed:
            if not self.allow_publish_on_quality_gate_failure:
                self.job_store.mark_failed(
                    job_id,
                    error_code="quality_gate_failed",
                    error_message="最终质量闸门未通过",
                    status=self.QUALITY_STATUS,
                    current_stage="failed_quality_gate",
                )
                self._emit_event(
                    job_id,
                    "failed_quality_gate",
                    "质量闸门未通过，报告阻断发布",
                    level="error",
                    data=quality_metrics,
                )
                return

            self._emit_event(
                job_id,
                "quality_warning",
                "质量闸门未通过，但已按配置继续发布报告",
                level="warning",
                data=quality_metrics,
            )

        diagnostics = {
            "sections": llm_sections,
            "ping": context_data.get("llm_ping"),
            "search_meta": (context_data.get("llm_search") or {}).get("_meta")
            if isinstance(context_data.get("llm_search"), dict)
            else None,
            "error": context_data.get("llm_error"),
            "quality_warning": (quality_metrics.get("failures") or []) if not quality_passed else [],
            "published_with_quality_warnings": bool(not quality_passed),
        }

        artifact = RenderArtifact(
            job_id=job_id,
            report_id=result.get("report_id", ""),
            output_path=result.get("output_path", ""),
            html_content=html_content,
            generated_at=result.get("generated_at") or datetime.now().isoformat(),
            llm_diagnostics=diagnostics,
            quality_gate=quality_metrics,
        )

        result_payload = {
            "job_id": artifact.job_id,
            "report_id": artifact.report_id,
            "output_path": artifact.output_path,
            "generated_at": artifact.generated_at,
            "llm_diagnostics": artifact.llm_diagnostics,
            "quality_gate": artifact.quality_gate,
            "quality_gate_passed": bool(quality_passed),
            "published_with_quality_warnings": bool(not quality_passed),
        }
        self.job_store.save_artifact(
            job_id,
            artifact_type="final",
            content=json.dumps(result_payload, ensure_ascii=False),
        )
        self.job_store.mark_succeeded(job_id, result_json=result_payload)
        self._update_stage(job_id, "completed", completed=len(section_plans), total=len(section_plans))
        self._emit_event(job_id, "completed", "任务成功完成", data=result_payload)

    def _build_section_plans(self, sections: list[Any], category: str) -> list[SectionPlan]:
        title_objectives = {
            "宏观趋势与格局": "分析市场规模、结构变化和增长驱动，识别品牌机会和约束。",
            "全球化洞察": "分析区域差异、出海机会和跨区域打法。",
            "人群洞察与画像": "刻画核心人群、消费动机、决策路径与触达策略。",
            "竞品深度攻防": "比较竞品定位、产品与传播策略，提出攻防动作。",
            "战略总结与资源": "给出优先级行动、资源投放建议和阶段性目标。",
        }
        keyword_blocks = {
            "宏观趋势与格局": ["市场规模", "增长趋势", "风险机会"],
            "全球化洞察": ["重点市场", "区域差异", "本地化建议"],
            "人群洞察与画像": ["核心客群", "消费场景", "决策触点"],
            "竞品深度攻防": ["竞品矩阵", "优势短板", "攻防动作"],
            "战略总结与资源": ["关键策略", "资源配置", "里程碑"],
        }

        non_washcare = not any(
            marker in (category or "").lower() for marker in self.report_generator.WASHCARE_CATEGORY_MARKERS
        )
        forbidden_terms = ["清扬", "KONO", "Spes", "去屑", "头皮", "洗发"] if non_washcare else []

        plans: list[SectionPlan] = []
        for section in sections:
            title = getattr(section, "title", "") or ""
            plans.append(
                SectionPlan(
                    section_id=getattr(section, "section_id", ""),
                    section_title=title,
                    objective=title_objectives.get(title, f"围绕 {title} 生成结构化洞察"),
                    required_information_blocks=keyword_blocks.get(title, ["关键结论", "证据", "建议动作"]),
                    min_density=3,
                    forbidden_terms=forbidden_terms,
                )
            )
        return plans

    def _build_evidence_pack(self, section_id: str, context: dict[str, Any]) -> EvidencePack:
        compact = self._compress_context(context, budget_chars=8000)
        source_urls: list[str] = []
        source_names: list[str] = []
        skipped: list[str] = []

        llm_search = context.get("llm_search") if isinstance(context, dict) else None
        if isinstance(llm_search, dict):
            meta = llm_search.get("_meta")
            links = meta.get("source_links") if isinstance(meta, dict) else None
            if isinstance(links, list):
                for item in links:
                    if isinstance(item, dict) and item.get("url"):
                        source_urls.append(str(item.get("url")))

        mock_skipped = context.get("mock_sources_skipped") if isinstance(context, dict) else None
        if isinstance(mock_skipped, list):
            skipped.extend([str(item) for item in mock_skipped])

        all_sources = context.get("all_sources") if isinstance(context, dict) else None
        if isinstance(all_sources, dict):
            source_names.extend(list(all_sources.keys()))

        return EvidencePack(
            section_id=section_id,
            compressed_context=compact,
            source_urls=source_urls[:20],
            source_names=source_names,
            mock_sources_skipped=skipped,
            budget_chars=8000,
        )

    def _compress_context(self, context: dict[str, Any], budget_chars: int = 8000) -> dict[str, Any]:
        try:
            text = json.dumps(context, ensure_ascii=False)
        except Exception:
            text = str(context)

        if len(text) <= budget_chars:
            return context

        head_size = int(budget_chars * 0.6)
        tail_size = int(budget_chars * 0.25)
        return {
            "_truncated": True,
            "head": text[:head_size],
            "tail": text[-tail_size:],
            "original_length": len(text),
            "budget_chars": budget_chars,
        }

    def _extract_section_drafts(self, html_content: str, parsed_sections: list[Any]) -> list[SectionDraft]:
        soup = BeautifulSoup(html_content or "", "lxml")
        generated_titles = soup.find_all("h2", class_="section-title")

        drafts: list[SectionDraft] = []
        expected_sections = [
            section for section in parsed_sections if str(getattr(section, "section_id", "")).startswith("section-")
        ]
        for index, section in enumerate(expected_sections):
            if index >= len(generated_titles):
                continue

            title_node = generated_titles[index]
            section_root = title_node.find_parent("section") or title_node.parent
            section_text = section_root.get_text(" ", strip=True) if section_root is not None else ""
            normalized_section_text = re.sub(r"\s+", " ", section_text).strip()

            section_title_text = title_node.get_text(" ", strip=True)
            candidates: list[str] = []
            if section_root is not None:
                # 扩大抽取标签覆盖，减少因模板结构差异导致的“有内容但抽不到要点”。
                for node in section_root.find_all(
                    ["p", "li", "td", "span", "h3", "h4", "strong", "small", "blockquote", "div"]
                ):
                    if getattr(node, "name", "") == "div":
                        # 避免抓取到大容器导致文本重复叠加，仅保留更接近叶子节点的 div。
                        if node.find(["div", "p", "li", "table", "ul", "ol"], recursive=False):
                            continue

                    raw = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
                    if not raw or len(raw) < 12:
                        continue
                    if raw == section_title_text:
                        continue
                    candidates.append(raw)

            deduped: list[str] = []
            seen: set[str] = set()
            for line in candidates:
                key = line[:120]
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(line)

            # 回退：若结构化标签抽取不足，则从整节文本按句拆分补足 key_points。
            if len(deduped) < 3 and normalized_section_text:
                cleaned_text = normalized_section_text.replace(section_title_text, " ").strip()
                fragments = [
                    fragment.strip(" •·-—:：")
                    for fragment in re.split(r"[。！？；;\n]+", cleaned_text)
                    if fragment.strip()
                ]
                for fragment in fragments:
                    if len(fragment) < 12:
                        continue
                    key = fragment[:120]
                    if key in seen:
                        continue
                    seen.add(key)
                    deduped.append(fragment)
                    if len(deduped) >= 6:
                        break

            if len(deduped) < 3 and normalized_section_text:
                # 进一步兜底：按长度切片，确保 verifier 至少有可评估的要点密度。
                cleaned_text = normalized_section_text.replace(section_title_text, " ").strip()
                chunk_size = 42
                for idx in range(0, len(cleaned_text), chunk_size):
                    fragment = cleaned_text[idx : idx + chunk_size].strip(" •·-—:：")
                    if len(fragment) < 12:
                        continue
                    key = fragment[:120]
                    if key in seen:
                        continue
                    seen.add(key)
                    deduped.append(fragment)
                    if len(deduped) >= 6:
                        break

            summary_candidates = [line for line in deduped if len(line) >= 20]
            summary = summary_candidates[0] if summary_candidates else (deduped[0] if deduped else normalized_section_text[:160])
            key_points = deduped[:6]
            action_items = [
                line
                for line in deduped
                if any(word in line for word in ["建议", "行动", "优先", "策略", "落地", "优化", "推进", "提升"])
            ][:4]
            metrics = [line for line in deduped if any(ch.isdigit() for ch in line)][:4]

            citations: list[dict[str, str]] = []
            if section_root is not None:
                for link in section_root.find_all("a", href=True):
                    href = str(link.get("href") or "").strip()
                    if not href.startswith("http"):
                        continue
                    citations.append(
                        {
                            "text": link.get_text(strip=True) or "来源",
                            "url": href,
                        }
                    )

            drafts.append(
                SectionDraft(
                    section_id=str(getattr(section, "section_id", "")),
                    section_title=str(getattr(section, "title", "")),
                    summary=summary,
                    key_points=key_points,
                    action_items=action_items,
                    metrics=metrics,
                    citations=citations[:8],
                    attempt=1,
                    retry_reason=None,
                    model_name=str(getattr(self.report_generator.llm_client, "model", "")) if hasattr(self.report_generator, "llm_client") else None,
                )
            )

        return drafts

    def _verify_section_draft(self, draft: SectionDraft, plan: Optional[SectionPlan]) -> dict[str, Any]:
        reasons: list[str] = []
        metrics = {
            "key_points_count": len(draft.key_points),
            "action_items_count": len(draft.action_items),
            "metrics_count": len(draft.metrics),
            "summary_len": len(draft.summary or ""),
        }

        min_density = plan.min_density if plan is not None else 3
        density = len(draft.key_points) + len(draft.action_items)
        metrics["density"] = density
        metrics["min_density"] = min_density

        if density < min_density:
            reasons.append("density_low")

        if plan is not None and plan.forbidden_terms:
            combined_text = " ".join([draft.summary, *draft.key_points, *draft.action_items]).lower()
            leaked = [term for term in plan.forbidden_terms if term.lower() in combined_text]
            if leaked:
                reasons.append("forbidden_terms")
                metrics["forbidden_terms"] = leaked

        passed = len(reasons) == 0
        return {
            "section_id": draft.section_id,
            "passed": passed,
            "error_code": None if passed else reasons[0],
            "reasons": reasons,
            "metrics": metrics,
        }

    def _run_final_quality_gate(
        self,
        html_content: str,
        parsed_sections: list[Any],
        category: str,
        llm_sections: list[dict[str, Any]],
        draft_verifications: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        failures: list[str] = []
        metrics: dict[str, Any] = {}

        soup = BeautifulSoup(html_content or "", "lxml")
        text = soup.get_text(" ", strip=True)
        text_lower = text.lower()

        if "llm-placeholder" in (html_content or ""):
            failures.append("contains_llm_placeholder")
        if "暂时无法生成" in text or "正在生成" in text:
            failures.append("contains_fallback_placeholder_text")

        expected_titles = [
            getattr(section, "title", "")
            for section in parsed_sections
            if str(getattr(section, "section_id", "")).startswith("section-")
        ]
        actual_titles = [node.get_text(strip=True) for node in soup.find_all("h2", class_="section-title")]
        metrics["expected_titles"] = expected_titles
        metrics["actual_titles"] = actual_titles[: len(expected_titles)]
        if actual_titles[: len(expected_titles)] != expected_titles:
            failures.append("title_order_mismatch")

        banned_terms = ["清扬", "kono", "spes", "去屑", "头皮", "洗发"]
        is_washcare = any(marker in (category or "").lower() for marker in self.report_generator.WASHCARE_CATEGORY_MARKERS)
        leaked_terms: list[str] = []
        if not is_washcare:
            for term in banned_terms:
                if term in text_lower:
                    leaked_terms.append(term)
            if leaked_terms:
                failures.append("category_pollution_terms")
        metrics["pollution_terms"] = leaked_terms

        section_text_lengths: list[int] = []
        for index, _ in enumerate(expected_titles):
            node = soup.find_all("h2", class_="section-title")
            if index >= len(node):
                section_text_lengths.append(0)
                continue
            title_node = node[index]
            section_root = title_node.find_parent("section") or title_node.parent
            sec_text = section_root.get_text(" ", strip=True) if section_root else ""
            section_text_lengths.append(len(sec_text))

        metrics["section_text_lengths"] = section_text_lengths
        if any(length < self.section_min_text_len for length in section_text_lengths):
            failures.append("section_text_too_short")

        verifications = draft_verifications or []
        metrics["draft_verifications"] = verifications
        failed_drafts = [item for item in verifications if isinstance(item, dict) and not item.get("passed")]
        if failed_drafts:
            failures.append("draft_verification_failed")

        similarity_flags: list[dict[str, Any]] = []
        inline_source_failures: list[dict[str, Any]] = []
        structure_retention_failures: list[dict[str, Any]] = []
        empty_block_warnings: list[dict[str, Any]] = []
        for item in llm_sections:
            if not isinstance(item, dict):
                continue
            ratio = item.get("similarity_ratio")
            if ratio is None:
                pass
            elif float(ratio) >= self.report_generator.TEMPLATE_SIMILARITY_THRESHOLD:
                similarity_flags.append(
                    {
                        "section_id": item.get("section_id"),
                        "similarity_ratio": ratio,
                    }
                )

            inline_ok = item.get("inline_source_ok")
            if inline_ok is False:
                inline_source_failures.append(
                    {
                        "section_id": item.get("section_id"),
                        "inline_source_coverage": item.get("inline_source_coverage"),
                    }
                )

            retention = item.get("structure_retention_ratio")
            if isinstance(retention, (int, float)) and float(retention) < self.structure_fidelity_threshold:
                structure_retention_failures.append(
                    {
                        "section_id": item.get("section_id"),
                        "structure_retention_ratio": retention,
                    }
                )

            empty_count = item.get("empty_block_count")
            if isinstance(empty_count, (int, float)) and int(empty_count) > 0:
                empty_block_warnings.append(
                    {
                        "section_id": item.get("section_id"),
                        "empty_block_count": int(empty_count),
                        "filled_block_count": item.get("filled_block_count"),
                    }
                )

        metrics["high_similarity_sections"] = similarity_flags
        if similarity_flags:
            failures.append("template_similarity_high")

        metrics["inline_source_failures"] = inline_source_failures
        if inline_source_failures:
            failures.append("missing_inline_sources")

        metrics["structure_retention_failures"] = structure_retention_failures
        if structure_retention_failures:
            failures.append("structure_retention_low")

        metrics["empty_block_warnings"] = empty_block_warnings
        if empty_block_warnings:
            failures.append("empty_blocks_detected")

        structure_score = self._compute_structure_fidelity_score(
            html_content=html_content,
            parsed_sections=parsed_sections,
        )
        metrics["structure_fidelity_score"] = round(structure_score, 4)
        if structure_score < self.structure_fidelity_threshold:
            failures.append("structure_fidelity_low")

        metrics["passed"] = len(failures) == 0
        metrics["failures"] = failures
        return metrics

    def _compute_structure_fidelity_score(self, html_content: str, parsed_sections: list[Any]) -> float:
        soup = BeautifulSoup(html_content or "", "lxml")
        generated_titles = soup.find_all("h2", class_="section-title")

        scores: list[float] = []
        expected_sections = [
            section for section in parsed_sections if str(getattr(section, "section_id", "")).startswith("section-")
        ]

        for index, section in enumerate(expected_sections):
            if index >= len(generated_titles):
                scores.append(0.0)
                continue

            generated_title = generated_titles[index]
            generated_root = generated_title.find_parent("section") or generated_title.parent
            generated_fragment = str(generated_root) if generated_root is not None else str(generated_title)
            template_fragment = str(getattr(section, "html_content", ""))

            template_features = self._extract_structure_features(template_fragment)
            generated_features = self._extract_structure_features(generated_fragment)

            template_classes = template_features["classes"]
            template_tags = template_features["tags"]
            generated_classes = generated_features["classes"]
            generated_tags = generated_features["tags"]

            class_score = (
                len(template_classes.intersection(generated_classes)) / len(template_classes)
                if template_classes
                else 1.0
            )
            tag_score = (
                len(template_tags.intersection(generated_tags)) / len(template_tags)
                if template_tags
                else 1.0
            )

            wrapper_bonus = 1.0 if generated_root is not None and generated_root.name == "section" else 0.0
            score = (class_score * 0.6) + (tag_score * 0.3) + (wrapper_bonus * 0.1)
            scores.append(min(max(score, 0.0), 1.0))

        if not scores:
            return 1.0
        return sum(scores) / len(scores)

    def _extract_structure_features(self, html_fragment: str) -> dict[str, set[str]]:
        soup = BeautifulSoup(html_fragment or "", "lxml")
        root = soup.body or soup

        classes: set[str] = set()
        tags: set[str] = set()
        important_prefixes = (
            "section",
            "grid",
            "glass-card",
            "card",
            "kpi",
            "chart",
            "table",
            "tag",
            "chip",
        )

        for node in root.find_all(True)[:240]:
            if not getattr(node, "name", None):
                continue
            tags.add(str(node.name))
            for token in node.get("class") or []:
                if not isinstance(token, str):
                    continue
                if token.startswith(important_prefixes):
                    classes.add(token)

        return {
            "classes": classes,
            "tags": tags,
        }

    def _is_cancelled(self, job_id: str) -> bool:
        job = self.job_store.get_job(job_id)
        if not isinstance(job, dict):
            return True
        return job.get("status") == "cancelled"

    def _update_stage(self, job_id: str, stage: str, completed: int, total: int) -> None:
        progress = {
            "stage": stage,
            "completed_sections": int(completed),
            "total_sections": int(total),
        }
        self.job_store.update_stage(job_id, stage=stage, progress=progress)

    def _emit_event(
        self,
        job_id: str,
        stage: str,
        message: str,
        level: str = "info",
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        payload = {
            "timestamp": datetime.now().isoformat(),
            "stage": stage,
            "level": level,
            "message": message,
            "data": data or {},
        }
        with self._events_lock:
            bucket = self._events.setdefault(job_id, [])
            seq = (bucket[-1]["seq"] + 1) if bucket else 1
            payload["seq"] = seq
            bucket.append(payload)
            # 事件淘汰：单 job 上限
            if len(bucket) > self._max_events_per_job:
                self._events[job_id] = bucket[-self._max_events_per_job :]

    def _evict_terminal_events(self) -> None:
        """清理终态任务的历史事件（TTL 过期）。"""
        now = datetime.now()
        with self._events_lock:
            expired_jobs: list[str] = []
            for jid, bucket in self._events.items():
                if not bucket:
                    expired_jobs.append(jid)
                    continue
                last_ts = bucket[-1].get("timestamp", "")
                last_stage = bucket[-1].get("stage", "")
                if last_stage in ("failed", "cancelled", "completed"):
                    try:
                        dt = datetime.fromisoformat(last_ts)
                        if (now - dt).total_seconds() > self._terminal_event_ttl_seconds:
                            expired_jobs.append(jid)
                    except (ValueError, TypeError):
                        expired_jobs.append(jid)
            for jid in expired_jobs:
                del self._events[jid]

    def get_events(self, job_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        with self._events_lock:
            bucket = self._events.get(job_id, [])
            return [event for event in bucket if int(event.get("seq", 0)) > int(after_seq)]

    def get_job_status(self, job_id: str) -> Optional[dict[str, Any]]:
        job = self.job_store.get_job(job_id)
        if not isinstance(job, dict):
            return None
        section_logs = self.job_store.list_section_logs(job_id)
        return {
            "job_id": job["job_id"],
            "report_type": job["report_type"],
            "status": job["status"],
            "created_at": job["created_at"],
            "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at"),
            "current_stage": job.get("current_stage"),
            "progress": job.get("progress") or {},
            "error_code": job.get("error_code"),
            "error_message": job.get("error_message"),
            "section_logs": section_logs,
        }

    def get_job_result(self, job_id: str) -> Optional[dict[str, Any]]:
        return self.job_store.get_result(job_id)

    def cancel_job(self, job_id: str) -> bool:
        cancelled = self.job_store.cancel_job(job_id)
        if cancelled:
            with self._tasks_lock:
                task = self._tasks.get(job_id)
            if task is not None and not task.done():
                task.cancel()
            self._emit_event(job_id, "cancelled", "任务取消请求已受理", level="warning")
            logger.info("job_cancelled", job_id=job_id)
        return cancelled


_orchestrator: Optional[ReportJobOrchestrator] = None


def get_orchestrator() -> ReportJobOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ReportJobOrchestrator()
    return _orchestrator
