"""Performance sampling and long-running M5 acceptance reports."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer

from .state_machine import PetState


@dataclass(frozen=True)
class RuntimeSample:
    elapsed_seconds: float
    rss_bytes: int
    cpu_percent: float
    state: str


class SoakMonitor(QObject):
    """Sample process health without adding third-party runtime dependencies."""

    def __init__(
        self,
        window: object,
        *,
        duration_seconds: float,
        report_path: str | Path,
        finished: Callable[[], None],
    ) -> None:
        super().__init__(window)
        self.window = window
        self.duration_seconds = max(0.2, duration_seconds)
        self.report_path = Path(report_path)
        self.finished_callback = finished
        self.samples: list[RuntimeSample] = []
        self._started = time.monotonic()
        self._last_wall = self._started
        self._last_cpu = time.process_time()
        self._response_times_ms: list[float] = []
        self._cycle_index = 0
        self._finished = False

        sample_interval = max(100, min(10_000, round(self.duration_seconds * 100)))
        self._sample_timer = QTimer(self)
        self._sample_timer.timeout.connect(self._sample)
        self._sample_timer.start(sample_interval)
        self._cycle_timer = QTimer(self)
        self._cycle_timer.timeout.connect(self._cycle_state)
        self._cycle_timer.start(max(100, min(1_800, round(self.duration_seconds * 200))))
        self._sample()
        QTimer.singleShot(round(self.duration_seconds * 1000), self.finish)

    def _cycle_state(self) -> None:
        states = (PetState.HOVER, PetState.IDLE, PetState.LOADING, PetState.WORKING, PetState.IDLE)
        target = states[self._cycle_index % len(states)]
        self._cycle_index += 1
        started = time.perf_counter()
        self.window.machine.force(target)
        self._response_times_ms.append((time.perf_counter() - started) * 1000)

    def _sample(self) -> None:
        now = time.monotonic()
        cpu_now = time.process_time()
        wall_delta = max(1e-6, now - self._last_wall)
        cpu_percent = (cpu_now - self._last_cpu) / wall_delta * 100 / max(1, os.cpu_count() or 1)
        self.samples.append(
            RuntimeSample(now - self._started, process_rss_bytes(), cpu_percent, self.window.machine.state.value)
        )
        self._last_wall = now
        self._last_cpu = cpu_now

    def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        self._sample_timer.stop()
        self._cycle_timer.stop()
        self._sample()
        rss_values = [item.rss_bytes for item in self.samples]
        cpu_values = [item.cpu_percent for item in self.samples[1:]]
        initial_rss = rss_values[0] if rss_values else 0
        peak_rss = max(rss_values, default=0)
        final_rss = rss_values[-1] if rss_values else 0
        response_max = max(self._response_times_ms, default=0.0)
        average_cpu = sum(cpu_values) / len(cpu_values) if cpu_values else 0.0
        checks = {
            "state_response_under_150ms": response_max <= 150,
            "rss_sampling_available": initial_rss > 0,
            "rss_growth_under_32mb": final_rss - initial_rss <= 32 * 1024 * 1024,
            "average_cpu_under_15_percent": average_cpu <= 15,
        }
        payload = {
            "schema_version": 1,
            "duration_seconds": time.monotonic() - self._started,
            "platform": sys.platform,
            "manifest": str(self.window.manifest.root / "manifest.json"),
            "animation_count": len(self.window.manifest.animations),
            "preloaded_frame_count": sum(len(item.frames) for item in self.window.manifest.animations.values()),
            "render_interval_ms": self.window.render_interval_ms,
            "state_response_max_ms": response_max,
            "initial_rss_bytes": initial_rss,
            "final_rss_bytes": final_rss,
            "peak_rss_bytes": peak_rss,
            "average_cpu_percent": average_cpu,
            "checks": checks,
            "passed": all(checks.values()),
            "samples": [asdict(item) for item in self.samples],
        }
        try:
            self.report_path.parent.mkdir(parents=True, exist_ok=True)
            self.report_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        finally:
            self.finished_callback()


def process_rss_bytes() -> int:
    if sys.platform == "win32":
        return _windows_rss_bytes()
    try:
        import resource

        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value if sys.platform == "darwin" else value * 1024)
    except (ImportError, OSError):
        return 0


def _windows_rss_bytes() -> int:
    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = (
            ctypes.wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            ctypes.wintypes.DWORD,
        )
        psapi.GetProcessMemoryInfo.restype = ctypes.wintypes.BOOL
        handle = kernel32.GetCurrentProcess()
        success = psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        )
        return int(counters.WorkingSetSize) if success else 0
    except (AttributeError, OSError):
        return 0
