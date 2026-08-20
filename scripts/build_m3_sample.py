"""Rebuild the checked-in M3 sample from its approved action anchors."""

from pathlib import Path

from desktoppet.motion import build_action_pack


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PET_ROOT = PROJECT_ROOT / "assets" / "pets" / "m3_sample"


if __name__ == "__main__":
    manifest = build_action_pack(PET_ROOT / "source", PET_ROOT)
    print(f"Built {manifest}")
