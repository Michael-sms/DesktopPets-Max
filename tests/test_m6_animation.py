import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageChops, ImageDraw, ImageStat
from PySide6.QtWidgets import QApplication

from desktoppet.app import PetWindow
from desktoppet.frame_animation import _remove_connected_background
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

    def test_faux_checkerboard_touching_character_is_removed(self) -> None:
        image = Image.new("RGBA", (128, 128), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        tile = 12
        for y in range(0, 128, tile):
            for x in range(0, 128, tile):
                shade = 244 if (x // tile + y // tile) % 2 else 254
                draw.rectangle((x, y, x + tile - 1, y + tile - 1), fill=(shade,) * 3 + (255,))
        draw.line((0, 60, 127, 60), fill=(220, 220, 220, 255), width=1)
        draw.line((64, 0, 64, 127), fill=(220, 220, 220, 255), width=1)
        # Coloured body and legs deliberately touch a broad white shoe highlight.
        draw.rounded_rectangle((38, 20, 90, 92), radius=12, fill=(32, 91, 214, 255))
        draw.rectangle((43, 82, 55, 116), fill=(24, 43, 89, 255))
        draw.rectangle((73, 82, 85, 116), fill=(24, 43, 89, 255))
        draw.rectangle((34, 108, 55, 119), fill=(250, 250, 250, 255))

        cleaned = _remove_connected_background(image)

        self.assertEqual(cleaned.getpixel((64, 110))[3], 0)
        self.assertEqual(cleaned.getpixel((8, 8))[3], 0)
        self.assertEqual(cleaned.getpixel((20, 60))[3], 0)
        self.assertEqual(cleaned.getpixel((64, 12))[3], 0)
        self.assertEqual(cleaned.getpixel((45, 112))[3], 255)

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
