"""Creation-project persistence and approval packaging."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path

from PIL import Image

from .idle import build_idle_frames, normalize_anchor
from .models import CharacterSpec, CreationProject, ProjectStage
from .photo import dominant_palette, validate_photo
from .providers import GenerationProvider


def create_project(
    source: str | Path,
    workspace_root: str | Path,
    *,
    name: str,
    rights_confirmed: bool,
) -> CreationProject:
    if not rights_confirmed:
        raise ValueError("必须确认拥有照片及人物形象的使用授权")
    report = validate_photo(source)
    if not report.accepted:
        raise ValueError("；".join(report.errors))

    project_id = f"{_slug(name)}-{uuid.uuid4().hex[:8]}"
    root = Path(workspace_root).resolve() / project_id
    source_dir = root / "source"
    source_dir.mkdir(parents=True, exist_ok=False)
    suffix = Path(source).suffix.lower() or ".png"
    source_copy = source_dir / f"source{suffix}"
    shutil.copy2(source, source_copy)

    palette = dominant_palette(source_copy)
    spec = CharacterSpec(
        name=name.strip() or "未命名桌宠",
        primary_color=palette[0],
        secondary_color=palette[1],
        accent_color=palette[2],
    )
    project = CreationProject(
        project_id=project_id,
        root=root,
        source_image=source_copy,
        stage=ProjectStage.DRAFT,
        rights_confirmed=True,
        photo_report=report,
        character_spec=spec,
    )
    save_project(project)
    _write_generation_brief(project)
    return project


def generate_candidates(
    project: CreationProject, provider: GenerationProvider
) -> CreationProject:
    candidates = provider.generate_candidates(
        project.source_image, project.character_spec, project.root / "candidates"
    )
    if len(candidates) < 2:
        raise ValueError("候选方案至少需要两个")
    project.candidate_files = candidates
    project.stage = ProjectStage.CANDIDATES_READY
    save_project(project)
    return project


def approve_candidate(
    project: CreationProject,
    provider: GenerationProvider,
    selected_index: int,
    destination: str | Path,
) -> Path:
    if project.stage is not ProjectStage.CANDIDATES_READY:
        raise ValueError("候选方案尚未生成")
    if not 0 <= selected_index < len(project.candidate_files):
        raise IndexError("候选方案序号无效")

    target = Path(destination).resolve()
    if target.exists():
        raise FileExistsError(f"目标角色目录已存在：{target}")
    target.mkdir(parents=True)
    selected = project.candidate_files[selected_index]
    anchor = normalize_anchor(selected, target / "preview.png")
    idle_frames = build_idle_frames(anchor, target / "idle")
    pose_sheet = provider.generate_pose_sheet(
        selected, project.character_spec, target / "pose_sheet.png"
    )

    fallback_dir = target / "m2_fallback"
    fallback_dir.mkdir()
    for state in ("hover", "loading", "working"):
        shutil.copy2(anchor, fallback_dir / f"{state}.png")

    manifest = _build_manifest(project, idle_frames)
    manifest_path = target / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (target / "character_spec.json").write_text(
        json.dumps(asdict(project.character_spec), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (target / "approval.json").write_text(
        json.dumps(
            {
                "review_gate": 1,
                "approved": True,
                "selected_candidate": selected_index,
                "source_project": project.project_id,
                "checks": ["身份相似度", "形象喜好", "允许继续制作动作"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    project.selected_candidate = selected_index
    project.pose_sheet = pose_sheet
    project.approved_manifest = manifest_path
    project.stage = ProjectStage.APPROVED
    save_project(project)
    return manifest_path


def save_project(project: CreationProject) -> None:
    project.root.mkdir(parents=True, exist_ok=True)
    (project.root / "project.json").write_text(
        json.dumps(project.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (project.root / "character_spec.json").write_text(
        json.dumps(asdict(project.character_spec), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_generation_brief(project: CreationProject) -> None:
    spec = project.character_spec
    content = f"""# {spec.name} 角色生成简报

- 输入图片：`{project.source_image.name}`
- 风格：{spec.style}
- 比例：{spec.proportions}
- 服装：{spec.outfit}
- 主色：{spec.primary_color}
- 辅色：{spec.secondary_color}
- 强调色：{spec.accent_color}
- 工作道具：悬浮终端

## 不得变化

{chr(10).join(f'- {item}' for item in spec.forbidden_changes)}
"""
    (project.root / "generation_brief.md").write_text(content, encoding="utf-8")


def _build_manifest(project: CreationProject, idle_frames: list[Path]) -> dict[str, object]:
    frames = [
        {"file": f"idle/{frame.name}", "duration_ms": 200} for frame in idle_frames
    ]
    return {
        "schema_version": 1,
        "pet_id": project.project_id,
        "name": project.character_spec.name,
        "canvas": [512, 512],
        "display_size": [280, 280],
        "anchor": [256, 492],
        "hitbox": [61, 30, 390, 462],
        "default_facing": "right",
        "m2_status": "idle-approved; other states use static fallback",
        "animations": {
            "idle": {
                "loop": True,
                "interruptible_frames": [0, 6],
                "frames": frames,
            },
            **{
                state: {
                    "loop": True,
                    "interruptible_frames": [0],
                    "frames": [
                        {"file": f"m2_fallback/{state}.png", "duration_ms": 800}
                    ],
                }
                for state in ("hover", "loading", "working")
            },
        },
    }


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "pet"
