"""
Market Insight Agent - Task Manager
====================================
任务管理器，负责任务的创建、查询和执行。

设计思想：
1. 统一任务管理入口
2. 支持内存存储（开发）和 Redis 存储（生产）
3. 预留 Celery 异步任务接口

后续开发方向：
1. 对接 Celery 实现真正的异步任务
2. 对接 Redis 实现任务状态持久化
3. 添加任务超时和重试机制
"""

import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from loguru import logger

from app.config import settings
from app.models.task import Task, TaskStatus, TaskType
from app.repositories.task_repository import TaskRepository


class TaskManager:
    """
    任务管理器
    
    当前实现：使用内存字典存储任务（仅适用于开发调试）
    
    生产环境应：
    1. 使用 Redis 存储任务状态
    2. 使用 Celery 执行异步任务
    """
    
    def __init__(self):
        # 内存存储（开发用）
        # TODO: 替换为 Redis 存储
        self._tasks: Dict[str, Task] = {}
        self._repo: Optional[TaskRepository] = (
            TaskRepository() if settings.task_store_backend == "sqlite" else None
        )
    
    async def create_task(
        self,
        task_type: str,
        params: Dict[str, Any],
    ) -> str:
        """
        创建新任务
        
        Args:
            task_type: 任务类型 (brand_health / tiktok_insight)
            params: 任务参数
            
        Returns:
            task_id: 任务唯一标识
        """
        # 生成唯一 task_id
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        
        # 创建任务对象
        task = Task(
            task_id=task_id,
            task_type=TaskType(task_type),
            status=TaskStatus.PENDING,
            params=params,
            created_at=datetime.utcnow(),
        )
        
        # 存储任务
        self._tasks[task_id] = task
        if self._repo is not None:
            await self._repo.upsert(task)
        
        logger.info(f"Task created: {task_id}, type: {task_type}")
        return task_id
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """
        获取任务信息
        
        Args:
            task_id: 任务 ID
            
        Returns:
            Task 对象，不存在则返回 None
        """
        task = self._tasks.get(task_id)
        if task is not None:
            return task
        if self._repo is None:
            return None
        task = await self._repo.get(task_id)
        if task is not None:
            self._tasks[task_id] = task
        return task

    async def list_tasks(self, limit: int = 50) -> list[Task]:
        """
        列出最近任务（用于历史记录/管理台）。

        - SQLite 模式：按创建时间倒序
        - Memory 模式：按创建时间倒序（当前进程内）
        """
        if self._repo is not None:
            return await self._repo.list_recent(limit=limit)

        tasks = sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]
    
    async def update_task_progress(
        self,
        task_id: str,
        progress: int,
        message: str,
    ) -> None:
        """
        更新任务进度
        
        Args:
            task_id: 任务 ID
            progress: 进度百分比 (0-100)
            message: 当前步骤描述
        """
        task = self._tasks.get(task_id)
        if task:
            task.update_progress(progress, message)
            if self._repo is not None:
                await self._repo.upsert(task)
            logger.debug(f"Task {task_id} progress: {progress}% - {message}")
    
    async def complete_task(self, task_id: str, result: str) -> None:
        """
        完成任务
        
        Args:
            task_id: 任务 ID
            result: 生成的 HTML 报告内容
        """
        task = self._tasks.get(task_id)
        if task:
            task.complete(result)
            if self._repo is not None:
                await self._repo.upsert(task)
            logger.info(f"Task {task_id} completed successfully")
    
    async def fail_task(
        self,
        task_id: str,
        error_message: str,
        error_details: Optional[str] = None,
    ) -> None:
        """
        标记任务失败
        
        Args:
            task_id: 任务 ID
            error_message: 错误信息
            error_details: 错误详情
        """
        task = self._tasks.get(task_id)
        if task:
            task.fail(error_message, error_details)
            if self._repo is not None:
                await self._repo.upsert(task)
            logger.error(f"Task {task_id} failed: {error_message}")
    
    async def execute_brand_health_task(
        self,
        task_id: str,
        params: Dict[str, Any],
    ) -> None:
        """
        执行品牌健康度分析任务
        
        这是后台任务执行入口，会调用 LangGraph Agent 完成报告生成。
        
        TODO: 对接 LangGraph BrandHealthAgent
        """
        logger.info(f"Starting brand health task: {task_id}")
        
        task = self._tasks.get(task_id)
        if not task:
            logger.error(f"Task not found: {task_id}")
            return
        
        try:
            # 开始任务
            task.start()
            if self._repo is not None:
                await self._repo.upsert(task)

            from app.agents.brand_health_agent import BrandHealthAgent

            def progress_callback(progress: int, message: str) -> None:
                asyncio.create_task(self.update_task_progress(task_id, progress, message))

            agent = BrandHealthAgent(progress_callback=progress_callback)
            html_report = await asyncio.wait_for(
                agent.run({**params, "task_id": task_id}),
                timeout=settings.task_timeout_seconds,
            )
            await self.complete_task(task_id, html_report)
            
        except Exception as e:
            logger.exception(f"Task {task_id} execution failed")
            await self.fail_task(task_id, str(e))
    
    async def execute_tiktok_insight_task(
        self,
        task_id: str,
        params: Dict[str, Any],
    ) -> None:
        """
        执行 TikTok 社媒洞察任务
        
        TODO: 对接 LangGraph TikTokInsightAgent
        """
        logger.info(f"Starting TikTok insight task: {task_id}")
        
        task = self._tasks.get(task_id)
        if not task:
            logger.error(f"Task not found: {task_id}")
            return
        
        try:
            task.start()
            if self._repo is not None:
                await self._repo.upsert(task)

            from app.agents.tiktok_insight_agent import TikTokInsightAgent

            def progress_callback(progress: int, message: str) -> None:
                asyncio.create_task(self.update_task_progress(task_id, progress, message))

            agent = TikTokInsightAgent(progress_callback=progress_callback)
            html_report = await asyncio.wait_for(
                agent.run({**params, "task_id": task_id}),
                timeout=settings.task_timeout_seconds,
            )
            await self.complete_task(task_id, html_report)
            
        except Exception as e:
            logger.exception(f"Task {task_id} execution failed")
            await self.fail_task(task_id, str(e))
    
    def _generate_mock_report(
        self,
        params: Dict[str, Any],
        report_type: str,
    ) -> str:
        """
        生成模拟报告（开发调试用）
        
        TODO: 删除此方法，替换为真实的 Agent 报告生成
        """
        if report_type == "brand_health":
            return f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <title>品牌健康度诊断报告 - {params.get('brand_name', 'Unknown')}</title>
    <style>
        body {{ font-family: system-ui; background: #0b0d12; color: #e9ecf3; padding: 40px; }}
        .container {{ max-width: 1100px; margin: 0 auto; }}
        h1 {{ color: #7aa2ff; }}
        .card {{ background: rgba(255,255,255,0.05); border-radius: 14px; padding: 20px; margin: 20px 0; }}
        .placeholder {{ color: #aab3c5; font-style: italic; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🎯 品牌健康度诊断报告</h1>
        <div class="card">
            <h2>品牌信息</h2>
            <p><strong>品牌名称：</strong>{params.get('brand_name', 'N/A')}</p>
            <p><strong>目标地区：</strong>{params.get('region', 'N/A')}</p>
            <p><strong>竞品：</strong>{', '.join(params.get('competitors', []))}</p>
        </div>
        <div class="card">
            <h2>📊 市场洞察</h2>
            <p class="placeholder">[此处为 Agent 生成的市场洞察内容]</p>
        </div>
        <div class="card">
            <h2>👥 消费者分析</h2>
            <p class="placeholder">[此处为 Agent 生成的消费者分析内容]</p>
        </div>
        <div class="card">
            <h2>🚧 SEO 诊断</h2>
            <p class="placeholder">此功能暂未启用，敬请期待</p>
        </div>
        <div class="card">
            <h2>💡 策略建议</h2>
            <p class="placeholder">[此处为 Agent 生成的策略建议内容]</p>
        </div>
    </div>
</body>
</html>
"""
        else:
            return f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <title>TikTok 社媒洞察报告 - {params.get('category', 'Unknown')}</title>
    <style>
        body {{ font-family: system-ui; background: #0b0d12; color: #e9ecf3; padding: 40px; }}
        .container {{ max-width: 1100px; margin: 0 auto; }}
        h1 {{ color: #7aa2ff; }}
        .card {{ background: rgba(255,255,255,0.05); border-radius: 14px; padding: 20px; margin: 20px 0; }}
        .placeholder {{ color: #aab3c5; font-style: italic; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📱 TikTok 社媒洞察报告</h1>
        <div class="card">
            <h2>分析信息</h2>
            <p><strong>品类：</strong>{params.get('category', 'N/A')}</p>
            <p><strong>卖点：</strong>{', '.join(params.get('selling_points', []))}</p>
        </div>
        <div class="card">
            <h2>🔥 热门视频分析</h2>
            <p class="placeholder">[此处为 Agent 生成的热门视频分析内容]</p>
        </div>
        <div class="card">
            <h2>📈 卖点策略洞察</h2>
            <p class="placeholder">[此处为 Agent 生成的卖点策略洞察内容]</p>
        </div>
        <div class="card">
            <h2>💡 创意方向建议</h2>
            <p class="placeholder">[此处为 Agent 生成的创意方向建议内容]</p>
        </div>
    </div>
</body>
</html>
"""


# 创建全局任务管理器实例
task_manager = TaskManager()
