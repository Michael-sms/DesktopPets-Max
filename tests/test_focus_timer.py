import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from desktoppet.app import DEFAULT_MANIFEST, PetWindow
from desktoppet.focus_timer import ReliableTimer, TimerStatus
from desktoppet.manifest import load_manifest


class ReliableTimerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = [1_700_000_000.0]
        self.clock = lambda: self.now[0]

    def test_deadline_survives_delayed_ticks_pause_and_resume(self) -> None:
        timer = ReliableTimer(clock=self.clock)
        timer.start(120)
        self.now[0] += 31
        self.assertEqual(timer.remaining_seconds, 89)

        self.assertTrue(timer.pause())
        self.now[0] += 600
        self.assertEqual(timer.remaining_seconds, 89)
        self.assertEqual(timer.status, TimerStatus.PAUSED)

        self.assertTrue(timer.resume())
        self.now[0] += 90
        self.assertTrue(timer.refresh())
        self.assertEqual(timer.status, TimerStatus.FINISHED)
        self.assertEqual(timer.display_text(), "专注完成 · 时间到")

    def test_running_timer_restores_from_disk_and_reconciles_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "focus_timer.json"
            ReliableTimer(path, clock=self.clock).start(75)
            self.now[0] += 20

            restored = ReliableTimer(path, clock=self.clock)
            self.assertEqual(restored.status, TimerStatus.RUNNING)
            self.assertEqual(restored.remaining_seconds, 55)
            self.now[0] += 60

            expired = ReliableTimer(path, clock=self.clock)
            self.assertEqual(expired.status, TimerStatus.FINISHED)
            self.assertEqual(expired.remaining_seconds, 0)

    def test_stop_clears_visible_timer_state(self) -> None:
        timer = ReliableTimer(clock=self.clock)
        timer.start(60)
        timer.stop()
        self.assertEqual(timer.status, TimerStatus.IDLE)
        self.assertEqual(timer.display_text(), "")


class VisibleFocusTimerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.manifest = load_manifest(DEFAULT_MANIFEST)

    def test_pet_window_exposes_explicit_countdown(self) -> None:
        now = [1_700_000_000.0]
        timer = ReliableTimer(clock=lambda: now[0])
        timer.start(65)
        window = PetWindow(self.manifest, focus_timer=timer)
        try:
            self.assertEqual(window.timer_display_text, "专注 01:05")
            window._pause_focus_timer()
            self.assertEqual(window.timer_display_text, "专注 01:05 · 已暂停")
            window._stop_focus_timer()
            self.assertEqual(window.timer_display_text, "")
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
