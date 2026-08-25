"""PySide6 desktop window and command-line entry point."""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import math
import os
import random
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QCursor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPixmap,
    QScreen,
    QShowEvent,
)
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QWidget

from .focus_timer import ReliableTimer, TimerStatus
from .manifest import ManifestError, PetManifest, load_manifest
from .settings import SettingsStore, relative_position, restored_position
from .state_machine import PetEvent, PetState, PetStateMachine


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = PROJECT_ROOT / "assets" / "pets" / "m6_sample" / "manifest.json"

STATE_LABELS = {
    PetState.IDLE: "静置",
    PetState.HOVER: "发现你了",
    PetState.LOADING: "加载中",
    PetState.WORKING: "工作中",
}
RENDER_INTERVAL_MS = 83


class PetWindow(QWidget):
    def __init__(
        self,
        manifest: PetManifest,
        *,
        demo: bool = False,
        debug: bool = False,
        settings: SettingsStore | None = None,
        focus_timer: ReliableTimer | None = None,
    ) -> None:
        super().__init__()
        self.manifest = manifest
        self._settings_store = settings or SettingsStore.default()
        self._preferences = self._settings_store.load()
        self._debug_badge = debug or self._preferences.debug_badge
        timer_path = (
            self._settings_store.path.with_name("focus_timer.json")
            if self._settings_store.path is not None
            else None
        )
        self.focus_timer = focus_timer or ReliableTimer(timer_path)
        self._screen_signal_connected = False
        self.machine = PetStateMachine()
        self.machine.subscribe(self._on_state_changed)
        self._pixmaps = self._load_pixmaps()
        self._idle_variants = tuple(
            name for name in manifest.animations if name.startswith("idle_variant_")
        )
        self._active_animation_name = PetState.IDLE.value
        self._transition_target: PetState | None = None
        self._frame_index = 0
        self._frame_elapsed_ms = 0
        self._phase = 0.0
        self._drag_origin: QPoint | None = None
        self._hover_token = 0

        self.setWindowTitle(f"Desktop Pet — {manifest.name}")
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self._preferences.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.resize(*manifest.display_size)
        self._restore_position()

        self._animation_timer = QTimer(self)
        self._animation_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._animation_timer.timeout.connect(self._tick)
        self._schedule_frame()
        self._idle_variant_timer = QTimer(self)
        self._idle_variant_timer.setSingleShot(True)
        self._idle_variant_timer.timeout.connect(self._play_idle_variant)
        self._schedule_idle_variant()
        self._focus_timer_tick = QTimer(self)
        self._focus_timer_tick.setInterval(250)
        self._focus_timer_tick.timeout.connect(self._refresh_focus_timer)
        self._focus_timer_tick.start()

        if demo:
            self._demo_states = iter(
                [
                    PetState.HOVER,
                    PetState.IDLE,
                    PetState.LOADING,
                    PetState.WORKING,
                    PetState.IDLE,
                ]
            )
            self._demo_timer = QTimer(self)
            self._demo_timer.timeout.connect(self._advance_demo)
            self._demo_timer.start(1800)

    @property
    def active_animation_name(self) -> str:
        return self._active_animation_name

    @property
    def render_interval_ms(self) -> int:
        return RENDER_INTERVAL_MS

    @property
    def timer_display_text(self) -> str:
        return self.focus_timer.display_text()

    def _load_pixmaps(self) -> dict[str, tuple[QPixmap, ...]]:
        result: dict[str, tuple[QPixmap, ...]] = {}
        for name, animation in self.manifest.animations.items():
            frames: list[QPixmap] = []
            for frame in animation.frames:
                pixmap = QPixmap(str(frame.file))
                if pixmap.isNull():
                    raise ManifestError(f"cannot render frame: {frame.file}")
                frames.append(pixmap)
            result[name] = tuple(frames)
        return result

    def _restore_position(self) -> None:
        screens = QApplication.screens()
        screen = next(
            (item for item in screens if item.name() == self._preferences.screen_name),
            QApplication.primaryScreen(),
        )
        if screen is None:
            return
        area = screen.availableGeometry()
        x, y = restored_position(
            (self._preferences.relative_x, self._preferences.relative_y),
            (self.width(), self.height()),
            (area.x(), area.y(), area.width(), area.height()),
        )
        self.move(x, y)

    def _save_preferences(self) -> None:
        screen = QApplication.screenAt(self.frameGeometry().center()) or self.screen()
        if screen is None:
            return
        area = screen.availableGeometry()
        relative_x, relative_y = relative_position(
            (self.x(), self.y()),
            (self.width(), self.height()),
            (area.x(), area.y(), area.width(), area.height()),
        )
        self._preferences = replace(
            self._preferences,
            screen_name=screen.name(),
            relative_x=relative_x,
            relative_y=relative_y,
        )
        self._settings_store.save(self._preferences)

    def _clamp_to_screen(self, screen: QScreen) -> None:
        area = screen.availableGeometry()
        x = min(
            max(self.x(), area.left()),
            max(area.left(), area.right() - self.width() + 1),
        )
        y = min(
            max(self.y(), area.top()),
            max(area.top(), area.bottom() - self.height() + 1),
        )
        self.move(x, y)

    def _schedule_frame(self) -> None:
        self._animation_timer.start(RENDER_INTERVAL_MS)

    def _tick(self) -> None:
        self._phase = (
            self._phase
            + math.tau * self._animation_timer.interval() / 2_400
        ) % math.tau
        animation = self.manifest.animations[self._active_animation_name]
        self._frame_elapsed_ms += self._animation_timer.interval()
        duration = animation.frames[self._frame_index].duration_ms
        if self._frame_elapsed_ms >= duration:
            self._frame_elapsed_ms %= duration
            if self._frame_index + 1 < len(animation.frames):
                self._frame_index += 1
            elif animation.loop:
                self._frame_index = 0
            else:
                self._finish_transition()
        self.update()

    def _on_state_changed(self, previous: PetState, current: PetState) -> None:
        self._idle_variant_timer.stop()
        transition = f"{previous.value}_to_{current.value}"
        if transition in self.manifest.animations:
            self._active_animation_name = transition
            self._transition_target = current
        else:
            self._active_animation_name = current.value
            self._transition_target = None
        self._frame_index = 0
        self._frame_elapsed_ms = 0
        self._phase = 0.0
        self._schedule_frame()
        if current is PetState.IDLE and self._transition_target is None:
            self._schedule_idle_variant()
        self.update()

    def _finish_transition(self) -> None:
        target = self._transition_target or self.machine.state
        self._active_animation_name = target.value
        self._transition_target = None
        self._frame_index = 0
        self._frame_elapsed_ms = 0
        if target is PetState.IDLE:
            self._schedule_idle_variant()

    def _schedule_idle_variant(self) -> None:
        if self._idle_variants and self.machine.state is PetState.IDLE:
            self._idle_variant_timer.start(random.randint(8_000, 20_000))

    def _play_idle_variant(self) -> None:
        if (
            self._idle_variants
            and self.machine.state is PetState.IDLE
            and self._active_animation_name == PetState.IDLE.value
        ):
            self._preview_animation(random.choice(self._idle_variants))

    def _advance_demo(self) -> None:
        try:
            state = next(self._demo_states)
        except StopIteration:
            self._demo_states = iter(
                [
                    PetState.HOVER,
                    PetState.IDLE,
                    PetState.LOADING,
                    PetState.WORKING,
                    PetState.IDLE,
                ]
            )
            state = next(self._demo_states)
        self.machine.force(state)

    def _preview_animation(self, name: str) -> None:
        animation = self.manifest.animations[name]
        if name in {state.value for state in PetState}:
            self.machine.force(PetState(name))
            return
        self._active_animation_name = name
        self._transition_target = None
        self._frame_index = 0
        self._frame_elapsed_ms = 0
        if animation.loop:
            self._schedule_frame()
        self.update()

    def paintEvent(self, event: object) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        pixmap = self._pixmaps[self._active_animation_name][self._frame_index]
        image_rect = QRectF(8, 8, self.width() - 16, self.height() - 16)
        state = self.machine.state
        animation = self.manifest.animations[self._active_animation_name]
        if self._active_animation_name == state.value and len(animation.frames) == 1:
            if state is PetState.IDLE:
                image_rect.adjust(1, 2 + math.sin(self._phase) * 1.5, -1, -2)
            elif state is PetState.HOVER:
                image_rect.translate(0, -3 + math.sin(self._phase) * 1.5)
            elif state is PetState.LOADING:
                image_rect.translate(math.sin(self._phase) * 2, 0)
            elif state is PetState.WORKING:
                image_rect.translate(math.sin(self._phase * 2) * 1.2, 0)
        painter.drawPixmap(image_rect.toRect(), pixmap)

        timer_text = self.timer_display_text
        if timer_text:
            badge = QRectF(42, 10, self.width() - 84, 32)
            painter.setPen(Qt.PenStyle.NoPen)
            colour = QColor(25, 119, 190, 225)
            if self.focus_timer.status is TimerStatus.PAUSED:
                colour = QColor(126, 93, 32, 225)
            elif self.focus_timer.status is TimerStatus.FINISHED:
                colour = QColor(31, 143, 88, 235)
            painter.setBrush(colour)
            painter.drawRoundedRect(badge, 16, 16)
            painter.setPen(QColor("white"))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, timer_text)

        if self._debug_badge:
            label = STATE_LABELS[state]
            badge = QRectF(12, 48 if timer_text else 10, 72, 28)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(22, 25, 38, 205))
            painter.drawRoundedRect(badge, 14, 14)
            painter.setPen(QColor("white"))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, label)

    def interactive_rect(self) -> QRect:
        left, top, width, height = self.manifest.hitbox
        image_width = max(1, self.width() - 16)
        image_height = max(1, self.height() - 16)
        scale_x = image_width / self.manifest.canvas[0]
        scale_y = image_height / self.manifest.canvas[1]
        return QRect(
            round(8 + left * scale_x),
            round(8 + top * scale_y),
            max(1, round(width * scale_x)),
            max(1, round(height * scale_y)),
        )

    def _is_interactive_position(self, position: QPoint) -> bool:
        return self.interactive_rect().contains(position)

    def _is_interactive_client_position(
        self, position: QPoint, client_size: tuple[int, int]
    ) -> bool:
        """Map native physical client pixels to Qt's device-independent space."""

        client_width, client_height = client_size
        if client_width <= 0 or client_height <= 0:
            return False
        logical = QPoint(
            round(position.x() * self.width() / client_width),
            round(position.y() * self.height() / client_height),
        )
        return self._is_interactive_position(logical)

    def nativeEvent(self, event_type: object, message: int) -> tuple[bool, int]:
        if sys.platform == "win32":
            try:
                native = ctypes.wintypes.MSG.from_address(int(message))
                if native.message == 0x0084:  # WM_NCHITTEST
                    point = ctypes.wintypes.POINT(
                        ctypes.c_short(native.lParam & 0xFFFF).value,
                        ctypes.c_short((native.lParam >> 16) & 0xFFFF).value,
                    )
                    client = ctypes.wintypes.RECT()
                    user32 = ctypes.WinDLL("user32", use_last_error=True)
                    user32.ScreenToClient.argtypes = (
                        ctypes.wintypes.HWND,
                        ctypes.POINTER(ctypes.wintypes.POINT),
                    )
                    user32.ScreenToClient.restype = ctypes.wintypes.BOOL
                    user32.GetClientRect.argtypes = (
                        ctypes.wintypes.HWND,
                        ctypes.POINTER(ctypes.wintypes.RECT),
                    )
                    user32.GetClientRect.restype = ctypes.wintypes.BOOL
                    if not user32.ScreenToClient(native.hWnd, ctypes.byref(point)):
                        return super().nativeEvent(event_type, message)
                    if not user32.GetClientRect(native.hWnd, ctypes.byref(client)):
                        return super().nativeEvent(event_type, message)
                    client_size = (client.right - client.left, client.bottom - client.top)
                    if not self._is_interactive_client_position(
                        QPoint(point.x, point.y), client_size
                    ):
                        return True, -1  # HTTRANSPARENT
                    return True, 1  # HTCLIENT
            except (AttributeError, TypeError, ValueError):
                pass
        return super().nativeEvent(event_type, message)

    def enterEvent(self, event: object) -> None:
        del event
        self._hover_token += 1
        token = self._hover_token

        def activate_hover() -> None:
            local_cursor = self.mapFromGlobal(QCursor.pos())
            if (
                token == self._hover_token
                and self.underMouse()
                and self._is_interactive_position(local_cursor)
            ):
                self.machine.dispatch(PetEvent.HOVER_ENTER)

        QTimer.singleShot(120, activate_hover)

    def leaveEvent(self, event: object) -> None:
        del event
        self._hover_token += 1
        token = self._hover_token

        def deactivate_hover() -> None:
            if token == self._hover_token and not self.underMouse():
                self.machine.dispatch(PetEvent.HOVER_LEAVE)

        QTimer.singleShot(200, deactivate_hover)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self._is_interactive_position(event.position().toPoint()):
            event.ignore()
            return
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
            self._save_preferences()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        handle = self.windowHandle()
        if handle is not None and not self._screen_signal_connected:
            handle.screenChanged.connect(self._on_screen_changed)
            self._screen_signal_connected = True

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_preferences()
        super().closeEvent(event)

    def _on_screen_changed(self, screen: QScreen) -> None:
        self._clamp_to_screen(screen)
        self._save_preferences()

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
        timer_menu = menu.addMenu("计时器")
        status_text = self.timer_display_text or "尚未开始"
        status_action = QAction(status_text, timer_menu)
        status_action.setEnabled(False)
        timer_menu.addAction(status_action)
        timer_menu.addSeparator()
        start_action = QAction("开始 25 分钟专注", timer_menu)
        start_action.triggered.connect(
            lambda checked=False: self._start_focus_timer(25)
        )
        timer_menu.addAction(start_action)
        custom_action = QAction("自定义时长…", timer_menu)
        custom_action.triggered.connect(self._start_custom_focus_timer)
        timer_menu.addAction(custom_action)
        timer_menu.addSeparator()
        pause_action = QAction("暂停", timer_menu)
        pause_action.setEnabled(self.focus_timer.status is TimerStatus.RUNNING)
        pause_action.triggered.connect(self._pause_focus_timer)
        timer_menu.addAction(pause_action)
        resume_action = QAction("继续", timer_menu)
        resume_action.setEnabled(self.focus_timer.status is TimerStatus.PAUSED)
        resume_action.triggered.connect(self._resume_focus_timer)
        timer_menu.addAction(resume_action)
        stop_action = QAction("停止并清除", timer_menu)
        stop_action.setEnabled(self.focus_timer.status is not TimerStatus.IDLE)
        stop_action.triggered.connect(self._stop_focus_timer)
        timer_menu.addAction(stop_action)
        menu.addSeparator()
        state_menu = menu.addMenu("状态")
        for state in PetState:
            action = QAction(STATE_LABELS[state], state_menu)
            action.setCheckable(True)
            action.setChecked(state is self.machine.state)
            action.triggered.connect(lambda checked=False, value=state: self.machine.force(value))
            state_menu.addAction(action)
        transition_menu = menu.addMenu("过渡预览")
        idle_menu = menu.addMenu("随机 Idle 动作")
        for name, animation in self.manifest.animations.items():
            if animation.loop:
                continue
            parent_menu = idle_menu if name.startswith("idle_variant_") else transition_menu
            action = QAction(name, parent_menu)
            action.triggered.connect(lambda checked=False, value=name: self._preview_animation(value))
            parent_menu.addAction(action)
        event_menu = menu.addMenu("任务结束事件")
        for label, event in (
            ("完成", PetEvent.FINISHED),
            ("取消", PetEvent.CANCELLED),
            ("失败", PetEvent.FAILED),
            ("超时", PetEvent.TIMED_OUT),
        ):
            action = QAction(label, event_menu)
            action.triggered.connect(lambda checked=False, value=event: self.machine.dispatch(value))
            event_menu.addAction(action)
        menu.addSeparator()
        badge_action = QAction("显示调试状态标签", menu)
        badge_action.setCheckable(True)
        badge_action.setChecked(self._debug_badge)
        badge_action.triggered.connect(self._toggle_debug_badge)
        menu.addAction(badge_action)
        top_action = QAction("窗口置顶", menu)
        top_action.setCheckable(True)
        top_action.setChecked(self._preferences.always_on_top)
        top_action.triggered.connect(self._toggle_always_on_top)
        menu.addAction(top_action)
        menu.addSeparator()
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(quit_action)
        menu.exec(position)

    def _start_focus_timer(self, minutes: int) -> None:
        self.focus_timer.start(minutes * 60, label="专注")
        self.update()

    def _start_custom_focus_timer(self) -> None:
        minutes, accepted = QInputDialog.getInt(
            self,
            "自定义专注时长",
            "分钟数：",
            25,
            1,
            480,
            1,
        )
        if accepted:
            self._start_focus_timer(minutes)

    def _pause_focus_timer(self) -> None:
        self.focus_timer.pause()
        self.update()

    def _resume_focus_timer(self) -> None:
        self.focus_timer.resume()
        self.update()

    def _stop_focus_timer(self) -> None:
        self.focus_timer.stop()
        self.update()

    def _refresh_focus_timer(self) -> None:
        self.focus_timer.refresh()
        if self.focus_timer.status is not TimerStatus.IDLE:
            self.update()

    def _toggle_debug_badge(self, enabled: bool) -> None:
        self._debug_badge = enabled
        self._preferences = replace(self._preferences, debug_badge=enabled)
        self._save_preferences()
        self.update()

    def _toggle_always_on_top(self, enabled: bool) -> None:
        self._preferences = replace(self._preferences, always_on_top=enabled)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.show()
        self._save_preferences()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Desktop pet prototype")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--demo", action="store_true", help="cycle through all states")
    parser.add_argument("--debug", action="store_true", help="show the state badge")
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
    parser.add_argument(
        "--soak-test", action="store_true", help="run performance and stability sampling"
    )
    parser.add_argument(
        "--soak-seconds", type=float, default=7200, help="soak duration; default is two hours"
    )
    parser.add_argument(
        "--soak-report",
        type=Path,
        default=PROJECT_ROOT / "workspace" / "m5_reports" / "soak.json",
    )
    return parser


