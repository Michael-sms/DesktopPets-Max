"""Short real-Windows probe for DPI-aware hit testing, hover and right-click."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import sys
from pathlib import Path

from PySide6.QtCore import QEventLoop, QPoint, QTimer
from PySide6.QtWidgets import QApplication

from desktoppet.app import DEFAULT_MANIFEST, PetWindow
from desktoppet.manifest import load_manifest
from desktoppet.settings import SettingsStore
from desktoppet.state_machine import PetState


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WM_NCHITTEST = 0x0084
HTTRANSPARENT = -1
HTCLIENT = 1
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
MK_RBUTTON = 0x0002


class ProbeWindow(PetWindow):
    def __init__(self) -> None:
        self.menu_requested = False
        super().__init__(load_manifest(DEFAULT_MANIFEST), debug=True, settings=SettingsStore(None))

    def _show_menu(self, position: QPoint) -> None:
        del position
        self.menu_requested = True


def wait(milliseconds: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def main() -> int:
    if sys.platform != "win32":
        print("SKIP: Windows-only interaction probe")
        return 0
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("DesktopPet")
    app.setApplicationName("DesktopPetInteractionProbe")
    window = ProbeWindow()
    window.show()
    wait(150)

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    hwnd = ctypes.wintypes.HWND(int(window.winId()))
    client = ctypes.wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(client))
    inside = ctypes.wintypes.POINT(
        (client.right - client.left) // 2,
        (client.bottom - client.top) // 2,
    )
    client_inside = ctypes.wintypes.POINT(inside.x, inside.y)
    outside = ctypes.wintypes.POINT(1, 1)
    user32.ClientToScreen(hwnd, ctypes.byref(inside))
    user32.ClientToScreen(hwnd, ctypes.byref(outside))
    user32.SendMessageW.restype = ctypes.c_ssize_t
    inside_result = user32.SendMessageW(
        hwnd, WM_NCHITTEST, 0, _point_lparam(inside)
    )
    outside_result = user32.SendMessageW(
        hwnd, WM_NCHITTEST, 0, _point_lparam(outside)
    )

    original = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(original))
    try:
        user32.SetCursorPos(inside.x, inside.y)
        wait(250)
        hover_ok = window.machine.state is PetState.HOVER
        client_lparam = _point_lparam(client_inside)
        user32.PostMessageW(hwnd, WM_RBUTTONDOWN, MK_RBUTTON, client_lparam)
        user32.PostMessageW(hwnd, WM_RBUTTONUP, 0, client_lparam)
        wait(100)
    finally:
        user32.SetCursorPos(original.x, original.y)
        window.close()

    checks = {
        "body_receives_input": inside_result == HTCLIENT,
        "transparent_corner_passes_through": outside_result == HTTRANSPARENT,
        "hover_reaches_state_machine": hover_ok,
        "right_click_reaches_menu": window.menu_requested,
    }
    for name, passed in checks.items():
        print(f"{'OK' if passed else 'FAILED'}: {name}")
    print(f"INFO: inside_hit={inside_result}, outside_hit={outside_result}")
    return 0 if all(checks.values()) else 2


def _point_lparam(point: ctypes.wintypes.POINT) -> int:
    return ((point.y & 0xFFFF) << 16) | (point.x & 0xFFFF)


if __name__ == "__main__":
    raise SystemExit(main())
