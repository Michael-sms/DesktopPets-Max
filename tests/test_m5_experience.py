import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QPoint
from PySide6.QtWidgets import QApplication

from desktoppet.acceptance import SoakMonitor, process_rss_bytes
from desktoppet.app import (
    DEFAULT_MANIFEST,
    RENDER_INTERVAL_MS,
    PetWindow,
    load_runtime_manifest,
    main,
)
from desktoppet.manifest import ManifestError, load_manifest
from desktoppet.settings import AppSettings, SettingsStore, relative_position, restored_position
from desktoppet.state_machine import PetState


class M5ExperienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.manifest = load_manifest(DEFAULT_MANIFEST)

    def test_hitbox_maps_to_stable_interactive_window_region(self) -> None:
        window = PetWindow(self.manifest)
        try:
            hitbox = window.interactive_rect()
            self.assertTrue(window._is_interactive_position(hitbox.center()))
            self.assertFalse(window._is_interactive_position(QPoint(0, 0)))
            window.machine.force(PetState.WORKING)
            self.assertEqual(window.interactive_rect(), hitbox)
        finally:
            window.close()

    def test_native_physical_pixels_map_into_hitbox_at_scaled_dpi(self) -> None:
        window = PetWindow(self.manifest)
        try:
            # A 280x280 logical window occupies 420x420 native pixels at 150% DPI.
            self.assertTrue(
                window._is_interactive_client_position(QPoint(210, 210), (420, 420))
            )
            self.assertFalse(
                window._is_interactive_client_position(QPoint(2, 2), (420, 420))
            )
        finally:
            window.close()

    def test_all_five_transitions_can_be_previewed_directly(self) -> None:
        window = PetWindow(self.manifest)
        try:
            transitions = {
                "idle_to_hover",
                "hover_to_idle",
                "idle_to_loading",
                "loading_to_working",
                "working_to_idle",
            }
            for name in transitions:
                window._preview_animation(name)
                self.assertEqual(window.active_animation_name, name)
        finally:
            window.close()

    def test_runtime_render_rate_is_not_an_idle_high_frequency_loop(self) -> None:
        window = PetWindow(self.manifest)
        try:
            self.assertEqual(window.render_interval_ms, RENDER_INTERVAL_MS)
            self.assertGreaterEqual(window.render_interval_ms, 42)
            self.assertLessEqual(window.render_interval_ms, 84)
            expected_frames = sum(len(item.frames) for item in self.manifest.animations.values())
            loaded_frames = sum(len(item) for item in window._pixmaps.values())
            self.assertEqual(loaded_frames, expected_frames)
        finally:
            window.close()

    def test_missing_custom_manifest_falls_back_but_strict_validation_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing" / "manifest.json"
            manifest, warning = load_runtime_manifest(missing)
            self.assertEqual(manifest.pet_id, self.manifest.pet_id)
            self.assertIn("回退", warning or "")
            with self.assertRaises(ManifestError):
                load_manifest(missing)

    def test_corrupt_custom_frame_falls_back_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bad_frame = root / "bad.png"
            bad_frame.write_text("not an image", encoding="utf-8")
            animations = {
                state: {
                    "loop": True,
                    "interruptible_frames": [0],
                    "frames": [{"file": "bad.png", "duration_ms": 100}],
                }
                for state in ("idle", "hover", "loading", "working")
            }
            manifest = {
                "schema_version": 1,
                "pet_id": "broken-pet",
                "name": "Broken Pet",
                "canvas": [512, 512],
                "display_size": [280, 280],
                "anchor": [256, 492],
                "hitbox": [46, 24, 420, 468],
                "animations": animations,
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(main(["--manifest", str(manifest_path), "--smoke-test"]), 0)

    def test_settings_round_trip_and_cross_screen_relative_restore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory) / "settings.json")
            expected = AppSettings(
                always_on_top=False,
                debug_badge=True,
                screen_name="Display-2",
                relative_x=0.25,
                relative_y=0.75,
            )
            store.save(expected)
            self.assertEqual(store.load(), expected)

            relative = relative_position((1250, 200), (280, 280), (1000, 0, 1920, 1080))
            position = restored_position(relative, (280, 280), (-1600, 100, 1600, 900))
            self.assertGreaterEqual(position[0], -1600)
            self.assertLessEqual(position[0] + 280, 0)
            self.assertGreaterEqual(position[1], 100)
            self.assertLessEqual(position[1] + 280, 1000)

    def test_short_soak_writes_machine_readable_health_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "soak.json"
            window = PetWindow(self.manifest)
            window.show()
            loop = QEventLoop()
            monitor = SoakMonitor(
                window,
                duration_seconds=0.35,
                report_path=report_path,
                finished=loop.quit,
            )
            loop.exec()
            del monitor
            window.close()

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(report["passed"])
            self.assertEqual(report["preloaded_frame_count"], 82)
            self.assertLessEqual(report["state_response_max_ms"], 150)
            self.assertGreaterEqual(len(report["samples"]), 2)
            self.assertGreater(process_rss_bytes(), 0)


if __name__ == "__main__":
    unittest.main()
