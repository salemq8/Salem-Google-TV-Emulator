from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass


if sys.platform == "win32":
    user32 = ctypes.windll.user32
else:
    user32 = None

LONG_PTR = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
if user32:
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = LONG_PTR
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
    user32.SetWindowLongPtrW.restype = LONG_PTR
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = wintypes.LONG
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
    user32.SetWindowLongW.restype = wintypes.LONG
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND


GWL_EXSTYLE = -20
GWL_STYLE = -16
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000
WS_EX_DLGMODALFRAME = 0x00000001
WS_EX_WINDOWEDGE = 0x00000100
WS_EX_CLIENTEDGE = 0x00000200
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_STATICEDGE = 0x00020000
SW_SHOW = 5
SW_RESTORE = 9
SW_MAXIMIZE = 3
HWND_TOP = 0
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
MONITOR_DEFAULTTONEAREST = 2


@dataclass
class EmbeddedWindow:
    hwnd: int
    original_style: int


@dataclass(frozen=True)
class WindowRect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass(frozen=True)
class TVModeState:
    hwnd: int
    title: str
    pid: int
    class_name: str
    style_before: int
    ex_style_before: int
    style_after: int
    ex_style_after: int
    original_rect: WindowRect
    monitor_rect: WindowRect
    fullscreen_rect: WindowRect
    final_rect_matches_monitor: bool
    was_maximized: bool


@dataclass(frozen=True)
class WindowCandidate:
    hwnd: int
    title: str
    pid: int
    class_name: str
    rect: WindowRect
    style: int
    ex_style: int
    visible: bool
    excluded_reason: str
    priority: int

    @property
    def selectable(self) -> bool:
        return not self.excluded_reason


@dataclass(frozen=True)
class ChildWindowInfo:
    hwnd: int
    parent_hwnd: int
    depth: int
    title: str
    class_name: str
    rect: WindowRect
    style: int
    ex_style: int
    visible: bool


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def find_emulator_window(pid: int | None, avd_name: str | None) -> int | None:
    candidates = list_emulator_windows(pid, avd_name)
    selectable = [candidate for candidate in candidates if candidate.selectable]
    selectable.sort(key=lambda candidate: candidate.priority)
    return selectable[0].hwnd if selectable else None


def list_emulator_windows(pid: int | None, avd_name: str | None) -> list[WindowCandidate]:
    if sys.platform != "win32" or not user32:
        return []

    candidates: list[WindowCandidate] = []
    avd_hint = _normalize_title(avd_name or "")

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd: int, _lparam: int) -> bool:
        title = _window_text(hwnd)
        normalized_title = _normalize_title(title)
        window_pid = _window_pid(hwnd)
        is_pid_match = bool(pid and window_pid == pid)
        is_related = "android emulator" in normalized_title or bool(avd_hint and avd_hint in normalized_title) or is_pid_match
        if not is_related:
            return True

        visible = bool(user32.IsWindowVisible(hwnd))
        class_name = _window_class_name(hwnd)
        style = _get_window_long(hwnd, GWL_STYLE)
        ex_style = _get_window_long(hwnd, GWL_EXSTYLE)
        rect = _safe_window_rect(hwnd)
        is_avd_match = bool(avd_hint and avd_hint in normalized_title)
        excluded_reason = _candidate_exclusion_reason(title, visible, ex_style)
        priority = _candidate_priority(normalized_title, is_pid_match, is_avd_match)
        candidates.append(
            WindowCandidate(
                hwnd=hwnd,
                title=title,
                pid=window_pid,
                class_name=class_name,
                rect=rect,
                style=style,
                ex_style=ex_style,
                visible=visible,
                excluded_reason=excluded_reason,
                priority=priority,
            )
        )
        return True

    user32.EnumWindows(enum_proc, 0)
    candidates.sort(key=lambda candidate: (candidate.priority, candidate.excluded_reason != "", candidate.hwnd))
    return candidates


def list_child_windows(hwnd: int | None) -> list[ChildWindowInfo]:
    if sys.platform != "win32" or not user32 or not hwnd:
        return []

    raw_children: dict[int, dict[str, object]] = {}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_child_proc(child_hwnd: int, _lparam: int) -> bool:
        raw_children[int(child_hwnd)] = {
            "parent_hwnd": _parent_hwnd(child_hwnd),
            "title": _window_text(child_hwnd),
            "class_name": _window_class_name(child_hwnd),
            "rect": _safe_window_rect(child_hwnd),
            "style": _get_window_long(child_hwnd, GWL_STYLE),
            "ex_style": _get_window_long(child_hwnd, GWL_EXSTYLE),
            "visible": bool(user32.IsWindowVisible(child_hwnd)),
        }
        return True

    user32.EnumChildWindows(wintypes.HWND(hwnd), enum_child_proc, 0)
    parent_map = {child_hwnd: int(info["parent_hwnd"]) for child_hwnd, info in raw_children.items()}
    children = [
        ChildWindowInfo(
            hwnd=child_hwnd,
            parent_hwnd=parent_map[child_hwnd],
            depth=_child_depth(child_hwnd, int(hwnd), parent_map),
            title=str(info["title"]),
            class_name=str(info["class_name"]),
            rect=info["rect"],  # type: ignore[arg-type]
            style=int(info["style"]),
            ex_style=int(info["ex_style"]),
            visible=bool(info["visible"]),
        )
        for child_hwnd, info in raw_children.items()
    ]
    children.sort(key=lambda child: (child.depth, child.parent_hwnd, child.hwnd))
    return children


