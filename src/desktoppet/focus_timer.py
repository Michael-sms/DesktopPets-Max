"""Deadline-based, restart-safe focus timer state."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable


class TimerStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"


@dataclass(frozen=True)
class TimerSnapshot:
    status: TimerStatus = TimerStatus.IDLE
    label: str = "专注"
    duration_seconds: int = 0
    deadline: float | None = None
    paused_remaining: float = 0.0


class ReliableTimer:
    """Persist a deadline instead of trusting UI timer tick counts."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(path).resolve() if path is not None else None
        self._clock = clock
        self._snapshot = self._load()
        self.refresh()

    @property
    def snapshot(self) -> TimerSnapshot:
        return self._snapshot

    @property
    def status(self) -> TimerStatus:
        return self._snapshot.status

    @property
    def remaining_seconds(self) -> int:
        if self.status is TimerStatus.RUNNING and self._snapshot.deadline is not None:
            return max(0, math.ceil(self._snapshot.deadline - self._clock()))
        if self.status is TimerStatus.PAUSED:
            return max(0, math.ceil(self._snapshot.paused_remaining))
        return 0

    def start(self, duration_seconds: int, *, label: str = "专注") -> None:
        if duration_seconds <= 0:
            raise ValueError("timer duration must be positive")
        self._snapshot = TimerSnapshot(
            status=TimerStatus.RUNNING,
            label=label.strip() or "专注",
            duration_seconds=int(duration_seconds),
            deadline=self._clock() + int(duration_seconds),
        )
        self._save()

    def pause(self) -> bool:
        if self.status is not TimerStatus.RUNNING:
            return False
        assert self._snapshot.deadline is not None
        remaining = max(0.0, self._snapshot.deadline - self._clock())
        if remaining <= 0:
            self._finish()
            return False
        self._snapshot = TimerSnapshot(
            status=TimerStatus.PAUSED,
            label=self._snapshot.label,
            duration_seconds=self._snapshot.duration_seconds,
            paused_remaining=remaining,
        )
        self._save()
        return True

    def resume(self) -> bool:
        if self.status is not TimerStatus.PAUSED:
            return False
        remaining = self._snapshot.paused_remaining
        if remaining <= 0:
            self._finish()
            return False
        self._snapshot = TimerSnapshot(
            status=TimerStatus.RUNNING,
            label=self._snapshot.label,
            duration_seconds=self._snapshot.duration_seconds,
            deadline=self._clock() + remaining,
        )
        self._save()
        return True

    def stop(self) -> None:
        self._snapshot = TimerSnapshot()
        self._save()

    def refresh(self) -> bool:
        """Reconcile with wall time and return whether visible state changed."""

        if (
            self.status is TimerStatus.RUNNING
            and self._snapshot.deadline is not None
            and self._snapshot.deadline <= self._clock()
        ):
            self._finish()
            return True
        return False

    def display_text(self) -> str:
        if self.status is TimerStatus.IDLE:
            return ""
        if self.status is TimerStatus.FINISHED:
            return f"{self._snapshot.label}完成 · 时间到"
        minutes, seconds = divmod(self.remaining_seconds, 60)
        suffix = " · 已暂停" if self.status is TimerStatus.PAUSED else ""
        return f"{self._snapshot.label} {minutes:02d}:{seconds:02d}{suffix}"

    def _finish(self) -> None:
        self._snapshot = TimerSnapshot(
            status=TimerStatus.FINISHED,
            label=self._snapshot.label,
            duration_seconds=self._snapshot.duration_seconds,
        )
        self._save()

    def _load(self) -> TimerSnapshot:
        if self.path is None or not self.path.is_file():
            return TimerSnapshot()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("schema_version") != 1:
                return TimerSnapshot()
            status = TimerStatus(data.get("status", TimerStatus.IDLE.value))
            label = data.get("label") if isinstance(data.get("label"), str) else "专注"
            duration = int(data.get("duration_seconds", 0))
            deadline_value = data.get("deadline")
            deadline = float(deadline_value) if isinstance(deadline_value, (int, float)) else None
            paused_value = data.get("paused_remaining", 0.0)
            paused = float(paused_value) if isinstance(paused_value, (int, float)) else 0.0
            if status is TimerStatus.RUNNING and deadline is None:
                return TimerSnapshot()
            return TimerSnapshot(status, label, max(0, duration), deadline, max(0.0, paused))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return TimerSnapshot()

    def _save(self) -> None:
        if self.path is None:
            return
        payload = {
            "schema_version": 1,
            "status": self._snapshot.status.value,
            "label": self._snapshot.label,
            "duration_seconds": self._snapshot.duration_seconds,
            "deadline": self._snapshot.deadline,
            "paused_remaining": self._snapshot.paused_remaining,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(self.path)
        except OSError:
            return
