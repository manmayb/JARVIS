import asyncio
import time
from typing import Optional
from core.logging import get_logger
from core.config import settings
from core.schemas import TaskRequest
from orchestration.react_loop import run_orchestrated

log = get_logger(__name__)

class EventWatcher:
    """Monitors external signals (Gmail, Filesystem) for proactive triggers."""

    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._last_gmail_poll = 0

    async def start(self):
        self._running = True
        # Start Gmail polling task
        self._tasks.append(asyncio.create_task(self._gmail_poller()))
        
        # Start File watcher if configured
        file_path = getattr(settings, "file_watch_path", None)
        if file_path:
            self._tasks.append(asyncio.create_task(self._file_poller(file_path)))
            
        self.logger.info("event_watcher.started")

    async def stop(self):
        self._running = False
        for task in self._tasks:
            task.cancel()
        self.logger.info("event_watcher.stopped")

    async def _gmail_poller(self):
        """Poll Gmail for JARVIS-directed messages."""
        interval = getattr(settings, "gmail_watch_interval_sec", 120)
        # Enforce safety minimum
        interval = max(60, interval)
        
        while self._running:
            now = time.monotonic()
            if now - self._last_gmail_poll >= interval:
                self._last_gmail_poll = now
                self.logger.info("event_watcher.gmail.poll")
                try:
                    # Request the orchestrator to check for new JARVIS-tagged emails
                    req = TaskRequest(
                        user_input="Check for unread emails with label 'JARVIS' or subject '[JARVIS]'. Summarise any important ones.",
                        session_id="system_event_gmail",
                        user_id="default_user",
                        trace_id=f"watch_gmail_{int(now)}"
                    )
                    await run_orchestrated(req, [], time.monotonic())
                except Exception as e:
                    self.logger.error("event_watcher.gmail.failed", error=str(e))
            
            await asyncio.sleep(10) # Small sleep to check stop signal

    async def _file_poller(self, path: str):
        """Monitor a directory for new file additions."""
        self.logger.info("event_watcher.file.monitoring", path=path)
        # Using a simple polling-based watcher or watchdog integration
        # For this MVP, we stub the detection
        while self._running:
            await asyncio.sleep(60)
            # In real implementation, use watchdog.observers.Observer

    async def handle_webhook(self, payload: dict):
        """Entry point for externally pushed events."""
        self.logger.info("event_watcher.webhook.received")
        try:
            task_desc = payload.get("task", str(payload))
            req = TaskRequest(
                user_input=f"External Webhook Trigger: {task_desc}",
                session_id="system_event_webhook",
                user_id="default_user",
                trace_id=f"webhook_{int(time.time())}"
            )
            return await run_orchestrated(req, [], time.monotonic())
        except Exception as e:
            self.logger.error("event_watcher.webhook.failed", error=str(e))

event_watcher = EventWatcher()