def embed(hwnd: int, parent_hwnd: int, width: int, height: int) -> EmbeddedWindow | None:
    if sys.platform != "win32" or not user32 or not hwnd or not parent_hwnd:
        return None

    original_style = _get_window_long(hwnd, GWL_STYLE)
    new_style = original_style
    new_style &= ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)
    new_style |= WS_CHILD | WS_VISIBLE

    user32.SetParent(wintypes.HWND(hwnd), wintypes.HWND(parent_hwnd))
    _set_window_long(hwnd, GWL_STYLE, new_style)
    user32.ShowWindow(wintypes.HWND(hwnd), SW_SHOW)
    resize(hwnd, width, height)
    return EmbeddedWindow(hwnd=hwnd, original_style=original_style)


def resize(hwnd: int, width: int, height: int) -> None:
    if sys.platform != "win32" or not user32 or not hwnd:
        return
    user32.MoveWindow(wintypes.HWND(hwnd), 0, 0, max(1, width), max(1, height), True)


def place_next_to(hwnd: int, app_hwnd: int) -> None:
    if sys.platform != "win32" or not user32 or not hwnd or not app_hwnd:
        return

    rect = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(app_hwnd), ctypes.byref(rect)):
        return

    x = rect.right + 12
    y = rect.top
    width = max(860, rect.right - rect.left)
    height = max(540, rect.bottom - rect.top)
    user32.SetWindowPos(wintypes.HWND(hwnd), None, x, y, width, height, 0)


def bring_to_front(hwnd: int) -> None:
    if sys.platform != "win32" or not user32 or not hwnd:
        return
    user32.SetForegroundWindow(wintypes.HWND(hwnd))
    user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_TOP), 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)


def is_maximized(hwnd: int) -> bool:
    if sys.platform != "win32" or not user32 or not hwnd:
        return False
    return bool(user32.IsZoomed(wintypes.HWND(hwnd)))


def enter_tv_mode(hwnd: int) -> TVModeState:
    if sys.platform != "win32" or not user32 or not hwnd:
        raise RuntimeError("TV Mode requires a valid Win32 emulator window handle.")
    if not user32.IsWindow(wintypes.HWND(hwnd)):
        raise RuntimeError(f"Window handle is no longer valid: {hwnd}")

    title = get_window_title(hwnd)
    pid = _window_pid(hwnd)
    class_name = _window_class_name(hwnd)
    style_before = _get_window_long(hwnd, GWL_STYLE)
    ex_style_before = _get_window_long(hwnd, GWL_EXSTYLE)
    original_rect = get_window_rect(hwnd)
    monitor_rect = get_monitor_rect(hwnd)
    was_maximized = is_maximized(hwnd)

    new_style = style_before
    new_style &= ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU | WS_CHILD)
    new_style |= WS_POPUP | WS_VISIBLE
    new_ex_style = ex_style_before
    new_ex_style &= ~(WS_EX_DLGMODALFRAME | WS_EX_WINDOWEDGE | WS_EX_CLIENTEDGE | WS_EX_STATICEDGE)

    user32.ShowWindow(wintypes.HWND(hwnd), SW_RESTORE)
    _set_window_long(hwnd, GWL_STYLE, new_style)
    _set_window_long(hwnd, GWL_EXSTYLE, new_ex_style)
    user32.SetWindowPos(
        wintypes.HWND(hwnd),
        wintypes.HWND(HWND_TOP),
        monitor_rect.left,
        monitor_rect.top,
        monitor_rect.width,
        monitor_rect.height,
        SWP_FRAMECHANGED | SWP_SHOWWINDOW,
    )
    bring_to_front(hwnd)

    fullscreen_rect = get_window_rect(hwnd)
    return TVModeState(
        hwnd=hwnd,
        title=title,
        pid=pid,
        class_name=class_name,
        style_before=style_before,
        ex_style_before=ex_style_before,
        style_after=_get_window_long(hwnd, GWL_STYLE),
        ex_style_after=_get_window_long(hwnd, GWL_EXSTYLE),
        original_rect=original_rect,
        monitor_rect=monitor_rect,
        fullscreen_rect=fullscreen_rect,
        final_rect_matches_monitor=_rects_match(fullscreen_rect, monitor_rect),
        was_maximized=was_maximized,
    )


