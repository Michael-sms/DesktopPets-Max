import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from desktoppet.app import PetWindow
from desktoppet.manifest import load_manifest
from desktoppet.state_machine import PetState


PROJECT_ROOT = Path(__file__).resolve().parents[1]
M3_MANIFEST = PROJECT_ROOT / "assets" / "pets" / "m3_sample" / "manifest.json"


class M3MotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.manifest = load_manifest(M3_MANIFEST)

    def test_complete_action_and_transition_set(self) -> None:
        expected = {
            "idle",
            "hover",
            "loading",
            "working",
            "idle_to_hover",
            "hover_to_idle",
            "idle_to_loading",
            "loading_to_working",
            "working_to_idle",
        }
        self.assertEqual(set(self.manifest.animations), expected)
        self.assertEqual(len(self.manifest.animations["idle"].frames), 12)
        self.assertEqual(len(self.manifest.animations["hover"].frames), 12)
        self.assertEqual(len(self.manifest.animations["loading"].frames), 16)
        self.assertEqual(len(self.manifest.animations["working"].frames), 12)
        for name in expected - {"idle", "hover", "loading", "working"}:
            self.assertFalse(self.manifest.animations[name].loop)
            self.assertEqual(len(self.manifest.animations[name].frames), 6)

    def test_all_frames_are_transparent_and_anchor_is_stable(self) -> None:
        for name, animation in self.manifest.animations.items():
            bottoms: list[int] = []
            for frame in animation.frames:
                with Image.open(frame.file) as opened:
                    image = opened.convert("RGBA")
                self.assertEqual(image.size, (512, 512), name)
                self.assertEqual(image.getchannel("A").getextrema()[0], 0, name)
                box = image.getchannel("A").getbbox()
                self.assertIsNotNone(box, name)
                bottoms.append(box[3])
            if name in {"idle", "hover", "loading", "working"}:
                self.assertLessEqual(max(bottoms) - min(bottoms), 2, name)

    def test_player_uses_and_finishes_non_looping_transition(self) -> None:
        window = PetWindow(self.manifest)
        try:
            window.machine.force(PetState.HOVER)
            self.assertEqual(window.active_animation_name, "idle_to_hover")
            for _ in range(18):
                window._tick()
            self.assertEqual(window.active_animation_name, "hover")
        finally:
            window.close()

    def test_new_busy_state_replaces_active_transition(self) -> None:
        window = PetWindow(self.manifest)
        try:
            window.machine.force(PetState.LOADING)
            self.assertEqual(window.active_animation_name, "idle_to_loading")
            window.machine.force(PetState.WORKING)
            self.assertEqual(window.active_animation_name, "loading_to_working")
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
