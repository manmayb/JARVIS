import asyncio
import time
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from core.logging import get_logger
from core.config import settings
from models.database import get_db
from orchestration.react_loop import run_orchestrated
from core.schemas import TaskRequest
from autonomy.goal_store import get_overdue_goals, update_progress

log = get_logger(__name__)

async def init_scheduler_log():
    db = await get_db()
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS scheduler_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            job_label    TEXT NOT NULL,
            triggered_at TEXT NOT NULL DEFAULT (datetime('now')),
            status       TEXT NOT NULL,
            output_summary TEXT
        );
    """)
    await db.commit()

class JARVISScheduler:
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        self._scheduler = AsyncIOScheduler()
        self._db_initialized = False

    async def start(self):
        await init_scheduler_log()
        self._db_initialized = True
        
        # Register built-in jobs
        # 1. Morning Brief at 08:00
        self._scheduler.add_job(
            self.morning_brief,
            CronTrigger(hour=8, minute=0),
            id="morning_brief",
            replace_existing=True
        )
        
        # 2. Goal check every 2 hours
        self._scheduler.add_job(
            self.check_goals,
            IntervalTrigger(hours=2),
            id="goal_check",
            replace_existing=True
        )
        
        # 3. Memory Consolidation at 02:00
        self._scheduler.add_job(
            self.memory_consolidation,
            CronTrigger(hour=2, minute=0),
            id="memory_consolidation",
            replace_existing=True
        )
        
        self._scheduler.start()
        self.logger.info("scheduler.started", jobs=len(self._scheduler.get_jobs()))

    async def shutdown(self):
        self._scheduler.shutdown()
        self.logger.info("scheduler.shutdown")

    async def _log_run(self, label: str, status: str, output: str):
        try:
            db = await get_db()
            await db.execute(
                "INSERT INTO scheduler_log (job_label, status, output_summary) VALUES (?, ?, ?)",
                (label, status, output[:500])
            )
            await db.commit()
        except Exception as e:
            self.logger.error("scheduler.log_failed", error=str(e))

    async def morning_brief(self):
        """Generate and dispatch daily summary."""
        self.logger.info("scheduler.job.morning_brief.start")
        try:
            req = TaskRequest(
                user_input="Generate my morning brief: summarise today's calendar events, any unread emails flagged important, and my active goals.",
                session_id="system_brief",
                user_id="default_user",
                trace_id=f"sched_brief_{int(time.time())}"
            )
            # Result is handled by orchestrator (Communicator Agent will handle Slack if logic exists)
            result = await run_orchestrated(req, [], time.monotonic())
            await self._log_run("morning_brief", "success", result.answer)
        except Exception as e:
            self.logger.error("scheduler.job.morning_brief.failed", error=str(e))
            await self._log_run("morning_brief", "failed", str(e))

    async def check_goals(self):
        """Proactively monitor goal deadlines."""
        self.logger.info("scheduler.job.goal_check.start")
        try:
            overdue = await get_overdue_goals()
            for goal in overdue:
                desc = goal["description"]
                req = TaskRequest(
                    user_input=f"The goal '{desc}' is overdue. Check if it can be completed now or suggest rescheduling.",
                    session_id="system_goal_check",
                    user_id="default_user",
                    trace_id=f"sched_goal_{goal['id'][:8]}"
                )
                result = await run_orchestrated(req, [], time.monotonic())
                await update_progress(goal["id"], f"System Check: {result.answer[:200]}")
            
            await self._log_run("goal_check", "success", f"Processed {len(overdue)} goals")
        except Exception as e:
            self.logger.error("scheduler.job.goal_check.failed", error=str(e))
            await self._log_run("goal_check", "failed", str(e))

    async def memory_consolidation(self):
        """Deduplicate and refine semantic memory."""
        self.logger.info("scheduler.job.memory_consolidation.start")
        try:
            # Placeholder for complex consolidation logic
            # retrieve recent facts -> semantic_extractor.consolidate() -> purge duplicates
            await self._log_run("memory_consolidation", "success", "Consolidation logic stub executed")
        except Exception as e:
            self.logger.error("scheduler.job.memory_consolidation.failed", error=str(e))
            await self._log_run("memory_consolidation", "failed", str(e))

    # API Helpers
    def list_jobs(self):
        return [
            {"id": j.id, "next_run": j.next_run_time.isoformat() if j.next_run_time else None}
            for j in self._scheduler.get_jobs()
        ]

scheduler = JARVISScheduler()