def exit_tv_mode(state: TVModeState) -> WindowRect:
    hwnd = state.hwnd
    if sys.platform != "win32" or not user32 or not hwnd:
        raise RuntimeError("TV Mode restore requires a valid Win32 emulator window handle.")
    if not user32.IsWindow(wintypes.HWND(hwnd)):
        raise RuntimeError(f"Window handle is no longer valid: {hwnd}")

    user32.ShowWindow(wintypes.HWND(hwnd), SW_RESTORE)
    _set_window_long(hwnd, GWL_STYLE, state.style_before)
    _set_window_long(hwnd, GWL_EXSTYLE, state.ex_style_before)
    user32.SetWindowPos(
        wintypes.HWND(hwnd),
        wintypes.HWND(HWND_NOTOPMOST),
        state.original_rect.left,
        state.original_rect.top,
        max(1, state.original_rect.width),
        max(1, state.original_rect.height),
        SWP_FRAMECHANGED | SWP_SHOWWINDOW | SWP_NOACTIVATE,
    )
    if state.was_maximized:
        user32.ShowWindow(wintypes.HWND(hwnd), SW_MAXIMIZE)
        user32.SetWindowPos(
            wintypes.HWND(hwnd),
            wintypes.HWND(HWND_NOTOPMOST),
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
    return get_window_rect(hwnd)


def get_window_title(hwnd: int) -> str:
    if sys.platform != "win32" or not user32 or not hwnd:
        return ""
    return _window_text(hwnd)


def get_window_rect(hwnd: int) -> WindowRect:
    if sys.platform != "win32" or not user32 or not hwnd:
        raise RuntimeError("Cannot read window rect without a valid Win32 window handle.")
    rect = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        raise RuntimeError(f"GetWindowRect failed for hwnd {hwnd}.")
    return _rect_from_win32(rect)


def get_monitor_rect(hwnd: int) -> WindowRect:
    if sys.platform != "win32" or not user32 or not hwnd:
        raise RuntimeError("Cannot read monitor bounds without a valid Win32 window handle.")
    monitor = user32.MonitorFromWindow(wintypes.HWND(hwnd), MONITOR_DEFAULTTONEAREST)
    if not monitor:
        raise RuntimeError(f"MonitorFromWindow failed for hwnd {hwnd}.")
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        raise RuntimeError(f"GetMonitorInfoW failed for hwnd {hwnd}.")
    return _rect_from_win32(info.rcMonitor)


def _candidate_exclusion_reason(title: str, visible: bool, ex_style: int) -> str:
    if not title.strip():
        return "empty title"
    title_lower = title.lower()
    if "extended controls" in title_lower:
        return "extended controls"
    if not visible:
        return "hidden window"
    if ex_style & WS_EX_TOOLWINDOW:
        return "tool/helper window"
    return ""


def _candidate_priority(normalized_title: str, is_pid_match: bool, is_avd_match: bool) -> int:
    if normalized_title.startswith("android emulator - salem") and is_avd_match:
        return 0
    if normalized_title.startswith("android emulator - salem"):
        return 1
    if is_avd_match:
        return 2
    if normalized_title.startswith("android emulator"):
        return 3
    if is_pid_match:
        return 4
    return 5


def _normalize_title(text: str) -> str:
    return text.strip().lower().replace("_", " ")


def _window_pid(hwnd: int) -> int:
    window_pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(window_pid))
    return int(window_pid.value)


def _window_class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    length = user32.GetClassNameW(wintypes.HWND(hwnd), buffer, len(buffer))
    return buffer.value[:length] if length else ""


def _parent_hwnd(hwnd: int) -> int:
    parent = user32.GetParent(wintypes.HWND(hwnd))
    return int(parent or 0)


def _child_depth(hwnd: int, root_hwnd: int, parent_map: dict[int, int]) -> int:
    depth = 0
    current = hwnd
    seen: set[int] = set()
    while current in parent_map and current not in seen:
        seen.add(current)
        parent = parent_map[current]
        if not parent:
            break
        depth += 1
        if parent == root_hwnd:
            return depth
        current = parent
    return max(1, depth)


def _safe_window_rect(hwnd: int) -> WindowRect:
    try:
        return get_window_rect(hwnd)
    except RuntimeError:
        return WindowRect(left=0, top=0, right=0, bottom=0)


def _rects_match(first: WindowRect, second: WindowRect) -> bool:
    return first.left == second.left and first.top == second.top and first.right == second.right and first.bottom == second.bottom


def _window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(wintypes.HWND(hwnd))
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(wintypes.HWND(hwnd), buffer, length + 1)
    return buffer.value


def _get_window_long(hwnd: int, index: int) -> int:
    if hasattr(user32, "GetWindowLongPtrW"):
        return user32.GetWindowLongPtrW(wintypes.HWND(hwnd), index)
    return user32.GetWindowLongW(wintypes.HWND(hwnd), index)


def _set_window_long(hwnd: int, index: int, value: int) -> None:
    if hasattr(user32, "SetWindowLongPtrW"):
        user32.SetWindowLongPtrW(wintypes.HWND(hwnd), index, value)
    else:
        user32.SetWindowLongW(wintypes.HWND(hwnd), index, value)


def _rect_from_win32(rect: wintypes.RECT) -> WindowRect:
    return WindowRect(left=rect.left, top=rect.top, right=rect.right, bottom=rect.bottom)
