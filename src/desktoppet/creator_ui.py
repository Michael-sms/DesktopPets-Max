"""M2 review UI for photo intake, candidate approval and idle preview."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from .creation.models import CreationProject
from .creation.project import approve_candidate, create_project, generate_candidates, save_project
from .creation.providers import BundledSampleProvider, OpenAIImageProvider
from .manifest import load_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_SOURCE = PROJECT_ROOT / "assets" / "pets" / "m2_sample" / "source"
CREATION_ROOT = PROJECT_ROOT / "workspace" / "creation_projects"
GENERATED_ROOT = PROJECT_ROOT / "workspace" / "generated_pets"


class CreationWindow(QWidget):
    def __init__(self, *, demo: bool = False) -> None:
        super().__init__()
        self.project: CreationProject | None = None
        self.provider: BundledSampleProvider | OpenAIImageProvider | None = None
        self.manifest_path: Path | None = None
        self._idle_frames: list[QPixmap] = []
        self._idle_index = 0
        self._pet_windows: list[QWidget] = []

        self.setWindowTitle("DesktopPet — M2 单角色制作")
        self.resize(1060, 760)
        self._build_ui()
        if demo:
            self.source_edit.setText(str(SAMPLE_SOURCE / "character_anchor.png"))
            self.rights_check.setChecked(True)
            self.name_edit.setText("小轨 M2")
            QTimer.singleShot(0, self._analyze)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        title = QLabel("单张照片 → 角色设定 → 候选确认 → Idle 动画")
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        root.addWidget(title)

        intake = QGroupBox("1. 照片与授权")
        intake_layout = QGridLayout(intake)
        self.source_edit = QLineEdit()
        self.source_edit.setReadOnly(True)
        browse = QPushButton("选择照片")
        browse.clicked.connect(self._browse)
        sample = QPushButton("使用内置样例")
        sample.clicked.connect(self._use_sample)
        self.rights_check = QCheckBox("我确认拥有该照片及主体形象的使用授权")
        analyze = QPushButton("分析并建立草稿")
        analyze.clicked.connect(self._analyze)
        self.report_label = QLabel("尚未分析")
        self.report_label.setWordWrap(True)
        intake_layout.addWidget(self.source_edit, 0, 0, 1, 3)
        intake_layout.addWidget(browse, 0, 3)
        intake_layout.addWidget(sample, 0, 4)
        intake_layout.addWidget(self.rights_check, 1, 0, 1, 3)
        intake_layout.addWidget(analyze, 1, 3, 1, 2)
        intake_layout.addWidget(self.report_label, 2, 0, 1, 5)
        root.addWidget(intake)

        middle = QHBoxLayout()
        spec_box = QGroupBox("2. 角色规格草稿")
        spec_form = QFormLayout(spec_box)
        self.name_edit = QLineEdit("我的桌宠")
        self.hair_edit = QLineEdit("根据照片保留，待确认")
        self.eyes_edit = QLineEdit("根据照片保留，待确认")
        self.outfit_edit = QLineEdit("忠于照片；信息不足时使用简洁主题服装")
        self.notes_edit = QLineEdit()
        self.palette_label = QLabel("—")
        spec_form.addRow("名称", self.name_edit)
        spec_form.addRow("发型", self.hair_edit)
        spec_form.addRow("眼睛", self.eyes_edit)
        spec_form.addRow("服装", self.outfit_edit)
        spec_form.addRow("补充说明", self.notes_edit)
        spec_form.addRow("照片提取色板", self.palette_label)
        spec_form.addRow("工作道具", QLabel("悬浮终端（已锁定）"))
        self.generate_button = QPushButton("生成 3 个候选方案")
        self.generate_button.setEnabled(False)
        self.generate_button.clicked.connect(self._generate)
        spec_form.addRow(self.generate_button)
        middle.addWidget(spec_box, 2)

        pose_box = QGroupBox("关键姿势表")
        pose_layout = QVBoxLayout(pose_box)
        self.pose_label = QLabel("确认候选后生成")
        self.pose_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pose_label.setMinimumSize(300, 260)
        self.pose_label.setStyleSheet("background:#f1f3f8; color:#61687a;")
        pose_layout.addWidget(self.pose_label)
        middle.addWidget(pose_box, 1)
        root.addLayout(middle)

        candidate_box = QGroupBox("3. 候选确认与审阅关卡 1")
        candidate_layout = QHBoxLayout(candidate_box)
        self.candidate_radios: list[QRadioButton] = []
        self.candidate_labels: list[QLabel] = []
        for index in range(3):
            column = QVBoxLayout()
            image = QLabel(f"候选 {index + 1}")
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image.setFixedSize(190, 190)
            image.setStyleSheet("background:#f1f3f8; border:1px solid #d8dce8;")
            radio = QRadioButton(f"选择方案 {index + 1}")
            radio.setEnabled(False)
            column.addWidget(image)
            column.addWidget(radio, alignment=Qt.AlignmentFlag.AlignCenter)
            candidate_layout.addLayout(column)
            self.candidate_labels.append(image)
            self.candidate_radios.append(radio)

        review_column = QVBoxLayout()
        self.identity_check = QCheckBox("主体辨识特征符合预期")
        self.like_check = QCheckBox("喜欢所选二次元形象")
        self.continue_check = QCheckBox("允许继续制作动作资源")
        self.approve_button = QPushButton("确认并生成 Idle 动画")
        self.approve_button.setEnabled(False)
        self.approve_button.clicked.connect(self._approve)
        self.launch_button = QPushButton("启动已确认桌宠")
        self.launch_button.setEnabled(False)
        self.launch_button.clicked.connect(self._launch_pet)
        self.idle_preview = QLabel("Idle 预览")
        self.idle_preview.setFixedSize(210, 210)
        self.idle_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        review_column.addWidget(self.identity_check)
        review_column.addWidget(self.like_check)
        review_column.addWidget(self.continue_check)
        review_column.addWidget(self.approve_button)
        review_column.addWidget(self.idle_preview)
        review_column.addWidget(self.launch_button)
        candidate_layout.addLayout(review_column)
        root.addWidget(candidate_box)

        self.status_label = QLabel("M2 不会自动上传照片；只有显式配置 AI Provider 后才会联网。")
        self.status_label.setStyleSheet("color:#596174;")
        root.addWidget(self.status_label)

        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._advance_idle_preview)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择照片", "", "Images (*.jpg *.jpeg *.png *.webp)"
        )
        if path:
            self.source_edit.setText(path)

    def _use_sample(self) -> None:
        self.source_edit.setText(str(SAMPLE_SOURCE / "character_anchor.png"))
        self.rights_check.setChecked(True)
        self.name_edit.setText("小轨 M2")

    def _analyze(self) -> None:
        try:
            self.project = create_project(
                self.source_edit.text(),
                CREATION_ROOT,
                name=self.name_edit.text(),
                rights_confirmed=self.rights_check.isChecked(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "无法建立草稿", str(exc))
            return
        report = self.project.photo_report
        messages = [
            f"通过：{report.width}×{report.height} {report.format}",
            f"亮度 {report.brightness}，细节分数 {report.edge_energy}",
        ]
        messages.extend(f"提示：{item}" for item in report.warnings)
        self.report_label.setText(" ｜ ".join(messages))
        spec = self.project.character_spec
        self.palette_label.setText(
            f"{spec.primary_color}  {spec.secondary_color}  {spec.accent_color}"
        )
        self.generate_button.setEnabled(True)
        self.status_label.setText(f"草稿已保存：{self.project.root}")

    def _select_provider(self):
        source = Path(self.source_edit.text()).resolve()
        if source == (SAMPLE_SOURCE / "character_anchor.png").resolve():
            return BundledSampleProvider(
                SAMPLE_SOURCE / "character_anchor.png", SAMPLE_SOURCE / "pose_sheet.png"
            )
        if os.environ.get("OPENAI_API_KEY") and importlib.util.find_spec("openai"):
            return OpenAIImageProvider()
        raise RuntimeError(
            "真实照片草稿已保存，但尚未配置图像生成服务。请安装 AI 可选依赖并在本机设置 "
            "OPENAI_API_KEY，或先用内置样例审阅完整流程。"
        )

    def _sync_spec(self) -> None:
        assert self.project is not None
        spec = self.project.character_spec
        spec.name = self.name_edit.text().strip() or "未命名桌宠"
        spec.hair = self.hair_edit.text().strip()
        spec.eyes = self.eyes_edit.text().strip()
        spec.outfit = self.outfit_edit.text().strip()
        spec.notes = self.notes_edit.text().strip()
        spec.locked_traits = [spec.hair, spec.eyes, spec.outfit]
        save_project(self.project)

    def _generate(self) -> None:
        if self.project is None:
            return
        self._sync_spec()
        try:
            self.provider = self._select_provider()
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            generate_candidates(self.project, self.provider)
        except Exception as exc:
            QMessageBox.information(self, "候选方案未生成", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        for index, path in enumerate(self.project.candidate_files[:3]):
            pixmap = QPixmap(str(path)).scaled(
                184,
                184,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.candidate_labels[index].setPixmap(pixmap)
            self.candidate_radios[index].setEnabled(True)
        self.candidate_radios[1].setChecked(True)
        self.approve_button.setEnabled(True)
        self.status_label.setText("候选已生成；请完成三项人工确认。")

    def _approve(self) -> None:
        if self.project is None or self.provider is None:
            return
        if not all(
            check.isChecked()
            for check in (self.identity_check, self.like_check, self.continue_check)
        ):
            QMessageBox.warning(self, "尚未完成审阅", "请确认全部三项审阅条件。")
            return
        selected = next(
            (index for index, radio in enumerate(self.candidate_radios) if radio.isChecked()),
            -1,
        )
        if selected < 0:
            QMessageBox.warning(self, "未选择方案", "请选择一个候选方案。")
            return
        try:
            destination = GENERATED_ROOT / self.project.project_id
            self.manifest_path = approve_candidate(
                self.project, self.provider, selected, destination
            )
        except Exception as exc:
            QMessageBox.critical(self, "生成失败", str(exc))
            return
        self._load_idle_preview()
        pose = QPixmap(str(destination / "pose_sheet.png")).scaled(
            self.pose_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.pose_label.setPixmap(pose)
        self.launch_button.setEnabled(True)
        self.status_label.setText(f"审阅关卡 1 已通过，角色资源位于：{destination}")

    def _load_idle_preview(self) -> None:
        assert self.manifest_path is not None
        manifest = load_manifest(self.manifest_path)
        self._idle_frames = [
            QPixmap(str(frame.file)).scaled(
                200,
                200,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            for frame in manifest.animations["idle"].frames
        ]
        self._idle_index = 0
        self.preview_timer.start(200)

    def _advance_idle_preview(self) -> None:
        if not self._idle_frames:
            return
        self.idle_preview.setPixmap(self._idle_frames[self._idle_index])
        self._idle_index = (self._idle_index + 1) % len(self._idle_frames)

    def _launch_pet(self) -> None:
        if self.manifest_path is None:
            return
        from .app import PetWindow

        window = PetWindow(load_manifest(self.manifest_path))
        window.show()
        self._pet_windows.append(window)
