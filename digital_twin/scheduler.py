"""
Part 3's periodic snapshot scheduler: "run this on a 5-minute scheduler
(configurable interval)." A plain background thread, not an external task
queue -- appropriate for this subsystem's scale, and swappable later.

Each tick opens its own SQLite connection via connection_factory, since
sqlite3 connections aren't safe to share across threads.
"""

import threading
from typing import Callable

from digital_twin.twin_service import DigitalTwinService

DEFAULT_INTERVAL_SECONDS = 5 * 60


class SnapshotScheduler:
    def __init__(self, campus_id: str, connection_factory: Callable,
                 interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
                 twin_service: DigitalTwinService = None):
        self.campus_id = campus_id
        self.connection_factory = connection_factory
        self.interval_seconds = interval_seconds
        self.twin_service = twin_service or DigitalTwinService()
        self._timer: threading.Timer = None
        self._running = False
        self.snapshot_count = 0

    def start(self):
        if self._running:
            return
        self._running = True
        self._schedule_next()

    def _schedule_next(self):
        if not self._running:
            return
        self._timer = threading.Timer(self.interval_seconds, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def _tick(self):
        conn = self.connection_factory()
        try:
            self.twin_service.snapshot_now(self.campus_id, conn)
            self.snapshot_count += 1
        finally:
            conn.close()
        self._schedule_next()

    def stop(self):
        self._running = False
        if self._timer:
            self._timer.cancel()

    def run_once_now(self):
        """Triggers an immediate snapshot outside the schedule -- used by
        tests so they don't have to wait for a real interval to elapse."""
        conn = self.connection_factory()
        try:
            self.twin_service.snapshot_now(self.campus_id, conn)
            self.snapshot_count += 1
        finally:
            conn.close()
