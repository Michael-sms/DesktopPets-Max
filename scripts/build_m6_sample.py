"""Build the M6 dynamic transparent-frame sample from generated key-pose sheets."""

import json
from pathlib import Path

from desktoppet.frame_animation import build_frame_animation_pack


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PET_ROOT = PROJECT_ROOT / "assets" / "pets" / "m6_sample"
M3_SPEC = PROJECT_ROOT / "assets" / "pets" / "m3_sample" / "character_spec.json"


if __name__ == "__main__":
    manifest = build_frame_animation_pack(PET_ROOT / "source", PET_ROOT)
    spec = json.loads(M3_SPEC.read_text(encoding="utf-8"))
    spec["status"] = "m6-dynamic-transparent-frames"
    spec["name"] = "小轨 M6 动态版"
    (PET_ROOT / "character_spec.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Built {manifest}")