def load_runtime_manifest(
    requested: str | Path, *, fallback: str | Path = DEFAULT_MANIFEST
) -> tuple[PetManifest, str | None]:
    requested_path = Path(requested).resolve()
    fallback_path = Path(fallback).resolve()
    try:
        return load_manifest(requested_path), None
    except ManifestError as exc:
        if requested_path == fallback_path:
            raise
        manifest = load_manifest(fallback_path)
        return manifest, f"资源 {requested_path} 无法加载（{exc}），已回退到默认桌宠"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.smoke_test or args.smoke_create:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    if args.create or args.create_demo or args.smoke_create:
        from .creator_ui import CreationWindow

        app = QApplication.instance() or QApplication(sys.argv[:1])
        app.setOrganizationName("DesktopPet")
        app.setApplicationName("DesktopPet")
        window = CreationWindow(demo=args.create_demo)
        window.show()
        if args.smoke_create:
            QTimer.singleShot(350, app.quit)
        return app.exec()

    if args.validate:
        try:
            manifest = load_manifest(args.manifest)
        except ManifestError as exc:
            print(f"Manifest error: {exc}", file=sys.stderr)
            return 2
        print(
            f"OK: {manifest.pet_id} ({len(manifest.animations)} animations, "
            f"{sum(len(item.frames) for item in manifest.animations.values())} frames)"
        )
        return 0

    try:
        manifest, warning = load_runtime_manifest(args.manifest)
    except ManifestError as exc:
        print(f"Manifest error: {exc}", file=sys.stderr)
        return 2
    if warning:
        print(f"Warning: {warning}", file=sys.stderr)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setOrganizationName("DesktopPet")
    app.setApplicationName("DesktopPet")
    try:
        window = PetWindow(manifest, demo=args.demo, debug=args.debug)
    except ManifestError as exc:
        if manifest.root == DEFAULT_MANIFEST.resolve().parent:
            print(f"Manifest error: {exc}", file=sys.stderr)
            return 2
        print(f"Warning: 资源帧无法渲染（{exc}），已回退到默认桌宠", file=sys.stderr)
        try:
            window = PetWindow(
                load_manifest(DEFAULT_MANIFEST), demo=args.demo, debug=args.debug
            )
        except ManifestError as fallback_exc:
            print(f"Manifest error: {fallback_exc}", file=sys.stderr)
            return 2
    window.show()
    monitor = None
    if args.soak_test:
        from .acceptance import SoakMonitor

        monitor = SoakMonitor(
            window,
            duration_seconds=args.soak_seconds,
            report_path=args.soak_report,
            finished=app.quit,
        )
    elif args.smoke_test:
        QTimer.singleShot(350, app.quit)
    exit_code = app.exec()
    if monitor is not None:
        if not args.soak_report.is_file():
            print(f"M5 soak report was not created: {args.soak_report}", file=sys.stderr)
            return 3
        import json

        result = json.loads(args.soak_report.read_text(encoding="utf-8"))
        print(
            f"{'OK' if result['passed'] else 'FAILED'}: M5 soak report {args.soak_report} "
            f"({result['duration_seconds']:.1f}s)"
        )
        return exit_code if result["passed"] else 3
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
