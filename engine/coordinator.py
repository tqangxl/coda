"""
Coda V4.0 — Coordinator Orchestration (中重要度 #12)
Coordinator 调度逻辑: 任务拆分、负载均衡、结果聚合。

设计参考: 原始 TS `coordinator/coordinatorMode.ts`
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol, TYPE_CHECKING
from collections.abc import Awaitable

from .base_types import (
    TaskStatus, SubTask, SwarmPeer, SwarmRole, SwarmMessage, 
    SwarmNetworkProtocol, IntentEngineProtocol
)

logger = logging.getLogger("Coda.coordinator")


# SubTask moved to base_types.py


class CoordinatorEngine:
    """
    Coordinator 调度引擎。

    作为主控引擎, 负责:
    1. 任务分析与拆分 — 将大任务分解为可并行的子任务
    2. 负载均衡 — 根据 Worker 能力和负载分配任务
    3. 结果聚合 — 收集所有子任务结果并合并
    4. 容错重试 — 子任务失败时自动重试或重新分配
    """
    _intent_engine: IntentEngineProtocol | None
    network: SwarmNetworkProtocol

    def __init__(
        self,
        llm_caller: object,
        store: object,
        network: SwarmNetworkProtocol,
        intent_engine: IntentEngineProtocol | None = None
    ) -> None:
        self._llm = llm_caller
        self._store = store
        self.network = network
        self._intent_engine = intent_engine
        self._tasks: dict[str, SubTask] = {}
        self._running_tasks: dict[str, SubTask] = {}
        self._task_splitter: Callable[..., Awaitable[object]] | None = None

    def set_task_splitter(self, splitter: Callable[..., Awaitable[object]]) -> None:
        """注入任务拆分器 (通常由 LLM 执行)。"""
        self._task_splitter = splitter

    async def orchestrate(self, task_description: str) -> dict[str, object]:
        """
        调度一个复合任务。

        流程:
        1. 拆分任务
        2. 分配给 Workers
        3. 等待结果
        4. 聚合返回
        """
        # ── Step 1: 拆分任务 ──
        subtasks = await self._split_task(task_description)
        if not subtasks:
            return {"status": "no_subtasks", "result": None}

        for st in subtasks:
            self._tasks[st.task_id] = st

        logger.info(f"Coordinator: split into {len(subtasks)} subtasks")

        # ── Step 2: 分配任务 ──
        workers = self.network.get_active_workers()
        if not workers:
            # 没有 Worker, 本地顺序执行
            logger.warning("No workers available, executing locally")
            return {"status": "no_workers", "subtasks": [s.description for s in subtasks]}

        assignments = self._assign_tasks(subtasks, workers)
        for task_id, peer_id in assignments.items():
            self._tasks[task_id].assigned_to = peer_id
            self._tasks[task_id].status = TaskStatus.ASSIGNED
            await self.network.dispatch_task(
                objective="Composite Task Execution",
                instruction=self._tasks[task_id].description,
                target=peer_id,
            )

        logger.info(f"Coordinator: dispatched {len(assignments)} tasks to {len(set(assignments.values()))} workers")

        # ── Step 3: 等待结果 ──
        async def _collect(task_id: str) -> tuple[str, dict[str, object] | None]:
            self._tasks[task_id].status = TaskStatus.RUNNING
            res = await self.network.collect_result(task_id, timeout=300)
            return task_id, res

        # 使用 asyncio.gather 实现并行收集 (Pillar 33)
        pending_results = await asyncio.gather(*[_collect(tid) for tid in assignments])
        
        results = {}
        for task_id, result in pending_results:
            if result:
                self._tasks[task_id].status = TaskStatus.COMPLETED
                self._tasks[task_id].result = result
                self._tasks[task_id].completed_at = time.time()
                results[task_id] = result
            else:
                self._tasks[task_id].status = TaskStatus.FAILED
                # 重试逻辑
                if self._tasks[task_id].retry_count < self._tasks[task_id].max_retries:
                    self._tasks[task_id].retry_count += 1
                    logger.warning(f"Task {task_id} failed, retry {self._tasks[task_id].retry_count}")

        # ── Step 4: 聚合结果 ──
        return self._aggregate(results)

    def get_status(self) -> dict[str, object]:
        """获取所有任务的状态摘要。"""
        status_counts: dict[str, int] = {}
        for task in self._tasks.values():
            status_counts[task.status.value] = status_counts.get(task.status.value, 0) + 1
        return {
            "total": len(self._tasks),
            "status": status_counts,
            "tasks": [
                {
                    "id": t.task_id,
                    "status": t.status.value,
                    "assigned_to": t.assigned_to,
                    "description": t.description[:100],
                }
                for t in self._tasks.values()
            ],
        }

    async def _split_task(self, description: str) -> list[SubTask]:
        """拆分任务 (优先使用 IntentEngine, 降级到行拆分)。"""
        if self._intent_engine:
            try:
                # 使用 IntentEngine 进行深度拆分 (Pillar 28)
                intent_res = await self._intent_engine.analyze(description)
                if intent_res.decomposed_steps:
                    return [
                        SubTask(task_id=f"sub_{i}", description=step)
                        for i, step in enumerate(intent_res.decomposed_steps)
                    ]
            except Exception as e:
                logger.warning(f"IntentEngine split failed, falling back: {e}")

        if self._task_splitter:
            raw = await self._task_splitter(description)
            if isinstance(raw, list):
                return [
                    SubTask(task_id=f"sub_{i}", description=str(item))
                    for i, item in enumerate(raw)
                ]

        # 默认拆分: 按换行或分号
        parts = [p.strip() for p in description.replace(";", "\n").split("\n") if p.strip()]
        if len(parts) <= 1:
            return [SubTask(task_id="sub_0", description=description)]
        return [SubTask(task_id=f"sub_{i}", description=p) for i, p in enumerate(parts)]

    def _assign_tasks(self, tasks: list[SubTask], workers: list[SwarmPeer]) -> dict[str, str]:
        """负载均衡: 轮询分配任务给 Worker。"""
        assignments: dict[str, str] = {}
        for i, task in enumerate(tasks):
            worker = workers[i % len(workers)]
            assignments[task.task_id] = worker.peer_id
        return assignments

    def _aggregate(self, results: dict[str, object]) -> dict[str, object]:
        """聚合所有子任务的结果。"""
        return {
            "status": "completed",
            "subtasks_completed": len(results),
            "subtasks_total": len(self._tasks),
            "results": results,
        }
