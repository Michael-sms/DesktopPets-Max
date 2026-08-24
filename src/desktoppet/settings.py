"""Local, privacy-safe application preferences and screen placement helpers."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtCore import QStandardPaths


@dataclass(frozen=True)
class AppSettings:
    always_on_top: bool = True
    debug_badge: bool = False
    screen_name: str = ""
    relative_x: float = 1.0
    relative_y: float = 1.0


class SettingsStore:
    def __init__(self, path: str | Path | None) -> None:
        self.path = Path(path).resolve() if path is not None else None

    @classmethod
    def default(cls) -> "SettingsStore":
        override = os.environ.get("DESKTOPPET_CONFIG")
        if override:
            return cls(override)
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return cls(None)
        root = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppConfigLocation
        )
        return cls(Path(root) / "settings.json")

    def load(self) -> AppSettings:
        if self.path is None or not self.path.is_file():
            return AppSettings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return AppSettings()
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            return AppSettings()
        return AppSettings(
            always_on_top=_boolean(data.get("always_on_top"), True),
            debug_badge=_boolean(data.get("debug_badge"), False),
            screen_name=_text(data.get("screen_name")),
            relative_x=_ratio(data.get("relative_x"), 1.0),
            relative_y=_ratio(data.get("relative_y"), 1.0),
        )

    def save(self, settings: AppSettings) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"schema_version": 1, **asdict(settings)}
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(self.path)
        except OSError:
            return


def relative_position(
    position: tuple[int, int],
    window_size: tuple[int, int],
    available: tuple[int, int, int, int],
) -> tuple[float, float]:
    left, top, width, height = available
    travel_x = max(1, width - window_size[0])
    travel_y = max(1, height - window_size[1])
    return (
        _clamp((position[0] - left) / travel_x, 0.0, 1.0),
        _clamp((position[1] - top) / travel_y, 0.0, 1.0),
    )


def restored_position(
    relative: tuple[float, float],
    window_size: tuple[int, int],
    available: tuple[int, int, int, int],
) -> tuple[int, int]:
    left, top, width, height = available
    travel_x = max(0, width - window_size[0])
    travel_y = max(0, height - window_size[1])
    return (
        left + round(travel_x * _clamp(relative[0], 0.0, 1.0)),
        top + round(travel_y * _clamp(relative[1], 0.0, 1.0)),
    )


def _ratio(value: object, fallback: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _clamp(float(value), 0.0, 1.0)
    return fallback


def _boolean(value: object, fallback: bool) -> bool:
    return value if isinstance(value, bool) else fallback


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
