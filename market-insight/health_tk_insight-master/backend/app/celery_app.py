"""
Celery integration (optional).

Default execution uses FastAPI BackgroundTasks.
Enable Celery by setting `CELERY_ENABLED=true` and providing a reachable Redis broker.
"""

from __future__ import annotations

import asyncio

from celery import Celery

from app.config import settings
from app.services.task_manager import task_manager


celery_app = Celery(
    "market_insight_agent",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)


@celery_app.task(
    name="tasks.run_brand_health",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def run_brand_health(task_id: str, params: dict) -> None:
    asyncio.run(task_manager.execute_brand_health_task(task_id=task_id, params=params))


@celery_app.task(
    name="tasks.run_tiktok_insight",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def run_tiktok_insight(task_id: str, params: dict) -> None:
    asyncio.run(task_manager.execute_tiktok_insight_task(task_id=task_id, params=params))
