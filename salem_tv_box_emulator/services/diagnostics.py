"""Read-only snapshots. Window geometry does not prove rendered viewport coverage."""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict

from .. import __app_name__, __version__
from ..android_backend import EmulatorController
from ..windows_embed import WindowRect, list_child_windows, list_emulator_windows
from .tv_mode import TVMode
from .compatibility import windows_info
from .setup_engine import setup_summary, package_revision
from .toolchain import load_manifest
from .support import sanitize


def area(rect: WindowRect) -> int:
    return max(0, rect.width) * max(0, rect.height)


def collect_diagnostics(controller: EmulatorController, mode: TVMode, hypervisor: str) -> str:
    launch = controller.launch_info
    candidates = list_emulator_windows(launch.pid if launch else None, launch.avd_name if launch else None)
    selected = next((c for c in candidates if c.selectable), None)
    hwnd = mode.state.hwnd if mode.state else (selected.hwnd if selected else None)
    children = list_child_windows(hwnd)
    top = mode.state.fullscreen_rect if mode.state else (selected.rect if selected else None)
    target = mode.state.monitor_rect if mode.state else top
    toolbar = next((c for c in children if c.visible and "toolbar" in f"{c.title} {c.class_name}".lower()), None)
    surfaces = [c for c in children if c.visible and c != toolbar and top and area(c.rect) >= area(top) * 0.05]
    surface = max(surfaces, key=lambda c: area(c.rect), default=None)
    viewport = {
        "top_level_rect": asdict(top) if top else None,
        "render_candidate": asdict(surface) if surface else None,
        "toolbar_candidate": asdict(toolbar) if toolbar else None,
        "candidate_fill_percent": round(100 * area(surface.rect) / area(target), 2) if surface and target and area(target) else None,
        "note": "Candidate geometry only. Qt may render without a child HWND; content coverage is unverified.",
    }
    tree = [f"Main Emulator Window hwnd={hwnd}"]
    for child in children:
        tree.append(f"{'  ' * child.depth}+- hwnd={child.hwnd} parent={child.parent_hwnd} "
                    f"class={child.class_name} visible={child.visible} title={child.title!r} "
                    f"rect={child.rect} style={child.style:#010x} ex_style={child.ex_style:#010x}")
    sections = {
        "Application": f"{__app_name__} v{__version__}",
        "Environment": "\n".join(controller.tools.status_lines()),
        "Windows": json.dumps(asdict(windows_info()), indent=2),
        "Setup status": setup_summary(),
        "Toolchain": json.dumps(load_manifest(), indent=2),
        "Installed packages": json.dumps({name: package_revision(controller.tools.sdk_root, name) if controller.tools.sdk_root else None for name in load_manifest()["packages"]}, indent=2),
        "Free disk GB": str(round(shutil.disk_usage(controller.tools.sdk_root or ".").free / 2**30, 2)),
        "Launch": json.dumps(asdict(launch), indent=2, default=str) if launch else "Not launched",
        "Active emulator serial": controller.device_serial or "Not detected",
        "Session": json.dumps(asdict(controller.session), indent=2, default=lambda value: sorted(value) if isinstance(value, set) else str(value)),
        "Windows virtualization": hypervisor,
        "ADB devices": controller.adb_devices_output(),
        "Latest ADB command output": controller.last_adb_output,
        "TV Mode": json.dumps({"active": mode.active, "message": mode.message, "saved": asdict(mode.state) if mode.state else None,
                              "restored": asdict(mode.restored) if mode.restored else None}, indent=2),
        "Window Candidates": json.dumps([asdict(c) for c in candidates], indent=2),
        "Viewport Analysis": json.dumps(viewport, indent=2),
        "Window Hierarchy": "\n".join(tree),
        "Audio messages": controller.audio_log_tail(),
        "Emulator log": controller.emulator_log_tail(120),
    }
    return sanitize("\n\n".join(f"{title}\n{'=' * len(title)}\n{content}" for title, content in sections.items()))
