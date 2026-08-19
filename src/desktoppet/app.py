"""PySide6 desktop window and command-line entry point."""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QKeyEvent, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from .manifest import ManifestError, PetManifest, load_manifest
from .state_machine import PetEvent, PetState, PetStateMachine


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = PROJECT_ROOT / "assets" / "pets" / "prototype" / "manifest.json"

STATE_LABELS = {
    PetState.IDLE: "静置",
    PetState.HOVER: "发现你了",
    PetState.LOADING: "加载中",
    PetState.WORKING: "工作中",
}
RENDER_INTERVAL_MS = 50


class PetWindow(QWidget):
    def __init__(self, manifest: PetManifest, *, demo: bool = False) -> None:
        super().__init__()
        self.manifest = manifest
        self.machine = PetStateMachine()
        self.machine.subscribe(self._on_state_changed)
        self._pixmaps = self._load_pixmaps()
        self._frame_index = 0
        self._frame_elapsed_ms = 0
        self._phase = 0.0
        self._drag_origin: QPoint | None = None
        self._hover_token = 0

        self.setWindowTitle(f"Desktop Pet — {manifest.name}")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.resize(*manifest.display_size)
        self._move_to_bottom_right()

        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._tick)
        self._schedule_frame()

        if demo:
            self._demo_states = iter(
                [PetState.HOVER, PetState.LOADING, PetState.WORKING, PetState.IDLE]
            )
            self._demo_timer = QTimer(self)
            self._demo_timer.timeout.connect(self._advance_demo)
            self._demo_timer.start(1800)

    def _load_pixmaps(self) -> dict[PetState, tuple[QPixmap, ...]]:
        result: dict[PetState, tuple[QPixmap, ...]] = {}
        for state in PetState:
            frames: list[QPixmap] = []
            for frame in self.manifest.animation_for(state).frames:
                pixmap = QPixmap(str(frame.file))
                if pixmap.isNull():
                    raise ManifestError(f"cannot render frame: {frame.file}")
                frames.append(pixmap)
            result[state] = tuple(frames)
        return result

    def _move_to_bottom_right(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.right() - self.width() - 24, area.bottom() - self.height() - 24)

    def _schedule_frame(self) -> None:
        self._animation_timer.start(RENDER_INTERVAL_MS)

    def _tick(self) -> None:
        self._phase = (self._phase + 0.14) % (math.tau)
        animation = self.manifest.animation_for(self.machine.state)
        self._frame_elapsed_ms += self._animation_timer.interval()
        duration = animation.frames[self._frame_index].duration_ms
        if len(animation.frames) > 1 and self._frame_elapsed_ms >= duration:
            self._frame_index = (self._frame_index + 1) % len(animation.frames)
            self._frame_elapsed_ms = 0
        self.update()

    def _on_state_changed(self, previous: PetState, current: PetState) -> None:
        del previous
        self._frame_index = 0
        self._frame_elapsed_ms = 0
        self._phase = 0.0
        self._schedule_frame()
        self.update()

    def _advance_demo(self) -> None:
        try:
            state = next(self._demo_states)
        except StopIteration:
            self._demo_states = iter(
                [PetState.HOVER, PetState.LOADING, PetState.WORKING, PetState.IDLE]
            )
            state = next(self._demo_states)
        self.machine.force(state)

    def paintEvent(self, event: object) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        pixmap = self._pixmaps[self.machine.state][self._frame_index]
        image_rect = QRectF(8, 8, self.width() - 16, self.height() - 16)
        state = self.machine.state
        animation = self.manifest.animation_for(state)
        if len(animation.frames) == 1:
            if state is PetState.IDLE:
                image_rect.adjust(1, 2 + math.sin(self._phase) * 1.5, -1, -2)
            elif state is PetState.HOVER:
                image_rect.translate(0, -3 + math.sin(self._phase) * 1.5)
            elif state is PetState.LOADING:
                image_rect.translate(math.sin(self._phase) * 2, 0)
            elif state is PetState.WORKING:
                image_rect.translate(math.sin(self._phase * 2) * 1.2, 0)
        painter.drawPixmap(image_rect.toRect(), pixmap)

        label = STATE_LABELS[state]
        badge = QRectF(12, 10, 72, 28)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(22, 25, 38, 205))
        painter.drawRoundedRect(badge, 14, 14)
        painter.setPen(QColor("white"))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, label)

    def enterEvent(self, event: object) -> None:
        del event
        self._hover_token += 1
        token = self._hover_token

        def activate_hover() -> None:
            if token == self._hover_token and self.underMouse():
                self.machine.dispatch(PetEvent.HOVER_ENTER)

        QTimer.singleShot(120, activate_hover)

    def leaveEvent(self, event: object) -> None:
        del event
        self._hover_token += 1
        QTimer.singleShot(200, lambda: self.machine.dispatch(PetEvent.HOVER_LEAVE))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() is Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        elif event.button() is Qt.MouseButton.RightButton:
            self._show_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_origin)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() is Qt.MouseButton.LeftButton:
            self._drag_origin = None

    def keyPressEvent(self, event: QKeyEvent) -> None:
        shortcuts = {
            Qt.Key.Key_1: PetState.IDLE,
            Qt.Key.Key_2: PetState.HOVER,
            Qt.Key.Key_3: PetState.LOADING,
            Qt.Key.Key_4: PetState.WORKING,
        }
        state = shortcuts.get(event.key())
        if state is not None:
            self.machine.force(state)
            event.accept()
            return
        super().keyPressEvent(event)

    def _show_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        for state in PetState:
            action = QAction(STATE_LABELS[state], menu)
            action.setCheckable(True)
            action.setChecked(state is self.machine.state)
            action.triggered.connect(lambda checked=False, value=state: self.machine.force(value))
            menu.addAction(action)
        menu.addSeparator()
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(quit_action)
        menu.exec(position)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Desktop pet prototype")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--demo", action="store_true", help="cycle through all states")
    parser.add_argument("--validate", action="store_true", help="validate assets and exit")
    parser.add_argument(
        "--smoke-test", action="store_true", help="open offscreen and exit automatically"
    )
    parser.add_argument("--create", action="store_true", help="open the M2 creation UI")
    parser.add_argument(
        "--create-demo", action="store_true", help="open creation UI with bundled sample"
    )
    parser.add_argument(
        "--smoke-create", action="store_true", help="open creation UI offscreen and exit"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.smoke_test or args.smoke_create:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    if args.create or args.create_demo or args.smoke_create:
        from .creator_ui import CreationWindow

        app = QApplication.instance() or QApplication(sys.argv[:1])
        window = CreationWindow(demo=args.create_demo)
        window.show()
        if args.smoke_create:
            QTimer.singleShot(350, app.quit)
        return app.exec()

    try:
        manifest = load_manifest(args.manifest)
    except ManifestError as exc:
        print(f"Manifest error: {exc}", file=sys.stderr)
        return 2

    if args.validate:
        print(
            f"OK: {manifest.pet_id} ({len(manifest.animations)} animations, "
            f"{sum(len(item.frames) for item in manifest.animations.values())} frames)"
        )
        return 0

    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = PetWindow(manifest, demo=args.demo)
    window.show()
    if args.smoke_test:
        QTimer.singleShot(350, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
