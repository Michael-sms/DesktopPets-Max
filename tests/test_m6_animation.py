import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageChops, ImageStat
from PySide6.QtWidgets import QApplication

from desktoppet.app import PetWindow
from desktoppet.manifest import load_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
M6_MANIFEST = PROJECT_ROOT / "assets" / "pets" / "m6_sample" / "manifest.json"


class M6AnimationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.manifest = load_manifest(M6_MANIFEST)

    def test_dynamic_pack_has_main_transitions_and_random_idle(self) -> None:
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
            "idle_variant_look",
        }
        self.assertEqual(set(self.manifest.animations), expected)
        for state in ("idle", "hover", "loading", "working"):
            self.assertEqual(len(self.manifest.animations[state].frames), 12)
        self.assertEqual(len(self.manifest.animations["idle_variant_look"].frames), 10)
        self.assertEqual(
            sum(len(item.frames) for item in self.manifest.animations.values()), 88
        )

    def test_each_state_contains_real_pose_changes(self) -> None:
        for state in ("idle", "hover", "loading", "working"):
            animation = self.manifest.animations[state]
            with Image.open(animation.frames[0].file) as first_opened:
                first = first_opened.convert("RGBA")
            with Image.open(animation.frames[4].file) as changed_opened:
                changed = changed_opened.convert("RGBA")
            difference = ImageChops.difference(first, changed)
            mean = sum(ImageStat.Stat(difference).mean) / 4
            self.assertGreater(mean, 3.0, state)

    def test_all_frames_are_transparent_and_grounded(self) -> None:
        for name, animation in self.manifest.animations.items():
            bottoms: list[int] = []
            for frame in animation.frames:
                with Image.open(frame.file) as opened:
                    image = opened.convert("RGBA")
                self.assertEqual(image.size, (512, 512), name)
                self.assertEqual(image.getchannel("A").getextrema()[0], 0, name)
                box = image.getchannel("A").getbbox()
                self.assertIsNotNone(box, name)
                assert box is not None
                visible_pixels = sum(
                    alpha > 0 for alpha in image.getchannel("A").get_flattened_data()
                )
                box_area = (box[2] - box[0]) * (box[3] - box[1])
                self.assertLess(visible_pixels, 110_000, name)
                self.assertLess(box_area, 190_000, name)
                bottoms.append(box[3])
            if name in {"idle", "hover", "loading", "working"}:
                self.assertLessEqual(max(bottoms) - min(bottoms), 2, name)

    def test_random_idle_clip_returns_to_idle_loop(self) -> None:
        window = PetWindow(self.manifest)
        try:
            window._idle_variant_timer.stop()
            window._play_idle_variant()
            self.assertEqual(window.active_animation_name, "idle_variant_look")
            for _ in range(24):
                window._tick()
            self.assertEqual(window.active_animation_name, "idle")
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
