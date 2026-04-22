"""
Coda V4.0 — Maintenance Daemon
负责后台定期任务: 过期检查、提醒扫描、以及系统健康巡检。
"""

import asyncio
import logging
import os
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from dotenv import load_dotenv

import sys

if TYPE_CHECKING:
    from surrealdb import Surreal as AsyncSurreal

# 确保工程根目录在 path 中，防止 ModuleNotFoundError
# 加载 .env (优先使用工程根目录下的 .env)
file_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(file_dir)
ENV_FILE = os.path.join(project_root, ".env")

if os.path.exists(ENV_FILE):
    _ = load_dotenv(ENV_FILE)
else:
    # 兼容回退
    _ = load_dotenv()

if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    from engine.skills.query_reminder.scripts.query_logic import query_reminders
except ImportError:
    # 兼容直接从 engine/ 运行
    sys.path.insert(0, os.path.dirname(project_root))
    from engine.skills.query_reminder.scripts.query_logic import query_reminders

logger = logging.getLogger("Coda.maintenance")

class MaintenanceDaemon:
    """
    后台维护守护进程。
    
    定期运行: 
    1. 自动过期处理 (UPDATE tasks/schedules)
    2. 多阶段提醒扫描 (SELECT reminders)
    3. 系统心跳更新
    """

    db_url: str
    interval: int
    _stop_event: asyncio.Event
    _last_run: datetime | None
    _run_count: int

    def __init__(self, db_url: str, interval_seconds: int = 3600):
        self.db_url = db_url
        self.interval = interval_seconds
        self._stop_event = asyncio.Event()
        self._last_run = None
        self._run_count = 0

    @classmethod
    def from_env(cls, interval_seconds: int = 3600):
        """从环境变量创建实例。"""
        db_url = os.getenv("SURREALDB_URL", "ws://127.0.0.1:11001/rpc")
        return cls(db_url, interval_seconds)

    async def start(self):
        """启动后台循环。"""
        logger.info(f"MaintenanceDaemon: Starting with interval {self.interval}s")
        while not self._stop_event.is_set():
            try:
                await self._perform_maintenance()
                self._last_run = datetime.now()
                self._run_count += 1
            except Exception as e:
                logger.error(f"MaintenanceDaemon Error: {e}")
            
            # 等待下次运行或停止信号
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                continue

    async def stop(self):
        """停止后台循环。"""
        logger.info("MaintenanceDaemon: Stopping...")
        self._stop_event.set()

    async def _perform_maintenance(self):
        """执行具体的维护任务。"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"MaintenanceDaemon Ticking at {now_str}")
        
        # 1. 运行提醒与过期逻辑 (复用 query_reminder 技能的代码)
        # 该函数内部会执行 UPDATE ... SET status = 'expired'
        report = await query_reminders(url=self.db_url)
        
        if report.errors:
            logger.warning(f"MaintenanceDaemon Trace: {report.errors}")
        else:
            logger.info(f"MaintenanceDaemon Scan: Found {report.total_items} active items")
            if report.recently_expired:
                logger.info(f"MaintenanceDaemon Expiry: Cleaned {len(report.recently_expired)} items")

    @property
    def status(self) -> dict[str, object]:
        """获取守护进程状态。"""
        return {
            "active": not self._stop_event.is_set(),
            "interval": self.interval,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "run_count": self._run_count
        }

if __name__ == "__main__":
    # 允许独立测试
    logging.basicConfig(level=logging.INFO)
    db_url = os.getenv("SURREALDB_URL", "ws://127.0.0.1:11001/rpc")
    daemon = MaintenanceDaemon(db_url, interval_seconds=10)
    asyncio.run(daemon.start())
