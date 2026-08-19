"""Serializable data models for a character creation project."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ProjectStage(str, Enum):
    DRAFT = "draft"
    CANDIDATES_READY = "candidates_ready"
    APPROVED = "approved"


@dataclass(frozen=True)
class PhotoReport:
    width: int
    height: int
    format: str
    brightness: float
    edge_energy: float
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return not self.errors


@dataclass
class CharacterSpec:
    name: str
    subject_type: str = "person"
    proportions: str = "2.7-head chibi"
    style: str = "anime chibi, crisp outline, restrained cel shading"
    hair: str = "根据照片保留，待确认"
    eyes: str = "根据照片保留，待确认"
    outfit: str = "忠于照片；信息不足时使用简洁主题服装"
    accessory: str = "仅保留照片中的显著配件"
    primary_color: str = "#6878E8"
    secondary_color: str = "#27324A"
    accent_color: str = "#72E2D1"
    working_prop: str = "floating_terminal"
    notes: str = ""
    locked_traits: list[str] = field(default_factory=list)
    forbidden_changes: list[str] = field(
        default_factory=lambda: [
            "改变发长或发色",
            "改变瞳色",
            "替换主要服装",
            "增加未确认的帽子或大型配件",
        ]
    )


@dataclass
class CreationProject:
    project_id: str
    root: Path
    source_image: Path
    stage: ProjectStage
    rights_confirmed: bool
    photo_report: PhotoReport
    character_spec: CharacterSpec
    candidate_files: list[Path] = field(default_factory=list)
    selected_candidate: int | None = None
    pose_sheet: Path | None = None
    approved_manifest: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["root"] = str(self.root)
        result["source_image"] = str(self.source_image)
        result["stage"] = self.stage.value
        result["candidate_files"] = [str(item) for item in self.candidate_files]
        result["pose_sheet"] = str(self.pose_sheet) if self.pose_sheet else None
        result["approved_manifest"] = (
            str(self.approved_manifest) if self.approved_manifest else None
        )
        return result
